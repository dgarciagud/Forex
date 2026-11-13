"""¿Cómo reaccionan EURUSD, USDCHF y EURCHF a los cambios del tipo a 2 años de EE. UU.?

Regresión rolling de los log-retornos diarios sobre la variación diaria del DGS2 (FRED,
data/raw/DGS2_fred.csv), expresada en % por cada +10 pb. Uso: python src/eurchf_tipos_usd.py
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from fx_loader import ROOT, load_d1

W = 120
OUT = ROOT / "output"


def main():
    data, _ = load_d1(["EURUSD", "USDCHF"])
    px = pd.DataFrame({k: v["close"] for k, v in data.items()}).dropna()
    px["EURCHF"] = px.EURUSD * px.USDCHF
    r = np.log(px / px.shift(1)) * 100                         # % diario
    y = pd.read_csv(ROOT / "data" / "raw" / "DGS2_fred.csv", parse_dates=["observation_date"],
                    index_col="observation_date")["DGS2"]
    y = pd.to_numeric(y, errors="coerce")
    dy = (y.diff() * 100 / 10).rename("dy10")                   # en unidades de 10 pb
    df = r.join(dy, how="inner").dropna()

    betas = pd.DataFrame({c: df[c].rolling(W).cov(df.dy10) / df.dy10.rolling(W).var()
                          for c in ["EURUSD", "USDCHF", "EURCHF"]})
    betas.to_csv(OUT / f"beta_tipos2a_W{W}.csv", index_label="date")

    def per(a, b):
        d = df.loc[a:b]
        return {c: d[c].cov(d.dy10) / d.dy10.var() for c in ["EURUSD", "USDCHF", "EURCHF"]} | {
            "corr EURCHF": d.EURCHF.corr(d.dy10), "días": len(d)}
    tab = pd.DataFrame({"2015-02 a 2021-12": per("2015-02", "2021-12"),
                        "2022-01 a 2024-12": per("2022-01", "2024-12"),
                        "últimos 12 meses": per(df.index[-1] - pd.Timedelta(days=365), df.index[-1])}).T
    print("Reacción media (% por cada +10 pb del 2 años EE. UU.):")
    print(tab.round(3).to_string())
    last = df.loc[df.index[-1] - pd.Timedelta(days=365):]
    big = last[last.dy10.abs() >= 0.8]                          # días con |Δ2a| ≥ 8 pb
    print(f"\nDías de los últimos 12 meses con |Δ2a| ≥ 8 pb: {len(big)}")
    print((big.assign(dy_pb=big.dy10 * 10)[["dy_pb", "EURUSD", "USDCHF", "EURCHF"]]).round(2).to_string())
    same = (np.sign(big.EURCHF) == np.sign(big.dy10)).mean() * 100
    print(f"EURCHF se mueve en el mismo sentido que el tipo (sube con subidas de tipos) en el {same:.0f} % de esos días")

    fig, ax = plt.subplots(figsize=(13, 5.8))
    cols = {"EURUSD": "#2a78d6", "USDCHF": "#eb6834", "EURCHF": "#0b0b0b"}
    b = betas.loc["2012":]
    for c, col in cols.items():
        ax.plot(b.index, b[c], color=col, lw=1.3 if c != "EURCHF" else 2.0, label=c)
        ax.text(b.index[-1], b[c].iloc[-1], f"  {c} {b[c].iloc[-1]:+.2f}", color="#52514e", fontsize=9, va="center")
    ax.axhline(0, color="#52514e", lw=0.8)
    ax.axvline(pd.Timestamp("2015-01-15"), color="#52514e", lw=0.9, ls="--")
    ax.set_title(f"Reacción a +10 pb en el tipo a 2 años de EE. UU. (beta rolling {W} días, % por +10 pb)",
                 loc="left", fontsize=12.5, pad=22)
    ax.text(0, 1.012, "EURUSD < 0: el USD se aprecia al subir los tipos · USDCHF > 0: el CHF se deprecia · "
            "EURCHF > 0: el EUR se aprecia frente al CHF", transform=ax.transAxes, fontsize=9, color="#52514e")
    ax.legend(frameon=False, ncol=3, loc="lower left")
    ax.grid(alpha=0.2)
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "beta_tipos2a_eurchf.png", dpi=120)


if __name__ == "__main__":
    main()
