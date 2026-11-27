import pytest

from rfl_oms import OMS, ArbDirection, ArbStatus, MarketSim, RiskLimits, Side
from rfl_oms.analytics import exposure_by_asset_class, stress_test, value_at_risk
from rfl_oms.models import OrderType

BIG = 10**13


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=21))


def roomy(oms):
    oms.limits = RiskLimits(
        capital=BIG, max_order_qty=10**9, max_order_notional=BIG, max_position_notional=BIG, max_gross_exposure=BIG
    )


# ------------------------------ 시장·지수 ------------------------------
def test_futures_tracks_fair_value(oms):
    devs = []
    for _ in range(300):
        oms.market.step()
        devs.append(oms.market.mark("K200F") - oms.market.fair_futures())
    assert abs(sum(devs) / len(devs)) < 0.3
    assert max(abs(d) for d in devs) < 3.0


def test_index_unit_replicates_one_contract(oms):
    idx = oms.market.index_def
    basket_value = sum(q * oms.market.mark(s) for s, q in idx.constituents.items())
    futures_notional = oms.market.index_value() * oms.instruments["K200F"].multiplier
    assert basket_value == pytest.approx(futures_notional)


def test_fair_value_carry(oms):
    idx = oms.market.index_def
    assert idx.fair_futures(100.0) == pytest.approx(100 * (1 + (0.035 - 0.015) * 30 / 365))


def test_equities_are_correlated(oms):
    import numpy as np

    for _ in range(300):
        oms.market.step()
    a = np.diff(np.log([p for _, p in oms.market.history["005930"]]))
    b = np.diff(np.log([p for _, p in oms.market.history["000660"]]))
    assert np.corrcoef(a, b)[0, 1] > 0.2


# ------------------------------ 차익거래 ------------------------------
def test_snapshot_edges(oms):
    snap = oms.arb.snapshot()
    assert snap.sell_edge == pytest.approx(snap.fut_bid - snap.fair - snap.cost_pts)
    assert snap.buy_edge == pytest.approx(snap.fair - snap.fut_ask - snap.cost_pts)
    assert snap.cost_pts == pytest.approx(snap.index * oms.arb.costs.round_trip_bps() / 1e4)


def test_sell_arb_enter_is_hedged_and_close_flattens(oms):
    roomy(oms)
    pos, problems = oms.arb.enter(ArbDirection.SELL_ARB, 2)
    assert not problems and pos.status is ArbStatus.OPEN
    net = oms.arb.net_holdings(pos)
    assert net["K200F"] == -2
    assert net["005930"] == 2 * oms.market.index_def.constituents["005930"]
    fut, stock = oms.arb.hedge(pos)
    assert abs(fut + stock) / abs(fut) < 0.01  # 반올림 오차 수준
    oms.step(5)
    assert oms.arb.close(pos.arb_id)
    assert all(q == 0 for q in oms.arb.net_holdings(pos).values())
    assert pos.status is ArbStatus.CLOSED
    assert not oms.arb.close(pos.arb_id)


def test_arb_pnl_matches_positions(oms):
    roomy(oms)
    pos, _ = oms.arb.enter(ArbDirection.BUY_ARB, 1)
    oms.step(3)
    # 이 계좌의 유일한 거래이므로 계좌 손익과 같아야 한다
    assert oms.arb.pnl(pos) == pytest.approx(oms.daily_pnl())


def test_arb_rejected_when_any_leg_fails_precheck(oms):
    oms.limits = RiskLimits(restricted_symbols=frozenset({"000660"}))
    pos, problems = oms.arb.enter(ArbDirection.SELL_ARB, 1)
    assert pos is None and any("000660" in p for p in problems)
    assert oms.orders == {}  # 어느 레그도 나가지 않음


def test_auto_entry_and_exit(oms):
    roomy(oms)
    s = oms.arb.settings
    s.auto, s.entry_edge_pts, s.max_open = True, -100.0, 1  # 항상 진입 조건 충족
    oms.step(1)
    assert len(oms.arb.positions) == 1
    pos = next(iter(oms.arb.positions.values()))
    s.entry_edge_pts = 100.0  # 재진입 금지
    s.exit_mispricing_pts = 100.0  # 즉시 청산 조건
    oms.step(1)
    assert pos.status is ArbStatus.CLOSED and "자동" in pos.note


def test_leg_error_detected(oms):
    roomy(oms)
    pos, _ = oms.arb.enter(ArbDirection.SELL_ARB, 1)
    basket = oms.baskets.baskets[pos.basket_ids[0]]
    basket.lines[0].error = "테스트 실패"
    oms.arb._check_legs(pos, False, basket)
    assert pos.status is ArbStatus.LEG_ERROR
    assert any(a.category == "차익 레그 불일치" for a in oms.alerts)


# ------------------------------ 리스크 분석 ------------------------------
def test_exposure_by_asset_class(oms):
    roomy(oms)
    oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
    oms.submit("K200F", Side.SELL, OrderType.MARKET, 1)
    df = exposure_by_asset_class(oms).set_index("자산군")
    assert df.loc["주식", "매수"] > 0 and df.loc["주가지수선물", "매도"] < 0
    assert df.loc["주가지수선물", "총노출"] == pytest.approx(abs(df.loc["주가지수선물", "순노출"]))


def test_var_needs_history_then_positive(oms):
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    assert value_at_risk(oms).historical is None
    oms.step(60)
    v = value_at_risk(oms)
    assert v.historical > 0 and v.parametric > 0 and v.observations >= 20


def test_hedged_book_has_lower_var(oms):
    roomy(oms)
    oms.step(80)
    oms.submit("K200F", Side.SELL, OrderType.MARKET, 1)
    naked = value_at_risk(oms).parametric
    for s, q in oms.market.index_def.constituents.items():
        oms.submit(s, Side.BUY, OrderType.MARKET, q)
    hedged = value_at_risk(oms).parametric
    assert hedged < naked * 0.8


def test_stress_test(oms):
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    df = stress_test(oms).set_index("시나리오")
    notional = 1_000 * oms.market.mark("005930")
    assert df.loc["주가 급락 (−5%)", "예상 손익"] == pytest.approx(-0.05 * notional)
    assert df.loc["금 급락 (−5%)", "예상 손익"] == 0


def test_pnl_history_recorded(oms):
    oms.step(5)
    assert len(oms.pnl_history) == 6 and oms.pnl_history[-1][0] == 5
