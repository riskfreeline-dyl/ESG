"""마켓메이킹·유동성 공급 (외환·국고채·KRX 금).

매 틱 기준가 양쪽에 매수·매도 지정가 호가를 유지한다.
- 호가 폭: 기준가 ± (반폭 틱 수)
- 재고 스큐: 보유가 많으면 호가 전체를 낮춰 매도를 유도하고, 적으면 높인다
- 재고 한도: 한도를 넘게 되는 쪽 호가는 내지 않는다
- 모든 호가는 일반 주문과 같은 사전 리스크 점검을 거치며, 거부되면 그 종목 마켓메이킹을 멈춘다
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ledger import orders_pnl
from .models import AlertLevel, OrderStatus, OrderType, Side, TimeInForce

if TYPE_CHECKING:
    from .engine import OMS


@dataclass
class MMConfig:
    symbol: str
    size: int  # 한쪽 호가 수량
    max_inventory: int  # 보유 한도 (매수·매도 각각)
    half_spread_ticks: int = 2
    skew_ticks: float = 2.0  # 재고가 한도에 닿았을 때 호가를 옮기는 틱 수
    enabled: bool = False
    owner: str = ""
    bid_id: str | None = None
    ask_id: str | None = None
    quotes_sent: int = 0
    stop_reason: str = ""

    @property
    def tag(self) -> str:
        return f"MM:{self.symbol}"


# 반폭은 각 상품의 틱당 가격 변동(달러 약 5틱, 국채 약 2틱, 금 약 12틱)보다 넓게 잡는다.
# (시뮬레이션에서 반폭이 이보다 좁으면 추세에 밀려 손실이 나는 것을 확인함)
DEFAULT_MM = (
    MMConfig("USDKRW", size=100_000, max_inventory=1_000_000, half_spread_ticks=6, skew_ticks=4),
    MMConfig("KTB3Y", size=100, max_inventory=1_000, half_spread_ticks=3, skew_ticks=2),
    MMConfig("GOLD", size=200, max_inventory=2_000, half_spread_ticks=15, skew_ticks=10),
)


class MarketMaker:
    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.configs: dict[str, MMConfig] = {
            c.symbol: MMConfig(**{**c.__dict__}) for c in DEFAULT_MM if c.symbol in oms.instruments
        }

    # ---------------- 조회 ----------------
    def orders(self, cfg: MMConfig):
        return [o for o in self.oms.orders.values() if o.strategy_tag == cfg.tag]

    def inventory(self, cfg: MMConfig) -> int:
        return sum(o.side.sign * o.filled_qty for o in self.orders(cfg))

    def stats(self, cfg: MMConfig) -> dict:
        orders = self.orders(cfg)
        filled = [o for o in orders if o.filled_qty]
        buys = sum(o.filled_qty for o in filled if o.side is Side.BUY)
        sells = sum(o.filled_qty for o in filled if o.side is Side.SELL)
        pnl = orders_pnl(self.oms, orders)
        return {
            "재고": buys - sells,
            "매수 체결": buys,
            "매도 체결": sells,
            "체결 건수": len(filled),
            "호가 제출": cfg.quotes_sent,
            **pnl,
        }

    def quotes(self, cfg: MMConfig) -> tuple[float, float]:
        """(매수호가, 매도호가) 계산: 기준가 ± 반폭 + 재고 스큐, 상대 호가를 넘지 않게."""
        m = self.oms.market
        inst = self.oms.instruments[cfg.symbol]
        q = m.quote(cfg.symbol)
        tick = inst.tick_size
        skew = -cfg.skew_ticks * self.inventory(cfg) / cfg.max_inventory if cfg.max_inventory else 0.0
        bid = inst.round_to_tick(q.mid - cfg.half_spread_ticks * tick + skew * tick)
        ask = inst.round_to_tick(q.mid + cfg.half_spread_ticks * tick + skew * tick)
        bid = min(bid, inst.round_to_tick(q.ask - tick))  # 즉시 체결되지 않는 대기 호가
        ask = max(ask, inst.round_to_tick(q.bid + tick))
        if ask <= bid:
            ask = inst.round_to_tick(bid + tick)
        return max(bid, tick), ask

    # ---------------- 제어 ----------------
    def enable(self, symbol: str) -> None:
        cfg = self.configs[symbol]
        cfg.enabled, cfg.owner, cfg.stop_reason = True, self.oms.actor, ""
        self.oms.system_event("마켓메이킹 시작", f"{symbol} 수량 {cfg.size:,}, 반폭 {cfg.half_spread_ticks}틱, 재고한도 {cfg.max_inventory:,}")
        with self.oms.acting(cfg.owner):
            self._requote(cfg)

    def disable(self, symbol: str, reason: str = "사용자 중지") -> None:
        cfg = self.configs[symbol]
        self._cancel_quotes(cfg, reason)
        if cfg.enabled:
            cfg.enabled, cfg.stop_reason = False, reason
            self.oms.system_event("마켓메이킹 중지", f"{symbol} — {reason}")

    def _cancel_quotes(self, cfg: MMConfig, reason: str) -> None:
        for oid in (cfg.bid_id, cfg.ask_id):
            if oid and self.oms.orders[oid].status.is_open:
                self.oms.cancel(oid, reason)
        cfg.bid_id = cfg.ask_id = None

    def _place(self, cfg: MMConfig, side: Side, price: float, current: str | None) -> str | None:
        """호가 하나를 유지: 같은 가격이면 그대로, 다르면 정정, 없으면 새로 낸다."""
        if current:
            o = self.oms.orders[current]
            if o.status.is_open:
                if o.limit_price == price and o.qty - o.filled_qty == cfg.size:
                    return current
                ok, _ = self.oms.amend(current, new_qty=o.filled_qty + cfg.size, new_limit_price=price)
                if ok:
                    cfg.quotes_sent += 1
                    return current if self.oms.orders[current].status.is_open else None
                self.oms.cancel(current, "호가 갱신")
        o = self.oms.submit(cfg.symbol, side, OrderType.LIMIT, cfg.size, price, TimeInForce.DAY, strategy_tag=cfg.tag)
        cfg.quotes_sent += 1
        if o.status is OrderStatus.REJECTED:
            self.disable(cfg.symbol, f"호가 거부: {o.reject_reason}")
            self.oms._alert(AlertLevel.CRITICAL, "마켓메이킹 중지", f"{cfg.symbol} 호가 거부 — {o.reject_reason}")
            return None
        return o.order_id if o.status.is_open else None

    def _requote(self, cfg: MMConfig) -> None:
        inv = self.inventory(cfg)
        bid, ask = self.quotes(cfg)
        want_bid = inv + cfg.size <= cfg.max_inventory
        want_ask = inv - cfg.size >= -cfg.max_inventory
        if want_bid:
            cfg.bid_id = self._place(cfg, Side.BUY, bid, cfg.bid_id)
        elif cfg.bid_id:
            self.oms.cancel(cfg.bid_id, "재고 한도")
            cfg.bid_id = None
        if not cfg.enabled:
            return
        if want_ask:
            cfg.ask_id = self._place(cfg, Side.SELL, ask, cfg.ask_id)
        elif cfg.ask_id:
            self.oms.cancel(cfg.ask_id, "재고 한도")
            cfg.ask_id = None

    def on_tick(self) -> None:
        for cfg in self.configs.values():
            if not cfg.enabled:
                continue
            if self.oms.kill_switch:
                self.disable(cfg.symbol, "킬 스위치")
                continue
            with self.oms.acting(f"{cfg.owner}(MM)"):
                self._requote(cfg)
