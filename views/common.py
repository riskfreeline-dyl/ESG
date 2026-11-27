"""화면 공용 도우미."""

from __future__ import annotations

import streamlit as st

from rfl_oms import OMS

NUM = st.column_config.NumberColumn(format="localized")
PCT = st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent")


def fmt_price(oms: OMS, symbol: str, price: float | None) -> str:
    if price is None:
        return "시장가"
    d = oms.instruments[symbol].price_decimals
    return f"{price:,.{d}f}"


def krw(v: float) -> str:
    """지표용 축약 표기: 1억 이상은 '억', 1만 이상은 '만' 단위."""
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.4f}억"
    if abs(v) >= 1e5:
        return f"{v / 1e4:,.1f}만"
    return f"{v:,.0f}"


def symbol_label(oms: OMS, symbol: str) -> str:
    return f"{symbol} · {oms.instruments[symbol].name}"


# ============================== 사용자·권한 ==============================
def current_user():
    """로그인한 사용자 (app.py가 매 실행마다 DB에서 다시 읽어 넣는다)."""
    return st.session_state.get("user")


def can(perm) -> bool:
    u = current_user()
    return bool(u and u.can(perm))


def can_manage(owner: str) -> bool:
    """정정·취소 권한: 리스크 관리자는 모든 것, 트레이더는 자기 것만."""
    from rfl_oms.auth import Perm

    u = current_user()
    if u is None:
        return False
    return u.can(Perm.CANCEL_ANY) or (u.can(Perm.TRADE) and owner == u.username)


def need(perm) -> str:
    """권한이 없을 때 버튼 도움말로 쓸 문구."""
    from rfl_oms.auth import ROLE_PERMS

    roles = ", ".join(r.value for r, ps in ROLE_PERMS.items() if perm in ps)
    return f"'{perm.value}' 권한이 필요합니다 ({roles})"
