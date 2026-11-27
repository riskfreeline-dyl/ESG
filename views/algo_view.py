"""알고리즘 주문 화면: TWAP · VWAP · POV 실행과 모니터링."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS, AlgoType, Side
from rfl_oms.algo import ALGO_DESCRIPTIONS

from rfl_oms.auth import Perm

from .common import NUM, PCT, can, can_manage, fmt_price, need, symbol_label


def new_algo_form(oms: OMS) -> None:
    symbol = st.selectbox("종목", list(oms.instruments), format_func=lambda s: symbol_label(oms, s), key="algo_symbol")
    inst = oms.instruments[symbol]
    with st.form("algo_form"):
        c = st.columns(2)
        side = c[0].radio("구분", [Side.BUY, Side.SELL], format_func=lambda x: x.value, horizontal=True)
        algo_type = c[1].radio("알고리즘", list(AlgoType), format_func=lambda x: x.value, horizontal=True)
        qty = st.number_input("총 수량", min_value=1, value=3_000 if inst.multiplier == 1 else 30, step=1)
        c = st.columns(2)
        duration = c[0].number_input("기간(틱)", min_value=1, max_value=600, value=30, help="POV는 최대 실행 기간")
        participation = c[1].number_input("참여율(%) · POV", min_value=1.0, max_value=100.0, value=10.0)
        use_limit = st.checkbox("제한가 사용", help="매수는 이 가격 이하, 매도는 이 가격 이상에서만 자식 주문을 냅니다")
        limit = st.number_input(
            f"제한가 (호가단위 {inst.tick_size:g})",
            min_value=float(inst.tick_size),
            value=float(oms.market.quote(symbol).ask),
            step=float(inst.tick_size),
            format=f"%.{inst.price_decimals}f",
            key=f"algo_px_{symbol}",
        )
        st.caption(" · ".join(f"**{k.value}** {v}" for k, v in ALGO_DESCRIPTIONS.items()))
        if st.form_submit_button(
            "알고 시작", type="primary", width="stretch", disabled=not can(Perm.TRADE),
            help=None if can(Perm.TRADE) else need(Perm.TRADE),
        ):
            algo = oms.algos.start(
                symbol,
                side,
                int(qty),
                algo_type,
                duration=int(duration),
                participation=participation / 100,
                limit_price=inst.round_to_tick(limit) if use_limit else None,
            )
            st.session_state.algo_sel = algo.algo_id
            if algo.halt_reason:
                st.error(f"{algo.algo_id} 거부: {algo.halt_reason}")
            else:
                st.success(f"{algo.algo_id} 시작 — 시장을 진행하면 자식 주문이 나갑니다")


def algos_frame(oms: OMS) -> pd.DataFrame:
    ae = oms.algos
    rows = []
    for a in reversed(list(ae.algos.values())):
        filled = ae.filled(a)
        tick = oms.market.tick_no
        target = ae.target(a, tick) if a.status.is_active else None
        arr = ae.slippage_bps(a, a.arrival_price)
        vw = ae.slippage_bps(a, ae.market_vwap(a))
        rows.append(
            {
                "알고": a.algo_id,
                "유형": a.algo_type.value,
                "종목": symbol_label(oms, a.symbol),
                "구분": a.side.value,
                "총수량": a.qty,
                "체결": filled,
                "진행률": filled / a.qty,
                "현재 목표": target,
                "경과/기간": f"{min(tick - a.start_tick, a.duration)}/{a.duration}",
                "상태": a.status.value,
                "평균체결가": round(ae.avg_price(a), 4) if filled else None,
                "도착가": a.arrival_price,
                "도착가 대비(bp)": round(arr, 1) if arr is not None else None,
                "구간 VWAP 대비(bp)": round(vw, 1) if vw is not None else None,
                "자식 주문": len(a.child_ids),
                "바스켓": a.strategy_tag,
                "실행자": a.actor,
                "사유": a.halt_reason,
            }
        )
    return pd.DataFrame(rows)


def algo_detail(oms: OMS, algo_id: str) -> None:
    ae = oms.algos
    a = ae.algos[algo_id]
    c = st.columns(4)
    mine = can(Perm.TRADE) and can_manage(a.actor)
    if c[0].button("일시정지", width="stretch", disabled=a.status.value != "실행중" or not can_manage(a.actor)):
        ae.pause(algo_id)
        st.rerun()
    if c[1].button("재개", width="stretch", disabled=a.status.value != "일시정지" or not mine):
        ae.resume(algo_id)
        st.rerun()
    if c[2].button("취소", width="stretch", disabled=not a.status.is_active or not can_manage(a.actor)):
        ae.cancel(algo_id)
        st.rerun()
    info = f"제한가 **{fmt_price(oms, a.symbol, a.limit_price) if a.limit_price else '없음'}**"
    if a.algo_type is AlgoType.POV:
        info += f" · 참여율 **{a.participation:.0%}**"
    c[3].markdown(info)

    df = pd.DataFrame(a.progress, columns=["틱", "누적 체결", "목표"])
    fig = go.Figure()
    fig.add_scatter(x=df["틱"], y=df["목표"], name="목표 스케줄", line=dict(dash="dot", width=1.6))
    fig.add_scatter(x=df["틱"], y=df["누적 체결"], name="누적 체결", line=dict(width=2.2))
    fig.add_hline(y=a.qty, line_color="gray", line_width=1, annotation_text=f"총수량 {a.qty:,}")
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1), xaxis_title="틱"
    )
    st.plotly_chart(fig, width="stretch")

    kids = [o for o in ae.children(a) if o.filled_qty]
    if kids:
        st.dataframe(
            pd.DataFrame(
                [
                    {"주문번호": o.order_id, "시각": o.created_at.strftime("%H:%M:%S"), "체결": o.filled_qty, "가격": o.avg_fill_price}
                    for o in reversed(kids)
                ]
            ),
            hide_index=True,
            width="stretch",
            height=220,
            column_config={"체결": NUM, "가격": NUM},
        )


def algo_view(oms: OMS) -> None:
    left, right = st.columns([1, 2.2])
    with left:
        st.markdown("**새 알고 주문**")
        new_algo_form(oms)
    with right:
        st.markdown("**알고 주문 현황**")
        df = algos_frame(oms)
        if df.empty:
            st.info("실행한 알고 주문이 없습니다. 왼쪽에서 시작한 뒤 사이드바에서 시장을 진행하세요.")
            return
        st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            column_config={
                "총수량": NUM,
                "체결": NUM,
                "현재 목표": NUM,
                "진행률": PCT,
                "평균체결가": NUM,
                "도착가": NUM,
            },
        )
        ids = df["알고"].tolist()
        default = st.session_state.get("algo_sel", ids[0])
        sel = st.selectbox("상세 보기", ids, index=ids.index(default) if default in ids else 0)
        algo_detail(oms, sel)
        st.caption("bp 값이 양수면 불리한 체결(매수는 더 비싸게, 매도는 더 싸게)입니다.")
