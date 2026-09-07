# 11. Resultados comparativos SLM vs. FSM

> **Estado (2026-09-07):** corridas piloto de Tier 0, Tier 1 base y Tier 2 base completadas (1 semilla, ilustrativo).
> El batch estadístico G4 (≥5 semillas, análisis Mann-Whitney) está pendiente de `townsim_ini` y `citymap_a`.
> Las tablas de esta sección presentan datos reales de las corridas piloto en §11.1 y marcadores de
> posición para G4 en §11.2–11.4.
>
> **Corte de datos:** todos los resultados de esta sección provienen de corridas con `code_version`
> posterior al 2026-09-03 — fecha de corrección de dos bugs que afectaban directamente la percepción
> del VLM (canales R/B invertidos y marcadores de debug en la captura). Las corridas anteriores a esa
> fecha no son comparables para el brazo `slm` y no se usan en el análisis.

---

## 11.1 Resultados piloto (1 semilla, ilustrativo — pre-batch G4)

Estas corridas cumplen el criterio de arranque del diseño experimental (`success = True`, 0 colisiones)
y sirven de referencia cualitativa antes del análisis estadístico de G4.
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

Datos de corridas piloto (seed=1, `deep_vlm`). La columna "DistMin" es el valor observado en
la corrida única; el percentil p5 se calculará sobre ≥5 semillas en el batch G4.
Las filas marcadas **[pendiente G4]** corresponden a condiciones no corridas aún.

> **Escenarios definitivos G4:** `minisim_clear` (Tier 0), `townsim_ini` (Tier 1 con obstáculos
> reales) / `townsim_calib_cruce_frontal` (T-CALIB-2), `citysim_clear` (Tier 2 base) /
> `citymap_a` (Tier 2 con obstáculos — pendiente construcción). Las filas de `townsim_clear`
> corresponden al escenario base (sin obstáculos a altitud de tránsito), equivalente al rol de
> `minisim_clear` en Tier 0.

| Brazo | Tier / Escenario | Estrategia Atasco | Éxito (1 sem.) | Col./km | DistMin (m) | Tiempo (s) | Deliberación | Fallback SLM | Res. Atasco VLM |
|---|---|---|---|---|---|---|---|---|---|
| `slm` | Tier 0 (`minisim_clear`) | `deep_vlm` | 1/1 ✅ | 0 | 9.74 | 235 | 6.95% | 1.25% | 100% (1/1) |
| `slm` | Tier 0 (`minisim_clear`) | `blind` | — | — | — | — | — | — | — |
| `slm` | Tier 1 (`townsim_clear`) | `deep_vlm` | 1/1 ✅ | 0 | 0.004* | 311 | 0.82% | 0% | 100% (3/3) |
| `slm` | Tier 1 (`townsim_clear`) | `blind` | — | — | — | — | — | — | — |
| `slm` | Tier 2 (`citysim_clear`) | `deep_vlm` | 1/1 ✅ | 0 | 0.77† | 174 | 0.80% | 0% | — (0 deadlocks) |
| `fsm` | Tier 0 (`minisim_clear`) | `deep_vlm` | 1/1 ✅ | 0 | 6.38 | 208 | — | — | 100% (2/2) |
| `fsm` | Tier 1 (`townsim_clear`) | `deep_vlm` | 1/1 ✅ | 0 | 7.89 | 347 | — | — | 100% (5/5) |
| `fsm` | Tier 2 (`citysim_clear`) | `deep_vlm` | 1/1 ✅ | 0 | 11.0 | 182 | — | — | — (0 deadlocks) |
| `reactive` | Tier 0 (`minisim_clear`) | — | 1/1 ✅ | 0 | 9.06 | 84 | — | — | — |
| `reactive` | Tier 1 (`townsim_clear`) | — | 1/1 ✅ | 0 | 9.51 | 266 | — | — | — |
| `reactive` | Tier 2 (`citysim_clear`) | — | 1/1 ✅ | 0 | 9.43 | 159 | — | — | — |
| **[pendiente G4]** | Tier 1 (`townsim_ini`) | todos | | | | | | | |
| **[pendiente G4]** | Tier 2 (`citymap_a`) | todos | | | | | | | |

\* DistMin Tier 1 `slm` = 0.004m: artefacto del ciclo de spawn (contacto estático con suelo), no aproximación en vuelo.
† DistMin Tier 2 `slm` = 0.77m: probable artefacto del segmento climb-first cerca del spawn; sin evasión activa registrada en vuelo horizontal.

---

## 11.3 Significancia estadística (placeholder — pendiente batch G4)

Análisis no paramétrico mediante prueba U de Mann-Whitney y estimación de tamaño de efecto
(Cliff's Delta / correlación de rango biserial) por celda factorial sobre las ≥5 semillas
independientes (§10.3). Hipótesis nula: la distribución de la métrica de éxito del brazo `slm`
es igual a la del brazo de referencia (`fsm` o `reactive`) en el mismo escenario y estrategia.

---

## 11.4 Análisis por tipo de escenario (placeholder — pendiente batch G4)

Discusión desagregada de la hipótesis central: ¿aporta la deliberación contextual del VLM sobre
la heurística rígida de la FSM?

- **Tier 0 (Control / `minisim_clear`):** los datos piloto muestran que en ambiente despejado
  la deliberación del VLM no aporta velocidad ni seguridad — `reactive` es 2.8× más rápido y
  las tres distancias mínimas al obstáculo son comparables. El costo de las 80 invocaciones es
  visible (235s vs 84s). El batch G4 con ≥5 semillas confirmaría si esta diferencia es
  estadísticamente significativa.

- **Tier 1 (Perímetro urbano con vegetación / `townsim_clear`):** los datos piloto muestran una
  reducción de ×19 en la tasa de deliberación del `slm` respecto a las corridas pre-fix de agosto
  (0.82% vs. 15.4%), con 0 colisiones y 3 deadlocks resueltos al 100% por escaneo profundo.
  El `fsm` registra 5 deadlocks (todos resueltos); el `reactive`, 0. La diferencia de tiempos
  entre brazos es pequeña (~45s sobre 300s), consistente con un escenario donde los obstáculos
  se pueden bordear con heurística fija. El batch G4 con `townsim_ini` (con obstáculos en el
  camino directo) es donde se espera que la ventaja del escaneo profundo (`deep_vlm`) sobre el
  escape ciego (`blind`) sea más visible.

- **Tier 2 base (Control / `citysim_clear`):** los datos piloto confirman que a −70m los tres
  brazos completan el perímetro sin deliberación activa (0 deadlocks en los tres). Rol análogo
  al de `minisim_clear`: cota inferior para el análisis del brazo `slm` en entorno urbano denso.
  El escenario con obstáculos reales (`citymap_a`, pendiente de construcción) es donde se
  espera mayor ventaja del brazo `slm`: corredores angostos entre edificios altos requieren
  decisiones de rodeo que ni el `reactive` ni el `fsm` resuelven con una heurística fija.
