"""거래비용: 체결마다 수수료와 세금을 계산한다 (모두 조정 가능한 가정값)."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Instrument, Side


@dataclass
class FeeSchedule:
    enabled: bool = True
    equity_commission_bps: float = 1.0  # 주식 매매수수료 (매수·매도 각각)
    equity_sell_tax_bps: float = 15.0  # 주식 매도 거래세 (시뮬레이션 가정값)
    gold_commission_bps: float = 2.0  # 금 현물 수수료
    futures_commission_bps: float = 0.3  # 선물 수수료

    def rate_bps(self, inst: Instrument, side: Side) -> float:
        if inst.asset_class == "주식":
            return self.equity_commission_bps + (self.equity_sell_tax_bps if side is Side.SELL else 0.0)
        if inst.asset_class == "금 현물":
            return self.gold_commission_bps
        return self.futures_commission_bps

    def fee(self, inst: Instrument, side: Side, qty: int, price: float) -> float:
        if not self.enabled:
            return 0.0
        return qty * price * inst.multiplier * self.rate_bps(inst, side) / 1e4
