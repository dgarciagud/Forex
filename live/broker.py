"""Capa de bróker sobre el paquete MetaTrader5 (cuenta hedge de Darwinex).

Todo lo que toca MT5 está aquí. En modo dry_run las lecturas son reales pero las
órdenes solo se registran. Cada estrategia se identifica por su número mágico.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

log = logging.getLogger("live.broker")

_OK_RETCODES = {10008, 10009, 10010}   # PLACED, DONE, DONE_PARTIAL
_FILLING_FOK, _FILLING_IOC = 1, 2      # flags de symbol_info().filling_mode


class BrokerError(RuntimeError):
    pass


@dataclass
class SymbolSpec:
    name: str
    step: float          # tamaño de un paso en lotes (max(volume_step, volume_min))
    volume_max: float
    tick: float
    digits: int
    stops_distance: float
    filling: int         # tipo de llenado para órdenes a mercado


@dataclass
class Tick:
    bid: float
    ask: float
    time: int            # segundos, hora del servidor


@dataclass
class PendingOrder:
    ticket: int
    side: str            # "buy" | "sell"
    volume: float
    price: float


class MT5Broker:
    def __init__(self, dry_run: bool, deviation_points: int = 20, path: str | None = None):
        import MetaTrader5 as mt5  # solo existe en Windows con el terminal instalado
        self.mt5 = mt5
        self.dry_run = dry_run
        self.deviation = deviation_points
        self.path = path
        self._specs: dict[str, SymbolSpec] = {}
        self.currency = ""

    # ------------------------------------------------------------------ conexión
    def connect(self) -> None:
        mt5 = self.mt5
        ok = mt5.initialize(path=self.path) if self.path else mt5.initialize()
        if not ok:
            raise BrokerError(f"no se pudo conectar con MT5: {mt5.last_error()}")
        acc = mt5.account_info()
        if acc is None:
            raise BrokerError("MT5 sin cuenta conectada")
        if acc.margin_mode != mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
            raise BrokerError("este sistema está pensado para una cuenta hedge")
        self.currency = acc.currency
        term = mt5.terminal_info()
        if not self.dry_run and (term is None or not term.trade_allowed):
            raise BrokerError("activa 'Algo Trading' en el terminal MT5")
        log.info("MT5 conectado: cuenta %s (%s), servidor %s, equity %.2f %s, modo %s",
                 acc.login, acc.company, acc.server, acc.equity, acc.currency,
                 "dry_run" if self.dry_run else "LIVE")

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def connected(self) -> bool:
        term = self.mt5.terminal_info()
        return bool(term and term.connected)

    def equity(self) -> float:
        acc = self.mt5.account_info()
        if acc is None:
            raise BrokerError("account_info() devolvió None")
        return float(acc.equity)

    # ------------------------------------------------------------------ mercado
    def spec(self, symbol: str) -> SymbolSpec:
        if symbol in self._specs:
            return self._specs[symbol]
        mt5 = self.mt5
        if not mt5.symbol_select(symbol, True):
            raise BrokerError(f"símbolo {symbol} no disponible")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise BrokerError(f"symbol_info({symbol}) devolvió None")
        if info.filling_mode & _FILLING_IOC:
            filling = mt5.ORDER_FILLING_IOC
        elif info.filling_mode & _FILLING_FOK:
            filling = mt5.ORDER_FILLING_FOK
        else:
            filling = mt5.ORDER_FILLING_RETURN
        spec = SymbolSpec(
            name=symbol,
            step=max(info.volume_step, info.volume_min),
            volume_max=info.volume_max,
            tick=info.trade_tick_size or info.point,
            digits=info.digits,
            stops_distance=info.trade_stops_level * info.point,
            filling=filling,
        )
        self._specs[symbol] = spec
        return spec

    def tick(self, symbol: str) -> Tick | None:
        t = self.mt5.symbol_info_tick(symbol)
        if t is None or t.bid <= 0 or t.ask <= 0:
            return None
        return Tick(bid=t.bid, ask=t.ask, time=int(t.time))

    def daily_closes(self, symbol: str, server_now: int, count: int = 3000) -> pd.Series:
        """Cierres D1 completos (la vela del día en curso se descarta)."""
        rates = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_D1, 0, count)
        if rates is None or len(rates) == 0:
            raise BrokerError(f"sin velas D1 para {symbol}: {self.mt5.last_error()}")
        df = pd.DataFrame(rates)
        df = df[df["time"] + 86400 <= server_now]
        idx = pd.to_datetime(df["time"], unit="s")
        return pd.Series(df["close"].to_numpy(), index=idx, name=symbol)

    def last_bar_time(self, symbol: str, timeframe: str = "H1") -> int | None:
        tf = getattr(self.mt5, f"TIMEFRAME_{timeframe}")
        rates = self.mt5.copy_rates_from_pos(symbol, tf, 0, 1)
        return int(rates[0]["time"]) if rates is not None and len(rates) else None

    def value_per_unit_lot(self, symbol: str, price: float) -> float:
        """Ganancia (divisa de la cuenta) de 1 lote largo cuando el precio sube 1 unidad."""
        delta = price * 0.001
        profit = self.mt5.order_calc_profit(self.mt5.ORDER_TYPE_BUY, symbol, 1.0, price, price + delta)
        if profit is None or profit <= 0:
            raise BrokerError(f"order_calc_profit falló para {symbol}: {self.mt5.last_error()}")
        return profit / delta

    # ------------------------------------------------------------------ estado
    def _positions(self, symbol: str, magic: int):
        return [p for p in (self.mt5.positions_get(symbol=symbol) or ()) if p.magic == magic]

    def position_lots(self, symbol: str, magic: int) -> tuple[float, int, int]:
        """(posición neta en lotes, nº de posiciones largas, nº de cortas)."""
        mt5 = self.mt5
        net, longs, shorts = 0.0, 0, 0
        for p in self._positions(symbol, magic):
            if p.type == mt5.POSITION_TYPE_BUY:
                net += p.volume
                longs += 1
            else:
                net -= p.volume
                shorts += 1
        return net, longs, shorts

    def foreign_positions(self, symbol: str, magics: set[int]) -> int:
        return sum(1 for p in (self.mt5.positions_get(symbol=symbol) or ()) if p.magic not in magics)

    def pending_orders(self, symbol: str, magic: int) -> list[PendingOrder]:
        mt5 = self.mt5
        out = []
        for o in self.mt5.orders_get(symbol=symbol) or ():
            if o.magic != magic:
                continue
            if o.type == mt5.ORDER_TYPE_BUY_LIMIT:
                side = "buy"
            elif o.type == mt5.ORDER_TYPE_SELL_LIMIT:
                side = "sell"
            else:
                side = "other"
            out.append(PendingOrder(o.ticket, side, o.volume_current, o.price_open))
        return out

    def deals_after(self, symbol: str, magic: int, after_ticket: int) -> list[tuple[int, float, int]]:
        """Operaciones (ticket, volumen con signo, hora) del mágico con ticket > after_ticket."""
        mt5 = self.mt5
        now = datetime.now()   # ventana amplia: MT5 interpreta las fechas en hora del servidor
        deals = mt5.history_deals_get(now - timedelta(days=7), now + timedelta(days=2)) or ()
        out = []
        for d in deals:
            if d.symbol != symbol or d.magic != magic or d.ticket <= after_ticket:
                continue
            if d.type == mt5.DEAL_TYPE_BUY:
                out.append((d.ticket, d.volume, int(d.time)))
            elif d.type == mt5.DEAL_TYPE_SELL:
                out.append((d.ticket, -d.volume, int(d.time)))
        return sorted(out)

    # ------------------------------------------------------------------ órdenes
    def _send(self, request: dict, what: str) -> bool:
        if self.dry_run:
            log.info("[dry_run] %s %s", what, request)
            return True
        res = self.mt5.order_send(request)
        if res is None:
            log.error("%s: order_send devolvió None (%s)", what, self.mt5.last_error())
            return False
        if res.retcode not in _OK_RETCODES:
            log.error("%s rechazada: retcode %s %s", what, res.retcode, res.comment)
            return False
        log.info("%s OK: retcode %s orden %s deal %s", what, res.retcode, res.order, res.deal)
        return True

    def place_limit(self, symbol: str, side: str, lots: float, price: float, magic: int,
                    comment: str) -> bool:
        mt5 = self.mt5
        spec = self.spec(symbol)
        req = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": round(lots, 2),
            "type": mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else mt5.ORDER_TYPE_SELL_LIMIT,
            "price": round(price, spec.digits),
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        return self._send(req, f"límite {side} {lots} {symbol} @ {req['price']}")

    def modify_limit(self, order: PendingOrder, symbol: str, price: float) -> bool:
        spec = self.spec(symbol)
        req = {
            "action": self.mt5.TRADE_ACTION_MODIFY,
            "order": order.ticket,
            "symbol": symbol,
            "price": round(price, spec.digits),
            "type_time": self.mt5.ORDER_TIME_GTC,
        }
        return self._send(req, f"mover {order.side} #{order.ticket} {symbol} -> {req['price']}")

    def cancel(self, order: PendingOrder, symbol: str) -> bool:
        req = {"action": self.mt5.TRADE_ACTION_REMOVE, "order": order.ticket}
        return self._send(req, f"cancelar {order.side} #{order.ticket} {symbol}")

    def cancel_all(self, symbol: str, magic: int) -> None:
        for o in self.pending_orders(symbol, magic):
            self.cancel(o, symbol)

    def market(self, symbol: str, delta_lots: float, magic: int, comment: str) -> bool:
        """Compra (delta>0) o vende (delta<0) a mercado.

        En cuenta hedge primero se cierran posiciones contrarias por ticket, para no
        abrir coberturas; el resto abre posición nueva.
        """
        mt5 = self.mt5
        spec = self.spec(symbol)
        tick = self.tick(symbol)
        if tick is None:
            log.error("sin precio para %s", symbol)
            return False
        buy = delta_lots > 0
        remaining = round(abs(delta_lots), 2)
        price = tick.ask if buy else tick.bid
        otype = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
        close_type = mt5.POSITION_TYPE_SELL if buy else mt5.POSITION_TYPE_BUY
        ok = True
        for p in self._positions(symbol, magic):
            if remaining <= 0:
                break
            if p.type != close_type:
                continue
            vol = round(min(p.volume, remaining), 2)
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": vol,
                   "type": otype, "position": p.ticket, "price": price,
                   "deviation": self.deviation, "magic": magic, "comment": comment,
                   "type_filling": spec.filling}
            ok &= self._send(req, f"cerrar {vol} de #{p.ticket} {symbol}")
            remaining = round(remaining - vol, 2)
        if remaining > 0:
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": remaining,
                   "type": otype, "price": price, "deviation": self.deviation,
                   "magic": magic, "comment": comment, "type_filling": spec.filling}
            ok &= self._send(req, f"mercado {'compra' if buy else 'venta'} {remaining} {symbol}")
        return ok

    def net_hedge(self, symbol: str, magic: int) -> None:
        """Si una límite abrió posición contraria, cierra largas contra cortas (close_by)."""
        mt5 = self.mt5
        for _ in range(20):
            pos = self._positions(symbol, magic)
            longs = [p for p in pos if p.type == mt5.POSITION_TYPE_BUY]
            shorts = [p for p in pos if p.type == mt5.POSITION_TYPE_SELL]
            if not longs or not shorts:
                return
            req = {"action": mt5.TRADE_ACTION_CLOSE_BY, "symbol": symbol,
                   "position": longs[0].ticket, "position_by": shorts[0].ticket, "magic": magic}
            if not self._send(req, f"close_by #{longs[0].ticket} con #{shorts[0].ticket} {symbol}"):
                return
            if self.dry_run:
                return
