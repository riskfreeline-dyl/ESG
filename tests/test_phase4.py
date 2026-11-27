import pytest

from rfl_oms import OMS, AlgoType, ArbDirection, MarketSim, RiskLimits, Side
from rfl_oms.auth import ROLE_PERMS, AuthError, Perm, Role
from rfl_oms.fees import FeeSchedule
from rfl_oms.models import OrderType
from rfl_oms.storage import Store

BIG = 10**13


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=31))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def roomy(oms):
    oms.limits = RiskLimits(
        capital=BIG, max_order_qty=10**9, max_order_notional=BIG, max_position_notional=BIG, max_gross_exposure=BIG
    )


# ------------------------------ 거래비용 ------------------------------
def test_fees_per_fill_and_net_pnl(oms):
    buy = oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
    sell = oms.submit("005930", Side.SELL, OrderType.MARKET, 100)
    f_buy, f_sell = oms.fills[0], oms.fills[1]
    assert f_buy.fee == pytest.approx(100 * buy.avg_fill_price * 1.0 / 1e4)  # 수수료 1bp
    assert f_sell.fee == pytest.approx(100 * sell.avg_fill_price * 16.0 / 1e4)  # 수수료 1bp + 매도세 15bp
    gross = oms.realized_pnl()
    assert oms.daily_pnl() == pytest.approx(gross - f_buy.fee - f_sell.fee)
    assert oms.positions["005930"].fees == pytest.approx(f_buy.fee + f_sell.fee)


def test_futures_fee_and_disable(oms):
    o = oms.submit("K200F", Side.BUY, OrderType.MARKET, 1)
    assert oms.fills[-1].fee == pytest.approx(o.avg_fill_price * 250_000 * 0.3 / 1e4)
    oms.set_fees(FeeSchedule(enabled=False))
    oms.submit("K200F", Side.SELL, OrderType.MARKET, 1)
    assert oms.fills[-1].fee == 0
    assert any(e.event == "수수료 변경" for e in oms.audit)


def test_fees_count_toward_loss_limit():
    oms = OMS(market=MarketSim(seed=1), limits=RiskLimits(max_daily_loss=100_000))
    for _ in range(3):
        oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
        oms.submit("005930", Side.SELL, OrderType.MARKET, 1_000)
    assert oms.daily_pnl() < -100_000  # 왕복 비용 + 스프레드로 손실 한도 초과
    blocked = oms.submit("005930", Side.BUY, OrderType.MARKET, 10)
    assert "일일 손실" in blocked.reject_reason


# ------------------------------ 헤지 증거금 상계 ------------------------------
def test_hedge_credit_reduces_margin(oms):
    roomy(oms)
    pos, _ = oms.arb.enter(ArbDirection.SELL_ARB, 1)
    mb = oms.margin_breakdown()
    fut_margin = abs(oms.positions["K200F"].qty) * oms.market.mark("K200F") * 250_000 * 0.10
    assert mb["헤지 상계"] == pytest.approx(min(fut_margin, mb["헤지 상계"] / 0.7 * 0.7))
    assert 0 < mb["헤지 상계"] <= fut_margin * 0.7 + 1
    assert mb["순증거금"] == pytest.approx(mb["상계 전"] - mb["헤지 상계"])
    oms.limits.margin_offset_enabled = False
    assert oms.margin_breakdown()["헤지 상계"] == 0


def test_no_credit_for_same_direction(oms):
    roomy(oms)
    oms.submit("K200F", Side.BUY, OrderType.MARKET, 1)
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    assert oms.margin_breakdown()["헤지 상계"] == 0


def test_working_order_that_breaks_hedge_removes_credit(oms):
    roomy(oms)
    oms.arb.enter(ArbDirection.SELL_ARB, 1)
    with_credit = oms.exposure().hedge_credit
    assert with_credit > 0
    # 선물을 되사는 미체결 주문이 있으면 헤지가 깨질 수 있으므로 상계를 인정하지 않는다
    bid = oms.market.quote("K200F").bid
    oms.submit("K200F", Side.BUY, OrderType.LIMIT, 1, limit_price=round(bid - 1.0, 2))
    assert oms.exposure().hedge_credit == 0


def test_hedge_credit_frees_room_for_orders():
    lim = dict(max_order_qty=10**9, max_order_notional=BIG, max_position_notional=BIG, max_gross_exposure=BIG)
    a = OMS(market=MarketSim(seed=4), limits=RiskLimits(capital=200_000_000, **lim))
    a.arb.enter(ArbDirection.SELL_ARB, 1)
    b = OMS(market=MarketSim(seed=4), limits=RiskLimits(capital=200_000_000, margin_offset_enabled=False, **lim))
    b.arb.enter(ArbDirection.SELL_ARB, 1)
    assert a.exposure().margin < b.exposure().margin


# ------------------------------ 행위자 기록 ------------------------------
def test_actor_recorded_on_orders_algos_and_system_events(oms):
    roomy(oms)
    with oms.acting("kim"):
        o = oms.submit("005930", Side.BUY, OrderType.MARKET, 10)
        algo = oms.algos.start("000660", Side.BUY, 300, AlgoType.TWAP, duration=3)
    oms.step(3)  # 틱 처리 중의 자식 주문은 알고를 시작한 사용자로 기록
    with oms.acting("risk1"):
        oms.set_kill_switch(True)
        oms.set_kill_switch(False)
    assert o.trader == "kim" and all(e.actor == "kim" for e in o.events)
    assert all(oms.orders[i].trader == "kim" for i in algo.child_ids) and algo.child_ids
    ks = [e for e in oms.audit if e.event == "킬 스위치"]
    assert len(ks) == 2 and all(e.actor == "risk1" and e.order_id == "-" for e in ks)


def test_set_limits_is_audited(oms):
    with oms.acting("risk1"):
        oms.set_limits(RiskLimits(max_order_qty=500))
    ev = [e for e in oms.audit if e.event == "한도 변경"][-1]
    assert "max_order_qty: 10000 → 500" in ev.detail and ev.actor == "risk1"


# ------------------------------ 권한 ------------------------------
def test_segregation_of_duties():
    assert Perm.TRADE in ROLE_PERMS[Role.TRADER]
    assert Perm.TRADE not in ROLE_PERMS[Role.RISK] and Perm.TRADE not in ROLE_PERMS[Role.ADMIN]
    assert Perm.SET_LIMITS in ROLE_PERMS[Role.RISK] and Perm.SET_LIMITS not in ROLE_PERMS[Role.TRADER]
    assert Perm.MANAGE_USERS in ROLE_PERMS[Role.ADMIN] and Perm.MANAGE_USERS not in ROLE_PERMS[Role.RISK]


# ------------------------------ 사용자·로그인 ------------------------------
def test_create_and_authenticate(store):
    assert not store.has_users()
    store.create_user("admin", "관리자", Role.ADMIN, "Secret123")
    assert store.has_users()
    u = store.authenticate("admin", "Secret123")
    assert u.role is Role.ADMIN and u.can(Perm.MANAGE_USERS)
    row = store.query("SELECT pw_hash, salt FROM users WHERE username='admin'")[0]
    assert "Secret123" not in row["pw_hash"] and len(row["salt"]) == 32


def test_password_policy_and_duplicates(store):
    with pytest.raises(AuthError):
        store.create_user("a", "A", Role.TRADER, "short1")
    with pytest.raises(AuthError):
        store.create_user("a", "A", Role.TRADER, "onlyletters")
    with pytest.raises(AuthError):
        store.create_user("bad name", "A", Role.TRADER, "Passw0rd!")
    store.create_user("a", "A", Role.TRADER, "Passw0rd1")
    with pytest.raises(AuthError):
        store.create_user("a", "A2", Role.TRADER, "Passw0rd1")


def test_lockout_after_failures(store):
    store.create_user("t1", "트레이더", Role.TRADER, "Passw0rd1")
    for _ in range(5):
        with pytest.raises(AuthError):
            store.authenticate("t1", "wrong-pass1")
    with pytest.raises(AuthError, match="잠긴"):
        store.authenticate("t1", "Passw0rd1")  # 맞는 비밀번호도 잠금 중에는 거부
    store.unlock("t1", by="admin")
    assert store.authenticate("t1", "Passw0rd1").username == "t1"
    events = [r["event"] for r in store.query("SELECT event FROM auth_log WHERE username='t1'")]
    assert events.count("로그인 실패") == 5 and "로그인 거부" in events and "잠금 해제" in events


def test_deactivate_and_last_admin_protected(store):
    store.create_user("admin", "관리자", Role.ADMIN, "Secret123")
    store.create_user("t1", "트레이더", Role.TRADER, "Passw0rd1")
    store.update_user("t1", active=False, by="admin")
    with pytest.raises(AuthError, match="비활성"):
        store.authenticate("t1", "Passw0rd1")
    with pytest.raises(AuthError, match="마지막"):
        store.update_user("admin", role=Role.TRADER)
    store.create_user("admin2", "관리자2", Role.ADMIN, "Secret123")
    store.update_user("admin", role=Role.RISK, by="admin2")
    assert store.get_user("admin").role is Role.RISK


def test_password_change(store):
    store.create_user("t1", "트레이더", Role.TRADER, "Passw0rd1")
    store.set_password("t1", "NewPass99", by="admin")
    with pytest.raises(AuthError):
        store.authenticate("t1", "Passw0rd1")
    assert store.authenticate("t1", "NewPass99")


# ------------------------------ 저장·복원 ------------------------------
def test_roundtrip_restores_full_engine(store, oms):
    roomy(oms)
    with oms.acting("kim"):
        oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
        q = oms.market.quote("000660")
        resting = oms.submit("000660", Side.BUY, OrderType.LIMIT, 5, limit_price=q.bid - 5_000)
        algo = oms.algos.start("005380", Side.BUY, 200, AlgoType.TWAP, duration=10)
        oms.arb.enter(ArbDirection.SELL_ARB, 1)
    oms.step(3)
    store.save(oms)

    restored = store.load()
    assert restored is not None
    assert restored.market.tick_no == 3
    assert restored.orders[resting.order_id].status.is_open
    assert restored.daily_pnl() == pytest.approx(oms.daily_pnl())
    assert {s: p.qty for s, p in restored.positions.items()} == {s: p.qty for s, p in oms.positions.items()}
    # 복원 후에도 알고가 이어서 동작한다
    restored.step(7)
    assert restored.algos.filled(restored.algos.algos[algo.algo_id]) == 200


def test_ledger_tables_match_engine(store, oms):
    with oms.acting("kim"):
        oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
        oms.submit("005930", Side.SELL, OrderType.MARKET, 40)
    store.save(oms)
    oms.step(2)
    with oms.acting("kim"):
        oms.submit("GOLD", Side.BUY, OrderType.MARKET, 3)
    store.save(oms)  # 두 번째 저장은 증분만 추가
    assert store.query("SELECT COUNT(*) n FROM orders")[0]["n"] == len(oms.orders)
    assert store.query("SELECT COUNT(*) n FROM fills")[0]["n"] == len(oms.fills)
    assert store.query("SELECT COUNT(*) n FROM audit")[0]["n"] == len(oms.audit)
    assert store.query("SELECT COUNT(*) n FROM alerts")[0]["n"] == len(oms.alerts)
    fee_sum = store.query("SELECT SUM(fee) s FROM fills")[0]["s"]
    assert fee_sum == pytest.approx(oms.total_fees())
    pos = {r["symbol"]: r["qty"] for r in store.query("SELECT symbol, qty FROM positions")}
    assert pos == {"005930": 60, "GOLD": 3}
    assert {r["trader"] for r in store.query("SELECT trader FROM orders")} == {"kim"}


def test_order_status_updates_are_upserted(store, oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    store.save(oms)
    oms.cancel(o.order_id)
    store.save(oms)
    row = store.query("SELECT status FROM orders WHERE order_id=?", (o.order_id,))[0]
    assert row["status"] == "취소"


def test_reset_keeps_users(store, oms):
    store.create_user("admin", "관리자", Role.ADMIN, "Secret123")
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1)
    store.save(oms)
    store.reset_trading()
    assert store.load() is None and store.has_users()
    assert store.query("SELECT COUNT(*) n FROM orders")[0]["n"] == 0


def test_pure_python_pbkdf2_matches_hashlib():
    import hashlib

    from rfl_oms.auth import _pbkdf2_sha256_pure

    for pw, salt in [(b"Admin1234", b"0123456789abcdef"), (b"x" * 100, b"salt"), (b"", b"")]:
        assert _pbkdf2_sha256_pure(pw, salt, 500) == hashlib.pbkdf2_hmac("sha256", pw, salt, 500)
