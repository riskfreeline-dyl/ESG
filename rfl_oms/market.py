"""시뮬레이션 시장: 종목 유니버스, 랜덤워크 시세, 5단계 호가와 잔량 소진."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .models import Instrument, Side

DEFAULT_INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument("005930", "삼성전자", "주식", 100, 1, 1.0, "KRX-SIM", 72_000, 0.0015, 3_000),
    Instrument("000660", "SK하이닉스", "주식", 500, 1, 1.0, "KRX-SIM", 180_000, 0.0020, 1_500),
    Instrument("K200F", "코스피200 선물", "주가지수선물", 0.05, 250_000, 0.10, "KRX-SIM", 350.00, 0.0010, 80),
    Instrument("USDF", "미국달러 선물", "통화선물", 0.1, 10_000, 0.05, "KRX-SIM", 1_380.0, 0.0004, 400),
    Instrument("KTBF", "3년 국채선물", "금리선물", 0.01, 1_000_000, 0.02, "KRX-SIM", 105.50, 0.0002, 300),
    Instrument("GOLD", "KRX 금 (1g)", "금 현물", 10, 1, 1.0, "KRX-SIM", 150_000, 0.0008, 2_000),
)

BOOK_LEVELS = 5


@dataclass
class Quote:
    bid: float
    ask: float
    last: float
    prev_close: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def change_pct(self) -> float:
        return (self.last / self.prev_close - 1) * 100


class MarketSim:
    """틱 단위로 진행하는 결정적(seed 고정 가능) 시장 시뮬레이터.

    - 매수 1호가 = 기준가, 매도 1호가 = 기준가 + 1틱
    - 각 호가 단계의 잔량은 틱마다 새로 생성되고, 같은 틱 안에서는 체결로 소진된다.
    """

    def __init__(self, instruments=DEFAULT_INSTRUMENTS, seed: int | None = 7):
        self.instruments: dict[str, Instrument] = {i.symbol: i for i in instruments}
        self.rng = np.random.default_rng(seed)
        self.tick_no = 0
        self._price = {s: i.start_price for s, i in self.instruments.items()}
        self._prev_close = dict(self._price)
        self._book: dict[str, dict[Side, list[list[float]]]] = {}
        self.history: dict[str, list[tuple[int, float]]] = {s: [] for s in self.instruments}
        for s in self.instruments:
            self._rebuild_book(s)
            self._record(s)

    # ----- 시세 -----
    def quote(self, symbol: str) -> Quote:
        inst = self.instruments[symbol]
        bid = self._price[symbol]
        ask = inst.round_to_tick(bid + inst.tick_size)
        return Quote(bid=bid, ask=ask, last=bid, prev_close=self._prev_close[symbol])

    def mark(self, symbol: str) -> float:
        return self.quote(symbol).mid

    def set_price(self, symbol: str, price: float) -> None:
        """테스트와 시나리오용: 기준가를 강제로 지정한다."""
        self._price[symbol] = self.instruments[symbol].round_to_tick(price)
        self._rebuild_book(symbol)

    def step(self) -> None:
        self.tick_no += 1
        for s, inst in self.instruments.items():
            shock = self.rng.normal(0.0, inst.volatility)
            new_price = inst.round_to_tick(self._price[s] * math.exp(shock))
            self._price[s] = max(new_price, inst.tick_size)
            self._rebuild_book(s)
            self._record(s)

    def _record(self, symbol: str, keep: int = 500) -> None:
        hist = self.history[symbol]
        hist.append((self.tick_no, self.mark(symbol)))
        del hist[:-keep]

    # ----- 호가 -----
    def _rebuild_book(self, symbol: str) -> None:
        inst = self.instruments[symbol]
        q = self.quote(symbol)
        base = inst.base_liquidity
        sizes = self.rng.integers(base // 2, base * 2, size=2 * BOOK_LEVELS)
        self._book[symbol] = {
            # 매수 주문은 매도호가(ask)와, 매도 주문은 매수호가(bid)와 체결된다.
            Side.BUY: [
                [inst.round_to_tick(q.ask + k * inst.tick_size), int(sizes[k])]
                for k in range(BOOK_LEVELS)
            ],
            Side.SELL: [
                [inst.round_to_tick(q.bid - k * inst.tick_size), int(sizes[BOOK_LEVELS + k])]
                for k in range(BOOK_LEVELS)
            ],
        }

    def book(self, symbol: str) -> dict[str, list[tuple[float, int]]]:
        b = self._book[symbol]
        return {
            "asks": [(p, int(v)) for p, v in b[Side.BUY]],
            "bids": [(p, int(v)) for p, v in b[Side.SELL]],
        }

    def take_liquidity(
        self, symbol: str, side: Side, qty: int, price_cap: float | None
    ) -> list[tuple[float, int]]:
        """주문 측(side)에서 호가를 소진하며 체결 목록 [(가격, 수량)]을 돌려준다.

        price_cap이 있으면 매수는 그 가격 이하, 매도는 그 가격 이상에서만 체결한다.
        """
        fills: list[tuple[float, int]] = []
        remaining = qty
        for level in self._book[symbol][side]:
            if remaining <= 0:
                break
            price, avail = level
            if price_cap is not None:
                if side is Side.BUY and price > price_cap + 1e-9:
                    break
                if side is Side.SELL and price < price_cap - 1e-9:
                    break
            take = int(min(avail, remaining))
            if take <= 0:
                continue
            level[1] -= take
            remaining -= take
            fills.append((price, take))
        return fills
