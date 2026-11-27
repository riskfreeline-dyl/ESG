"""RFL OMS 엔진: 주문 라이프사이클, 모의 체결, 포지션·손익, 한도 알림.

주문 흐름: 생성 → 형식 검증 → 보강(라우팅 대상·명목금액·증거금) → 사전 리스크 점검
→ 라우팅(접수) → 체결/부분체결 → (정정·취소·IOC 잔량 취소)
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime

from .algo import AlgoEngine
from .arbitrage import ArbEngine
from .basket import BasketManager
from .fees import FeeSchedule
from .market import MarketSim
from .models import (
    Alert,
    AlertLevel,
    Fill,
    Order,
    OrderEvent,
    OrderStatus,
    OrderType,
    Position,
    PriceAlertRule,
    Side,
    TimeInForce,
)
from .risk import CheckResult, Exposure, RiskLimits, pre_trade_checks, static_checks


class OMS:
    def __init__(
        self,
        market: MarketSim | None = None,
        limits: RiskLimits | None = None,
        account: str = "RFL-001",
    ):
        self.market = market or MarketSim()
        self.limits = limits or RiskLimits()
        self.fees = FeeSchedule()
        self.account = account
        self.actor = ""  # 현재 행위자 (acting() 문맥으로 지정)
        self._dirty_orders: set[str] = set()  # 저장소에 아직 반영하지 않은 주문
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.positions: dict[str, Position] = {s: Position(s) for s in self.market.instruments}
        self.audit: list[OrderEvent] = []
        self.alerts: list[Alert] = []
        self.price_rules: list[PriceAlertRule] = []
        self.kill_switch = False
        self._seq = 0
        self._rule_seq = 0
        self._alert_state: dict[str, AlertLevel] = {}
        self.algos = AlgoEngine(self)
        self.baskets = BasketManager(self)
        self.arb = ArbEngine(self)
        # 시장이 한 틱 진행된 뒤, 미체결 주문 매칭 다음에 호출되는 처리기
        self.tick_hooks = [self.algos.on_tick, self.baskets.on_tick, self.arb.on_tick]
        # (틱, 실현손익, 미실현손익, 평가자산, 총노출)
        self.pnl_history: list[tuple[int, float, float, float, float]] = []
        self._record_pnl()

    # ================= 조회·지표 =================
    @property
    def instruments(self):
        return self.market.instruments

    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.status.is_open]

    def unrealized_pnl(self, symbol: str) -> float:
        pos = self.positions[symbol]
        if pos.qty == 0:
            return 0.0
        inst = self.instruments[symbol]
        return (self.market.mark(symbol) - pos.avg_price) * pos.qty * inst.multiplier

    def realized_pnl(self) -> float:
        """실현손익 (비용 차감 전)."""
        return sum(p.realized_pnl for p in self.positions.values())

    def total_fees(self) -> float:
        return sum(p.fees for p in self.positions.values())

    def daily_pnl(self) -> float:
        """순손익 = 실현 + 미실현 − 수수료·세금. 손실 한도와 평가자산의 기준."""
        return self.realized_pnl() + sum(self.unrealized_pnl(s) for s in self.positions) - self.total_fees()

    # ================= 행위자·시스템 이벤트 =================
    @contextmanager
    def acting(self, actor: str):
        """이 문맥 안에서 생긴 주문·이벤트에 행위자를 기록한다."""
        prev, self.actor = self.actor, actor
        try:
            yield self
        finally:
            self.actor = prev

    def system_event(self, event: str, detail: str = "") -> None:
        self.audit.append(OrderEvent(datetime.now(), "-", event, detail, self.actor))

    def set_limits(self, limits: RiskLimits) -> None:
        old, self.limits = self.limits, limits
        changes = [
            f"{k}: {getattr(old, k)} → {getattr(limits, k)}"
            for k in limits.__dataclass_fields__
            if getattr(old, k) != getattr(limits, k)
        ]
        if changes:
            self.system_event("한도 변경", "; ".join(changes))
        self._evaluate_alerts()

    def set_fees(self, fees: FeeSchedule) -> None:
        old, self.fees = self.fees, fees
        changes = [
            f"{k}: {getattr(old, k)} → {getattr(fees, k)}"
            for k in fees.__dataclass_fields__
            if getattr(old, k) != getattr(fees, k)
        ]
        if changes:
            self.system_event("수수료 변경", "; ".join(changes))

    def equity(self) -> float:
        return self.limits.capital + self.daily_pnl()

    def exposure(self, extra: Order | None = None, exclude_id: str | None = None) -> Exposure:
        """현재 포지션 + 미체결 주문 + 알고 잔량(+ 신규 주문)이 모두 체결될 때의 최악 노출."""
        buys = {s: 0 for s in self.instruments}
        sells = {s: 0 for s in self.instruments}
        algo_buys, algo_sells = self.algos.reserved()
        for s, q in algo_buys.items():
            buys[s] += q
        for s, q in algo_sells.items():
            sells[s] += q
        candidates = [o for o in self.open_orders() if o.order_id != exclude_id]
        if extra is not None:
            candidates.append(extra)
        for o in candidates:
            leaves = o.qty - o.filled_qty
            (buys if o.side is Side.BUY else sells)[o.symbol] += leaves
        qty, notional = {}, {}
        gross = margin = 0.0
        for s, inst in self.instruments.items():
            pos = self.positions[s].qty
            worst = max(abs(pos + buys[s]), abs(pos - sells[s]))
            n = worst * self.market.mark(s) * inst.multiplier
            qty[s], notional[s] = worst, n
            gross += n
            margin += n * inst.margin_rate
        # 헤지 상계는 보수적으로: 현재 포지션, 매수 전량 체결, 매도 전량 체결 중 가장 작은 상계만 인정
        pos_now = {s: p.qty for s, p in self.positions.items()}
        all_buys = {s: pos_now[s] + buys[s] for s in pos_now}
        all_sells = {s: pos_now[s] - sells[s] for s in pos_now}
        credit = min(self.hedge_credit(pos_now), self.hedge_credit(all_buys), self.hedge_credit(all_sells))
        return Exposure(qty, notional, gross, margin - credit, margin, credit)

    def hedge_credit(self, signed_qty: dict[str, int]) -> float:
        """지수선물과 구성종목 순노출이 반대 방향이면, 헤지된 금액만큼 선물 증거금을 감면한다."""
        idx = self.market.index_def
        if idx is None or not self.limits.margin_offset_enabled:
            return 0.0
        fsym = idx.futures_symbol
        finst = self.instruments[fsym]
        fut = signed_qty.get(fsym, 0) * self.market.mark(fsym) * finst.multiplier
        stock = sum(signed_qty.get(s, 0) * self.market.mark(s) for s in idx.constituents)
        if fut * stock >= 0:
            return 0.0
        hedged = min(abs(fut), abs(stock))
        return hedged * finst.margin_rate * self.limits.margin_offset_pct / 100

    def margin_breakdown(self) -> dict[str, float]:
        """체결된 포지션 기준 증거금: 상계 전, 상계액, 순증거금."""
        gross = sum(
            abs(p.qty) * self.market.mark(s) * self.instruments[s].multiplier * self.instruments[s].margin_rate
            for s, p in self.positions.items()
        )
        credit = self.hedge_credit({s: p.qty for s, p in self.positions.items()})
        return {"상계 전": gross, "헤지 상계": credit, "순증거금": gross - credit}

    def margin_used(self) -> float:
        """체결된 포지션 기준 순증거금 (헤지 상계 반영)."""
        return self.margin_breakdown()["순증거금"]

    def utilization(self) -> list[dict]:
        """한도별 사용률 (알림과 대시보드 공용)."""
        exp = self.exposure()
        lim = self.limits
        equity = self.equity()
        rows = [
            {"key": "margin", "항목": "증거금 (미체결 포함)", "사용": exp.margin, "한도": equity},
            {"key": "gross", "항목": "총 노출 (미체결 포함)", "사용": exp.gross, "한도": lim.max_gross_exposure},
            {"key": "loss", "항목": "일일 손실", "사용": max(-self.daily_pnl(), 0.0) + 0.0, "한도": lim.max_daily_loss},
        ]
        for s, n in exp.symbol_notional.items():
            if n > 0:
                rows.append(
                    {
                        "key": f"pos:{s}",
                        "항목": f"포지션 · {self.instruments[s].name}",
                        "사용": n,
                        "한도": lim.max_position_notional,
                    }
                )
        for r in rows:
            r["사용률"] = r["사용"] / r["한도"] if r["한도"] > 0 else float("inf")
        return rows

    # ================= 주문 =================
    def _log(self, order: Order, event: str, detail: str = "") -> None:
        ev = OrderEvent(datetime.now(), order.order_id, event, detail, self.actor)
        order.events.append(ev)
        self.audit.append(ev)
        self._dirty_orders.add(order.order_id)

    def _alert(self, level: AlertLevel, category: str, message: str) -> None:
        self.alerts.append(Alert(datetime.now(), level, category, message))

    def _px(self, symbol: str, price: float | None) -> str:
        if price is None:
            return "시장가"
        return f"{price:,.{self.instruments[symbol].price_decimals}f}"

    def _ref_price(self, order: Order) -> float:
        if order.order_type is OrderType.LIMIT and order.limit_price:
            return order.limit_price
        q = self.market.quote(order.symbol)
        return q.ask if order.side is Side.BUY else q.bid

    def _new_order(self, symbol, side, order_type, qty, limit_price, tif, strategy_tag="") -> Order:
        self._seq += 1
        if order_type is OrderType.MARKET:
            limit_price = None
        return Order(
            order_id=f"O{self._seq:06d}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=int(qty),
            limit_price=float(limit_price) if limit_price is not None else None,
            account=self.account,
            tif=TimeInForce.IOC if order_type is OrderType.MARKET else tif,
            created_at=datetime.now(),
            strategy_tag=strategy_tag,
            trader=self.actor,
        )

    def _enrich(self, order: Order) -> None:
        inst = self.instruments[order.symbol]
        order.venue = inst.venue
        order.est_notional = order.qty * self._ref_price(order) * inst.multiplier
        order.est_margin = order.est_notional * inst.margin_rate

    def run_checks(self, order: Order, exclude_id: str | None = None) -> list[CheckResult]:
        inst = self.instruments.get(order.symbol)
        results = static_checks(order, inst)
        if not all(r.passed for r in results):
            return results
        before = self.exposure()
        after = self.exposure(extra=order, exclude_id=exclude_id)
        return results + pre_trade_checks(
            order,
            inst,
            mark=self.market.mark(order.symbol),
            ref_price=self._ref_price(order),
            limits=self.limits,
            before=before,
            after=after,
            equity=self.equity(),
            daily_pnl=self.daily_pnl(),
            kill_switch=self.kill_switch,
        )

    def preview(
        self, symbol, side, order_type, qty, limit_price=None, tif=TimeInForce.DAY
    ) -> list[CheckResult]:
        """주문을 내지 않고 사전 점검 결과만 본다 (주문번호를 소비하지 않음)."""
        draft = self._new_order(symbol, side, order_type, qty, limit_price, tif)
        self._seq -= 1
        return self.run_checks(draft)

    def submit(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        qty: int,
        limit_price: float | None = None,
        tif: TimeInForce = TimeInForce.DAY,
        strategy_tag: str = "",
    ) -> Order:
        order = self._new_order(symbol, side, order_type, qty, limit_price, tif, strategy_tag)
        self.orders[order.order_id] = order
        self._log(
            order,
            "생성",
            f"{symbol} {side.value} {order.qty:,} @{self._px(symbol, order.limit_price)} {order.tif.value}",
        )

        checks = self.run_checks(order)
        failed = [c for c in checks if not c.passed]
        if failed:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "; ".join(f"{c.name}: {c.detail}" for c in failed)
            self._log(order, "거부", order.reject_reason)
            self._alert(AlertLevel.WARNING, "주문 거부", f"{order.order_id} {symbol} — {order.reject_reason}")
            return order

        order.status = OrderStatus.VALIDATED
        self._log(order, "검증 통과", f"사전 점검 {len(checks)}건 통과")
        self._enrich(order)
        self._log(
            order,
            "보강",
            f"라우팅 {order.venue}, 예상 명목 {order.est_notional:,.0f}, 예상 증거금 {order.est_margin:,.0f}",
        )
        order.status = OrderStatus.WORKING
        self._log(order, "라우팅", f"{order.venue} 접수")

        self._match(order)
        self._expire_if_ioc(order)
        self._evaluate_alerts()
        return order

    def amend(
        self, order_id: str, new_qty: int | None = None, new_limit_price: float | None = None
    ) -> tuple[bool, list[CheckResult] | str]:
        order = self.orders.get(order_id)
        if order is None or not order.status.is_open:
            return False, "미체결 상태의 주문만 정정할 수 있습니다"
        if order.order_type is not OrderType.LIMIT:
            return False, "지정가 주문만 정정할 수 있습니다"
        qty = order.qty if new_qty is None else int(new_qty)
        price = order.limit_price if new_limit_price is None else float(new_limit_price)
        if qty == order.qty and price == order.limit_price:
            return False, "변경된 내용이 없습니다"
        if qty <= order.filled_qty:
            msg = f"정정 수량은 체결 수량({order.filled_qty:,})보다 커야 합니다"
            self._log(order, "정정 거부", msg)
            return False, msg

        draft = copy.copy(order)
        draft.events = []
        draft.qty, draft.limit_price = qty, price
        checks = self.run_checks(draft, exclude_id=order.order_id)
        failed = [c for c in checks if not c.passed]
        if failed:
            msg = "; ".join(f"{c.name}: {c.detail}" for c in failed)
            self._log(order, "정정 거부", msg)
            self._alert(AlertLevel.WARNING, "정정 거부", f"{order.order_id} — {msg}")
            return False, checks

        old = f"{order.qty:,}@{self._px(order.symbol, order.limit_price)}"
        order.qty, order.limit_price = qty, price
        self._enrich(order)
        self._log(order, "정정", f"{old} → {qty:,}@{self._px(order.symbol, price)}")
        self._match(order)
        self._evaluate_alerts()
        return True, checks

    def cancel(self, order_id: str, reason: str = "사용자 취소") -> bool:
        order = self.orders.get(order_id)
        if order is None or not order.status.is_open:
            return False
        leaves = order.qty - order.filled_qty
        order.status = OrderStatus.CANCELED
        self._log(order, "취소", f"{reason} (잔량 {leaves:,})")
        self._evaluate_alerts()
        return True

    def cancel_all(self, reason: str = "전체 취소") -> int:
        return sum(self.cancel(o.order_id, reason) for o in self.open_orders())

    def set_kill_switch(self, on: bool) -> None:
        if on == self.kill_switch:
            return
        self.kill_switch = on
        self.system_event("킬 스위치", "켜짐 (거래 중지)" if on else "꺼짐 (거래 재개)")
        if on:
            a = self.algos.cancel_all("킬 스위치")
            n = self.cancel_all("킬 스위치")
            self._alert(
                AlertLevel.CRITICAL, "킬 스위치", f"거래 중지: 신규 주문 차단, 미체결 {n}건·알고 {a}건 취소"
            )
        else:
            self._alert(AlertLevel.INFO, "킬 스위치", "거래 재개")

    # ================= 체결 =================
    def _match(self, order: Order) -> None:
        if not order.status.is_open:
            return
        leaves = order.qty - order.filled_qty
        cap = order.limit_price if order.order_type is OrderType.LIMIT else None
        for price, qty in self.market.take_liquidity(order.symbol, order.side, leaves, cap):
            self._fill(order, qty, price)

    def _fill(self, order: Order, qty: int, price: float) -> None:
        inst = self.instruments[order.symbol]
        order.apply_fill(qty, price)
        pos = self.positions[order.symbol]
        realized = pos.apply_fill(order.side, qty, price, inst.multiplier)
        fee = self.fees.fee(inst, order.side, qty, price)
        pos.fees += fee
        fill = Fill(order.order_id, order.symbol, order.side, qty, price, datetime.now(), fee)
        self.fills.append(fill)
        label = "전량체결" if order.status is OrderStatus.FILLED else "부분체결"
        extra = f", 실현손익 {realized:,.0f}" if realized else ""
        extra += f", 비용 {fee:,.0f}" if fee else ""
        self._log(order, label, f"{qty:,}@{self._px(order.symbol, price)} (누적 {order.filled_qty:,}/{order.qty:,}){extra}")

    def _expire_if_ioc(self, order: Order) -> None:
        if order.status.is_open and order.tif is TimeInForce.IOC:
            reason = "시장가 잔량 취소" if order.order_type is OrderType.MARKET else "IOC 잔량 취소"
            self.cancel(order.order_id, reason)

    def step(self, n: int = 1) -> None:
        """시장을 n틱 진행하고 미체결 주문을 시간 우선 순서로 체결한다."""
        for _ in range(n):
            self.market.step()
            for order in self.open_orders():
                self._match(order)
            for hook in self.tick_hooks:
                hook()
            self._check_price_rules()
            self._evaluate_alerts()
            self._record_pnl()

    def _record_pnl(self) -> None:
        realized = self.realized_pnl() - self.total_fees()  # 비용 차감 후 실현
        unrealized = sum(self.unrealized_pnl(s) for s in self.positions)
        gross = sum(
            abs(p.qty) * self.market.mark(s) * self.instruments[s].multiplier for s, p in self.positions.items()
        )
        self.pnl_history.append(
            (self.market.tick_no, realized, unrealized, self.limits.capital + realized + unrealized, gross)
        )
        del self.pnl_history[:-1000]

    # ================= 알림 =================
    def add_price_rule(self, symbol: str, condition: str, price: float) -> PriceAlertRule:
        self._rule_seq += 1
        rule = PriceAlertRule(f"R{self._rule_seq:03d}", symbol, condition, float(price))
        self.price_rules.append(rule)
        return rule

    def _check_price_rules(self) -> None:
        for rule in self.price_rules:
            if not rule.active:
                continue
            mark = self.market.mark(rule.symbol)
            hit = mark >= rule.price if rule.condition == "이상" else mark <= rule.price
            if hit:
                rule.active = False
                name = self.instruments[rule.symbol].name
                self._alert(
                    AlertLevel.INFO,
                    "가격 알림",
                    f"{name} 현재가 {mark:,.4g}가 {rule.price:,} {rule.condition}에 도달",
                )

    def _evaluate_alerts(self) -> None:
        """한도 사용률이 경고/위험 구간에 새로 들어갈 때만 알림을 만든다."""
        for row in self.utilization():
            ratio = row["사용률"]
            if ratio >= 1:
                level = AlertLevel.CRITICAL
            elif ratio >= self.limits.warn_ratio:
                level = AlertLevel.WARNING
            else:
                self._alert_state.pop(row["key"], None)
                continue
            prev = self._alert_state.get(row["key"])
            rank = {AlertLevel.WARNING: 1, AlertLevel.CRITICAL: 2}
            if prev is None or rank[level] > rank[prev]:
                suffix = " — 신규 위험증가 주문 차단" if row["key"] == "loss" and ratio >= 1 else ""
                self._alert(
                    level,
                    "한도",
                    f"{row['항목']} 사용률 {ratio:.0%} ({row['사용']:,.0f} / {row['한도']:,.0f}){suffix}",
                )
            self._alert_state[row["key"]] = level
