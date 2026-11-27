"""코스피200 옵션 화면: 체인, 주문, 포트폴리오 민감도, 델타 헤지, 만기 손익."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS, OrderType, Side
from rfl_oms.auth import Perm
from rfl_oms.market import OPTION_UNDERLYING, SESSION_TICKS
from rfl_oms.options import chain, delta_hedge_qty, option_symbols, payoff, portfolio_greeks

from .common import NUM, can, krw, need


def options_view(oms: OMS) -> None:
    if OPTION_UNDERLYING not in oms.instruments or not option_symbols(oms):
        st.info("옵션이 설정되지 않았습니다.")
        return
    trade_ok = can(Perm.TRADE)
    tip = None if trade_ok else need(Perm.TRADE)
    F = oms.market.mark(OPTION_UNDERLYING)
    spec0 = oms.instruments[option_symbols(oms)[0]].option
    days_left = max(spec0.expiry_tick - oms.market.tick_no, 0) / SESSION_TICKS

    m = st.columns(4)
    m[0].metric("기초자산 (코스피200 선물)", f"{F:,.2f}")
    m[1].metric("만기까지", f"{days_left:,.1f}일", help="시뮬레이션 1거래일 = 120틱")
    oms.market.option_base_vol = m[2].number_input(
        "기준 변동성(%)", 5.0, 80.0, oms.market.option_base_vol * 100, 0.5, key="opt_vol",
        disabled=not can(Perm.SET_LIMITS) and not trade_ok, help="옵션 가격 계산에 쓰는 변동성(행사가별 스큐 적용)",
    ) / 100
    m[3].metric("승수", "250,000원")

    st.markdown("#### 옵션 체인")
    df = pd.DataFrame(chain(oms))
    cols = ["콜 보유", "콜 델타", "콜 매수호가", "콜 매도호가", "행사가", "풋 매수호가", "풋 매도호가", "풋 델타", "풋 보유", "변동성(%)"]
    st.dataframe(df[cols], hide_index=True, width="stretch")
    st.caption("행사가 근처가 등가격(ATM)입니다. 가격은 Black-76 모형으로 계산한 시뮬레이션 값입니다.")

    left, right = st.columns([1, 1.5])
    with left:
        st.markdown("#### 주문")
        with st.form("opt_order"):
            c = st.columns(2)
            kind = c[0].radio("종류", ["콜", "풋"], horizontal=True)
            side = c[1].radio("구분", [Side.BUY, Side.SELL], format_func=lambda x: x.value, horizontal=True)
            strike = st.selectbox("행사가", df["행사가"].tolist(), index=len(df) // 2, format_func=lambda k: f"{k:.1f}")
            qty = st.number_input("수량(계약)", 1, 1000, 1)
            if st.form_submit_button("시장가 주문", type="primary", disabled=not trade_ok, help=tip):
                sym = df.loc[df["행사가"] == strike, f"{kind} 종목"].iloc[0]
                o = oms.submit(sym, side, OrderType.MARKET, int(qty), strategy_tag="옵션")
                if o.reject_reason:
                    st.error(f"{o.order_id} 거부: {o.reject_reason}")
                else:
                    st.success(f"{o.order_id} {oms.instruments[sym].name} {side.value} {o.filled_qty}/{o.qty} @ {o.avg_fill_price:.2f}")
        st.caption("매도 옵션 증거금 = 프리미엄 + 기초자산 명목의 15% (시뮬레이션 가정)")

        st.markdown("#### 포트폴리오 민감도")
        g = portfolio_greeks(oms)
        gc = st.columns(2)
        gc[0].metric("델타 (선물 계약 환산)", f"{g['델타(선물 계약)']:+.2f}", help=f"델타 금액 {g['델타 금액']:,.0f}원")
        gc[1].metric("감마", f"{g['감마(1pt당 델타 변화)']:+.3f}", help="기초자산 1pt 변화당 델타 변화(계약)")
        gc = st.columns(2)
        gc[0].metric("베가 (변동성 1%p)", krw(g["베가(변동성 1%p당 원)"]))
        gc[1].metric("세타 (하루)", krw(g["세타(하루당 원)"]))
        hedge = delta_hedge_qty(oms)
        label = f"델타 헤지: 선물 {abs(hedge)}계약 {'매수' if hedge > 0 else '매도'}" if hedge else "델타 헤지 (이미 중립)"
        if st.button(label, width="stretch", disabled=not trade_ok or hedge == 0, help=tip or "선물로 델타를 0에 가깝게 맞춥니다", key="opt_hedge"):
            o = oms.submit(OPTION_UNDERLYING, Side.BUY if hedge > 0 else Side.SELL, OrderType.MARKET, abs(hedge), strategy_tag="델타헤지")
            (st.error(o.reject_reason) if o.reject_reason else st.success(f"{o.order_id} 선물 {o.side.value} {o.filled_qty}계약"))
    with right:
        st.markdown("#### 손익 그래프 (옵션 + 코스피200 선물 보유분)")
        pts = payoff(oms)
        if not any(oms.positions[s].qty for s in option_symbols(oms)) and not oms.positions[OPTION_UNDERLYING].qty:
            st.info("옵션이나 코스피200 선물 보유분이 없습니다. 왼쪽에서 주문해 보세요.")
        else:
            fig = go.Figure()
            fig.add_scatter(x=[p[0] for p in pts], y=[p[2] for p in pts], name="만기 손익", line=dict(width=2.2))
            fig.add_scatter(x=[p[0] for p in pts], y=[p[1] for p in pts], name="현재 평가손익", line=dict(width=1.4, dash="dot"))
            fig.add_vline(x=F, line_color="gray", line_dash="dash", annotation_text="현재가")
            fig.add_hline(y=0, line_color="gray", line_width=1)
            fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1), xaxis_title="코스피200 선물 가격", yaxis_title="원")
            st.plotly_chart(fig, width="stretch")
        held = [
            {"종목": s, "종목명": oms.instruments[s].name, "수량": oms.positions[s].qty, "평균단가": round(oms.positions[s].avg_price, 3),
             "현재가": oms.market.mark(s), "델타": round(oms.market.option_greeks(s).delta, 3), "평가손익": round(oms.unrealized_pnl(s))}
            for s in option_symbols(oms) if oms.positions[s].qty
        ]
        if held:
            st.dataframe(pd.DataFrame(held), hide_index=True, width="stretch", column_config={"수량": NUM, "평가손익": NUM})
