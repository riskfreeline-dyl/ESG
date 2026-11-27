"""옵션 가격·민감도: Black-76 (선물 기초자산 유럽형 옵션).

F: 선물가격, K: 행사가, T: 만기(년), r: 할인금리, vol: 변동성(연)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SQRT2 = math.sqrt(2.0)


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


@dataclass
class Greeks:
    price: float
    delta: float  # 선물 1포인트 변화당 옵션가격 변화
    gamma: float
    vega: float  # 변동성 1%p 변화당 옵션가격 변화
    theta: float  # 하루 경과당 옵션가격 변화


def black76(F: float, K: float, T: float, r: float, vol: float, kind: str) -> Greeks:
    disc = math.exp(-r * T)
    if T <= 0 or vol <= 0:
        intrinsic = max(F - K, 0.0) if kind == "C" else max(K - F, 0.0)
        delta = (1.0 if F > K else 0.0) if kind == "C" else (-1.0 if F < K else 0.0)
        return Greeks(intrinsic, delta, 0.0, 0.0, 0.0)
    sq = vol * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * vol * vol * T) / sq
    d2 = d1 - sq
    if kind == "C":
        price = disc * (F * _ncdf(d1) - K * _ncdf(d2))
        delta = disc * _ncdf(d1)
    else:
        price = disc * (K * _ncdf(-d2) - F * _ncdf(-d1))
        delta = -disc * _ncdf(-d1)
    gamma = disc * _npdf(d1) / (F * sq)
    vega = disc * F * _npdf(d1) * math.sqrt(T) / 100
    # 시간 경과에 따른 가격 변화(하루): 수치 미분으로 계산해 콜·풋 모두 일관되게
    dt = 1 / 365
    if T > dt:
        later = black76(F, K, T - dt, r, vol, kind).price
        theta = later - price
    else:
        theta = (max(F - K, 0.0) if kind == "C" else max(K - F, 0.0)) - price
    return Greeks(price, delta, gamma, vega, theta)


def smile_vol(base_vol: float, F: float, K: float, skew: float = -0.6) -> float:
    """행사가가 낮을수록 변동성이 높은 단순 스큐."""
    return min(max(base_vol + skew * (K / F - 1.0), 0.06), 0.8)


# ============================ 포트폴리오 도구 ============================
def option_symbols(oms) -> list[str]:
    return [s for s, i in oms.instruments.items() if i.option is not None]


def chain(oms) -> list[dict]:
    """행사가별 콜·풋 시세와 민감도."""
    rows: dict[float, dict] = {}
    for s in option_symbols(oms):
        spec = oms.instruments[s].option
        q = oms.market.quote(s)
        g = oms.market.option_greeks(s)
        row = rows.setdefault(spec.strike, {"행사가": spec.strike})
        p = "콜" if spec.kind == "C" else "풋"
        row.update({
            f"{p} 종목": s, f"{p} 매수호가": q.bid, f"{p} 매도호가": q.ask, f"{p} 델타": round(g.delta, 3),
            f"{p} 보유": oms.positions[s].qty, "변동성(%)": round(oms.market.option_vol(spec) * 100, 1),
        })
    return [rows[k] for k in sorted(rows)]


def portfolio_greeks(oms) -> dict[str, float]:
    """옵션 + 기초 선물 합계. 델타는 선물 계약 수 환산, 금액은 원화."""
    from .market import OPTION_UNDERLYING

    fut = oms.instruments.get(OPTION_UNDERLYING)
    if fut is None:
        return {}
    F = oms.market.mark(OPTION_UNDERLYING)
    mult = fut.multiplier
    delta = float(oms.positions[OPTION_UNDERLYING].qty)
    gamma = vega = theta = 0.0
    for s in option_symbols(oms):
        q = oms.positions[s].qty
        if not q:
            continue
        g = oms.market.option_greeks(s)
        ratio = oms.instruments[s].multiplier / mult
        delta += q * g.delta * ratio
        gamma += q * g.gamma * ratio
        vega += q * g.vega * oms.instruments[s].multiplier
        theta += q * g.theta * oms.instruments[s].multiplier
    return {
        "델타(선물 계약)": delta,
        "델타 금액": delta * F * mult,
        "감마(1pt당 델타 변화)": gamma,
        "베가(변동성 1%p당 원)": vega,
        "세타(하루당 원)": theta,
    }


def delta_hedge_qty(oms) -> int:
    """델타를 0에 가깝게 만드는 선물 주문 수량 (+매수 / −매도)."""
    g = portfolio_greeks(oms)
    return -round(g.get("델타(선물 계약)", 0.0))


def payoff(oms, points: int = 61, width: float = 0.12) -> list[tuple[float, float, float]]:
    """기초 선물 가격별 (가격, 현재 평가손익, 만기 손익). 옵션·선물 보유분만 대상."""
    from .market import OPTION_RATE, OPTION_UNDERLYING

    F0 = oms.market.mark(OPTION_UNDERLYING)
    fut = oms.instruments[OPTION_UNDERLYING]
    pf = oms.positions[OPTION_UNDERLYING]
    opts = [(s, oms.positions[s]) for s in option_symbols(oms) if oms.positions[s].qty]
    out = []
    for k in range(points):
        F = F0 * (1 - width + 2 * width * k / (points - 1))
        now = expiry = (F - pf.avg_price) * pf.qty * fut.multiplier if pf.qty else 0.0
        for s, p in opts:
            inst = oms.instruments[s]
            spec = inst.option
            val_now = black76(F, spec.strike, oms.market.option_years(spec), OPTION_RATE,
                              smile_vol(oms.market.option_base_vol, F, spec.strike), spec.kind).price
            val_exp = max(F - spec.strike, 0.0) if spec.kind == "C" else max(spec.strike - F, 0.0)
            now += (val_now - p.avg_price) * p.qty * inst.multiplier
            expiry += (val_exp - p.avg_price) * p.qty * inst.multiplier
        out.append((F, now, expiry))
    return out
