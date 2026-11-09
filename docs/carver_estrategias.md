# Especificaciones de estrategias – *Advanced Futures Trading Strategies* (R. Carver)

Resumen propio (no texto del libro) para implementar backtests. Las fórmulas del libro
son imágenes y no se extraen del PDF; donde un parámetro no se ha podido verificar se indica.

## Estrategia 26 – Fast mean reversion (Part Four)
* Datos horarios; holding de 1–2 días.
* Equilibrio: EWMA span 5 de los cierres **diarios** (índice de días laborables), usando el
  último cierre diario disponible (t−1). Span elegido sin optimizar; otros spans dan resultados similares.
* Forecast: (equilibrio − precio actual) ajustado por riesgo con la vol diaria en precio,
  escalado y con tope ±20. *Escalar 9.3: de memoria, pendiente de verificar (páginas no extraídas).*
* Ejecución: órdenes límite de compra/venta en los precios donde la posición óptima cambia
  ±1 contrato; se recolocan al llenarse. Costes del backtest del libro: solo comisión.
* Backtest del libro: llenados retrasados una vela (1 hora) por prudencia.

## Estrategia 27 – Safer fast mean reversion
* Parte del forecast de la 26 y añade dos cambios:
  1. **Filtro de tendencia**: si EWMAC(16,64) tiene signo distinto al forecast de reversión,
     el forecast se pone a 0 (compra caídas en tendencia alcista, vende subidas en bajista).
     Sustituye al stop loss: la tendencia saca de las posiciones perdedoras.
  2. **Atenuación por volatilidad** (método de la estrategia 13): V = vol % actual / media
     de 10 años; Q = percentil histórico de V (0–1); multiplicador M (de la estrategia 13:
     EWMA₁₀(2 − 1.5·Q), de memoria) aplicado al forecast.
* **Escalar del forecast ≈ 20** (el filtro apaga la estrategia ~la mitad del tiempo), luego tope ±20.
* Posición óptima y precios límite como en la 26, incluyendo M. Resto del plan igual a la 26.
* Resultados del libro (futuros, horario desde 2013, solo comisiones): SR mediano por
  instrumento 0.54 (FX 0.54), skew mensual mediano −0.57; cartera Jumbo SR 2.14
  (el autor advierte que no se fía de SR > 2: periodo corto, dificultad de testear límites con datos horarios).
* Correlación con tendencia ≈ +0.34; asignación sugerida ~20 % del capital junto a estrategias diarias.

## Estrategia 21 – Breakout (Part Three)
* Estrategia diaria de tipo tendencia. Para un horizonte de N días: máximo y mínimo de los
  cierres de los últimos N días; forecast bruto = 40 × (precio − punto medio) / (máx − mín),
  acotado de forma natural en ±20; se suaviza con EWMA de span N/4 (elección arbitraria,
  comprobada como robusta) y se aplica un escalar de forecast (no es 1 porque el precio no
  se distribuye uniformemente dentro del rango). Similar al oscilador estocástico de Lane.
* Seis variantes N = 10, 20, 40, 80, 160, 320 con igual peso; tope ±20; FDM.
* Combinación del libro con carry y EWMAC: 40 % carry, 30 % EWMAC, 30 % breakout.
* Resto del plan igual a la estrategia 9 (sizing por vol, buffer, IDM).
* Libro (Jumbo, futuros): breakout solo SR 1.17; correlación con EWMAC 0.97; añadirlo a
  carry+tendencia mejora poco (SR 1.27 → 1.29).
* Escalares usados (valores publicados por Carver, no verificados en el texto extraído):
  0.60, 0.67, 0.70, 0.73, 0.74, 0.74 para N = 10…320.
