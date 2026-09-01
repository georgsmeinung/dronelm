# Plan de pruebas base — TownSim (mapa `townsim_calib.png`)

**Fecha:** 2026-09-01
**Origen:** el Tier 1 actual (`townsim_a.json`/`townsim_pilot.json`/`townsim_demo.json`) usa
`townsim.png`. Existe un mapa más nuevo, `townsim_calib.png`, y ya hay una corrida manual
exitosa sobre él (`TOWNSIM_CALIB_0`, ver §1.2) que sirve de punto de partida geométrico
confiable. Este documento define la batería de escenarios de prueba que debería reemplazar/
complementar al Tier 1 sobre ese mapa.
**Estado de partida:** `PLAN-MEJORAS.md`, `PLAN-MEJORAS-2.md` y `PLAN-MEJORAS-3.md`
implementados (H0–H3: guardia de no-profundidad, escaneo inicial, escaneo profundo en atasco,
`DEADLOCK_STRATEGY=blind|deep_vlm`). Este plan es el escenario que le falta al diseño
experimental del capítulo 10 (`informe/10-METODOLOGIA-EXPERIMENTAL.md`): *"un tercer escenario,
aún por definir, con un bloqueo frontal masivo genuino"*.
**Objetivo:** una batería de misiones sobre `townsim_calib.png`, con geometría derivada de datos
ya volados (no de una lectura de píxeles no verificada), que cubra crucero de control, elección
de corredor y bloqueo frontal masivo — y que sea directamente utilizable en el batch de G4 y en
el ablation `AGENT_ARM × DEADLOCK_STRATEGY` de H3.

---

## 0. Principio rector — no inventar geometría no verificada

Este mapa no tiene un archivo de calibración píxel↔metro confiable (no hay escala conocida ni
puntos de referencia georreferenciados documentados). Medir la imagen a ojo y convertirlo en
coordenadas de vuelo sería fabricar precisión que no existe — el mismo tipo de error que este
proyecto ya evitó en otros frentes ("todo umbral sale de una medición", `PLAN-MEJORAS-2.md`).

Por eso, la regla de este plan es:

1. **Toda coordenada nueva se deriva por interpolación de coordenadas YA VOLADAS y confirmadas**
   (`TOWNSIM_CALIB_0`, §1.2), nunca de una posición estimada directamente sobre el PNG.
2. La imagen (`townsim_calib.png`) se usa **solo cualitativamente**: para describir la
   disposición relativa de la plaza, los tres bloques de edificios, el corredor central y la
   avenida — nunca para derivar una distancia en metros.
3. **Ninguna misión nueva de este plan se considera "confiable" hasta pasar el protocolo de
   validación de §5** (`scripts/plot_mission_route.py` + corrida piloto de una sola semilla).
   Es la misma disciplina que ya sigue el proyecto para este mapa (`townsim_demo.json`: *"cada
   tramo confirmado visualmente en el viewport de UE antes de darlo por bueno"*).
4. **Sin teletransporte.** `main.py` no aplica `start_pose` (a propósito: el dron siempre
   arranca en el *PlayerStart* del nivel de UE, nunca en una pose inyectada por
   `simSetVehiclePose`). Toda misión de este plan tiene que ser alcanzable por VUELO REAL desde
   ese punto de partida fijo — nunca asumir que el dron puede "aparecer" en un punto lejano.
   Un escenario que necesita empezar lejos del spawn se arma como una misión de varios tramos:
   un tramo de tránsito a altitud segura (`z=-30`, ya validada por `TOWNSIM_CALIB_0`) hasta el
   punto de interés, y recién ahí el tramo de prueba real a nivel de calle. (Descubierto al
   volar T-CALIB-2 con un `set_vehicle_pose` agregado por error a `main.py`: cambio revertido
   de inmediato.)

---

## 1. Lo que ya sabemos

### 1.1 — Geometría cualitativa del mapa (`townsim_calib.png`, 2000×2000px)

De norte a sur: una plaza con rotonda/jardín circular, y luego tres bloques rectangulares de
edificios en fila, cada uno separado del siguiente por una calle transversal. Cada bloque tiene
dos filas de edificios (oeste y este) con un pasaje peatonal central entre ambas. Una avenida
ancha sale hacia el este, aproximadamente a la altura del límite entre la plaza y el primer
bloque. Todo el complejo está rodeado de bosque denso; hay un cuerpo de agua al sur, fuera del
complejo.

### 1.2 — La corrida ya volada: `TOWNSIM_CALIB_0`

`airsim-plan/missions/flightplans/townsim_calib_0.json` (mismo contenido que
`TOWNSIM_CALIB_0.preloop.json`) ya se voló manualmente dos veces; la corrida más reciente
(`airsim-plan/runs/manual/TOWNSIM_CALIB_0_20260901T001142Z.summary.json`) terminó **exitosa,
sin colisiones**: 656.35m, 1748 ciclos, 361.92s, brazo `slm`, `deliberation_rate=15.4%`.
Histograma de rutas: `reactive` 77%, `deliberative` 16%, `evasive` 6%, `girar_90` 0.2%.

```
WP_1: (0.0,    0.4,  -10)
WP_2: (0.4,  -71.6,  -30)
WP_3: (-145.2, -70.8, -30)
WP_4: (-146.8,  83.6, -30)
WP_5: (1.2,    84.8, -30)
WP_6: (0.0,   27.2,    0)   -- aterrizaje
```

**Lectura de esta geometría** (deducida de los propios tramos volados, no de la imagen):

- WP_1 y WP_6 comparten `x≈0`: ese es el eje del **corredor central** del complejo.
- WP_2/WP_3 comparten `y≈-71` (borde sur) y WP_4/WP_5 comparten `y≈84` (borde norte): el
  complejo mide **≈156m de norte a sur**.
- WP_3/WP_4 comparten `x≈-146` (borde oeste): el complejo mide **≈146m de ancho** desde el
  corredor central hasta el borde oeste exterior.
- El tramo WP_1→WP_2 vuela **derecho sobre el corredor central**, ganando altitud hasta -30m
  (por encima del nivel de los edificios) — es la razón por la que esta corrida es 77%
  `reactive`: a esa altura, el dron sobrevuela los tres bloques en vez de negociarlos. **Es un
  buen escenario de control/crucero largo, pero no ejercita evasión real.**
- Centroide del complejo: `x≈-73`, `y≈6.5`.
- Con los tres bloques repartidos en tercios sobre el rango norte-sur (`y∈[-71,84]`, 156m/3 ≈
  52m por bloque), los límites entre bloques quedarían aproximadamente en `y≈-19` y `y≈32`.
  **Esta subdivisión en tercios es una aproximación, no una medición — se marca como
  PROVISORIA en cada escenario que la usa, sujeta a confirmación por §5.**

---

## 2. Batería de escenarios propuestos

| ID | Rol | Origen de las coordenadas | Distancia aprox. | Altitud |
|---|---|---|---|---|
| **T-CALIB-0** `perimetro` | Control / smoke-test de crucero largo (YA EXISTE Y VALIDADO) | Volado (`townsim_calib_0.json`) | 656m | -10/-30 (mixta, según WP) |
| **T-CALIB-1** `pilot` | Smoke-test rápido | Subconjunto volado (WP_1→WP_2) | ~72m | -10→-30 |
| **T-CALIB-2** `cruce_frontal` | Bloqueo frontal masivo genuino (llena el hueco del cap. 10) | Interpolado sobre el borde oeste volado | ~320m (con tránsito, sin teletransporte) | -30 tránsito / -10 cruce |
| **T-CALIB-3** `eleccion_corredor` | Elección lateral real (EVADIR_IZQUIERDA/DERECHA) | Interpolado + límite de bloque PROVISORIO | ~320m (con tránsito) | -30 tránsito / -10 cruce |
| **T-CALIB-4** `avenida_abierta` | Control / cota inferior sin obstáculos | Extrapolado desde la salida de la avenida | ~370m (provisorio, con tránsito) | -30 tránsito / -10 cruce |
| **T-CALIB-5** `atasco_duro` | Bloqueo doble, diseñado para H2/H3 (`DEADLOCK_STRATEGY`) | Interpolado, cruza el bloque de lado a lado | ~470m (con tránsito) | -30 tránsito / -10 cruce |

### T-CALIB-0 — `perimetro` (ya existe, ya validado)

Sin cambios: `airsim-plan/missions/flightplans/townsim_calib_0.json`. Falta correrlo con los
tres brazos (`slm`/`fsm`/`reactive`) y 5 semillas para integrarlo al batch de G4 — hoy solo hay
una corrida manual (`slm`, seed 0).

### T-CALIB-1 — `pilot`

Reusa exactamente WP_1 y WP_2 del manifiesto ya volado, sin inventar nada:

```json
{
  "mission_id": "TOWNSIM_CALIB_PILOT",
  "start_pose": { "x": 0.0, "y": 0.4, "z": -10.0, "yaw_deg": 0.0 },
  "waypoints": [
    { "x": 0.4, "y": -71.6, "z": -30.0, "label": "WP_1" }
  ],
  "map": "townsim_calib.png"
}
```

Rol: chequeo de humo de ~1 minuto antes de correr cualquier batch sobre este mapa (mismo
patrón que `townsim_pilot.json` sobre `townsim.png`).

### T-CALIB-2 — `cruce_frontal` (bloqueo frontal masivo)

**v2 (sin teletransporte, ver §0.4):** sale del spawn real (coincide con `x≈0, y≈0.4`, el
mismo punto que `WP_1` de `TOWNSIM_CALIB_0`), transita a altitud segura hasta el borde oeste,
desciende fuera del complejo, y recién ahí cruza de lleno la fila de edificios **oeste** del
bloque a nivel de calle — forzando la elección entre `GANAR_ALTURA` (sobrevolar el edificio) o
un corredor lateral.

```json
{
  "mission_id": "TOWNSIM_CALIB_CRUCE_FRONTAL",
  "waypoints": [
    { "x": -150.0, "y": 0.4, "z": -30.0, "label": "WP_1" },
    { "x": -150.0, "y": 0.4, "z": -10.0, "label": "WP_2" },
    { "x": 0.0, "y": 0.4, "z": -10.0, "label": "WP_3" }
  ],
  "map": "townsim_calib.png"
}
```

- `y=0.4`: mismo `y` que el spawn/`WP_1` de `TOWNSIM_CALIB_0` — no hace falta desviarse en `y`.
- `WP_1` (`x=-150, z=-30`): tránsito de ida a la altitud ya validada por el perímetro completo
  (`TOWNSIM_CALIB_0` voló a esa altura sin incidentes).
- `WP_2` (mismo `x`, `z=-10`): desciende ya fuera del complejo, en el bosque abierto.
- `WP_3` (`x=0`, `z=-10`): cruce real a nivel de calle, de vuelta hacia el eje del corredor
  central — este es el único tramo sin verificar, y el que efectivamente prueba el escenario.

### T-CALIB-3 — `eleccion_corredor`

**v2 (sin teletransporte):** mismo patrón de tránsito que T-CALIB-2 (ida a `z=-30`, descenso
fuera del complejo, cruce real a `z=-10`), pero alineado con el límite PROVISORIO entre bloque 1
y bloque 2 (`y≈32`, ver §1.2), para que el frente quede bloqueado por la esquina de un edificio
con una calle transversal visible al costado — la elección debería ser lateral
(`EVADIR_IZQUIERDA`/`EVADIR_DERECHA`), no vertical.

```json
{
  "mission_id": "TOWNSIM_CALIB_ELECCION_CORREDOR",
  "waypoints": [
    { "x": -150.0, "y": 32.0, "z": -30.0, "label": "WP_1" },
    { "x": -150.0, "y": 32.0, "z": -10.0, "label": "WP_2" },
    { "x": 0.0, "y": 32.0, "z": -10.0, "label": "WP_3" }
  ],
  "map": "townsim_calib.png"
}
```

`y=32` es la subdivisión en tercios de §1.2 — **marcada PROVISORIA**: si al validar con
`plot_mission_route.py` la línea no cae cerca de un límite de bloque real, ajustar `y` antes de
usar este escenario en un batch.

### T-CALIB-4 — `avenida_abierta` (control, cota inferior)

**v2 (sin teletransporte):** primero sube en el eje del spawn (`x=0`) hasta la altura `y` donde
sale la avenida, desciende ahí (terreno abierto, calle ancha), y recién ahí vuela hacia el este.
Tramo largo sin obstáculos aparentes — mide el costo fijo de cada brazo (`slm`/`fsm`/`reactive`)
cuando no hay nada que negociar.

```json
{
  "mission_id": "TOWNSIM_CALIB_AVENIDA_ABIERTA",
  "waypoints": [
    { "x": 0.0, "y": 50.0, "z": -30.0, "label": "WP_1" },
    { "x": 0.0, "y": 50.0, "z": -10.0, "label": "WP_2" },
    { "x": 300.0, "y": 50.0, "z": -10.0, "label": "WP_3" }
  ],
  "map": "townsim_calib.png"
}
```

- `y=50`: aproximado, cerca de donde la avenida sale hacia el este (entre el borde norte del
  complejo y el centroide). **PROVISORIO.**
- `x=300` (WP_3): distancia arbitraria "larga" — la extensión real de la avenida despejada
  **no está verificada**. Recortar tras la inspección visual de §5 si termina antes.

### T-CALIB-5 — `atasco_duro` (para H2/H3)

**v2 (sin teletransporte):** mismo patrón de tránsito, pero el tramo final cruza el bloque de
lado a lado (fachada oeste → corredor → fachada este) en vez de detenerse en el corredor,
maximizando la probabilidad de un atasco genuino con reintentos de escape. Es el escenario
candidato para el ablation `AGENT_ARM × DEADLOCK_STRATEGY` de H3 (`PLAN-MEJORAS-3.md`).

```json
{
  "mission_id": "TOWNSIM_CALIB_ATASCO_DURO",
  "waypoints": [
    { "x": -150.0, "y": 0.4, "z": -30.0, "label": "WP_1" },
    { "x": -150.0, "y": 0.4, "z": -10.0, "label": "WP_2" },
    { "x": 150.0, "y": 0.4, "z": -10.0, "label": "WP_3" }
  ],
  "map": "townsim_calib.png"
}
```

`x=150` (WP_3) al este del corredor asume una fila de edificios simétrica a la oeste (no
verificado por datos volados, solo por lectura cualitativa de la imagen) — confirmar en §5 antes
de depender de este escenario para el ablation.

---

## 3. Presupuestos, semillas y brazos

| Escenario | Distancia aprox. (v2, sin teletransporte) | `--max-seconds` | `--max-cycles` (5Hz) | Semillas | Brazos |
|---|---|---|---|---|---|
| T-CALIB-0 `perimetro` | 656m | 480 | 2400 | 1–5 | slm, fsm, reactive |
| T-CALIB-1 `pilot` | ~75m | 120 | 600 | 1–2 | slm |
| T-CALIB-2 `cruce_frontal` | ~320m | 420 | 2100 | 1–5 | slm, fsm, reactive |
| T-CALIB-3 `eleccion_corredor` | ~320m | 420 | 2100 | 1–5 | slm, fsm, reactive |
| T-CALIB-4 `avenida_abierta` | ~370m | 480 | 2400 | 1–5 | slm, fsm, reactive |
| T-CALIB-5 `atasco_duro` | ~470m | 600 | 3000 | 1–5 | slm, fsm × `blind`/`deep_vlm` (`reactive` no delibera, se excluye de la segunda variable) |

Presupuestos calculados con margen ≥2.5× sobre la velocidad de crucero real medida en
`TOWNSIM_CALIB_0` (656m/349.6s de vuelo ≈ 1.9 m/s), no sobre la velocidad de crucero nominal
(`REACTIVE_FORWARD_SPEED=5.0`) — la nominal sobreestima el avance real una vez que se descuentan
frenadas, deliberación y maniobras. T-CALIB-2/3/5 llevan margen extra por el freno propio del
escaneo profundo (H2) cuando `DEADLOCK_STRATEGY=deep_vlm`.

---

## 4. Integración con G4 y H3

- **G4** (`G4_THESIS_RUN.md`): T-CALIB-0 reemplaza/complementa a `townsim_a.json` como
  escenario Tier 1 sobre el mapa nuevo. T-CALIB-2/3 son los candidatos directos para el
  "tercer escenario con bloqueo frontal masivo" que pide `10-METODOLOGIA-EXPERIMENTAL.md §10.1`.
- **H3** (`PLAN-MEJORAS-3.md`): T-CALIB-5 es el escenario pensado para el factorial
  `AGENT_ARM × DEADLOCK_STRATEGY` — correrlo vía `experiments/runner.py --deadlock-strategies
  blind deep_vlm`, y leer la tabla nueva de `experiments/analyze.py` (tasa de resolución del
  escaneo profundo, ciclos promedio a resolución, tasa de fallback al escape ciego).
- Ningún escenario de este plan reintroduce profundidad: todos usan waypoints/altitud, no
  sensores adicionales — la guardia H0 (`tests/test_no_depth_in_flight_path.py`) sigue siendo
  la garantía automática de eso, no depende de este documento.

---

## 5. Protocolo de validación (obligatorio antes de un batch)

Por cada escenario NUEVO (T-CALIB-1 a T-CALIB-5), en este orden:

1. Redactar el manifiesto en `airsim-plan/missions/`.
2. `python scripts/plot_mission_route.py airsim-plan/missions/<archivo>.json` — confirmar a
   simple vista en el viewport de UE que la línea dibujada cruza donde el escenario pretende
   (fachada de edificio para T-CALIB-2/3/5, calle abierta para T-CALIB-4). Ajustar coordenadas
   si no coincide — son PROVISORIAS por diseño (§0).
3. Corrida piloto de **una sola combinación** (`slm`, 1 semilla) y verificar que complete la
   misión (`success=True`) o que, si no la completa, el motivo sea instructivo (atasco real,
   no un error de geometría tipo "arrancar dentro de un edificio"). Es el mismo criterio de
   arranque que ya usa el capítulo 10: *"si ninguna combinación puede tener éxito, no tiene
   sentido ejecutar el resto"*.
4. Recién ahí, correr el batch completo de la tabla de §3.

---

## 6. Qué no incluye este plan

1. **No genera los archivos `.json` de misión todavía** — este documento los deja
   especificados (§2) para que se creen a pedido, después de revisarlos.
2. **No corrige `townsim_a.json`/`townsim_pilot.json`/`townsim_demo.json`** (mapa
   `townsim.png`): quedan como están, este plan es exclusivamente para `townsim_calib.png`.
3. **No mide la escala real del PNG en metros/píxel** — deliberado (§0): sin un punto de
   calibración confiable, cualquier número así sería fabricado. Si en el futuro aparece un
   archivo de calibración georreferenciado del proyecto UE, este plan debería revisarse con esa
   fuente en vez de con interpolación de vuelos.
