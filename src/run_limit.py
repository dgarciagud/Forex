"""Compara ejecución a mercado (pagando medio spread) con órdenes límite sin spread.

Uso: python src/run_limit.py [--start 2010-01-01]
Guarda results/ejecucion_limite.csv y results/equity_limite_1h.png
"""
import argparse
from dataclasses import replace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from carver_s27 import ROOT, Config, daily_from_hourly, load_hourly, stats
from run_backtest import PAIRS, VARIANTS, run, summarise

EXEC = {
    "mercado, medio spread": dict(execution="close", cost_mult=1.0),
    "mercado, sin costes": dict(execution="close", cost_mult=0.0),
    "límite, al tocar": dict(execution="limit", limit_pen_mult=0.0, cost_mult=1.0),
    "límite, atravesar ½ spread": dict(execution="limit", limit_pen_mult=1.0, cost_mult=1.0),
    "límite, atravesar 1 spread": dict(execution="limit", limit_pen_mult=2.0, cost_mult=1.0),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    a = ap.parse_args()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    h1 = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    rows, curves = [], {}
    for bar in ("1h", "2h"):
        hourly = h1 if bar == "1h" else {p: h.resample(bar).agg(agg).dropna() for p, h in h1.items()}
        base = Config(weights={p: 1 / len(PAIRS) for p in PAIRS})
        daily_px = {p: daily_from_hourly(h, base.day_end_hour_utc) for p, h in hourly.items()}
        for vname in ("S26 mean reversion", "S27 solo filtro tendencia", "S27 completa"):
            for ename, ekw in EXEC.items():
                for buf in (0.10, 0.25):
                    cfg = replace(base, buffer_frac=buf, **VARIANTS[vname], **ekw)
                    pp = run(cfg, hourly, daily_px, a.start)
                    port, daily, extra = summarise(pp, cfg)
                    st = stats(port)
                    per = {f"SR {p}": stats(daily[p])["sharpe"] for p in PAIRS}
                    rows.append({"vela": bar, "variante": vname, "ejecución": ename,
                                 "buffer": f"{int(buf*100)}%", "sharpe": st["sharpe"],
                                 "ret_anual_%": st["ret_anual_%"], "vol_anual_%": st["vol_anual_%"],
                                 "max_dd_%": st["max_dd_%"], "skew_mensual": st["skew_mensual"],
                                 **extra, **per})
                    if bar == "1h" and buf == 0.10 and vname != "S26 mean reversion":
                        curves[f"{vname} | {ename}"] = port
                    print(rows[-1]["vela"], vname, ename, buf, round(st["sharpe"], 2), flush=True)
    df = pd.DataFrame(rows).round(3)
    out = ROOT / "results"
    df.to_csv(out / "ejecucion_limite.csv", index=False)

    fig, ax = plt.subplots(figsize=(12, 6))
    for k, s in curves.items():
        if "S27 solo" in k:
            ax.plot(s.cumsum() * 100, label=k)
    ax.set_title("S27 (filtro de tendencia), 1h, buffer 10 % – ejecución a mercado vs límite")
    ax.set_ylabel("% del capital (suma, sin componer)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "equity_limite_1h.png", dpi=110)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
