"""Pruebas sin MT5:  python -m pytest live/tests -q   (desde la raíz del repo)."""
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from live import config as cfgmod
from live.strategies import s27

PARAMS = dict(s27.DEFAULTS)


def state(trend=1, eq=1.0, sigma_p=0.005, att=1.0):
    return s27.DailyState(day=pd.Timestamp("2025-01-02"), close=eq, eq=eq, sigma_p=sigma_p,
                          vol_pct=sigma_p / eq, trend=trend, att=att, last_ret=0.0,
                          prev_vol_pct=sigma_p / eq)


# ------------------------------------------------------------------ bounds
def test_bounds_trend_and_sides():
    assert s27.bounds(1, "both", "normal", 0, 4) == (0, 4)
    assert s27.bounds(-1, "both", "normal", 0, 4) == (-4, 0)
    assert s27.bounds(1, "short", "normal", 0, 4) == (0, 0)     # tendencia alcista, solo cortos
    assert s27.bounds(-1, "short", "normal", 0, 4) == (-4, 0)
    assert s27.bounds(0, "both", "normal", 0, 4) == (0, 0)
    assert s27.bounds(1, "none", "normal", 0, 4) == (0, 0)


def test_bounds_modes():
    assert s27.bounds(1, "both", "close", 3, 4) == (0, 0)
    assert s27.bounds(1, "both", "reduce_only", 2, 4) == (0, 2)
    assert s27.bounds(-1, "both", "reduce_only", -3, 4) == (-3, 0)
    assert s27.bounds(-1, "both", "reduce_only", 2, 4) == (0, 0)  # largo con tendencia bajista: cerrar


# ------------------------------------------------------------------ escalera límite
def test_limit_ladder_levels_invert_position_formula():
    st = state(trend=1)
    n_avg = 2.0
    k = 20.0 * n_avg / (10 * st.sigma_p)                 # pasos por unidad de precio
    p = s27.plan_limit(st, n_avg, 10, pos=1, bid=0.9995, ask=0.9996, tick=0.00001,
                       sides="both", mode="normal", params=PARAMS)
    assert p.market_steps == 0
    assert p.buy_limit == pytest.approx(math.floor((1.0 - 2 / k) / 1e-5 + 1e-9) * 1e-5)
    assert p.sell_limit == pytest.approx(math.ceil((1.0 - 0 / k) / 1e-5 - 1e-9) * 1e-5)
    assert p.buy_limit < 0.9996 and p.sell_limit > 0.9995


def test_no_sell_limit_below_zero_in_uptrend():
    p = s27.plan_limit(state(trend=1), 2.0, 10, pos=0, bid=0.9999, ask=1.0, tick=0.00001,
                       sides="both", mode="normal", params=PARAMS)
    assert p.sell_limit is None and p.buy_limit is not None


def test_gap_goes_to_market_toward_optimal():
    st = state(trend=1)
    n_avg = 2.0
    k = 20.0 * n_avg / (10 * st.sigma_p)
    ask = 1.0 - 3.5 / k                                   # óptima ~3.5 pasos
    p = s27.plan_limit(st, n_avg, 10, pos=0, bid=ask - 1e-5, ask=ask, tick=0.00001,
                       sides="both", mode="normal", params=PARAMS)
    assert p.market_steps == 3


def test_cap_and_max_lots():
    st = state(trend=1)
    p = s27.plan_limit(st, 2.0, 10, pos=4, bid=0.90, ask=0.9001, tick=0.00001,
                       sides="both", mode="normal", params=PARAMS)
    assert p.hi == 4 and p.buy_limit is None             # forecast topado en 20 -> 2 x n_avg
    p = s27.plan_limit(st, 2.0, 3, pos=4, bid=0.90, ask=0.9001, tick=0.00001,
                       sides="both", mode="normal", params=PARAMS)
    assert p.market_steps == -1                           # max_lots = 3 pasos


def test_trend_flip_forces_close():
    p = s27.plan_limit(state(trend=-1), 2.0, 10, pos=3, bid=0.99, ask=0.9901, tick=0.00001,
                       sides="both", mode="normal", params=PARAMS)
    assert p.market_steps == -3


def test_long_only_side_blocks_shorts():
    p = s27.plan_limit(state(trend=-1), 2.0, 10, pos=0, bid=1.01, ask=1.0101, tick=0.00001,
                       sides="long", mode="normal", params=PARAMS)
    assert (p.lo, p.hi, p.market_steps, p.buy_limit, p.sell_limit) == (0, 0, 0, None, None)


# ------------------------------------------------------------------ mercado con buffer
def test_market_buffer_trades_to_edge():
    st = state(trend=1)
    n_avg = 20.0                                          # buffer 10 % = 2 pasos
    k = 20.0 * n_avg / (10 * st.sigma_p)
    mid = 1.0 - 7.3 / k
    p = s27.plan_market(st, n_avg, 100, pos=0, bid=mid, ask=mid, sides="both", mode="normal",
                        params=PARAMS, new_bar=True)
    assert p.market_steps == math.floor(7.3 - 2 + 1)
    p = s27.plan_market(st, n_avg, 100, pos=0, bid=mid, ask=mid, sides="both", mode="normal",
                        params=PARAMS, new_bar=False)
    assert p.market_steps == 0


# ------------------------------------------------------------------ estado diario y tamaño
def test_daily_state_matches_backtest_signals():
    from carver_s27 import Config, daily_signals
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=1500)
    closes = pd.Series(1.1 * np.exp(np.cumsum(rng.normal(0, 0.005, len(idx)))), index=idx)
    st = s27.daily_state(closes, PARAMS)
    ref = daily_signals(closes, Config()).iloc[-1]          # el backtest desplaza 1 día
    ref_next = daily_signals(pd.concat([closes, closes.iloc[-1:].rename(lambda _: idx[-1] + pd.offsets.BDay())]),
                             Config()).iloc[-1]
    assert st.eq == pytest.approx(ref_next["eq"])
    assert st.sigma_p == pytest.approx(ref_next["sigma_p"])
    assert st.trend == ref_next["trend"]
    assert st.att == pytest.approx(ref_next["att"])
    assert not math.isnan(ref["eq"])


def test_n_avg_steps_eurchf_1900():
    # 1.900 EUR, IDM 1.70, peso 1/5, tau 20 %, sigma_p 0.0038, 1 lote = ~106.000 EUR por unidad
    n = s27.n_avg_steps(1900, 1.70, 0.2, 1.0, 0.20, 0.0038, 106_000, 0.01)
    assert 1.5 < n < 2.5


# ------------------------------------------------------------------ configuración
def test_config_example_loads():
    s = cfgmod.load(Path(__file__).resolve().parents[1] / "config.toml")
    assert s.capital == 1900 and s.expect_server == "Darwinex-Demo" and s.idm == pytest.approx(1.70)
    assert {a.symbol for a in s.active()} == {"EURUSD", "USDJPY", "EURCHF", "USDCAD", "EURNOK"}
    assert sum(a.weight for a in s.active()) == pytest.approx(1.0)


def test_config_rejects_bad_side(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[strategies.s27]\nmagic = 1\n[[assignment]]\nstrategy = "s27"\n'
                 'symbol = "EURUSD"\nsides = "up"\n')
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(p)
