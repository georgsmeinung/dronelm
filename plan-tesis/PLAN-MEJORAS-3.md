# Plan de implementación 3 — Escaneo espacial monocular (inicial y de atasco)

**Fecha:** 2026-09-01
**Origen:** discusión de diseño sobre el orden de deliberación del grafo de control —el VLM
va último por ser el más caro, correctamente— y sobre si conviene una capacidad de análisis
espacial más profunda en dos momentos: al despegar, antes de moverse, y al detectar un
atasco sin solución dentro del lazo táctico.
**Estado de partida:** `PLAN-MEJORAS.md` y `PLAN-MEJORAS-2.md` implementados
(`origin/main` = `bc2a1e2`). `ObstacleField` calibrado (G0), `LOOP_HZ` medido (G1),
derotación validada con caveats (G2), escape sincrónico con enclavamiento y alternancia
vertical/giro (2026-0827), corrida de tesis en preparación (G4).
**Objetivo:** agregar dos capacidades de percepción de mayor alcance —panorama al
despegar y panorama en atasco duro— sin romper la premisa central del proyecto: navegación
**estrictamente monocular**, sin ningún sensor de profundidad, en ninguna fase del vuelo.

---

## 0. Principio rector — exclusión total de profundidad (no negociable)

Esta es la hipótesis que la tesis pone a prueba: **que un VLM pequeño puede mitigar la
ausencia de sensores de rango, no que puede complementarla.** Cualquier lectura de `depth`
en una ruta que decide cómo vuela el dron —en cualquier fase, incluida la planificación—
invalida esa hipótesis, aunque se use en el 1% de los ciclos.

### 0.1 — Alcance de la exclusión

**Excluido, sin excepción:** toda lectura de `capture(return_depth=True)` (o de
`DepthPlanar` por cualquier otra vía) desde:
- el lazo táctico por ciclo (`src/agents/*.py`, `src/perception/*.py`,
  `src/navigation/waypoint_tracker.py`, `main.py`);
- el escaneo espacial inicial (Fase H1 de este plan);
- el escaneo profundo en atasco (Fase H2 de este plan);
- cualquier función invocada desde alguno de los puntos anteriores, directa o
  indirectamente.

"Planificación incluida" quiere decir explícitamente: el escaneo inicial —que ocurre antes
de que el dron se traslade— **no tiene un pase libre** por ocurrir antes del movimiento. Es
parte del vuelo tanto como el lazo táctico, y se diseña con la misma restricción.

### 0.2 — Lo que queda fuera de esta exclusión, y por qué

Dos usos existentes de `depth` en el repo **no** son parte del vuelo y quedan sin cambios:

| Uso | Dónde | Por qué no cuenta |
|---|---|---|
| Ground truth para calibrar el TTC por flujo óptico (F1.3, G0.4, G2.2) | `experiments/collect_ttc_dataset.py`, `experiments/analyze_ttc.py`, `experiments/analyze_occupancy.py` | Corre offline, en scripts separados del grafo. Valida qué tan bien el estimador *monocular* aproxima la realidad; el estimador desplegado nunca lee `depth`. Es instrumentación de laboratorio, no del sistema — el mismo patrón que usar un LIDAR de referencia para calibrar un estimador monocular en un paper, sin volar con el LIDAR. |
| `min_obstacle_dist_m` (G3.1) | `experiments/runner.py:194` | Explícitamente **solo para métricas**, nunca escrito al `DroneState` ni leído por ningún nodo. Es análogo a medir con un GPS de referencia la precisión de una trayectoria, sin usar ese GPS para controlar el vehículo. |

Estos dos usos **no se tocan** en este plan. Pero justamente porque la línea entre
"instrumentación de laboratorio" y "sensor del sistema" es la que hay que proteger, H0
agrega una guardia automática que la hace explícita y verificable — no solo documentada.

### 0.3 — Por qué no hace falta profundidad para lo que se pide

Un detalle técnico que hace que la exclusión sea más limpia de lo que parece, y que conviene
dejar explícito en la tesis: durante un escaneo parado-y-rotando la traslación es ≈0.
`FlowTTCEstimator` (F1.2) necesita expansión/paralaje —desplazamiento hacia la escena— para
producir una señal; girando en el lugar no hay eso, y el estimador ya maneja este caso
devolviendo `foe_confidence = 0` y `TTC = inf` (`src/perception/flow_ttc.py`, rama de "sin
evidencia suficiente"). Es decir: en el instante del escaneo, **ni el propio canal de flujo
monocular tiene nada métrico que ofrecer** — no es que falte un dato que la profundidad
podría rellenar, es que estructuralmente no hay señal de la que extraer nada. La única fuente
de información en ese momento es la lectura semántica del VLM sobre el panorama, y eso es
exactamente lo que se supone que tiene que ser: un juicio cualitativo (despejado / bloqueado
/ sin evidencia), nunca una distancia en metros con precisión inventada.

**El escaneo no necesita certeza métrica porque no decide solo.** El rumbo o macro-acción
que elige se ejecuta bajo el mismo `policy_router` y la misma persistencia de maniobra que
cualquier otra decisión (`src/agents/graph.py:policy_router`): en cuanto el dron retoma
traslación real hacia ese rumbo, el `ObstacleField` por ciclo —monocular, ya calibrado contra
depth *offline* en F1.3/G0.4— vuelve a tener señal y actúa como verificador. Si el VLM se
equivocó, el gatekeeper rápido lo detecta en los primeros ciclos de movimiento real y evade
igual, sin trato especial para las decisiones que vinieron del escaneo. El escaneo elige una
dirección plausible; el lazo monocular de siempre confirma o corrige.

---

## Fase H0 — Guardia arquitectónica de la exclusión

Duración estimada: medio día. Rama sugerida: `guard/no-depth-in-flight`.
**Va primero**, antes de tocar código de las fases H1/H2: la restricción tiene que existir
como test automático antes de que haya código nuevo que pueda violarla por accidente — que
es exactamente lo que casi pasa en esta misma conversación de diseño.

### H0.1 — Test de guardia estático

- **Nuevo:** `tests/test_no_depth_in_flight_path.py`.
- Lista blanca de módulos de vuelo (deben quedar libres de `return_depth=True` y de
  `DepthPlanar`, tanto en código como en comentarios que documenten una llamada real):
  `src/agents/graph.py`, `src/agents/deliberative.py`, `src/agents/evasive.py`,
  `src/agents/fsm.py`, `src/agents/reactive.py`, `src/agents/action_map.py`,
  `src/agents/deliberation_service.py`, `src/perception/flow_ttc.py`,
  `src/perception/obstacle_field.py`, `src/navigation/waypoint_tracker.py`, `main.py`, y
  los módulos nuevos de H1/H2 (`src/agents/spatial_scan.py`, `src/agents/deep_scan.py` o
  como se llamen al implementarse).
- Lista de excepción explícita y documentada (los dos usos de §0.2):
  `experiments/collect_ttc_dataset.py`, `experiments/analyze_ttc.py`,
  `experiments/analyze_occupancy.py`, `experiments/runner.py`.
- El test lee cada archivo de la lista blanca como texto y falla si aparece
  `return_depth=True` (o `return_depth = True`) o `DepthPlanar`. Cualquier módulo de vuelo
  nuevo que se agregue después **debe sumarse a la lista blanca explícitamente** — el test
  falla también si detecta un archivo bajo `src/agents/` o `src/perception/` que no está en
  ninguna de las dos listas, para que no haya forma de agregar un módulo de vuelo nuevo sin
  pasar por esta guardia.

### H0.2 — Segunda red: `DroneState` como lista blanca de por sí

`src/agents/graph.py:54` (`class DroneState(TypedDict, total=False)`) ya documenta la regla
que el propio proyecto aprendió por las malas el 2026-0824: **LangGraph descarta en
silencio cualquier clave que un nodo escriba y no esté declarada en el esquema.** Ese
comportamiento causó el deadlock duro cuando era un bug; acá se usa a favor: mientras
ninguna clave relacionada con profundidad (`depth`, `depth_image`, `min_obstacle_dist_m`, o
similar) se declare en `DroneState`, un nodo que intente escribirla no tiene forma de que
sobreviva a `graph.invoke()` — el framework mismo la tira.

- **Criterio:** no agregar nunca una clave de profundidad a `DroneState`. Documentarlo como
  comentario junto al bloque de claves ya comentado en `graph.py:96-113`, para que quien
  edite el esquema en el futuro vea la razón, no solo la ausencia.

### H0.3 — Verificación

- **Criterio de aceptación de toda la fase:** `pytest tests/test_no_depth_in_flight_path.py`
  pasa contra el estado actual del repo (ya debería, porque hoy no hay ningún uso de depth
  en vuelo — la verificación previa a este plan lo confirmó), y el mismo test debe **fallar**
  si se reintroduce deliberadamente `return_depth=True` en, por ejemplo,
  `src/agents/graph.py`, como prueba de que la guardia realmente detecta la violación.

---

## Fase H1 — Escaneo espacial inicial (pre-vuelo)

Duración estimada: 3–4 días. Rama: `feat/initial-spatial-scan`. Depende de H0.

### H1.1 — Qué es y qué no es

Un barrido de yaw en el lugar (nunca traslación) inmediatamente después del despegue, antes
de que `main.py` entre al `while True` del lazo táctico. Produce un panorama —N imágenes RGB
en N rumbos distintos, mismo punto— y una sola llamada al VLM que devuelve un contexto
cualitativo: qué rumbos parecen despejados, cuál conviene tomar primero, si el plan de
misión (los waypoints cargados) es consistente con lo que se ve.

**Es advisory, no safety-critical.** Sesga el rumbo de arranque y sirve de chequeo de
cordura contra el plan de misión. El `ObstacleField` por ciclo sigue siendo la única
autoridad de seguridad una vez que el dron se mueve — este contexto nunca se usa para
saltarse ni relajar el gatekeeper rápido.

### H1.2 — Implementación

- **Nuevo:** `src/agents/spatial_scan.py` con `run_initial_scan(airsim_client) -> dict`.
- **No es un nodo del `StateGraph`.** Es una función de una sola vez, llamada desde
  `main.py` entre `airsim_client.connect()` (que ya hace el `takeoffAsync`, ver
  `src/hardware/airsim_client.py:131`) y la construcción de `drone_state` / entrada al
  `while True`. Insertarlo como nodo cíclico lo ejecutaría en cada tick, que no es la
  intención.
- **Llamada bloqueante, no vía `DeliberationService`.** El dron está en hover y no hay lazo
  en tiempo real compitiendo todavía — no hace falta el patrón de cola de 1 + watchdog que
  usa la deliberación por ciclo (`src/agents/deliberation_service.py`). Watchdog propio y
  generoso (`INITIAL_SCAN_TIMEOUT_MS`, sugerido 15000): si falla o expira, se registra y la
  misión arranca igual sin contexto inicial — un VLM caído nunca debe impedir el despegue.
- **Barrido:** `SCAN_HEADING_COUNT` rumbos (sugerido 6–8, separados 45–60°), con un breve
  asentamiento en cada uno antes de capturar (evitar motion blur; sin restricción de
  `LOOP_HZ` porque todavía no arrancó el lazo). Reutilizar `airsim_client.capture()`
  **sin** `return_depth` (ver H0).
- **Payload multi-imagen:** mismo mecanismo que ya arma `_query_slm_impl` para
  `frame_history` (`src/agents/deliberative.py:316-322`, el loop que etiqueta
  `[Fotograma t-N]`), pero **con una etiqueta distinta**: `[Rumbo 045°]` en vez de
  `[Fotograma t-N]`, porque el eje no es temporal, es espacial. Reusar la etiqueta de tiempo
  acá sería el mismo error que corrigió F2.1 (afirmarle al modelo un eje que no es el real).
- **Prompt y salida:** system prompt propio (`SYSTEM_PROMPT_SPATIAL_SCAN`), pidiendo un JSON
  con evaluación cualitativa por rumbo (`despejado` / `bloqueado` / `incierto`) y una
  recomendación de rumbo inicial. Sin números de distancia — cualitativo, consistente con
  §0.3.
- **Salida almacenada:** `initial_scene_context` — no forma parte de `DroneState` (no cruza
  la frontera del grafo compilado); vive en `main.py` y se usa para, como mucho, loguearse y
  opcionalmente advertir si contradice el primer tramo del plan de misión (p. ej. rumbo
  recomendado a más de 90° del rumbo al primer waypoint). No se pasa al grafo como sesgo
  numérico de guiado en esta primera versión — mantenerlo como advertencia legible, no como
  parámetro que mueva la cinemática, acota el riesgo de la primera implementación.

### H1.3 — Tests

- **Nuevo:** `tests/test_spatial_scan.py`. Con `AirSimClient` simulado (mismo patrón que
  usan los tests existentes para el modo degradado): verificar que
  1. nunca se llama a `capture` con `return_depth=True`;
  2. las etiquetas de las imágenes enviadas son por rumbo, nunca `t-N`;
  3. un timeout del VLM no bloquea el retorno de la función más allá de
     `INITIAL_SCAN_TIMEOUT_MS`, y la misión puede seguir sin contexto.

### H1.4 — Criterio de aceptación

Un vuelo real muestra en el log el resultado del escaneo inicial antes del primer ciclo del
lazo táctico, sin que `pytest tests/test_no_depth_in_flight_path.py` deje de pasar.

---

## Fase H2 — Escaneo profundo en atasco sin solución

Duración estimada: 1 semana. Rama: `feat/deep-scan-deadlock`. Depende de H0 y H1
(comparte la infraestructura de payload multi-imagen por rumbo).

### H2.1 — Dónde se inserta, exactamente

El punto de inserción es el bloque de escape sincrónico de `deliberative_node`
(`src/agents/deliberative.py:455-536`). Hoy, cuando `stuck_cycles >= stuck_threshold and
not escape_locked and not corridor_open`, el sistema fuerza `GANAR_ALTURA`/`PERDER_ALTURA`
alternado (fix del 2026-0827) **sin consultar nunca al SLM** — el `service.request()` ni
se llama. Es la asimetría que motivó este plan: en el caso que más necesita comprensión
espacial, el sistema cae al comportamiento menos informado.

**El escape sincrónico existente no se borra — se convierte en la red de seguridad final,
sin tocar su lógica.** `MAX_CONSECUTIVE_ESCAPES`, `MAX_ESCAPE_ALT_M`, el enclavamiento
(`_escape_locked`), la alternancia vertical y el giro con `inject_corner` de
`deliberative.py:507-524` siguen exactamente igual. Lo que cambia es que, **antes** de la
primera vez que este bloque forzaría una acción ciega, se intenta un escaneo profundo
acotado.

### H2.2 — Maniobra de escaneo: mismo grafo, mismo loop, sub-estado nuevo

**No es un loop aparte que envuelve o suspende al actual — corre dentro del mismo
`StateGraph`, con el mismo `LOOP_HZ`, el mismo `DroneState`, el mismo `motor_node`.** Es la
razón de fondo por la que H2 (a diferencia de H1) tiene que vivir adentro del grafo: el
lazo siempre pasa por `capture → perception → policy_router` en cada tick
(`src/agents/graph.py`), así que mientras el escaneo profundo gira de rumbo en rumbo,
`perception_node` sigue produciendo un `ObstacleField` real cada ciclo, y el gatekeeper
rápido puede seguir interrumpiendo la maniobra si aparece peligro genuino — la vigilancia
nunca se apaga porque nunca hay un segundo loop bloqueante que la reemplace.

- **Nuevo estado/macro persistente:** `ESCANEO`, siguiendo el mismo patrón que
  `girar_90_node` (`src/agents/graph.py:175-193`): maniobra con `active_maneuver` /
  `maneuver_cycles_left`, interrumpible por la misma persistencia de maniobra de
  `policy_router` (si el TTC se degrada a real peligro mientras se gira, el gatekeeper corta
  igual que con cualquier otra maniobra — no se le da inmunidad).
- **Pero a diferencia de `GIRAR_90` (un solo tramo), `ESCANEO` es multi-fase**: girar a
  rumbo 1 → asentar → capturar → girar a rumbo 2 → ... hasta completar
  `SCAN_HEADING_COUNT_DEEP`, y recién ahí una sola llamada al VLM. El contador plano
  `active_maneuver`/`maneuver_cycles_left` no alcanza para eso solo; hace falta sub-estado
  explícito, declarado en `DroneState` (misma regla de `graph.py:96-113`: toda clave que
  cruza la frontera nodo↔lazo se declara ahí o LangGraph la descarta en silencio — el mismo
  mecanismo que causó el deadlock duro del 2026-0824 si se olvida):
  - `_scan_phase: Optional[str]` — `"rotando" | "asentando" | "capturado" | None`;
  - `_scan_heading_index: int` — cuántos rumbos del barrido ya se completaron;
  - `_scan_frames: List[Any]` — los frames ya capturados en este barrido, para no perderlos
    entre ciclos (cada ciclo del grafo es una invocación nueva de `graph.invoke()`, así que
    lo que no esté en `DroneState` no sobrevive de un tick al siguiente).
- Barrido de `SCAN_HEADING_COUNT_DEEP` rumbos (sugerido 3–4, menor que el escaneo inicial
  para acotar la latencia total: menos rumbos que H1 porque acá el reloj de la misión sí
  corre). Reutiliza `capture()` sin `return_depth` (H0).
- Al completar el barrido, arma **una** llamada profunda vía `DeliberationService`
  (`src/agents/deliberation_service.py`) — sí usa la cola async, a diferencia de H1, porque
  acá el lazo táctico sigue vivo y no puede bloquearse — con:
  - las imágenes del barrido, etiquetadas por rumbo (mismo mecanismo que H1);
  - opcionalmente 1 frame frontal de referencia, etiquetado como "rumbo actual — el que
    viene fallando" (no como `t-0`), para anclar el panorama al punto de atasco;
  - historial textual **ampliado**: `recent_history` completo o una ventana mayor (p. ej.
    últimas 8–10 entradas) en vez del recorte actual `recent_history[-3:]`
    (`src/agents/deliberative.py:169`) — esto es barato (texto, no imagen) y es la parte que
    realmente necesita ser "más larga" para que el modelo sepa qué ya falló;
  - presupuesto de escape ya gastado: `_consecutive_escapes`, altitud actual,
    `MAX_ESCAPE_ALT_M`.
- **Total de imágenes acotado** (≈4–5: 3–4 del barrido + 1 de referencia opcional). Más
  imágenes en un solo prompt degrada a los VLM chicos locales (dilución de atención, peor
  adherencia al esquema JSON) y alarga el prefill — justo lo que no conviene con un watchdog
  ya de por sí más largo.
- **Watchdog propio:** `SLM_DEEP_WATCHDOG_MS` (sugerido 12000 — mayor que
  `SLM_WATCHDOG_MS=6000` de la deliberación de un frame, porque el prefill multi-imagen es
  más lento). Si expira, o si la respuesta no adhiere al formato tras el parser tolerante, o
  si el modelo no da una acción viable: se cae exactamente al bloque de escape sincrónico
  existente, sin cambios — la red de seguridad no se toca.

### H2.3 — Contrato de salida

- **Se mantiene el vocabulario de macro-acciones existente** (`PROMPT_ACTIONS`,
  `src/agents/deliberative.py`), resuelto con el mismo `action_to_command()`
  (`src/agents/action_map.py:40`) que usan todos los demás nodos. No se introduce una
  acción de rumbo arbitrario en este plan — mantiene acotado el radio de cambio.
  *(Nota para más adelante, fuera de alcance acá: el snap a múltiplos de 90°
  —`_manhattan_snap_yaw` en `action_map.py`— tiene sentido en mapas tipo grilla, pero
  `manhattan_a` ya fue descartado y las misiones de tesis usan TownSim/CitySim, que no son
  necesariamente ortogonales. Si el escaneo profundo demuestra valor, una acción de rumbo
  libre sería la extensión natural — pero se evalúa después de tener el ablation de H3.)*
- La macro-acción elegida por el escaneo profundo entra al lazo exactamente como cualquier
  otra: con `active_maneuver`/`maneuver_cycles_left`, sujeta al mismo `policy_router`. No
  hay bypass de seguridad para las decisiones que vienen del escaneo — es la garantía de
  §0.3: el escaneo elige una dirección plausible, el `ObstacleField` monocular de siempre la
  confirma o la corrige en cuanto hay movimiento real.

### H2.4 — Tests

- **Nuevo:** `tests/test_deep_scan.py`:
  1. nunca se llama a `capture` con `return_depth=True` (mismo test que H1.3, reutilizable);
  2. si el escaneo profundo resuelve, el bloque de escape sincrónico existente **no** se
     ejecuta ese ciclo (evita duplicar la acción);
  3. si el escaneo profundo expira o falla, el bloque de escape sincrónico se ejecuta
     exactamente como hoy (regresión de comportamiento — no se puede perder la red de
     seguridad por agregar la capa nueva encima);
  4. el total de imágenes en el payload de la llamada profunda nunca excede el máximo
     configurado;
  5. `_scan_phase`, `_scan_heading_index` y `_scan_frames` sobreviven varias llamadas
     sucesivas a `graph.invoke()` sobre el **grafo compilado** (no al nodo llamado
     directamente como función — ahí es donde el bug de claves no declaradas del 2026-0824
     era invisible a los tests existentes).
- **Regresión explícita sobre el fix del 2026-0824/0827:** correr `test_escape_deadlock.py`
  completo tras integrar H2 — el enclavamiento, el techo de altura y la alternancia
  vertical/giro deben seguir comportándose igual cuando el escaneo profundo no resuelve.

### H2.5 — Criterio de aceptación

Un vuelo real con un atasco genuino (mismo tipo de escenario que produjo el ascenso de 356 m
documentado en el 2026-0824) muestra en `deliberations[]` una entrada de tipo escaneo
profundo antes de, o en lugar de, la entrada de escape sincrónico — y `MAX_ESCAPE_ALT_M`
sigue sin violarse en ningún caso.

---

## Fase H3 — Instrumentación y diseño del ablation

Duración estimada: 3–4 días. Depende de H2. Puede prepararse en paralelo con H2.

### H3.1 — Aplicar el escaneo profundo a los dos brazos, no solo a `slm`

El atasco no es exclusivo del brazo VLM: `fsm.py` tiene el mismo mecanismo raíz de escape
sincrónico (mencionado en `deliberative.py:466`: "mismo fix que fsm.py"). Exponer el
escaneo profundo como una capacidad compartida, seleccionable con
`DEADLOCK_STRATEGY=blind|deep_vlm`, aplicable tanto al brazo `slm` como al `fsm`. Esto
separa dos preguntas que hoy están mezcladas en una sola comparación:

1. ¿Aporta el VLM en el lazo rápido, por ciclo? (`AGENT_ARM=slm` vs `fsm` vs `reactive`,
   ya instrumentado en G4.)
2. ¿Aporta un VLM con visión más amplia para resolver atascos, sobre un escape ciego?
   (`DEADLOCK_STRATEGY=deep_vlm` vs `blind`, nuevo — aplicable a `slm` y a `fsm` por igual.)

Es un diseño factorial 2×2 más limpio que agregar una tercera opción ambigua al `AGENT_ARM`
existente, y responde con más precisión la pregunta abierta de G4.3 ("¿el SLM aporta sobre
la FSM?") separando *dónde* aporta.

### H3.2 — Métricas nuevas en `flight_logger.py`

- Por evento de atasco: `deadlock_strategy` (`blind`/`deep_vlm`), `resolved_by_scan`
  (booleano), `cycles_to_resolve`, `altitude_gained_m`, `fell_back_to_blind` (booleano —
  si el escaneo profundo expiró/falló y se usó la red de seguridad).
- Agregado en `summary.json`: tasa de resolución del escaneo profundo, tiempo medio hasta
  resolver, tasa de caída a la red de seguridad.

### H3.3 — Criterio de aceptación

`experiments/analyze.py` reporta la tabla de resolución de atascos desagregada por
`AGENT_ARM × DEADLOCK_STRATEGY`, con las mismas semillas y escenarios ya definidos para G4.

---

## Fase H4 — Encaje con la tesis

Sin dependencias de código; se puede escribir en paralelo con H1–H3, siguiendo el patrón de
G6.

- **Sección nueva o ampliación de `09-MODOS-DE-FALLA-LLM.md`:** documentar la asimetría
  encontrada (el sistema caía al comportamiento menos informado justo cuando más necesitaba
  comprensión espacial) como un hallazgo de diseño, no solo como una mejora — es del mismo
  género que los otros modos de falla ya documentados (percepción vacía, historial
  inventado, ocupación saturada): un caso más de que la interfaz importa más que el modelo.
- **Vínculo explícito con la hipótesis central de la tesis:** el escaneo inicial y el
  escaneo profundo son la instrumentación directa de "¿puede un VLM chico mitigar la
  ausencia de sensores de rango?" — y la guardia de H0 es lo que hace que esa prueba sea
  válida: sin ella, cualquier resultado positivo sería indistinguible de "el sistema mejoró
  porque le agregamos un sensor por la puerta de atrás".
- **Metodología:** el ablation de H3 (blind vs. deep_vlm, cruzado con slm/fsm/reactive) va
  en la sección de metodología experimental (`10-METODOLOGIA-EXPERIMENTAL.md`) como una
  segunda variable de diseño, con la misma disciplina de "todo umbral sale de una medición"
  ya establecida en `PLAN-MEJORAS-2.md`.

---

## Dependencias y camino crítico

```
H0.1 (test de guardia) ──> H0.2 (DroneState sin claves de depth) ──> H0.3 (verificación)
        │
        v
H1 (escaneo inicial) ──────────────────┐
        │                              │  (comparte payload multi-imagen por rumbo)
        v                              v
H2.1 (punto de inserción) ──> H2.2 (maniobra ESCANEO) ──> H2.3 (contrato de salida)
        │                              │
        v                              v
H2.4 (tests, incl. regresión 2026-0824/0827) ──> H2.5 (criterio de aceptación)
                                        │
                                        v
                                  H3 (ablation blind vs deep_vlm, slm × fsm)
                                        │
                                        v
                                  H4 (escritura) — en paralelo desde el día 1
```

**Camino crítico:** H0 → H1 → H2 → H3.

---

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Alguien reintroduce `return_depth=True` en un módulo de vuelo al implementar H1/H2 (pasó casi literalmente en esta conversación) | Invalida la hipótesis central de la tesis sin que se note en el comportamiento — el dron vuela mejor "por razones equivocadas" | H0 lo convierte en un test que falla en CI, no en una regla que hay que recordar |
| El escaneo profundo (H2) no resuelve nada porque un VLM de 3B no interpreta bien un panorama de rumbos discontinuos | El ablation de H3 da `resolved_by_scan` bajo | Es un resultado válido igual — negativo pero medido, mismo espíritu que G4.3. La red de seguridad (escape ciego) sigue intacta, así que no hay costo de seguridad por el experimento |
| El escaneo (inicial o profundo) tarda tanto que degrada más de lo que ayuda | Tiempo de misión peor que con el escape ciego solo | Watchdogs propios y acotados (H1.2, H2.2); `SCAN_HEADING_COUNT_DEEP` deliberadamente menor que el inicial; H3.2 mide `cycles_to_resolve` para poder comparar el costo real, no solo si resuelve |
| Confundir "instrumentación de laboratorio" con "sensor del sistema" en algún script nuevo de análisis (H3) | Contamina silenciosamente el ablation con información que el dron no tendría en vuelo real | H0.1 mantiene la lista blanca/lista de excepción explícita; cualquier script nuevo de `experiments/` que use depth debe agregarse a la lista de excepción a mano, nunca por omisión |

---

## Lo que no se toca

1. **El escape sincrónico existente** (`deliberative.py:455-536`), con su enclavamiento,
   techo de altura y alternancia vertical/giro del 2026-0827. Es la red de seguridad final;
   H2 se inserta *antes*, nunca lo reemplaza.
2. **`ObstacleField` como único contrato de percepción del lazo por ciclo** y su calibración
   contra depth *offline* (F1.3/G0.4) — eso no es parte del vuelo, sigue como está.
3. **`policy_router` y la persistencia de maniobra.** El escaneo profundo no obtiene
   inmunidad: sus decisiones se ejecutan bajo las mismas reglas que cualquier macro-acción.
4. **`min_obstacle_dist_m` (G3.1)** como métrica de evaluación offline, explícitamente
   fuera del control — sin cambios, y ahora con guardia explícita (H0) en vez de solo
   documental.
