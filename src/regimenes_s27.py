"""¿En qué entorno de mercado gana o pierde la estrategia 27?

Rentabilidad BRUTA (sin costes, ejecución a mercado con retraso de una vela: medida
insesgada de la ventaja) de la S27 completa, por par y día, agrupada por regímenes:
  * Choppiness del día: eficiencia = |cierre − apertura| / suma |cambios horarios|
    (baja = día de ida y vuelta, alta = día direccional).
  * Tamaño del movimiento del día en volatilidades: |ret diario| / σ.
  * Fuerza de la tendencia (|EWMAC16/64| al inicio del día).
  * Régimen de volatilidad (percentil Q de vol relativa al inicio del día).
  * Año.
Uso: python src/regimenes_s27.py  → results/regimenes/
"""
from dataclasses import replace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from carver_s27 import ROOT, Config, carver_vol, daily_from_hourly, load_hourly, trading_day
from run_backtest import PAIRS, VARIANTS, run

BLUE, RED, INK, INK2 = "#2a78d6", "#e34948", "#0b0b0b", "#52514e"


def regime_frame(pair, h):
    days = trading_day(h.index, 21)
    g = h["close"].groupby(days)
    first_open = h["open"].groupby(days).first()
    close = g.last()
    path = g.apply(lambda s: s.diff().abs().sum())
    eff = (close - first_open).abs() / path.replace(0, np.nan)
    ret = close.pct_change()
    vol = carver_vol(ret)
    move = (ret.abs() / vol.shift(1))
    trend = (close.ewm(span=16).mean() - close.ewm(span=64).mean()) / (vol * close)
    rel = vol / vol.rolling(2500, min_periods=10).mean()
    q = rel.expanding(min_periods=10).rank(pct=True)
    df = pd.DataFrame({"eficiencia": eff, "movimiento": move,
                       "tendencia": trend.abs().shift(1), "vol_q": q.shift(1)})
    df.index = pd.DatetimeIndex(df.index)
    df["par"] = pair
    return df


def main():
    out = ROOT / "results" / "regimenes"
    out.mkdir(parents=True, exist_ok=True)
    hourly = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    daily_px = {p: daily_from_hourly(h, 21) for p, h in hourly.items()}
    cfg = replace(Config(weights={p: 1 / len(PAIRS) for p in PAIRS}), cost_mult=0.0,
                  **VARIANTS["S27 completa"])
    pp = run(cfg, hourly, daily_px, "2010-01-01")

    frames = []
    for p, r in pp.items():
        pnl = r.groupby("day")["gross_usd"].sum() / cfg.capital * 1e4      # pb del capital
        pnl.index = pd.DatetimeIndex(pnl.index)
        reg = regime_frame(p, hourly[p]).reindex(pnl.index)
        reg["pnl_pb"] = pnl
        frames.append(reg)
    df = pd.concat(frames).dropna(subset=["pnl_pb"])
    df = df[(df.index.dayofweek < 5) & (df.index.year <= 2025)]

    def bucket(col, labels, q=None, bins=None):
        b = pd.qcut(df[col], q, labels=labels) if q else pd.cut(df[col], bins, labels=labels)
        t = df.groupby(b, observed=True).agg(pnl_medio_pb=("pnl_pb", "mean"), días=("pnl_pb", "size"))
        t["anualizado_%"] = t.pnl_medio_pb * 256 * len(PAIRS) / 100   # cartera de 4 pares
        t["acierto_%"] = df.groupby(b, observed=True)["pnl_pb"].apply(lambda s: (s > 0).mean() * 100)
        return t.round(2)

    tables = {
        "Tipo de día (eficiencia intradía)": bucket("eficiencia", ["Ida y vuelta (rango)", "Mixto", "Direccional"], q=3),
        "Tamaño del movimiento diario": bucket("movimiento", ["< 0,5 σ", "0,5–1 σ", "1–2 σ", "> 2 σ"],
                                                bins=[0, 0.5, 1, 2, np.inf]),
        "Fuerza de la tendencia de fondo": bucket("tendencia", ["Débil", "Media", "Fuerte"], q=3),
        "Régimen de volatilidad": bucket("vol_q", ["Vol baja", "Vol media", "Vol alta"], bins=[0, 1/3, 2/3, 1]),
    }
    # Desglose por par: rentabilidad media diaria del par anualizada (% capital del par = peso 25 %)
    defs = {"Tipo de día": ("eficiencia", ["Ida y vuelta", "Mixto", "Direccional"], 3, None),
            "Movimiento": ("movimiento", ["<0,5σ", "0,5–1σ", "1–2σ", ">2σ"], None, [0, 0.5, 1, 2, np.inf]),
            "Tendencia": ("tendencia", ["Débil", "Media", "Fuerte"], 3, None),
            "Volatilidad": ("vol_q", ["Baja", "Media", "Alta"], None, [0, 1/3, 2/3, 1])}
    per_pair = {}
    for k, (col, labels, q, bins) in defs.items():
        parts = []
        for p_, d in df.groupby("par"):
            b = pd.qcut(d[col], q, labels=labels) if q else pd.cut(d[col], bins, labels=labels)
            parts.append((d.groupby(b, observed=True)["pnl_pb"].mean() * 256 * len(PAIRS) / 100).rename(p_))
        per_pair[k] = pd.concat(parts, axis=1).T.round(1)
    with open(out / "regimenes_por_par.txt", "w") as f:
        for k, t in per_pair.items():
            f.write(f"== {k} (rentabilidad bruta anualizada, % si todo fuera así)\n{t.to_string()}\n\n")
        yp = df.pivot_table(index=df.index.year, columns="par", values="pnl_pb", aggfunc="sum") / 100
        f.write(f"== Por año y par (% del capital total, bruto)\n{yp.round(2).to_string()}\n")
    print(open(out / "regimenes_por_par.txt").read())

    fig2, axes2 = plt.subplots(1, 4, figsize=(17, 4.8), sharey=True)
    cols = {"EURCHF": "#2a78d6", "EURNOK": "#eb6834", "USDCAD": "#1baf7a", "USDJPY": "#6250d6"}
    for ax, (k, t) in zip(axes2, per_pair.items()):
        x = np.arange(t.shape[1])
        wdt = 0.8 / len(t)
        for i, (p_, row) in enumerate(t.iterrows()):
            ax.bar(x + (i - 1.5) * wdt, row.values, width=wdt * 0.9, color=cols[p_], label=p_)
        ax.set_xticks(x, t.columns, fontsize=9)
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_title(k, fontsize=10.5, loc="left", color=INK)
        ax.set_yscale("symlog", linthresh=50)
        for s_ in ("top", "right"):
            ax.spines[s_].set_visible(False)
        ax.grid(axis="y", alpha=0.25)
    axes2[0].set_ylabel("Rentabilidad bruta anualizada\n(% si todo fuera así; escala symlog)")
    axes2[0].legend(fontsize=9, frameon=False)
    fig2.suptitle("Estrategia 27 por par: ¿se mantiene el patrón?", x=0.01, ha="left", fontsize=12.5)
    fig2.tight_layout()
    fig2.savefig(out / "regimenes_por_par.png", dpi=120)

    yearly = (df.groupby(df.index.year)["pnl_pb"].sum() / 100).round(2).rename("ret_% (bruto, cartera)")
    with open(out / "regimenes.txt", "w") as f:
        for k, t in tables.items():
            f.write(f"== {k}\n{t.to_string()}\n\n")
        f.write(f"== Por año\n{yearly.to_string()}\n")
    print(open(out / "regimenes.txt").read())

    fig, axes = plt.subplots(1, 4, figsize=(16, 4.6), sharey=True)
    for ax, (k, t) in zip(axes, tables.items()):
        v = t["anualizado_%"]
        ax.bar(range(len(v)), v, color=[BLUE if x >= 0 else RED for x in v], width=0.6)
        ax.set_xticks(range(len(v)), v.index, rotation=20, ha="right", fontsize=9)
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_title(k, fontsize=10.5, loc="left", color=INK)
        for i, x in enumerate(v):
            ax.text(i, x + (1.5 if x >= 0 else -1.5), f"{x:+.0f} %", ha="center",
                    va="bottom" if x >= 0 else "top", fontsize=9, color=INK)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Rentabilidad bruta anualizada si todo el año\nfuera así (% capital, 4 pares)")
    fig.suptitle("Estrategia 27 (EURCHF, EURNOK, USDCAD, USDJPY, 2010–2025): ¿cuándo gana y cuándo pierde?",
                 x=0.01, ha="left", fontsize=12.5)
    fig.tight_layout()
    fig.savefig(out / "regimenes_s27.png", dpi=120)


if __name__ == "__main__":
    main()
