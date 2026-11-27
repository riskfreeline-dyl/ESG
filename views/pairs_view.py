"""페어 트레이딩 화면."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS
from rfl_oms.auth import Perm
from rfl_oms.pairs import PairDirection

from .common import NUM, can, can_manage, current_user, need


def _name(oms: OMS, s: str) -> str:
    return oms.instruments[s].name


def pairs_view(oms: OMS) -> None:
    pe = oms.pairs
    s = pe.settings
    trade_ok = can(Perm.TRADE)
    tip = None if trade_ok else need(Perm.TRADE)

    stats = [pe.stat(a, b) for a, b in pe.pairs]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "페어 (A / B)": f"{_name(oms, x.a)} / {_name(oms, x.b)}",
                    "Z-점수": round(x.z, 2) if x.ready else None,
                    "헤지비율 β": round(x.beta, 3) if x.beta is not None else None,
                    "수익률 상관": round(x.corr, 2) if x.corr is not None else None,
                    "평균회귀 반감기(틱)": round(x.half_life, 1) if x.half_life else None,
                    "판단": (
                        "데이터 부족" if not x.ready
                        else "평균회귀 약함 (주의)" if not x.half_life or x.half_life > s.lookback / 2
                        else "A 비쌈 → A 매도·B 매수" if x.z >= s.entry_z
                        else "A 쌈 → A 매수·B 매도" if x.z <= -s.entry_z
                        else "관망"
                    ),
                    "관측 틱": x.n,
                }
                for x in stats
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption("Z-점수 = (현재 스프레드 − 평균) ÷ 표준편차, 스프레드 = log(A) − β·log(B). 반감기가 짧을수록 스프레드가 빨리 되돌아옵니다.")

    left, right = st.columns([1.6, 1])
    with left:
        labels = {f"{_name(oms, a)} / {_name(oms, b)}": (a, b) for a, b in pe.pairs}
        pick = st.selectbox("차트", list(labels), key="pair_pick")
        a, b = labels[pick]
        hist = pe.z_history.get((a, b), [])
        fig = go.Figure()
        if hist:
            fig.add_scatter(x=[t for t, _ in hist], y=[z for _, z in hist], name="Z-점수", line=dict(width=1.8))
        for y, color, dash in ((s.entry_z, "#c62828", "dot"), (-s.entry_z, "#2e7d32", "dot"), (s.exit_z, "gray", "dash"), (-s.exit_z, "gray", "dash"), (s.stop_z, "#6a1b9a", "dashdot"), (-s.stop_z, "#6a1b9a", "dashdot")):
            fig.add_hline(y=y, line_color=color, line_dash=dash, line_width=1)
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="틱", yaxis_title="Z")
        st.plotly_chart(fig, width="stretch")
        st.caption("빨강·초록 점선: 진입 기준, 회색: 청산 기준, 보라: 손절 기준")
    with right:
        with st.form("pair_settings"):
            c = st.columns(2)
            lookback = c[0].number_input("통계 기간(틱)", 20, 400, s.lookback, 10)
            notional = c[1].number_input("A 레그 금액(원)", 1e6, 1e10, float(s.notional), 1e7, format="%.0f")
            c = st.columns(3)
            entry = c[0].number_input("진입 |Z|", 0.5, 6.0, s.entry_z, 0.1)
            exit_ = c[1].number_input("청산 |Z|", 0.0, 3.0, s.exit_z, 0.1)
            stop = c[2].number_input("손절 |Z|", 1.0, 10.0, s.stop_z, 0.5)
            max_open = st.number_input("최대 동시 포지션", 1, 10, s.max_open)
            if st.form_submit_button("설정 저장", disabled=not trade_ok, help=tip):
                s.lookback, s.notional, s.entry_z, s.exit_z, s.stop_z, s.max_open = int(lookback), notional, entry, exit_, stop, int(max_open)
                st.success("저장했습니다")
        c = st.columns(2)
        if c[0].button("A 매도 · B 매수", width="stretch", disabled=not trade_ok, help=tip, key="pair_short"):
            pos, problems = pe.enter(a, b, PairDirection.SHORT_A)
            (st.success(f"{pos.pair_id} 진입") if pos else st.error("; ".join(problems[:2])))
        if c[1].button("A 매수 · B 매도", width="stretch", disabled=not trade_ok, help=tip, key="pair_long"):
            pos, problems = pe.enter(a, b, PairDirection.LONG_A)
            (st.success(f"{pos.pair_id} 진입") if pos else st.error("; ".join(problems[:2])))
        auto = st.toggle("자동 페어 트레이딩", value=s.auto, disabled=not trade_ok, help=tip or "기준에 따라 모든 페어를 자동 진입·청산·손절", key="pair_auto")
        if trade_ok and auto != s.auto:
            s.auto, s.auto_owner = auto, current_user().username
            oms.system_event("자동 페어", "켜짐" if auto else "꺼짐")
        if s.auto:
            st.caption(f"자동 실행자: {s.auto_owner}")

    st.markdown("#### 페어 포지션")
    if not pe.positions:
        st.caption("페어 포지션이 없습니다.")
        return
    rows = []
    for p in reversed(list(pe.positions.values())):
        pnl = pe.pnl(p)
        rows.append(
            {
                "ID": p.pair_id,
                "페어": f"{_name(oms, p.a)} / {_name(oms, p.b)}",
                "방향": p.direction.value,
                "수량 A / B": f"{p.qty_a:,} / {p.qty_b:,}",
                "진입 Z": round(p.entry.z, 2),
                "청산 Z": round(p.exit_z, 2) if p.exit_z is not None else None,
                "상태": "보유" if p.open else "청산",
                "손익(비용 전)": round(pnl["손익"]),
                "비용": round(pnl["비용"]),
                "순손익": round(pnl["순손익"]),
                "진입자": p.owner,
                "메모": p.note,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={k: NUM for k in ["손익(비용 전)", "비용", "순손익"]})
    closable = [p.pair_id for p in pe.open_positions() if can_manage(p.owner.removesuffix("(자동)"))]
    if closable:
        c = st.columns([2, 1])
        sel = c[0].selectbox("청산할 포지션", closable, label_visibility="collapsed", key="pair_close_sel")
        if c[1].button("청산", width="stretch", key="pair_close"):
            pe.close(sel)
            st.rerun()
    st.caption("주식 매도세·수수료가 페어 수익의 상당 부분을 차지합니다. 비용 차감 후 '순손익'을 기준으로 판단하세요.")
