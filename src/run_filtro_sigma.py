"""Filtro: no ampliar posición si el precio se ha movido en contra más de k·σ diaria
desde la apertura del día FX (21:00 UTC). Solo se permite reducir o cerrar.

Uso: python src/run_filtro_sigma.py  → results/filtro_sigma/
"""
from dataclasses import replace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from carver_s27 import ROOT, Config, daily_from_hourly, load_hourly, stats
from run_backtest import PAIRS, VARIANTS, run, summarise
from run_limit import EXEC

KS = {"sin filtro": None, "0,5 σ": 0.5, "1 σ": 1.0, "1,5 σ": 1.5, "2 σ": 2.0}
EXECS = ["mercado, medio spread", "mercado, sin costes", "límite, al tocar", "límite, atravesar ½ spread"]


def main():
    out = ROOT / "results" / "filtro_sigma"
    out.mkdir(parents=True, exist_ok=True)
    hourly = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    base = Config(weights={p: 1 / len(PAIRS) for p in PAIRS})
    daily_px = {p: daily_from_hourly(h, base.day_end_hour_utc) for p, h in hourly.items()}
    rows, curves = [], {}
    for vname in ("S27 solo filtro tendencia", "S27 completa"):
        for buf in (0.0, 0.25):
            for ename in EXECS:
                for kname, k in KS.items():
                    cfg = replace(base, buffer_frac=buf, add_stop_sigma=k, **VARIANTS[vname], **EXEC[ename])
                    pp = run(cfg, hourly, daily_px, "2010-01-01")
                    port, daily, extra = summarise(pp, cfg)
                    st = stats(port)
                    rows.append({"variante": vname, "buffer": "libro" if buf == 0 else "25%",
                                 "ejecución": ename, "filtro": kname, "sharpe": st["sharpe"],
                                 "ret_anual_%": st["ret_anual_%"], "vol_anual_%": st["vol_anual_%"],
                                 "max_dd_%": st["max_dd_%"], "skew_mensual": st["skew_mensual"],
                                 "peor_dia_%": st["peor_dia_%"], **extra,
                                 **{f"SR {p}": stats(daily[p])["sharpe"] for p in PAIRS}})
                    if vname == "S27 completa" and buf == 0.25 and ename == "límite, atravesar ½ spread":
                        curves[kname] = port
                    print(vname, buf, ename, kname, round(st["sharpe"], 2), flush=True)
    df = pd.DataFrame(rows).round(3)
    df.to_csv(out / "filtro_sigma.csv", index=False)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    colors = ["#8a8984", "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"]
    for (k, s), col in zip(curves.items(), colors):
        ax.plot(s.cumsum() * 100, label=k, color=col, lw=2 if k == "1 σ" else 1.3)
    ax.set_title("S27 completa, 1h, buffer 25 %, límite atravesando ½ spread – efecto del filtro k·σ",
                 loc="left", fontsize=11.5)
    ax.set_ylabel("% del capital (suma, sin componer)")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "equity_filtro_sigma.png", dpi=120)


if __name__ == "__main__":
    main()
