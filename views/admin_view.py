"""관리 탭: 사용자 관리, 수수료 설정, 로그인 기록, 데이터베이스, 시스템 초기화."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from rfl_oms import OMS
from rfl_oms.auth import MIN_PASSWORD_LEN, ROLE_PERMS, AuthError, Perm, Role
from rfl_oms.fees import FeeSchedule

from .common import can, current_user
from .runtime import runtime


def users_section() -> None:
    store = runtime().store
    me = current_user()
    rows = store.list_users()
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "아이디": r["username"],
                    "이름": r["display_name"],
                    "역할": r["role"],
                    "상태": "활성" if r["active"] else "비활성",
                    "잠금": "잠김" if r["locked_until"] else "",
                    "생성": r["created_at"][:16].replace("T", " "),
                }
                for r in rows
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**사용자 추가**")
        with st.form("new_user", clear_on_submit=True):
            username = st.text_input("아이디")
            name = st.text_input("이름")
            role = st.selectbox("역할", list(Role), format_func=lambda r: r.value)
            pw = st.text_input(f"초기 비밀번호 ({MIN_PASSWORD_LEN}자 이상, 문자+숫자)", type="password")
            if st.form_submit_button("추가", type="primary"):
                try:
                    store.create_user(username, name, role, pw, by=me.username)
                    st.toast(f"{username} 추가")
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
    with c2:
        st.markdown("**사용자 변경**")
        names = [r["username"] for r in rows]
        target = st.selectbox("대상", names, key="admin_target")
        u = store.get_user(target)
        if u:
            with st.form("edit_user"):
                role = st.selectbox("역할", list(Role), index=list(Role).index(u.role), format_func=lambda r: r.value)
                active = st.checkbox("활성", value=u.active)
                new_pw = st.text_input("비밀번호 재설정 (비우면 유지)", type="password")
                if st.form_submit_button("저장"):
                    try:
                        if target == me.username and (role is not Role.ADMIN or not active):
                            raise AuthError("자기 자신의 관리자 권한은 해제할 수 없습니다")
                        store.update_user(target, role=role, active=active, by=me.username)
                        if new_pw:
                            store.set_password(target, new_pw, by=me.username)
                        st.toast("저장했습니다")
                        st.rerun()
                    except AuthError as e:
                        st.error(str(e))
            if st.button("잠금 해제", key="unlock_btn"):
                store.unlock(target, by=me.username)
                st.toast(f"{target} 잠금 해제")
                st.rerun()

    with st.expander("역할별 권한"):
        st.dataframe(
            pd.DataFrame(
                [{"권한": p.value, **{r.value: "✅" if p in ROLE_PERMS[r] else "" for r in Role}} for p in Perm]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption("업무 분리: 주문은 트레이더만, 한도 변경은 리스크 관리자만, 사용자 관리는 관리자만 할 수 있습니다.")


def fees_section(oms: OMS) -> None:
    f = oms.fees
    with st.form("fees"):
        enabled = st.checkbox("거래비용 반영", value=f.enabled)
        c = st.columns(4)
        eq = c[0].number_input("주식 수수료(bp)", 0.0, 100.0, f.equity_commission_bps, 0.1)
        tax = c[1].number_input("주식 매도세(bp)", 0.0, 100.0, f.equity_sell_tax_bps, 0.5, help="시뮬레이션 가정값입니다. 실제 세율로 조정하세요.")
        gold = c[2].number_input("금 현물 수수료(bp)", 0.0, 100.0, f.gold_commission_bps, 0.1)
        fut = c[3].number_input("선물 수수료(bp)", 0.0, 100.0, f.futures_commission_bps, 0.05)
        if st.form_submit_button("수수료 저장"):
            oms.set_fees(FeeSchedule(enabled, eq, tax, gold, fut))
            st.success("저장했습니다 (이후 체결부터 적용)")


def db_section(oms: OMS) -> None:
    rt = runtime()
    store = rt.store
    counts = {t: store.query(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in ("orders", "fills", "positions", "audit", "alerts", "users", "auth_log")}  # noqa: S608
    st.caption(f"DB 파일: `{store.path}` · 시작 시 {'저장된 상태를 복원함' if rt.restored else '새로 시작함'}")
    st.dataframe(pd.DataFrame([counts]), hide_index=True, width="stretch")


def auth_log_section() -> None:
    rows = runtime().store.query("SELECT ts, username, event, detail FROM auth_log ORDER BY id DESC LIMIT 300")
    st.dataframe(
        pd.DataFrame([dict(r) for r in rows]).rename(columns={"ts": "시각", "username": "아이디", "event": "이벤트", "detail": "내용"}),
        hide_index=True,
        width="stretch",
    )


def reset_section() -> None:
    st.warning("모든 주문·체결·포지션·감사 로그·알고·바스켓·차익 기록을 지우고 새 시장으로 시작합니다. 사용자 계정과 로그인 기록은 유지됩니다.")
    confirm = st.text_input("확인하려면 '초기화'를 입력하세요", key="reset_confirm")
    if st.button("거래 데이터 초기화", type="primary", disabled=confirm != "초기화"):
        rt = runtime()
        rt.reset_trading()
        rt.store.log_auth(current_user().username, "시스템 초기화", "거래 데이터 삭제")
        st.success("초기화했습니다")
        st.rerun()


def admin_view(oms: OMS) -> None:
    if can(Perm.MANAGE_USERS):
        st.markdown("#### 사용자")
        users_section()
    if can(Perm.SET_FEES):
        st.markdown("#### 거래비용")
        fees_section(oms)
    if can(Perm.MANAGE_USERS):
        st.markdown("#### 데이터베이스")
        db_section(oms)
        with st.expander("로그인 기록"):
            auth_log_section()
    if can(Perm.RESET_SYSTEM):
        with st.expander("시스템 초기화"):
            reset_section()
