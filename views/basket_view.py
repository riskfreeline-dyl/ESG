"""바스켓 주문 화면: 구성 → 점검 → 원클릭 실행 → 모니터링."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from rfl_oms import OMS, ExecMode, ExecParams
from rfl_oms.basket import SIDE_ALIASES, normalize_symbol, sample_template

from rfl_oms.auth import Perm

from .common import NUM, PCT, can, can_manage, krw, need, symbol_label

COLUMNS = ["종목코드", "구분", "수량", "비중(%)"]


def _set_table(df: pd.DataFrame) -> None:
    df = df.copy()
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS]
    df["종목코드"] = df["종목코드"].map(lambda v: normalize_symbol(v) if pd.notna(v) else None)
    df["구분"] = df["구분"].map(
        lambda v: SIDE_ALIASES.get(str(v).strip().upper()).value if str(v).strip().upper() in SIDE_ALIASES else v
    )
    st.session_state.basket_df = df.reset_index(drop=True)
    st.session_state.basket_ver = st.session_state.get("basket_ver", 0) + 1


def _read_upload(file) -> pd.DataFrame:
    if file.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(file, dtype={"종목코드": str})
    return pd.read_csv(file, dtype={"종목코드": str})


def _sample_downloads() -> None:
    sample = sample_template()
    buf = io.BytesIO()
    sample.to_excel(buf, index=False)
    c1, c2 = st.columns(2)
    c1.download_button("양식 (엑셀)", buf.getvalue(), "rfl_basket_template.xlsx", width="stretch")
    c2.download_button(
        "양식 (CSV)", sample.to_csv(index=False).encode("utf-8-sig"), "rfl_basket_template.csv", width="stretch"
    )


def build_section(oms: OMS) -> None:
    bm = oms.baskets
    if "basket_df" not in st.session_state:
        _set_table(sample_template())

    left, right = st.columns([2.2, 1])
    with right:
        st.markdown("**불러오기**")
        up = st.file_uploader("엑셀/CSV 업로드", type=["xlsx", "xls", "csv"], label_visibility="collapsed")
        if up is not None and st.session_state.get("basket_upload_id") != up.file_id:
            try:
                _set_table(_read_upload(up))
                st.session_state.basket_upload_id = up.file_id
                st.success(f"{up.name} 불러옴")
            except Exception as e:  # 파일 형식 오류를 화면에 표시
                st.error(f"파일을 읽지 못했습니다: {e}")
        st.caption("열: 종목코드, 구분(매수/매도), 수량 또는 비중(%)")
        _sample_downloads()

        st.markdown("**템플릿**")
        if bm.templates:
            tname = st.selectbox("저장된 템플릿", list(bm.templates))
            if st.button("템플릿 불러오기", width="stretch"):
                _set_table(bm.load_template(tname))
                st.rerun()
        new_name = st.text_input("현재 구성을 저장할 이름", placeholder="예: 대형주 5종")
        save_clicked = st.button("템플릿 저장", width="stretch", disabled=not new_name.strip())

    with left:
        st.markdown("**바스켓 구성** — 행을 추가·삭제하거나 값을 직접 고칠 수 있습니다")
        edited = st.data_editor(
            st.session_state.basket_df,
            key=f"basket_editor_{st.session_state.basket_ver}",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "종목코드": st.column_config.SelectboxColumn(
                    options=list(oms.instruments), required=True, help="시뮬레이션 종목만 선택할 수 있습니다"
                ),
                "구분": st.column_config.SelectboxColumn(options=["매수", "매도"], required=True),
                "수량": st.column_config.NumberColumn(min_value=0, step=1, format="localized"),
                "비중(%)": st.column_config.NumberColumn(min_value=0.0, step=0.5),
            },
        )
        if save_clicked:
            bm.save_template(new_name.strip(), edited)
            st.success(f"템플릿 '{new_name.strip()}' 저장")

        c1, c2 = st.columns([1, 1.4])
        by = c1.radio("수량 결정 방식", ["수량", "비중"], horizontal=True, help="비중: 목표 금액을 비중대로 나눠 수량 계산")
        target = None
        if by == "비중":
            target = c2.number_input("목표 명목금액(원)", min_value=0.0, value=300_000_000.0, step=1e7, format="%.0f")

    lines, errors = bm.build_lines(edited, by=by, target_notional=target)
    for e in errors:
        st.warning(e)
    if not lines:
        st.info("실행할 종목이 없습니다.")
        return

    st.markdown("**실행 전 점검**")
    preview = bm.preview_frame(lines)
    st.dataframe(
        preview,
        hide_index=True,
        width="stretch",
        column_config={"수량": NUM, "기준가": NUM, "예상 명목": NUM},
    )
    buy_n = preview.loc[preview["구분"] == "매수", "예상 명목"].sum()
    sell_n = preview.loc[preview["구분"] == "매도", "예상 명목"].sum()
    fails = (preview["사전 점검"] != "통과").sum()
    m = st.columns(4)
    m[0].metric("종목 수", f"{len(lines)}")
    m[1].metric("매수 명목", krw(buy_n))
    m[2].metric("매도 명목", krw(sell_n))
    m[3].metric("점검 실패", f"{fails}건")

    st.markdown("**실행 설정**")
    c = st.columns([1.3, 1.4, 1, 1, 1])
    name = c[0].text_input("바스켓 이름", value=f"바스켓 {len(bm.baskets) + 1}")
    mode = c[1].selectbox("실행 방식", list(ExecMode), format_func=lambda m: m.value)
    params = ExecParams(mode=mode)
    if mode in (ExecMode.AGGRESSIVE, ExecMode.PASSIVE):
        params.offset_ticks = int(c[2].number_input("호가 조정(틱)", min_value=0, max_value=50, value=0))
    if mode.algo_type is not None:
        params.duration = int(c[2].number_input("기간(틱)", min_value=1, max_value=600, value=30))
    if mode is ExecMode.POV:
        params.participation = c[3].number_input("참여율(%)", min_value=1.0, max_value=100.0, value=10.0) / 100
    if mode is ExecMode.MARKET:
        params.auto_retry = c[2].checkbox("잔량 자동 재전송", value=True, help="유동성 부족으로 남은 수량을 다음 틱에 최대 3회 재전송")
    c[4].write("")
    if c[4].button(
        "원클릭 실행", type="primary", width="stretch", disabled=not can(Perm.TRADE),
        help=None if can(Perm.TRADE) else need(Perm.TRADE),
    ):
        b = bm.execute(name, lines, params)
        st.session_state.basket_sel = b.basket_id
        s = bm.summary(b)
        msg = f"{b.basket_id} 실행: {s['종목 수']}종목, 체결률 {s['수량 체결률']:.0%}, 거부 {s['거부 종목']}건"
        (st.warning if s["거부 종목"] else st.success)(msg)


def monitor_section(oms: OMS) -> None:
    bm = oms.baskets
    if not bm.baskets:
        st.caption("실행된 바스켓이 없습니다.")
        return
    ids = list(reversed(bm.baskets))
    default = st.session_state.get("basket_sel", ids[0])
    bid = st.selectbox(
        "바스켓",
        ids,
        index=ids.index(default) if default in ids else 0,
        format_func=lambda i: f"{i} · {bm.baskets[i].name} · {bm.baskets[i].params.mode.value}",
    )
    b = bm.baskets[bid]
    s = bm.summary(b)
    m = st.columns(6)
    m[0].metric("수량 체결률", f"{s['수량 체결률']:.1%}")
    m[1].metric("금액 체결률", f"{s['금액 체결률']:.1%}")
    m[2].metric("완료 종목", f"{s['완료 종목']}/{s['종목 수']}")
    m[3].metric("체결 금액", krw(s["체결 금액"]))
    m[4].metric("잔량 (진행 중)", f"{s['잔량']:,} ({s['진행 중 수량']:,})")
    m[5].metric("평가손익", krw(s["평가손익"]))
    st.progress(min(s["수량 체결률"], 1.0))

    st.dataframe(
        bm.lines_frame(b),
        hide_index=True,
        width="stretch",
        column_config={
            "목표": NUM,
            "체결": NUM,
            "진행 중": NUM,
            "체결률": PCT,
            "평균체결가": NUM,
            "현재가": NUM,
            "평가손익": NUM,
        },
    )
    st.caption(f"실행자: {b.actor or '-'}")
    mine = can(Perm.TRADE) and can_manage(b.actor)  # 재실행·정정은 실행한 트레이더만
    c = st.columns(3)
    if c[0].button("미체결 전체 취소", width="stretch", key=f"bc_{bid}", disabled=not can_manage(b.actor)):
        st.success(f"{bm.cancel(bid)}건 취소")
    if c[1].button(
        "잔량 재실행", width="stretch", key=f"br_{bid}", disabled=not mine,
        help="거부·취소·미체결로 남은 수량을 같은 방식으로 다시 보냅니다 (바스켓을 실행한 트레이더만)",
    ):
        st.success(f"{bm.retry(bid)}종목 재전송")
    limit_mode = b.params.mode in (ExecMode.AGGRESSIVE, ExecMode.PASSIVE)
    if c[2].button("현재 호가로 정정", width="stretch", key=f"bp_{bid}", disabled=not (limit_mode and mine)):
        st.success(f"{bm.reprice(bid)}건 정정")


def basket_view(oms: OMS) -> None:
    with st.expander("바스켓 구성·실행", expanded=True):
        build_section(oms)
    st.markdown("#### 바스켓 모니터")
    monitor_section(oms)
    st.caption(
        "종목: " + ", ".join(symbol_label(oms, s) for s, i in oms.instruments.items() if i.asset_class == "주식")
    )
