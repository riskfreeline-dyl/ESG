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
    """지표용 축약 표기: 1억 이상은 '억' 단위."""
    return f"{v / 1e8:,.4f}억" if abs(v) >= 1e8 else f"{v:,.0f}"


def symbol_label(oms: OMS, symbol: str) -> str:
    return f"{symbol} · {oms.instruments[symbol].name}"
