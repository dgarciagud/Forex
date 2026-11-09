"""Carga y validación de live/config.toml (qué estrategia en qué cruce y con qué lados)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

SIDES = {"both", "long", "short", "none"}
MODES = {"normal", "reduce_only", "close"}
RUN_MODES = {"dry_run", "live"}
KNOWN_STRATEGIES = {"s27"}

# IDM aproximado según nº de instrumentos (AFTS, tabla 16)
_IDM_TABLE = [(1, 1.00), (2, 1.20), (3, 1.48), (4, 1.56), (5, 1.70), (6, 1.90),
              (7, 2.10), (8, 2.20), (15, 2.30), (25, 2.40), (30, 2.50)]


def idm_for(n_instruments: int) -> float:
    value = 1.0
    for n, v in _IDM_TABLE:
        if n_instruments >= n:
            value = v
    return value


class ConfigError(ValueError):
    pass


@dataclass
class Assignment:
    strategy: str
    symbol: str
    sides: str = "both"          # both | long | short | none
    mode: str = "normal"         # normal | reduce_only | close
    weight: float | None = None  # peso de instrumento; None = reparto igual
    size_mult: float = 1.0       # multiplicador manual de tamaño (0-1 para reducir)
    max_lots: float = 0.10       # tope duro de posición en lotes
    enabled: bool = True

    @property
    def key(self) -> str:
        return f"{self.strategy}:{self.symbol}"


@dataclass
class Settings:
    path: Path
    run_mode: str
    poll_seconds: float
    state_dir: Path
    log_dir: Path
    stop_file: Path
    capital: float | None          # None = usar todo el equity
    risk_target: float
    idm: float
    max_trades_per_day: int
    spike_sigma: float
    max_tick_age_seconds: float
    deviation_points: int
    min_history_days: int
    blackout_start: str
    blackout_end: str
    mt5_path: str | None
    strategies: dict[str, dict] = field(default_factory=dict)
    assignments: list[Assignment] = field(default_factory=list)

    @property
    def dry_run(self) -> bool:
        return self.run_mode == "dry_run"

    def active(self) -> list[Assignment]:
        return [a for a in self.assignments if a.enabled]


def _hhmm(value: str, name: str) -> str:
    try:
        h, m = value.split(":")
        assert 0 <= int(h) < 24 and 0 <= int(m) < 60
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"{name} debe ser 'HH:MM', no {value!r}") from exc
    return value


def load(path: str | Path) -> Settings:
    path = Path(path).resolve()
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)
    base = path.parent
    gen, acc, saf = raw.get("general", {}), raw.get("account", {}), raw.get("safety", {})

    run_mode = gen.get("mode", "dry_run")
    if run_mode not in RUN_MODES:
        raise ConfigError(f"general.mode debe ser uno de {sorted(RUN_MODES)}")

    strategies = raw.get("strategies", {})
    for name in strategies:
        if name not in KNOWN_STRATEGIES:
            raise ConfigError(f"estrategia desconocida en [strategies]: {name}")
    magics = [s.get("magic") for s in strategies.values()]
    if None in magics or len(set(magics)) != len(magics):
        raise ConfigError("cada estrategia necesita un 'magic' único")

    assignments: list[Assignment] = []
    seen = set()
    for i, item in enumerate(raw.get("assignment", [])):
        try:
            a = Assignment(**item)
        except TypeError as exc:
            raise ConfigError(f"assignment #{i + 1}: {exc}") from exc
        if a.strategy not in strategies:
            raise ConfigError(f"{a.key}: falta la sección [strategies.{a.strategy}]")
        if a.sides not in SIDES:
            raise ConfigError(f"{a.key}: sides debe ser uno de {sorted(SIDES)}")
        if a.mode not in MODES:
            raise ConfigError(f"{a.key}: mode debe ser uno de {sorted(MODES)}")
        if a.key in seen:
            raise ConfigError(f"{a.key} está repetido")
        if a.max_lots <= 0 or a.size_mult < 0:
            raise ConfigError(f"{a.key}: max_lots debe ser > 0 y size_mult >= 0")
        seen.add(a.key)
        assignments.append(a)

    active = [a for a in assignments if a.enabled]
    given = [a.weight for a in active if a.weight is not None]
    if given and len(given) != len(active):
        raise ConfigError("o se da 'weight' en todas las asignaciones activas o en ninguna")
    if not given and active:
        for a in active:
            a.weight = 1.0 / len(active)
    total = sum(a.weight for a in active)
    if active and total > 1.0 + 1e-6:
        raise ConfigError(f"la suma de pesos es {total:.3f} > 1")

    idm = acc.get("idm", "auto")
    if idm == "auto":
        idm = idm_for(len({a.symbol for a in active}))
    capital = acc.get("capital", "equity")
    capital = None if capital == "equity" else float(capital)

    mt5_path = raw.get("mt5", {}).get("path") or None
    return Settings(
        path=path,
        run_mode=run_mode,
        poll_seconds=float(gen.get("poll_seconds", 5)),
        state_dir=base / gen.get("state_dir", "state"),
        log_dir=base / gen.get("log_dir", "logs"),
        stop_file=base / gen.get("stop_file", "STOP"),
        capital=capital,
        risk_target=float(acc.get("risk_target", 0.20)),
        idm=float(idm),
        max_trades_per_day=int(saf.get("max_trades_per_day", 30)),
        spike_sigma=float(saf.get("spike_sigma", 8.0)),
        max_tick_age_seconds=float(saf.get("max_tick_age_seconds", 120)),
        deviation_points=int(saf.get("deviation_points", 20)),
        min_history_days=int(saf.get("min_history_days", 500)),
        blackout_start=_hhmm(saf.get("blackout_start", "23:45"), "blackout_start"),
        blackout_end=_hhmm(saf.get("blackout_end", "00:20"), "blackout_end"),
        mt5_path=mt5_path,
        strategies=strategies,
        assignments=assignments,
    )
