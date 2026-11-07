"""Descarga datos de 1 minuto de HistData.com (paquete `histdata`) y los agrega a
velas horarias en data/<PAR>_H1.csv (índice UTC, columnas open/high/low/close).

HistData da las horas en EST fijo (UTC-5, sin horario de verano).
Uso: python src/download_histdata.py EURCHF EURNOK USDCAD USDJPY EURUSD --start 2008 --end 2025
"""
import argparse, io, time, zipfile
from pathlib import Path
import pandas as pd
from histdata import download_hist_data
from histdata.api import Platform, TimeFrame

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = DATA / "raw_histdata"


def get_year(pair, year, pause):
    RAW.mkdir(parents=True, exist_ok=True)
    f = RAW / f"DAT_ASCII_{pair}_M1_{year}.zip"
    if not f.exists():
        for attempt in range(5):
            try:
                out = download_hist_data(year=str(year), pair=pair.lower(), output_directory=str(RAW),
                                         platform=Platform.GENERIC_ASCII, time_frame=TimeFrame.ONE_MINUTE,
                                         verbose=False)
                Path(out).rename(f) if Path(out) != f else None
                break
            except Exception as e:  # noqa: BLE001
                print("reintento", pair, year, repr(e)[:120], flush=True)
                time.sleep(pause * 4 ** attempt)
        time.sleep(pause)
    if not f.exists():
        return None
    with zipfile.ZipFile(f) as z:
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        df = pd.read_csv(io.BytesIO(z.read(name)), sep=";", header=None,
                         names=["t", "open", "high", "low", "close", "v"])
    idx = pd.to_datetime(df.t, format="%Y%m%d %H%M%S") + pd.Timedelta(hours=5)
    df.index = idx.dt.tz_localize("UTC")
    return df[["open", "high", "low", "close"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+")
    ap.add_argument("--start", type=int, default=2008)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--pause", type=float, default=2.0)
    a = ap.parse_args()
    for pair in a.pairs:
        parts = [m for y in range(a.start, a.end + 1) if (m := get_year(pair, y, a.pause)) is not None]
        m1 = pd.concat(parts).sort_index()
        m1 = m1[~m1.index.duplicated()]
        h1 = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        h1.index.name = "time"
        h1.to_csv(DATA / f"{pair}_H1.csv")
        print("guardado", pair, len(h1), h1.index[0], h1.index[-1], flush=True)


if __name__ == "__main__":
    main()
