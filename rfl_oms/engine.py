"""RFL OMS 엔진: 주문 라이프사이클, 모의 체결, 포지션·손익, 한도 알림.

주문 흐름: 생성 → 형식 검증 → 보강(라우팅 대상·명목금액·증거금) → 사전 리스크 점검
→ 라우팅(접수) → 체결/부분체결 → (정정·취소·IOC 잔량 취소)
"""

from __future__ import annotations

import copy
from datetime import datetime

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
        self.account = account
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
        return sum(p.realized_pnl for p in self.positions.values())

    def daily_pnl(self) -> float:
        return self.realized_pnl() + sum(self.unrealized_pnl(s) for s in self.positions)

    def equity(self) -> float:
        return self.limits.capital + self.daily_pnl()

    def exposure(self, extra: Order | None = None, exclude_id: str | None = None) -> Exposure:
        """현재 포지션 + 미체결 주문(+ 신규 주문)이 모두 체결될 때의 최악 노출."""
        buys = {s: 0 for s in self.instruments}
        sells = {s: 0 for s in self.instruments}
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
        return Exposure(qty, notional, gross, margin)

    def margin_used(self) -> float:
        """체결된 포지션 기준 증거금."""
        total = 0.0
        for s, inst in self.instruments.items():
            total += abs(self.positions[s].qty) * self.market.mark(s) * inst.multiplier * inst.margin_rate
        return total

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
        ev = OrderEvent(datetime.now(), order.order_id, event, detail)
        order.events.append(ev)
        self.audit.append(ev)

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
        if on:
            n = self.cancel_all("킬 스위치")
            self._alert(AlertLevel.CRITICAL, "킬 스위치", f"거래 중지: 신규 주문 차단, 미체결 {n}건 취소")
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
        realized = self.positions[order.symbol].apply_fill(order.side, qty, price, inst.multiplier)
        fill = Fill(order.order_id, order.symbol, order.side, qty, price, datetime.now())
        self.fills.append(fill)
        label = "전량체결" if order.status is OrderStatus.FILLED else "부분체결"
        extra = f", 실현손익 {realized:,.0f}" if realized else ""
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
            self._check_price_rules()
            self._evaluate_alerts()

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
