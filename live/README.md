# Sistema live (Darwinex MT5 + Python)

Motor que ejecuta las estrategias de Carver en una cuenta **hedge** de Darwinex desde un VPS
Windows con MT5 y Python. De momento solo la **estrategia 27** (*safer fast mean reversion*).
Qué estrategia opera en qué cruce, y con qué lados, se decide en [`config.toml`](config.toml).

> **Nada de este código se ha ejecutado todavía contra MT5.** Antes de operar dinero real:
> pruebas → `--status` → `dry_run` → cuenta **demo** de Darwinex durante varias semanas.

## Piezas

| Archivo | Qué hace |
|---|---|
| `config.toml` | Capital, riesgo, límites de seguridad y una sección `[[assignment]]` por estrategia y cruce |
| `config.py` | Carga y valida la configuración (lados, modos, pesos, IDM automático) |
| `strategies/s27.py` | Señal y plan de órdenes de la estrategia 27. Funciones puras, sin MT5; reutiliza `carver_vol` y `vol_attenuation` de `src/carver_s27.py` (los mismos cálculos que el backtest) |
| `broker.py` | Única capa que habla con MT5: velas, ticks, posiciones por número mágico, órdenes límite, a mercado y `close_by` |
| `engine.py` | Bucle principal: controles de seguridad, estado diario y ejecución |
| `tests/test_s27.py` | Pruebas sin MT5 |
| `run_forever.bat` | Arranca el motor y lo reinicia si se cae |

## Cómo funciona (estrategia 27)

1. **Una vez al día**, con la última vela D1 completa (en Darwinex la vela D1 cierra a medianoche
   del servidor, es decir, al cierre de Nueva York):
   * equilibrio = media exponencial (span 5) de los cierres diarios;
   * volatilidad diaria (span 32, mezclada 70/30 con la media de 10 años);
   * signo de la tendencia EWMAC(16,64);
   * multiplicador por volatilidad M = EWMA10(2 − 1,5·Q);
   * posición media en lotes = `capital × IDM × peso × τ / (16 × σ_precio × valor de 1 lote por unidad de precio)`.
     El valor por lote se calcula con `order_calc_profit`, así sale directamente en EUR.
2. **Posición óptima** al precio P: `N = (20 × M × (equilibrio − P) / σ_precio) / 10 × posición media`,
   con tope de ±2× la posición media y de `max_lots`. Solo se permite el lado que coincide con la
   tendencia **y** con `sides`; con `mode` se puede limitar a reducir o cerrar.
3. **Ejecución `limit`**: una compra límite de q pasos en el precio donde la óptima es la posición
   actual + q, y una venta límite donde es − q. q = `buffer_fraction` × posición media (mínimo 1
   paso de 0,01 lotes, que es la escalera del libro). Con `buffer_fraction = 1.0` y 1.700 €, q = 2 pasos. Cuando se llena una se
   recolocan las dos. Si un nivel ya es ejecutable (salto de precio, nuevo día) se va a mercado
   hasta la óptima. Las reducciones obligadas (cambio de tendencia, lado prohibido, modo
   `close`) van a mercado.
   **Ejecución `market`** (la del backtest del repo): una vez por vela H1, a mercado, solo si la
   óptima se aleja más que el buffer.
4. **Cuenta hedge**: las ventas cierran primero posiciones largas por ticket (y viceversa). Si una
   límite abre una posición contraria, se netea con `close_by`.

Tamaño orientativo con 1.700 € y 5 cruces (IDM 1,70, peso 20 %, τ 20 %): posición media de
**≈ 0,015–0,025 lotes** por cruce y máxima de 0,02–0,05. La granularidad de 0,01 lotes es gruesa: cada
nivel de la escalera es un 25–50 % de la posición media. El motor avisa si en algún cruce la
posición máxima no llega a 0,01 lotes.

## Controles de seguridad

| Control | Comportamiento |
|---|---|
| `mode = "dry_run"` | Lee todo de MT5 y registra lo que haría, sin enviar órdenes |
| Archivo `live/STOP` | Si existe: cancela las pendientes y no opera. Si contiene `flat`, además cierra las posiciones del sistema |
| Conciliación | Posición esperada = la última conocida + las operaciones del número mágico. Si no coincide en dos ciclos seguidos (por ejemplo, por un cierre manual) → bloqueo |
| Bloqueos | Se guardan en `live/state/locks.json`. Se cancelan las pendientes y se dejan las posiciones. **Para reanudar, borra la entrada** del archivo |
| `max_trades_per_day` | Si se supera, la asignación queda bloqueada |
| Salto de precio | Si un cierre diario se mueve más de `spike_sigma` desviaciones → bloqueo. Si el dato es correcto: crea `state/approve_<CRUCE>_<AAAA-MM-DD>` y borra el bloqueo |
| `max_lots` | Tope duro de posición por asignación (si se supera → bloqueo) |
| Ventana de rollover | Entre `blackout_start` y `blackout_end` (23:45–01:00, hora del servidor) se cancelan las pendientes y no se opera |
| Horario y spread de las órdenes a mercado | Spread de referencia = mediana de los ticks de 10:00–18:00 del servidor de los últimos `reference_days` días. Una orden a mercado solo sale si el spread ≤ `max_spread_mult` × referencia. Las **no urgentes** (nivel ya ejecutable) además solo dentro de `market_hours` (por defecto 01:00–23:45; EURNOK 10:00–22:00). Las **reducciones obligatorias** ignoran el horario y esperan a un spread normal como mucho `max_forced_wait_hours` (10 h). Mientras se aplaza, se cancelan las pendientes del par |
| Ticks viejos | Si no llegan ticks durante `max_tick_age_seconds` (fin de semana, desconexión) se cancelan las pendientes |
| Risk overlay (AFTS, táctica 4) | Multiplicador ≤ 1 sobre las posiciones óptimas de **todos** los pares (antes del redondeo y el buffer). Es el mínimo de cuatro límites: riesgo esperado de la cartera ≤ 35 %, riesgo con cada volatilidad en su percentil 99 ≤ 110 %, riesgo con correlaciones de choque (±1) ≤ 60 % y apalancamiento ≤ 10×. Máximos = percentil 99 del backtest de la S27 con los 5 pares, así que debería actuar ~1–4 % del tiempo. Registro en `logs/riesgo.csv` |
| Telegram (opcional) | Variables de entorno `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` |

Registros en `live/logs/`: `live.log` (rotación diaria), `acciones.csv` (cada orden) y
`estado_diario.csv` (equilibrio, volatilidad, tendencia, M y tamaño de cada cruce y día).

## Puesta en marcha en el VPS

```bash
pip install -r live/requirements.txt
```
```bash
python -m pytest live/tests -q
```
1. En MT5: inicia sesión (primero en la **demo**), activa **Algo Trading** y comprueba que los
   cinco cruces existen con esos nombres en *Observación del mercado*.
2. Muestra el plan actual sin operar ni escribir bloqueos:
   ```bash
   python -m live.engine --config live/config.toml --status
   ```
   Revisa `live/logs/estado_diario.csv`: los tamaños, la volatilidad y la tendencia deben tener sentido.
3. Deja el motor en `dry_run` unos días (`run_forever.bat`) y revisa `acciones.csv`.
4. Cambia a `mode = "live"` **en la cuenta demo**. Con varias semanas sin incidencias, pasa a la
   cuenta real.
5. Arranque automático: crea una tarea en el Programador de tareas de Windows que se ejecute
   "al iniciar sesión" del usuario del VPS y lance `live\run_forever.bat`. MT5 también tiene que
   abrirse solo con la cuenta conectada; el motor se engancha al terminal abierto.

## Avisos importantes

* **El backtest del repo no avala operar la estrategia 27 en FX al contado.** Según la revisión
  v3 del README principal (S27 completa, velas de 1h), con supuestos de llenado realistas pierde:
  a mercado pagando medio spread, Sharpe −0,82 sin buffer y −0,21 con buffer del 25 %; con
  órdenes límite que deben cruzar medio spread, entre −0,93 y −0,35. Solo es positiva sin costes
  o si las límites se llenan al tocar el nivel (0,60–1,00), que es optimista. La ventaja bruta
  es del orden del spread, EURNOK es demasiado caro y **EURUSD no se ha probado**. Las variantes
  (`execution`, `buffer_fraction`, `vol_attenuation`) están en `config.toml`, pero ninguna está
  demostrada: usa la demo para medir los llenados reales antes de arriesgar dinero.
* **Los swaps no están en el backtest.** La estrategia mantiene posiciones de un día para otro (y
  el miércoles se cobra swap triple).
* Las órdenes límite en real tienen cola y selección adversa. Compara los llenados reales de
  `acciones.csv` con el backtest antes de subir tamaño.
* `enabled = false` deja de gestionar el cruce, pero **no cierra** su posición. Para salir usa
  `mode = "close"`.
* Si cambias `magic`, el motor deja de reconocer las posiciones antiguas.
