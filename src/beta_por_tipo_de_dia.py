"""Beta leave-one-out al factor dólar separada por tipo de día (2016-11 en adelante):
días de tipos (|Δ2 años EE. UU.| ≥ 8 pb con bolsa tranquila), días de miedo (S&P ≤ −1,5 %) y resto.
Datos: data/raw/*_D1.csv, DGS2_fred.csv, SP500_fred.csv. Uso: python src/beta_por_tipo_de_dia.py
"""
import contextlib
import io

import numpy as np
import pandas as pd

from fx_loader import ROOT, load_d1
from rolling_dollar_betas import SYMBOLS, common_closes, dollar_factors


def fred(name):
    s = pd.read_csv(ROOT / "data" / "raw" / name, index_col=0, parse_dates=True).iloc[:, 0]
    return pd.to_numeric(s, errors="coerce")


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        data, _ = load_d1(SYMBOLS)
        px = common_closes(data)
    r = np.log(px / px.shift(1)) * 100
    _, loo = dollar_factors(r)
    df = (r.join((fred("DGS2_fred.csv").diff() * 100).rename("dy"), how="inner")
           .join((np.log(fred("SP500_fred.csv")).diff() * 100).rename("spx"), how="inner").dropna())
    L = loo.reindex(df.index)
    groups = {"Días de tipos (|Δ2a| ≥ 8 pb, |S&P| < 1 %)": (df.dy.abs() >= 8) & (df.spx.abs() < 1),
              "Días de miedo (S&P ≤ −1,5 %)": df.spx <= -1.5,
              "Resto de días": (df.dy.abs() < 8) & (df.spx > -1.5),
              "Todos los días": pd.Series(True, index=df.index)}
    rows = {}
    for g, m in groups.items():
        d, l = df[m], L[m]
        rows[g] = {c: d[c].cov(l[c]) / l[c].var() for c in r.columns} | {"días": int(m.sum())}
    out = pd.DataFrame(rows).T.round(2)
    out.to_csv(ROOT / "output" / "beta_por_tipo_de_dia.csv")
    print(out.to_string())
    for name, m in (("subida de tipos ≥ 8 pb (bolsa tranquila)", (df.dy >= 8) & (df.spx.abs() < 1)),
                    ("miedo (S&P ≤ −1,5 %)", df.spx <= -1.5)):
        d = df[m]
        print(f"Media en días de {name}: factor dólar {L.loc[d.index, 'CHF'].mean():+.2f} %, "
              + ", ".join(f"{c} {d[c].mean():+.2f} %" for c in ["CHF", "JPY", "EUR", "AUD"]))


if __name__ == "__main__":
    main()
