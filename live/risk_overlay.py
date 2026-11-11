"""Risk overlay de Carver (AFTS, táctica 4).

Multiplicador M <= 1 que se aplica a las posiciones óptimas de TODOS los pares cuando el
riesgo de la cartera supera su máximo. M es el mínimo de cuatro multiplicadores:

  * riesgo esperado      sqrt(w' Σ w)                 con Σ = vol actual y correlaciones
  * riesgo con saltos    sqrt(w' Σj w)                con cada vol en su percentil 99 histórico
  * correlación choque   Σ |w_i| σ_i                  como si todas las correlaciones fueran ±1
  * apalancamiento       Σ |w_i|

w_i = nominal de la posición óptima SIN escalar / capital (con signo). Cada máximo se calibró
en el percentil 99 del backtest de los 5 pares (ver README), para que actúe ~1 % del tiempo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class OverlayLimits:
    max_risk: float = 0.35
    max_jump_risk: float = 1.10
    max_corr_shock: float = 0.60
    max_leverage: float = 10.0
    quantum: float = 0.05        # M se redondea hacia abajo a múltiplos de esto (menos órdenes movidas)


@dataclass
class OverlayResult:
    multiplier: float
    risk: float
    jump_risk: float
    corr_shock: float
    leverage: float
    binding: str                 # medida que limita ("" si M = 1)


def compute(weights: np.ndarray, vol: np.ndarray, vol_jump: np.ndarray, corr: np.ndarray,
            limits: OverlayLimits) -> OverlayResult:
    w = np.asarray(weights, float)
    corr = np.nan_to_num(np.asarray(corr, float), nan=0.0)
    np.fill_diagonal(corr, 1.0)
    cov = np.outer(vol, vol) * corr
    covj = np.outer(vol_jump, vol_jump) * corr
    measures = {
        "riesgo": (math.sqrt(max(w @ cov @ w, 0.0)), limits.max_risk),
        "saltos": (math.sqrt(max(w @ covj @ w, 0.0)), limits.max_jump_risk),
        "correlación": (float(np.sum(np.abs(w) * vol)), limits.max_corr_shock),
        "apalancamiento": (float(np.sum(np.abs(w))), limits.max_leverage),
    }
    mult, binding = 1.0, ""
    for name, (value, cap) in measures.items():
        if value > cap > 0 and cap / value < mult:
            mult, binding = cap / value, name
    if mult < 1.0 and limits.quantum > 0:
        mult = math.floor(mult / limits.quantum + 1e-9) * limits.quantum
    return OverlayResult(multiplier=mult, risk=measures["riesgo"][0], jump_risk=measures["saltos"][0],
                         corr_shock=measures["correlación"][0], leverage=measures["apalancamiento"][0],
                         binding=binding)
