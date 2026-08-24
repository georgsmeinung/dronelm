# Plan de implementación — Reconstrucción del lazo táctico (`airsim-loop`)

**Fecha:** 2026-08-24
**Origen:** revisión crítica del lazo táctico, README, CHANGELOG y plan de tesis.
**Objetivo:** llevar el piloto de "arquitectura correcta con percepción vacía" a "lazo demostrable con
resultados medibles", sin perder las fortalezas ya construidas (deliberación por excepción,
auditabilidad, `WaypointTracker`).

---

## 0. Criterio de orden

El plan está ordenado **por dependencia, no por importancia**. Cada fase produce un artefacto
verificable y deja el repo en estado volable.

| Fase | Qué desbloquea | Estado final |
|---|---|---|
| **F0** Desbloquear el lazo | Todo lo demás. Hoy el `join()` fija el período del ciclo en 2 s. | Lazo a 5–10 Hz, una sola llamada al SLM, un solo cliente, código = diagrama. |
| **F1** Contrato de percepción | El router, el evasive, el prompt y la futura FSM. | `ObstacleField` producido por un nodo y consumido por todos; TTC validado contra depth. |
| **F2** Deliberación honesta | La comparabilidad SLM vs FSM. | Prompt sobre datos reales, decodificación restringida, cinemática con una sola fuente de verdad. |
| **F3** Instrumentación experimental | Los resultados de la tesis. | Brazo FSM, runner batch, JSONL, métricas, tests de seguridad. |
| **F4** Cierre documental | La defensa. | README/diagramas sincronizados, código muerto en `legacy/`. |

**Regla transversal:** ningún umbral nuevo se elige a mano. Todo umbral que llegue a `main` sale de
la curva ROC de F1.3 o de una medición registrada en el CHANGELOG.

---

## Fase 0 — Desbloquear el lazo

Duración estimada: 3–5 días. Rama sugerida: `fix/loop-unblock`.

### F0.0 — Medir el techo real de captura *(hacer primero: todo el presupuesto temporal depende de esto)*

- **Nuevo:** `airsim-loop/scripts/bench_capture.py`.
- Mide, sobre la conexión real Mac → Windows (`AIRSIM_IP=192.168.110.110`), el tiempo de
  `simGetImages` y `getMultirotorState` para: 1080×720 / 640×480 / 320×240, con y sin
  `DepthPlanar`, 200 muestras cada combinación. El timing ya está instrumentado en
  `airsim_client.capture()`.
- **Salida:** tabla p50/p95 por combinación → se elige `LOOP_HZ` y la resolución del pipeline de
  percepción con evidencia, no por default.
- **Criterio de aceptación:** existe una tabla en el CHANGELOG con la frecuencia máxima sostenible.
  Si la red topea en ~5 Hz, se acepta 5 Hz y se re-escalan los umbrales en consecuencia; no se
  fuerza un número que el enlace no soporta.

### F0.1 — Actuador no bloqueante

- **Archivo:** `src/hardware/airsim_client.py` → `execute_velocity()` (≈ líneas 262–303).
- Eliminar `self._last_move_future.join()`. `moveByVelocityBodyFrameAsync` es *last-command-wins*:
  refrescar el comando cada ciclo con `duration = k / LOOP_HZ` (k ≈ 2–3) da continuidad sin
  bloquear, y permite abortar una maniobra en curso simplemente emitiendo otra.
- Reemplazar la rama de comando nulo: hoy hace `hoverAsync().join()` (bloqueante). Usar
  `cancelLastTask()` + `moveByVelocityBodyFrameAsync(0,0,0, duration=1.0/LOOP_HZ*k)`.
- Conservar `_last_move_future` solo para `cancelLastTask()` en el apagado.
- **Criterio:** `execute_velocity` devuelve en < 10 ms p95 (medir con el logger de F3.2).

### F0.2 — Una sola ruta hacia el SLM

- **Archivo:** `src/agents/graph.py`.
- Quitar `return blind_wall_router_node(state)` del final de `hover_before_slm_node` (línea ≈184).
  `hover_before_slm_node` pasa a hacer **solo** freno + actualización de percepción.
- Convertir `blind_wall_router` de **nodo** a **función de ruteo** en una `add_conditional_edges`,
  con dos destinos reales: nodo `girar_90` (bypass determinista) y nodo `deliberative`.
  Esto además hace que el grafo coincida con `informe/2006-0823 Nuevo Grafo de Control.mmd`.
- **Criterio:** un ciclo con FOV no bloqueado produce **exactamente una** entrada nueva en
  `deliberations[]`. Test: `test_graph_single_deliberation.py` (F3.4).

### F0.3 — Cliente AirSim único (inyección de dependencia)

- **Archivo:** `src/agents/graph.py` → `_build_nodes()`, `build_workflow()`, `get_airsim_client()`.
- `_build_nodes(client)` y `build_workflow(client)` reciben el cliente ya conectado.
  `compile_workflow(client)` idem. `main.py` crea **el** `AirSimClient`, hace `connect()` una vez y
  lo inyecta.
- Deprecar `get_airsim_client()` (hoy reconstruye el grafo entero y dispara un segundo
  `takeoffAsync().join()`). Dejar un shim que emita `DeprecationWarning` durante una release.
- **Criterio:** un solo `confirmConnection` y un solo `takeoffAsync` por misión, verificable en el log.

### F0.4 — Cablear (o retirar) el `xor_router`

- **Archivo:** `src/agents/graph.py` línea ≈352.
- Reemplazar `add_edge("canny_xor_gate", "optical_flow")` por
  `add_conditional_edges("canny_xor_gate", xor_router, {...})`.
- **Pero** instrumentar antes: registrar el histograma de `xor_change_ratio` durante una misión
  completa a la frecuencia nueva. Con el dron en movimiento a 5–10 Hz el ratio probablemente
  supere siempre `0.02–0.03` y el gate nunca dispare.
  - Si dispara con frecuencia útil → se cablea y se recalibra el umbral con el percentil medido.
  - Si nunca dispara → **se elimina** el nodo, el router y su mención en README/`.mmd`, y se
    documenta como resultado medido ("el gating por bordes no aporta a esta velocidad de vuelo").
- **Criterio:** código, README y `.mmd` dicen lo mismo, y el CHANGELOG registra la medición que
  justificó la decisión.

### F0.5 — Frecuencia de control y SLM asíncrono

- **Nuevo:** `src/agents/deliberation_service.py`.
- `DeliberationService`: hilo worker + cola de tamaño 1. API:
  - `request(context)` → encola (descarta pedido previo pendiente),
  - `poll()` → `(decision | None, age_ms, pending)`.
- `deliberative_node` deja de bloquear: al entrar, emite el comando de freno, encola el pedido y
  devuelve `FRENAR`; en ciclos siguientes hace `poll()`. Esto **preserva** la semántica de seguridad
  actual ("frenar antes de deliberar") pero deja el lazo de percepción corriendo mientras el SLM piensa.
- **Watchdog:** `SLM_WATCHDOG_MS` (default sugerido: 1500). Si el pedido excede ese tiempo, gana la
  política reactiva/fallback y el pedido se marca `timeout` en `deliberations[]` (métrica reportable).
- `LOOP_HZ` pasa al valor elegido en F0.0. Re-escalar en `.env` y documentar:
  - `TTC_EVASION_THRESHOLD`, `TTC_SAFE_THRESHOLD` — **quedan pendientes de F1.3**; hasta entonces se
    marcan explícitamente como provisorios en `.env`.
  - `WAYPOINT_ACCEPTANCE_RADIUS = 3.5 m` deja de ser problemático (pasos de ~0.5 m a 10 Hz).
  - `maneuver_cycles_left`: los valores actuales (5, 8, 15) están en unidades de ciclo. Convertirlos
    a **segundos** (`MANEUVER_DURATION_S`) y derivar los ciclos de `LOOP_HZ`, para que un cambio de
    frecuencia no altere el comportamiento táctico.
- **Criterio:** el período p95 del ciclo ≤ 1.2 × (1/`LOOP_HZ`) durante una misión completa, incluidos
  los ciclos con deliberación.

### F0.6 — Los datos simulados dejan de enmascarar fallos

- **Archivo:** `src/hardware/airsim_client.py` (`_simulated_frame`, `_simulated_depth`), `main.py`.
- Agregar `AIRSIM_STRICT` (default `true` en vuelo): con AirSim caído, `capture()` **no** devuelve un
  frame sintético; devuelve `None` + `source="unavailable"`.
- `main.py` ya hace esto bien para telemetría; extenderlo a imagen: si `source != "airsim"`, comandar
  hover, marcar el ciclo como degradado en el log y no ejecutar percepción ni deliberación.
- Los frames sintéticos quedan disponibles solo para tests (`AIRSIM_STRICT=false`).
- **Criterio:** con el simulador apagado el lazo hovering + warning; no "vuela" sobre datos ficticios.

---

## Fase 1 — Reconstruir el contrato de percepción

Duración estimada: 2–3 semanas. Rama: `feat/obstacle-field`.
**Es la fase crítica.** Todo lo demás depende de que exista un descriptor de escena real.

### F1.1 — `ObstacleField`: el único contrato

- **Nuevo:** `src/perception/obstacle_field.py`.

```python
SECTORS = ("izquierda", "centro", "derecha")
BANDS   = ("superior", "medio", "inferior")

@dataclass(frozen=True)
class Cell:
    sector: str          # izquierda | centro | derecha
    band: str            # superior | medio | inferior
    occupancy: float     # [0,1] fracción de la celda con evidencia de obstáculo
    ttc_s: float         # segundos (inf si no hay evidencia de aproximación)
    divergence: float    # 1/s, tasa de expansión medida del campo traslacional
    confidence: float    # [0,1] fracción de píxeles válidos de la celda

@dataclass(frozen=True)
class ObstacleField:
    cells: dict[tuple[str, str], Cell]
    dt_s: float
    timestamp: float
    source: str          # "flow" | "depth" | "degraded"
    foe: tuple[float, float] | None
    foe_confidence: float

    # ---- API de consumo (única superficie pública) ----
    def sector_ttc(self, sector: str) -> float: ...          # mínimo robusto de la columna
    def sector_occupancy(self, sector: str) -> float: ...     # máximo ponderado por confianza
    def is_blocked(self, sector: str) -> bool: ...            # umbrales calibrados en F1.3
    def blocked_fraction(self) -> float: ...                  # reemplaza occlusion_ratio
    def min_ttc(self) -> float: ...
    def summary_text(self) -> str: ...                        # única fuente del prompt
    def to_dict(self) -> dict: ...                            # única fuente del JSONL
```

- **Un solo productor:** `perception_node` (fusiona los actuales `optical_flow_node`,
  `ipm_segmentation_node` y `ttc_estimate_node` en un nodo).
- **Consumidores** (todos leen la misma API, ninguno accede a campos crudos): `ttc_router`,
  `evasive_node`, `deliberative` (prompt), `fsm_node` (F3.1), `flight_logger` (F3.2), `main.py` (display).
- **Eliminar `detected_obstacles` de `DroneState`.** Para no romper WebDCS/`stream_hub`, exponer
  `ObstacleField.to_dict()` en el payload y actualizar `main.py::_print_state` y el consumidor web.
- **Instanciación única:** los estimadores se crean **una vez** en `_build_nodes()`, no por frame
  (hoy `OpticalFlowEstimator()` e `IPMSegmentator()` se instancian dentro del nodo cada ciclo).

### F1.2 — TTC correcto: derotación → FOE → TTC en segundos

**Nuevo:** `src/perception/flow_ttc.py`. Sustituye `1/mean(|flow|)`.

1. **`dt` real.** Tomar `telemetry["timestamp"]` del frame actual y del anterior. Nunca asumir el
   período nominal.

2. **Compensación de ego-rotación** *(la corrección que explica el "vuelo cortado y errático" del
   CHANGELOG 0820: hoy cada giro de yaw desploma el TTC espuriamente).*
   Para rotación pequeña `(Δθx, Δθy, Δθz)` entre frames, obtenida de la telemetría de actitud
   (pitch/roll/yaw ya están en `_state_to_telemetry`), el flujo inducido en el píxel `(x, y)`
   relativo al punto principal, con focal `f`:

   ```
   u_rot = (Δθx · x·y / f) − Δθy · (f + x²/f) + Δθz · y
   v_rot =  Δθx · (f + y²/f) − Δθy · x·y / f − Δθz · x
   ```

   Flujo traslacional: `v_trans = v_medido − v_rot`.
   *Validación cruzada:* estimar además la homografía/afín global entre frames
   (`cv2.estimateAffinePartial2D` sobre features ralos) y comparar con la predicción de telemetría.
   Divergencia sostenida entre ambas ⇒ telemetría de actitud desincronizada del frame.

3. **FOE por mínimos cuadrados.** Con flujo puramente traslacional, todo vector apunta desde el FOE.
   Para cada píxel `p_i` con flujo `v_i`, el FOE está sobre la recta `p_i + λ·v_i`. Sea `n_i ⟂ v̂_i`:

   ```
   FOE = argmin Σ w_i · (n_i · (FOE − p_i))²      →  sistema lineal 2×2
   w_i = |v_i| · confidence_i
   ```

   Con RANSAC para robustez. Si `‖v_traslacional‖` está bajo el piso de ruido (dron en hover o giro
   puro), el FOE es indefinido: `foe_confidence = 0` y `ttc = inf` en todas las celdas.
   Esto elimina el stub `_calc_foe()` que devuelve el centro geométrico.

4. **TTC por píxel, en segundos:**

   ```
   TTC_i = ‖p_i − FOE‖ · dt / ‖v_trans_i‖
   ```

   Agregación por celda: percentil 20 sobre los píxeles con `‖v‖` por encima del piso de ruido.
   `confidence` = fracción de píxeles válidos. **Sin clamp cosmético** `[0.1, 10.0]`: el valor sale
   como `inf` cuando no hay evidencia, y la confianza dice cuánto vale.

5. **Divergencia** `∇·v_trans` (Sobel sobre las componentes del flujo), agregada por celda. Para un
   plano fronto-paralelo `∇·v ≈ 2/TTC`; sirve de verificación independiente del punto 4.

6. **Algoritmo de flujo.** A 10 Hz y 5 m/s el desplazamiento entre frames vuelve al rango de
   captura (a 0.5 Hz eran ~10 m: ruido, no señal). Default sugerido `cv2.DISOpticalFlow`
   (`PRESET_MEDIUM`) sobre imagen reducida (320×240), con Farnebäck como alternativa. **Medir ambos**
   en el mismo dataset de F1.3 y reportar latencia/precisión: es una tabla de tesis.

### F1.3 — Validación contra depth *(esto es un capítulo, no una tarea)*

`capture(return_depth=True)` ya devuelve `DepthPlanar` en metros: hay ground truth gratis.

- **Nuevo:** `experiments/collect_ttc_dataset.py` y `experiments/analyze_ttc.py` (notebook o script).
- **Ground truth por celda:**

  ```
  TTC_gt(celda) = percentil20(Z_celda) / max(v_closing, ε)
  ```

  con `v_closing` = componente de la velocidad del cuerpo (telemetría) sobre el eje óptico.
- **Dataset:** ~3 vuelos scripteados cubriendo (a) aproximación frontal a edificio, (b) vuelo por
  cañón urbano recto, (c) giros de yaw sin aproximación *(el caso que hoy dispara frenos falsos)*.
  Registrar por ciclo y por celda: `ttc_est, ttc_gt, divergence, occupancy, confidence, dt, speed,
  yaw_rate, algoritmo_de_flujo`.
- **Análisis:**
  - dispersión `ttc_est` vs `ttc_gt`, correlación y error relativo;
  - error estratificado por velocidad y por `|yaw_rate|` — **demuestra si la derotación funciona**;
  - ROC del evento binario "colisión dentro de τ s" para τ ∈ {1, 2, 3};
  - elección de `TTC_EVASION_THRESHOLD` y `TTC_SAFE_THRESHOLD` por índice de Youden o por una tasa
    de falsos positivos objetivo, con AUC reportado.
- **Salida:** los umbrales mágicos de `.env` pasan a ser parámetros justificados, y queda una figura
  y una tabla directamente publicables.

### F1.4 — Decisión sobre el IPM: **retirarlo**

**Recomendación: retirar, no reparar.** Justificación técnica (a documentar en la tesis):

- El IPM asume un plano de suelo dominante en el FOV. Con cámara frontal a ~10 m de altura en cañón
  urbano el suelo ocupa una fracción marginal de la imagen: la hipótesis no se cumple.
- La implementación actual no es un IPM en ningún caso: con `R = I` la homografía se reduce a
  `diag(fx/(1+h), fy/(1+h), 1)` — un escalado dependiente de la altitud, sin pitch, roll ni altura de
  cámara respecto al plano. Y aplicar **la misma H a ambos frames** convierte
  `absdiff(ipm_cur, ipm_prev)` en un frame-difference bajo ego-movimiento: todo borde texturado se
  marca como obstáculo. Ese es el `occlusion_ratio` que hoy dispara `GIRAR_90`.
- El costo tampoco cierra: bucle Python sobre `np.unique(segments)` (~200 iteraciones/frame) y un
  fallback k-means con k=200 sobre la imagen completa cuando falta scikit-image.

**Reemplazo:** flujo denso + FOE + TTC por celda (F1.2) + clustering DBSCAN sobre `(x, y, 1/TTC)` para
obtener blobs de obstáculo. `occlusion_ratio` → `ObstacleField.blocked_fraction()`, calibrado contra
depth en F1.3 (fracción de celdas con `occupancy > θ_occ` y `ttc < τ`). La semántica del bypass
`GIRAR_90` se conserva; solo cambia la métrica que lo dispara.

`ipm_segmentator.py` va a `legacy/` en F4, con la evidencia medida como justificación.

> **Alternativa considerada y rechazada:** implementar el IPM de verdad (H del plano de suelo con
> pitch/roll/altura de telemetría, K real de AirSim, compensación de ego-movimiento warpeando t-1
> hacia t, SLIC sobre la imagen original y grafo geodésico). Es correcto pero resuelve un problema
> que este caso de uso no tiene, y agrega el costo del grafo geodésico. Se documenta como decisión,
> no como omisión.

---

## Fase 2 — Deliberación honesta

Duración estimada: 1–2 semanas. Rama: `feat/honest-deliberation`. Depende de F1.

### F2.1 — `frame_history` real, o etiquetas fuera

- **Archivo:** `src/agents/graph.py` (`capture_node`), `src/agents/deliberative.py`.
- Hoy `frame_history` y `annotated_image` **nunca se pueblan**: el VLM recibe 1 frame y el prompt lo
  etiqueta `[Fotograma t-3]`, `[Fotograma t-2]`… Se le está afirmando al modelo una historia que no existe.
- Implementar un ring buffer real (`collections.deque(maxlen=VLM_FRAME_HISTORY_SIZE)`) con frames ya
  reducidos a `VLM_IMAGE_MAX_SIZE` para no inflar memoria.
- Con `VLM_FRAME_HISTORY_SIZE = 1` (valor actual del `.env`): **quitar las etiquetas temporales** del
  prompt. La condición de invariante: la cantidad de etiquetas siempre es igual a la cantidad de
  imágenes efectivamente enviadas. Test en F3.4.

### F2.2 — Prompt sobre el `ObstacleField` real + memoria corta

- `_summarize_sectors()` se elimina; el resumen sale de `ObstacleField.summary_text()`, con números
  reales por sector (`ocupación`, `TTC`, `confianza`).
- Agregar memoria corta: últimas N decisiones con su **resultado medido** (Δdistancia al waypoint,
  Δmin-TTC). Sin esto el modelo re-decide en el vacío y oscila.
- Corregir el mensaje inconsistente del override: el log dice "Estructura a menos de 5.5m" con
  `SAFE_MARGIN_METERS = 1.0` (`deliberative.py`, override de seguridad). Usar la variable.
- El override anti-`MANTENER_RUMBO` (hoy muerto porque depende de `detected_obstacles`) se reescribe
  sobre `field.is_blocked("centro")` y vuelve a estar vivo.
- `_fallback_decision()` se reescribe sobre `ObstacleField` (hoy con lista vacía devuelve
  `MANTENER_RUMBO`: empuja hacia adelante contra el obstáculo).

### F2.3 — Decodificación restringida

- Reemplazar el parser por regex como camino principal: usar
  `response_format={"type": "json_schema", ...}` (soportado por LM Studio y Ollama; ya hay un
  documento propio sobre esto en `informe/Optimización de Modelos mediante Decodificación Restringida.md`).
- **Conservar** `_parse_decision()` como red de seguridad — está bien escrito y es la evidencia del
  antes/después.
- **Métrica reportable:** `adherence_rate` = fracción de respuestas parseables al primer intento,
  con y sin decodificación restringida. Es una tabla de resultados directa.

### F2.4 — Una sola fuente de verdad para la cinemática

- Hoy `ACTION_VELOCITY_MAP` es casi decorativo: `GANAR_ALTURA` define `vx=0.0, vy=0.5` y quince líneas
  después el nodo lo pisa con `vx=1.0, vy=0.0`.
- **Nuevo:** `src/agents/action_map.py` con
  `action_to_command(action, guidance, telemetry, field) -> dict`, usado **por igual** por
  `deliberative`, `evasive`, `fsm` (F3.1) y `reactive`. Se eliminan todas las asignaciones
  `decision["vx"] = ...` posteriores en `deliberative_node`.
- **Criterio:** ninguna macro-acción tiene dos definiciones cinemáticas en el repo (test en F3.4).

### F2.5 — `evasion_stuck_cycles` mide progreso de verdad

- El comentario dice "sin reducir distancia al waypoint"; el código solo cuenta ciclos en rutas
  `evasive`/`deliberative`. Un desvío Manhattan largo y **correcto** se clasifica como atasco y
  dispara `GANAR_ALTURA`.
- Mover la lógica a `WaypointTracker.progress_stall_cycles`: incrementar solo si
  `dist_actual > min_dist_vista − PROGRESS_EPS` durante K ciclos consecutivos. Reset ante progreso real.

### F2.6 — Pregunta abierta a responder con datos (no antes)

¿El VLM aporta sobre la política determinista? Con F3 armado, la respuesta puede ser *"no en el caso
frontal masivo, sí en la elección de calle transversal"* — y **eso es un resultado publicable, no un
fracaso**. Diseñar el análisis de F3.3 para poder responderlo por tipo de escenario, no en agregado.

---

## Fase 3 — Instrumentación experimental

Duración estimada: 2–3 semanas. Rama: `feat/experiments`. Depende de F1; F2 puede correr en paralelo.

> Sin esta fase no hay resultados que reportar, independientemente de qué tan bien vuele el dron.
> El objetivo específico aprobado exige comparar **SLM vs FSM** en tasa de éxito, tiempo de reacción y
> consumo computacional, y hoy no existe ni la FSM, ni el runner, ni el logging.

### F3.1 — Brazo FSM (y un tercer brazo reactivo)

- **Nuevo:** `src/agents/fsm.py` — `FSMPolicy` como máquina de estados explícita:
  `CRUISE → AVOID_LEFT | AVOID_RIGHT | CLIMB | BRAKE → CRUISE`, con transiciones por umbrales sobre
  el **mismo** `ObstacleField` y el **mismo** espacio de macro-acciones, resueltas con el **mismo**
  `action_to_command`. Comparación limpia: lo único que cambia es quién elige la etiqueta.
- Aclarar en la tesis que `reactive_node` **no** es la FSM: es guiado a waypoint. Se usa como
  **tercer brazo** (cota inferior: navegación sin evasión).
- **Selector:** `AGENT_ARM = slm | fsm | reactive` (env + flag de CLI).

### F3.2 — Logging estructurado

- **Nuevo:** `src/logging/flight_logger.py` → un JSONL por corrida, un registro por ciclo:

```json
{"t": 0.0, "cycle": 1, "arm": "slm", "scenario": "manhattan_a", "seed": 7,
 "pos": {"x":0,"y":0,"z":-10}, "vel": {...}, "yaw_deg": 0.0, "dt_s": 0.1,
 "route": "deliberative", "action": "EVADIR_DERECHA",
 "obstacle_field": { "...": "9 celdas: occupancy, ttc_s, divergence, confidence" },
 "ttc_min_s": 2.7, "blocked_fraction": 0.33, "foe_confidence": 0.81,
 "latency_ms": {"capture": 31.0, "perception": 12.4, "router": 0.1, "policy": 840.0, "motor": 3.2},
 "slm": {"invoked": true, "latency_ms": 840.0, "fallback": false, "timeout": false, "adherent": true},
 "collision": {"has_collided": false, "object": ""},
 "min_obstacle_dist_m": 4.2,
 "wp_index": 2, "dist_to_wp_m": 41.7, "degraded": false}
```

- `min_obstacle_dist_m` sale del canal depth (solo para métricas: **no** se realimenta al control,
  para no contaminar el experimento).
- Más un `summary.json` por corrida con los agregados de la misión.

### F3.3 — Runner batch y análisis

- **Nuevo:** `experiments/runner.py` — N misiones × M escenarios × K semillas, headless (sin ventana
  cv2, sin `stream_hub`). Por corrida: `client.reset()`, `simSetVehiclePose` a la pose inicial, carga
  del manifiesto, presupuesto de tiempo y de ciclos, escritura en
  `runs/<escenario>/<arm>/<seed>.jsonl`.
- **Nuevo:** `experiments/analyze.py` — agrega y produce la tabla de métricas:
  - tasa de éxito de misión;
  - colisiones por km;
  - distancia mínima a obstáculo (p5);
  - longitud de trayectoria vs. óptima (razón tipo SPL);
  - tiempo a destino;
  - latencia p50/p95 **por rama** (`keep_going` / `evasive` / `deliberative`);
  - invocaciones de SLM por misión; tasa de fallback; tasa de timeout del watchdog;
  - `adherence_rate` (F2.3).
- Comparación estadística entre brazos: Mann-Whitney U sobre las semillas (no promedios sueltos),
  con tamaño de efecto. Escenarios fijos y semillas fijas: reproducible.

### F3.4 — Tests unitarios de seguridad *(ninguno necesita AirSim)*

- **Nuevo:** `airsim-loop/tests/` + `conftest.py` (mismo patrón que `airsim-plan/conftest.py`, que ya
  inserta `src/` en `sys.path`).

| Test | Qué protege |
|---|---|
| `test_ttc_router.py` | Tabla de `ObstacleField` sintéticos → ruta esperada. Cubre los 3 casos + persistencia + deadlock. |
| `test_flow_ttc.py` | Campo traslacional sintético con FOE y TTC conocidos → recuperación dentro de tolerancia. **Y campo de rotación pura → TTC = inf tras derotación** (regresión del freno espurio por yaw). |
| `test_obstacle_field.py` | Agregación por celda, `blocked_fraction`, propagación de confianza, casos degenerados (0 píxeles válidos). |
| `test_action_map.py` | Toda `VALID_ACTION` mapea a un comando acotado, sin NaN, idéntico entre nodos. |
| `test_parser.py` | Respuestas corruptas del LLM: markdown, texto conversacional, JSON truncado, acción inválida, respuesta vacía. |
| `test_waypoint_tracker.py` | Waypoints degenerados: duplicados, segmento de longitud cero, lista de uno, dedup de `inject_corner_waypoint`. |
| `test_fsm.py` | Determinismo y transiciones de la FSM. |
| `test_graph_single_deliberation.py` | Un ciclo ⇒ una sola entrada en `deliberations[]` (regresión de F0.2). |
| `test_prompt_invariants.py` | #etiquetas de fotograma == #imágenes enviadas (regresión de F2.1). |
| `test_degraded_mode.py` | `source != "airsim"` ⇒ hover, no comandos de vuelo (regresión de F0.6). |

- Objetivo de cobertura: 100 % de las ramas de `ttc_router`, `action_map`, `_parse_decision` y
  `flow_ttc`. El resto, best-effort.

---

## Fase 4 — Cierre

Duración estimada: 3–4 días.

### F4.1 — Sincronizar documentación con el código

Es lo primero que salta en una defensa. Diferencias a resolver:

| Documento | Dice | Código |
|---|---|---|
| `README.md:40,65,79,92,106` | YOLO TensorRT a 2 ms como pieza central | eliminado |
| `README.md:66` | seguimiento multiobjeto por IoU, `area_ratio/width_ratio/height_ratio` | no se calculan |
| `airsim-loop/README.md:60-63` | ROI 62° + YOLO, `xor_router` activo | ROI sin uso, router sin cablear |
| `informe/2006-0823 …mmd` | IPM solo tras el freno, umbral de bloqueo 90 % | IPM en todos los ciclos, `FOV_BLOCKED_THRESHOLD = 0.6` |

Regenerar el `.mmd` **desde** el grafo compilado (LangGraph puede exportar el diagrama) para que la
divergencia no pueda repetirse.

### F4.2 — Código muerto a `legacy/`

Mover con un `legacy/README.md` que explique cada retiro y su evidencia:
`detector.py`, `translator.py`, `roi_cropper.py`, `ttc_estimator.py` (instanciado en `_build_nodes`
y nunca usado), `ipm_segmentator.py`. Depurar también `requirements.txt` (`ultralytics` duplicado en
dos versiones, `gymnasium`/`pygame`/`keyboard` del sub-proyecto `rllander`).

### F4.3 — Framing de tesis

- Documentar el retiro de YOLO como **decisión de diseño con evidencia medida** (no como nota de
  changelog), apoyada en el dataset de F1.3.
- Sobre LangGraph: el grafo llega a `END` en cada tick y la ciclicidad la da el `while True` de
  `main.py`. Es una arquitectura defendible, pero conviene describirla como **"grafo de decisión por
  tick"** y no como "grafo cíclico de navegación". Decirlo así es más fuerte que que lo pregunten.

---

## Dependencias y camino crítico

```
F0.0 (medir captura)
  └─> F0.1 (actuador no bloqueante) ─┐
      F0.2 (una ruta al SLM)         ├─> F0.5 (frecuencia + SLM async)
      F0.3 (cliente único)           │
      F0.4 (xor_router)  ────────────┘
      F0.6 (modo estricto)
                    │
                    v
      F1.1 (ObstacleField) ──> F1.2 (TTC real) ──> F1.3 (validación depth)  ◀── CAMINO CRÍTICO
                    │                                      │
                    │                                      └─> umbrales calibrados
                    ├─> F1.4 (retiro de IPM)
                    │
        ┌───────────┴───────────┐
        v                       v
   F2 (deliberación)      F3.1 (FSM) ─> F3.2 (logging) ─> F3.3 (runner + análisis)
        │                       │
        └───────> F3.4 (tests) <┘
                    │
                    v
                   F4
```

**Camino crítico:** F0.0 → F0.1 → F0.5 → F1.1 → F1.2 → F1.3. Todo lo demás puede paralelizarse.

**Hipótesis a verificar temprano:** con F0 y F1 hechas, el lazo reactivo solo probablemente ya vuele
razonablemente. Eso es exactamente el **baseline contra el cual el SLM tiene que demostrar que
aporta algo** — y es más valioso tenerlo antes que después.

---

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El enlace de red Mac↔Windows no sostiene 10 Hz de `simGetImages` | Todo el presupuesto temporal de F0.5 | F0.0 lo mide **antes** de comprometer la frecuencia; se baja resolución o se acepta 5 Hz con umbrales re-escalados |
| La derotación por telemetría queda desincronizada del frame (latencia del RPC) | El TTC vuelve a ser ruido en los giros | Validación cruzada con afín global (F1.2 punto 2); si divergen, estimar la rotación solo por imagen |
| El SLM local no soporta `json_schema` en la versión instalada de LM Studio | F2.3 | El parser tolerante queda como camino principal; se reporta la métrica de adherencia sin restricción como línea base |
| Reescribir `deliberative_node` rompe la auditabilidad de `deliberations[]` | Se pierde la evidencia primaria de la tesis | `deliberations[]` es **contrato congelado**: solo se le agregan campos (`timeout`, `adherent`, `arm`), nunca se le quitan |
| El brazo FSM se implementa "de más" o "de menos" y sesga la comparación | Invalida el resultado central | Mismo `ObstacleField`, mismo espacio de acciones, mismo `action_to_command`; lo único que difiere es quién elige la etiqueta. Documentar la FSM completa en la tesis |

---

## Lo que no se toca

Fortalezas ya construidas que el refactor debe **preservar**, no reescribir:

1. **La arquitectura de deliberación por excepción**: freno previo, whitelist de acciones, parser
   tolerante, fallback determinista, persistencia de maniobra anti-flip-flop. El esqueleto es correcto.
2. **`deliberations[]`**: prompt, `raw_response`, modelo, latencia y flag de fallback. Es la evidencia
   primaria de cada decisión. Solo se extiende.
3. **`WaypointTracker`**: cross-track error contra el eje de la calle, zona muerta de 2.5°, saturación
   de yaw-rate, `vx ∝ cos(Δψ)`. Control clásico bien hecho. Solo se le agrega `progress_stall_cycles`.
4. **`callibration_flight` y `local-llm-eval`**: contribuciones metodológicas independientes del
   estado del lazo. No se tocan.
