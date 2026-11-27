"""차익거래 화면: 지수(주식 바스켓)·외환·국고채·금 현물/선물 괴리 모니터, 진입·청산, 자동 매매."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS, ArbDirection, ExecMode

from rfl_oms.auth import Perm

from .common import NUM, can, can_manage, current_user, krw, need


def settings_panel(arb) -> None:
    s, c, mdl, k = arb.settings, arb.costs, arb.model, arb.PREFIX
    is_index = arb.PREFIX == "X"
    rate_label = "무위험 금리" if is_index else mdl.rate_label
    yield_label = "배당수익률" if is_index else mdl.yield_label
    with st.expander("설정 · 이론가 모형 · 비용", expanded=False):
        a = st.columns(3)
        mdl.rate = a[0].number_input(f"{rate_label}(%)", 0.0, 20.0, mdl.rate * 100, 0.05, key=f"{k}_rate") / 100
        mdl.dividend_yield = a[1].number_input(f"{yield_label}(%)", 0.0, 20.0, mdl.dividend_yield * 100, 0.05, key=f"{k}_yld") / 100
        mdl.days_to_expiry = int(a[2].number_input("만기까지 일수", 1, 365, mdl.days_to_expiry, key=f"{k}_days"))
        b = st.columns(4)
        spot_word = "주식" if is_index else "현물"
        c.commission_bps = b[0].number_input(f"{spot_word} 수수료(bp, 편도)", 0.0, 50.0, c.commission_bps, 0.1, key=f"{k}_comm")
        c.sell_tax_bps = b[1].number_input(f"{spot_word} 매도세(bp)", 0.0, 100.0, c.sell_tax_bps, 0.5, key=f"{k}_tax", help="시뮬레이션 가정값입니다. 실제 세율에 맞게 조정하세요.")
        c.futures_bps = b[2].number_input("선물 수수료(bp, 편도)", 0.0, 20.0, c.futures_bps, 0.1, key=f"{k}_fut")
        c.slippage_bps = b[3].number_input("슬리피지(bp, 편도)", 0.0, 50.0, c.slippage_bps, 0.5, key=f"{k}_slip")
        d = st.columns(4)
        unit = "pt" if is_index else "원"
        step = 0.05 if is_index else float(max(arb.oms.instruments[arb.futures_symbol].tick_size, 0.001))
        s.entry_edge_pts = d[0].number_input(f"진입 기준(비용 차감 후, {unit})", -1e6, 1e6, float(s.entry_edge_pts), step, key=f"{k}_entry")
        s.exit_mispricing_pts = d[1].number_input(f"청산 기준(괴리, {unit})", 0.0, 1e6, float(s.exit_mispricing_pts), step, key=f"{k}_exit")
        s.max_open = int(d[2].number_input("최대 동시 포지션", 1, 20, s.max_open, key=f"{k}_max"))
        s.stock_mode = d[3].selectbox(
            "현물 레그 실행", [ExecMode.MARKET, ExecMode.TWAP, ExecMode.VWAP], format_func=lambda m: m.value,
            index=[ExecMode.MARKET, ExecMode.TWAP, ExecMode.VWAP].index(s.stock_mode)
            if s.stock_mode in (ExecMode.MARKET, ExecMode.TWAP, ExecMode.VWAP) else 0,
            help="TWAP/VWAP은 10틱에 걸쳐 나눠 체결하므로 그동안 헤지가 불완전합니다",
            key=f"{k}_mode",
        )
        st.caption(
            f"왕복 비용 {c.round_trip_bps():.1f}bp = 수수료 2×{c.commission_bps:g} + 매도세 {c.sell_tax_bps:g} "
            f"+ 선물 2×{c.futures_bps:g} + 슬리피지 2×{c.slippage_bps:g}"
        )


def spread_chart(arb) -> None:
    h = arb.history
    df = pd.DataFrame(
        {
            "틱": [x.tick for x in h],
            "괴리": [x.mispricing for x in h],
            "매도차익 기준": [x.cost_pts + arb.settings.entry_edge_pts for x in h],
            "매수차익 기준": [-(x.cost_pts + arb.settings.entry_edge_pts) for x in h],
        }
    )
    fig = go.Figure()
    fig.add_scatter(x=df["틱"], y=df["매도차익 기준"], name="매도차익 진입선", line=dict(color="#c62828", dash="dot", width=1))
    fig.add_scatter(x=df["틱"], y=df["매수차익 기준"], name="매수차익 진입선", line=dict(color="#2e7d32", dash="dot", width=1))
    fig.add_scatter(x=df["틱"], y=df["괴리"], name="괴리 (선물 − 이론가)", line=dict(width=1.8, color="#1565c0"))
    fig.add_hline(y=0, line_color="gray", line_width=1)
    for p in arb.positions.values():
        color = "#c62828" if p.direction is ArbDirection.SELL_ARB else "#2e7d32"
        fig.add_scatter(
            x=[p.opened_tick], y=[p.entry.mispricing], mode="markers", marker=dict(symbol="triangle-up", size=10, color=color),
            showlegend=False, hovertext=f"{p.arb_id} {p.direction.value} 진입",
        )
        if p.exit:
            fig.add_scatter(
                x=[p.closed_tick], y=[p.exit.mispricing], mode="markers", marker=dict(symbol="x", size=9, color=color),
                showlegend=False, hovertext=f"{p.arb_id} 청산",
            )
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.12), yaxis_title="pt" if arb.PREFIX == "X" else "원", xaxis_title="틱")
    st.plotly_chart(fig, width="stretch")


def positions_table(arb) -> None:
    if not arb.positions:
        st.caption("차익 포지션이 없습니다.")
        return
    rows = []
    for p in reversed(list(arb.positions.values())):
        fut, stock = arb.hedge(p)
        rows.append(
            {
                "ID": p.arb_id,
                "방향": p.direction.value,
                "계약": p.contracts,
                "상태": p.status.value,
                "진입 틱": p.opened_tick,
                "진입 괴리": round(p.entry.mispricing, 4),
                "청산 괴리": round(p.exit.mispricing, 4) if p.exit else None,
                "손익(비용 전)": round(arb.pnl(p)),
                "비용": round(arb.fees(p)),
                "순손익": round(arb.pnl_net(p)),
                "선물 명목": round(fut),
                "현물 명목": round(stock),
                "헤지 잔차": round(fut + stock),
                "진입자": p.owner,
                "메모": p.note,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={k: NUM for k in ["손익(비용 전)", "비용", "순손익", "선물 명목", "현물 명목", "헤지 잔차"]},
    )
    open_ids = [p.arb_id for p in arb.open_positions() if can_manage(p.owner.removesuffix("(자동)"))]
    if open_ids:
        c = st.columns([2, 1, 1])
        sel = c[0].selectbox("청산할 포지션", open_ids, label_visibility="collapsed", key=f"{arb.PREFIX}_closesel")
        if c[1].button("선택 청산", width="stretch", key=f"{arb.PREFIX}_close1"):
            arb.close(sel)
            st.rerun()
        if c[2].button("전체 청산", width="stretch", key=f"{arb.PREFIX}_closeall"):
            for i in open_ids:
                arb.close(i)
            st.rerun()


def constituents_table(oms: OMS) -> None:
    idx = oms.market.index_def
    total = sum(q * oms.market.mark(s) for s, q in idx.constituents.items())
    rows = [
        {
            "종목": s,
            "종목명": oms.instruments[s].name,
            "계약당 주식수": q,
            "현재가": oms.market.mark(s),
            "금액": q * oms.market.mark(s),
            "비중": q * oms.market.mark(s) / total,
        }
        for s, q in idx.constituents.items()
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "계약당 주식수": NUM,
            "현재가": NUM,
            "금액": NUM,
            "비중": st.column_config.NumberColumn(format="percent"),
        },
    )
    st.caption(f"{idx.name} = Σ(주식수 × 가격) / {idx.divisor:,.0f} · 선물 1계약 = 위 바스켓 1단위 ({krw(total)})")


def arb_view(oms: OMS) -> None:
    engines = {"지수 (주식 바스켓)": oms.arb}
    engines.update({f"{e.KIND} ({e.futures_symbol} ↔ {e.model.spot_symbol})": e for e in oms.carry_arbs.values() if e.available})
    choice = st.segmented_control("시장", list(engines), default=list(engines)[0], key="arb_market") or list(engines)[0]
    arb_market_view(oms, engines[choice])


def arb_market_view(oms: OMS, arb) -> None:
    if not arb.available:
        st.info("선물과 현물이 설정되지 않아 차익거래를 사용할 수 없습니다.")
        return
    is_index = arb.PREFIX == "X"
    unit = "pt" if is_index else "원"
    d = max(oms.instruments[arb.futures_symbol].price_decimals, 2)
    snap = arb.snapshot()
    m = st.columns(6)
    m[0].metric("RFL 시뮬 지수" if is_index else f"현물 {arb.model.spot_symbol}", f"{snap.index:,.{d}f}")
    m[1].metric("선물 중간가", f"{snap.fut_mid:,.{d + 1}f}", help=f"매수호가 {snap.fut_bid:,.{d}f} / 매도호가 {snap.fut_ask:,.{d}f}")
    m[2].metric("이론가", f"{snap.fair:,.{d}f}", help=f"이론 베이시스 {snap.theo_basis:+.{d}f}{unit}")
    m[3].metric("괴리", f"{snap.mispricing:+.{d}f}{unit}", delta=f"{snap.mispricing_bps:+.1f}bp", delta_color="off")
    m[4].metric("매도차익 순수익", f"{snap.sell_edge:+.{d}f}{unit}")
    m[5].metric("매수차익 순수익", f"{snap.buy_edge:+.{d}f}{unit}")

    settings_panel(arb)
    spread_chart(arb)

    s = arb.settings
    k = arb.PREFIX
    c = st.columns([1, 1.2, 1.2, 1.4])
    s.contracts = int(c[0].number_input("계약 수", 1, 100, s.contracts, key=f"{k}_contracts"))
    trade_ok = can(Perm.TRADE)
    tip = None if trade_ok else need(Perm.TRADE)
    hot_sell = snap.sell_edge >= s.entry_edge_pts
    hot_buy = snap.buy_edge >= s.entry_edge_pts
    c[1].write("")
    if c[1].button("매도차익 진입" + (" 🔥" if hot_sell else ""), width="stretch", type="primary" if hot_sell else "secondary",
                   help=tip or "선물 매도 + 현물 매수", disabled=not trade_ok, key=f"{k}_sell"):
        pos, problems = arb.enter(ArbDirection.SELL_ARB)
        (st.success(f"{pos.arb_id} 진입") if pos else st.error("진입 거부: " + "; ".join(problems[:3])))
    c[2].write("")
    if c[2].button("매수차익 진입" + (" 🔥" if hot_buy else ""), width="stretch", type="primary" if hot_buy else "secondary",
                   help=tip or "선물 매수 + 현물 매도(대차 매도 가정)", disabled=not trade_ok, key=f"{k}_buy"):
        pos, problems = arb.enter(ArbDirection.BUY_ARB)
        (st.success(f"{pos.arb_id} 진입") if pos else st.error("진입 거부: " + "; ".join(problems[:3])))
    c[3].write("")
    auto = c[3].toggle(
        "자동 차익 (진입·청산)", value=s.auto, disabled=not trade_ok, key=f"{k}_auto",
        help=tip or "시장이 진행될 때 기준을 넘으면 자동 진입, 괴리가 수렴하면 자동 청산. 자동 주문은 켠 사용자 이름으로 기록됩니다",
    )
    if trade_ok and auto != s.auto:
        s.auto = auto
        s.auto_owner = current_user().username
        oms.system_event("자동 차익", f"{arb.KIND} " + ("켜짐" if auto else "꺼짐"))
    if s.auto:
        c[3].caption(f"자동 실행자: {s.auto_owner}")

    st.markdown("#### 차익 포지션")
    positions_table(arb)
    if is_index:
        with st.expander("지수 구성 · 선물 1계약 복제 바스켓"):
            constituents_table(oms)
    else:
        mdl = arb.model
        st.caption(
            f"이론가 = 현물 × (1 + ({mdl.rate_label} {mdl.rate:.2%} − {mdl.yield_label} {mdl.dividend_yield:.2%}) × {mdl.days_to_expiry}/365) · "
            f"선물 1계약 = 현물 {arb.spot_units_per_contract():,}단위"
        )
    st.caption("매수차익의 현물 매도는 대차(공매도)가 가능하다고 가정합니다. 비용 차감 후 손익은 '순손익' 열을 보세요.")
