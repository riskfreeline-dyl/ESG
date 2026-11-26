"""RFL OMS 1단계 — Streamlit 화면.

실행: streamlit run app.py
모든 시세와 체결은 시뮬레이션이며 실제 시장과 연결되어 있지 않습니다.
"""

from __future__ import annotations

import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS, AlertLevel, MarketSim, OrderType, RiskLimits, Side, TimeInForce
from views.algo_view import algo_view
from views.basket_view import basket_view
from views.common import NUM, fmt_price, krw

st.set_page_config(page_title="RFL OMS", page_icon="📈", layout="wide")

LEVEL_ICON = {AlertLevel.INFO: "🔵", AlertLevel.WARNING: "🟠", AlertLevel.CRITICAL: "🔴"}


def get_oms() -> OMS:
    if "oms" not in st.session_state:
        st.session_state.oms = OMS(market=MarketSim(seed=None))
        st.session_state.last_auto_step = time.time()
    return st.session_state.oms


# ============================== 사이드바 ==============================
def sidebar(oms: OMS) -> tuple[bool, float]:
    st.sidebar.title("RFL OMS")
    st.sidebar.caption("1단계 · 모의 체결 환경")

    st.sidebar.subheader("시장 시뮬레이션")
    c1, c2 = st.sidebar.columns(2)
    if c1.button("1틱 진행", width="stretch"):
        oms.step(1)
    if c2.button("10틱 진행", width="stretch"):
        oms.step(10)
    auto = st.sidebar.toggle("자동 진행", value=False)
    interval = st.sidebar.slider("진행 간격(초)", 0.5, 5.0, 1.0, 0.5, disabled=not auto)
    st.sidebar.caption(f"현재 틱: {oms.market.tick_no:,}")

    st.sidebar.subheader("거래 통제")
    kill = st.sidebar.toggle(
        "킬 스위치 (거래 중지)", value=oms.kill_switch, help="켜면 미체결 주문을 모두 취소하고 신규 주문을 막습니다."
    )
    if kill != oms.kill_switch:
        oms.set_kill_switch(kill)
    if st.sidebar.button("미체결·알고 전체 취소", width="stretch"):
        a = oms.algos.cancel_all("전체 취소")
        n = oms.cancel_all()
        st.sidebar.success(f"주문 {n}건 · 알고 {a}건 취소")

    st.sidebar.subheader("리스크 한도")
    lim = oms.limits
    with st.sidebar.form("limits"):
        capital = st.number_input("계좌 자본(원)", min_value=0.0, value=float(lim.capital), step=1e8, format="%.0f")
        max_qty = st.number_input("주문당 최대 수량", min_value=1, value=int(lim.max_order_qty), step=100)
        max_notional = st.number_input(
            "주문당 최대 명목(원)", min_value=0.0, value=float(lim.max_order_notional), step=1e7, format="%.0f"
        )
        band = st.number_input("가격 괴리 허용(%)", min_value=0.1, value=float(lim.price_band_pct), step=0.5)
        max_pos = st.number_input(
            "종목별 포지션 한도(원)", min_value=0.0, value=float(lim.max_position_notional), step=1e8, format="%.0f"
        )
        max_gross = st.number_input(
            "총 노출 한도(원)", min_value=0.0, value=float(lim.max_gross_exposure), step=1e8, format="%.0f"
        )
        max_loss = st.number_input(
            "일일 손실 한도(원)", min_value=0.0, value=float(lim.max_daily_loss), step=1e6, format="%.0f"
        )
        warn = st.slider("경고 알림 기준(한도 대비)", 0.5, 0.99, float(lim.warn_ratio), 0.01)
        restricted = st.multiselect(
            "거래 제한 종목",
            options=list(oms.instruments),
            default=sorted(lim.restricted_symbols),
            format_func=lambda s: f"{s} {oms.instruments[s].name}",
        )
        if st.form_submit_button("한도 적용", width="stretch"):
            oms.limits = RiskLimits(
                capital=capital,
                max_order_qty=int(max_qty),
                max_order_notional=max_notional,
                price_band_pct=band,
                max_position_notional=max_pos,
                max_gross_exposure=max_gross,
                max_daily_loss=max_loss,
                warn_ratio=warn,
                restricted_symbols=frozenset(restricted),
            )
            oms._evaluate_alerts()
            st.success("한도를 적용했습니다")

    if st.sidebar.button("세션 초기화", type="secondary", width="stretch"):
        del st.session_state["oms"]
        st.rerun()
    return auto, interval


# ============================== 본문 ==============================
def header_metrics(oms: OMS) -> None:
    pnl = oms.daily_pnl()
    exp = oms.exposure()
    cols = st.columns(6)
    cols[0].metric("평가자산", krw(oms.equity()))
    cols[1].metric("일일 손익", krw(pnl), delta=f"{pnl / oms.limits.capital:.2%}" if oms.limits.capital else None)
    cols[2].metric("실현 손익", krw(oms.realized_pnl()))
    cols[3].metric("증거금(체결 기준)", krw(oms.margin_used()))
    cols[4].metric("총 노출(미체결 포함)", krw(exp.gross))
    n_algos = sum(1 for a in oms.algos.algos.values() if a.status.is_active)
    cols[5].metric("미체결 · 실행중 알고", f"{len(oms.open_orders())} · {n_algos}")
    n_alerts = sum(1 for a in oms.alerts if a.level is not AlertLevel.INFO)
    if n_alerts:
        st.caption(f"경고·위험 알림 {n_alerts}건 — 알림 탭에서 확인하세요")
    if oms.kill_switch:
        st.error("킬 스위치가 켜져 있습니다. 신규 주문이 차단됩니다.", icon="⛔")


def market_watch(oms: OMS) -> None:
    rows = []
    for s, inst in oms.instruments.items():
        q = oms.market.quote(s)
        rows.append(
            {
                "종목코드": s,
                "종목명": inst.name,
                "자산군": inst.asset_class,
                "매수호가": q.bid,
                "매도호가": q.ask,
                "기준가": q.mid,
                "등락률(%)": round(q.change_pct, 2),
                "승수": inst.multiplier,
                "증거금률": inst.margin_rate,
                "보유": oms.positions[s].qty,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            **{k: NUM for k in ["매수호가", "매도호가", "기준가", "승수", "보유"]},
            "증거금률": st.column_config.NumberColumn(format="percent"),
        },
    )


def price_chart(oms: OMS, symbol: str) -> None:
    hist = oms.market.history[symbol]
    df = pd.DataFrame(hist, columns=["tick", "price"])
    fig = go.Figure(go.Scatter(x=df["tick"], y=df["price"], mode="lines", line=dict(width=1.6)))
    for o in oms.open_orders():
        if o.symbol == symbol and o.limit_price is not None:
            fig.add_hline(
                y=o.limit_price,
                line_dash="dot",
                line_color="#2e7d32" if o.side is Side.BUY else "#c62828",
                annotation_text=f"{o.order_id} {o.side.value} {o.leaves_qty:,}",
            )
    fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="틱", yaxis_title=None)
    st.plotly_chart(fig, width="stretch")


def order_book(oms: OMS, symbol: str) -> None:
    b = oms.market.book(symbol)
    asks = list(reversed(b["asks"]))
    rows = [{"매도잔량": f"{v:,}", "가격": fmt_price(oms, symbol, p), "매수잔량": ""} for p, v in asks]
    rows += [{"매도잔량": "", "가격": fmt_price(oms, symbol, p), "매수잔량": f"{v:,}"} for p, v in b["bids"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=388)


def show_checks(checks) -> None:
    df = pd.DataFrame(
        [
            {
                "결과": "✅" if c.passed else "❌",
                "점검 항목": c.name,
                "내용": c.detail,
                "사용률": min(c.usage, 9.99) if c.usage is not None else None,
            }
            for c in checks
        ]
    )
    st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        column_config={"사용률": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent")},
    )


def order_entry(oms: OMS) -> None:
    left, mid, right = st.columns([1.1, 1.6, 1.0])
    with left:
        symbol = st.selectbox(
            "종목",
            list(oms.instruments),
            format_func=lambda s: f"{s} · {oms.instruments[s].name}",
            key="entry_symbol",
        )
        inst = oms.instruments[symbol]
        q = oms.market.quote(symbol)
        with st.form("order_form"):
            side = st.radio("구분", [Side.BUY, Side.SELL], format_func=lambda x: x.value, horizontal=True)
            otype = st.radio("유형", [OrderType.LIMIT, OrderType.MARKET], format_func=lambda x: x.value, horizontal=True)
            qty = st.number_input("수량", min_value=1, value=10, step=1)
            price = st.number_input(
                f"지정가 (호가단위 {inst.tick_size:g})",
                min_value=float(inst.tick_size),
                value=float(q.bid),
                step=float(inst.tick_size),
                format=f"%.{inst.price_decimals}f",
                key=f"px_{symbol}",
            )
            tif = st.radio("유효조건", [TimeInForce.DAY, TimeInForce.IOC], format_func=lambda x: x.value, horizontal=True)
            tag = st.text_input("전략 태그 (선택)", "")
            b1, b2 = st.columns(2)
            do_preview = b1.form_submit_button("사전 점검", width="stretch")
            do_submit = b2.form_submit_button("주문 제출", type="primary", width="stretch")

        limit_px = inst.round_to_tick(price) if otype is OrderType.LIMIT else None
        if do_preview:
            st.session_state.last_checks = ("미리보기", oms.preview(symbol, side, otype, int(qty), limit_px, tif))
        if do_submit:
            checks = oms.preview(symbol, side, otype, int(qty), limit_px, tif)
            order = oms.submit(symbol, side, otype, int(qty), limit_px, tif, strategy_tag=tag)
            st.session_state.last_checks = (f"{order.order_id} → {order.status.value}", checks)
            if order.reject_reason:
                st.error(f"{order.order_id} 거부: {order.reject_reason}")
            else:
                st.success(
                    f"{order.order_id} {order.status.value} · 체결 {order.filled_qty:,}/{order.qty:,}"
                    + (f" @ {order.avg_fill_price:,.4g}" if order.filled_qty else "")
                )
    with mid:
        st.markdown(f"**{inst.name}** 시세")
        price_chart(oms, symbol)
        if "last_checks" in st.session_state:
            title, checks = st.session_state.last_checks
            if checks:
                st.markdown(f"**사전 리스크 점검** · {title}")
                show_checks(checks)
    with right:
        st.markdown("**호가 (5단계)**")
        order_book(oms, symbol)


def orders_frame(oms: OMS, orders) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "주문번호": o.order_id,
                "시각": o.created_at.strftime("%H:%M:%S"),
                "종목": f"{o.symbol} {oms.instruments[o.symbol].name}",
                "구분": o.side.value,
                "유형": o.order_type.value,
                "조건": o.tif.value,
                "가격": fmt_price(oms, o.symbol, o.limit_price),
                "수량": o.qty,
                "체결": o.filled_qty,
                "잔량": o.leaves_qty,
                "평균체결가": round(o.avg_fill_price, 4) if o.filled_qty else None,
                "상태": o.status.value,
                "전략": o.strategy_tag,
                "거부 사유": o.reject_reason,
            }
            for o in reversed(list(orders))
        ]
    )


def blotter(oms: OMS) -> None:
    c1, c2 = st.columns([3, 1])
    status_filter = c1.segmented_control(
        "보기", ["전체", "미체결", "체결", "취소/거부"], default="전체", key="blotter_filter"
    )
    hide_children = c2.checkbox("알고 자식주문 숨기기", value=True, help="TWAP/VWAP/POV가 낸 분할 주문을 목록에서 감춥니다")
    orders = list(oms.orders.values())
    if hide_children:
        orders = [o for o in orders if o.strategy_tag not in oms.algos.algos]
    if status_filter == "미체결":
        orders = [o for o in orders if o.status.is_open]
    elif status_filter == "체결":
        orders = [o for o in orders if o.filled_qty > 0]
    elif status_filter == "취소/거부":
        orders = [o for o in orders if o.status.value in ("취소", "거부")]
    if orders:
        st.dataframe(
            orders_frame(oms, orders),
            hide_index=True,
            width="stretch",
            column_config={"수량": NUM, "체결": NUM, "잔량": NUM},
        )
    else:
        st.info("표시할 주문이 없습니다.")

    st.markdown("#### 정정 · 취소")
    open_orders = oms.open_orders()
    if not open_orders:
        st.caption("미체결 주문이 없습니다.")
    else:
        oid = st.selectbox(
            "대상 주문",
            [o.order_id for o in open_orders],
            format_func=lambda i: (
                f"{i} · {oms.orders[i].symbol} {oms.orders[i].side.value} "
                f"{oms.orders[i].leaves_qty:,} @ {fmt_price(oms, oms.orders[i].symbol, oms.orders[i].limit_price)}"
            ),
        )
        o = oms.orders[oid]
        inst = oms.instruments[o.symbol]
        c1, c2, c3, c4 = st.columns([1, 1, 0.6, 0.6])
        new_qty = c1.number_input("정정 수량(총)", min_value=o.filled_qty + 1, value=o.qty, step=1, key=f"aq_{oid}")
        new_px = c2.number_input(
            "정정 가격",
            min_value=float(inst.tick_size),
            value=float(o.limit_price or oms.market.mark(o.symbol)),
            step=float(inst.tick_size),
            format=f"%.{inst.price_decimals}f",
            key=f"ap_{oid}",
            disabled=o.order_type is not OrderType.LIMIT,
        )
        c3.write("")
        c4.write("")
        if c3.button("정정", width="stretch"):
            ok, res = oms.amend(oid, int(new_qty), inst.round_to_tick(new_px))
            if ok:
                st.success(f"{oid} 정정 완료 ({o.status.value})")
            else:
                st.error(res if isinstance(res, str) else "정정 거부: " + "; ".join(c.name for c in res if not c.passed))
        if c4.button("취소", width="stretch"):
            oms.cancel(oid)
            st.success(f"{oid} 취소")

    st.markdown("#### 주문 라이프사이클")
    if oms.orders:
        sel = st.selectbox("주문 선택", list(reversed(oms.orders)), key="lifecycle_sel")
        events = oms.orders[sel].events
        st.dataframe(
            pd.DataFrame([{"시각": e.ts.strftime("%H:%M:%S.%f")[:-3], "단계": e.event, "내용": e.detail} for e in events]),
            hide_index=True,
            width="stretch",
        )


def positions_view(oms: OMS) -> None:
    rows = []
    for s, p in oms.positions.items():
        if p.qty == 0 and p.realized_pnl == 0:
            continue
        inst = oms.instruments[s]
        mark = oms.market.mark(s)
        notional = abs(p.qty) * mark * inst.multiplier
        rows.append(
            {
                "종목": f"{s} {inst.name}",
                "수량": p.qty,
                "평균단가": round(p.avg_price, 4),
                "기준가": mark,
                "평가금액": notional,
                "미실현손익": round(oms.unrealized_pnl(s)),
                "실현손익": round(p.realized_pnl),
                "증거금": round(notional * inst.margin_rate),
            }
        )
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={k: NUM for k in ["수량", "평가금액", "미실현손익", "실현손익", "증거금"]},
        )
    else:
        st.info("보유 포지션이 없습니다.")

    st.markdown("#### 체결 내역")
    if oms.fills:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "시각": f.ts.strftime("%H:%M:%S"),
                        "주문번호": f.order_id,
                        "종목": f.symbol,
                        "구분": f.side.value,
                        "수량": f.qty,
                        "가격": f.price,
                    }
                    for f in reversed(oms.fills)
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={"수량": NUM},
        )
    else:
        st.caption("체결 내역이 없습니다.")


def risk_view(oms: OMS) -> None:
    warn = oms.limits.warn_ratio
    for row in oms.utilization():
        ratio = row["사용률"]
        icon = "🔴" if ratio >= 1 else "🟠" if ratio >= warn else "🟢"
        st.markdown(f"{icon} **{row['항목']}** — {row['사용']:,.0f} / {row['한도']:,.0f} ({ratio:.1%})")
        st.progress(min(max(ratio, 0.0), 1.0))
    lim = oms.limits
    st.markdown("#### 적용 중인 한도")
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
    st.caption("노출과 증거금은 미체결 주문이 모두 체결된다고 가정한 최악의 경우로 계산합니다. 위험을 줄이는 주문은 한도를 넘어도 허용됩니다.")


def alerts_view(oms: OMS) -> None:
    c1, c2 = st.columns([2, 1])
    with c1:
        levels = st.multiselect(
            "등급", list(AlertLevel), default=list(AlertLevel), format_func=lambda x: f"{LEVEL_ICON[x]} {x.value}"
        )
        alerts = [a for a in reversed(oms.alerts) if a.level in levels]
        if alerts:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "시각": a.ts.strftime("%H:%M:%S"),
                            "등급": f"{LEVEL_ICON[a.level]} {a.level.value}",
                            "분류": a.category,
                            "내용": a.message,
                        }
                        for a in alerts
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("알림이 없습니다.")
    with c2:
        st.markdown("**가격 알림 추가**")
        with st.form("price_rule"):
            sym = st.selectbox("종목", list(oms.instruments), format_func=lambda s: f"{s} {oms.instruments[s].name}")
            cond = st.radio("조건", ["이상", "이하"], horizontal=True)
            px = st.number_input("가격", min_value=0.0, value=float(oms.market.mark(sym)), format="%.4f")
            if st.form_submit_button("추가", width="stretch"):
                r = oms.add_price_rule(sym, cond, px)
                st.success(f"{r.rule_id} 등록")
        if oms.price_rules:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"규칙": r.rule_id, "종목": r.symbol, "조건": f"{r.price:,} {r.condition}", "상태": "대기" if r.active else "발생"}
                        for r in oms.price_rules
                    ]
                ),
                hide_index=True,
                width="stretch",
            )


def audit_view(oms: OMS) -> None:
    df = pd.DataFrame(
        [
            {"시각": e.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], "주문번호": e.order_id, "단계": e.event, "내용": e.detail}
            for e in reversed(oms.audit)
        ]
    )
    if df.empty:
        st.info("기록된 이벤트가 없습니다.")
        return
    st.dataframe(df, hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    c1.download_button(
        "감사 로그 CSV", df.to_csv(index=False).encode("utf-8-sig"), "rfl_oms_audit.csv", "text/csv", width="stretch"
    )
    c2.download_button(
        "주문 내역 CSV",
        orders_frame(oms, oms.orders.values()).to_csv(index=False).encode("utf-8-sig"),
        "rfl_oms_orders.csv",
        "text/csv",
        width="stretch",
    )


def main_view(auto: bool, interval: float) -> None:
    oms = get_oms()
    if auto and time.time() - st.session_state.last_auto_step >= interval * 0.9:
        oms.step(1)
        st.session_state.last_auto_step = time.time()

    st.title("RFL OMS")
    st.caption("주문관리 · 사전 리스크 점검 · 한도 알림 — 시세와 체결은 모두 시뮬레이션입니다.")
    header_metrics(oms)
    market_watch(oms)

    tabs = st.tabs(
        [
            "주문 입력",
            "바스켓",
            "알고리즘",
            "주문 블로터",
            "포지션·손익",
            "리스크",
            "알림",
            "감사 로그",
        ]
    )
    with tabs[0]:
        order_entry(oms)
    with tabs[1]:
        basket_view(oms)
    with tabs[2]:
        algo_view(oms)
    with tabs[3]:
        blotter(oms)
    with tabs[4]:
        positions_view(oms)
    with tabs[5]:
        risk_view(oms)
    with tabs[6]:
        alerts_view(oms)
    with tabs[7]:
        audit_view(oms)


oms = get_oms()
auto, interval = sidebar(oms)
st.fragment(main_view, run_every=interval if auto else None)(auto, interval)
