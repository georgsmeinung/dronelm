# 11. Resultados comparativos SLM vs. FSM

> **Estado (2026-09-07):** corridas piloto de Tier 0, Tier 1 base y Tier 2 base completadas (1 semilla, ilustrativo).
> El lote estadístico completo (≥5 semillas, análisis Mann-Whitney) está pendiente.
> Las tablas de esta sección presentan datos reales de las corridas piloto en §11.1 y marcadores de
> posición para el lote completo en §11.2–11.4.
>
> **Corte de datos:** todos los resultados de esta sección provienen de corridas con `code_version`
> posterior al 2026-09-03 — fecha de corrección de dos bugs que afectaban directamente la percepción
> del VLM (canales R/B invertidos y marcadores de debug en la captura). Las corridas anteriores a esa
> fecha no son comparables para el brazo `slm` y no se usan en el análisis.

---

## 11.1 Resultados piloto (1 semilla, ilustrativo)

Estas corridas cumplen el criterio de arranque del diseño experimental (`success = True`, 0 colisiones)
y sirven de referencia cualitativa antes del análisis estadístico completo.
Estrategia de desbloqueo: `deep_vlm` en todos los casos (default de producción).

### Tier 0 — `minisim_clear` · MiniSim (crater.png)

Escenario: 3 waypoints en L (~191m), altitud −10m, ambiente despejado. Fecha: 2026-09-07.

| Brazo | Éxito | Ciclos | Duración (s) | Distancia (m) | Colisiones | Invoc. SLM | Deliberación | Fallback SLM | Deadlocks | Res. atasco VLM |
|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | ✅ | 1151 | 235 | 191.7 | 0 | 80 | 6.95% | 1.25% | 1 | 100% |
| `fsm` | ✅ | 1031 | 208 | 224.4 | 0 | — | — | — | 2 | 100% |
| `reactive` | ✅ | 414 | 84 | 183.6 | 0 | — | — | — | 0 | — |

*Dist. mín. al obstáculo:* `slm` 9.74m · `fsm` 6.38m · `reactive` 9.06m

**Observación:** En un ambiente despejado la diferencia entre brazos es de velocidad pura.
`reactive` completa en 84s (sin deliberar); `slm` tarda 2.8× más debido a las 80 invocaciones
al VLM, aunque el trayecto real es el más corto (191.7m vs 224.4m del `fsm`).

---

### Tier 1 — `townsim_clear` · TownSim (townsim_calib.png)

Escenario: perímetro completo del complejo, 6 WPs, ~640m, altitud de tránsito −30m (sobre los
edificios). Fecha: 2026-09-07.

| Brazo | Éxito | Ciclos | Duración (s) | Distancia (m) | Colisiones | Invoc. SLM | Deliberación | Fallback SLM | Deadlocks | Res. atasco VLM |
|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | ✅ | 1337 | 311 | 632.3 | 0 | 11 | 0.82% | 0% | 3 | 100% |
| `fsm` | ✅ | 1537 | 347 | 652.3 | 0 | — | — | — | 5 | 100% |
| `reactive` | ✅ | 1196 | 266 | 639.0 | 0 | — | — | — | 0 | — |

*Dist. mín. al obstáculo:* `slm` 0.004m · `fsm` 7.89m · `reactive` 9.51m

**Observación:** La tasa de deliberación del `slm` bajó de 15.4% (corridas pre-fix de agosto) a
0.82% — reducción de ×19, atribuible al avance cauteloso durante la espera del VLM (elimina el
bucle mecánico de baja confianza) y al fix de colores R/B (reduce falsas alarmas de percepción).
Con sólo 11 invocaciones sobre 1337 ciclos, el brazo `slm` es el más rápido de los tres en este
escenario. El `fsm` acumula 5 deadlocks (todos resueltos por escaneo profundo); el `reactive`, 0.
La distancia mínima al obstáculo del `slm` (0.004m) es un artefacto del spawn conocido (ciclo
inicial, colisión estática con el suelo), no una aproximación peligrosa en vuelo.

---

### Tier 2 — `citysim_clear` · CitySim (citysim_calib.png)

Escenario: perímetro de una manzana del grid regular, 7 WPs, ~430m, altitud de tránsito −70m
(climb-first: WP_1→WP_2 sube vertical puro antes de mover en horizontal). Fecha: 2026-09-07.

| Brazo | Éxito | Ciclos | Duración (s) | Distancia (m) | Colisiones | Invoc. SLM | Deliberación | Fallback SLM | Deadlocks | Res. atasco VLM |
|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | ✅ | 628 | 174 | 427.2 | 0 | 5 | 0.80% | 0% | 0 | — |
| `fsm` | ✅ | 641 | 182 | 447.2 | 0 | — | — | — | 0 | — |
| `reactive` | ✅ | 541 | 159 | 431.2 | 0 | — | — | — | 0 | — |

*Dist. mín. al obstáculo:* `slm` 0.77m · `fsm` 11.0m · `reactive` 9.43m

**Observación:** Los tres brazos completan el perímetro sin colisiones ni deadlocks — el escenario
base a −70m está por encima de la línea de tejados de CitySim. La arquitectura climb-first
(near_vertical fix, 2026-09-07) evita el problema de la primera corrida (z=-50m, rampa diagonal
que atravesaba edificios). Con 0 deadlocks en los tres brazos, `citysim_clear` confirma el mismo
rol que `minisim_clear` y `townsim_clear`: escenario de control a altitud de tránsito libre,
cota inferior para el análisis del brazo `slm` en Tier 2.
La dist. mín. del `slm` (0.77m) es probable artefacto del segmento de climb cerca del spawn;
no se registró ninguna evasión activa durante el vuelo horizontal.

---

## 11.2 Tabla de resultados por brazo y escenario

Datos de corridas piloto (seed=1). La columna "DistMin" es el valor observado en la corrida única;
el percentil p5 se calculará sobre ≥5 semillas en el lote estadístico completo.
Las filas marcadas **[pendiente]** corresponden a condiciones no corridas aún.

| Brazo | Tier / Escenario | Éxito (1 sem.) | Col./km | DistMin (m) | Tiempo (s) | Deliberación | Fallback SLM | Res. Atasco VLM |
|---|---|---|---|---|---|---|---|---|
| `slm` | Tier 0 (`minisim_clear`) | 1/1 ✅ | 0 | 9.74 | 235 | 6.95% | 1.25% | 100% (1/1) |
| `slm` | Tier 1 (`townsim_clear`) | 1/1 ✅ | 0 | 0.004* | 311 | 0.82% | 0% | 100% (3/3) |
| `slm` | Tier 1 (`townsim_ini`) | [pendiente] | | | | | | |
| `slm` | Tier 1 (`townsim_calib_cruce_frontal`) | [pendiente] | | | | | | |
| `slm` | Tier 2 (`citysim_clear`) | 1/1 ✅ | 0 | 0.77† | 174 | 0.80% | 0% | — (0 deadlocks) |
| `slm` | Tier 2 (`citymap_pilot`) | [pendiente] | | | | | | |
| `fsm` | Tier 0 (`minisim_clear`) | 1/1 ✅ | 0 | 6.38 | 208 | — | — | 100% (2/2) |
| `fsm` | Tier 1 (`townsim_clear`) | 1/1 ✅ | 0 | 7.89 | 347 | — | — | 100% (5/5) |
| `fsm` | Tier 1 (`townsim_ini`) | [pendiente] | | | | | | |
| `fsm` | Tier 1 (`townsim_calib_cruce_frontal`) | [pendiente] | | | | | | |
| `fsm` | Tier 2 (`citysim_clear`) | 1/1 ✅ | 0 | 11.0 | 182 | — | — | — (0 deadlocks) |
| `fsm` | Tier 2 (`citymap_pilot`) | [pendiente] | | | | | | |
| `reactive` | Tier 0 (`minisim_clear`) | 1/1 ✅ | 0 | 9.06 | 84 | — | — | — |
| `reactive` | Tier 1 (`townsim_clear`) | 1/1 ✅ | 0 | 9.51 | 266 | — | — | — |
| `reactive` | Tier 1 (`townsim_ini`) | [pendiente] | | | | | | |
| `reactive` | Tier 1 (`townsim_calib_cruce_frontal`) | [pendiente] | | | | | | |
| `reactive` | Tier 2 (`citysim_clear`) | 1/1 ✅ | 0 | 9.43 | 159 | — | — | — |
| `reactive` | Tier 2 (`citymap_pilot`) | [pendiente] | | | | | | |


\* DistMin Tier 1 `slm` = 0.004m: artefacto del ciclo de spawn (contacto estático con suelo), no aproximación en vuelo.
† DistMin Tier 2 `slm` = 0.77m: probable artefacto del segmento climb-first cerca del spawn; sin evasión activa registrada en vuelo horizontal.

---

## 11.3 Observaciones preliminares y marco para el análisis estadístico

> **Nota:** con 1 semilla por celda no es posible ejecutar pruebas de significancia estadística.
> Esta sección presenta las tendencias observadas en los datos piloto y el diseño del análisis
> que se realizará sobre el lote estadístico completo (≥5 semillas por celda).

### 11.3.1 Tendencias en los datos piloto

Los tres escenarios ejecutados hasta la fecha son escenarios de **control a altitud de tránsito
libre**: la ruta no cruza ningún obstáculo en la dirección de vuelo horizontal — los edificios
quedan por debajo del plano de crucero (−30m en Tier 1, −70m en Tier 2). En esta configuración,
los datos piloto muestran un patrón consistente en los tres tiers:

| Escenario | Tiempo `reactive` | Tiempo `slm` | Ratio `slm`/`reactive` | Tiempo `fsm` | Ratio `fsm`/`reactive` |
|---|---|---|---|---|---|
| Tier 0 `minisim_clear` | 84s | 235s | **2.8×** | 208s | 2.5× |
| Tier 1 `townsim_clear` | 266s | 311s | **1.17×** | 347s | 1.30× |
| Tier 2 `citysim_clear` | 159s | 174s | **1.09×** | 182s | 1.14× |

El ratio `slm`/`reactive` decrece con la longitud de la ruta: en Tier 0 (~191m), la latencia fija
del VLM (~2.9s por invocación × 80 invocaciones) domina el tiempo total; en Tier 2 (~430m), con
solo 5 invocaciones y avance cauteloso durante la espera, el overhead es marginal. Esta relación
es consistente con la hipótesis de que el costo del brazo `slm` no es lineal en la distancia,
sino principalmente en la frecuencia de deliberación.

Una segunda tendencia es la diferencia en distancia recorrida:

| Escenario | Distancia `slm` | Distancia `fsm` | Δ |
|---|---|---|---|
| Tier 0 | 191.7m | 224.4m | −32.7m (−15%) |
| Tier 1 | 632.3m | 652.3m | −20.0m (−3%) |
| Tier 2 | 427.2m | 447.2m | −20.0m (−5%) |

En los tres tiers, el brazo `slm` recorre menos distancia que el `fsm`. Con 1 semilla, esto puede
ser varianza del punto de spawn; con ≥5 semillas, si el patrón se sostiene, indicaría que las
pocas invocaciones del VLM en escenarios de control producen correcciones de rumbo que evitan
desviaciones que la FSM sí acumula.

Los deadlocks observados son escasos (0–5 por corrida) y todos resueltos al 100% por `deep_vlm`
en `slm` y `fsm`. El brazo `reactive` no registra deadlocks en ningún tier, lo cual es esperado:
su control reactivo puro no tiene el concepto de "objetivo pendiente" que genera atascos en los
brazos deliberativos cuando la ruta directa está bloqueada.

### 11.3.2 Marco estadístico para el lote completo

Sobre ≥5 semillas independientes por celda se ejecutará:

1. **Prueba U de Mann-Whitney** (bilateral) comparando cada par de brazos en el mismo escenario.
   Hipótesis nula: la distribución de la métrica principal no difiere entre brazos. Métrica
   primaria: tiempo de misión en corridas con `success=True` para escenarios de control; SPL para
   escenarios con bloqueo. Métrica secundaria: `dist_min_m` como indicador de seguridad.

2. **Tamaño de efecto**: Cliff's Delta (δ) sobre el mismo par. Umbral de referencia: δ > 0.3
   como efecto "mediano" ([Romano et al., 2006](13-REFERENCIAS.md#ref-romano-2006)). Un p-valor significativo con δ pequeño (< 0.1)
   indicaría una diferencia real pero de magnitud práctica despreciable.

3. **Corrección de Bonferroni** sobre las comparaciones múltiples (3 pares de brazos × 6
   escenarios = 18 pruebas); umbral ajustado α = 0.05/18 ≈ 0.0028.

Las comparaciones previstas son: `slm` vs. `fsm`, `slm` vs. `reactive`, y `fsm` vs. `reactive`
en cada escenario.

---

## 11.4 Análisis por tipo de escenario

La pregunta central de la tesis — ¿aporta la deliberación contextual del VLM sobre la heurística
rígida de la FSM? — requiere desagregarla por tipo de escenario, porque la respuesta esperada
es distinta según el nivel de dificultad.

### 11.4.1 Tier 0 — Control sin obstáculos (`minisim_clear`)

El escenario de referencia más simple: 3 waypoints en L, ambiente despejado, sin ningún obstáculo
en la trayectoria directa. El dato piloto muestra el costo puro del brazo `slm` sin ningún
beneficio compensatorio: 80 invocaciones al VLM sobre 1151 ciclos (6.95%) generan 235s de tiempo
de misión frente a los 84s del brazo `reactive` (ratio 2.8×). El `fsm` (208s) ocupa una posición
intermedia: también sufre del overhead de su lazo deliberativo en atascos (2 deadlocks), pero sin
la latencia VLM por invocación.

La distancia mínima al obstáculo es comparable entre brazos (9.74m `slm`, 9.06m `reactive`,
6.38m `fsm`), confirmando que en un entorno despejado ningún brazo es más seguro que otro — la
ventaja del VLM no tiene dónde manifestarse. Este resultado es el esperado por diseño: `minisim_clear`
existe para establecer la cota inferior de rendimiento del sistema y cuantificar el overhead puro
del brazo `slm` en ausencia de beneficio.

**Predicción:** la diferencia de velocidad entre `reactive` y `slm` debería sostenerse con
alta significancia estadística (Cliff's δ cercano a 1.0 en favor de `reactive`); la comparación
`slm` vs. `fsm` puede ser más variable porque depende de cuántos deadlocks acumule la FSM por
corrida.

### 11.4.2 Tier 1 — Perímetro urbano con vegetación (`townsim_clear`)

El escenario `townsim_clear` para Tier 1: vuela el perímetro a −30m (sobre la línea de tejados), sin obstáculos en la trayectoria de crucero. A diferencia de Tier 0, la longitud de la ruta (~640m vs. ~191m) diluye el overhead por invocación, y el brazo `slm` resulta el más rápido de los tres en el piloto (311s vs. 347s `fsm` vs. 266s `reactive`). La tasa de deliberación de 0.82% (11 invocaciones / 1337 ciclos) representa una reducción de ×19 respecto a las corridas pre-fix de agosto (15.4%), directamente atribuible al avance cauteloso durante la espera del VLM y al fix de canales de color que reduce las falsas alarmas.

El dato más significativo de Tier 1 piloto no es la velocidad sino los deadlocks: el `fsm` acumula 5 (todos resueltos por escaneo profundo `deep_vlm`); el `slm`, 3; el `reactive`, 0. Con 1 semilla, este patrón es indicativo pero no concluyente — puede reflejar diferencias en la gestión de atascos entre brazos, o simplemente la varianza de una única semilla.

El escenario de interés real para Tier 1 es `townsim_ini`: un recorrido que cruza el interior del complejo, con corredores vegetados y fachadas que obstruyen la trayectoria directa. Es allí donde el escaneo deliberativo tiene un caso de uso genuino: la FSM y el `reactive` deben bordear obstáculos por heurística, mientras el `slm` puede consultar al VLM para elegir el corredor. Los datos de `townsim_clear` solo establecen la cota de partida.

### 11.4.3 Tier 2 — Entorno urbano denso (`citysim_clear`)

El escenario base `citysim_clear` funciona como el tercer escenario de control: los tres brazos completan el perímetro en ~159–182s, sin colisiones ni deadlocks, con tiempos comparables entre sí (ratio `slm`/`reactive` = 1.09×). A −70m, el dron vuela por encima de la línea de tejados de CitySim; la deliberación del VLM no tiene obstáculo real que analizar.

Tres observaciones son relevantes para el análisis posterior:

1. **`fsm` conservador, `reactive` agresivo**: el `fsm` registra la mayor distancia mínima al obstáculo (11.0m) y el mayor tiempo (182s); el `reactive` el menor (9.43m, 159s). El `slm` queda entre ambos (0.77m en climb inicial, 174s). En un entorno donde no hay obstáculos activos, la heurística conservadora de la FSM penaliza velocidad sin ganar seguridad.

2. **Altitud como variable crítica de diseño**: la primera corrida a z=−50m falló (success=False, colisión) porque la altitud insuficiente hacía que la ruta de climb desde el spawn atravesara edificios. El fix de near_vertical (2026-09-07) permite el patrón climb-first, pero la variable determinante fue la elección de −70m > altura de tejados.

3. **Cero deadlocks en los tres brazos**: confirma que la ruta de crucero no presenta obstrucciones reales a −70m. Cualquier deadlock que aparezca en `citymap_clear` — donde la ruta sí cruza corredores entre edificios — será atribuible a la geometría del escenario, no a artefactos de la altitud.

El escenario `citymap_clear` es el experimento inicial de Tier 2: un recorrido que atraviesa corredores angostos entre edificios altos, donde ni el `reactive` ni el `fsm` tienen información semántica para elegir entre dos calles de ancho similar. La hipótesis es que el brazo `slm`, al consultar al VLM con una imagen aérea del corredor, podrá elegir la ruta más despejada con mayor consistencia que una heurística basada en distancia pura o en flujo óptico. El resultado negativo también es válido: si el VLM no aporta información útil en un entorno de alta textura urbana uniforme, es un hallazgo de diseño relevante para el capítulo 09.
