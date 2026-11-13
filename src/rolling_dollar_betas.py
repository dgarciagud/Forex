"""Betas rolling de cada divisa del G8 frente al factor dólar (DOL).

Spec: SPEC_dollar_betas_rolling.md. Uso: python src/rolling_dollar_betas.py
Salidas en output/ (CSV de betas y R², gráficos y summary.csv).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from fx_loader import ROOT, load_d1

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]
INVERT = {"USDJPY", "USDCHF", "USDCAD"}                  # precio -> 1/precio (USD por divisa)
CCY = {"EURUSD": "EUR", "GBPUSD": "GBP", "USDJPY": "JPY", "USDCHF": "CHF",
       "AUDUSD": "AUD", "USDCAD": "CAD", "NZDUSD": "NZD"}
WINDOWS = [60, 120, 250]
MAIN_W = 120
MARK_DATES = {"2011-09-06": "Suelo SNB (06-09-2011)", "2015-01-15": "Fin del suelo SNB (15-01-2015)"}
OUT_DIR = ROOT / "output"
TOL = 1e-10
# Paleta categórica de referencia (orden fijo, skill dataviz)
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
W_COLORS = {60: "#9ec5f0", 120: "#2a78d6", 250: "#0b0b0b"}
INK2 = "#52514e"


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------
def orient(close: pd.Series, symbol: str) -> pd.Series:
    """USD por unidad de divisa extranjera: retorno > 0 = la divisa se aprecia frente al USD."""
    return 1.0 / close if symbol in INVERT else close


def common_closes(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    closes = {s: df["close"] for s, df in data.items()}
    union = pd.Index(sorted(set().union(*[c.index for c in closes.values()])))
    common = union
    for c in closes.values():
        common = common.intersection(c.index)
    start = max(c.index.min() for c in closes.values())       # fecha más antigua común
    common = common[common >= start]
    union_from_start = union[union >= start]
    print(f"Inicio: {common[0].date()}  Fin: {common[-1].date()}  Días comunes: {len(common)}  "
          f"Días descartados (presentes en algún símbolo pero no en los 7): {len(union_from_start) - len(common)}")
    for s, c in closes.items():
        c = c[c.index >= start]
        print(f"  {s}: {len(c)} días, {len(c.index.difference(common))} descartados")
    return pd.DataFrame({CCY[s]: orient(closes[s].reindex(common), s) for s in closes})


def dollar_factors(r: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    dol = r.mean(axis=1)
    n = r.shape[1]
    loo = pd.DataFrame({c: (r.sum(axis=1) - r[c]) / (n - 1) for c in r.columns})
    return dol, loo


def rolling_beta_r2(r: pd.DataFrame, factor: pd.DataFrame, w: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    betas, r2 = {}, {}
    for c in r.columns:
        f = factor[c]
        cov = r[c].rolling(w, min_periods=w).cov(f)
        var = f.rolling(w, min_periods=w).var()
        betas[c] = cov / var
        r2[c] = r[c].rolling(w, min_periods=w).corr(f) ** 2
    return pd.DataFrame(betas), pd.DataFrame(r2)


# ---------------------------------------------------------------------------
# Comprobaciones
# ---------------------------------------------------------------------------
def check_orientation() -> None:
    usdjpy = pd.Series([100.0, 101.0])                 # USDJPY sube un 1 %
    r = np.log(orient(usdjpy, "USDJPY")).diff().iloc[-1]
    assert abs(r - np.log(1 / 1.01)) < 1e-12 and abs(r + 0.01) < 5e-4, r
    print(f"Comprobación de orientación OK: USDJPY +1 % -> r_JPY = {r:.4%}")


def check_mean_beta(betas_full: pd.DataFrame, w: int) -> None:
    dev = (betas_full.mean(axis=1) - 1.0).abs().dropna()
    assert (dev < TOL).all(), f"W={w}: media de betas ≠ 1 (máx. desviación {dev.max():.2e})"
    print(f"Comprobación media de betas = 1 (DOL completo, W={w}) OK: máx. desviación {dev.max():.1e}")


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def _decorate(ax, label_marks=False):
    for d, txt in MARK_DATES.items():
        ax.axvline(pd.Timestamp(d), color=INK2, lw=0.9, ls="--")
        if label_marks:
            ax.text(pd.Timestamp(d), 1.0, f" {txt}", transform=ax.get_xaxis_transform(),
                    fontsize=8, color=INK2, va="top", rotation=90)
    ax.axhline(1.0, color=INK2, lw=0.8)
    ax.grid(alpha=0.2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def plot_all_in_one(b: pd.DataFrame, path):
    fig, ax = plt.subplots(figsize=(13, 6))
    for c, col in zip(b.columns, COLORS):
        ax.plot(b.index, b[c], color=col, lw=1.4, label=c)
    # etiquetas directas al final, separadas verticalmente para que no se pisen
    last = b.ffill().iloc[-1].sort_values()
    ys, gap = [], 0.07
    for v in last.values:
        ys.append(max(v, ys[-1] + gap) if ys else v)
    for (c, v), y in zip(last.items(), ys):
        ax.text(b.index[-1], y, f"  {c} {v:.2f}", color=INK2, fontsize=8.5, va="center")
    _decorate(ax, label_marks=True)
    ax.set_title(f"Beta rolling ({MAIN_W} días) de cada divisa frente al factor dólar (leave-one-out)",
                 loc="left", fontsize=12.5)
    ax.set_ylabel("β frente a DOL (sin la propia divisa)")
    ax.legend(ncol=7, fontsize=9, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_grid(series: dict[str, pd.DataFrame], colors: dict, title: str, path):
    ccys = next(iter(series.values())).columns
    fig, axes = plt.subplots(4, 2, figsize=(14, 13), sharex=True, sharey=True)
    for ax, c in zip(axes.flat, ccys):
        for name, df in series.items():
            ax.plot(df.index, df[c], color=colors[name], lw=1.0 if name != str(MAIN_W) else 1.4, label=name)
        _decorate(ax)
        ax.set_title(c, loc="left", fontsize=11)
    axes.flat[-1].axis("off")
    axes.flat[-2].tick_params(labelbottom=True)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    axes.flat[-1].legend(handles, labels, loc="center", fontsize=11, frameon=False,
                         title="Líneas discontinuas: 06-09-2011 y 15-01-2015 (SNB)")
    fig.suptitle(title, x=0.01, ha="left", fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------------------
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    check_orientation()
    data, source = load_d1(SYMBOLS)
    print(f"Fuente de datos: {source}")
    px = common_closes(data)
    r = np.log(px / px.shift(1)).dropna()
    dol, loo = dollar_factors(r)
    full = pd.DataFrame({c: dol for c in r.columns})

    betas, r2s, rows = {}, {}, []
    for w in WINDOWS:
        for kind, fac in (("full", full), ("loo", loo)):
            b, rr = rolling_beta_r2(r, fac, w)
            if kind == "full":
                check_mean_beta(b, w)
            b.to_csv(OUT_DIR / f"betas_rolling_W{w}_{kind}.csv", index_label="date")
            rr.to_csv(OUT_DIR / f"r2_rolling_W{w}_{kind}.csv", index_label="date")
            betas[(w, kind)], r2s[(w, kind)] = b, rr
            for c in b.columns:
                s = b[c].dropna()
                rows.append({"divisa": c, "ventana": w, "factor": kind, "media": s.mean(), "desv": s.std(),
                             "min": s.min(), "max": s.max(), "ultimo": s.iloc[-1],
                             "fecha_ultimo": s.index[-1].date()})
    summary = pd.DataFrame(rows)
    summary.round(4).to_csv(OUT_DIR / "summary.csv", index=False)
    pd.set_option("display.width", 200)
    print(summary.round(3).to_string(index=False))

    plot_all_in_one(betas[(MAIN_W, "loo")], OUT_DIR / f"betas_W{MAIN_W}_loo.png")
    plot_grid({str(w): betas[(w, "loo")] for w in WINDOWS}, {str(w): W_COLORS[w] for w in WINDOWS},
              "Beta rolling frente al factor dólar (leave-one-out): ventanas de 60, 120 y 250 días",
              OUT_DIR / f"betas_W{MAIN_W}_loo_grid.png")
    plot_grid({"DOL completo": betas[(MAIN_W, "full")], "Leave-one-out": betas[(MAIN_W, "loo")]},
              {"DOL completo": "#eb6834", "Leave-one-out": "#2a78d6"},
              f"Beta rolling ({MAIN_W} días): factor dólar completo frente a leave-one-out",
              OUT_DIR / f"betas_W{MAIN_W}_full_vs_loo.png")
    print(f"Salidas en {OUT_DIR}")


if __name__ == "__main__":
    main()
