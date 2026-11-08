# Estrategia 27 de Carver (*Safer fast mean reversion*) en FX

Backtest de la estrategia 27 de *Advanced Futures Trading Strategies* (Robert Carver)
sobre **EURCHF, EURNOK, USDCAD y USDJPY**, con velas de **1h y 2h**, 2010–2025.
Se incluye la estrategia 26 (reversión rápida sin protecciones) como referencia.

## Cómo reproducir

```bash
pip install pandas numpy matplotlib histdata
python src/download_histdata.py EURCHF EURNOK USDCAD USDJPY EURUSD   # ya incluido en data/
python src/run_backtest.py --bar 1h
python src/run_backtest.py --bar 2h
```

* `data/<PAR>_H1.csv`: velas horarias (UTC) construidas desde los minutos de HistData.com.
  EURUSD solo se usa para convertir a USD el P&L en CHF/NOK.
* `src/carver_s27.py`: señales y simulador. `src/run_backtest.py`: tablas y gráficos.
* `results/1h/` y `results/2h/`: CSV de resultados y gráficos.
* `src/download_dukascopy.py`: descargador alternativo (Dukascopy limitaba las peticiones).

## Implementación

| Pieza | Detalle |
|---|---|
| Equilibrio | EWMA span 5 de los cierres diarios (día FX cierra 21:00 UTC), del día anterior |
| Forecast | 9.3 × (equilibrio − precio de la vela) / vol diaria en precio, tope ±20 |
| Vol | EWMA span 32 de retornos diarios, 70 % actual + 30 % media de 10 años |
| Tamaño | Capital 1 M USD, τ = 20 %, peso 25 % por par, IDM 1.56, lotes de 10 000 |
| **S27: filtro de tendencia** | forecast = 0 si su signo contradice EWMAC(16,64) diario |
| **S27: atenuación por vol** | forecast × EWMA₁₀(2 − 1.5·Q), Q = percentil de vol relativa |
| Buffer | se opera solo si la posición óptima se aleja ≥ 10 % de la posición media (sensibilidad: 1 lote, 25 %, 50 %) |
| Ejecución | al cierre de cada vela; coste = medio spread por lote (EURCHF 0.8 pip, EURNOK 12 pips, USDCAD 0.8 pip, USDJPY 0.6 pip) |
| No incluido | swaps/carry overnight, comisiones aparte del spread, deslizamiento en gaps |

**Nota sobre la ejecución.** En el libro las órdenes son límite en los precios donde la
posición óptima cambia ±1 contrato. Simular esa escalera *dentro* de cada vela con O/H/L/C
da un sesgo fuertemente negativo (Sharpe −6 en un paseo aleatorio), porque se pierden
las oscilaciones intra-vela que la escalera aprovecha. Por eso se evalúa la señal en el
cierre de cada vela, lo que es insesgado (Sharpe ≈ 0 en paseo aleatorio, verificado) pero
conservador: no captura la reversión dentro de la hora.

## Resultados (cartera de los 4 pares, 2010–2025, buffer 10 %)

### Velas de 1 hora

| Variante | Costes | Ret. anual | Vol | Sharpe | Max DD | Skew mensual | Coste anual |
|---|---|---|---|---|---|---|---|
| S26 mean reversion | bruto | 13.9 % | 25.7 % | 0.54 | −83 % | −8.4 | – |
| S26 mean reversion | neto | −1.7 % | 25.7 % | −0.07 | −88 % | −8.4 | 15.5 % |
| S27 solo filtro tendencia | bruto | 11.5 % | 10.7 % | **1.07** | −16 % | 0.0 | – |
| S27 solo filtro tendencia | neto | 4.5 % | 10.7 % | **0.42** | −23 % | 0.0 | 7.0 % |
| S27 completa | bruto | 11.7 % | 11.8 % | 0.99 | −17 % | 0.0 | – |
| S27 completa | neto | 3.0 % | 11.7 % | 0.25 | −31 % | 0.0 | 8.7 % |

### Velas de 2 horas

| Variante | Costes | Ret. anual | Vol | Sharpe | Max DD | Coste anual |
|---|---|---|---|---|---|---|
| S26 mean reversion | bruto / neto | 7.6 % / −5.1 % | 29.4 % | 0.26 / −0.18 | −96 % / −97 % | 12.7 % |
| S27 solo filtro tendencia | bruto / neto | 8.5 % / 2.8 % | 10.4 % | 0.82 / 0.27 | −16 % / −30 % | 5.7 % |
| S27 completa | bruto / neto | 8.3 % / 1.3 % | 11.5 % | 0.72 / 0.11 | −22 % / −40 % | 7.1 % |

### Sensibilidad S27 completa (1h): Sharpe según buffer y coste

| Buffer | sin costes | ½ medio spread | medio spread | Coste anual (medio spread) |
|---|---|---|---|---|
| 1 lote | 1.21 | 0.59 | −0.03 | 14.8 % |
| 10 % | 0.99 | 0.63 | 0.25 | 8.7 % |
| 25 % | 0.71 | 0.52 | 0.32 | 4.7 % |
| 50 % | 0.43 | 0.35 | 0.28 | 2.1 % |

Por par (S27 completa, 1h, neto): EURCHF Sharpe 0.46, USDJPY 0.15, EURNOK 0.01, USDCAD −0.03.
Antes de costes los cuatro son positivos (1.7–4.9 % anual a 5 % de vol).

## Conclusiones

1. **La S26 sin protecciones es inviable**: el 15‑ene‑2015 (fin del suelo del franco suizo)
   la reversión en EURCHF pierde ~75 % del capital en un día (skew mensual −8). Es
   exactamente el riesgo que motiva la estrategia 27.
2. **El filtro de tendencia es lo que hace la estrategia "segura"**: elimina el desastre del
   SNB, baja el drawdown de −83 % a −16 % y sube el Sharpe bruto de 0.5 a ~1.0.
3. **Hay ventaja bruta clara** (Sharpe ~1 en 1h, ~0.7–0.8 en 2h), pero **los costes se comen
   la mayor parte**: la estrategia rota cientos de lotes al día. Con spread de mercado
   el Sharpe neto queda en 0.1–0.4.
4. **1h es mejor que 2h**: más señal bruta y el coste relativo similar.
5. **La atenuación por vol no aporta** en estos pares (ligeramente peor que solo el filtro).
6. Para que sea operable hace falta: ejecutar con órdenes límite (como propone Carver, sin
   pagar spread → acercarse a la columna "sin costes"), un buffer del 25 % y/o centrarse en
   pares baratos (EURCHF, USDJPY). EURNOK es demasiado caro para esta frecuencia.

Caveats: la S27 implementada es la interpretación descrita arriba (filtro de tendencia +
atenuación de vol sobre la S26); ambos componentes son configurables en `Config`. Parte del
resultado del filtro de tendencia proviene de mantener posiciones solo en la dirección de la
tendencia, es decir, contiene algo de exposición *trend following*.

## Ejecución con órdenes límite (sin pagar spread)

`python src/run_limit.py` → `results/ejecucion_limite.csv`, `results/equity_limite_1h.png`.

Modelo: al inicio de cada vela se coloca una escalera de órdenes límite fija (tamaño de
orden = buffer; nivel *j* en el precio donde la posición óptima = posición + *j*·orden).
Una orden se llena **al precio límite, sin spread**, si la vela lo atraviesa. Las órdenes no
se recolocan dentro de la vela (así no se inventa el orden intra-vela; en paseo aleatorio
el Sharpe sale ≈ 0). Las órdenes que ya son ejecutables al abrir la vela (cambio diario del
equilibrio) y los cierres obligados por el filtro de tendencia se ejecutan a mercado
pagando medio spread: de ahí el coste residual.

Como los datos de HistData son precios **bid**, una venta límite se llena cuando el bid toca
el nivel, pero una compra límite necesita que el *ask* llegue, es decir, que el bid lo
atraviese un spread completo. **El caso realista es «atravesar ½ spread» (media de ambos lados)**;
«al tocar» es el optimista (además ignora la cola de órdenes).

### Sharpe de la cartera, velas 1h (buffer 10 % / 25 %)

| Variante | Mercado, ½ spread | Mercado, sin costes | Límite al tocar | **Límite, atravesar ½ spread** | Límite, atravesar 1 spread |
|---|---|---|---|---|---|
| S26 | −0.07 / −0.01 | 0.54 / 0.35 | 0.62 / 0.67 | −0.36 / −0.05 | −1.08 / −0.61 |
| S27 solo tendencia | 0.42 / **0.46** | 1.07 / 0.79 | 1.07 / **1.14** | −0.12 / 0.29 | −1.03 / −0.40 |
| S27 completa | 0.25 / 0.32 | 0.99 / 0.71 | 0.87 / 1.00 | −0.45 / −0.03 | −1.41 / −0.81 |

Con velas de 2h el patrón es el mismo (S27 solo tendencia, 25 %: 0.32 mercado, 1.12 al tocar,
0.31 atravesando ½ spread).

**Conclusión:** las órdenes límite **solo mejoran si se llenan en cuanto el precio toca el
nivel** (Sharpe ~1.1). Si se exige el cruce realista del spread, la selección adversa
(solo te llenan cuando el precio sigue en tu contra; te pierdes los rebotes que se dan
justo en el nivel) se come la ventaja y el resultado es **igual o peor que ejecutar a
mercado** (0.29 vs 0.46). Por pares, EURCHF y EURNOK aguantan mejor con límites;
USDCAD y USDJPY empeoran. La ventaja de la estrategia en FX spot es del orden del spread,
por lo que el resultado depende casi por completo de la calidad de ejecución.

## Revisión contra el libro (v2)

Contrastado con el capítulo de la estrategia 27 (ver `docs/carver_estrategias.md`). Cambios:

1. **Escalar del forecast 20 en la S27** (no 9.3): el filtro apaga la estrategia ~50 % del
   tiempo y Carver duplica el escalar. La vol de la cartera sube de ~11 % a ~15 %.
2. **Llenados retrasados una vela** en la ejecución a mercado, como hace Carver. Antes se
   operaba al mismo cierre que generaba la señal: en datos reales eso captura el rebote
   bid/ask y **inflaba el resultado** (Sharpe bruto ~1.0 → ~0.5).

### Resultados v2 (cartera, 1h, buffer 10 %/25 %)

| Variante | Mercado ½ spread | Mercado sin costes | Límite al tocar | Límite atravesar ½ spread |
|---|---|---|---|---|
| S26 | −0.42 / – | 0.44 / – | – | – |
| S27 solo tendencia | −0.34 / −0.08 | 0.56 / 0.46 | 0.93 / **1.13** | −0.48 / −0.12 |
| S27 completa | −0.49 / −0.21 | 0.47 / 0.39 | 0.80 / 1.00 | −0.68 / −0.35 |

Con 2h el patrón es igual (S27 solo tendencia 25 %: −0.05 mercado, 1.04 al tocar, 0.01 atravesando ½ spread).

**Conclusión v2:** con supuestos realistas la S27 **no es rentable en estos 4 pares de FX spot**.
Solo funciona si las órdenes límite se llenan al tocar el nivel (SR ~1, comparable al 0.54
por instrumento del libro, que también asume solo comisiones). La diferencia entre "al tocar"
y "cruzar ½ spread" es todo el resultado: la estrategia vive o muere por la microestructura.
Por pares, EURCHF y EURNOK son los únicos con señal con límites; USDCAD/USDJPY pierden.
Las tablas de las secciones anteriores corresponden a la v1 (sin retraso ni escalar 20).
