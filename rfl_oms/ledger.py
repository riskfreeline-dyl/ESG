"""전략별 손익 계산 공용 도우미: 주문 묶음의 현금흐름 + 남은 보유분 평가."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .engine import OMS
    from .models import Order


def net_holdings(orders: Iterable["Order"]) -> dict[str, int]:
    net: dict[str, int] = {}
    for o in orders:
        if o.filled_qty:
            net[o.symbol] = net.get(o.symbol, 0) + o.side.sign * o.filled_qty
    return net


def orders_pnl(oms: "OMS", orders: list["Order"]) -> dict[str, float]:
    """{'손익': 비용 전, '비용': 수수료·세금, '순손익': 비용 후}"""
    gross = 0.0
    for o in orders:
        if o.filled_qty:
            gross -= o.side.sign * o.filled_qty * o.avg_fill_price * oms.instruments[o.symbol].multiplier
    for sym, q in net_holdings(orders).items():
        gross += q * oms.market.mark(sym) * oms.instruments[sym].multiplier
    ids = {o.order_id for o in orders}
    fees = sum(f.fee for f in oms.fills if f.order_id in ids)
    return {"손익": gross, "비용": fees, "순손익": gross - fees}
