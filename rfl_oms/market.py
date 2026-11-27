"""시뮬레이션 시장: 종목 유니버스, 랜덤워크 시세, 5단계 호가와 잔량 소진."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .index import IndexDef, build_default_index
from .models import Instrument, Side

DEFAULT_INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument("005930", "삼성전자", "주식", 100, 1, 1.0, "KRX-SIM", 72_000, 0.0015, 3_000),
    Instrument("000660", "SK하이닉스", "주식", 500, 1, 1.0, "KRX-SIM", 180_000, 0.0020, 1_500),
    Instrument("K200F", "코스피200 선물", "주가지수선물", 0.05, 250_000, 0.10, "KRX-SIM", 350.00, 0.0010, 80),
    Instrument("USDF", "미국달러 선물", "통화선물", 0.1, 10_000, 0.05, "KRX-SIM", 1_380.0, 0.0004, 400),
    Instrument("KTBF", "3년 국채선물", "금리선물", 0.01, 1_000_000, 0.02, "KRX-SIM", 105.50, 0.0002, 300),
    Instrument("GOLD", "KRX 금 (1g)", "금 현물", 10, 1, 1.0, "KRX-SIM", 150_000, 0.0008, 2_000),
    # 바스켓 구성용 주식 (가격은 시뮬레이션 시작값일 뿐 실제 시세가 아님)
    Instrument("005380", "현대차", "주식", 500, 1, 1.0, "KRX-SIM", 240_000, 0.0018, 800),
    Instrument("000270", "기아", "주식", 100, 1, 1.0, "KRX-SIM", 98_000, 0.0018, 1_200),
    Instrument("035420", "NAVER", "주식", 100, 1, 1.0, "KRX-SIM", 190_000, 0.0020, 700),
    Instrument("105560", "KB금융", "주식", 100, 1, 1.0, "KRX-SIM", 82_000, 0.0014, 1_200),
    Instrument("005490", "POSCO홀딩스", "주식", 500, 1, 1.0, "KRX-SIM", 380_000, 0.0018, 400),
    Instrument("068270", "셀트리온", "주식", 100, 1, 1.0, "KRX-SIM", 175_000, 0.0020, 600),
)

BOOK_LEVELS = 5
EQUITY_MARKET_CORR = 0.6  # 주식 수익률 중 시장 공통요인 비중(상관계수 근사)
BASIS_MEAN_REVERSION = 0.85  # 선물 괴리의 틱당 잔존 비율
BASIS_VOL = 0.30  # 선물 괴리 충격 (지수 포인트)
SESSION_TICKS = 120  # 시뮬레이션 1거래일 = 120틱


def volume_profile(tick: int) -> float:
    """장중 거래량 U자형 패턴 (장 시작·마감에 많고 점심에 적음). 평균 약 1."""
    x = (tick % SESSION_TICKS) / (SESSION_TICKS - 1)
    return 0.5 + 2.0 * (x - 0.5) ** 2 * 3


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

    def __init__(
        self,
        instruments=DEFAULT_INSTRUMENTS,
        seed: int | None = 7,
        index_def: IndexDef | None = None,
        futures_symbol: str = "K200F",
    ):
        self.instruments: dict[str, Instrument] = {i.symbol: i for i in instruments}
        self.rng = np.random.default_rng(seed)
        self.tick_no = 0
        self._price = {s: i.start_price for s, i in self.instruments.items()}
        # 지수선물을 구성종목 지수의 이론가 + 평균회귀 괴리로 움직인다
        if index_def is None and futures_symbol in self.instruments:
            fut = self.instruments[futures_symbol]
            index_def = build_default_index(self._price, futures_symbol, fut.start_price, fut.multiplier)
        self.index_def = index_def if index_def and index_def.constituents else None
        self.basis_dev = 0.0  # 선물가 − 이론가 (포인트)
        self._prev_close = dict(self._price)
        if self.index_def:
            self._link_futures()
        self._prev_close = dict(self._price)
        self._book: dict[str, dict[Side, list[list[float]]]] = {}
        self.history: dict[str, list[tuple[int, float]]] = {s: [] for s in self.instruments}
        self.volume: dict[str, int] = {s: 0 for s in self.instruments}  # 직전 틱 시장 거래량
        self.volume_history: dict[str, list[tuple[int, int]]] = {s: [] for s in self.instruments}
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

    def index_value(self) -> float | None:
        return self.index_def.value(self.mark) if self.index_def else None

    def fair_futures(self) -> float | None:
        if not self.index_def:
            return None
        return self.index_def.fair_futures(self.index_value())

    def _link_futures(self) -> None:
        fsym = self.index_def.futures_symbol
        inst = self.instruments[fsym]
        # 기준가(매수1호가) = 이론가 + 괴리 − 반 틱 → 중간가가 이론가 + 괴리에 가깝게
        self._price[fsym] = inst.round_to_tick(self.fair_futures() + self.basis_dev - inst.tick_size / 2)

    def step(self) -> None:
        self.tick_no += 1
        mkt = self.rng.normal()
        fsym = self.index_def.futures_symbol if self.index_def else None
        for s, inst in self.instruments.items():
            z = self.rng.normal()
            if inst.asset_class == "주식":
                rho = EQUITY_MARKET_CORR
                z = rho * mkt + math.sqrt(1 - rho**2) * z
            if s == fsym:
                continue
            new_price = inst.round_to_tick(self._price[s] * math.exp(z * inst.volatility))
            self._price[s] = max(new_price, inst.tick_size)
        if fsym:
            self.basis_dev = BASIS_MEAN_REVERSION * self.basis_dev + self.rng.normal(0.0, BASIS_VOL)
            self._link_futures()
        for s, inst in self.instruments.items():
            self._rebuild_book(s)
            vol = inst.base_liquidity * volume_profile(self.tick_no) * self.rng.lognormal(0.0, 0.3)
            self.volume[s] = max(int(vol), 1)
            self.volume_history[s].append((self.tick_no, self.volume[s]))
            del self.volume_history[s][:-500]
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
