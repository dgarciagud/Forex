"""Motor live: lee config.toml y gestiona cada (estrategia, cruce) con posición objetivo.

Uso (desde la raíz del repo):
    python -m live.engine --config live/config.toml           # bucle continuo
    python -m live.engine --config live/config.toml --once    # un solo ciclo
    python -m live.engine --config live/config.toml --status  # estado, sin operar

Cada ciclo y por asignación:
  1. Controles: archivo STOP, conciliación de posición, bloqueos, operaciones por día.
  2. Una vez por día (nueva vela D1 completa): estado diario, tamaño, chequeo de saltos.
  3. Plan de la estrategia (escalera límite o mercado con buffer) y ejecución.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import logging.handlers
import os
import time
import statistics
from collections import deque
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from live import config as cfgmod
from live import risk_overlay
from live.strategies import s27

log = logging.getLogger("live.engine")


# --------------------------------------------------------------------------- avisos
class Notifier:
    """Telegram opcional: variables de entorno TELEGRAM_TOKEN y TELEGRAM_CHAT_ID."""

    def __init__(self):
        self.token = os.environ.get("TELEGRAM_TOKEN")
        self.chat = os.environ.get("TELEGRAM_CHAT_ID")
        self._last: dict[str, float] = {}

    def send(self, text: str, key: str | None = None, every_s: float = 3600) -> None:
        if key:
            now = time.time()
            if now - self._last.get(key, 0) < every_s:
                return
            self._last[key] = now
        log.warning("AVISO: %s", text)
        if not (self.token and self.chat):
            return
        try:
            data = urllib.parse.urlencode({"chat_id": self.chat, "text": text}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                   data=data, timeout=10)
        except Exception as exc:  # noqa: BLE001
            log.error("no se pudo enviar a Telegram: %s", exc)


# --------------------------------------------------------------------------- estado
@dataclass
class Slot:
    """Estado en memoria de una asignación (estrategia, cruce)."""
    daily: s27.DailyState | None = None
    n_avg: float = 0.0
    max_steps: int = 0
    last_pos: int | None = None
    last_ticket: int = 0
    mismatch: int = 0
    trades: dict[str, int] = field(default_factory=dict)
    last_h1: int | None = None
    tick_time: int = 0
    tick_seen_at: float = 0.0
    dry: dict = field(default_factory=dict)   # últimas órdenes simuladas (evita repetir logs)
    spreads: deque = field(default_factory=lambda: deque(maxlen=720))  # ~1 h de spreads
    gap_cycles: int = 0  # ciclos seguidos con un nivel ya ejecutable
    ref_spread: float | None = None      # spread mediano de horas líquidas (referencia)
    blocked_since: float | None = None   # desde cuándo se aplaza una orden a mercado
    vol_ann: float = 0.0                 # vol anual actual (overlay)
    vol_jump: float = 0.0                # vol anual en su percentil 99 histórico (overlay)
    returns: object = None               # rendimientos diarios recientes (correlaciones)
    vpu: float = 0.0                     # EUR por unidad de precio y lote
    mid: float = 0.0
    opt_unscaled: float | None = None    # posición óptima sin overlay, en pasos


class Locks:
    """Bloqueos persistentes en state/locks.json. Para desbloquear, borrar la entrada."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}

    def add(self, key: str, reason: str) -> bool:
        if key in self.data:
            return False
        self.data[key] = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC: {reason}"
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
        return True

    def reload(self) -> None:
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def __contains__(self, key: str) -> bool:
        return key in self.data


def _in_window(hhmm: str, start: str, end: str) -> bool:
    return start <= hhmm < end if start <= end else (hhmm >= start or hhmm < end)


# --------------------------------------------------------------------------- motor
class Engine:
    def __init__(self, settings: cfgmod.Settings, broker, notifier: Notifier | None = None,
                 readonly: bool = False):
        self.s = settings
        self.b = broker
        self.n = notifier or Notifier()
        self.readonly = readonly          # --status: no escribe bloqueos
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.locks = Locks(settings.state_dir / "locks.json")
        self.slots: dict[str, Slot] = {a.key: Slot() for a in settings.assignments}
        self.disconnected = 0
        self.capital: float | None = None
        self.overlay_m = 1.0
        self.overlay: risk_overlay.OverlayResult | None = None
        self._overlay_logged = 0.0
        self.overlay_csv = settings.log_dir / "riesgo.csv"
        self.magics = {v["magic"] for v in settings.strategies.values()}
        self.actions_csv = settings.log_dir / "acciones.csv"
        self.daily_csv = settings.log_dir / "estado_diario.csv"

    # ---------------------------------------------------------------- utilidades
    def _record(self, path: Path, row: dict) -> None:
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                header = fh.readline().strip().split(",")
            if header != list(row):          # cambiaron las columnas: archivar el CSV anterior
                path.rename(path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"))
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)

    def _action(self, key: str, what: str, detail: str, ok: bool) -> None:
        self._record(self.actions_csv, {"utc": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}",
                                        "asignacion": key, "accion": what, "detalle": detail,
                                        "ok": ok, "modo": self.s.run_mode})

    def _lock(self, key: str, reason: str) -> None:
        if self.readonly:
            log.warning("(status) se bloquearía %s: %s", key, reason)
            return
        if self.locks.add(key, reason):
            self.n.send(f"BLOQUEADO {key}: {reason}. Revisa y borra la entrada de "
                        f"{self.locks.path} para reanudar.")

    def _stop_state(self) -> str | None:
        if not self.s.stop_file.exists():
            return None
        content = self.s.stop_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
        return "flat" if content == "flat" else "stop"

    # ---------------------------------------------------------------- ciclo
    def cycle(self, trade: bool = True) -> None:
        self.locks.reload()
        if not self.b.connected():
            self.disconnected += 1
            self.n.send("MT5 desconectado; reintentando la conexión", key="disconnected", every_s=900)
            if self.disconnected % 6 == 0:          # cada ~30 s: rehacer el enlace con el terminal
                self.b.reconnect()
            return
        if self.disconnected:
            self.n.send(f"MT5 reconectado tras {self.disconnected} ciclos", key="reconnected", every_s=60)
            self.disconnected = 0
            return
        stop = self._stop_state()
        if stop:
            self.n.send(f"archivo STOP activo ({stop})", key="stop", every_s=6 * 3600)
        if self.s.overlay_enabled:
            try:
                self._update_overlay()
            except Exception as exc:  # noqa: BLE001
                log.exception("error en el risk overlay")
                self.n.send(f"error en el risk overlay: {exc}", key="err:overlay")
        for a in self.s.active():
            try:
                self._run(a, stop, trade)
            except Exception as exc:  # noqa: BLE001
                log.exception("error en %s", a.key)
                self.n.send(f"error en {a.key}: {exc}", key=f"err:{a.key}")

    def _run(self, a: cfgmod.Assignment, stop: str | None, trade: bool) -> None:
        sp = self.s.strategies[a.strategy]
        magic = sp["magic"]
        slot = self.slots[a.key]
        spec = self.b.spec(a.symbol)
        tick = self.b.tick(a.symbol)
        if tick is None:
            return
        server = datetime.fromtimestamp(tick.time, tz=timezone.utc)   # reloj del servidor
        day = f"{server:%Y-%m-%d}"

        # --- 1. conciliación: posición real vs la esperada por nuestras operaciones
        pos = self._reconcile(a, slot, magic, spec, day)
        if pos is None:
            return

        if stop:
            if trade:
                self.b.cancel_all(a.symbol, magic)
                if stop == "flat" and pos != 0:
                    ok = self.b.market(a.symbol, -pos * spec.step, magic, f"{a.strategy} STOP")
                    self._action(a.key, "STOP flat", f"{-pos} pasos", ok)
            return

        # --- 2. datos frescos y ventana de rollover
        now = time.time()
        if tick.time != slot.tick_time:
            slot.tick_time, slot.tick_seen_at = tick.time, now
        stale = now - slot.tick_seen_at > self.s.max_tick_age_seconds
        blackout = _in_window(f"{server:%H:%M}", self.s.blackout_start, self.s.blackout_end)
        if stale or blackout:
            if trade:
                self.b.cancel_all(a.symbol, magic)
            return

        slot.spreads.append(tick.ask - tick.bid)
        # --- 3. estado diario (una vez por vela D1 completa)
        if slot.daily is None or self._new_daily(a, slot, tick):
            closes = self.b.daily_closes(a.symbol, tick.time)
            age_days = (tick.time - closes.index[-1].timestamp()) / 86400 if len(closes) else 99
            if age_days > 6:   # margen para fin de semana + festivo
                # al pedir historial por primera vez MT5 puede devolver velas viejas mientras
                # sincroniza: no usar y reintentar en el siguiente ciclo
                self.n.send(f"{a.key}: último cierre D1 de hace {age_days:.1f} días; esperando "
                            "historial actualizado", key=f"stale:{a.key}", every_s=6 * 3600)
                return
            if not self._refresh_daily(a, slot, sp, spec, closes):
                return
        st = slot.daily

        if a.key in self.locks:
            if trade:
                self.b.cancel_all(a.symbol, magic)
            return
        if slot.trades.get(day, 0) > self.s.max_trades_per_day:
            self._lock(a.key, f"más de {self.s.max_trades_per_day} operaciones hoy")
            return

        # --- 4. plan
        # Posición óptima sin overlay (entrada del risk overlay) y posición media escalada
        slot.mid = 0.5 * (tick.bid + tick.ask)
        slot.opt_unscaled = s27.plan_limit(st, slot.n_avg, slot.max_steps, pos, tick.bid, tick.ask,
                                           spec.tick, a.sides, a.mode, sp).optimal
        n_avg = slot.n_avg * (self.overlay_m if self.s.overlay_enabled else 1.0)
        if sp.get("execution", "limit") == "market":
            h1 = self.b.last_bar_time(a.symbol, "H1")
            new_bar = slot.last_h1 is not None and h1 != slot.last_h1
            slot.last_h1 = h1
            plan = s27.plan_market(st, n_avg, slot.max_steps, pos, tick.bid, tick.ask,
                                   a.sides, a.mode, sp, new_bar)
        else:
            plan = s27.plan_limit(st, n_avg, slot.max_steps, pos, tick.bid, tick.ask,
                                  spec.tick, a.sides, a.mode, sp)
        if not trade:
            log.info("%s bid=%s ask=%s pos=%d rango=[%d,%d] óptima=%.2f compra=%s venta=%s mercado=%d %s",
                     a.key, tick.bid, tick.ask, pos, plan.lo, plan.hi, plan.optimal, plan.buy_limit,
                     plan.sell_limit, plan.market_steps, plan.reason)
            return

        # --- 5. ejecución
        if self.b.dry_run:
            # en dry_run la posición no cambia: registrar solo cuando cambia el plan
            snap = (plan.market_steps, plan.buy_limit, plan.sell_limit, plan.buy_steps, plan.sell_steps)
            if slot.dry.get("plan") == snap:
                return
            slot.dry["plan"] = snap
        # Si el precio ya está en el nivel, la orden límite que hay allí puede estar llenándose
        # y MT5 aún no lo refleja en la posición: esperar ~3 ciclos antes de ir a mercado para
        # no duplicar la operación (pasó en EURCHF el 10-11-2026).
        if plan.market_steps and plan.reason.startswith("nivel"):
            slot.gap_cycles += 1
            if slot.gap_cycles < 3:
                return
        else:
            slot.gap_cycles = 0
        if plan.market_steps and not self._market_allowed(a, slot, tick, server, plan):
            self.b.cancel_all(a.symbol, magic)      # no dejar límites de niveles viejos
            return
        slot.blocked_since = None
        if plan.market_steps:
            slot.gap_cycles = 0
            self.b.cancel_all(a.symbol, magic)
            ok = self.b.market(a.symbol, plan.market_steps * spec.step, magic, a.strategy)
            self._action(a.key, "mercado", f"{plan.market_steps:+d} pasos ({plan.reason})", ok)
            return
        self._sync_limit(a, magic, spec, tick, "buy", plan.buy_limit, plan.buy_steps)
        self._sync_limit(a, magic, spec, tick, "sell", plan.sell_limit, plan.sell_steps)

    # ---------------------------------------------------------------- piezas
    def _update_overlay(self) -> None:
        """Recalcula el multiplicador M del risk overlay con las posiciones óptimas sin escalar."""
        rows = [(a, self.slots[a.key]) for a in self.s.active()]
        rows = [(a, sl) for a, sl in rows if sl.daily is not None and sl.opt_unscaled is not None
                and sl.vpu > 0 and sl.returns is not None]
        if not rows or not self.capital:
            return
        step = {a.key: self.b.spec(a.symbol).step for a, _ in rows}
        w = np.array([sl.opt_unscaled * step[a.key] * sl.vpu * sl.mid / self.capital for a, sl in rows])
        vol = np.array([sl.vol_ann for _, sl in rows])
        jump = np.array([sl.vol_jump for _, sl in rows])
        rets = pd.concat({a.key: sl.returns for a, sl in rows}, axis=1).dropna().tail(self.s.corr_days)
        corr = rets.corr().values if len(rets) > 60 else np.eye(len(rows))
        res = risk_overlay.compute(w, vol, jump, corr, self.s.overlay)
        changed = abs(res.multiplier - self.overlay_m) > 1e-9
        self.overlay_m, self.overlay = res.multiplier, res
        now = time.time()
        if changed or now - self._overlay_logged > 3600:
            self._overlay_logged = now
            self._record(self.overlay_csv, {
                "utc": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}", "multiplicador": res.multiplier,
                "limita": res.binding, "riesgo": round(res.risk, 4), "saltos": round(res.jump_risk, 4),
                "correlacion": round(res.corr_shock, 4), "apalancamiento": round(res.leverage, 3),
                **{f"w_{a.symbol}": round(x, 4) for (a, _), x in zip(rows, w)}})
        if changed:
            msg = (f"risk overlay: multiplicador {res.multiplier:.2f}"
                   + (f" (limita {res.binding})" if res.binding else " (sin límite activo)")
                   + f"; riesgo {res.risk:.0%}, saltos {res.jump_risk:.0%}, "
                     f"correlación {res.corr_shock:.0%}, apalancamiento {res.leverage:.1f}x")
            if res.multiplier < 1:
                self.n.send(msg, key="overlay", every_s=600)
            else:
                log.info(msg)

    def _market_allowed(self, a, slot: Slot, tick, server: datetime, plan) -> bool:
        """¿Se puede enviar ya la orden a mercado o conviene esperar?

        * Reducciones obligatorias (fuera de rango): solo esperan a un spread normal, y como
          mucho max_forced_wait_hours; después se ejecutan igualmente (control de riesgo).
        * Resto (nivel ya ejecutable): además solo dentro de market_hours del par.
        Spread normal = como mucho max_spread_mult × el spread mediano de horas líquidas.
        """
        forced = plan.reason.startswith("fuera de rango")
        now = time.time()
        if slot.blocked_since is None:
            slot.blocked_since = now
        waited_h = (now - slot.blocked_since) / 3600
        start, end = a.market_hours or self.s.market_hours
        if not forced and not _in_window(f"{server:%H:%M}", start, end):
            log.debug("%s: fuera de horario de mercado (%s-%s); se aplaza", a.key, start, end)
            return False
        ref = slot.ref_spread
        if ref is None:                                   # sin historial de ticks: última hora
            if len(slot.spreads) < 30:
                return False
            ref = statistics.median(slot.spreads)
        spread = tick.ask - tick.bid
        if spread <= self.s.max_spread_mult * ref:
            return True
        if forced and waited_h >= self.s.max_forced_wait_hours:
            self.n.send(f"{a.key}: reducción obligatoria tras {waited_h:.1f} h esperando spread "
                        f"normal; se ejecuta con spread {spread:.6g}", key=f"forced:{a.key}", every_s=3600)
            return True
        self.n.send(f"{a.key}: spread {spread:.6g} > {self.s.max_spread_mult}× referencia "
                    f"({ref:.6g}); se aplaza la orden a mercado", key=f"spread:{a.key}", every_s=1800)
        return False

    def _reconcile(self, a, slot: Slot, magic: int, spec, day: str) -> int | None:
        before = self.b.deals_after(a.symbol, magic, slot.last_ticket)
        lots, longs, shorts = self.b.position_lots(a.symbol, magic)
        after = self.b.deals_after(a.symbol, magic, slot.last_ticket)
        if [d[0] for d in before] != [d[0] for d in after]:
            return None                                   # llegó un llenado: reintentar
        pos = round(lots / spec.step)
        if slot.last_pos is None:                         # arranque: se toma lo que hay
            slot.last_pos = pos
            slot.last_ticket = max([d[0] for d in after], default=slot.last_ticket)
            if pos:
                log.info("%s arranca con posición existente de %d pasos", a.key, pos)
            if self.b.foreign_positions(a.symbol, self.magics):
                log.warning("%s: hay posiciones de otros mágicos/manuales en %s (se ignoran)",
                            a.key, a.symbol)
        else:
            expected = slot.last_pos + round(sum(d[1] for d in after) / spec.step)
            if pos != expected:
                slot.mismatch += 1
                if slot.mismatch >= 2:
                    self._lock(a.key, f"posición {pos} pasos, esperada {expected}")
                    slot.mismatch = 0
                    slot.last_pos = pos
                    slot.last_ticket = max([d[0] for d in after], default=slot.last_ticket)
                return None
            slot.mismatch = 0
            slot.trades[day] = slot.trades.get(day, 0) + len(after)
            slot.last_pos = pos
            slot.last_ticket = max([d[0] for d in after], default=slot.last_ticket)
        if longs and shorts and not self.s.dry_run:
            self.b.net_hedge(a.symbol, magic)
        if abs(pos) * spec.step > a.max_lots + 1e-9:
            self._lock(a.key, f"posición {pos * spec.step:.2f} lotes supera max_lots {a.max_lots}")
        return pos

    def _new_daily(self, a, slot: Slot, tick) -> bool:
        closes = self.b.daily_closes(a.symbol, tick.time, count=2)
        return len(closes) > 0 and closes.index[-1] != slot.daily.day

    def _refresh_daily(self, a, slot: Slot, sp: dict, spec, closes) -> bool:
        if len(closes) < self.s.min_history_days:
            self._lock(a.key, f"solo {len(closes)} días de historia (mín. {self.s.min_history_days})")
            return False
        st = s27.daily_state(closes, sp)
        if not (st.sigma_p > 0) or st.sigma_p != st.sigma_p:
            self._lock(a.key, "volatilidad no válida")
            return False
        if abs(st.last_ret) > self.s.spike_sigma * st.prev_vol_pct:
            flag = self.s.state_dir / f"approve_{a.symbol}_{st.day:%Y-%m-%d}"
            if not flag.exists():
                self._lock(a.key, f"salto de {st.last_ret:+.2%} el {st.day:%Y-%m-%d} "
                                  f"(> {self.s.spike_sigma} desv.). Si el dato es bueno crea "
                                  f"{flag.name} en state/ y desbloquea")
        equity = self.b.equity()
        capital = equity if self.s.capital is None else min(self.s.capital, equity)
        vpu = self.b.value_per_unit_lot(a.symbol, st.close)
        slot.n_avg = s27.n_avg_steps(capital, self.s.idm, a.weight, a.size_mult,
                                     self.s.risk_target, st.sigma_p, vpu, spec.step)
        slot.max_steps = int(min(a.max_lots, spec.volume_max) / spec.step + 1e-9)
        slot.daily = st
        vol_hist = s27.carver_vol(closes.pct_change()) * 16
        slot.vol_ann = float(vol_hist.iloc[-1])
        slot.vol_jump = float(vol_hist.quantile(0.99))
        slot.returns = closes.pct_change().tail(self.s.corr_days + 10)
        slot.vpu = vpu
        self.capital = capital
        try:
            slot.ref_spread = self.b.reference_spread(a.symbol, *self.s.liquid_hours,
                                                      self.s.reference_days)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: sin spread de referencia (%s); se usa la mediana de la última hora",
                        a.key, exc)
            slot.ref_spread = None
        row = {"utc": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M}", "asignacion": a.key,
               "dia": f"{st.day:%Y-%m-%d}", "cierre": st.close, "equilibrio": round(st.eq, 6),
               "sigma_p": round(st.sigma_p, 6), "vol_anual_%": round(st.vol_pct * 1600, 2),
               "tendencia": st.trend, "M": round(st.att, 3), "capital": round(capital, 2),
               "idm": self.s.idm, "peso": round(a.weight, 4),
               "pos_media_lotes": round(slot.n_avg * spec.step, 4),
               "pos_max_lotes": round(min(2 * slot.n_avg, slot.max_steps) * spec.step, 4),
               "orden_lotes": round(s27.limit_order_steps(slot.n_avg, sp) * spec.step, 2),
               "spread_ref": slot.ref_spread}
        self._record(self.daily_csv, row)
        log.info("estado diario %s", row)
        if slot.n_avg * 2 < 1:
            self.n.send(f"{a.key}: posición máxima {2 * slot.n_avg:.2f} pasos (< 1 lote mínimo); "
                        "no operará hasta que suba el capital o la vol baje", key=f"small:{a.key}",
                        every_s=24 * 3600)
        return True

    def _sync_limit(self, a, magic: int, spec, tick, side: str, price: float | None,
                    steps: int = 1) -> None:
        lots = round(steps * spec.step, 2)
        orders = [o for o in self.b.pending_orders(a.symbol, magic) if o.side == side]
        if price is not None:
            valid = (price <= tick.ask - spec.stops_distance if side == "buy"
                     else price >= tick.bid + spec.stops_distance)
            if not valid:
                price = None
        keep = None
        for o in orders:
            if keep is None and price is not None and abs(o.volume - lots) < 1e-9:
                keep = o
            else:
                self._action(a.key, f"cancelar {side}", f"#{o.ticket}", self.b.cancel(o, a.symbol))
        if price is None:
            return
        if keep is None:
            ok = self.b.place_limit(a.symbol, side, lots, price, magic, a.strategy)
            self._action(a.key, f"límite {side}", f"{lots} @ {price}", ok)
        elif abs(keep.price - price) > spec.tick / 2:
            ok = self.b.modify_limit(keep, a.symbol, price)
            self._action(a.key, f"mover {side}", f"#{keep.ticket} {keep.price} -> {price}", ok)


# --------------------------------------------------------------------------- main
def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.TimedRotatingFileHandler(log_dir / "live.log", when="midnight",
                                                   backupCount=60, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sistema live de estrategias de Carver en MT5")
    ap.add_argument("--config", default="live/config.toml")
    ap.add_argument("--once", action="store_true", help="un solo ciclo")
    ap.add_argument("--status", action="store_true", help="mostrar el plan sin operar")
    args = ap.parse_args()

    settings = cfgmod.load(args.config)
    _setup_logging(settings.log_dir)
    from live.broker import MT5Broker
    broker = MT5Broker(dry_run=settings.dry_run or args.status,
                       deviation_points=settings.deviation_points, path=settings.mt5_path,
                       expect_server=settings.expect_server)
    try:
        broker.connect()
    except Exception:
        log.exception("no se pudo arrancar")
        raise
    log.info("IDM %.2f, riesgo %.0f%%, capital %s, asignaciones: %s", settings.idm,
             100 * settings.risk_target, settings.capital or "equity",
             ", ".join(f"{a.key}[{a.sides},{a.mode},w={a.weight:.3f}]" for a in settings.active()))
    engine = Engine(settings, broker, readonly=args.status)
    try:
        if args.status or args.once:
            engine.cycle(trade=not args.status)
            if settings.overlay_enabled:
                engine._update_overlay()
                r = engine.overlay
                if r is not None:
                    log.info("risk overlay: multiplicador %.2f %s| riesgo %.1f%%, saltos %.1f%%, "
                             "correlación %.1f%%, apalancamiento %.2fx", r.multiplier,
                             f"(limita {r.binding}) " if r.binding else "", 100 * r.risk,
                             100 * r.jump_risk, 100 * r.corr_shock, r.leverage)
            return
        while True:
            start = time.time()
            engine.cycle()
            time.sleep(max(0.5, settings.poll_seconds - (time.time() - start)))
    finally:
        broker.shutdown()


if __name__ == "__main__":
    main()
