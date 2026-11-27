"""바스켓 주문: 구성(수량·비중·파일), 템플릿, 원클릭 실행, 모니터링, 재실행."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import pandas as pd

from .algo import AlgoType
from .models import AlertLevel, OrderStatus, OrderType, Side, TimeInForce

if TYPE_CHECKING:
    from .engine import OMS


class ExecMode(str, Enum):
    MARKET = "시장가"
    AGGRESSIVE = "지정가 · 상대호가"  # 매수는 매도호가(+n틱), 매도는 매수호가(-n틱)
    PASSIVE = "지정가 · 자기호가"  # 매수는 매수호가(-n틱), 매도는 매도호가(+n틱)
    TWAP = "TWAP"
    VWAP = "VWAP"
    POV = "POV"

    @property
    def algo_type(self) -> AlgoType | None:
        return {ExecMode.TWAP: AlgoType.TWAP, ExecMode.VWAP: AlgoType.VWAP, ExecMode.POV: AlgoType.POV}.get(self)


@dataclass
class ExecParams:
    mode: ExecMode = ExecMode.MARKET
    offset_ticks: int = 0
    duration: int = 30
    participation: float = 0.1
    auto_retry: bool = True  # 유동성 부족으로 남은 수량을 다음 틱에 자동 재전송
    max_retries: int = 3


@dataclass
class BasketLine:
    symbol: str
    side: Side
    qty: int
    order_ids: list[str] = field(default_factory=list)
    algo_ids: list[str] = field(default_factory=list)
    retries: int = 0
    error: str = ""


@dataclass
class Basket:
    basket_id: str
    name: str
    lines: list[BasketLine]
    params: ExecParams
    created_at: datetime
    canceled: bool = False
    actor: str = ""  # 바스켓을 실행한 사용자


SIDE_ALIASES = {
    "매수": Side.BUY, "BUY": Side.BUY, "B": Side.BUY, "LONG": Side.BUY, "1": Side.BUY,
    "매도": Side.SELL, "SELL": Side.SELL, "S": Side.SELL, "SHORT": Side.SELL, "-1": Side.SELL,
}


def parse_side(value) -> Side:
    key = str(value).strip().upper()
    if key not in SIDE_ALIASES:
        raise ValueError(f"구분 값 '{value}'을(를) 알 수 없습니다 (매수/매도, BUY/SELL, B/S)")
    return SIDE_ALIASES[key]


def normalize_symbol(value) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else text.upper()


class BasketManager:
    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.baskets: dict[str, Basket] = {}
        self.templates: dict[str, pd.DataFrame] = {}
        self._seq = 0

    # ================= 구성 =================
    def build_lines(
        self, df: pd.DataFrame, by: str = "수량", target_notional: float | None = None
    ) -> tuple[list[BasketLine], list[str]]:
        """표(DataFrame)를 바스켓 라인으로 변환한다.

        필수 열: 종목코드, 구분, 그리고 by="수량"이면 수량 열, by="비중"이면 비중(%) 열.
        비중 방식은 target_notional(목표 명목금액)을 비중대로 나눠 수량을 계산한다(소수점 이하 버림).
        """
        errors: list[str] = []
        cols = {c.strip(): c for c in df.columns.astype(str)}
        for need in ("종목코드", "구분"):
            if need not in cols:
                return [], [f"'{need}' 열이 없습니다"]
        weight_col = next((cols[c] for c in ("비중(%)", "비중") if c in cols), None)
        qty_col = cols.get("수량")
        use_weight = by == "비중"
        if use_weight and weight_col is None:
            return [], ["비중 방식에는 '비중(%)' 열이 필요합니다"]
        if not use_weight and qty_col is None:
            return [], ["수량 방식에는 '수량' 열이 필요합니다"]
        if use_weight and not target_notional:
            return [], ["비중 방식은 목표 명목금액이 필요합니다"]

        rows = df.dropna(subset=[cols["종목코드"]])
        total_w = 0.0
        if use_weight:
            total_w = pd.to_numeric(rows[weight_col], errors="coerce").fillna(0).clip(lower=0).sum()
            if total_w <= 0:
                return [], ["비중 합계가 0입니다"]

        lines: list[BasketLine] = []
        for i, row in rows.iterrows():
            label = f"{i + 1}행"
            symbol = normalize_symbol(row[cols["종목코드"]])
            if symbol not in self.oms.instruments:
                errors.append(f"{label}: 알 수 없는 종목 {symbol}")
                continue
            try:
                side = parse_side(row[cols["구분"]])
            except ValueError as e:
                errors.append(f"{label}: {e}")
                continue
            inst = self.oms.instruments[symbol]
            if use_weight:
                w = float(pd.to_numeric(row[weight_col], errors="coerce") or 0)
                unit = self.oms.market.mark(symbol) * inst.multiplier
                qty = math.floor(target_notional * w / total_w / unit)
                if qty <= 0:
                    errors.append(f"{label}: {symbol} 배정 금액이 1주(계약) 가격보다 작습니다")
                    continue
            else:
                q = pd.to_numeric(row[qty_col], errors="coerce")
                if pd.isna(q) or q <= 0 or q != int(q):
                    errors.append(f"{label}: 수량은 1 이상의 정수여야 합니다")
                    continue
                qty = int(q)
            lines.append(BasketLine(symbol, side, qty))
        return lines, errors

    def preview_frame(self, lines: list[BasketLine]) -> pd.DataFrame:
        rows = []
        for ln in lines:
            inst = self.oms.instruments[ln.symbol]
            mark = self.oms.market.mark(ln.symbol)
            checks = self.oms.preview(ln.symbol, ln.side, OrderType.MARKET, ln.qty)
            failed = [c.name for c in checks if not c.passed]
            rows.append(
                {
                    "종목코드": ln.symbol,
                    "종목명": inst.name,
                    "구분": ln.side.value,
                    "수량": ln.qty,
                    "기준가": mark,
                    "예상 명목": ln.qty * mark * inst.multiplier,
                    "사전 점검": "통과" if not failed else "실패: " + ", ".join(failed),
                }
            )
        return pd.DataFrame(rows)

    # ================= 템플릿 =================
    def save_template(self, name: str, df: pd.DataFrame) -> None:
        self.templates[name] = df.copy()

    def load_template(self, name: str) -> pd.DataFrame:
        return self.templates[name].copy()

    # ================= 실행 =================
    def execute(self, name: str, lines: list[BasketLine], params: ExecParams) -> Basket:
        self._seq += 1
        basket = Basket(
            f"B{self._seq:04d}", name or f"바스켓 {self._seq}", lines, params, datetime.now(), actor=self.oms.actor
        )
        self.baskets[basket.basket_id] = basket
        for ln in lines:
            self._send(basket, ln, ln.qty)
        failed = [ln for ln in lines if ln.error]
        level = AlertLevel.WARNING if failed else AlertLevel.INFO
        self.oms._alert(
            level,
            "바스켓 실행",
            f"{basket.basket_id} {basket.name}: {len(lines)}종목 전송, 거부 {len(failed)}건",
        )
        return basket

    def _price_for(self, line: BasketLine, params: ExecParams) -> float:
        inst = self.oms.instruments[line.symbol]
        q = self.oms.market.quote(line.symbol)
        off = params.offset_ticks * inst.tick_size
        if params.mode is ExecMode.AGGRESSIVE:
            px = q.ask + off if line.side is Side.BUY else q.bid - off
        else:  # PASSIVE
            px = q.bid - off if line.side is Side.BUY else q.ask + off
        return inst.round_to_tick(max(px, inst.tick_size))

    def _send(self, basket: Basket, line: BasketLine, qty: int) -> None:
        params = basket.params
        tag = basket.basket_id
        line.error = ""
        if params.mode.algo_type is not None:
            algo = self.oms.algos.start(
                line.symbol, line.side, qty, params.mode.algo_type, params.duration, params.participation,
                strategy_tag=tag,
            )
            line.algo_ids.append(algo.algo_id)
            if algo.halt_reason:
                line.error = algo.halt_reason
            return
        if params.mode is ExecMode.MARKET:
            order = self.oms.submit(line.symbol, line.side, OrderType.MARKET, qty, strategy_tag=tag)
        else:
            px = self._price_for(line, params)
            order = self.oms.submit(line.symbol, line.side, OrderType.LIMIT, qty, px, TimeInForce.DAY, strategy_tag=tag)
        line.order_ids.append(order.order_id)
        if order.status is OrderStatus.REJECTED:
            line.error = order.reject_reason

    # ================= 상태 =================
    def line_orders(self, line: BasketLine):
        orders = [self.oms.orders[i] for i in line.order_ids]
        for aid in line.algo_ids:
            orders += self.oms.algos.children(self.oms.algos.algos[aid])
        return orders

    def line_filled(self, line: BasketLine) -> tuple[int, float]:
        orders = [o for o in self.line_orders(line) if o.filled_qty]
        q = sum(o.filled_qty for o in orders)
        avg = sum(o.avg_fill_price * o.filled_qty for o in orders) / q if q else 0.0
        return q, avg

    def line_working(self, line: BasketLine) -> int:
        working = sum(o.leaves_qty for o in self.line_orders(line) if o.status.is_open)
        for aid in line.algo_ids:
            a = self.oms.algos.algos[aid]
            if a.status.is_active:
                working += max(a.qty - self.oms.algos.filled(a), 0)
        return working

    def line_status(self, line: BasketLine) -> str:
        filled, _ = self.line_filled(line)
        if filled >= line.qty:
            return "완료"
        if self.line_working(line):
            return "진행중" if not filled else "부분체결"
        if line.error:
            return "거부" if not filled else "부분체결·거부"
        return "미체결 잔량" if filled else "미체결"

    def lines_frame(self, basket: Basket) -> pd.DataFrame:
        rows = []
        for ln in basket.lines:
            inst = self.oms.instruments[ln.symbol]
            filled, avg = self.line_filled(ln)
            mark = self.oms.market.mark(ln.symbol)
            pnl = (mark - avg) * filled * ln.side.sign * inst.multiplier if filled else 0.0
            rows.append(
                {
                    "종목코드": ln.symbol,
                    "종목명": inst.name,
                    "구분": ln.side.value,
                    "목표": ln.qty,
                    "체결": filled,
                    "진행 중": self.line_working(ln),
                    "체결률": filled / ln.qty,
                    "평균체결가": round(avg, 4) if filled else None,
                    "현재가": mark,
                    "평가손익": round(pnl),
                    "상태": self.line_status(ln),
                    "재전송": ln.retries,
                    "주문": ", ".join(ln.order_ids + ln.algo_ids),
                    "오류": ln.error,
                }
            )
        return pd.DataFrame(rows)

    def summary(self, basket: Basket) -> dict:
        target_n = filled_n = filled_at_mark = pnl = 0.0
        target_q = filled_q = working = 0
        for ln in basket.lines:
            inst = self.oms.instruments[ln.symbol]
            mark = self.oms.market.mark(ln.symbol)
            filled, avg = self.line_filled(ln)
            target_n += ln.qty * mark * inst.multiplier
            filled_n += filled * avg * inst.multiplier
            filled_at_mark += filled * mark * inst.multiplier
            pnl += (mark - avg) * filled * ln.side.sign * inst.multiplier if filled else 0.0
            target_q += ln.qty
            filled_q += filled
            working += self.line_working(ln)
        done = sum(self.line_status(ln) == "완료" for ln in basket.lines)
        return {
            "종목 수": len(basket.lines),
            "완료 종목": done,
            "수량 체결률": filled_q / target_q if target_q else 0.0,
            # 금액 체결률은 목표와 체결을 같은 현재가로 평가해 가격 변동 효과를 뺀다
            "금액 체결률": filled_at_mark / target_n if target_n else 0.0,
            "목표 명목": target_n,
            "체결 금액": filled_n,
            "진행 중 수량": working,
            "잔량": target_q - filled_q,
            "평가손익": pnl,
            "거부 종목": sum(bool(ln.error) for ln in basket.lines),
        }

    # ================= 제어 =================
    def cancel(self, basket_id: str) -> int:
        b = self.baskets[basket_id]
        b.canceled = True
        n = 0
        for ln in b.lines:
            for aid in ln.algo_ids:
                if self.oms.algos.algos[aid].status.is_active:
                    self.oms.algos.cancel(aid, f"{basket_id} 바스켓 취소")
                    n += 1
            for oid in ln.order_ids:
                n += self.oms.cancel(oid, f"{basket_id} 바스켓 취소")
        return n

    def retry(self, basket_id: str) -> int:
        """체결되지 않고 진행 중이지도 않은 잔량을 같은 실행 방식으로 다시 보낸다."""
        b = self.baskets[basket_id]
        b.canceled = False
        sent = 0
        for ln in b.lines:
            filled, _ = self.line_filled(ln)
            rest = ln.qty - filled - self.line_working(ln)
            if rest > 0:
                ln.retries += 1
                self._send(b, ln, rest)
                sent += 1
        return sent

    def reprice(self, basket_id: str) -> int:
        """지정가 미체결 주문을 현재 호가 기준(실행 설정의 n틱)으로 정정한다."""
        b = self.baskets[basket_id]
        if b.params.mode not in (ExecMode.AGGRESSIVE, ExecMode.PASSIVE):
            return 0
        n = 0
        for ln in b.lines:
            px = self._price_for(ln, b.params)
            for oid in ln.order_ids:
                o = self.oms.orders[oid]
                if o.status.is_open and o.limit_price != px:
                    ok, _ = self.oms.amend(oid, new_limit_price=px)
                    n += ok
        return n

    def on_tick(self) -> None:
        """자동 재전송: 리스크 거부가 아닌 이유(유동성 부족 등)로 남은 수량을 다시 보낸다."""
        for b in self.baskets.values():
            if b.canceled or not b.params.auto_retry or b.params.mode is not ExecMode.MARKET:
                continue
            for ln in b.lines:
                if ln.error or ln.retries >= b.params.max_retries:
                    continue
                filled, _ = self.line_filled(ln)
                rest = ln.qty - filled - self.line_working(ln)
                if rest > 0:
                    ln.retries += 1
                    with self.oms.acting(b.actor):
                        self._send(b, ln, rest)
                    if ln.error:
                        self.oms._alert(
                            AlertLevel.WARNING, "바스켓 재전송 거부", f"{b.basket_id} {ln.symbol} — {ln.error}"
                        )


def sample_template() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "종목코드": ["005930", "000660", "005380", "035420", "105560"],
            "구분": ["매수"] * 5,
            "수량": [500, 100, 80, 100, 300],
            "비중(%)": [30, 25, 15, 15, 15],
        }
    )
