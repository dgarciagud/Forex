"""Descarga velas horarias (BID) de Dukascopy y las guarda en data/<PAR>_H1.csv.

Uso: python src/download_dukascopy.py EURCHF EURNOK USDCAD USDJPY --start 2008 --end 2025
Las peticiones se hacen de forma secuencial y con pausas para respetar los
límites del servidor (si responde 429 se espera y se reintenta).
"""
import argparse, lzma, struct, time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

URL = "https://datafeed.dukascopy.com/datafeed/{pair}/{year}/{month:02d}/BID_candles_hour_1.bi5"
DATA = Path(__file__).resolve().parent.parent / "data"


def fetch_month(sess, pair, year, month0, pause):
    cache = DATA / "raw" / pair / f"{year}_{month0:02d}.bi5"
    if cache.exists():
        return cache.read_bytes()
    url = URL.format(pair=pair, year=year, month=month0)
    status = None
    for attempt in range(14):
        try:
            r = sess.get(url, timeout=60)
            status = r.status_code
        except requests.RequestException as e:
            status = repr(e)
            r = None
        if r is not None and r.status_code == 200:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(r.content)
            time.sleep(pause)
            return r.content
        if r is not None and r.status_code == 404:
            return b""
        time.sleep(min(pause * 2 ** (attempt + 2), 300))  # back-off ante 429 / errores
    raise RuntimeError(f"No se pudo descargar {url} ({status})")


def parse(raw, year, month0, scale):
    if not raw:
        return []
    d = lzma.decompress(raw)
    base = datetime(year, month0 + 1, 1, tzinfo=timezone.utc).timestamp()
    rows = []
    for i in range(len(d) // 24):
        t, o, c, lo, hi, v = struct.unpack(">5if", d[i * 24:(i + 1) * 24])
        if v <= 0:  # horas sin cotización (fin de semana)
            continue
        rows.append((base + t, o / scale, hi / scale, lo / scale, c / scale, v))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+")
    ap.add_argument("--start", type=int, default=2008)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--pause", type=float, default=1.0)
    a = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    sess = requests.Session()
    now = datetime.now(timezone.utc)
    for pair in a.pairs:
        scale = 1e3 if pair.endswith("JPY") else 1e5
        rows = []
        for y in range(a.start, a.end + 1):
            for m in range(12):
                if (y, m + 1) >= (now.year, now.month):
                    break
                rows += parse(fetch_month(sess, pair, y, m, a.pause), y, m, scale)
            print(pair, y, len(rows), flush=True)
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df.pop("ts"), unit="s", utc=True)
        df.set_index("time").to_csv(DATA / f"{pair}_H1.csv")
        print("guardado", pair, len(df), flush=True)


if __name__ == "__main__":
    main()
