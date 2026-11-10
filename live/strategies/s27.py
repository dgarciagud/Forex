"""Estrategia 27 (safer fast mean reversion) para operar en vivo.

Funciones puras (sin MT5) para poder probarlas:
  * daily_state(): lo que se calcula una vez al día con los cierres D1 completos.
    Reutiliza carver_vol y vol_attenuation del backtest (src/carver_s27.py) para que
    live y backtest calculen exactamente lo mismo.
  * bounds(): rango de posiciones permitido (filtro de tendencia + lados + modo).
  * plan_limit(): escalera de órdenes límite del libro (posición ± 1 paso).
  * plan_market(): alternativa del backtest: a mercado una vez por vela H1 con buffer.

Unidades: las posiciones se cuentan en "pasos" enteros (1 paso = volume_step del
símbolo, 0.01 lotes en Darwinex). n_avg = posición media (forecast 10) en pasos.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from carver_s27 import carver_vol, vol_attenuation  # noqa: E402

DEFAULTS = {
    "eq_span": 5,
    "forecast_scalar": 20.0,
    "forecast_cap": 20.0,
    "trend_fast": 16,
    "trend_slow": 64,
    "vol_attenuation": True,
    "execution": "limit",        # "limit" (libro) | "market" (como el backtest del repo)
    "buffer_fraction": 0.10,     # market: buffer; limit: tamaño de orden (mín. 1 paso)
}


@dataclass
class DailyState:
    day: pd.Timestamp       # fecha del último cierre D1 completo usado
    close: float            # último cierre diario
    eq: float               # equilibrio: EWMA span 5 de cierres diarios
    sigma_p: float          # vol diaria en unidades de precio
    vol_pct: float          # vol diaria en %
    trend: int              # signo de EWMAC(16,64) diario: +1 / -1 / 0
    att: float              # multiplicador de vol M (1.0 si está desactivado)
    last_ret: float         # rendimiento del último día
    prev_vol_pct: float     # vol del día anterior (para detectar saltos)


def daily_state(closes: pd.Series, params: dict) -> DailyState:
    p = {**DEFAULTS, **params}
    closes = closes.astype(float).dropna()
    ret = closes.pct_change()
    vol_pct = carver_vol(ret)
    eq = closes.ewm(span=p["eq_span"], adjust=False).mean()
    trend = closes.ewm(span=p["trend_fast"]).mean() - closes.ewm(span=p["trend_slow"]).mean()
    att = vol_attenuation(vol_pct).iloc[-1] if p["vol_attenuation"] else 1.0
    return DailyState(
        day=closes.index[-1],
        close=float(closes.iloc[-1]),
        eq=float(eq.iloc[-1]),
        sigma_p=float(vol_pct.iloc[-1] * closes.iloc[-1]),
        vol_pct=float(vol_pct.iloc[-1]),
        trend=int(np.sign(trend.iloc[-1])),
        att=float(att),
        last_ret=float(ret.iloc[-1]),
        prev_vol_pct=float(vol_pct.iloc[-2]),
    )


def n_avg_steps(capital: float, idm: float, weight: float, size_mult: float, tau: float,
                sigma_p: float, value_per_unit_lot: float, step_lots: float) -> float:
    """Posición media (forecast 10) en pasos.

    value_per_unit_lot: ganancia en divisa de la cuenta de 1 lote por 1 unidad de precio.
    """
    lots = capital * idm * weight * size_mult * tau / (16.0 * sigma_p * value_per_unit_lot)
    return lots / step_lots


def bounds(trend: int, sides: str, mode: str, pos: int, nmax: int) -> tuple[int, int]:
    """Rango [lo, hi] de posición permitido, en pasos."""
    long_ok = sides in ("both", "long") and trend > 0
    short_ok = sides in ("both", "short") and trend < 0
    hi = nmax if long_ok else 0
    lo = -nmax if short_ok else 0
    if mode == "close":
        return 0, 0
    if mode == "reduce_only":
        hi = min(hi, max(pos, 0))
        lo = max(lo, min(pos, 0))
    return lo, hi


def _k(st: DailyState, n_avg: float, params: dict) -> float:
    """Pasos de posición por unidad de precio: N(P) = k * (eq - P)."""
    p = {**DEFAULTS, **params}
    return p["forecast_scalar"] * st.att * n_avg / (10.0 * st.sigma_p)


def _nmax(n_avg: float, max_steps: int, params: dict) -> int:
    p = {**DEFAULTS, **params}
    return max(0, min(math.floor(p["forecast_cap"] / 10.0 * n_avg + 1e-9), max_steps))


def _floor_tick(price: float, tick: float) -> float:
    return round(math.floor(price / tick + 1e-9) * tick, 10)


def _ceil_tick(price: float, tick: float) -> float:
    return round(math.ceil(price / tick - 1e-9) * tick, 10)


@dataclass
class Plan:
    market_steps: int = 0            # >0 comprar, <0 vender a mercado (0 = nada)
    buy_limit: float | None = None   # precio de la compra límite
    sell_limit: float | None = None  # precio de la venta límite
    buy_steps: int = 1               # tamaño de la compra límite en pasos
    sell_steps: int = 1              # tamaño de la venta límite en pasos
    lo: int = 0
    hi: int = 0
    optimal: float = 0.0             # posición óptima sin redondear al precio medio
    reason: str = ""


def limit_order_steps(n_avg: float, params: dict) -> int:
    """Tamaño de cada orden de la escalera en pasos: buffer_fraction x posición media (mín. 1).

    Igual que el backtest del repo en modo límite: órdenes de q pasos, con niveles en los
    precios donde la óptima = posición ± q. q = 1 es la escalera del libro.
    """
    p = {**DEFAULTS, **params}
    return max(1, int(round(p["buffer_fraction"] * n_avg)))


def plan_limit(st: DailyState, n_avg: float, max_steps: int, pos: int, bid: float, ask: float,
               tick: float, sides: str, mode: str, params: dict) -> Plan:
    """Escalera: compra límite de q pasos donde la óptima = pos+q, venta donde = pos-q.

    Si un nivel ya es ejecutable (salto de precio o nuevo día) se va a mercado por los
    niveles ya superados. Las reducciones obligadas (filtro de tendencia, lados, modo) van
    a mercado.
    """
    nmax = _nmax(n_avg, max_steps, params)
    lo, hi = bounds(st.trend, sides, mode, pos, nmax)
    k = _k(st, n_avg, params)
    q = limit_order_steps(n_avg, params)
    mid = 0.5 * (bid + ask)
    opt = min(max(k * (st.eq - mid), lo), hi)
    plan = Plan(lo=lo, hi=hi, optimal=opt)

    if pos > hi or pos < lo:
        plan.market_steps = min(max(pos, lo), hi) - pos
        plan.reason = "fuera de rango permitido"
        return plan
    if k <= 0:
        return plan

    if pos < hi:
        size = min(q, hi - pos)
        level = st.eq - (pos + size) / k
        if ask <= level:
            n_levels = max(1, math.floor((k * (st.eq - ask) - pos) / q))
            plan.market_steps = min(hi, pos + n_levels * q) - pos
            plan.reason = "nivel de compra ya ejecutable"
            return plan
        plan.buy_limit, plan.buy_steps = _floor_tick(level, tick), size
    if pos > lo:
        size = min(q, pos - lo)
        level = st.eq - (pos - size) / k
        if bid >= level:
            n_levels = max(1, math.floor((pos - k * (st.eq - bid)) / q))
            plan.market_steps = max(lo, pos - n_levels * q) - pos
            plan.reason = "nivel de venta ya ejecutable"
            return plan
        plan.sell_limit, plan.sell_steps = _ceil_tick(level, tick), size
    return plan


def plan_market(st: DailyState, n_avg: float, max_steps: int, pos: int, bid: float, ask: float,
                sides: str, mode: str, params: dict, new_bar: bool) -> Plan:
    """Como el backtest del repo: una vez por vela H1, a mercado, con buffer.

    Se opera hasta el borde del buffer si la óptima se aleja >= buffer de la actual.
    Las reducciones obligadas se hacen en cualquier momento.
    """
    p = {**DEFAULTS, **params}
    nmax = _nmax(n_avg, max_steps, params)
    lo, hi = bounds(st.trend, sides, mode, pos, nmax)
    k = _k(st, n_avg, params)
    mid = 0.5 * (bid + ask)
    opt = min(max(k * (st.eq - mid), lo), hi)
    plan = Plan(lo=lo, hi=hi, optimal=opt)
    if pos > hi or pos < lo:
        plan.market_steps = min(max(pos, lo), hi) - pos
        plan.reason = "fuera de rango permitido"
        return plan
    if not new_bar:
        return plan
    buf = max(1.0, p["buffer_fraction"] * n_avg)
    if opt - pos >= buf:
        plan.market_steps = math.floor(opt - buf + 1.0) - pos
    elif pos - opt >= buf:
        plan.market_steps = math.ceil(opt + buf - 1.0) - pos
    if plan.market_steps:
        plan.reason = "óptima fuera del buffer"
    return plan
