"""
Marco de backtest diario de Carver (AFTS) para FX spot y estrategia 21 (Breakout).

Reglas
------
* Breakout(N): rango de N días (máx/mín de cierres diarios), punto medio m.
    bruto = 40 * (P - m) / (máx - mín)          (entre -20 y +20)
    suavizado con EWMA de span N/4, multiplicado por su escalar de forecast.
  Variantes N = 10, 20, 40, 80, 160, 320 (peso igual).
* EWMAC(f, 4f) (estrategia 9): (EWMA_f - EWMA_4f) / sigma_p diaria * escalar.
  Variantes f = 8, 16, 32, 64 (las más rápidas son caras en FX).

Combinación: media ponderada de forecasts (tope +-20 cada uno), multiplicada por el
FDM estimado con la correlación de los forecasts (como en el libro), tope +-20.

Posición: N = F/10 * Cap * IDM * w * tau / (P * sigma%_anual), en unidades de divisa base,
con buffer del 10 % de la posición media (estrategia 8) y ejecución en el cierre del día
siguiente a la señal, pagando medio spread. Sin swaps (carry de tipos) ni comisiones.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from carver_s27 import HALF_SPREAD, carver_vol, quote_per_usd

# Escalares de forecast (valores publicados por Carver para estas variantes).
BREAKOUT_SCALAR = {10: 0.60, 20: 0.67, 40: 0.70, 80: 0.73, 160: 0.74, 320: 0.74}
EWMAC_SCALAR = {2: 12.1, 4: 8.53, 8: 5.95, 16: 4.10, 32: 2.79, 64: 1.91}


@dataclass
class DailyConfig:
    capital: float = 1_000_000.0
    tau: float = 0.20
    idm: float = 1.56
    buffer: float = 0.10
    cost_mult: float = 1.0
    cap: float = 20.0
    unit: float = 1_000.0          # granularidad de la posición (unidades base)
    weights: dict = field(default_factory=dict)


def breakout(close: pd.Series, n: int) -> pd.Series:
    hi = close.rolling(n, min_periods=max(2, n // 2)).max()
    lo = close.rolling(n, min_periods=max(2, n // 2)).min()
    mid = (hi + lo) / 2
    raw = 40.0 * (close - mid) / (hi - lo).replace(0, np.nan)
    return (raw.ewm(span=max(2, n // 4)).mean() * BREAKOUT_SCALAR[n]).clip(-20, 20)


def ewmac(close: pd.Series, sigma_p: pd.Series, f: int) -> pd.Series:
    raw = (close.ewm(span=f).mean() - close.ewm(span=4 * f).mean()) / sigma_p
    return (raw * EWMAC_SCALAR[f]).clip(-20, 20)


def rule_forecasts(close: pd.Series, rules: list[str]) -> pd.DataFrame:
    sigma_p = carver_vol(close.pct_change()) * close
    out = {}
    for r in rules:
        kind, n = r.split("_")
        out[r] = breakout(close, int(n)) if kind == "breakout" else ewmac(close, sigma_p, int(n))
    return pd.DataFrame(out)


def fdm(fc: dict[str, pd.DataFrame], weights: pd.Series) -> float:
    """FDM = 1/sqrt(w' C w), con la correlación de forecasts agrupada entre instrumentos."""
    pooled = pd.concat(fc.values(), axis=0).dropna()
    corr = pooled.corr().clip(lower=0).to_numpy()
    w = weights[pooled.columns].to_numpy()
    return float(min(2.5, 1.0 / np.sqrt(w @ corr @ w)))


def simulate(pair: str, close: pd.Series, forecast: pd.Series, qpu: pd.Series,
             cfg: DailyConfig) -> pd.DataFrame:
    w = cfg.weights.get(pair, 1.0)
    vol_pct = carver_vol(close.pct_change())                # diaria
    cap_q = cfg.capital * qpu
    # posición óptima con F=10 y F real (unidades base)
    n10 = cap_q * cfg.idm * w * cfg.tau / (close * vol_pct * 16.0)
    opt = (forecast / 10.0 * n10)
    hs = HALF_SPREAD[pair] * cfg.cost_mult

    c = close.to_numpy()
    opt_a, buf_a = opt.to_numpy(), (cfg.buffer * n10).to_numpy()
    n = len(c)
    pos = np.zeros(n)
    trade = np.zeros(n)
    cur = 0.0
    target_prev = np.nan
    for i in range(n):
        # ejecuta al cierre de hoy la decisión tomada con el cierre de ayer
        if not np.isnan(target_prev):
            trade[i] = target_prev - cur
            cur = target_prev
        pos[i] = cur
        o, b = opt_a[i], buf_a[i]
        if np.isnan(o) or np.isnan(b):
            target_prev = np.nan
            continue
        lo_b, hi_b = o - b, o + b
        if cur < lo_b:
            target_prev = np.round(lo_b / cfg.unit) * cfg.unit
        elif cur > hi_b:
            target_prev = np.round(hi_b / cfg.unit) * cfg.unit
        else:
            target_prev = np.nan
    pos_s = pd.Series(pos, index=close.index)
    pnl_q = pos_s.shift(1) * close.diff()                   # P&L de la posición de ayer
    cost_q = pd.Series(np.abs(trade) * hs, index=close.index)
    res = pd.DataFrame({"gross_usd": pnl_q / qpu, "cost_usd": cost_q / qpu,
                        "pos": pos_s, "forecast": forecast})
    res["pnl_usd"] = res.gross_usd.fillna(0) - res.cost_usd
    return res
