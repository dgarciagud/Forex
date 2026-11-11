"""
Backtest de la Estrategia 27 de Robert Carver ("Advanced Futures Trading
Strategies"): *Safer fast mean reversion*, aplicada a FX spot con datos horarios.

Resumen de la lógica implementada
---------------------------------
Estrategia 26 (base, fast mean reversion):
  * Precio de equilibrio E = EWMA(span=5) de los cierres diarios.
  * Forecast bruto  = (E - P) / sigma_p, donde sigma_p es la vol diaria en precio.
  * Forecast escalado = 9.3 * forecast bruto, limitado a +-20.
  * Posición óptima  N = F/10 * Capital * IDM * w * tau / (P * sigma_anual%)
    Con P_ref y sigma fijos durante el día (P*sigma_anual% = 16*sigma_p), N(P) es
    lineal en el precio:  N(P) = 9.3 * k * (E - P) / (10 * sigma_p),
    con k = Cap*IDM*w*tau / (16*sigma_p), y |N| <= 2*k (forecast 20).
  * Ejecución: en el libro se usan órdenes límite en los precios donde
    N(P) = posición +- 1 contrato. Aquí se evalúa N en cada cierre horario y se
    opera (al cierre) solo si la óptima se aleja >= 1 lote -> mismo buffer.
    (Simular la escalera de límites dentro de la barra con O/H/L/C introduce un
    sesgo negativo fuerte: se pierden las oscilaciones intra-hora; ver README.)

Estrategia 27 (safer) añade, sobre la 26:
  * Filtro de tendencia: si el signo del forecast de reversión es distinto del
    signo de la tendencia (EWMAC 16/64 diario), el forecast se pone a 0
    -> con tendencia alcista solo se permiten largos y con bajista solo cortos.
  * Atenuación por régimen de volatilidad (como en la estrategia 13):
    M = EWMA_10( 2 - 1.5 * Q ), Q = percentil histórico de vol/vol_media_10y.
    El forecast se multiplica por M.

Supuestos de simulación (ver README):
  * Día de trading FX cerrando a las 21:00 UTC. Todo lo diario (E, sigma, tendencia,
    M) se calcula al cierre del día d y se usa durante las horas del día d+1.
  * Ejecución al cierre de cada barra horaria (sin look-ahead: la posición
    nueva empieza a ganar/perder desde la barra siguiente).
  * Coste por unidad negociada configurable (por defecto medio spread típico).
  * P&L en divisa cotizada convertido a USD con el cierre diario. Sin swaps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Medio spread típico (en precio) que se cobra en cada lote negociado.
HALF_SPREAD = {
    "EURCHF": 0.00008,
    "EURNOK": 0.00120,
    "USDCAD": 0.00008,
    "USDJPY": 0.006,
}


@dataclass
class Config:
    capital: float = 1_000_000.0      # USD
    tau: float = 0.20                 # objetivo de riesgo anual
    idm: float = 1.56                 # IDM para 4 instrumentos (tabla del libro)
    lot: float = 10_000.0             # tamaño de lote en unidades de divisa base
    eq_span: int = 5                  # span del EWMA del equilibrio
    fc_scalar: float = 9.3
    fc_cap: float = 20.0
    trend_filter: bool = True         # Estrategia 27
    vol_attenuation: bool = True      # Estrategia 27
    trend_fast: int = 16
    trend_slow: int = 64
    cost_mult: float = 1.0            # multiplicador sobre HALF_SPREAD (0 = sin costes)
    fill_lag: int = 1                 # "close": se ejecuta 1 vela después de la señal (como Carver)
    add_stop_sigma: float | None = None   # no ampliar posición si el precio se ha movido en
                                          # contra > k·σ diaria desde la apertura del día
    execution: str = "close"          # "close": a mercado al cierre; "limit": órdenes límite
    limit_pen_mult: float = 1.0       # penetración exigida a la límite, en medios spreads
    buffer_frac: float = 0.10         # buffer = fracción de la posición con forecast 10 (mín. 1 lote)
    day_end_hour_utc: int = 21
    weights: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Datos
# --------------------------------------------------------------------------
def load_hourly(pair: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{pair}_H1.csv", parse_dates=["time"], index_col="time")
    df = df[~df.index.duplicated()].sort_index()
    return df[["open", "high", "low", "close"]]


def trading_day(idx: pd.DatetimeIndex, day_end_hour: int) -> pd.DatetimeIndex:
    """Asigna cada barra horaria (marcada por su hora de inicio) a su día FX."""
    shift = 24 - day_end_hour
    d = (idx + pd.Timedelta(hours=shift)).floor("D").tz_localize(None)
    dow = d.dayofweek
    # restos del viernes noche -> viernes; domingo noche ya cae en lunes
    d = d - pd.to_timedelta((dow == 5).astype(int), unit="D") + pd.to_timedelta((dow == 6).astype(int), unit="D")
    return pd.DatetimeIndex(d)


def daily_from_hourly(h: pd.DataFrame, day_end_hour: int) -> pd.Series:
    d = h["close"].groupby(trading_day(h.index, day_end_hour)).last()
    return d[d.index.dayofweek < 5]


def quote_per_usd(pair: str, daily_px: dict[str, pd.Series], index) -> pd.Series:
    """Unidades de divisa cotizada por 1 USD (para convertir P&L a USD)."""
    if pair.startswith("USD"):
        return daily_px[pair].reindex(index).ffill()
    # EURxxx: xxx por USD = EURxxx / EURUSD
    eurusd = daily_px["EURUSD"].reindex(index).ffill()
    return (daily_px[pair].reindex(index).ffill() / eurusd)


# --------------------------------------------------------------------------
# Estadísticos diarios
# --------------------------------------------------------------------------
def carver_vol(ret: pd.Series) -> pd.Series:
    """Vol diaria de Carver: EWMA span 32 mezclada 70/30 con su media de 10 años."""
    v = ret.ewm(span=32, min_periods=20).std()
    long = v.rolling(2500, min_periods=10).mean()
    return 0.7 * v + 0.3 * long


def vol_attenuation(vol_pct: pd.Series) -> pd.Series:
    rel = vol_pct / vol_pct.rolling(2500, min_periods=10).mean()
    q = rel.expanding(min_periods=10).rank(pct=True)
    m = (2.0 - 1.5 * q).ewm(span=10).mean()
    return m.fillna(1.0)


def daily_signals(close: pd.Series, cfg: Config) -> pd.DataFrame:
    ret = close.pct_change()
    vol_pct = carver_vol(ret)                       # vol diaria en %
    sigma_p = vol_pct * close                        # vol diaria en precio
    eq = close.ewm(span=cfg.eq_span, adjust=False).mean()
    trend = (close.ewm(span=cfg.trend_fast).mean() - close.ewm(span=cfg.trend_slow).mean())
    att = vol_attenuation(vol_pct) if cfg.vol_attenuation else pd.Series(1.0, index=close.index)
    out = pd.DataFrame({"close": close, "eq": eq, "sigma_p": sigma_p,
                        "trend": np.sign(trend), "att": att})
    # Lo calculado al cierre de d se usa en d+1
    return out.shift(1)


# --------------------------------------------------------------------------
# Simulación horaria con escalera de órdenes límite
# --------------------------------------------------------------------------
def simulate_pair(pair: str, h: pd.DataFrame, sig: pd.DataFrame, qpu: pd.Series,
                  cfg: Config) -> pd.DataFrame:
    w = cfg.weights.get(pair, 1.0)
    days = trading_day(h.index, cfg.day_end_hour_utc)
    o, hi, lo, c = (h[k].to_numpy() for k in ("open", "high", "low", "close"))
    sig = sig.reindex(days)
    eq_a, sp_a, tr_a, at_a = (sig[k].to_numpy() for k in ("eq", "sigma_p", "trend", "att"))
    qpu_a = qpu.reindex(days).ffill().to_numpy()
    day_open = h["open"].groupby(days).transform("first").to_numpy()
    kstop = cfg.add_stop_sigma
    half_spread = HALF_SPREAD[pair] * cfg.cost_mult
    lot = cfg.lot

    pos = 0                       # en lotes
    cash_q = 0.0                  # flujo de caja acumulado en divisa cotizada (desde último mark)
    last_mark = None
    n = len(h)
    pnl_q = np.zeros(n)
    cost_q = np.zeros(n)
    pos_out = np.zeros(n)
    fills_out = np.zeros(n)
    prev_c = np.nan
    pending = None

    for i in range(n):
        E, sp, tr, att, fxq = eq_a[i], sp_a[i], tr_a[i], at_a[i], qpu_a[i]
        bar_pnl = 0.0
        bar_cost = 0.0
        nfills = 0
        # mark-to-market de la posición que traemos desde la barra anterior
        if not math.isnan(prev_c):
            bar_pnl += pos * lot * (c[i] - prev_c)

        valid = not (math.isnan(E) or math.isnan(sp) or sp <= 0 or math.isnan(fxq))
        if valid:
            cap_q = cfg.capital * fxq                            # capital en divisa cotizada
            k = cap_q * cfg.idm * w * cfg.tau / (16.0 * sp)       # unidades base por punto de forecast/10
            A = cfg.fc_scalar * att * k / (10.0 * sp) / lot       # lotes por unidad de precio
            nmax = cfg.fc_cap * k / 10.0 / lot                    # tope (|F|<=20) en lotes
            buf = max(1.0, cfg.buffer_frac * k / lot)
            lo_b, hi_b = -nmax, nmax
            if cfg.trend_filter:
                if tr > 0:
                    lo_b = 0.0
                elif tr < 0:
                    hi_b = 0.0
                else:
                    lo_b = hi_b = 0.0
            A = max(A, 1e-12)

            # posición óptima evaluada al cierre horario, limitada por el filtro
            if cfg.execution == "limit":
                q = max(1, int(round(buf)))       # tamaño de cada orden límite (lotes)
                p0 = o[i]
                hs_raw = HALF_SPREAD[pair]
                pen = hs_raw * cfg.limit_pen_mult
                # 1) reducciones obligadas (filtro de tendencia / tope): a mercado
                if pos > hi_b:
                    d = pos - math.floor(hi_b)
                    pos -= d; bar_pnl -= d * lot * (c[i] - p0)
                    bar_cost += d * lot * half_spread; nfills += d
                elif pos < lo_b:
                    d = math.ceil(lo_b) - pos
                    pos += d; bar_pnl += d * lot * (c[i] - p0)
                    bar_cost += d * lot * half_spread; nfills += d
                start = pos
                # 2) escalera de compras fijada al inicio de la vela: nivel j en el
                #    precio donde la posición óptima = start + j*q
                prev = start
                for j in range(1, 1000):
                    tgt = min(start + j * q, math.floor(hi_b))
                    if tgt <= prev:
                        break
                    level = math.inf if tgt <= lo_b else E - tgt / A
                    if level >= p0:                       # ya ejecutable: a mercado
                        fpx, cst = p0, half_spread
                    elif lo[i] <= level - pen:            # la vela atraviesa el límite
                        fpx, cst = level, 0.0
                    else:
                        break
                    if (kstop is not None and tgt > max(prev, 0)
                            and fpx < day_open[i] - kstop * sp):
                        break                             # filtro: no ampliar largos tras caída > k·σ
                    d = tgt - prev
                    bar_pnl += d * lot * (c[i] - fpx); bar_cost += d * lot * cst
                    nfills += d; prev = tgt
                bought = prev - start
                prev = start
                for j in range(1, 1000):
                    tgt = max(start - j * q, math.ceil(lo_b))
                    if tgt >= prev:
                        break
                    level = -math.inf if tgt >= hi_b else E - tgt / A
                    if level <= p0:
                        fpx, cst = p0, half_spread
                    elif hi[i] >= level + pen:
                        fpx, cst = level, 0.0
                    else:
                        break
                    if (kstop is not None and tgt < min(prev, 0)
                            and fpx > day_open[i] + kstop * sp):
                        break                             # filtro: no ampliar cortos tras subida > k·σ
                    d = prev - tgt
                    bar_pnl -= d * lot * (c[i] - fpx); bar_cost += d * lot * cst
                    nfills += d; prev = tgt
                pos = start + bought - (start - prev)
                n_opt = None
            else:
                n_opt = min(max(A * (E - c[i]), lo_b), hi_b)
            # buffer: solo se opera si la óptima se aleja >= buf lotes (con buf=1
            # equivale a las órdenes límite del libro en pos+1 / pos-1)
            # se opera hasta el borde del buffer (Carver)
            if cfg.execution == "close" and cfg.fill_lag:
                # ejecuta ahora (al cierre de esta vela) la orden decidida en la vela anterior
                if pending is not None and pending != pos:
                    d = abs(pending - pos)
                    bar_cost += d * lot * half_spread
                    nfills = d
                    pos = pending
                pending = None
            if n_opt is None:
                new_pos = pos
            elif n_opt - pos >= buf:
                new_pos = math.floor(n_opt - buf + 1.0)
            elif pos - n_opt >= buf:
                new_pos = math.ceil(n_opt + buf - 1.0)
            else:
                new_pos = pos
            if kstop is not None and n_opt is not None:
                if c[i] < day_open[i] - kstop * sp:
                    new_pos = min(new_pos, max(pos, 0))   # no ampliar largos tras caída > k·σ
                elif c[i] > day_open[i] + kstop * sp:
                    new_pos = max(new_pos, min(pos, 0))   # no ampliar cortos tras subida > k·σ
            if cfg.execution == "close" and cfg.fill_lag:
                pending = new_pos
            elif new_pos != pos:
                nfills = abs(new_pos - pos)
                bar_cost += nfills * lot * half_spread
                pos = new_pos
        pnl_q[i] = bar_pnl
        cost_q[i] = bar_cost
        pos_out[i] = pos
        fills_out[i] = nfills
        prev_c = c[i]

    res = pd.DataFrame({"pnl_q": pnl_q, "cost_q": cost_q, "pos_lots": pos_out,
                        "fills": fills_out, "day": days}, index=h.index)
    res["fxq"] = qpu_a
    res["pnl_usd"] = (res.pnl_q - res.cost_q) / res.fxq
    res["gross_usd"] = res.pnl_q / res.fxq
    res["cost_usd"] = res.cost_q / res.fxq
    return res


# --------------------------------------------------------------------------
# Estadísticas
# --------------------------------------------------------------------------
def stats(daily_ret: pd.Series) -> dict:
    r = daily_ret.dropna()
    if r.std() == 0 or len(r) < 2:
        return {}
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    ann = r.mean() * 256
    vol = r.std() * 16
    weekly = r.groupby(pd.Grouper(freq="W")).sum()
    monthly = r.groupby(pd.Grouper(freq="ME")).sum()
    return {
        "ret_anual_%": 100 * ann,
        "vol_anual_%": 100 * vol,
        "sharpe": ann / vol,
        "max_dd_%": 100 * dd.min(),
        "skew_diario": r.skew(),
        "skew_semanal": weekly.skew(),
        "skew_mensual": monthly.skew(),
        "peor_dia_%": 100 * r.min(),
        "años": len(r) / 256,
    }
