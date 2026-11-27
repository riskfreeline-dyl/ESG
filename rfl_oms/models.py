"""RFL OMS 도메인 모델: 종목, 주문, 체결, 포지션, 이벤트, 알림."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "매수"
    SELL = "매도"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderType(str, Enum):
    LIMIT = "지정가"
    MARKET = "시장가"


class TimeInForce(str, Enum):
    DAY = "DAY"  # 당일 유효: 미체결 잔량은 취소 전까지 대기
    IOC = "IOC"  # 즉시 체결 후 잔량 취소


class OrderStatus(str, Enum):
    CREATED = "생성"
    VALIDATED = "검증완료"
    WORKING = "접수(미체결)"
    PARTIALLY_FILLED = "부분체결"
    FILLED = "전량체결"
    CANCELED = "취소"
    REJECTED = "거부"

    @property
    def is_open(self) -> bool:
        return self in (OrderStatus.WORKING, OrderStatus.PARTIALLY_FILLED)


class AlertLevel(str, Enum):
    INFO = "정보"
    WARNING = "경고"
    CRITICAL = "위험"


@dataclass(frozen=True)
class OptionSpec:
    underlying: str  # 기초자산(선물) 종목코드
    strike: float
    kind: str  # "C"(콜) 또는 "P"(풋)
    expiry_tick: int  # 만기 시점의 시장 틱


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    asset_class: str
    tick_size: float
    multiplier: float  # 계약승수 (현물은 1)
    margin_rate: float  # 증거금률 (현물은 1.0 = 전액)
    venue: str
    start_price: float
    volatility: float  # 틱당 수익률 표준편차 (시뮬레이션)
    base_liquidity: int  # 호가 단계별 기본 잔량 (시뮬레이션)
    option: OptionSpec | None = None  # 옵션이면 계약 조건

    @property
    def price_decimals(self) -> int:
        text = f"{self.tick_size:.10f}".rstrip("0")
        return len(text.split(".")[1]) if "." in text else 0

    def round_to_tick(self, price: float) -> float:
        return round(round(price / self.tick_size) * self.tick_size, self.price_decimals)

    def is_on_tick(self, price: float) -> bool:
        return abs(self.round_to_tick(price) - price) < self.tick_size * 1e-6


@dataclass
class OrderEvent:
    ts: datetime
    order_id: str  # 시스템 이벤트(한도 변경, 킬 스위치 등)는 "-"
    event: str
    detail: str = ""
    actor: str = ""  # 행위자 (로그인 사용자 또는 시스템)


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: int
    price: float
    ts: datetime
    fee: float = 0.0  # 수수료 + 세금 (원)


@dataclass
class Order:
    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    qty: int
    limit_price: float | None
    account: str
    tif: TimeInForce
    created_at: datetime
    status: OrderStatus = OrderStatus.CREATED
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    venue: str = ""
    est_notional: float = 0.0
    est_margin: float = 0.0
    reject_reason: str = ""
    strategy_tag: str = ""
    trader: str = ""  # 주문을 낸 사용자
    rested: bool = False  # 접수 후 즉시 체결되지 않고 호가에 대기한 적이 있는지 (대기 주문은 지정가로 체결)
    events: list[OrderEvent] = field(default_factory=list)

    @property
    def leaves_qty(self) -> int:
        if self.status.is_open:
            return self.qty - self.filled_qty
        return 0

    def apply_fill(self, qty: int, price: float) -> None:
        total = self.avg_fill_price * self.filled_qty + price * qty
        self.filled_qty += qty
        self.avg_fill_price = total / self.filled_qty
        self.status = (
            OrderStatus.FILLED if self.filled_qty >= self.qty else OrderStatus.PARTIALLY_FILLED
        )


@dataclass
class Position:
    symbol: str
    qty: int = 0
    avg_price: float = 0.0
    realized_pnl: float = 0.0  # 비용 차감 전
    fees: float = 0.0  # 누적 수수료 + 세금

    def apply_fill(self, side: Side, qty: int, price: float, multiplier: float) -> float:
        """평균단가 방식으로 체결을 반영하고, 이번 체결로 실현된 손익을 돌려준다."""
        signed = side.sign * qty
        realized = 0.0
        if self.qty == 0 or (self.qty > 0) == (signed > 0):
            new_qty = self.qty + signed
            self.avg_price = (self.avg_price * abs(self.qty) + price * qty) / abs(new_qty)
            self.qty = new_qty
        else:
            closing = min(abs(signed), abs(self.qty))
            direction = 1 if self.qty > 0 else -1
            realized = (price - self.avg_price) * closing * direction * multiplier
            remaining = abs(signed) - closing
            self.qty += side.sign * closing
            if self.qty == 0:
                self.avg_price = 0.0
            if remaining:  # 포지션 방향 전환
                self.qty = side.sign * remaining
                self.avg_price = price
        self.realized_pnl += realized
        return realized


@dataclass
class Alert:
    ts: datetime
    level: AlertLevel
    category: str
    message: str


@dataclass
class PriceAlertRule:
    rule_id: str
    symbol: str
    condition: str  # "이상" 또는 "이하"
    price: float
    active: bool = True
