"""시뮬레이션 주가지수와 지수선물 이론가.

지수 = Σ(구성종목 주식수 × 가격) / 제수. 제수를 선물 승수와 같게 두면
지수 1단위(구성종목 주식수 그대로)가 선물 1계약의 현물 복제 바스켓이 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

DEFAULT_WEIGHTS = {
    "005930": 0.30,
    "000660": 0.20,
    "005380": 0.10,
    "000270": 0.08,
    "035420": 0.08,
    "105560": 0.08,
    "005490": 0.08,
    "068270": 0.08,
}


@dataclass
class IndexDef:
    name: str
    futures_symbol: str
    constituents: dict[str, int]  # 종목 → 선물 1계약당 주식 수
    divisor: float
    rate: float = 0.035  # 무위험 금리 (연)
    dividend_yield: float = 0.015  # 배당수익률 (연)
    days_to_expiry: int = 30

    def value(self, price: Callable[[str], float]) -> float:
        return sum(q * price(s) for s, q in self.constituents.items()) / self.divisor

    @property
    def carry(self) -> float:
        return (self.rate - self.dividend_yield) * self.days_to_expiry / 365

    def fair_futures(self, index_value: float) -> float:
        """보유비용 모형: F* = S × (1 + (r − d) × T/365)."""
        return index_value * (1 + self.carry)


def build_default_index(start_prices: dict[str, float], futures_symbol: str, futures_price: float, multiplier: float) -> IndexDef:
    """시작 가격 기준으로 선물 이론가가 futures_price가 되도록 구성종목 주식 수를 정한다."""
    idx = IndexDef("RFL 시뮬 지수", futures_symbol, {}, divisor=multiplier)
    target_index = futures_price / (1 + idx.carry)
    unit_value = target_index * multiplier
    idx.constituents = {
        s: max(round(unit_value * w / start_prices[s]), 1) for s, w in DEFAULT_WEIGHTS.items() if s in start_prices
    }
    return idx
