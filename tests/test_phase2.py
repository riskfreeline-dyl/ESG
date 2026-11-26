import pandas as pd
import pytest

from rfl_oms import OMS, AlgoStatus, AlgoType, ExecMode, ExecParams, MarketSim, OrderStatus, RiskLimits, Side
from rfl_oms.basket import normalize_symbol, parse_side, sample_template


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=11))


# ------------------------------ 알고리즘 ------------------------------
def test_twap_tracks_linear_schedule(oms):
    algo = oms.algos.start("005930", Side.BUY, 3_000, AlgoType.TWAP, duration=30)
    for k in range(1, 31):
        oms.step()
        if k in (10, 20):
            assert abs(oms.algos.filled(algo) - 3_000 * k / 30) <= 1
    assert algo.status is AlgoStatus.DONE
    assert oms.positions["005930"].qty == 3_000
    assert all(oms.orders[i].strategy_tag == algo.algo_id for i in algo.child_ids)


def test_vwap_front_loads_at_session_open(oms):
    vwap = oms.algos.start("005930", Side.BUY, 6_000, AlgoType.VWAP, duration=60)
    twap = oms.algos.start("000660", Side.BUY, 1_000, AlgoType.TWAP, duration=60)
    oms.step(15)
    # 장 시작 구간은 거래량이 많으므로 VWAP 진행률이 TWAP보다 빠르다
    assert oms.algos.filled(vwap) / 6_000 > oms.algos.filled(twap) / 1_000
    oms.step(45)
    assert vwap.status is AlgoStatus.DONE


def test_pov_follows_market_volume(oms):
    big = 10**13
    oms.limits = RiskLimits(capital=big, max_order_qty=10**9, max_order_notional=big, max_position_notional=big, max_gross_exposure=big)
    algo = oms.algos.start("005930", Side.SELL, 50_000, AlgoType.POV, duration=20, participation=0.1)
    oms.step(20)
    expected = int(algo.mkt_volume * 0.1)
    assert expected > 0
    assert abs(oms.algos.filled(algo) - expected) <= 1
    assert algo.status is AlgoStatus.EXPIRED


def test_algo_limit_price_blocks_children(oms):
    ask = oms.market.quote("005930").ask
    algo = oms.algos.start("005930", Side.BUY, 1_000, AlgoType.TWAP, duration=10, limit_price=ask - 5_000)
    oms.step(10)
    assert oms.algos.filled(algo) == 0 and algo.child_ids == []


def test_algo_parent_risk_check_and_reservation():
    oms = OMS(market=MarketSim(seed=5), limits=RiskLimits(capital=100_000_000))
    big = oms.algos.start("005930", Side.BUY, 5_000, AlgoType.TWAP, duration=10)  # 약 3.6억
    assert big.status is AlgoStatus.HALTED and "증거금" in big.halt_reason
    ok = oms.algos.start("005930", Side.BUY, 1_000, AlgoType.TWAP, duration=10)
    assert ok.status is AlgoStatus.RUNNING
    # 알고 잔량은 노출에 잡히므로 같은 방향 추가 주문 여력이 줄어든다
    assert oms.exposure().symbol_qty["005930"] == 1_000


def test_algo_pause_resume_cancel(oms):
    algo = oms.algos.start("005930", Side.BUY, 3_000, AlgoType.TWAP, duration=30)
    oms.step(5)
    oms.algos.pause(algo.algo_id)
    before = oms.algos.filled(algo)
    oms.step(5)
    assert oms.algos.filled(algo) == before
    oms.algos.resume(algo.algo_id)
    oms.step(1)
    assert oms.algos.filled(algo) > before  # 밀린 목표를 따라잡음
    oms.algos.cancel(algo.algo_id)
    oms.step(5)
    assert algo.status is AlgoStatus.CANCELED
    assert oms.exposure().symbol_qty["005930"] == oms.positions["005930"].qty


def test_kill_switch_cancels_algos(oms):
    algo = oms.algos.start("005930", Side.BUY, 3_000, AlgoType.TWAP, duration=30)
    oms.set_kill_switch(True)
    assert algo.status is AlgoStatus.CANCELED


def test_slippage_sign(oms):
    algo = oms.algos.start("005930", Side.BUY, 300, AlgoType.TWAP, duration=3)
    oms.step(3)
    slip = oms.algos.slippage_bps(algo, algo.arrival_price)
    expected = (oms.algos.avg_price(algo) / algo.arrival_price - 1) * 1e4
    assert slip == pytest.approx(expected)


# ------------------------------ 바스켓 ------------------------------
def test_parse_helpers():
    assert parse_side("buy") is Side.BUY and parse_side("매도") is Side.SELL
    assert normalize_symbol(5930) == "005930" and normalize_symbol("5930.0") == "005930"
    with pytest.raises(ValueError):
        parse_side("hold")


def test_build_by_qty_with_errors(oms):
    df = pd.DataFrame({"종목코드": ["005930", "XXXX", "000660"], "구분": ["매수", "매수", "보유"], "수량": [10, 5, 3]})
    lines, errors = oms.baskets.build_lines(df, by="수량")
    assert [ln.symbol for ln in lines] == ["005930"]
    assert len(errors) == 2


def test_build_by_weight(oms):
    lines, errors = oms.baskets.build_lines(sample_template(), by="비중", target_notional=100_000_000)
    assert not errors
    total = sum(ln.qty * oms.market.mark(ln.symbol) for ln in lines)
    assert 95_000_000 < total <= 100_000_000
    samsung = next(ln for ln in lines if ln.symbol == "005930")
    assert samsung.qty == int(30_000_000 // oms.market.mark("005930"))


def test_weight_requires_target(oms):
    lines, errors = oms.baskets.build_lines(sample_template(), by="비중")
    assert not lines and errors


def test_one_click_market_basket(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("테스트", lines, ExecParams(mode=ExecMode.MARKET))
    s = oms.baskets.summary(b)
    assert s["수량 체결률"] == 1.0 and s["완료 종목"] == 5
    assert all(oms.orders[i].strategy_tag == b.basket_id for ln in b.lines for i in ln.order_ids)


def test_basket_risk_rejection_flags_line_and_alerts():
    oms = OMS(market=MarketSim(seed=3), limits=RiskLimits(restricted_symbols=frozenset({"000660"})))
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("제한 포함", lines, ExecParams())
    bad = next(ln for ln in b.lines if ln.symbol == "000660")
    assert "거래 제한" in bad.error
    assert oms.baskets.line_status(bad) == "거부"
    assert any(a.category == "바스켓 실행" and "거부 1건" in a.message for a in oms.alerts)


def test_auto_retry_when_liquidity_short(oms):
    top = sum(v for _, v in oms.market.book("005380")["asks"])
    lines, _ = oms.baskets.build_lines(
        pd.DataFrame({"종목코드": ["005380"], "구분": ["매수"], "수량": [top + 100]}), by="수량"
    )
    big = 10**13
    oms.limits = RiskLimits(capital=big, max_order_qty=10**9, max_order_notional=big, max_position_notional=big, max_gross_exposure=big)
    b = oms.baskets.execute("유동성", lines, ExecParams(mode=ExecMode.MARKET, auto_retry=True))
    ln = b.lines[0]
    assert oms.baskets.line_filled(ln)[0] == top  # 5단계 호가 소진
    oms.step(1)
    assert ln.retries == 1 and oms.baskets.line_filled(ln)[0] == ln.qty


def test_passive_basket_cancel_reprice_retry(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("패시브", lines, ExecParams(mode=ExecMode.PASSIVE, offset_ticks=10))
    assert oms.baskets.summary(b)["진행 중 수량"] == sum(ln.qty for ln in lines)
    b.params.offset_ticks = 0
    assert oms.baskets.reprice(b.basket_id) == 5
    assert oms.baskets.cancel(b.basket_id) == 5
    assert all(oms.orders[i].status is OrderStatus.CANCELED for ln in b.lines for i in ln.order_ids)
    b.params.mode = ExecMode.MARKET
    assert oms.baskets.retry(b.basket_id) == 5
    assert oms.baskets.summary(b)["수량 체결률"] == 1.0


def test_algo_basket(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("TWAP 바스켓", lines, ExecParams(mode=ExecMode.TWAP, duration=10))
    assert all(len(ln.algo_ids) == 1 for ln in b.lines)
    oms.step(10)
    assert oms.baskets.summary(b)["수량 체결률"] == 1.0


def test_templates(oms):
    oms.baskets.save_template("코어5", sample_template())
    df = oms.baskets.load_template("코어5")
    df.loc[0, "수량"] = 1
    assert oms.baskets.load_template("코어5").loc[0, "수량"] == 500  # 원본 보존


def test_amount_fill_rate_ignores_price_moves(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("가격변동", lines, ExecParams(mode=ExecMode.MARKET))
    oms.market.set_price("005930", oms.market.mark("005930") * 1.05)
    assert oms.baskets.summary(b)["금액 체결률"] == pytest.approx(1.0)
