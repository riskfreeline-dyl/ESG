"""사전 리스크 점검 (pre-trade risk checks).

모든 점검은 '위험을 줄이는 주문은 허용한다'는 원칙을 따른다. 한도를 넘더라도
주문 후 노출이 주문 전보다 작으면 통과시켜, 한도 초과 상태에서도 청산이 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Instrument, Order, OrderType


@dataclass
class RiskLimits:
    capital: float = 1_000_000_000  # 계좌 기본 자본 (원)
    max_order_qty: int = 1_000_000  # 주문당 최대 수량 (외환은 달러, 채권은 액면 단위라 크게 둠 — 실질 통제는 명목금액 한도)
    max_order_notional: float = 500_000_000  # 주문당 최대 명목금액
    price_band_pct: float = 10.0  # 지정가와 현재가의 최대 괴리율 (%)
    max_position_notional: float = 1_000_000_000  # 종목별 최대 포지션 명목금액
    max_gross_exposure: float = 3_000_000_000  # 계좌 총 노출 한도
    max_daily_loss: float = 50_000_000  # 일일 손실 한도
    warn_ratio: float = 0.8  # 한도 대비 이 비율 이상이면 경고 알림
    restricted_symbols: frozenset[str] = field(default_factory=frozenset)
    margin_offset_enabled: bool = True  # 지수선물 ↔ 구성종목 헤지 증거금 상계
    margin_offset_pct: float = 70.0  # 헤지된 선물 증거금 감면율 (%)


@dataclass
class Exposure:
    """미체결 주문이 모두 체결된다고 가정한 최악의 노출."""

    symbol_qty: dict[str, int]
    symbol_notional: dict[str, float]
    gross: float
    margin: float  # 상계 후 순증거금
    margin_gross: float = 0.0  # 상계 전 증거금
    hedge_credit: float = 0.0  # 헤지 상계액


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    usage: float | None = None  # 한도 대비 사용률 (0~1+), 해당 없으면 None


def _fmt(v: float) -> str:
    return f"{v:,.0f}"


def static_checks(order: Order, inst: Instrument | None) -> list[CheckResult]:
    """주문 자체의 형식 검증 (시장 상태와 무관)."""
    results = [
        CheckResult("종목 확인", inst is not None, "등록된 종목" if inst else "등록되지 않은 종목"),
        CheckResult(
            "수량",
            isinstance(order.qty, int) and order.qty > 0,
            f"{order.qty}" if order.qty > 0 else "수량은 1 이상의 정수여야 합니다",
        ),
    ]
    if order.order_type is OrderType.LIMIT:
        if order.limit_price is None or order.limit_price <= 0:
            results.append(CheckResult("지정가", False, "지정가 주문에는 0보다 큰 가격이 필요합니다"))
        elif inst is not None and not inst.is_on_tick(order.limit_price):
            results.append(
                CheckResult("호가단위", False, f"가격이 호가단위 {inst.tick_size}의 배수가 아닙니다")
            )
        else:
            results.append(CheckResult("지정가", True, f"{order.limit_price}"))
    return results


def pre_trade_checks(
    order: Order,
    inst: Instrument,
    mark: float,
    ref_price: float,
    limits: RiskLimits,
    before: Exposure,
    after: Exposure,
    equity: float,
    daily_pnl: float,
    kill_switch: bool,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    increases_risk = after.gross > before.gross + 1e-6

    results.append(
        CheckResult(
            "거래 중지(킬 스위치)",
            not kill_switch,
            "킬 스위치가 켜져 있어 신규 주문이 차단됩니다" if kill_switch else "정상",
        )
    )
    restricted = order.symbol in limits.restricted_symbols
    results.append(
        CheckResult("거래 제한 종목", not restricted, "거래 제한 목록에 있는 종목" if restricted else "해당 없음")
    )

    results.append(
        CheckResult(
            "주문 수량 한도",
            order.qty <= limits.max_order_qty,
            f"{order.qty:,} / {limits.max_order_qty:,}",
            order.qty / limits.max_order_qty,
        )
    )

    notional = order.qty * ref_price * inst.multiplier
    results.append(
        CheckResult(
            "주문 명목금액 한도",
            notional <= limits.max_order_notional,
            f"{_fmt(notional)} / {_fmt(limits.max_order_notional)}",
            notional / limits.max_order_notional,
        )
    )

    if order.order_type is OrderType.LIMIT and order.limit_price:
        dev = abs(order.limit_price / mark - 1) * 100
        results.append(
            CheckResult(
                "가격 괴리율",
                # 저가 옵션처럼 호가단위가 큰 종목은 2틱 이내 괴리를 허용
                dev <= limits.price_band_pct or abs(order.limit_price - mark) <= 2 * inst.tick_size + 1e-9,
                f"현재가 대비 {dev:.2f}% (허용 {limits.price_band_pct:.1f}%)",
                dev / limits.price_band_pct if limits.price_band_pct else None,
            )
        )

    pos_after = after.symbol_notional.get(order.symbol, 0.0)
    pos_before = before.symbol_notional.get(order.symbol, 0.0)
    results.append(
        CheckResult(
            "종목별 포지션 한도",
            pos_after <= limits.max_position_notional or pos_after <= pos_before + 1e-6,
            f"{_fmt(pos_after)} / {_fmt(limits.max_position_notional)}",
            pos_after / limits.max_position_notional,
        )
    )

    results.append(
        CheckResult(
            "총 노출 한도",
            after.gross <= limits.max_gross_exposure or not increases_risk,
            f"{_fmt(after.gross)} / {_fmt(limits.max_gross_exposure)}",
            after.gross / limits.max_gross_exposure,
        )
    )

    results.append(
        CheckResult(
            "증거금",
            after.margin <= equity or after.margin <= before.margin + 1e-6,
            f"필요 {_fmt(after.margin)} / 평가자산 {_fmt(equity)}",
            after.margin / equity if equity > 0 else float("inf"),
        )
    )

    loss = max(-daily_pnl, 0.0) + 0.0  # -0.0 방지
    breached = loss >= limits.max_daily_loss
    results.append(
        CheckResult(
            "일일 손실 한도",
            not (breached and increases_risk),
            f"손실 {_fmt(loss)} / {_fmt(limits.max_daily_loss)}"
            + (" (위험 감소 주문만 허용)" if breached else ""),
            loss / limits.max_daily_loss,
        )
    )
    return results
