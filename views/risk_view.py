"""리스크 대시보드: 한도 사용률, VaR, 손익 추이, 노출 분해, 집중도, 스트레스 테스트."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS
from rfl_oms.analytics import concentration, equity_beta_exposure, exposure_by_asset_class, stress_test, value_at_risk

from .common import NUM, krw


def limits_panel(oms: OMS) -> None:
    warn = oms.limits.warn_ratio
    for row in oms.utilization():
        ratio = row["사용률"]
        icon = "🔴" if ratio >= 1 else "🟠" if ratio >= warn else "🟢"
        st.markdown(f"{icon} **{row['항목']}** — {krw(row['사용'])} / {krw(row['한도'])} ({ratio:.1%})")
        st.progress(min(max(ratio, 0.0), 1.0))
    st.caption("노출·증거금은 미체결 주문과 알고 잔량이 모두 체결된다고 가정한 최악의 경우입니다.")


def limits_table(oms: OMS) -> None:
    lim = oms.limits
    st.dataframe(
        pd.DataFrame(
            [
                ("계좌 자본", f"{lim.capital:,.0f}"),
                ("주문당 최대 수량", f"{lim.max_order_qty:,}"),
                ("주문당 최대 명목", f"{lim.max_order_notional:,.0f}"),
                ("가격 괴리 허용", f"{lim.price_band_pct:.1f}%"),
                ("종목별 포지션 한도", f"{lim.max_position_notional:,.0f}"),
                ("총 노출 한도", f"{lim.max_gross_exposure:,.0f}"),
                ("일일 손실 한도", f"{lim.max_daily_loss:,.0f}"),
                ("경고 기준", f"{lim.warn_ratio:.0%}"),
                ("거래 제한 종목", ", ".join(sorted(lim.restricted_symbols)) or "없음"),
            ],
            columns=["항목", "값"],
        ),
        hide_index=True,
        width="stretch",
    )


def pnl_chart(oms: OMS) -> None:
    df = pd.DataFrame(oms.pnl_history, columns=["틱", "실현", "미실현", "평가자산", "총노출"])
    df["일일 손익"] = df["실현"] + df["미실현"]
    fig = go.Figure()
    fig.add_scatter(x=df["틱"], y=df["일일 손익"], name="일일 손익", line=dict(width=2))
    fig.add_scatter(x=df["틱"], y=df["실현"], name="실현", line=dict(width=1.2, dash="dot"))
    fig.add_hline(y=-oms.limits.max_daily_loss, line_color="#c62828", line_dash="dash", annotation_text="손실 한도")
    fig.add_hline(y=0, line_color="gray", line_width=1)
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.12), xaxis_title="틱")
    st.plotly_chart(fig, width="stretch")


def exposure_chart(oms: OMS) -> None:
    df = exposure_by_asset_class(oms)
    if df.empty:
        st.caption("보유 포지션이 없습니다.")
        return
    fig = go.Figure()
    fig.add_bar(y=df["자산군"], x=df["매수"], name="매수", orientation="h", marker_color="#2e7d32")
    fig.add_bar(y=df["자산군"], x=df["매도"], name="매도", orientation="h", marker_color="#c62828")
    fig.add_scatter(y=df["자산군"], x=df["순노출"], name="순노출", mode="markers", marker=dict(size=11, color="#1565c0", symbol="diamond"))
    fig.update_layout(barmode="relative", height=260, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, width="stretch")


def risk_view(oms: OMS) -> None:
    var99 = value_at_risk(oms, 0.99)
    var95 = value_at_risk(oms, 0.95)
    beta = equity_beta_exposure(oms)
    m = st.columns(5)
    if var99.historical is None:
        m[0].metric("VaR 99% (1일, 과거)", "데이터 부족", help=f"수익률 관측치 {var99.observations}/20 — 시장을 더 진행하세요")
        m[1].metric("VaR 99% (1일, 모수)", "—")
        m[2].metric("VaR 95% (1일, 과거)", "—")
    else:
        m[0].metric("VaR 99% (1일, 과거)", krw(var99.historical), help=f"최근 {var99.observations}틱 수익률, √120로 1일 환산")
        m[1].metric("VaR 99% (1일, 모수)", krw(var99.parametric))
        m[2].metric("VaR 95% (1일, 과거)", krw(var95.historical))
    m[3].metric("주가 방향 순노출", krw(beta), help="주식 + 지수선물 순명목 (차익 포지션은 서로 상쇄)")
    loss_room = oms.limits.max_daily_loss + min(oms.daily_pnl(), 0)
    m[4].metric("남은 손실 여력", krw(loss_room))
    if var99.historical and var99.historical > loss_room:
        st.warning("1일 VaR 99%가 남은 손실 여력보다 큽니다. 포지션 축소를 검토하세요.", icon="⚠️")

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("**손익 추이**")
        pnl_chart(oms)
        st.markdown("**자산군별 노출**")
        exposure_chart(oms)
    with right:
        st.markdown("**한도 사용률**")
        limits_panel(oms)

    st.markdown("#### 스트레스 테스트")
    st.dataframe(
        stress_test(oms),
        hide_index=True,
        width="stretch",
        column_config={
            "예상 손익": NUM,
            "평가자산 대비": st.column_config.NumberColumn(format="percent"),
            "손실한도 대비": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent"),
        },
    )
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.markdown("#### 상위 집중 포지션")
        conc = concentration(oms)
        if conc.empty:
            st.caption("보유 포지션이 없습니다.")
        else:
            st.dataframe(
                conc,
                hide_index=True,
                width="stretch",
                column_config={"수량": NUM, "순명목": NUM, "비중": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent")},
            )
    with c2:
        st.markdown("#### 적용 중인 한도")
        limits_table(oms)
