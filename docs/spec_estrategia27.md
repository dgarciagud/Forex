# SPEC — Estrategia 27 de Carver (*Safer fast mean reversion*) para backtest en renta variable

Especificación autocontenida para implementar y backtestear la estrategia 27 de *Advanced
Futures Trading Strategies* (Robert Carver, 2022) sobre **índices de renta variable**.
Resumen propio (no texto del libro). Incluye las lecciones de su implementación en FX
(repo `dgarciagud/Forex`, rama `ccr-cc40f003-7upz2d`: `src/carver_s27.py`, `src/run_limit.py`,
`live/strategies/s27.py`).

---

## 1. Idea

Reversión a la media rápida (horizonte de 1–2 días) operada con datos horarios, que **solo
opera a favor de la tendencia de fondo**: en tendencia alcista compra las caídas por debajo de
un equilibrio; en bajista vende las subidas por encima. Se ejecuta con una escalera de órdenes
límite (parecido a un grid, pero con posición máxima acotada y salida automática cuando gira la
tendencia).

Es la estrategia 26 (reversión rápida pura) más dos protecciones: filtro de tendencia y
atenuación por volatilidad.

---

## 2. Reglas

Todo lo diario se calcula **al cierre del día d** y se usa durante las barras horarias del día
**d+1** (sin mirar al futuro).

### 2.1 Equilibrio
```
E_d = EWMA_span5(cierres diarios)            # adjust=False; ≈ una semana de días hábiles
```
Span 5 elegido sin optimizar; otros spans cercanos dan resultados parecidos.

### 2.2 Volatilidad (estimador estándar de Carver)
```
σ%_d   = 0.7 × EWMA_span32_std(rendimientos diarios %) + 0.3 × media(σ%, últimos 10 años)
σ_p,d  = σ%_d × precio_d                      # vol diaria en unidades de precio
```

### 2.3 Forecast de reversión
```
raw   = (E − P) / σ_p                         # P = precio actual (barra horaria)
```
Positivo si el precio está por debajo del equilibrio (comprar).

### 2.4 Atenuación por volatilidad (de la estrategia 13)
```
V  = σ%_d / media(σ%, últimos 10 años)        # vol relativa
Q  = percentil de V en su propia historia     # 0..1, solo datos pasados (expanding rank)
M  = EWMA_span10(2 − 1.5 × Q)                 # ×2 con la vol mínima vista, ×0.5 con la máxima
```

### 2.5 Filtro de tendencia
```
T  = signo( EWMA16(cierres diarios) − EWMA64(cierres diarios) )      # EWMAC(16,64)
```
Si `signo(raw) ≠ T`, el forecast es **0**. Con T > 0 solo largos; con T < 0 solo cortos.
Cuando la tendencia gira, la posición contraria se cierra (hace de stop loss).

### 2.6 Forecast final
```
F = tope_±20( 20 × M × raw )   (y 0 si contradice a T)
```
Escalar **20** (no el 9.3 de la estrategia 26): el filtro apaga la estrategia ~la mitad del
tiempo y Carver lo duplica para mantener |F| medio ≈ 10. Con escalar 20 y tope 20, la posición
máxima se alcanza cuando el precio está a **σ_p / M** del equilibrio (≈ 1 vol diaria).

### 2.7 Tamaño de posición
```
N_media = Capital × IDM × w × τ / (16 × σ_p × valor_por_unidad_de_precio_de_1_contrato)
N(P)    = F / 10 × N_media                      # lineal en P mientras no topa
```
* τ = 20 % anual; w = peso del instrumento; IDM según nº de instrumentos (tabla AFTS:
  1 → 1.00, 2 → 1.20, 3 → 1.48, 4 → 1.56, 5 → 1.70, 6 → 1.90, 7 → 2.10, 8–14 → 2.20).
* Con P y σ fijos durante el día: `N(P) = k·(E − P)`, `k = 20·M·N_media / (10·σ_p)`, y
  `|N| ≤ 2·N_media`, recortado al lado permitido por T.

### 2.8 Ejecución (libro): escalera de órdenes límite, **sin buffer**
* Posición actual C (en contratos/lotes enteros).
* Compra límite en el precio donde la óptima = C + 1: `P_compra = E − (C + 1)/k`.
* Venta límite donde la óptima = C − 1: `P_venta = E − (C − 1)/k`.
* Al llenarse una, recolocar ambas. No poner la orden que ampliaría más allá del tope o del
  lado prohibido. Si un nivel ya es ejecutable (gap, nuevo día) → a mercado.
* Cancelar las órdenes al final del día y recalcular con el nuevo E, σ, T, M.
* Carver retrasa los llenados **una barra** en su backtest por prudencia.

### 2.9 Plan de trading
Igual que la estrategia 26 (con los cambios anteriores). Asignación sugerida por Carver:
≤ 20 % del capital, junto a estrategias diarias de tendencia y carry.

---

## 3. Resultados del libro (futuros, horario desde 2013, costes = solo comisiones)

| Clase | SR mediano por instrumento | Skew mensual |
|---|---|---|
| **Renta variable** | **0.43** | **−0.77** |
| Volatilidad | 0.60 | −2.41 |
| FX | 0.54 | −0.27 |
| Bonos | 1.00 | −0.11 |
| Metales / Energía / Agrícolas | 0.43 / 0.47 / 0.46 | −0.74 / −0.65 / −0.94 |

Cartera Jumbo (~100 instrumentos): SR 2.14 (el autor no se fía de SR > 2: periodo corto y
difícil simular límites con datos horarios). Correlación con tendencia ≈ +0.34.
**En renta variable es la clase financiera con peor SR y peor skew.**

---

## 4. Lecciones de la implementación en FX (importantes para no repetir errores)

1. **No simular la escalera dentro de la barra con O/H/L/C interpolando linealmente.** Da un
   sesgo fuertemente negativo (SR ≈ −6 en paseo aleatorio): se pierden las oscilaciones
   intra-barra que la escalera aprovecha. Modelos insesgados:
   * *A mercado al cierre de cada barra*, con buffer, ejecutando **una barra después** de la
     señal (con retraso 0 el rebote bid/ask infla el resultado: SR bruto 1.0 → 0.5 en FX).
   * *Escalera de límites fija al inicio de cada barra* (sin recolocar dentro de la barra): una
     orden se llena al precio límite si la barra la atraviesa.
2. **Validar el motor con datos sintéticos:** paseo aleatorio → SR ≈ 0; proceso con reversión
   (Ornstein-Uhlenbeck) → SR > 0.
3. **Supuesto de llenado de las límites = todo el resultado.** En FX (4 pares, 2010–2025,
   buffer 25 %): límite "al tocar" SR ≈ 1.0; exigiendo cruzar ½ spread SR ≈ −0.35; a mercado
   pagando ½ spread SR ≈ −0.2. Si los datos son *bid*, una compra límite necesita que el *ask*
   llegue: el bid debe atravesar un spread completo. Reportar siempre varios supuestos.
4. **Costes:** sin buffer (como el libro) la rotación es enorme; en FX el coste fue 15–21 %
   anual (≈ 1.3 de Sharpe). Un buffer amplio (25 % de la posición media) ayuda. Incluir
   comisión, spread y financiación overnight (la posición se mantiene 1–2 días).
5. **Regímenes (FX):** gana en días de ida y vuelta y movimientos < 0.5 σ; pierde mucho en días
   direccionales y movimientos > 2 σ (asimetría tipo grid). El patrón se repitió en los 4 pares.
   La atenuación por vol solo ayudó en EURCHF; en el resto la ventaja bruta era mayor con vol
   alta. Un filtro de "no ampliar tras k·σ intradía" no mejoró (la posición ya está casi al tope
   cuando el precio se ha alejado 1 σ).
6. **Gaps:** con un salto, todas las órdenes saltadas se llenan al precio de apertura. Riesgo de
   cola real (EURCHF 15-01-2015: la estrategia 26 sin filtro perdió ~75 % en un día).

---

## 5. Adaptaciones específicas para renta variable

* **Instrumentos:** futuros o CFD de índices (S&P 500, Nasdaq 100, DAX, Euro Stoxx 50, FTSE,
  Nikkei…). Mínimo 4–6 para diversificar: en un solo índice el skew es feo.
* **Cierre diario:** usar el cierre de la sesión de contado (o el de liquidación del futuro),
  no medianoche UTC. Definir por índice la zona horaria y el horario de negociación.
* **Gap overnight / fin de semana:** mucho mayor que en FX. Opciones a comparar: (a) operar solo
  en horario de contado y cancelar órdenes fuera de él; (b) 24 h con futuros. Modelar el llenado
  en gap al precio de apertura.
* **Precio ajustado:** con futuros, serie back-adjusted (Panamá); con CFD, incluir dividendos y
  financiación diaria (en CFD de índices los largos suelen pagar financiación).
* **Asimetría de la tendencia:** los índices tienen sesgo alcista, así que el filtro dejará
  sobre todo el lado largo ("comprar caídas en tendencia alcista"). Medir por separado largos y
  cortos.
* **Días de miedo:** las caídas fuertes de bolsa son direccionales y con vol al alza → peor
  entorno para la estrategia; comprobar si la atenuación por vol ayuda aquí (Carver la introdujo
  por COVID-2020 y 2022).
* **Costes:** spread + comisión del instrumento real; tamaño mínimo de contrato (micro-futuros
  o CFD) y granularidad: con cuentas pequeñas hay pocos peldaños.

---

## 6. Backtest pedido (propuesta)

* Datos horarios (OHLC) de 4–6 índices, ≥ 10 años, en UTC, más cierre diario de sesión.
* Variantes: E26 (sin filtros), E27 solo tendencia, E27 completa.
* Ejecución: (a) a mercado al cierre de barra con retraso de 1 barra; (b) límites al tocar;
  (c) límites atravesando ½ spread y 1 spread. Buffer: libro (1 contrato), 10 %, 25 %.
* Métricas por índice y cartera: rentabilidad, vol, Sharpe bruto/neto, max DD, skew diario/
  semanal/mensual, peor día, coste anual, rotación, % de tiempo activo.
* Análisis de regímenes: por tipo de día (eficiencia intradía), tamaño del movimiento en σ,
  fuerza de la tendencia, régimen de vol, y días de caída fuerte (p. ej. índice ≤ −2 %).
* Tests: paseo aleatorio (SR ≈ 0) y OU (SR > 0) antes de usar datos reales.

## 7. Parámetros (resumen)

| Parámetro | Valor |
|---|---|
| Span equilibrio | 5 días |
| Vol | EWMA 32 días, 70/30 con media 10 años |
| Filtro de tendencia | EWMAC(16, 64) diario, signo |
| Atenuación | M = EWMA10(2 − 1.5·Q) |
| Escalar / tope | 20 / ±20 |
| τ | 20 % |
| Ejecución libro | límites a ±1 contrato, sin buffer, retraso 1 barra en backtest |
| Datos | barras de 1 hora; niveles diarios recalculados cada día |
