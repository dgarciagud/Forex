"""Loader de velas D1 para los símbolos del G8 (Darwinex).

1. Si el paquete `MetaTrader5` está instalado y el terminal se inicializa, usa `copy_rates_range`.
2. Si no, lee `data/raw/{SYMBOL}_D1.csv` con columnas `time, open, high, low, close`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
MT5_START = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _load_mt5(symbols: list[str]) -> dict[str, pd.DataFrame] | None:
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    try:
        out = {}
        for s in symbols:
            rates = mt5.copy_rates_range(s, mt5.TIMEFRAME_D1, MT5_START, datetime.now(timezone.utc))
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"MT5 no devolvió datos para {s}: {mt5.last_error()}")
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s").dt.normalize()
            out[s] = df.set_index("time")[["open", "high", "low", "close"]]
        return out
    finally:
        mt5.shutdown()


def _load_csv(symbols: list[str], raw_dir: Path) -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        f = raw_dir / f"{s}_D1.csv"
        if not f.exists():
            raise FileNotFoundError(f"Falta {f} (y MetaTrader5 no está disponible)")
        df = pd.read_csv(f, parse_dates=["time"]).set_index("time").sort_index()
        df.index = pd.DatetimeIndex(df.index).normalize()
        out[s] = df[["open", "high", "low", "close"]]
    return out


def load_d1(symbols: list[str], raw_dir: Path = RAW_DIR) -> tuple[dict[str, pd.DataFrame], str]:
    """Devuelve ({símbolo: DataFrame OHLC diario}, fuente)."""
    data = _load_mt5(symbols)
    if data is not None:
        return data, "MetaTrader5"
    return _load_csv(symbols, raw_dir), f"CSV ({raw_dir})"
