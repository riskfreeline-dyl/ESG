"""리스크 분석: 노출 분해, 집중도, VaR, 스트레스 테스트.

모든 계산은 체결된 포지션 기준이다 (미체결 주문은 한도 점검에서 따로 반영).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .market import SESSION_TICKS

if TYPE_CHECKING:
    from .engine import OMS

Z = {0.95: 1.6449, 0.99: 2.3263}


def position_frame(oms: "OMS") -> pd.DataFrame:
    rows = []
    for s, p in oms.positions.items():
        if p.qty == 0:
            continue
        inst = oms.instruments[s]
        # 옵션은 델타 환산 기초자산 명목으로 노출을 본다
        n = p.qty * oms.exposure_per_unit(s) * (1 if inst.option is None or oms.market.option_greeks(s).delta >= 0 else -1)
        rows.append(
            {
                "종목": s,
                "종목명": inst.name,
                "자산군": inst.asset_class,
                "수량": p.qty,
                "순명목": n,
                "총명목": abs(n),
                "증거금": oms.position_margin(s, p.qty),
            }
        )
    return pd.DataFrame(rows, columns=["종목", "종목명", "자산군", "수량", "순명목", "총명목", "증거금"])


def exposure_by_asset_class(oms: "OMS") -> pd.DataFrame:
    df = position_frame(oms)
    if df.empty:
        return pd.DataFrame(columns=["자산군", "매수", "매도", "순노출", "총노출"])
    df["매수"] = df["순명목"].clip(lower=0)
    df["매도"] = df["순명목"].clip(upper=0)
    out = df.groupby("자산군", as_index=False)[["매수", "매도", "순명목", "총명목"]].sum()
    return out.rename(columns={"순명목": "순노출", "총명목": "총노출"}).sort_values("총노출", ascending=False)


def concentration(oms: "OMS", top: int = 5) -> pd.DataFrame:
    df = position_frame(oms)
    if df.empty:
        return df
    gross = df["총명목"].sum()
    df = df.sort_values("총명목", ascending=False).head(top).copy()
    df["비중"] = df["총명목"] / gross
    return df[["종목", "종목명", "수량", "순명목", "비중"]]


def equity_beta_exposure(oms: "OMS") -> float:
    """주식 + 지수선물 순노출 (지수 방향 위험, 베타 1 가정)."""
    df = position_frame(oms)
    if df.empty:
        return 0.0
    return float(df.loc[df["자산군"].isin(["주식", "주가지수선물", "주가지수옵션"]), "순명목"].sum())


@dataclass
class VarResult:
    historical: float | None  # 1거래일, 손실 금액(양수)
    parametric: float | None
    observations: int
    confidence: float


def value_at_risk(oms: "OMS", confidence: float = 0.99, lookback: int = 250) -> VarResult:
    """과거 틱 수익률로 현재 포트폴리오의 손익 분포를 만들고 1거래일로 환산(√120)."""
    pos = {s: p.qty for s, p in oms.positions.items() if p.qty}
    if not pos:
        return VarResult(0.0, 0.0, 0, confidence)
    series = {}
    for s in pos:
        hist = oms.market.history[s][-(lookback + 1):]
        series[s] = pd.Series({t: px for t, px in hist})
    prices = pd.DataFrame(series).sort_index().dropna()
    rets = prices.pct_change().dropna()
    if len(rets) < 20:
        return VarResult(None, None, len(rets), confidence)
    notional = np.array(
        [pos[s] * oms.market.mark(s) * oms.instruments[s].multiplier for s in rets.columns]
    )
    pnl = rets.values @ notional
    scale = math.sqrt(SESSION_TICKS)
    hist_var = -np.quantile(pnl, 1 - confidence) * scale
    param_var = Z.get(confidence, 2.3263) * pnl.std(ddof=1) * scale
    return VarResult(max(hist_var, 0.0), max(param_var, 0.0), len(rets), confidence)


# 자산군 또는 종목코드 → 가격 변화율
DEFAULT_SCENARIOS: dict[str, dict[str, float]] = {
    "주가 급락 (−5%)": {"주식": -0.05, "주가지수선물": -0.05},
    "주가 급등 (+5%)": {"주식": 0.05, "주가지수선물": 0.05},
    "원/달러 급등 (+3%)": {"통화선물": 0.03, "외환 현물": 0.03},
    "금리 +50bp (국채 −1.3%)": {"금리선물": -0.013, "채권 현물": -0.013},
    "금 급락 (−5%)": {"금 현물": -0.05, "금 선물": -0.05},
    "선물 베이시스 확대 (선물 −1%)": {"주가지수선물": -0.01},
    "변동성 급등 (옵션 +5%p)": {"옵션 변동성": 0.05},
    "복합 위기": {
        "주식": -0.08, "주가지수선물": -0.09, "통화선물": 0.05, "외환 현물": 0.05, "금리선물": 0.008,
        "채권 현물": 0.008, "금 현물": 0.03, "금 선물": 0.03, "옵션 변동성": 0.10,
    },
}


def stress_test(oms: "OMS", scenarios: dict[str, dict[str, float]] | None = None) -> pd.DataFrame:
    scenarios = scenarios or DEFAULT_SCENARIOS
    df = position_frame(oms)
    equity = oms.equity()
    rows = []
    from .options import black76, smile_vol
    from .market import OPTION_RATE

    for name, shocks in scenarios.items():
        pnl = 0.0
        for _, r in df.iterrows():
            inst = oms.instruments[r["종목"]]
            if inst.option is not None:
                # 옵션은 기초자산·변동성 충격을 넣어 가격을 다시 계산 (비선형 반영)
                spec = inst.option
                T = oms.market.option_years(spec)
                F0 = oms.market.mark(spec.underlying)
                F = F0 * (1 + shocks.get(oms.instruments[spec.underlying].asset_class, 0.0))
                vol = smile_vol(oms.market.option_base_vol, F, spec.strike) + shocks.get("옵션 변동성", 0.0)
                base = black76(F0, spec.strike, T, OPTION_RATE, smile_vol(oms.market.option_base_vol, F0, spec.strike), spec.kind).price
                new = black76(F, spec.strike, T, OPTION_RATE, vol, spec.kind).price
                pnl += (new - base) * r["수량"] * inst.multiplier  # 모형가끼리 비교 (호가 반올림 영향 제거)
                continue
            shock = shocks.get(r["종목"], shocks.get(r["자산군"], 0.0))
            pnl += r["순명목"] * shock
        rows.append(
            {
                "시나리오": name,
                "충격": ", ".join(f"{k} {v:+.1%}" for k, v in shocks.items()),
                "예상 손익": round(pnl),
                "평가자산 대비": pnl / equity if equity else None,
                "손실한도 대비": -pnl / oms.limits.max_daily_loss if pnl < 0 and oms.limits.max_daily_loss else 0.0,
            }
        )
    return pd.DataFrame(rows)
