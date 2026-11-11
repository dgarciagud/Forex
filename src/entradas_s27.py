"""Cuándo entra la estrategia 27: escalera de órdenes límite sobre precios de 1 minuto.

Uso: python src/entradas_s27.py [PAR] [FECHA]   → results/ilustracion/entradas_s27_<PAR>.png
Cuenta de 2.000 EUR, micro-lotes de 0,01. Los parámetros diarios (equilibrio, σ, tendencia, M)
salen de ilustracion_s27.hourly_path; los llenados se simulan con los mínimos/máximos de cada
minuto (orden límite llenada al tocar su nivel, como ilustración).
"""
import io
import sys
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from carver_s27 import ROOT, daily_from_hourly, load_hourly, trading_day
from ilustracion_s27 import MICRO, PAIRS, hourly_path

BLUE, GREEN, RED, GREY, INK, INK2, AQUA = "#2a78d6", "#008300", "#e34948", "#b5b4ae", "#0b0b0b", "#52514e", "#1baf7a"


def load_minutes(pair, year):
    f = ROOT / "data" / "raw_histdata" / f"DAT_ASCII_{pair}_M1_{year}.zip"
    with zipfile.ZipFile(f) as z:
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None,
                         names=["t", "open", "high", "low", "close", "v"])
    idx = pd.to_datetime(df.t, format="%Y%m%d %H%M%S") + pd.Timedelta(hours=5)
    df.index = pd.DatetimeIndex(idx).tz_localize("UTC")
    return df[["open", "high", "low", "close"]]


def ladder(m, E, step, nmax):
    """Escalera de largos (tendencia alcista): compra en E − n·step, vende un peldaño más arriba."""
    pos, fills, path = 0, [], []
    for t, r in m.iterrows():
        while pos < nmax and r.low <= E - (pos + 1) * step:
            pos += 1
            fills.append((t, E - pos * step, +1, pos))
        while pos > 0 and r.high >= E - (pos - 1) * step:
            pos -= 1
            fills.append((t, E - pos * step, -1, pos))
        path.append(pos)
    return pd.Series(path, index=m.index), pd.DataFrame(fills, columns=["t", "precio", "lado", "pos"])


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "EURCHF"
    day = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2025-01-27")
    hourly = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    daily = {p: daily_from_hourly(h, 21) for p, h in hourly.items()}
    hp = hourly_path(pair, hourly[pair], daily)
    hp["fxday"] = trading_day(hp.index, 21)
    d = hp[hp.fxday == day]
    E, sp, M, tr, n10 = (d[k].iloc[0] for k in ("equil", "sp", "att", "trend", "n10"))
    assert tr > 0, "elige un día con tendencia alcista"
    step = MICRO * 10 * sp / (20 * M * n10)          # precio entre peldaños de 0,01 lotes
    nmax = int(np.floor(2 * n10 / MICRO))            # forecast +20 = posición máxima

    m = load_minutes(pair, day.year)
    m = m[(trading_day(m.index, 21) == day)]
    m = m[(m.index >= m.index[0] + pd.Timedelta(hours=8))].iloc[: 60 * 12]   # 12 horas desde el inicio de sesión europea
    pos, fills = ladder(m, E, step, nmax)

    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(13, 9.5), sharex=True, gridspec_kw={"height_ratios": [3.3, 1]})
    t_a, t_b = m.index[0], m.index[-1]
    lo = min(m.low.min(), E - (nmax + 0.5) * step)
    ax.axhspan(E, max(m.high.max(), E + 2 * step), color=GREY, alpha=0.18, lw=0)
    ax.text(t_a, E + 0.5 * step, "  Sobre el equilibrio: no hace nada (la tendencia es alcista, no abre cortos)",
            fontsize=8.5, color=INK2, va="center")
    for n in range(1, nmax + 1):
        lvl = E - n * step
        ax.axhline(lvl, color=GREEN, lw=0.7, alpha=0.6, ls=(0, (4, 3)))
        ax.text(t_b, lvl, f"  peldaño {n}: {n/100:.2f} lotes" + ("  (máximo)" if n == nmax else ""),
                fontsize=8, color=GREEN, va="center", ha="left")
    ax.axhline(E, color=BLUE, lw=2.4)
    ax.text(t_b, E, "  equilibrio: posición 0", fontsize=8.5, color=BLUE, va="center", ha="left", weight="bold")
    ax.plot(m.index, m.close, color=INK, lw=1.0, label="Precio (1 minuto)")
    b, s = fills[fills.lado > 0], fills[fills.lado < 0]
    ax.scatter(b.t, b.precio, marker="^", s=90, color=GREEN, edgecolor="white", lw=1.3, zorder=5,
               label="Compra límite de 0,01 (llenada al tocar el peldaño)")
    ax.scatter(s.t, s.precio, marker="v", s=90, color=RED, edgecolor="white", lw=1.3, zorder=5,
               label="Venta límite de 0,01 (un peldaño más arriba: recoge el beneficio)")
    ax.set_ylim(lo - step, max(m.high.max(), E + 2 * step))
    ax.set_ylabel(pair)
    ax.legend(loc="lower left", fontsize=8.5, frameon=True, facecolor="white", edgecolor="none")
    ax.set_title(f"Cuándo entra la estrategia 27 – {pair}, {day:%d-%m-%Y} (tendencia alcista), cuenta de 2.000 €",
                 loc="left", fontsize=13, pad=40)
    ax.text(0, 1.015, f"Cada {step / (0.01 if pair.endswith('JPY') else 0.0001):.1f} pips por debajo del equilibrio "
            f"hay una compra límite de 0,01 lotes (hasta {nmax/100:.2f}). Cada compra lleva su venta límite un peldaño "
            "más arriba.\nSi el precio cae, va comprando; cuando rebota, vende peldaño a peldaño y queda plano al "
            "volver al equilibrio. Las órdenes se recalculan cada día.", transform=ax.transAxes, fontsize=9,
            color=INK2, va="bottom")
    ax.grid(alpha=0.15)

    ax2.step(pos.index, pos / 100, where="post", color=AQUA, lw=2.2)
    ax2.axhline(0, color=INK2, lw=0.8)
    ax2.set_ylabel("Posición (lotes)")
    ax2.set_ylim(-0.005, (nmax + 1) / 100)
    ax2.grid(alpha=0.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M UTC"))
    for a in (ax, ax2):
        for sp_ in ("top", "right"):
            a.spines[sp_].set_visible(False)
    fig.tight_layout()
    out = ROOT / "results" / "ilustracion" / f"entradas_s27_{pair}.png"
    fig.savefig(out, dpi=130)
    pnl = (-(fills.lado * fills.precio).sum() + pos.iloc[-1] * m.close.iloc[-1]) * MICRO
    print(out, "peldaño (pips):", round(step / 0.0001, 2), "nmax:", nmax, "compras:", len(b), "ventas:", len(s),
          "P&L bruto (CHF):", round(pnl, 2))


if __name__ == "__main__":
    main()
