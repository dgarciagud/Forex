"""Backtest de la estrategia 21 (Breakout) frente a tendencia EWMAC y su combinación.

Uso: python src/run_breakout.py [--start 2010-01-01]
Resultados en results/breakout/.
"""
import argparse
from dataclasses import replace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from carver_daily import DailyConfig, fdm, rule_forecasts, simulate
from carver_s27 import ROOT, daily_from_hourly, load_hourly, quote_per_usd, stats

PAIRS = ["EURCHF", "EURNOK", "USDCAD", "USDJPY"]
BREAKOUTS = [f"breakout_{n}" for n in (10, 20, 40, 80, 160, 320)]
EWMACS = [f"ewmac_{f}" for f in (8, 16, 32, 64)]
STRATS = {
    "S21 Breakout": {r: 1 / len(BREAKOUTS) for r in BREAKOUTS},
    "S9 Tendencia EWMAC": {r: 1 / len(EWMACS) for r in EWMACS},
    "Breakout + EWMAC (50/50)": {**{r: 0.5 / len(BREAKOUTS) for r in BREAKOUTS},
                                 **{r: 0.5 / len(EWMACS) for r in EWMACS}},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    a = ap.parse_args()
    out = ROOT / "results" / "breakout"
    out.mkdir(parents=True, exist_ok=True)

    base = DailyConfig(weights={p: 1 / len(PAIRS) for p in PAIRS})
    px = {p: daily_from_hourly(load_hourly(p), 21) for p in PAIRS + ["EURUSD"]}
    start = pd.Timestamp(a.start)
    fc_all = {p: rule_forecasts(px[p], BREAKOUTS + EWMACS) for p in PAIRS}
    qpu = {p: quote_per_usd(p, px, px[p].index) for p in PAIRS}

    def backtest(fc_by_pair, cost_mult):
        cfg = replace(base, cost_mult=cost_mult)
        res = {p: simulate(p, px[p], fc_by_pair[p], qpu[p], cfg) for p in PAIRS}
        daily = {p: r.loc[r.index >= start, "pnl_usd"] / cfg.capital for p, r in res.items()}
        port = pd.concat(daily, axis=1, sort=True).fillna(0).sum(axis=1)
        yrs = len(port) / 256
        cost = sum(r.loc[r.index >= start, "cost_usd"].sum() for r in res.values()) / cfg.capital / yrs * 100
        turnover = sum((r.loc[r.index >= start, "pos"].diff().abs().sum()
                        / r.loc[r.index >= start, "pos"].abs().mean()) for r in res.values()) / len(res) / yrs
        return port, daily, {"coste_anual_%": cost, "rotación_anual": turnover}

    rows, pair_rows, curves = [], [], {}
    for name, wts in STRATS.items():
        w = pd.Series(wts)
        fcs = {p: fc_all[p][list(wts)] for p in PAIRS}
        # FDM de las tablas del libro (6 breakout 1.33, 4 EWMAC 1.13); la mezcla se estima
        f_dm = {"S21 Breakout": 1.33, "S9 Tendencia EWMAC": 1.13}.get(name) or fdm(
            {p: fcs[p][fcs[p].index < start] if (fcs[p].index < start).sum() > 300 else fcs[p]
             for p in PAIRS}, w)
        comb = {p: ((fcs[p] * w).sum(axis=1, min_count=1) * f_dm).clip(-20, 20) for p in PAIRS}
        for cm, tag in ((0.0, "bruto"), (1.0, "neto")):
            port, daily, extra = backtest(comb, cm)
            rows.append({"estrategia": name, "costes": tag, "FDM": f_dm, **stats(port), **extra})
            curves[f"{name} | {tag}"] = port
            if tag == "neto":
                for p in PAIRS:
                    pair_rows.append({"estrategia": name, "par": p, **stats(daily[p])})

    # Variantes individuales de breakout (cartera de 4 pares, neto)
    var_rows = []
    for r in BREAKOUTS + EWMACS:
        port, _, extra = backtest({p: fc_all[p][r] for p in PAIRS}, 1.0)
        st = stats(port)
        var_rows.append({"regla": r, "sharpe_neto": st["sharpe"], "ret_anual_%": st["ret_anual_%"],
                         "vol_anual_%": st["vol_anual_%"], **extra})

    summary = pd.DataFrame(rows).round(3)
    pairs = pd.DataFrame(pair_rows).round(3)
    variants = pd.DataFrame(var_rows).round(3)
    summary.to_csv(out / "resumen_portfolio.csv", index=False)
    pairs.to_csv(out / "resumen_por_par.csv", index=False)
    variants.to_csv(out / "variantes.csv", index=False)
    pd.DataFrame(curves).to_csv(out / "retornos_diarios.csv")

    fig, ax = plt.subplots(figsize=(11, 6))
    for k, s in curves.items():
        if k.endswith("neto"):
            ax.plot(s.cumsum() * 100, label=k.replace(" | neto", ""))
    ax.set_title("EURCHF/EURNOK/USDCAD/USDJPY – retorno acumulado neto (%)")
    ax.set_ylabel("% del capital (suma, sin componer)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "equity.png", dpi=110)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for t in (summary, pairs, variants):
        print(t.to_string(index=False))
        print()


if __name__ == "__main__":
    main()
