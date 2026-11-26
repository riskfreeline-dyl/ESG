import pytest

from rfl_oms import OMS, AlertLevel, MarketSim, OrderStatus, OrderType, RiskLimits, Side, TimeInForce
from rfl_oms.models import Position


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=1))


def statuses(order):
    return [e.event for e in order.events]


def test_market_buy_fills_and_updates_position(oms):
    ask = oms.market.quote("005930").ask
    o = oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
    assert o.status is OrderStatus.FILLED
    assert o.avg_fill_price == ask
    assert oms.positions["005930"].qty == 100
    assert statuses(o)[:4] == ["생성", "검증 통과", "보강", "라우팅"]


def test_passive_limit_rests_then_fills_when_market_moves(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    assert o.status is OrderStatus.WORKING
    oms.market.set_price("005930", q.bid - 1_000)  # 매도호가가 지정가 아래로 내려옴
    for order in oms.open_orders():
        oms._match(order)
    assert o.status is OrderStatus.FILLED
    assert o.avg_fill_price <= q.bid - 500


def test_partial_fill_and_ioc_remainder_canceled():
    big = 10**13
    oms = OMS(
        market=MarketSim(seed=1),
        limits=RiskLimits(capital=big, max_order_notional=big, max_position_notional=big, max_gross_exposure=big),
    )
    book = oms.market.book("K200F")["asks"]
    top_px, top_qty = book[0]
    o = oms.submit(
        "K200F", Side.BUY, OrderType.LIMIT, top_qty + 5, limit_price=top_px, tif=TimeInForce.IOC
    )
    assert o.filled_qty == top_qty
    assert o.status is OrderStatus.CANCELED
    assert "취소" in statuses(o)


def test_order_qty_limit_rejects(oms):
    o = oms.submit("005930", Side.BUY, OrderType.MARKET, 20_000)
    assert o.status is OrderStatus.REJECTED
    assert "주문 수량 한도" in o.reject_reason
    assert any(a.category == "주문 거부" for a in oms.alerts)


def test_off_tick_price_rejected(oms):
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 1, limit_price=72_050)
    assert o.status is OrderStatus.REJECTED
    assert "호가단위" in o.reject_reason


def test_price_band(oms):
    mark = oms.market.mark("005930")
    far = oms.instruments["005930"].round_to_tick(mark * 0.8)
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 1, limit_price=far)
    assert "가격 괴리율" in o.reject_reason


def test_margin_limit_and_risk_reducing_order_allowed():
    oms = OMS(market=MarketSim(seed=2), limits=RiskLimits(capital=100_000_000))
    first = oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)  # 약 7,200만원
    assert first.status is OrderStatus.FILLED
    second = oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    assert second.status is OrderStatus.REJECTED and "증거금" in second.reject_reason
    sell = oms.submit("005930", Side.SELL, OrderType.MARKET, 500)
    assert sell.status is OrderStatus.FILLED


def test_daily_loss_blocks_only_risk_increasing():
    oms = OMS(market=MarketSim(seed=3), limits=RiskLimits(max_daily_loss=1_000_000))
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    oms.market.set_price("005930", oms.market.quote("005930").bid - 2_000)  # 약 -200만원
    oms._evaluate_alerts()
    assert any(a.level is AlertLevel.CRITICAL and "일일 손실" in a.message for a in oms.alerts)
    more = oms.submit("005930", Side.BUY, OrderType.MARKET, 10)
    assert more.status is OrderStatus.REJECTED and "일일 손실" in more.reject_reason
    close = oms.submit("005930", Side.SELL, OrderType.MARKET, 1_000)
    assert close.status is OrderStatus.FILLED


def test_amend_and_cancel(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    ok, _ = oms.amend(o.order_id, new_qty=20, new_limit_price=q.bid - 300)
    assert ok and o.qty == 20 and o.limit_price == q.bid - 300
    ok, _ = oms.amend(o.order_id, new_qty=99_999)
    assert not ok and o.qty == 20
    assert oms.cancel(o.order_id)
    assert o.status is OrderStatus.CANCELED and o.leaves_qty == 0
    assert not oms.cancel(o.order_id)


def test_amend_to_marketable_price_fills(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    oms.amend(o.order_id, new_limit_price=q.ask)
    assert o.status is OrderStatus.FILLED


def test_kill_switch_cancels_and_blocks(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    oms.set_kill_switch(True)
    assert o.status is OrderStatus.CANCELED
    blocked = oms.submit("005930", Side.BUY, OrderType.MARKET, 1)
    assert blocked.status is OrderStatus.REJECTED
    oms.set_kill_switch(False)
    assert oms.submit("005930", Side.BUY, OrderType.MARKET, 1).status is OrderStatus.FILLED


def test_restricted_symbol():
    oms = OMS(limits=RiskLimits(restricted_symbols=frozenset({"GOLD"})))
    assert oms.submit("GOLD", Side.BUY, OrderType.MARKET, 1).status is OrderStatus.REJECTED


def test_preview_does_not_create_order(oms):
    checks = oms.preview("005930", Side.BUY, OrderType.MARKET, 10)
    assert all(c.passed for c in checks)
    assert oms.orders == {}
    assert oms.submit("005930", Side.BUY, OrderType.MARKET, 1).order_id == "O000001"


def test_position_flip_realized_pnl():
    p = Position("X")
    p.apply_fill(Side.BUY, 10, 100.0, 1)
    realized = p.apply_fill(Side.SELL, 15, 110.0, 1)
    assert realized == 100.0
    assert p.qty == -5 and p.avg_price == 110.0


def test_futures_multiplier_pnl(oms):
    o = oms.submit("K200F", Side.BUY, OrderType.MARKET, 1)
    entry = o.avg_fill_price
    oms.market.set_price("K200F", entry + 1.0)
    expected = (oms.market.mark("K200F") - entry) * 250_000
    assert oms.unrealized_pnl("K200F") == pytest.approx(expected)


def test_price_alert_rule_triggers_once(oms):
    mark = oms.market.mark("USDF")
    oms.add_price_rule("USDF", "이상", mark + 0.5)
    oms.market.set_price("USDF", mark + 5)
    oms._check_price_rules()
    oms._check_price_rules()
    assert sum(a.category == "가격 알림" for a in oms.alerts) == 1


def test_warning_alert_dedup(oms):
    oms.limits.max_gross_exposure = 100_000_000
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_200)  # 약 8,640만원 → 86%
    oms.step(3)
    warnings = [a for a in oms.alerts if "총 노출" in a.message]
    assert len(warnings) >= 1
    assert len({a.level for a in warnings}) == len(warnings)  # 같은 단계 알림 중복 없음


def test_simulation_runs(oms):
    oms.submit("USDF", Side.SELL, OrderType.LIMIT, 5, limit_price=oms.market.quote("USDF").ask + 0.3)
    oms.step(200)
    assert oms.market.tick_no == 200


def test_amend_without_change_is_rejected(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    ok, msg = oms.amend(o.order_id, new_qty=10, new_limit_price=q.bid - 500)
    assert not ok and "변경" in msg
