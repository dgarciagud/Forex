"""Efecto de la comisión y los swaps de Darwinex sobre la estrategia 27 (velas 1h).

Uso: python src/run_costes.py [--start 2010-01-01]
Guarda results/costes_swaps.csv.

Escenarios de costes (acumulativos):
  * spread:           medio spread, como el resto del repo
  * +comisión:        además ~0,0025 % del nominal por lado (Darwinex)
  * +comisión+swaps:  además los swaps de Darwinex de HOY aplicados a todo el histórico
                      (aproximación: los tipos de interés de 2010-2025 fueron otros)
y dos juegos de lados: ambos lados, o prohibiendo el lado cuyo swap es caro hoy.
"""
import argparse
from dataclasses import replace

import pandas as pd

from carver_s27 import COMMISSION_DARWINEX, ROOT, Config, daily_from_hourly, load_hourly
from run_backtest import PAIRS, VARIANTS, run, summarise

EXEC = {
    "límite, atravesar ½ spread": dict(execution="limit", limit_pen_mult=1.0, cost_mult=1.0),
    "mercado, medio spread": dict(execution="close", cost_mult=1.0),
}
COSTS = {
    "spread": dict(),
    "+comisión": dict(commission=COMMISSION_DARWINEX),
    "+comisión+swaps": dict(commission=COMMISSION_DARWINEX, swaps=True),
}
# Lado que hoy cobra swap (o no paga): se prohíbe el que lo paga caro
SIDES_SWAP = {"EURCHF": "long", "USDJPY": "long", "EURNOK": "short", "USDCAD": "both"}


def sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * 16) if r.std() > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    a = ap.parse_args()
    hourly = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    base = Config(weights={p: 1 / len(PAIRS) for p in PAIRS}, **VARIANTS["S27 completa"])
    daily_px = {p: daily_from_hourly(h, base.day_end_hour_utc) for p, h in hourly.items()}
    rows = []
    for ename, ekw in EXEC.items():
        for buf in (0.5, 1.0, 1.5):
            for cname, ckw in COSTS.items():
                for sname, sides in (("ambos lados", {}), ("sin lado de swap caro", SIDES_SWAP)):
                    if sides and cname != "+comisión+swaps":
                        continue
                    cfg = replace(base, buffer_frac=buf, sides=sides, **ekw, **ckw)
                    pp = run(cfg, hourly, daily_px, a.start)
                    port, daily, extra = summarise(pp, cfg)
                    yrs = port.shape[0] / 256
                    swap = sum(r.swap_usd.sum() for r in pp.values()) / cfg.capital / yrs * 100
                    comm = sum(r.comm_usd.sum() for r in pp.values()) / cfg.capital / yrs * 100
                    rows.append({"ejecución": ename, "buffer": buf, "costes": cname, "lados": sname,
                                 "sharpe": round(sharpe(port), 2),
                                 "ret_anual_%": round(port.mean() * 256 * 100, 1),
                                 "vol_anual_%": round(port.std() * 16 * 100, 1),
                                 "spread+comisión_%": round(extra["coste_anual_%"], 2),
                                 "comisión_%": round(comm, 2), "swaps_%": round(swap, 2),
                                 **{f"SR {p}": round(sharpe(daily[p]), 2) for p in PAIRS}})
                    print(rows[-1], flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "results" / "costes_swaps.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
