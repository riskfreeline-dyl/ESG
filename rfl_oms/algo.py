"""실행 알고리즘: TWAP, VWAP, POV.

부모(알고) 주문은 매 틱 목표 누적 수량을 계산하고, 부족분을 자식 주문(IOC 지정가,
상대 1호가)으로 낸다. 자식 주문은 일반 주문과 똑같이 사전 리스크 점검을 거친다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .market import volume_profile
from .models import AlertLevel, OrderStatus, OrderType, Side, TimeInForce

if TYPE_CHECKING:
    from .engine import OMS


class AlgoType(str, Enum):
    TWAP = "TWAP"
    VWAP = "VWAP"
    POV = "POV"


class AlgoStatus(str, Enum):
    RUNNING = "실행중"
    PAUSED = "일시정지"
    DONE = "완료"
    EXPIRED = "기간종료"
    CANCELED = "취소"
    HALTED = "중단"

    @property
    def is_active(self) -> bool:
        return self in (AlgoStatus.RUNNING, AlgoStatus.PAUSED)


ALGO_DESCRIPTIONS = {
    AlgoType.TWAP: "기간 동안 시간에 비례해 균등하게 나눠 체결",
    AlgoType.VWAP: "장중 거래량 패턴(U자형)에 비례해 나눠 체결",
    AlgoType.POV: "직전 틱 시장 거래량의 일정 비율만큼 체결",
}


@dataclass
class AlgoOrder:
    algo_id: str
    symbol: str
    side: Side
    qty: int
    algo_type: AlgoType
    start_tick: int
    duration: int  # 틱 (POV는 최대 실행 기간)
    participation: float  # POV 참여율 (0~1)
    limit_price: float | None
    arrival_price: float
    strategy_tag: str = ""
    actor: str = ""  # 알고를 시작한 사용자 (자식 주문의 행위자)
    status: AlgoStatus = AlgoStatus.RUNNING
    halt_reason: str = ""
    child_ids: list[str] = field(default_factory=list)
    in_flight: int = 0  # 자식 주문 점검 중인 수량 (노출 중복 계산 방지)
    progress: list[tuple[int, int, int]] = field(default_factory=list)  # (틱, 누적체결, 목표)
    mkt_notional: float = 0.0  # 실행 구간 시장 VWAP 계산용
    mkt_volume: int = 0
    _target_pov: float = 0.0


class AlgoEngine:
    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.algos: dict[str, AlgoOrder] = {}
        self._seq = 0

    # ---------------- 조회 ----------------
    def children(self, algo: AlgoOrder):
        return [self.oms.orders[i] for i in algo.child_ids]

    def filled(self, algo: AlgoOrder) -> int:
        return sum(o.filled_qty for o in self.children(algo))

    def avg_price(self, algo: AlgoOrder) -> float:
        kids = [o for o in self.children(algo) if o.filled_qty]
        q = sum(o.filled_qty for o in kids)
        return sum(o.avg_fill_price * o.filled_qty for o in kids) / q if q else 0.0

    def market_vwap(self, algo: AlgoOrder) -> float:
        return algo.mkt_notional / algo.mkt_volume if algo.mkt_volume else 0.0

    def slippage_bps(self, algo: AlgoOrder, benchmark: float) -> float | None:
        """양수 = 불리한 체결 (매수는 비싸게, 매도는 싸게)."""
        avg = self.avg_price(algo)
        if not avg or not benchmark:
            return None
        return (avg / benchmark - 1) * 1e4 * algo.side.sign

    def reserved(self) -> tuple[dict[str, int], dict[str, int]]:
        """아직 자식 주문으로 나가지 않은 알고 잔량 (리스크 노출 계산용)."""
        buys: dict[str, int] = {}
        sells: dict[str, int] = {}
        for a in self.algos.values():
            if not a.status.is_active:
                continue
            rest = max(a.qty - self.filled(a) - a.in_flight, 0)
            book = buys if a.side is Side.BUY else sells
            book[a.symbol] = book.get(a.symbol, 0) + rest
        return buys, sells

    def target(self, algo: AlgoOrder, tick: int) -> int:
        elapsed = tick - algo.start_tick
        if elapsed <= 0:
            return 0
        if algo.algo_type is AlgoType.TWAP:
            frac = min(elapsed / algo.duration, 1.0)
        elif algo.algo_type is AlgoType.VWAP:
            weights = [volume_profile(algo.start_tick + k) for k in range(1, algo.duration + 1)]
            frac = sum(weights[: min(elapsed, algo.duration)]) / sum(weights)
        else:  # POV: 누적 시장 거래량 × 참여율
            return min(int(algo._target_pov), algo.qty)
        return min(int(algo.qty * frac + 1e-9), algo.qty)

    # ---------------- 제어 ----------------
    def start(
        self,
        symbol: str,
        side: Side,
        qty: int,
        algo_type: AlgoType,
        duration: int = 30,
        participation: float = 0.1,
        limit_price: float | None = None,
        strategy_tag: str = "",
    ) -> AlgoOrder:
        self._seq += 1
        algo = AlgoOrder(
            algo_id=f"A{self._seq:04d}",
            symbol=symbol,
            side=side,
            qty=int(qty),
            algo_type=algo_type,
            start_tick=self.oms.market.tick_no,
            duration=max(int(duration), 1),
            participation=float(participation),
            limit_price=limit_price,
            arrival_price=self.oms.market.mark(symbol),
            strategy_tag=strategy_tag,
            actor=self.oms.actor,
        )
        # 부모 주문 전체 수량으로 사전 점검 (시장가로 전량 체결된다고 가정)
        checks = self.oms.preview(symbol, side, OrderType.MARKET, int(qty))
        failed = [c for c in checks if not c.passed]
        if failed:
            algo.status = AlgoStatus.HALTED
            algo.halt_reason = "; ".join(f"{c.name}: {c.detail}" for c in failed)
            self.oms._alert(AlertLevel.WARNING, "알고 거부", f"{algo.algo_id} {symbol} — {algo.halt_reason}")
        elif algo.algo_type is AlgoType.POV and not 0 < algo.participation <= 1:
            algo.status = AlgoStatus.HALTED
            algo.halt_reason = "참여율은 0% 초과 100% 이하여야 합니다"
        self.algos[algo.algo_id] = algo
        algo.progress.append((algo.start_tick, 0, 0))
        return algo

    def pause(self, algo_id: str) -> None:
        a = self.algos[algo_id]
        if a.status is AlgoStatus.RUNNING:
            a.status = AlgoStatus.PAUSED

    def resume(self, algo_id: str) -> None:
        a = self.algos[algo_id]
        if a.status is AlgoStatus.PAUSED:
            a.status = AlgoStatus.RUNNING

    def cancel(self, algo_id: str, reason: str = "사용자 취소") -> None:
        a = self.algos[algo_id]
        if not a.status.is_active:
            return
        for o in self.children(a):
            if o.status.is_open:
                self.oms.cancel(o.order_id, reason)
        a.status = AlgoStatus.CANCELED
        a.halt_reason = reason

    def cancel_all(self, reason: str) -> int:
        active = [a.algo_id for a in self.algos.values() if a.status.is_active]
        for i in active:
            self.cancel(i, reason)
        return len(active)

    # ---------------- 틱 처리 ----------------
    def on_tick(self) -> None:
        tick = self.oms.market.tick_no
        for algo in list(self.algos.values()):
            if not algo.status.is_active:
                continue
            vol = self.oms.market.volume[algo.symbol]
            algo.mkt_volume += vol
            algo.mkt_notional += vol * self.oms.market.mark(algo.symbol)
            if algo.algo_type is AlgoType.POV:
                algo._target_pov += vol * algo.participation
            if algo.status is AlgoStatus.RUNNING:
                self._work(algo, tick)
            filled = self.filled(algo)
            algo.progress.append((tick, filled, self.target(algo, tick)))
            if filled >= algo.qty:
                algo.status = AlgoStatus.DONE
                self.oms._alert(AlertLevel.INFO, "알고 완료", self._summary(algo))
            elif tick - algo.start_tick >= algo.duration and algo.status is AlgoStatus.RUNNING:
                algo.status = AlgoStatus.EXPIRED
                self.oms._alert(
                    AlertLevel.WARNING, "알고 기간종료", f"{self._summary(algo)} · 미체결 {algo.qty - filled:,}"
                )
            del algo.progress[:-500]

    def _summary(self, algo: AlgoOrder) -> str:
        slip = self.slippage_bps(algo, algo.arrival_price)
        slip_txt = f", 도착가 대비 {slip:+.1f}bp" if slip is not None else ""
        return (
            f"{algo.algo_id} {algo.algo_type.value} {algo.symbol} {algo.side.value} "
            f"{self.filled(algo):,}/{algo.qty:,} 평균 {self.avg_price(algo):,.4g}{slip_txt}"
        )

    def _work(self, algo: AlgoOrder, tick: int) -> None:
        want = self.target(algo, tick) - self.filled(algo)
        if tick - algo.start_tick >= algo.duration and algo.algo_type is not AlgoType.POV:
            want = algo.qty - self.filled(algo)  # 마지막 틱: 남은 수량 전부 시도
        if want <= 0:
            return
        q = self.oms.market.quote(algo.symbol)
        price = q.ask if algo.side is Side.BUY else q.bid
        if algo.limit_price is not None:
            if algo.side is Side.BUY and price > algo.limit_price:
                return  # 제한가 위: 이번 틱은 대기
            if algo.side is Side.SELL and price < algo.limit_price:
                return
        algo.in_flight = want
        with self.oms.acting(algo.actor):
            child = self.oms.submit(
                algo.symbol,
                algo.side,
                OrderType.LIMIT,
                want,
                price,
                TimeInForce.IOC,
                strategy_tag=algo.algo_id,
            )
        algo.in_flight = 0
        algo.child_ids.append(child.order_id)
        if child.status is OrderStatus.REJECTED:
            algo.status = AlgoStatus.HALTED
            algo.halt_reason = child.reject_reason
            self.oms._alert(AlertLevel.CRITICAL, "알고 중단", f"{algo.algo_id} 자식 주문 거부 — {child.reject_reason}")

