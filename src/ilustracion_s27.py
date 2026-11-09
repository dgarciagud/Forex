"""Gráfico ilustrativo de la estrategia 27 con una cuenta de 2.000 EUR (micro-lotes de 0.01).

Uso: python src/ilustracion_s27.py [PAR]
Genera results/ilustracion/s27_<PAR>.png y s27_tamano_2000eur.png
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from carver_s27 import ROOT, Config, carver_vol, daily_from_hourly, daily_signals, load_hourly, trading_day

CAPITAL_EUR = 2000.0
IDM, W, TAU = 1.56, 0.25, 0.20
MICRO = 1000.0                     # 0.01 lotes = 1.000 unidades de divisa base
PAIRS = ["EURCHF", "EURNOK", "USDCAD", "USDJPY"]
# Paleta de referencia (skill dataviz)
BLUE, ORANGE, AQUA, GREEN, RED, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#008300", "#e34948", "#8a8984"
INK, INK2 = "#0b0b0b", "#52514e"


def quote_per_eur(pair, daily):
    if pair.startswith("EUR"):
        return daily[pair]
    return daily[pair] * daily["EURUSD"].reindex(daily[pair].index).ffill()


def hourly_path(pair, h, daily):
    cfg = Config(fc_scalar=20.0)
    sig = daily_signals(daily[pair], cfg)
    qpe = quote_per_eur(pair, daily).shift(1)
    days = trading_day(h.index, 21)
    s = sig.reindex(days)
    s.index = h.index
    q = qpe.reindex(days).to_numpy()
    c = h["close"].to_numpy()
    E, sp, tr, M = (s[k].to_numpy() for k in ("eq", "sigma_p", "trend", "att"))
    n10 = CAPITAL_EUR * q * IDM * W * TAU / (16 * sp)            # unidades con F=10
    f = np.clip(20.0 * M * (E - c) / sp, -20, 20)
    f = np.where(np.sign(f) == tr, f, 0.0)                      # filtro de tendencia
    opt = f / 10.0 * n10 / MICRO                                # en micro-lotes
    pos, trades, cur = np.zeros(len(c)), np.zeros(len(c)), 0
    for i in range(len(c)):
        if np.isnan(opt[i]):
            pos[i] = cur
            continue
        if opt[i] - cur >= 1:
            new = int(np.floor(opt[i]))
        elif cur - opt[i] >= 1:
            new = int(np.ceil(opt[i]))
        else:
            new = cur
        trades[i] = new - cur
        cur = new
        pos[i] = cur
    out = pd.DataFrame({"close": c, "equil": E, "sp": sp, "trend": tr, "att": M, "fc": f,
                        "opt_lots": opt / 100, "pos_lots": pos / 100, "trade": trades / 100},
                       index=h.index)
    # precio en el que el forecast llega a +-20 (posición máxima)
    out["full_long"] = out.equil - out.sp / out.att
    out["full_short"] = out.equil + out.sp / out.att
    return out


def pick_window(df, days=8):
    """Ventana reciente con giro de tendencia y operaciones en ambos regímenes."""
    d = df[df.index >= "2023-01-01"]
    best, score = None, -1
    for st in pd.date_range(d.index[0].normalize(), d.index[-1].normalize() - pd.Timedelta(days=days), freq="1D"):
        win = d[(d.index >= st) & (d.index < st + pd.Timedelta(days=days))]
        if len(win) < 100 or win.index[0].dayofweek != 0:
            continue
        up_tr = ((win.trade != 0) & (win.trend > 0)).sum()
        dn_tr = ((win.trade != 0) & (win.trend < 0)).sum()
        sc = min(up_tr, dn_tr)
        if sc > score:
            best, score = win, sc
    return best


def plot_window(pair, win, out):
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1.3, 1.6]})
    ax = axes[0]
    up, dn = win.trend > 0, win.trend < 0
    for mask, col in ((up, GREEN), (dn, RED)):
        ax.fill_between(win.index, win.equil, np.where(mask, win.full_long if col == GREEN else win.full_short, np.nan),
                        color=col, alpha=0.10, step="post", linewidth=0)
    ax.plot(win.index, win.close, color=INK, lw=1.2, label="Precio (cierre horario)")
    ax.plot(win.index, win.equil, color=BLUE, lw=2, drawstyle="steps-post", label="Equilibrio (EWMA 5 días)")
    ax.plot(win.index, win.full_long.where(up), color=GREEN, lw=1, ls="--", drawstyle="steps-post",
            label="Compra máxima (forecast +20)")
    ax.plot(win.index, win.full_short.where(dn), color=RED, lw=1, ls="--", drawstyle="steps-post",
            label="Venta máxima (forecast −20)")
    b, s = win[win.trade > 0], win[win.trade < 0]
    ax.scatter(b.index, b.close, marker="^", s=70, color=GREEN, edgecolor="white", linewidth=1.5, zorder=5,
               label="Compra (≥ 0,01 lotes)")
    ax.scatter(s.index, s.close, marker="v", s=70, color=RED, edgecolor="white", linewidth=1.5, zorder=5,
               label="Venta (≥ 0,01 lotes)")
    ax.set_title(f"Estrategia 27 en {pair} con 2.000 € — cómo decide", loc="left", fontsize=14, color=INK, pad=22)
    ax.text(0, 1.015, "Verde: tendencia alcista → solo compra bajo el equilibrio · Rojo: tendencia bajista → solo vende sobre él",
            transform=ax.transAxes, fontsize=9.5, color=INK2, va="bottom")
    ax.legend(loc="lower center", fontsize=8.5, ncol=3, frameon=True, facecolor="white", edgecolor="none",
              framealpha=0.9)
    ax.grid(alpha=0.25)
    ax.set_ylabel("Precio")
    # Anotaciones: giro de tendencia y mayor posición de cada signo
    box = dict(boxstyle="round,pad=0.35", fc="white", ec="#d6d5d0", lw=0.8)
    flips = win.index[(win.trend.diff().fillna(0) != 0)]
    for t in flips[:1]:
        tr = win.loc[t, "trade"]
        ax.annotate(f"La tendencia gira → cierra la posición\n({tr:+.2f} lotes de golpe)", xy=(t, win.loc[t, "close"]),
                    xytext=(25, 45), textcoords="offset points", fontsize=8.5, bbox=box,
                    arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))
    for sign, txt in ((-1, "Tendencia bajista y precio sobre el equilibrio\n→ vende; tope {:.2f} lotes"),
                      (1, "Tendencia alcista y precio bajo el equilibrio\n→ compra la caída; hasta {:.2f} lotes")):
        sub = win[np.sign(win.pos_lots) == sign]
        if len(sub):
            t = sub.pos_lots.abs().idxmax()
            ax.annotate(txt.format(abs(sub.pos_lots).max()), xy=(t, win.loc[t, "close"]),
                        xytext=(-200 if sign > 0 else 30, 30 if sign < 0 else -55), textcoords="offset points",
                        fontsize=8.5, bbox=box, arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8))

    ax = axes[1]
    ax.fill_between(win.index, 0, win.fc, step="post", color=ORANGE, alpha=0.35, linewidth=0)
    ax.plot(win.index, win.fc, color=ORANGE, lw=1.2, drawstyle="steps-post")
    ax.axhline(0, color=GREY, lw=0.8)
    ax.set_ylim(-22, 22)
    ax.set_yticks([-20, -10, 0, 10, 20])
    ax.set_ylabel("Forecast")
    ax.grid(alpha=0.25)
    ax.text(0.005, 0.92, "Forecast = 20 × M × (equilibrio − precio) / vol diaria, tope ±20; 0 si va contra la tendencia",
            transform=ax.transAxes, fontsize=8.5, color=INK2, va="top")

    ax = axes[2]
    ax.plot(win.index, win.opt_lots, color=GREY, lw=1, label="Posición óptima (sin redondear)")
    ax.plot(win.index, win.pos_lots, color=AQUA, lw=2.2, drawstyle="steps-post", label="Posición real (micro-lotes)")
    ax.axhline(0, color=GREY, lw=0.8)
    lim = max(0.02, float(np.nanmax(np.abs(win[["opt_lots", "pos_lots"]].to_numpy())))) + 0.01
    ax.set_ylim(-lim, lim)
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(0.02))
    ax.set_ylabel("Lotes (+ largo / − corto)")
    ax.legend(loc="upper left", fontsize=8.5, frameon=False, ncol=2)
    ax.grid(alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    for a in axes:
        for sp_ in ("top", "right"):
            a.spines[sp_].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=130)


def plot_sizes(daily, out):
    rows = []
    for p in PAIRS:
        c = daily[p]
        vol = carver_vol(c.pct_change())
        sp = (vol * c).iloc[-1]
        n10 = CAPITAL_EUR * quote_per_eur(p, daily).iloc[-1] * IDM * W * TAU / (16 * sp)
        rows.append((p, n10 / 1e5, 2 * n10 / 1e5, vol.iloc[-1] * 16 * 100))
    df = pd.DataFrame(rows, columns=["par", "f10", "f20", "vol"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    y = np.arange(len(df))
    ax.barh(y + 0.18, df.f20, height=0.34, color=BLUE, label="Forecast ±20 (posición máxima)")
    ax.barh(y - 0.18, df.f10, height=0.34, color="#9ec5f0", label="Forecast ±10 (posición media)")
    for i, r in df.iterrows():
        ax.text(r.f20 + 0.002, i + 0.18, f"{r.f20:.2f} lotes", va="center", fontsize=9, color=INK)
        ax.text(r.f10 + 0.002, i - 0.18, f"{r.f10:.2f}", va="center", fontsize=9, color=INK2)
    ax.set_yticks(y, [f"{r.par}\nvol {r.vol:.1f} %" for r in df.itertuples()])
    ax.axvline(0.01, color=RED, ls=":", lw=1.2)
    ax.text(0.0105, -0.62, "lote mínimo 0,01", color=RED, fontsize=8.5)
    ax.set_xlabel("Lotes (1 lote = 100.000 unidades de la divisa base)")
    ax.set_title("Tamaño de posición con 2.000 € (riesgo 20 %, 25 % del capital por par, IDM 1.56)",
                 loc="left", fontsize=12, color=INK)
    ax.legend(loc="upper right", fontsize=9, frameon=False)
    ax.set_xlim(0, df.f20.max() * 1.25); ax.set_ylim(-0.75, len(df) - 0.4)
    for sp_ in ("top", "right"):
        ax.spines[sp_].set_visible(False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    return df


def main():
    pair = sys.argv[1] if len(sys.argv) > 1 else "EURCHF"
    out = ROOT / "results" / "ilustracion"
    out.mkdir(parents=True, exist_ok=True)
    hourly = {p: load_hourly(p) for p in PAIRS + ["EURUSD"]}
    daily = {p: daily_from_hourly(h, 21) for p, h in hourly.items()}
    path = hourly_path(pair, hourly[pair], daily)
    win = pick_window(path)
    plot_window(pair, win, out / f"s27_{pair}.png")
    sizes = plot_sizes(daily, out / "s27_tamano_2000eur.png")
    print(win.index[0], win.index[-1], "operaciones:", int((win.trade != 0).sum()),
          "max lotes:", win.pos_lots.abs().max())
    print(sizes.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
