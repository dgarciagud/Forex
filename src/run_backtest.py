"""Ejecuta el backtest de la Estrategia 27 (y la 26 como referencia) y guarda
resultados en results/<bar>/.

Uso: python src/run_backtest.py [--start 2010-01-01] [--bar 1h|2h]
"""
import argparse
import warnings
from dataclasses import replace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from carver_s27 import (ROOT, Config, daily_from_hourly, daily_signals, load_hourly,
                        quote_per_usd, simulate_pair, stats)

warnings.simplefilter("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*Sorting by default.*")

PAIRS = ["EURCHF", "EURNOK", "USDCAD", "USDJPY"]

VARIANTS = {
    "S26 mean reversion": dict(trend_filter=False, vol_attenuation=False),
    "S27 solo filtro tendencia": dict(trend_filter=True, vol_attenuation=False),
    "S27 completa": dict(trend_filter=True, vol_attenuation=True),
}
BUFFERS = {"1 lote": 0.0, "10%": 0.10, "25%": 0.25, "50%": 0.50}


def run(cfg, hourly, daily_px, start):
    out = {}
    for p in PAIRS:
        sig = daily_signals(daily_px[p], cfg)
        qpu = quote_per_usd(p, daily_px, daily_px[p].index)
        res = simulate_pair(p, hourly[p], sig, qpu, cfg)
        out[p] = res[res.index >= pd.Timestamp(start, tz="UTC")]
    return out


def to_daily(res, col):
    s = res.groupby("day")[col].sum()
    s.index = pd.DatetimeIndex(s.index)
    return s


def summarise(pp, cfg):
    daily = {p: to_daily(r, "pnl_usd") / cfg.capital for p, r in pp.items()}
    port = pd.concat(daily, axis=1, sort=True).fillna(0).sum(axis=1)
    yrs = port.shape[0] / 256
    cost = sum(r.cost_usd.sum() for r in pp.values()) / cfg.capital / yrs * 100
    lots = sum(r.fills.sum() for r in pp.values()) / port.shape[0]
    return port, daily, {"coste_anual_%": cost, "lotes_por_dia": lots}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--bar", default="1h", help="tamaño de vela: 1h o 2h")
    a = ap.parse_args()
    results = ROOT / "results" / a.bar
    results.mkdir(parents=True, exist_ok=True)

    hourly = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    if a.bar != "1h":
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        hourly = {p: h.resample(a.bar).agg(agg).dropna() for p, h in hourly.items()}
    base = Config(weights={p: 1 / len(PAIRS) for p in PAIRS})
    daily_px = {p: daily_from_hourly(h, base.day_end_hour_utc) for p, h in hourly.items()}

    # 1) Tabla principal: variantes x costes, buffer 10 %
    rows, curves, pair_rows = [], {}, []
    for name, kw in VARIANTS.items():
        for cost_mult, tag in ((0.0, "bruto"), (1.0, "neto")):
            cfg = replace(base, cost_mult=cost_mult, **kw)
            pp = run(cfg, hourly, daily_px, a.start)
            port, daily, extra = summarise(pp, cfg)
            rows.append({"variante": name, "costes": tag, **stats(port), **extra})
            curves[f"{name} | {tag}"] = port
            if tag == "neto":
                for p, r in pp.items():
                    yrs = daily[p].shape[0] / 256
                    pair_rows.append({"variante": name, "par": p, **stats(daily[p]),
                                      "bruto_anual_%": r.gross_usd.sum() / cfg.capital / yrs * 100,
                                      "coste_anual_%": r.cost_usd.sum() / cfg.capital / yrs * 100})

    # 2) Sensibilidad S27 completa: buffer x costes
    sens = []
    for bname, bf in BUFFERS.items():
        for cost_mult in (0.0, 0.5, 1.0):
            cfg = replace(base, buffer_frac=bf, cost_mult=cost_mult, **VARIANTS["S27 completa"])
            port, _, extra = summarise(run(cfg, hourly, daily_px, a.start), cfg)
            st = stats(port)
            sens.append({"buffer": bname, "coste (x medio spread)": cost_mult,
                         "sharpe": st["sharpe"], "ret_anual_%": st["ret_anual_%"],
                         "vol_anual_%": st["vol_anual_%"], "max_dd_%": st["max_dd_%"], **extra})

    summary = pd.DataFrame(rows).round(3)
    pairs = pd.DataFrame(pair_rows).round(3)
    sens = pd.DataFrame(sens).round(3)
    summary.to_csv(results / "resumen_portfolio.csv", index=False)
    pairs.to_csv(results / "resumen_por_par.csv", index=False)
    sens.to_csv(results / "sensibilidad_buffer_costes.csv", index=False)
    pd.DataFrame(curves).to_csv(results / "retornos_diarios_portfolio.csv")

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), sharey=False)
    for k, s in curves.items():
        ax = axes[0] if k.endswith("bruto") else axes[1]
        ax.plot(s.cumsum() * 100, label=k.split(" | ")[0])
    for ax, t in zip(axes, ("bruto (sin costes)", "neto (medio spread por operación)")):
        ax.set_title(f"Retorno acumulado {t} – {a.bar}")
        ax.set_ylabel("% del capital (suma, sin componer)")
        ax.grid(alpha=0.3)
        ax.legend()
    fig.tight_layout()
    fig.savefig(results / "equity_portfolio.png", dpi=110)

    cfg = replace(base, cost_mult=1.0, **VARIANTS["S27 completa"])
    pp = run(cfg, hourly, daily_px, a.start)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for p, r in pp.items():
        ax.plot(to_daily(r, "gross_usd").cumsum() / cfg.capital * 100, label=f"{p} bruto")
    ax.set_title(f"S27 completa – contribución bruta por par (%) – {a.bar}")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(results / "equity_por_par_s27.png", dpi=110)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for t in (summary, pairs, sens):
        print(t.to_string(index=False))
        print()


if __name__ == "__main__":
    main()
