"""마켓메이킹·유동성 공급 화면 (외환·국고채·KRX 금)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from rfl_oms import OMS
from rfl_oms.auth import Perm

from .common import NUM, can, can_manage, fmt_price, need


def mm_view(oms: OMS) -> None:
    mm = oms.mm
    trade_ok = can(Perm.TRADE)
    tip = None if trade_ok else need(Perm.TRADE)

    rows = []
    for sym, cfg in mm.configs.items():
        st_ = mm.stats(cfg)
        q = oms.market.quote(sym)
        bid = oms.orders[cfg.bid_id].limit_price if cfg.bid_id and oms.orders[cfg.bid_id].status.is_open else None
        ask = oms.orders[cfg.ask_id].limit_price if cfg.ask_id and oms.orders[cfg.ask_id].status.is_open else None
        rows.append(
            {
                "종목": f"{sym} {oms.instruments[sym].name}",
                "상태": "운영중" if cfg.enabled else ("중지: " + cfg.stop_reason if cfg.stop_reason else "중지"),
                "시장 매수/매도": f"{fmt_price(oms, sym, q.bid)} / {fmt_price(oms, sym, q.ask)}",
                "내 매수호가": fmt_price(oms, sym, bid) if bid else "-",
                "내 매도호가": fmt_price(oms, sym, ask) if ask else "-",
                "재고": st_["재고"],
                "재고 한도": cfg.max_inventory,
                "체결 건수": st_["체결 건수"],
                "손익(비용 전)": round(st_["손익"]),
                "비용": round(st_["비용"]),
                "순손익": round(st_["순손익"]),
                "운영자": cfg.owner,
            }
        )
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={k: NUM for k in ["재고", "재고 한도", "체결 건수", "손익(비용 전)", "비용", "순손익"]},
    )

    st.markdown("#### 종목별 설정")
    cols = st.columns(len(mm.configs))
    for col, (sym, cfg) in zip(cols, mm.configs.items()):
        inst = oms.instruments[sym]
        with col:
            st.markdown(f"**{inst.name}**")
            st.caption(f"호가단위 {inst.tick_size:g} · 승수 {inst.multiplier:g}")
            with st.form(f"mm_{sym}"):
                size = st.number_input("호가 수량", 1, 10**9, cfg.size, key=f"mm_size_{sym}")
                half = st.number_input("반폭(틱)", 1, 200, cfg.half_spread_ticks, key=f"mm_half_{sym}",
                                       help="기준가에서 매수·매도 호가까지 거리. 가격 변동보다 좁으면 추세에 밀려 손실이 납니다")
                maxinv = st.number_input("재고 한도", 1, 10**10, cfg.max_inventory, key=f"mm_inv_{sym}")
                skew = st.number_input("재고 스큐(틱)", 0.0, 100.0, float(cfg.skew_ticks), 0.5, key=f"mm_skew_{sym}",
                                       help="재고가 한도에 닿으면 호가 전체를 이만큼 옮겨 반대 방향 체결을 유도")
                if st.form_submit_button("설정 저장", disabled=not trade_ok, help=tip):
                    cfg.size, cfg.half_spread_ticks, cfg.max_inventory, cfg.skew_ticks = int(size), int(half), int(maxinv), float(skew)
                    oms.system_event("마켓메이킹 설정", f"{sym} 수량 {cfg.size:,}, 반폭 {cfg.half_spread_ticks}틱, 재고한도 {cfg.max_inventory:,}, 스큐 {cfg.skew_ticks}")
                    st.success("저장했습니다")
            if cfg.enabled:
                if st.button("중지", key=f"mm_off_{sym}", width="stretch", disabled=not can_manage(cfg.owner)):
                    mm.disable(sym)
                    st.rerun()
            elif st.button("시작", key=f"mm_on_{sym}", type="primary", width="stretch", disabled=not trade_ok, help=tip):
                mm.enable(sym)
                st.rerun()
    st.caption(
        "매 틱 기준가 양쪽에 매수·매도 호가를 유지하고, 시장이 그 가격을 지나가면 자기 호가로 체결됩니다. "
        "재고가 쌓이면 호가를 옮겨 줄이고, 한도에 닿은 쪽은 호가를 내지 않습니다. 킬 스위치가 켜지면 모든 호가를 취소하고 멈춥니다. "
        "실제 유동성 공급자(LP)는 거래소 수수료 감면을 받는 경우가 많으니 수수료 설정을 확인하세요."
    )
