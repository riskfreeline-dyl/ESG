"""로그인, 첫 관리자 생성, 내 비밀번호 변경."""

from __future__ import annotations

import streamlit as st

from rfl_oms.auth import MIN_PASSWORD_LEN, AuthError, Role

from .runtime import runtime


def _setup_admin() -> None:
    st.title("RFL OMS 초기 설정")
    st.info("등록된 사용자가 없습니다. 첫 관리자 계정을 만드세요. 기본 계정이나 기본 비밀번호는 없습니다.")
    with st.form("setup_admin"):
        username = st.text_input("관리자 아이디", placeholder="예: admin")
        name = st.text_input("이름")
        pw = st.text_input(f"비밀번호 ({MIN_PASSWORD_LEN}자 이상, 문자와 숫자 포함)", type="password")
        pw2 = st.text_input("비밀번호 확인", type="password")
        if st.form_submit_button("관리자 계정 만들기", type="primary"):
            if pw != pw2:
                st.error("비밀번호 확인이 일치하지 않습니다")
                return
            try:
                user = runtime().store.create_user(username, name, Role.ADMIN, pw)
            except AuthError as e:
                st.error(str(e))
                return
            st.session_state.username = user.username
            st.rerun()


def _login() -> None:
    st.title("RFL OMS 로그인")
    st.caption("주문관리 · 사전 리스크 점검 — 시세와 체결은 모두 시뮬레이션입니다.")
    with st.form("login"):
        username = st.text_input("아이디")
        pw = st.text_input("비밀번호", type="password")
        if st.form_submit_button("로그인", type="primary"):
            try:
                user = runtime().store.authenticate(username, pw)
            except AuthError as e:
                st.error(str(e))
                return
            st.session_state.username = user.username
            st.rerun()


def require_login():
    """로그인한 User를 돌려준다. 아니면 로그인·설정 화면을 그리고 실행을 멈춘다."""
    store = runtime().store
    if not store.has_users():
        _setup_admin()
        st.stop()
    username = st.session_state.get("username")
    user = store.get_user(username) if username else None
    if user is None or not user.active:
        if user is not None:
            st.warning("계정이 비활성화되어 로그아웃되었습니다.")
        st.session_state.pop("username", None)
        st.session_state.pop("user", None)
        _login()
        st.stop()
    st.session_state.user = user
    return user


def account_sidebar(user) -> None:
    st.sidebar.markdown(f"**{user.display_name}** · {user.role.value}")
    st.sidebar.caption(f"아이디: {user.username}")
    c1, c2 = st.sidebar.columns(2)
    if c1.button("로그아웃", width="stretch"):
        runtime().store.log_auth(user.username, "로그아웃")
        st.session_state.pop("username", None)
        st.session_state.pop("user", None)
        st.rerun()
    with c2.popover("비밀번호", width="stretch"):
        with st.form("own_pw"):
            cur = st.text_input("현재 비밀번호", type="password")
            new = st.text_input("새 비밀번호", type="password")
            new2 = st.text_input("새 비밀번호 확인", type="password")
            if st.form_submit_button("변경"):
                store = runtime().store
                try:
                    store.authenticate(user.username, cur)
                    if new != new2:
                        raise AuthError("새 비밀번호 확인이 일치하지 않습니다")
                    store.set_password(user.username, new, by=user.username)
                    st.success("비밀번호를 변경했습니다")
                except AuthError as e:
                    st.error(str(e))
