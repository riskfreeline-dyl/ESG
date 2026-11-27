"""페어 트레이딩 (통계적 차익).

두 종목 로그가격의 회귀로 헤지비율 β를 구하고, 스프레드 = log(A) − β·log(B)의
최근 평균 대비 Z-점수가 진입 기준을 넘으면 비싼 쪽을 팔고 싼 쪽을 산다.
Z-점수가 청산 기준 안으로 돌아오면 청산, 손절 기준을 넘으면 손절한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

from .ledger import net_holdings, orders_pnl
from .models import AlertLevel, OrderStatus, OrderType, Side

if TYPE_CHECKING:
    from .engine import OMS

DEFAULT_PAIRS = (("005380", "000270"), ("005930", "000660"), ("105560", "005490"))


class PairDirection(str, Enum):
    SHORT_A = "A 매도 · B 매수"  # 스프레드가 높음 (A가 상대적으로 비쌈)
    LONG_A = "A 매수 · B 매도"  # 스프레드가 낮음 (A가 상대적으로 쌈)


@dataclass
class PairSettings:
    lookback: int = 60  # 통계 계산 기간(틱)
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0
    notional: float = 50_000_000  # A 종목 1레그 명목금액
    auto: bool = False
    auto_owner: str = ""
    max_open: int = 2


@dataclass
class PairStat:
    a: str
    b: str
    n: int
    beta: float | None = None
    z: float | None = None
    spread: float | None = None
    mean: float | None = None
    std: float | None = None
    corr: float | None = None
    half_life: float | None = None  # 스프레드 평균회귀 반감기(틱), 회귀하지 않으면 None

    @property
    def ready(self) -> bool:
        return self.z is not None


@dataclass
class PairPosition:
    pair_id: str
    a: str
    b: str
    direction: PairDirection
    qty_a: int
    qty_b: int
    entry: PairStat
    opened_tick: int
    owner: str
    order_ids: list[str] = field(default_factory=list)
    open: bool = True
    exit_z: float | None = None
    closed_tick: int | None = None
    note: str = ""


class PairsEngine:
    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.settings = PairSettings()
        self.pairs: list[tuple[str, str]] = [p for p in DEFAULT_PAIRS if all(s in oms.instruments for s in p)]
        self.positions: dict[str, PairPosition] = {}
        self.z_history: dict[tuple[str, str], list[tuple[int, float]]] = {p: [] for p in self.pairs}
        self._seq = 0

    # ---------------- 통계 ----------------
    def stat(self, a: str, b: str) -> PairStat:
        lb = self.settings.lookback
        ha = dict(self.oms.market.history[a][-(lb + 1):])
        hb = dict(self.oms.market.history[b][-(lb + 1):])
        ticks = sorted(set(ha) & set(hb))
        st = PairStat(a, b, len(ticks))
        if len(ticks) < 20:
            return st
        la = np.log([ha[t] for t in ticks])
        lb_ = np.log([hb[t] for t in ticks])
        if np.std(lb_) == 0 or np.std(la) == 0:
            return st
        beta, alpha = np.polyfit(lb_, la, 1)
        spread = la - beta * lb_
        mean, std = float(spread.mean()), float(spread.std(ddof=1))
        if std == 0:
            return st
        st.beta, st.spread, st.mean, st.std = float(beta), float(spread[-1]), mean, std
        st.z = (st.spread - mean) / std
        ra, rb = np.diff(la), np.diff(lb_)
        st.corr = float(np.corrcoef(ra, rb)[0, 1]) if ra.std() and rb.std() else None
        # 반감기: Δs = φ·s(−1) + ε 회귀, φ < 0 이면 평균회귀
        ds, lag = np.diff(spread), spread[:-1] - mean
        phi = float(np.dot(lag, ds) / np.dot(lag, lag)) if np.dot(lag, lag) else 0.0
        st.half_life = -math.log(2) / phi if phi < 0 else None
        return st

    def pair_orders(self, pos: PairPosition):
        return [self.oms.orders[i] for i in pos.order_ids]

    def pnl(self, pos: PairPosition) -> dict[str, float]:
        return orders_pnl(self.oms, self.pair_orders(pos))

    def open_positions(self) -> list[PairPosition]:
        return [p for p in self.positions.values() if p.open]

    # ---------------- 진입·청산 ----------------
    def size(self, a: str, b: str, beta: float) -> tuple[int, int]:
        """A는 설정 금액만큼, B는 β만큼의 금액으로 (로그 수익률 기준 헤지)."""
        pa, pb = self.oms.market.mark(a), self.oms.market.mark(b)
        qa = max(int(self.settings.notional // pa), 1)
        qb = max(round(abs(beta) * qa * pa / pb), 1)
        return qa, qb

    def enter(self, a: str, b: str, direction: PairDirection | None = None) -> tuple[PairPosition | None, list[str]]:
        st = self.stat(a, b)
        if not st.ready:
            return None, [f"통계 계산에 필요한 데이터가 부족합니다 ({st.n}/20틱). 시장을 더 진행하세요"]
        if direction is None:
            direction = PairDirection.SHORT_A if st.z > 0 else PairDirection.LONG_A
        qa, qb = self.size(a, b, st.beta)
        side_a = Side.SELL if direction is PairDirection.SHORT_A else Side.BUY
        side_b = Side.BUY if side_a is Side.SELL else Side.SELL
        problems = [
            f"{sym} {c.name}: {c.detail}"
            for sym, side, q in ((a, side_a, qa), (b, side_b, qb))
            for c in self.oms.preview(sym, side, OrderType.MARKET, q)
            if not c.passed
        ]
        if problems:
            self.oms._alert(AlertLevel.WARNING, "페어 진입 거부", f"{a}/{b} — {problems[0]}")
            return None, problems
        self._seq += 1
        pos = PairPosition(f"P{self._seq:03d}", a, b, direction, qa, qb, st, self.oms.market.tick_no, self.oms.actor)
        self.positions[pos.pair_id] = pos
        for sym, side, q in ((a, side_a, qa), (b, side_b, qb)):
            o = self.oms.submit(sym, side, OrderType.MARKET, q, strategy_tag=pos.pair_id)
            pos.order_ids.append(o.order_id)
            if o.status is OrderStatus.REJECTED or o.filled_qty < q:
                pos.note = "레그 일부 미체결"
                self.oms._alert(AlertLevel.CRITICAL, "페어 레그 불일치", f"{pos.pair_id} {sym} 체결 {o.filled_qty}/{q}")
        self.oms._alert(
            AlertLevel.INFO, "페어 진입",
            f"{pos.pair_id} {a}/{b} {direction.value} · Z {st.z:+.2f} · β {st.beta:.2f} · 수량 {qa}/{qb}",
        )
        return pos, []

    def close(self, pair_id: str, reason: str = "수동 청산") -> bool:
        pos = self.positions.get(pair_id)
        if pos is None or not pos.open:
            return False
        for sym, q in net_holdings(self.pair_orders(pos)).items():
            if q:
                o = self.oms.submit(sym, Side.SELL if q > 0 else Side.BUY, OrderType.MARKET, abs(q), strategy_tag=pos.pair_id)
                pos.order_ids.append(o.order_id)
        st = self.stat(pos.a, pos.b)
        pos.open, pos.exit_z, pos.closed_tick, pos.note = False, st.z, self.oms.market.tick_no, reason
        self.oms._alert(
            AlertLevel.INFO, "페어 청산",
            f"{pair_id} {reason} · Z {pos.entry.z:+.2f} → {st.z:+.2f}" if st.z is not None else f"{pair_id} {reason}",
        )
        return True

    # ---------------- 틱 처리 ----------------
    def on_tick(self) -> None:
        tick = self.oms.market.tick_no
        stats = {}
        for a, b in self.pairs:
            st = self.stat(a, b)
            stats[(a, b)] = st
            if st.ready:
                hist = self.z_history.setdefault((a, b), [])
                hist.append((tick, st.z))
                del hist[:-500]
        if not self.settings.auto or self.oms.kill_switch:
            return
        s = self.settings
        with self.oms.acting(f"{s.auto_owner}(자동)"):
            for pos in self.open_positions():
                st = stats.get((pos.a, pos.b))
                if st is None or not st.ready:
                    continue
                if abs(st.z) <= s.exit_z:
                    self.close(pos.pair_id, "자동 청산(스프레드 수렴)")
                elif abs(st.z) >= s.stop_z:
                    self.close(pos.pair_id, "자동 손절(스프레드 확대)")
            held = {(p.a, p.b) for p in self.open_positions()}
            for (a, b), st in stats.items():
                if len(self.open_positions()) >= s.max_open:
                    break
                if st.ready and (a, b) not in held and s.entry_z <= abs(st.z) < s.stop_z:
                    self.enter(a, b)
