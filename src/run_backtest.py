"""Ejecuta el backtest de la Estrategia 27 (y la 26 como referencia) y guarda
resultados en results/.

Uso: python src/run_backtest.py [--start 2010-01-01]
"""
import argparse
from dataclasses import replace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from carver_s27 import (ROOT, Config, daily_from_hourly, daily_signals, load_hourly,
                        quote_per_usd, simulate_pair, stats)

PAIRS = ["EURCHF", "EURNOK", "USDCAD", "USDJPY"]
RESULTS = ROOT / "results"

VARIANTS = {
    "S26 mean reversion": dict(trend_filter=False, vol_attenuation=False),
    "S27 solo filtro tendencia": dict(trend_filter=True, vol_attenuation=False),
    "S27 completa (tendencia + vol)": dict(trend_filter=True, vol_attenuation=True),
}


def run(cfg: Config, hourly, daily_px, start):
    per_pair = {}
    for p in PAIRS:
        sig = daily_signals(daily_px[p], cfg)
        qpu = quote_per_usd(p, daily_px, daily_px[p].index)
        res = simulate_pair(p, hourly[p], sig, qpu, cfg)
        res = res[res.index >= pd.Timestamp(start, tz="UTC")]
        per_pair[p] = res
    return per_pair


def to_daily(res, col):
    s = res.groupby("day")[col].sum()
    s.index = pd.DatetimeIndex(s.index)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--bar", default="1h", help="tamaño de vela: 1h o 2h")
    a = ap.parse_args()
    global RESULTS
    RESULTS = ROOT / "results" / a.bar
    RESULTS.mkdir(parents=True, exist_ok=True)

    hourly = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    if a.bar != "1h":
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        hourly = {p: h.resample(a.bar).agg(agg).dropna() for p, h in hourly.items()}
    base = Config(weights={p: 1 / len(PAIRS) for p in PAIRS})
    daily_px = {p: daily_from_hourly(h, base.day_end_hour_utc) for p, h in hourly.items()}

    rows, curves, pair_rows, turnover = [], {}, [], []
    for name, kw in VARIANTS.items():
        for cost_mult, tag in ((0.0, "bruto"), (1.0, "neto")):
            cfg = replace(base, cost_mult=cost_mult, **kw)
            pp = run(cfg, hourly, daily_px, a.start)
            col = "pnl_usd"
            daily = {p: to_daily(r, col) / cfg.capital for p, r in pp.items()}
            port = pd.concat(daily, axis=1).fillna(0).sum(axis=1)
            st = stats(port)
            rows.append({"variante": name, "costes": tag, **st})
            curves[(name, tag)] = port
            if tag == "neto":
                for p, r in pp.items():
                    # estadísticas por par escalando a la misma vol objetivo (w=1)
                    s = stats(daily[p])
                    cost_share = r.cost_usd.sum() / max(r.gross_usd.sum(), 1e-9)
                    pair_rows.append({"variante": name, "par": p, **s,
                                      "fills_por_dia": r.fills.sum() / r.day.nunique(),
                                      "coste/bruto": cost_share})
                    turnover.append(r.assign(variante=name, par=p))

    summary = pd.DataFrame(rows).round(3)
    pairs = pd.DataFrame(pair_rows).round(3)
    summary.to_csv(RESULTS / "resumen_portfolio.csv", index=False)
    pairs.to_csv(RESULTS / "resumen_por_par.csv", index=False)
    pd.DataFrame({f"{k[0]} | {k[1]}": v for k, v in curves.items()}).to_csv(
        RESULTS / "retornos_diarios_portfolio.csv")

    # Gráficos
    fig, ax = plt.subplots(figsize=(11, 6))
    for (name, tag), s in curves.items():
        if tag == "neto":
            ax.plot(s.cumsum() * 100, label=name)
    ax.set_title("Portfolio EURCHF/EURNOK/USDCAD/USDJPY – retorno acumulado neto (%)")
    ax.set_ylabel("% del capital (suma, sin componer)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS / "equity_portfolio.png", dpi=120)

    name = "S27 completa (tendencia + vol)"
    cfg = replace(base, cost_mult=1.0, **VARIANTS[name])
    pp = run(cfg, hourly, daily_px, a.start)
    fig, ax = plt.subplots(figsize=(11, 6))
    for p, r in pp.items():
        ax.plot(to_daily(r, "pnl_usd").cumsum() / cfg.capital * 100, label=p)
    ax.set_title(f"{name} – contribución neta por par (%)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS / "equity_por_par_s27.png", dpi=120)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(summary.to_string(index=False))
    print()
    print(pairs.to_string(index=False))


if __name__ == "__main__":
    main()
