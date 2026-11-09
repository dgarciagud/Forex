# Especificación de las estrategias de Robert Carver

Resumen técnico propio (redactado con mis palabras, sin texto de los libros) de las reglas,
fórmulas, parámetros, escalares de forecast y ejecución de los tres libros de Carver, pensado
para implementar backtests en este repo:

| Abrev. | Libro | Enfoque |
|---|---|---|
| **ST** | *Systematic Trading* (2015) | Marco general: forecasts, combinación, volatility targeting, tamaño de posición; tres perfiles de usuario |
| **LT** | *Leveraged Trading* (2019) | "Starter System" para cuentas pequeñas (CFD, spread bets, FX spot, futuros) y sus extensiones |
| **AFTS** | *Advanced Futures Trading Strategies* (2022) | 30 estrategias numeradas sobre futuros + 4 tácticas |

Notas de fuente:
* En AFTS y LT casi todas las fórmulas (y en LT las tablas de escalares) son imágenes. Las
  fórmulas aquí están reconstruidas a partir de la prosa, de los ejemplos numéricos y de las
  tablas que sí son texto. Lo que no se ha podido comprobar en el texto se marca como
  **(no verificado)**.
* Notación común: `P_t` precio (ajustado hacia atrás en futuros), `σ%` desviación típica anual
  de rendimientos porcentuales, `σ_p` desviación típica **diaria** de las diferencias de precio
  (en unidades de precio), `τ` objetivo de riesgo anual, `F` forecast, `N` posición en contratos,
  `M` multiplicador del futuro (o tamaño de punto), `fx` tipo de cambio a la divisa de la cuenta.
  Un año ≈ 256 días hábiles, de ahí el factor `16 = √256` para anualizar.

---

## 1. Marco común (los tres libros)

### 1.1 Forecast
* Un forecast es una predicción del **rendimiento ajustado por riesgo** (proporcional al Sharpe
  esperado). Signo = dirección; magnitud = convicción.
* Escalado: cada regla se multiplica por un **escalar de forecast** para que el valor absoluto
  medio sea **10**. Se calcula sin mirar rentabilidades: media del |forecast bruto| sobre
  muchos instrumentos e historia larga → `escalar = 10 / media|F_bruto|`.
* **Tope ±20** (doble de la posición media). Se aplica a cada regla antes de combinar y otra
  vez al forecast combinado.
* Razones del tope: limita el apalancamiento en colas y las reglas predicen peor en extremos.

### 1.2 Combinación de forecasts
```
F_comb = FDM × Σ_j w_j · cap20(F_j)        (w_j ≥ 0, Σ w_j = 1)
F_final = cap20(F_comb)
```
* Pesos por "handcrafting" (agrupar por estilo y repartir a partes iguales, luego dentro de
  cada grupo) o bootstrapping. Supuesto por defecto: **mismo Sharpe pre-coste** para todas las
  reglas; solo costes y correlaciones mueven los pesos.
* **FDM** (forecast diversification multiplier) = `1 / sqrt(wᵀ H w)`, con `H` la matriz de
  correlación de los forecasts y correlaciones negativas truncadas a 0. Compensa la pérdida de
  magnitud al promediar forecasts poco correlados.
* **IDM** (instrument diversification multiplier): misma fórmula con correlaciones de los
  rendimientos de los subsistemas por instrumento.

### 1.3 Volatilidad
| Libro | Estimador |
|---|---|
| ST | Desv. típica de 25 días, o EWMA de rendimientos al cuadrado con span 36 (≈ misma vida media). Solo se recalcula la posición si la vol cambió > 25 % (semi-automático) |
| LT | Desv. típica simple de los últimos 25 rendimientos diarios × 16. Con precios ajustados, rendimiento = Δ(precio ajustado) / precio del contrato realmente operado |
| AFTS | `σ_EW` = desv. típica EWMA con **span 32** de rendimientos diarios %; estimador final = **0.7·σ_EW + 0.3·(media de σ_EW de los últimos 10 años)**, anualizado ×16. `σ_p` = σ% × precio / 16, o directamente la desv. típica de las diferencias de precio ajustado |

### 1.4 Tamaño de posición
AFTS (formulación de referencia; ST y LT son equivalentes):
```
N_i = F_final × Capital × IDM × w_i × τ / (10 × M_i × P_i × fx_i × σ%_i)
    = F_final × Capital × IDM × w_i × τ / (10 × M_i × fx_i × σ_p,i × 16)
```
* `P_i` es el precio del contrato que se tiene (no el ajustado).
* Con F = 10 se obtiene la **posición media**; con F = 20, el doble.
* ST lo expresa como: *valor de bloque* = cambio en dinero por 1 % de movimiento del precio;
  *volatilidad del instrumento en divisa* = valor de bloque × vol diaria en %; *escalar de
  volatilidad* = objetivo diario de vol en efectivo (Capital × τ / 16) / vol del instrumento
  en divisa de la cuenta; *posición del subsistema* = forecast × escalar / 10; posición de
  cartera = subsistema × peso × IDM.
* LT lo expresa en exposición nocional: `Exposición = (F/10) × τ × Capital / σ%`, luego se
  traduce a contratos/€ por punto según el producto.

### 1.5 Objetivo de riesgo τ
Se toma el **mínimo** de:
1. Límite por margen/apalancamiento máximo del bróker (`τ_max = apalancamiento_max × σ%`).
2. Apalancamiento prudente frente a un peor día plausible (p. ej. aceptar perder la mitad del
   capital en un crash de 1 día del tamaño histórico peor).
3. Tolerancia personal (tablas de probabilidad de pérdidas).
4. **Medio Kelly**: `τ = Sharpe esperado / 2` (Kelly completo: τ = Sharpe). Con sesgo negativo,
   recortar más.

Valores típicos: AFTS usa **τ = 20 %**; ST: 20 % (systems trader), 15 % (semi-automático),
~7.5 % (asset allocator sin apalancamiento); LT: **12 %** para el Starter System, ampliable con
diversificación hasta un máximo de 25–30 %. Spreads de valor relativo en AFTS: **10 %**.

### 1.6 Reducción de costes
* **Buffer / inercia de posición**: zona muerta de ±10 % de la posición media
  (`B = 0.1 × |N_media|`, N_media = posición con F = 10). Si la posición actual en contratos
  enteros está dentro de `[N − B, N + B]` no se opera; si está fuera, se opera **solo hasta el
  borde** más cercano de la zona (AFTS). En ST/LT: operar si la desviación respecto a la
  posición ideal supera el 10 % de la posición media (LT: `(ideal − actual)/media ≥ 10 %`).
* **Suavizado** EWMA de forecasts (se usa en carry, breakout, skew, momentum transversal...).
* **Límite de velocidad** ("speed limit"): no gastar más de **1/3 del Sharpe pre-coste** en
  costes.
  * ST: coste máximo anual 0.13 SR (systems trader), 0.08 SR en otros casos;
    coste anual = coste estandarizado por operación (en SR) × rotación.
  * AFTS: coste de un instrumento ajustado por riesgo ≤ **0.01 SR por operación**
    (≈ 0.10 SR/año para la estrategia de referencia); para una variante de regla, coste
    anual ≤ **0.15 SR**. Coste anual = coste por operación en SR × (rotación + 2 × nº de rolls/año).
  * Coste en SR por operación = coste en precio por contrato / (σ% anual × precio).
* **Mínimo de 4 contratos** de posición media (AFTS): capital mínimo
  `= 4 × M × P × fx × σ% / (IDM × w × τ)`.

### 1.7 Futuros: datos y rolls
* Precio continuo por **ajuste hacia atrás tipo Panamá** (sumar el diferencial en cada roll).
  El precio ajustado incluye carry (es un índice de rendimiento total).
* Contratos: normalmente el más líquido/cercano; en algunos mercados (crudo, gas, STIR, VIX)
  conviene uno más lejano para poder medir carry con el contrato anterior.

---

## 2. *Systematic Trading* (ST)

### 2.1 Pasos del marco (modular)
1. Elegir instrumentos (líquidos, baratos, vol no demasiado baja).
2. Reglas de trading → forecasts escalados (media |F| = 10, tope ±20).
3. Combinar con pesos de forecast + FDM, recapar ±20.
4. Objetivo de vol (τ) → objetivo diario de vol en efectivo.
5. Tamaño de posición por instrumento (escalar de volatilidad).
6. Pesos de instrumento + IDM → posición de cartera.
7. Inercia de posición (10 %) y redondeo.
8. Ajuste de velocidad y tamaño (costes, tamaño mínimo de cuenta).

Reglas de diseño: no ajustar parámetros mirando rentabilidad pre-coste; podar variantes con
correlación > 0.95; aceptar como mucho la mitad del Sharpe del backtest como esperable
(≈ 75 % con bootstrapping fuera de muestra); Sharpe esperado realista ≤ 0.5 por subsistema.

### 2.2 Regla EWMAC (cruce de medias exponenciales)
```
α(L) = 2 / (L + 1)
E_t   = α·P_t + (1 − α)·E_{t−1}
raw_t = (E_fast − E_slow) / σ_p          (σ_p: vol diaria en unidades de precio)
F_t   = cap20(escalar × raw_t)
```
* Ratio lento/rápido fijo = 4. Variantes: 2/8, 4/16, 8/32, 16/64, 32/128, 64/256
  (correlación ≈ 0.9 entre vecinas).
* Escalares: **2/8 → 10.6; 4/16 → 7.5; 8/32 → 5.3; 16/64 → 3.75; 32/128 → 2.65; 64/256 → 1.87**.
* Rotación aproximada (viajes de ida y vuelta/año) y coste máximo por operación para no pasar
  de 0.13 SR/año: 2/8 → 54 / 0.0024; 4/16 → 28 / 0.0046; 8/32 → 16 / 0.0081;
  16/64 → 11 / 0.012; 32/128 → 8.5 / 0.015; 64/256 → 7.5 / 0.017; carry → 10 / 0.013.

### 2.3 Regla de carry
```
rendimiento_esperado_anual (en precio) / (σ_p × 16)  → raw carry (≈ Sharpe esperado)
F = cap20(30 × raw)
```
Cálculo del rendimiento esperado según producto:
* Acciones (contado o margen): (dividendo % − coste de financiación %) × precio.
* CFD de acciones: dividendo − media del tipo pagado en largo y cobrado en corto.
* FX contado: tipo de la divisa extranjera − tipo de la divisa financiada.
* Spread bet: (spot − nivel del spread bet) / tiempo a vencimiento en años.
* Futuros, sin tener el contrato más cercano (preferido): diferencia con el contrato **más
  cercano** dividida por la distancia en años (0.25 trimestral, 0.083 mensual).
* Futuros, teniendo el más cercano: aproximación con el **siguiente** contrato, suponiendo
  pendiente constante de la curva.
* **Cuidado con el signo**: el carry de un largo debe ser positivo en *backwardation*
  (contratos lejanos más baratos). Usar la convención de AFTS (§4, estrategia 10):
  `carry = P_cercano − P_actual` o `carry = P_actual − P_siguiente`.
* Recalcular semanalmente para evitar ruido. Escalar **30**.

### 2.4 Sistema "A y B" (solo ilustrativo; no recomendado para operar)
* Siempre largo o corto una "posición estándar" (dimensionada por vol).
* Desviación = 1 desv. típica diaria del precio medida en la última entrada.
* Objetivo de beneficio: si el precio avanza **A** desviaciones desde la entrada → invertir
  posición. Stop dinámico: si retrocede **B** desviaciones desde el máximo (mínimo si corto)
  desde la entrada → invertir posición. Recalcular desviación y tamaño en cada inversión.
* "Early profit taker": A = 5, B = 20. "Early loss taker": A = 20, B = 5.

### 2.5 Perfil 1 – Trader semi-automático
* Entradas discrecionales traducidas a forecast discreto: muy fuerte ±20, fuerte ±15,
  normal ±10, débil ±5, neutral 0 (solo positivos si no puede ir corto). **No se cambia el
  forecast** con la operación abierta.
* **Salida única: stop dinámico** a X veces la vol diaria en precio desde el máximo (largo)
  o mínimo (corto) alcanzado desde la entrada; sin objetivos de beneficio.
  X recomendado **4**. Relación X → periodo medio / rotación / coste máx por operación:
  1 → 4 días / 64 / 0.0013 SR; 2 → 9 días / 29 / 0.0027; 3 → 17 días / 15 / 0.0053;
  4 → 6.5 semanas / 8 / 0.01; 8 → 13 semanas / 4 / 0.02; 10 → 26 semanas / 2 / 0.04.
* Vol estimada "a ojo" o con 25 días; se actualiza solo si cambia > 25 %.
* Ejemplo: capital 100k, τ = 15 % (Sharpe supuesto 0.30), spread bets. Puede añadir
  posiciones con nuevas apuestas, nunca promediar pérdidas cambiando el forecast.

### 2.6 Perfil 2 – Inversor asset allocator
* Regla **"no-rule"**: forecast constante **+10** (no se predice nada).
* Cartera de ETFs con pesos por handcrafting (grupos por clase de activo/región) + IDM.
* τ ajustado para alcanzar el apalancamiento deseado (≤ 100 %, ejemplo ~90 % → τ ≈ 7.5 %).
* Rebalanceo con inercia de posición del 10 %, revisión poco frecuente; costes muy bajos.

### 2.7 Perfil 3 – Staunch systems trader (sistema completo de ejemplo)
* Futuros (ejemplo: Eurodólar, US 5y, Euro Stoxx, V2TX, MXP/USD, maíz), 250k USD.
* Reglas: EWMAC 16/64, 32/128, 64/256 + carry. Variantes rápidas solo en instrumentos baratos
  (coste máx por regla = 0.13 SR / rotación).
* Pesos de forecast handcrafted: EWMAC16 **21 %**, EWMAC32 **8 %**, EWMAC64 **21 %**,
  carry **50 %**; **FDM 1.31**.
* τ = 20 % (Sharpe esperado 0.40 tras descontar el backtest); vol EWMA span 36.
* Proceso diario: precios → vol → forecasts → combinación → posición → inercia 10 % → órdenes.

---

## 3. *Leveraged Trading* (LT)

### 3.1 Starter System (un instrumento, binario)
| Componente | Especificación |
|---|---|
| Instrumento | Uno barato (coste ajustado por riesgo bajo) cuyo capital mínimo se cumpla holgadamente (empezar con ≥ 2× el mínimo) |
| Regla de apertura | Cruce de **medias simples** `MAC = SMA16 − SMA64` (diario, cierre). MAC > 0 → largo; < 0 → corto |
| Tamaño | `Exposición nocional = τ × Capital / σ%`, τ = **12 %** (medio Kelly de un Sharpe esperado 0.24) |
| Stop (cierre) | Stop dinámico: `hueco = σ% × precio × 0.5` (fracción de stop **0.5**); largo: máximo cierre desde la apertura − hueco; corto: mínimo + hueco. Se evalúa al cierre diario |
| Reentrada | Tras un stop solo se abre en **sentido contrario** y cuando la regla lo indique; nunca en el mismo sentido de la operación que se acaba de cerrar |
| Frecuencia | ≈ 5.4 operaciones/año; capital en riesgo por operación ≈ τ × fracción = 6 % |
| Rolls | Productos fechados: rolar antes del vencimiento manteniendo la dirección |
* Capital mínimo: `= exposición_mínima × σ% / τ`. Si se cae por debajo, dejar de operar ese
  instrumento o reducir.
* Fracción de stop calibrada a la velocidad de la regla de apertura: reglas más rápidas
  necesitan stops más ajustados (p. ej. ~100 operaciones/año ↔ fracción 0.025).
* Retorno esperado pre-coste ≈ 0.24 × 12 % + tipo de financiación.

### 3.2 Diversificar instrumentos
* Ejecutar el Starter System en varios instrumentos, cada uno con su parte de capital.
* τ por instrumento = τ_cuenta × IDM (ejemplo: 2 clases de activo → IDM 1.2, τ cuenta 13 %,
  τ instrumento 15.6 %). Recomendación: τ de cuenta **≤ 25 %** por muchos instrumentos que haya.
* Capital mínimo ajustado: `nuevo_mínimo = mínimo × (τ_original / τ_nuevo) / peso`.

### 3.3 Nuevas reglas de apertura
* **MAC** variantes 2/8, 4/16, 8/32, 16/64, 32/128, 64/256 (las más rápidas solo si son baratas).
* **Breakout** (rango): `R_max`, `R_min` de los últimos N cierres, `R_avg = (R_max + R_min)/2`,
  `precio_escalado = (P_t − R_avg)/(R_max − R_min) ∈ [−0.5, +0.5]`. Largo si > 0, corto si < 0
  (no espera a romper el rango). N = **10, 20, 40, 80, 160, 320**.
* **Carry**: rendimiento anual esperado de un largo si el subyacente no se mueve.
  * Productos físicos (margen, FX contado): media del carry largo y del corto con signo
    cambiado (excluye el diferencial de financiación, que ya es coste de mantenimiento).
  * Derivados: método 1 vs contrato más cercano; método 2 vs spot; método 3 vs siguiente
    contrato (aproximación). Rotación similar a MAC 16/64.
* Pesos (top-down): **50 % carry, 50 % tendencia**; tendencia = 25 % MAC + 25 % breakout;
  repartir a partes iguales entre las variantes baratas del instrumento (p. ej. 4 MAC → 6.25 %
  cada una; 5 breakouts → 5 % cada una). Sin carry: duplicar los pesos de tendencia.
* Con varias reglas binarias: media ponderada de ±10 de cada regla; operar según el signo.
* Riesgo: más reglas → Sharpe esperado mayor → τ mayor (proporción multiplicativa con la de
  instrumentos; ejemplo 3 instrumentos y 5 reglas → ≈ 18 %). Máximo **30 %**.
* Stop con varias reglas: fracción recalibrada a la rotación media ponderada de las reglas.

### 3.4 Trading continuo (sin stop)
* Abrir en la dirección del forecast combinado; mantener mientras no cambie de signo; al
  cambiar, cerrar y abrir en sentido contrario ("stop and reverse").
* Mejora el Sharpe (≈ 0.24 → 0.27, no significativo; **no** subir τ por ello).
* Mantener el stop si > 50 % del peso está en reglas no tendenciales (carry).

### 3.5 Forecasts continuos y ajuste de posición
```
Exposición ideal = (F/10) × τ × Capital / σ%       F ∈ [−20, +20]
```
Cálculo de forecasts:
* MAC: `raw = (SMA_f − SMA_s) / (σ% × precio)` (vol **anual** en precio); escalar MAC16/64 =
  **57.12**. Resto de pares: tabla de la edición no disponible en la copia epub **(no
  verificado)**; estimarlos con el procedimiento de media |F| = 10 (orden de magnitud: escalar de
  ST × 16, porque LT usa vol anual en vez de diaria).
* Breakout: `F = escalar × precio_escalado`; escalar para N = 320 = **33.5**; resto
  **(no verificado)**, estimar por media |F| = 10.
* Carry: `F = 30 × carry_anual% / σ%`.
* Combinación: media ponderada de forecasts (sin FDM explícito en LT), tope ±20.
* **Ajuste de posición**: `desviación = (ideal − actual) / exposición_media` con
  exposición_media = τ × Capital / σ%. Operar (hasta la ideal) solo si |desviación| ≥ **10 %**.
  Revisar diariamente (cambian σ, F y capital).

### 3.6 Calibración del trader semi-automático (LT cap. 11)
* Ratio de rendimiento = beneficio medio por operación / desviación típica por operación
  (ambos tras costes). Con nº de operaciones → tabla de Sharpe conservador (confianza 75 %,
  máximo 1.0; por defecto 0.24 si hay pocas operaciones).
* `τ_max = Sharpe_conservador / 2`. Presupuesto de costes: `Sharpe_cons/2 − coste_mantenimiento`;
  `operaciones_max/año = presupuesto / coste_por_operación`. Con eso se elige fracción de stop
  y horizonte. Reducir τ si el rendimiento empeora.

---

## 4. *Advanced Futures Trading Strategies* (AFTS)

Supuestos por defecto del libro: τ = 20 %, cartera "Jumbo" de ~100 futuros, vol según §1.3,
posición según §1.4, tope ±20, buffer 10 %. Combinación general recomendada: **60 %
divergente (tendencia) / 40 % convergente (carry, etc.)**.

### Parte 1 – Estrategias direccionales básicas

**E1 – Comprar y mantener 1 contrato.** Un contrato largo, rolando. Sirve para medir las
propiedades del instrumento (rendimiento = spot + carry). Muestra los problemas: riesgo no
controlado y tamaño arbitrario.

**E2 – Comprar y mantener con escalado por riesgo fijo.** `N = Capital × τ / (M × P × fx × σ%)`
con σ% fija (histórica). Fijar τ por el mínimo de margen, apalancamiento prudente, apetito y
medio Kelly. Capital mínimo para 4 contratos. Ratios útiles: apalancamiento = τ / σ%.

**E3 – Comprar y mantener con riesgo variable.** Igual que E2 pero σ% se reestima a diario
(estimador combinado 0.7 EWMA32 + 0.3 media 10 años). Filtro de instrumentos: coste ≤ 0.01 SR
por operación, volumen ≥ 100 contratos/día, riesgo en dólares ≥ 1.5 M$/año, ≥ 4 contratos.

**E4 – Cartera de comprar y mantener con riesgo variable.** Varias subestrategias E3 con pesos
de instrumento `w_i` (Σ = 1) e IDM. Pesos: handcrafting por clase de activo (supuesto de mismo
Sharpe; solo correlación y coste importan). IDM aproximado según nº de instrumentos
(diversificados): 1 → 1.00; 2 → 1.20; 3 → 1.48; 4 → 1.56; 5 → 1.70; 6 → 1.90; 7 → 2.10;
8–14 → 2.20; 15–24 → 2.30; 25–29 → 2.40; ≥ 30 → 2.50. Variantes comentadas: paridad de
riesgo, "All Weather", algoritmo de selección automática de instrumentos según capital.

**E5 – Tendencia lenta, solo largos.** E4 con interruptor: largo (posición de E4) si
`EWMA64(P) > EWMA256(P)`, plano en caso contrario. (Versión con SMA 64/256 equivalente pero
peor.) α ≈ 0.031 y 0.0078.

**E6 – Tendencia lenta, largos y cortos.** Como E5 pero corto con la posición de E4 cuando
`EWMA64 < EWMA256`. Siempre ±posición media.

**E7 – Tendencia lenta con fuerza.**
`F = cap20(1.91 × (EWMA64 − EWMA256) / σ_p)` y la posición usa F (§1.4). Buffer 10 %.

**E8 – Tendencia rápida con fuerza.** EWMAC(16,64), escalar **4.10**, tope ±20, posición
según F, **buffer**: `B = 0.1 × N_media`; operar solo si la posición entera sale de
`[N−B, N+B]` y solo hasta el borde.

**E9 – Varias reglas de tendencia.** EWMAC(2,8)…(64,256). Escalares (precios diarios):
**2 → 12.1; 4 → 8.53; 8 → 5.95; 16 → 4.10; 32 → 2.79; 64 → 1.91** (por el span rápido).
Seleccionar por instrumento las variantes que cumplen el límite de 0.15 SR/año. Pesos iguales
entre las elegidas; FDM: 6 reglas (2…64) 1.26; 5 (4…64) 1.19; 4 (8…64) 1.13; 3 (16…64) 1.08;
2 (32, 64) 1.03; 1 (64) 1.0. Recapar el combinado a ±20.

**E10 – Carry básico.**
```
Si se tiene un contrato no frontal:  carry_bruto = P_más_cercano − P_actual
Si se tiene el frontal:              carry_bruto = P_actual − P_siguiente   (pendiente constante)
años = diferencia de meses entre los dos contratos / 12
carry_anual = carry_bruto / años
raw = carry_anual / (σ_p × 16)             (≈ Sharpe esperado del carry)
F_k = cap20(30 × EWMA_span_k(raw)),  k ∈ {5, 20, 60, 120}
```
Pesos/FDM: 4 variantes 0.25 c/u, FDM 1.04; 3 (20, 60, 120) 1.03; 2 (60, 120) 1.02; solo 120
→ 1.0. Seleccionar por coste. Problemas conocidos: estacionalidad (gas natural, bonos tipo
Bund donde el carry estimado puede tener el signo equivocado, índices por dividendos). Mismo
escalar 30 para todas las clases (para que el carry prometido y el realizado sean comparables).

**E11 – Carry + tendencia.** Combinar E9 y E10: **60 % tendencia, 40 % carry** repartido entre
variantes disponibles (p. ej. 6 EWMAC al 10 % + 4 carry al 10 %; con EWMAC16-64 → 20 % c/u y
carry 13.3 %). FDM aproximado por nº de reglas del instrumento: 1 → 1.0; 2 → 1.02; 3 → 1.03;
4 → 1.23; 5 → 1.25; 6 → 1.27; 7 → 1.29; 8 → 1.32; 9 → 1.34; 10 → 1.35; 11 → 1.36; 12 → 1.38;
13 → 1.39; 14 → 1.41; 15 → 1.42; 16 → 1.44; 17 → 1.46; 18 → 1.48; 19 → 1.50; 20 → 1.53;
21 → 1.54; 22 → 1.55; 25 → 1.69; 30 → 1.81; 35 → 1.93; ≥ 40 → 2.00 (interpolar).
Es la estrategia de referencia para comparar las partes siguientes.

### Parte 2 – Tendencia y carry avanzados (variaciones aplicables a E9–E11)

**E12 – Tendencia ajustada.** Los forecasts extremos de tendencia predicen peor. Sustituye el
tope estándar en algunas variantes:
* EWMAC2, mapeo "doble V": `|F| ≤ 10 → 2F`; `10 < F ≤ 20 → 40 − 2F` (simétrico en negativo);
  `|F| > 20 → 0`.
* EWMAC4 y EWMAC64, "escalar y capar": `F' = clip(1.25·F, −15, +15)`.
* Resto sin cambios. Resultado del libro: apenas mejora (EWMAC2 empeora por costes). Evitar
  ajustes asimétricos o por clase de activo (sobreajuste).

**E13 – Regímenes de volatilidad.** Tendencia y carry funcionan peor con vol alta.
```
V = σ%_actual / media(σ%, últimos 10 años)
Q = percentil de V en su propia historia (0 = mínimo visto, 1 = máximo), sin mirar al futuro
M = EWMA_span10(2 − 1.5·Q)          → ×2 con vol mínima, ×0.5 con vol máxima
F_raw' = F_raw × M  (antes del escalar)
```
Escalares: EWMAC igual; carry **23** en vez de 30. Luego tope y FDM normales. Mejora el
Sharpe de forma consistente; recomendado.

**E14 – Tendencia sobre spot sintético.** Quitar el carry del precio ajustado:
`S_t = S_{t−1} + (P_t − P_{t−1}) − carry_anual_bruto × fracción_de_año` (≈ 1/256 por día),
`S_0 = P_0`. Aplicar EWMAC a S. Pierde rendimiento (sobre todo en reglas lentas); útil solo si
se quiere separar el carry implícito de la tendencia.

**E15 – Carry preciso.** Corrige el sesgo del carry cuando la curva no tiene pendiente
constante: (a) con spot disponible (índices, VIX, FX) usar spot − contrato; (b) si no,
**ajuste estacional**: restar la media estacional del carry (por mes del año) y desplazarla en
el tiempo según el nº de rolls por año (p. ej. 4 rolls ≈ 91 días) para reflejar el carry entre
spot y contrato actual. No aplicar a FX ni metales (sin estacionalidad predecible). Si la
estacionalidad es mala y no hay spot, considerar no operar carry en ese instrumento.

**E16 – Asignación dinámica tendencia/carry.**
```
R_t   = r_tendencia_t − r_carry_t                   (rendimientos diarios % del capital)
RP_t  = Σ_{últimos 256 días} R / τ                  (τ = 20 %)
W_t   = EWMA_span30(clip(0.5 + RP_t/2, 0, 1))       (peso de tendencia; carry = 1 − W)
```
Sustituye el 60/40 fijo. Mejora leve en el backtest; prudente acotar W (p. ej. 20–80 %), con
lo que se acerca a E11.

**E17 – Tendencia normalizada.** Precio normalizado por vol:
`PN_t = PN_{t−1} + 100 × (P_t − P_{t−1}) / σ_p,t`, `PN_0 = 0`. EWMAC sobre PN (normalizando
también por la vol de PN). Mismos escalares que E9, tope ±20, mismas FDM. Complementa a E9.

**E18 – Tendencia por clase de activo.** Índice de clase: `A_t = A_{t−1} + media_i(ΔPN_i,t)`
(media simple de los rendimientos normalizados de los instrumentos de la clase, se pueden
incluir instrumentos no operados). EWMAC sobre A, mismo forecast para todos los instrumentos
de la clase; mismos escalares que E9.

**E19 – Momentum transversal (dentro de la clase).**
```
R_t = PN_t − A_t                                   (precio relativo)
raw_H = EWMA_span(H/4)( (R_t − R_{t−H}) / H )
F = cap20(escalar_H × raw_H)
```
Horizontes y spans: 5 (2), 10 (3), 20 (5), 40 (10), 80 (20), 160 (40). Escalares:
**56.1, 79.0, 108.5, 153.5, 217.1, 296.8**. FDM con pesos iguales: 6 → 1.49; 5 (10…160) → 1.40;
4 (20…160) → 1.30; 3 (40…160) → 1.21; 2 (80, 160) → 1.11. Eliminar los periodos donde el
instrumento es el único de su clase (R = 0).

**E20 – Carry transversal.** `F_i = EWMA_90(raw_carry_i)`; `CS_i = F_i − mediana_clase(F)`;
escalar **50**, tope ±20. Rotación muy baja. Diversifica, pero añade poco.

### Parte 3 – Otras estrategias direccionales

**E21 – Breakout.**
```
raw = 40 × (P_t − (max_N + min_N)/2) / (max_N − min_N)    ∈ [−20, +20]
F   = escalar_N × EWMA_span(N/4)(raw)
```
Máximo/mínimo de cierres de los últimos N días; sin normalizar por vol (el rango ya la
recoge y así se descorrelaciona algo de EWMAC). N = 10, 20, 40, 80, 160, 320. Escalares:
**0.60, 0.67, 0.70, 0.73, 0.74, 0.74** (tope redundante). FDM con pesos iguales:
6 → 1.33; 5 (20…320) → 1.24; 4 (40…320) → 1.17; 3 (80…320) → 1.10; 2 (160, 320) → 1.07.
Libro (Jumbo): breakout SR 1.17, correlación con EWMAC 0.97; añadirlo a carry + tendencia
apenas mejora (SR 1.27 → 1.29). Combinación del libro: 40 % carry, 30 % EWMAC, 30 % breakout.

**E22 – Value (reversión muy lenta).**
```
R_t   = PN_t − A_t                                (como E19)
raw   = −EWMA_30( (R_t − R_{t−256·H}) / (256·H) ), H = 5 años
F     = cap20(7.27 × raw)
```
Rotación ≈ 8.7. Funciona en bonos y acciones, en conjunto débil; pocas pruebas estadísticas.
Convergente (va en el 40 %).

**E23 – Aceleración.** Cambio del forecast de tendencia:
`raw = F_EWMAC(N)_t − F_EWMAC(N)_{t−N}` (forecast ya escalado de EWMAC(N, 4N));
`F = cap20(escalar × raw)`. Variantes N = 8, 16, 32, 64 (2 y 4 demasiado caras). Escalares
**1.87, 1.90, 1.98, 2.05**. FDM: 4 → 1.55; 3 (16…64) → 1.37; 2 (32, 64) → 1.17; 1 → 1.0.
Divergente.

**E24 – Skew (caso de estudio de cómo convertir cualquier variable en forecast).**
`raw = −skew(rendimientos diarios %, ventana w)`, `w ∈ {60, 120, 240}`; suavizar con
EWMA span w/4; escalares **33.3, 37.2, 39.2**; tope ±20 (|skew| > 0.6 ya topa en skew60).
También versión relativa a la clase de activo. Convergente: 20 % del total (mitad del bloque
convergente, la otra mitad para carry). Método general: estimar escalar y rotación sin mirar
rentabilidades, comprobar distribución (sin bimodalidad, media cercana a 0).

**E25 – Optimización dinámica (cuentas pequeñas).** Sustituye el redondeo por instrumento:
1. Calcular posiciones óptimas sin redondear y sin buffer de toda la cartera → pesos
   `w*_i = N_i × M_i × P_i × fx_i / Capital`.
2. Covarianza de rendimientos % (correlaciones × σ).
3. Objetivo: minimizar el error de seguimiento `sqrt((w − w*)ᵀ Σ (w − w*))` +
   **50 × coste total** de las operaciones necesarias (coste por contrato / capital, en peso).
4. **Algoritmo voraz**: partir de 0; en cada iteración probar sumar/restar 1 contrato (en la
   dirección del óptimo) a cada instrumento; aceptar el mejor cambio; parar cuando ninguno
   mejore.
5. **Buffer en error de seguimiento**: `B = 0.05 × τ` (= 1 % con τ = 20 %). Si el error entre
   la cartera actual y la optimizada < B, no operar; si no, operar la fracción
   `(error − B)/error` de las operaciones (redondeado) para quedar en el borde.
6. Opcional: límites de riesgo / posición máxima.

### Parte 4 – Estrategias direccionales rápidas (datos horarios)

**E26 – Reversión a la media rápida.**
* Equilibrio: EWMA **span 5** de los cierres **diarios** (días laborables), usando el último
  cierre disponible (t−1).
* `raw = (equilibrio − P_actual) / σ_p` (σ_p diaria en precio = σ% × precio / 16);
  `F = cap20(9.3 × raw)`.
* **Sin buffer** (siempre se quiere la posición óptima redondeada).
* Ejecución con **órdenes límite**: separar `N = F × N_media/10`; invertir la fórmula para hallar
  el precio al que la posición óptima cambia ±1 contrato:
  `P(N) = equilibrio − N × 10 × σ_p / (9.3 × N_media)` (redondeado al tick). Poner compra
  límite en el precio de `posición_actual + 1` y venta límite en el de `posición_actual − 1`;
  al llenarse una, recolocar ambas. Si el forecast ya está topado (±20), no poner la orden que
  ampliaría la posición. Cancelar las órdenes al cierre (no dejarlas de noche) y recalcular.
* Rotación ≈ 140/año → solo instrumentos muy baratos. Backtest del libro con llenados
  retrasados una vela por prudencia. Sesgo muy negativo; peligroso en crisis.

**E27 – Reversión rápida más segura.**
1. **Filtro de tendencia**: si EWMAC(16,64) tiene signo distinto al forecast de reversión,
   forecast = 0 (comprar caídas en alcista, vender subidas en bajista). Hace de stop loss.
2. **Atenuación por volatilidad**: multiplicador M de E13 (`EWMA10(2 − 1.5·Q)`) aplicado al
   forecast bruto.
3. Escalar **≈ 20** (el filtro anula la estrategia ~mitad del tiempo); tope ±20.
4. Posición y precios límite como en E26 incluyendo M:
   `N = cap20(20 × M × (eq − P)/σ_p) × N_media / 10`.
* Libro (desde 2013, solo comisiones): SR mediano por instrumento ≈ 0.54; cartera Jumbo SR
  2.14 (el autor desconfía de SR > 2: periodo corto y difícil simular límites con datos
  horarios), skew positivo; correlación con tendencia ≈ +0.34. Asignación sugerida **≤ 20 %**
  (mitad del bloque convergente) junto a E11.

### Parte 5 – Valor relativo

**E28 – Spreads entre instrumentos.** Instrumento sintético "R·a / b": largo R unidades de
`a`, corto 1 de `b`.
* Ratio que minimiza el riesgo (simplificado): `R = σ_p,b / σ_p,a` (riesgos diarios en
  precio, ajustando por multiplicador/fx si difieren). Con la correlación: el óptimo exacto
  depende de ρ, pero se usa la razón de volatilidades; se puede fijar a un número redondo.
* Precio del spread: `S_t = R × P_a,t − P_b,t` (en unidades de b); su σ se mide con las
  diferencias diarias de S. `σ_S² = R²σ_a² + σ_b² − 2Rρσ_aσ_b` (riesgo de correlación: si ρ
  baja, el riesgo se dispara).
* Posición: fórmula estándar con σ del spread y **τ = 10 %**; `N_b = −N_spread`,
  `N_a = R × N_spread × (M_b fx_b)/(M_a fx_a)`; ejecutar ambas patas a la vez.
* Reglas: cualquiera basada en precio (EWMAC, breakout, mean reversion...). Carry del spread:
  combinación de los carry de cada pata, exige mismo nº y fecha de rolls.
* Libro (bonos EE. UU.): EWMAC16 en spreads peor que en directos pero diversifica; carry60 en
  spreads ≈ SR 0. Mucho apalancamiento y colas inferiores feas.

**E29 – Triplets (butterflies) entre instrumentos.** "X·a / b / Y·c": corto 1 de b, largo X de
a e Y de c. Si `ρ_ab ≈ ρ_bc`, `X = σ_b/(2σ_a)`, `Y = σ_b/(2σ_c)`. Precio
`T = X·P_a − P_b + Y·P_c`; resto como E28 (τ = 10 %, reglas EWMAC16 y carry60 en el libro).

**E30 – Calendar spreads y triplets.** Igual que E28/E29 pero con vencimientos del mismo
instrumento (a más cercano que b; b más cercano que c). Solo en mercados con varios
vencimientos líquidos (STIR, VIX, energía, agrícolas). Ejemplos: Eurodólar (8.º trimestral y
+6 y +12 meses), WTI (2.º/3.º/4.º mensual), VIX (3.º/4.º). **Rolar todas las patas a la
vez**. Riesgo de correlación y estructura temporal de vol.

### Parte 6 – Tácticas
(Resumen general; no son estrategias con reglas de forecast propias.)
* **T1 Selección de contrato y roll**: contrato con liquidez suficiente; en algunos mercados
  uno fijo (p. ej. crudo diciembre, Eurodólar a ~2–3 años) para carry y liquidez; rolar con
  spread de calendario cuando sea barato; precio ajustado tipo Panamá.
* **T2 Ejecución**: algoritmos sencillos con órdenes límite al mejor lado y paso a mercado si
  no se llena; medir deslizamiento; costes = medio spread + comisión.
* **T3 Caja y capitalización**: margen ≈ 30 % del capital, resto en efectivo; capital de
  referencia actualizado (compuesto o fijo con retiradas).
* **T4 Gestión de riesgo**: controles de riesgo adicionales (límites por instrumento, por
  apalancamiento, por riesgo esperado de cartera con correlaciones de estrés) que solo
  reducen posiciones; vigilar datos erróneos y gaps.

---

## 5. Resumen de escalares de forecast

| Regla | Variante | Escalar | Fuente |
|---|---|---|---|
| EWMAC (span rápido/lento ×4) | 2, 4, 8, 16, 32, 64 | 10.6, 7.5, 5.3, 3.75, 2.65, 1.87 | ST |
| EWMAC | 2, 4, 8, 16, 32, 64 | 12.1, 8.53, 5.95, 4.10, 2.79, 1.91 | AFTS |
| MAC simple (vol anual) | 16/64 | 57.12 (resto no verificado) | LT |
| Carry | todas | 30 | ST, LT, AFTS |
| Carry con multiplicador de vol | todas | 23 | AFTS E13 |
| Carry transversal | span 90 | 50 | AFTS E20 |
| Breakout (40× rango) | 10, 20, 40, 80, 160, 320 | 0.60, 0.67, 0.70, 0.73, 0.74, 0.74 | AFTS |
| Breakout (rango ±0.5) | 320 | 33.5 (resto no verificado) | LT |
| Momentum transversal | 5…160 | 56.1, 79.0, 108.5, 153.5, 217.1, 296.8 | AFTS |
| Value | 5 años | 7.27 | AFTS |
| Aceleración | 8, 16, 32, 64 | 1.87, 1.90, 1.98, 2.05 | AFTS |
| Skew | 60, 120, 240 | 33.3, 37.2, 39.2 | AFTS |
| Mean reversion rápida | span 5 | 9.3 | AFTS E26 |
| Mean reversion segura | span 5 + filtros | ≈ 20 | AFTS E27 |

Los escalares de AFTS y ST difieren algo para EWMAC por distintos datos y estimador de vol;
usar los del libro cuyo estimador de vol se implemente. Para otro universo (p. ej. FX contado)
conviene re-estimarlos: media |F_bruto| agrupada sobre todos los instrumentos → `10 / media`.
