import math

import pytest

from rfl_oms import OMS, ArbDirection, MarketSim, RiskLimits, Side
from rfl_oms.analytics import stress_test
from rfl_oms.models import OrderStatus, OrderType
from rfl_oms.options import black76, chain, delta_hedge_qty, payoff, portfolio_greeks
from rfl_oms.pairs import PairDirection

BIG = 10**13


@pytest.fixture
def oms():
    o = OMS(market=MarketSim(seed=41))
    o.limits = RiskLimits(
        capital=BIG, max_order_qty=10**9, max_order_notional=BIG, max_position_notional=BIG, max_gross_exposure=BIG
    )
    return o


# ------------------------------ 시장 연결 ------------------------------
def test_carry_futures_track_fair(oms):
    for _ in range(200):
        oms.market.step()
    for c in oms.market.carry_links:
        fair = c.fair_futures(oms.market.mark(c.spot_symbol))
        assert abs(oms.market.mark(c.futures_symbol) / fair - 1) < 0.003, c.name


def test_fx_futures_discount_from_rate_gap(oms):
    c = oms.market.carry_link("USDF")
    assert c.rate < c.dividend_yield and c.fair_futures(1000) < 1000  # 달러 금리가 더 높으면 선물 할인


def test_pair_is_mean_reverting(oms):
    for _ in range(400):
        oms.market.step()
    r = [math.log(pa / pb) for (_, pa), (_, pb) in zip(oms.market.history["005380"], oms.market.history["000270"])]
    assert max(r) - min(r) < 0.06


# ------------------------------ 외환·채권·금 차익 ------------------------------
@pytest.mark.parametrize("fsym,spot,units", [("USDF", "USDKRW", 10_000), ("KTBF", "KTB3Y", 100), ("GOLDF", "GOLD", 100)])
def test_carry_arb_enter_close(oms, fsym, spot, units):
    eng = oms.carry_arbs[fsym]
    pos, problems = eng.enter(ArbDirection.SELL_ARB, 2)
    assert not problems
    net = eng.net_holdings(pos)
    assert net[fsym] == -2 and net[spot] == 2 * units
    fut, stk = eng.hedge(pos)
    assert abs(fut + stk) / abs(fut) < 0.02  # 차이는 보유비용(캐리)만큼
    oms.step(3)
    assert eng.close(pos.arb_id)
    assert all(q == 0 for q in eng.net_holdings(pos).values())
    assert eng.pnl_net(pos) == pytest.approx(eng.pnl(pos) - eng.fees(pos))


def test_carry_arb_ids_and_auto(oms):
    eng = oms.carry_arbs["USDF"]
    eng.settings.auto, eng.settings.entry_edge_pts, eng.settings.max_open = True, -1e9, 1
    oms.step(1)
    assert list(eng.positions)[0].startswith("FX")
    assert len(eng.open_positions()) == 1


# ------------------------------ 페어 트레이딩 ------------------------------
def test_pair_stat_needs_history(oms):
    assert not oms.pairs.stat("005380", "000270").ready
    pos, problems = oms.pairs.enter("005380", "000270")
    assert pos is None and problems


def test_pair_enter_sizes_and_close(oms):
    oms.step(80)
    st = oms.pairs.stat("005380", "000270")
    assert st.ready and st.beta is not None and st.half_life is not None  # 공적분 쌍은 반감기 존재
    pos, _ = oms.pairs.enter("005380", "000270", PairDirection.SHORT_A)
    assert pos.qty_a == int(oms.pairs.settings.notional // oms.market.mark("005380")) or pos.qty_a > 0
    assert oms.positions["005380"].qty == -pos.qty_a and oms.positions["000270"].qty == pos.qty_b
    assert oms.pairs.close(pos.pair_id)
    assert oms.positions["005380"].qty == 0 and oms.positions["000270"].qty == 0
    p = oms.pairs.pnl(pos)
    assert p["순손익"] == pytest.approx(p["손익"] - p["비용"])


def test_pair_auto_trades(oms):
    s = oms.pairs.settings
    s.auto, s.auto_owner, s.entry_z = True, "kim", 1.5
    oms.step(250)
    assert oms.pairs.positions, "자동 진입이 한 번도 없음"
    assert all(oms.orders[i].trader == "kim(자동)" for p in oms.pairs.positions.values() for i in p.order_ids)


# ------------------------------ 마켓메이킹 ------------------------------
def test_mm_quotes_two_sided_and_passive(oms):
    with oms.acting("kim"):
        oms.mm.enable("USDKRW")
    cfg = oms.mm.configs["USDKRW"]
    bid, ask = oms.orders[cfg.bid_id], oms.orders[cfg.ask_id]
    q = oms.market.quote("USDKRW")
    assert bid.side is Side.BUY and ask.side is Side.SELL
    assert bid.limit_price < q.ask and ask.limit_price > q.bid  # 즉시 체결되지 않는 대기 호가
    assert bid.status.is_open and ask.status.is_open and bid.rested


def test_mm_fills_at_quote_price_and_respects_inventory(oms):
    cfg = oms.mm.configs["KTB3Y"]
    cfg.max_inventory = cfg.size * 2
    with oms.acting("kim"):
        oms.mm.enable("KTB3Y")
    oms.step(200)
    filled = [o for o in oms.mm.orders(cfg) if o.filled_qty]
    assert filled
    for o in filled:  # 대기 호가는 자기 지정가로 체결
        assert o.avg_fill_price == pytest.approx(o.limit_price)
    assert abs(oms.mm.inventory(cfg)) <= cfg.max_inventory


def test_mm_stops_on_kill_switch(oms):
    with oms.acting("kim"):
        oms.mm.enable("GOLD")
    oms.set_kill_switch(True)
    oms.step(1)
    cfg = oms.mm.configs["GOLD"]
    assert not cfg.enabled and cfg.stop_reason == "킬 스위치"
    assert not [o for o in oms.mm.orders(cfg) if o.status.is_open]


def test_mm_disabled_when_quote_rejected(oms):
    oms.limits = RiskLimits(restricted_symbols=frozenset({"GOLD"}))
    with oms.acting("kim"):
        oms.mm.enable("GOLD")
    cfg = oms.mm.configs["GOLD"]
    assert not cfg.enabled and "거부" in cfg.stop_reason
    assert any(a.category == "마켓메이킹 중지" for a in oms.alerts)


# ------------------------------ 옵션 ------------------------------
def test_black76_put_call_parity():
    F, K, T, r, v = 350.0, 345.0, 30 / 365, 0.035, 0.2
    c, p = black76(F, K, T, r, v, "C"), black76(F, K, T, r, v, "P")
    assert c.price - p.price == pytest.approx(math.exp(-r * T) * (F - K))
    h = 1e-3
    fd = (black76(F + h, K, T, r, v, "C").price - black76(F - h, K, T, r, v, "C").price) / (2 * h)
    assert c.delta == pytest.approx(fd, rel=1e-4)
    assert c.theta < 0 and p.theta < 0


def test_option_chain_and_prices_follow_underlying(oms):
    rows = chain(oms)
    assert len(rows) == 9 and all("콜 종목" in r and "풋 종목" in r for r in rows)
    sym = rows[4]["콜 종목"]
    before = oms.market.mark(sym)
    oms.market.set_price("K200F", oms.market.mark("K200F") + 5)
    oms.market._price_option(sym)
    assert oms.market.mark(sym) > before


def test_short_option_margin_addon(oms):
    sym = chain(oms)[4]["풋 종목"]
    oms.submit(sym, Side.SELL, OrderType.MARKET, 4)
    prem = 4 * oms.market.mark(sym) * 250_000
    F = oms.market.mark("K200F")
    assert oms.position_margin(sym, -4) == pytest.approx(prem + 4 * F * 250_000 * 0.15)
    assert oms.position_margin(sym, 4) == pytest.approx(prem)


def test_delta_hedge_neutralizes(oms):
    sym = chain(oms)[5]["콜 종목"]
    oms.submit(sym, Side.BUY, OrderType.MARKET, 20)
    q = delta_hedge_qty(oms)
    assert q < 0
    oms.submit("K200F", Side.SELL, OrderType.MARKET, -q)
    assert abs(portfolio_greeks(oms)["델타(선물 계약)"]) <= 0.5


def test_option_stress_is_nonlinear_and_isolated(oms):
    sym = chain(oms)[4]["콜 종목"]
    oms.submit(sym, Side.BUY, OrderType.MARKET, 2)
    df = stress_test(oms).set_index("시나리오")
    up, down = df.loc["주가 급등 (+5%)", "예상 손익"], df.loc["주가 급락 (−5%)", "예상 손익"]
    assert up > 0 > down and up > -down  # 콜 매수: 상승 이익이 하락 손실보다 큼 (볼록성)
    assert df.loc["금 급락 (−5%)", "예상 손익"] == 0
    assert df.loc["변동성 급등 (옵션 +5%p)", "예상 손익"] > 0


def test_payoff_long_call_shape(oms):
    sym = chain(oms)[4]["콜 종목"]
    oms.submit(sym, Side.BUY, OrderType.MARKET, 1)
    pts = payoff(oms)
    assert pts[0][2] == pytest.approx(pts[1][2])  # 깊은 외가격 구간: 만기 손익 = −프리미엄 (평평)
    assert pts[-1][2] > pts[-2][2] > 0


def test_resting_order_fills_at_limit(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    assert o.rested and o.status is OrderStatus.WORKING
    oms.market.set_price("005930", q.bid - 2_000)
    oms._match(o)
    assert o.avg_fill_price == q.bid - 500
