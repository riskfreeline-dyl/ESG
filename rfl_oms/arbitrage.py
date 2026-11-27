"""지수 차익거래: 지수선물 ↔ 현물 바스켓.

- 매도차익: 선물이 이론가보다 비쌀 때 선물 매도 + 현물 바스켓 매수
- 매수차익: 선물이 이론가보다 쌀 때 선물 매수 + 현물 바스켓 매도(대차 매도 가정)

거래비용(수수료·세금·슬리피지)을 지수 포인트로 환산해 뺀 '순 기대수익(edge)'이
진입 기준을 넘으면 진입하고, 괴리가 청산 기준 안으로 돌아오면 청산한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .basket import BasketLine, ExecMode, ExecParams
from .models import AlertLevel, OrderStatus, OrderType, Side

if TYPE_CHECKING:
    from .engine import OMS


class ArbDirection(str, Enum):
    SELL_ARB = "매도차익"  # 선물 매도 + 현물 매수
    BUY_ARB = "매수차익"  # 선물 매수 + 현물 매도

    @property
    def futures_side(self) -> Side:
        return Side.SELL if self is ArbDirection.SELL_ARB else Side.BUY

    @property
    def stock_side(self) -> Side:
        return Side.BUY if self is ArbDirection.SELL_ARB else Side.SELL


class ArbStatus(str, Enum):
    OPEN = "보유"
    CLOSED = "청산"
    LEG_ERROR = "레그 불일치"


@dataclass
class ArbCosts:
    commission_bps: float = 1.0  # 주식 매매수수료 (편도)
    sell_tax_bps: float = 15.0  # 주식 매도 시 거래세 (시뮬레이션 가정값, 조정 가능)
    futures_bps: float = 0.3  # 선물 수수료 (편도)
    slippage_bps: float = 2.0  # 체결 슬리피지 (편도)

    def round_trip_bps(self) -> float:
        return 2 * self.commission_bps + self.sell_tax_bps + 2 * self.futures_bps + 2 * self.slippage_bps


@dataclass
class ArbSettings:
    entry_edge_pts: float = 0.10  # 비용 차감 후 이 포인트 이상이면 진입
    exit_mispricing_pts: float = 0.0  # 괴리가 이 값 안쪽으로 돌아오면 청산
    contracts: int = 1
    stock_mode: ExecMode = ExecMode.MARKET
    auto: bool = False
    auto_owner: str = "자동차익"  # 자동 차익을 켠 사용자 (자동 주문의 행위자)
    max_open: int = 3


@dataclass
class ArbSnapshot:
    tick: int
    index: float
    fut_bid: float
    fut_ask: float
    fair: float
    cost_pts: float

    @property
    def fut_mid(self) -> float:
        return (self.fut_bid + self.fut_ask) / 2

    @property
    def basis(self) -> float:
        return self.fut_mid - self.index

    @property
    def theo_basis(self) -> float:
        return self.fair - self.index

    @property
    def mispricing(self) -> float:
        """선물 중간가 − 이론가 (양수 = 선물 고평가)."""
        return self.fut_mid - self.fair

    @property
    def mispricing_bps(self) -> float:
        return self.mispricing / self.index * 1e4

    @property
    def sell_edge(self) -> float:
        """매도차익 순 기대수익: 선물 매수호가에 팔 때."""
        return self.fut_bid - self.fair - self.cost_pts

    @property
    def buy_edge(self) -> float:
        """매수차익 순 기대수익: 선물 매도호가에 살 때."""
        return self.fair - self.fut_ask - self.cost_pts


@dataclass
class ArbPosition:
    arb_id: str
    direction: ArbDirection
    contracts: int
    opened_tick: int
    entry: ArbSnapshot
    futures_order_ids: list[str] = field(default_factory=list)
    basket_ids: list[str] = field(default_factory=list)
    status: ArbStatus = ArbStatus.OPEN
    closed_tick: int | None = None
    exit: ArbSnapshot | None = None
    note: str = ""
    owner: str = ""  # 진입한 사용자


class ArbEngine:
    """지수선물 ↔ 구성종목 바스켓 차익. 하위 클래스가 기초(현물)와 복제 방법만 바꿔 재사용한다."""

    PREFIX = "X"  # 포지션 번호 접두사
    KIND = "지수"

    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.costs = ArbCosts()
        self.settings = ArbSettings()
        self.positions: dict[str, ArbPosition] = {}
        self.history: list[ArbSnapshot] = []
        self._seq = 0
        if self.available:
            self.history.append(self.snapshot())

    @property
    def index_def(self):
        return self.oms.market.index_def

    @property
    def model(self):
        """이론가 모형 (rate, dividend_yield, days_to_expiry, fair_futures 보유)."""
        return self.index_def

    @property
    def available(self) -> bool:
        return self.model is not None

    @property
    def futures_symbol(self) -> str:
        return self.model.futures_symbol

    def spot_value(self) -> float:
        return self.oms.market.index_value()

    # ---------------- 시세 ----------------
    def snapshot(self) -> ArbSnapshot:
        m = self.oms.market
        idx = self.spot_value()
        q = m.quote(self.futures_symbol)
        return ArbSnapshot(
            tick=m.tick_no,
            index=idx,
            fut_bid=q.bid,
            fut_ask=q.ask,
            fair=self.model.fair_futures(idx),
            cost_pts=idx * self.costs.round_trip_bps() / 1e4,
        )

    def unit_lines(self, side: Side, units: int) -> list[BasketLine]:
        return [BasketLine(s, side, q * units) for s, q in self.index_def.constituents.items()]

    # ---------------- 포지션 평가 ----------------
    def _orders(self, pos: ArbPosition):
        orders = [self.oms.orders[i] for i in pos.futures_order_ids]
        for bid in pos.basket_ids:
            for ln in self.oms.baskets.baskets[bid].lines:
                orders += self.oms.baskets.line_orders(ln)
        return orders

    def net_holdings(self, pos: ArbPosition) -> dict[str, int]:
        net: dict[str, int] = {}
        for o in self._orders(pos):
            net[o.symbol] = net.get(o.symbol, 0) + o.side.sign * o.filled_qty
        return net

    def pnl(self, pos: ArbPosition) -> float:
        """현금흐름 + 남은 보유분 평가 (진입·청산 모두 포함, 비용 제외)."""
        total = 0.0
        for o in self._orders(pos):
            mult = self.oms.instruments[o.symbol].multiplier
            total -= o.side.sign * o.filled_qty * o.avg_fill_price * mult
        for sym, q in self.net_holdings(pos).items():
            total += q * self.oms.market.mark(sym) * self.oms.instruments[sym].multiplier
        return total

    def fees(self, pos: ArbPosition) -> float:
        ids = {o.order_id for o in self._orders(pos)}
        return sum(f.fee for f in self.oms.fills if f.order_id in ids)

    def pnl_net(self, pos: ArbPosition) -> float:
        """비용 차감 후 손익."""
        return self.pnl(pos) - self.fees(pos)

    def hedge(self, pos: ArbPosition) -> tuple[float, float]:
        """(선물 명목, 현물 명목) — 부호 포함. 합이 0에 가까울수록 완전 헤지."""
        fsym = self.futures_symbol
        fut = stock = 0.0
        for sym, q in self.net_holdings(pos).items():
            n = q * self.oms.market.mark(sym) * self.oms.instruments[sym].multiplier
            if sym == fsym:
                fut += n
            else:
                stock += n
        return fut, stock

    def open_positions(self) -> list[ArbPosition]:
        return [p for p in self.positions.values() if p.status is not ArbStatus.CLOSED]

    # ---------------- 진입·청산 ----------------
    def pre_check(self, direction: ArbDirection, contracts: int) -> list[str]:
        """두 레그 모두 사전 점검을 통과해야 진입한다 (한쪽만 체결되는 위험 방지)."""
        problems = []
        fsym = self.futures_symbol
        for c in self.oms.preview(fsym, direction.futures_side, OrderType.MARKET, contracts):
            if not c.passed:
                problems.append(f"선물 {c.name}: {c.detail}")
        for ln in self.unit_lines(direction.stock_side, contracts):
            for c in self.oms.preview(ln.symbol, ln.side, OrderType.MARKET, ln.qty):
                if not c.passed:
                    problems.append(f"{ln.symbol} {c.name}: {c.detail}")
        return problems

    def enter(self, direction: ArbDirection, contracts: int | None = None) -> tuple[ArbPosition | None, list[str]]:
        contracts = int(contracts or self.settings.contracts)
        problems = self.pre_check(direction, contracts)
        if problems:
            self.oms._alert(AlertLevel.WARNING, "차익 진입 거부", f"{direction.value} {contracts}계약 — {problems[0]}")
            return None, problems
        self._seq += 1
        snap = self.snapshot()
        pos = ArbPosition(f"{self.PREFIX}{self._seq:03d}", direction, contracts, snap.tick, snap, owner=self.oms.actor)
        self.positions[pos.arb_id] = pos
        fsym = self.futures_symbol
        fut = self.oms.submit(fsym, direction.futures_side, OrderType.MARKET, contracts, strategy_tag=pos.arb_id)
        pos.futures_order_ids.append(fut.order_id)
        basket = self.oms.baskets.execute(
            f"{pos.arb_id} {direction.value} 현물",
            self.unit_lines(direction.stock_side, contracts),
            ExecParams(mode=self.settings.stock_mode, duration=10),
        )
        pos.basket_ids.append(basket.basket_id)
        self._check_legs(pos, fut.status is OrderStatus.REJECTED or fut.filled_qty < contracts, basket)
        self.oms._alert(
            AlertLevel.INFO,
            "차익 진입",
            f"{pos.arb_id} {direction.value} {contracts}계약 · 괴리 {snap.mispricing:+.2f}pt "
            f"({snap.mispricing_bps:+.1f}bp) · 비용 {snap.cost_pts:.2f}pt",
        )
        return pos, []

    def close(self, arb_id: str, reason: str = "수동 청산") -> bool:
        pos = self.positions.get(arb_id)
        if pos is None or pos.status is ArbStatus.CLOSED:
            return False
        fsym = self.futures_symbol
        net = self.net_holdings(pos)
        fq = net.pop(fsym, 0)
        if fq:
            side = Side.SELL if fq > 0 else Side.BUY
            o = self.oms.submit(fsym, side, OrderType.MARKET, abs(fq), strategy_tag=pos.arb_id)
            pos.futures_order_ids.append(o.order_id)
        lines = [BasketLine(s, Side.SELL if q > 0 else Side.BUY, abs(q)) for s, q in net.items() if q]
        if lines:
            b = self.oms.baskets.execute(
                f"{pos.arb_id} 청산 현물", lines, ExecParams(mode=self.settings.stock_mode, duration=10)
            )
            pos.basket_ids.append(b.basket_id)
        pos.exit = self.snapshot()
        pos.closed_tick = pos.exit.tick
        pos.status = ArbStatus.CLOSED
        pos.note = reason
        self.oms._alert(
            AlertLevel.INFO,
            "차익 청산",
            f"{pos.arb_id} {reason} · 괴리 {pos.entry.mispricing:+.2f} → {pos.exit.mispricing:+.2f}pt",
        )
        return True

    def _check_legs(self, pos: ArbPosition, futures_failed: bool, basket) -> None:
        stock_failed = any(ln.error for ln in basket.lines)
        if futures_failed or stock_failed:
            pos.status = ArbStatus.LEG_ERROR
            pos.note = "선물 레그 실패" if futures_failed else "현물 레그 일부 실패"
            self.oms._alert(
                AlertLevel.CRITICAL,
                "차익 레그 불일치",
                f"{pos.arb_id} {pos.note} — 헤지가 깨졌습니다. 청산하거나 잔량을 재실행하세요",
            )

    # ---------------- 틱 처리 ----------------
    def on_tick(self) -> None:
        if not self.available:
            return
        snap = self.snapshot()
        self.history.append(snap)
        del self.history[:-500]
        if not self.settings.auto or self.oms.kill_switch:
            return
        with self.oms.acting(f"{self.settings.auto_owner}(자동)"):
            self._auto(snap)

    def _auto(self, snap: ArbSnapshot) -> None:
        exit_band = self.settings.exit_mispricing_pts
        for pos in self.open_positions():
            if pos.status is not ArbStatus.OPEN:
                continue
            if pos.direction is ArbDirection.SELL_ARB and snap.mispricing <= exit_band:
                self.close(pos.arb_id, "자동 청산(괴리 수렴)")
            elif pos.direction is ArbDirection.BUY_ARB and snap.mispricing >= -exit_band:
                self.close(pos.arb_id, "자동 청산(괴리 수렴)")
        if len(self.open_positions()) >= self.settings.max_open:
            return
        if snap.sell_edge >= self.settings.entry_edge_pts:
            self.enter(ArbDirection.SELL_ARB)
        elif snap.buy_edge >= self.settings.entry_edge_pts:
            self.enter(ArbDirection.BUY_ARB)


class CarryArbEngine(ArbEngine):
    """현물 1종목 ↔ 선물 차익 (외환·국고채·금). 선물 1계약 = 현물 (선물 승수 ÷ 현물 승수) 단위."""

    def __init__(self, oms: "OMS", futures_symbol: str, prefix: str, costs: ArbCosts):
        self._fsym = futures_symbol
        self.PREFIX = prefix
        super().__init__(oms)
        self.costs = costs
        self.settings.entry_edge_pts = 0.0
        self.history = [self.snapshot()] if self.available else []

    @property
    def model(self):
        return self.oms.market.carry_link(self._fsym)

    @property
    def KIND(self) -> str:  # noqa: N802 (상위 클래스 속성 재정의)
        return self.model.name if self.model else self._fsym

    def spot_value(self) -> float:
        return self.oms.market.mark(self.model.spot_symbol)

    def spot_units_per_contract(self) -> int:
        inst = self.oms.instruments
        return max(round(inst[self._fsym].multiplier / inst[self.model.spot_symbol].multiplier), 1)

    def unit_lines(self, side: Side, units: int) -> list[BasketLine]:
        return [BasketLine(self.model.spot_symbol, side, self.spot_units_per_contract() * units)]


CARRY_ARB_SETUP = {
    # 선물: (포지션 접두사, 비용 가정)
    "USDF": ("FX", ArbCosts(commission_bps=0.3, sell_tax_bps=0.0, futures_bps=0.3, slippage_bps=1.0)),
    "KTBF": ("BD", ArbCosts(commission_bps=0.3, sell_tax_bps=0.0, futures_bps=0.3, slippage_bps=0.5)),
    "GOLDF": ("GD", ArbCosts(commission_bps=2.0, sell_tax_bps=0.0, futures_bps=0.3, slippage_bps=1.0)),
}
