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
