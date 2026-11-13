"""Construye data/raw/{SYMBOL}_D1.csv (time, open, high, low, close) desde los minutos de
HistData.com: años completos 2008–(año anterior) y meses del año en curso hasta hoy.

El día FX cierra a las 21:00 UTC (≈ 17:00 Nueva York, como las velas D1 de Darwinex);
las velas del viernes noche y del domingo se asignan al viernes/lunes.
Uso: python src/build_d1_histdata.py EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD NZDUSD
"""
import argparse
import io
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
from histdata import download_hist_data
from histdata.api import Platform, TimeFrame

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw_histdata"
OUT = ROOT / "data" / "raw"
DAY_END_UTC = 21


def fetch(pair, year, month=None, pause=2.0):
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = f"{year}{month:02d}" if month else f"{year}"
    f = CACHE / f"DAT_ASCII_{pair}_M1_{tag}.zip"
    if f.exists():
        return f
    for attempt in range(5):
        try:
            out = download_hist_data(year=str(year), month=str(month) if month else None, pair=pair.lower(),
                                     output_directory=str(CACHE), platform=Platform.GENERIC_ASCII,
                                     time_frame=TimeFrame.ONE_MINUTE, verbose=False)
            if Path(out) != f:
                Path(out).rename(f)
            time.sleep(pause)
            return f
        except Exception as e:  # noqa: BLE001
            print("reintento", pair, tag, repr(e)[:100], flush=True)
            time.sleep(pause * 4 ** attempt)
    return None


def read_zip(f):
    with zipfile.ZipFile(f) as z:
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None,
                         names=["t", "open", "high", "low", "close", "v"])
    idx = pd.to_datetime(df.t, format="%Y%m%d %H%M%S") + pd.Timedelta(hours=5)   # EST fijo -> UTC
    df.index = pd.DatetimeIndex(idx).tz_localize("UTC")
    return df[["open", "high", "low", "close"]]


def to_daily(m1):
    d = (m1.index + pd.Timedelta(hours=24 - DAY_END_UTC)).floor("D").tz_localize(None)
    dow = d.dayofweek
    d = d - pd.to_timedelta((dow == 5).astype(int), unit="D") + pd.to_timedelta((dow == 6).astype(int), unit="D")
    g = m1.groupby(pd.DatetimeIndex(d))
    out = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(), "close": g.close.last()})
    out.index.name = "time"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+")
    ap.add_argument("--start", type=int, default=2008)
    a = ap.parse_args()
    today = date.today()
    OUT.mkdir(parents=True, exist_ok=True)
    for pair in a.pairs:
        files = [fetch(pair, y) for y in range(a.start, today.year)]
        files += [fetch(pair, today.year, m) for m in range(1, today.month + 1)]
        parts = [read_zip(f) for f in files if f is not None]
        m1 = pd.concat(parts).sort_index()
        m1 = m1[~m1.index.duplicated()]
        d1 = to_daily(m1)
        d1.to_csv(OUT / f"{pair}_D1.csv")
        print("guardado", pair, len(d1), d1.index[0].date(), d1.index[-1].date(), flush=True)


if __name__ == "__main__":
    main()
