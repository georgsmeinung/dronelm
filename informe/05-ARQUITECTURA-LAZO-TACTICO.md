# 5. Arquitectura del lazo táctico

## 5.0 Escaneo espacial pre-vuelo (`spatial_scan`)

Antes de que el grafo de decisión empiece a ejecutarse, `main.py` llama de forma bloqueante a `spatial_scan()` (`src/agents/spatial_scan.py`). Esta función no es un nodo del `StateGraph`: se ejecuta una sola vez, entre la conexión con AirSim y la construcción del estado inicial del grafo.

El escaneo realiza un barrido de yaw en el lugar (sin traslación) hacia un conjunto de rumbos equiespaciados alrededor del rumbo inicial, captura un fotograma en cada rumbo tras un breve período de asentamiento y envía todas las imágenes en una única consulta al VLM. El modelo devuelve un contexto cualitativo del entorno visible desde el punto de despegue (obstáculos prominentes, corredores potenciales, densidad general de la escena). Este contexto es **advisory, no safety-critical**: el `ObstacleField` por ciclo sigue siendo la única autoridad de seguridad una vez que el dron está en movimiento.

Si el VLM no responde dentro del watchdog del escaneo, o devuelve una respuesta no parseable, la misión arranca igualmente sin contexto inicial — un VLM caído nunca impide el despegue. Al igual que el resto del sistema de percepción (cap. 6), el escaneo pre-vuelo opera exclusivamente sobre fotogramas RGB monoculares y nunca consulta el canal de profundidad del simulador.

La latencia de `spatial_scan` es un costo de inicialización de única vez, no un costo por ciclo; se mide y registra separadamente del presupuesto de latencia táctica (§10.2).

## 5.1 Visión general del lazo

El lazo descrito en este capítulo se ejecuta sobre el entorno de simulación construido y validado en el capítulo 3 (Unreal Engine 5.5 con Cosys-AirSim), ejecutando los manifiestos compilados por la estación terrena (capítulo 4). El sistema implementado es un **grafo de decisión por ciclo** (`StateGraph` de LangGraph, [LangChain, 2024](13-REFERENCIAS.md#ref-langchain-2024); `src/agents/graph.py`) que se ejecuta a una frecuencia objetivo de `LOOP_HZ` (5 Hz en la configuración de producción; ciclo medido ≈ 0.2 s).

El grafo se compila **una sola vez** al inicio de la misión y el bucle externo de `main.py` (o del ejecutor de experimentos, `experiments/runner.py`) lo invoca con `graph.invoke()` en cada ciclo. El grafo no tiene aristas de retorno: es acíclico por diseño. La naturaleza cíclica de la navegación la aporta el bucle externo, no el grafo. Esta distinción importa porque LangGraph construye los canales del estado a partir del `TypedDict` declarado (`DroneState`, §5.2): cualquier clave que un nodo escriba pero no esté declarada en ese schema es **descartada en silencio** al finalizar `graph.invoke()`, y por lo tanto no persiste entre ciclos. Esta propiedad es la causa raíz de varios de los modos de falla documentados en el capítulo 9.

### 5.1.1 Topología: cuatro nodos y una arista condicional

Cada ciclo recorre `capture → perception → navigate → motor`. La única arista condicional es la que sigue a `capture`: si AirSim no entregó un par imagen–telemetría válido, el ciclo se desvía a `degraded_hover` y se salta la percepción y la decisión.

```
capture ──(ok)──────────► perception ──► navigate ──► motor ──► FIN
   │                                                    ▲
   └──(AirSim sin datos)──► degraded_hover ─────────────┘
```

`navigate` es un **único nodo** que contiene toda la política de navegación. La decisión no se distribuye en varios nodos hermanos seleccionados por un conmutador, sino que se organiza **en capas de prioridad** dentro del nodo (§5.3): una capa reactiva de latencia nula que siempre puede actuar, una capa táctica determinista que detecta y resuelve atascos con la historia de trayectoria, y una capa asíncrona de consulta al VLM cuyo resultado se consume cuando llega, sin bloquear el lazo. Los comportamientos concretos (crucero guiado, evasión lateral, giro de 90°, escape vertical, escaneo del VLM) son **funciones** que la capa activa invoca, no nodos del grafo.

<img src="2026-0928 drone_graph_layered_architecture.png"/>

*Figura 5.1. Arquitectura en capas del nodo `navigate`. Cada `invoke()` recorre capture → perception → navigate → motor en forma síncrona; las capas 1 y 2 tienen latencia de 0 ciclos y la capa 3 (VLM) latencia de 1 a N ciclos, comunicada por el almacén `_vlm_intention`.*

### 5.1.2 Por qué capas y no un conmutador plano

Un conmutador de N ramas al mismo nivel (una por comportamiento) presenta tres problemas estructurales que la organización en capas resuelve:

1. **No hay precedencia explícita.** Con ramas hermanas, el orden de las condiciones es la única prioridad y cualquier condición nueva se inserta «en el medio». En capas, la prioridad es la posición de la capa: lo que garantiza seguridad (continuar una maniobra comprometida, reaccionar a un contacto) se evalúa siempre antes que lo que optimiza progreso.
2. **El razonamiento lento no debe frenar al vehículo.** Si la rama que consulta al VLM emite `FRENAR` mientras espera, la percepción por flujo óptico —que necesita traslación— se queda sin señal y el sistema entra en un ciclo de realimentación (frenar → sin flujo → sin confianza → volver a consultar). En la arquitectura en capas, la consulta proactiva es no bloqueante y el vuelo continúa por las capas 1 y 2 hasta que la respuesta esté disponible.
3. **Las respuestas del VLM llegan a destiempo.** Una respuesta tarda entre uno y varios ciclos (§8.6); aplicarla sin más equivale a actuar sobre una escena que ya cambió. El almacén `_vlm_intention` asocia cada respuesta a su marca temporal y la capa que la consume la descarta si excede una edad máxima (5 s en la capa de TTC, 10 s en la resolución de atasco).

Esta organización sigue el patrón clásico de arquitecturas de tres capas para robots móviles, con un controlador reactivo de respuesta inmediata, un secuenciador de comportamientos y una capa deliberativa que opera a otra escala temporal ([Gat, 1998](13-REFERENCIAS.md#ref-gat-1998)), y la idea de descomponer el control por niveles de competencia en los que las capas inferiores conservan siempre la capacidad de actuar ([Brooks, 1986](13-REFERENCIAS.md#ref-brooks-1986)). La diferencia es que aquí la capa deliberativa es un modelo de visión-lenguaje de 3 000 M de parámetros y su latencia (≈ 1.5 s de mediana, §8.6) es un orden de magnitud mayor que el período del lazo.

## 5.2 El estado compartido: `DroneState`

El estado que circula entre los nodos es un `TypedDict` llamado `DroneState` (`graph.py`). Es el único canal de comunicación entre nodos: ningún nodo importa funciones de otro ni mantiene estado propio más allá de lo que declara aquí. La tabla siguiente describe los campos clave y su rol en el sistema.

**Datos sensoriales:**

| Campo | Tipo | Descripción |
|---|---|---|
| `rgb_image` | `ndarray` | Fotograma RGB del ciclo actual, producido por `capture_node` |
| `prev_image` | `ndarray` | Fotograma del ciclo anterior, usado por `FlowTTCEstimator` |
| `frame_history` | `List[ndarray]` | Ring buffer de los últimos `VLM_FRAME_HISTORY_SIZE` fotogramas (default 2: instantes `t` y `t-1`) para el VLM |
| `frame_history_ts` | `List[float]` | Timestamps reales de captura (reloj del simulador) de cada frame de `frame_history`, índice a índice |
| `telemetry` | `Dict` | Posición NED, velocidad, orientación (pitch/roll/yaw), colisión, timestamp y `source` del ciclo actual |
| `prev_telemetry` | `Dict` | Telemetría del ciclo anterior, usada por el estimador de flujo óptico |
| `degraded` | `bool` | `True` si AirSim no respondió este ciclo (`rgb_image is None` o `source != "airsim"`) |

**Percepción:**

| Campo | Tipo | Descripción |
|---|---|---|
| `obstacle_field` | `ObstacleField` | Contrato único de percepción: estado de los tres sectores (centro/izquierda/derecha) con ocupación, TTC y flag de bloqueo por sector (cap. 6) |
| `estimated_ttc` | `float` | TTC mínimo entre todos los sectores, derivado de `obstacle_field.min_ttc()`, para display y logging |
| `scene_summary` | `str` | Texto compacto del `ObstacleField` para el prompt del VLM |

**Decisión y control:**

| Campo | Tipo | Descripción |
|---|---|---|
| `next_action` | `str` | Macro-acción elegida por el nodo de política activo este ciclo |
| `velocity_command` | `Dict` | Comando cinemático `{macro_action, vx, vy, vz, yaw_rate, target_yaw, rationale}` listo para `motor_node` |
| `route` | `str` | Comportamiento que produjo el comando: `"reactive"`, `"evasive"` (incluye la continuación de maniobra), `"tactical"` (resolución de atasco y escape vertical), `"girar_90"`, `"fsm"`, `"degraded"` |
| `flight_status` | `str` | Estado textual de la misión para logging y overlay |

**Guiado a waypoint:**

| Campo | Tipo | Descripción |
|---|---|---|
| `waypoints` | `List[Dict]` | Lista de waypoints del manifiesto (x/y/z/label) |
| `current_wp_index` | `int` | Índice del waypoint activo en la lista |
| `target_waypoint` | `Dict` | Waypoint activo, copiado de la lista por `WaypointTracker` |
| `waypoint_guidance` | `Dict` | Salida de `WaypointTracker.compute_guidance()`: `vx`, `vy`, `vz`, `yaw_rate`, `distance`, `bearing_err_deg`, `target_wp`, `is_completed` |
| `mission_completed` | `bool` | `True` cuando todos los waypoints fueron alcanzados |

**Persistencia de maniobra (anti-flip-flop):**

| Campo | Tipo | Descripción |
|---|---|---|
| `active_maneuver` | `str\|None` | Macro-acción de la maniobra comprometida actualmente en ejecución |
| `maneuver_cycles_left` | `int` | Ciclos restantes de la maniobra comprometida |
| `maneuver_command` | `Dict\|None` | Comando cinemático fijo de la maniobra comprometida |

**Deliberación y VLM:**

| Campo | Tipo | Descripción |
|---|---|---|
| `deliberations` | `List[Dict]` | Registro de todas las consultas al VLM de la misión, incluidas las fallidas (de solo agregado: campos nunca se borran, §5.16) |
| `last_deliberation` | `Dict\|None` | Última entrada de `deliberations`, actualizada por `motor_node` |
| `slm_request_id` | `int\|None` | ID del pedido VLM pendiente en `DeliberationService`; `None` si no hay pedido en vuelo |
| `_deliberation_pending` | `bool` | `True` mientras el escaneo de resolución de atasco espera la respuesta del VLM; el bucle externo salta `record_progress()` para no penalizar la espera como "atasco". Solo lo escriben `_slam_assess_cycle` y `deep_scan_cycle` |
| `_vlm_intention` | `Dict\|None` | Última decisión parseada del VLM con su marca temporal (`_ts`) y latencia; la consumen las capas 1 y 2 mientras esté vigente y se pone a `None` al usarla (§5.10.2) |
| `_pending_delib_prompt` | `str\|None` | Prompt enviado al VLM, guardado para adjuntarlo al registro cuando llegue la respuesta |
| `_pending_delib_frames` | `List\|None` | Frames RAW + timestamps enviados al VLM, guardados para auditoría |
| `_last_delib_frames` | `List\|None` | Canal de una sola pasada hacia `FlightLogger`: solo tiene contenido en el ciclo exacto en que una deliberación se resuelve (o un escaneo falla); se consume con `pop()` y nunca se acumula en `deliberations` |
| `vlm_goal` | `Dict\|None` | Sub-meta semántica emitida por el VLM (`dx_m`, `dy_m`, `dz_m`, `confidence`, `semantic_label`, `mode`) cuando su confianza supera `VLM_GOAL_MIN_CONFIDENCE = 0.7` (§5.10) |
| `_vlm_goal_history` | `List[Dict]` | Últimas tres sub-metas, reinyectadas al prompt como contexto de las decisiones previas |

**Lógica de escape de deadlock:**

| Campo | Tipo | Descripción |
|---|---|---|
| `evasion_stuck_cycles` | `int` | Ciclos consecutivos sin progresar hacia el waypoint activo (acumulado por `WaypointTracker.record_progress()`) |
| `_consecutive_escapes` | `int` | Cantidad de escapes verticales consecutivos (GANAR_ALTURA / PERDER_ALTURA) sin progreso horizontal medido |
| `_escape_locked` | `bool` | `True` cuando el escape vertical se agotó (`_consecutive_escapes > MAX_CONSECUTIVE_ESCAPES`); el escape queda inhabilitado hasta que haya progreso horizontal real |
| `_escape_baseline_dist` | `float\|None` | Distancia al waypoint en el momento en que se inició el último escape; usada para evaluar si el escape resolvió el atasco |
| `_escape_reset` | `bool` | Señal de flanco (no de nivel): `True` en el ciclo exacto en que un escape se resuelve, para que `main.py` llame a `WaypointTracker.reset_progress()` |
| `_deadlock_cycles` | `int` | Ciclos dentro del estado de atasco duro (acumula mientras el escaneo profundo está activo) |
| `_deadlock_event` | `Dict\|None` | Métricas de resolución del atasco (estrategia, ciclos hasta resolver, acción del VLM, respuesta cruda), consumidas por `FlightLogger`; el bucle externo también las usa para registrar el punto de contacto en el `WaypointTracker` (§5.15.4) |
| `_scan_track` | `Dict` | Contadores publicados para el log: escaneos fútiles consecutivos y escapes verticales ejecutados (§5.3.4) |
| `_scan_last_evadir_dir` / `_scan_evadir_count` | `str\|None` / `int` | Último lado de evasión despachado por el escaneo y cuántas veces seguidas se repitió; sirven para detectar oscilación o repetición sin progreso (§5.12) |
| `_post_retroceder_corner_pending` | `bool` | Se activa al despachar `RETROCEDER` como resolución de atasco y se consume en la siguiente consulta de escape, donde inyecta un waypoint de esquina perpendicular al rumbo al waypoint (§5.12.3) |
| `inject_corner` | `Dict\|None` | Waypoint de desvío temporal `{x, y, z}` que `WaypointTracker` adopta como objetivo hasta alcanzarlo; lo producen el agotamiento del escape vertical (§5.10), la esquina post-retroceso (§5.12.3) y la sub-meta semántica del VLM (§5.10) |

**Estado del escaneo panorámico profundo (`deep_scan`):**

| Campo | Tipo | Descripción |
|---|---|---|
| `_scan_phase` | `str\|None` | Fase actual: `"rotando"` \| `"asentando"` \| `"capturado"` \| `None` (no activo) |
| `_scan_heading_index` | `int` | Rumbo actual dentro del barrido (0 a `SCAN_HEADING_COUNT_DEEP-1`) |
| `_scan_frames` | `List` | Fotogramas capturados hasta ahora: `[(heading_deg, rgb_frame, capture_ts)]` |
| `_scan_start_yaw_deg` | `float\|None` | Yaw al inicio del barrido, referencia para calcular los rumbos objetivo |
| `_scan_settle_left` | `int` | Ciclos de asentamiento restantes en el rumbo actual |
| `_scan_rot_stall` | `int` | Ciclos consecutivos en fase `"rotando"` sin alcanzar el rumbo objetivo; al superar `SCAN_ROT_TIMEOUT_CYCLES = 10` el barrido se abandona (§5.12) |
| `_deep_scan_request_id` | `int\|None` | ID del pedido VLM panorámico pendiente |

**Señales de obstáculo invisible (publicadas por el `StallDetector`, §5.3.1):**

| Campo | Tipo | Descripción |
|---|---|---|
| `imu_jitter_level` | `str` | `"normal"` \| `"elevado"` \| `"critico"` según RMS de aceleración lateral |
| `imu_contact_event` | `bool` | Contacto inferido por vibración sostenida con comando de avance |
| `blind_wall_event` | `bool` | Comando frontal sin velocidad real con flujo libre |
| `_stopped_cycles` | `int` | Ciclos consecutivos parado (< 0.10 m/s) sin pedido VLM pendiente (tope 200) |
| `_pos_freeze_cycles` | `int` | Ciclos consecutivos con desplazamiento XY neto < `POS_FREEZE_DIST_M` |
| `_wp_no_progress_cycles` | `int` | Ciclos consecutivos sin mejorar `WP_NO_PROGRESS_MIN_M` la distancia al waypoint |
| `stuck_invisible` | `bool` | OR unificado de contacto IMU, pared ciega, parado y posición congelada |

Los contadores internos de cada detector (ciclos de contacto, referencia de posición, mejor distancia al waypoint) no se declaran en el estado: son atributos del objeto `StallDetector`, que persiste entre invocaciones.

**Estadísticas de trayectoria para routing:**

| Campo | Tipo | Descripción |
|---|---|---|
| `_traj_frente_stall_rate` | `float` | Tasa de stall de la zona FRENTE (últimos 30 eventos), publicado por `capture_node` |
| `_traj_frente_attempts` | `int` | Intentos en la zona FRENTE |
| `_traj_izq_stall_rate` | `float` | Tasa de stall IZQUIERDA, para C1 en `evasive_node` |
| `_traj_izq_attempts` | `int` | Intentos IZQUIERDA |
| `_traj_der_stall_rate` | `float` | Tasa de stall DERECHA, para C1 y D1 |
| `_traj_der_attempts` | `int` | Intentos DERECHA |

**Profundidad monocular (V4):**

| Campo | Tipo | Descripción |
|---|---|---|
| `_depth_proximity_m` | `float\|None` | Distancia estimada por Depth Anything V2 Metric al obstáculo frontal; `None` si el estimador no tiene resultado reciente o la señal no está activa |
| `_depth_below_cycles` | `int` | Ciclos consecutivos con `depth_m < DEPTH_BRAKE_M` (guarda V4b anti-falso-positivo) |
| `_depth_obstacle_type` | `str\|None` | `"follaje"` \| `"superficie plana"` \| `"desconocido"` \| `None` — clasificación por textura del mapa de profundidad (E2) |

**Corrección de altitud en hover:**

| Campo | Tipo | Descripción |
|---|---|---|
| `_hover_alt_anchor` | `float\|None` | Altitud anclada al primer ciclo de FRENAR; `motor_node` la usa para corregir la deriva vertical con un controlador P |

**Regla de diseño crítica.** Todo campo que cruce la frontera entre invocaciones de `graph.invoke()` debe estar declarado en este `TypedDict`. LangGraph no lanza error si un nodo escribe una clave no declarada: la descarta en silencio. Esta propiedad provoca fallas especialmente difíciles de diagnosticar, porque el sistema sigue funcionando con un valor perdido: un indicador de reinicio que nunca se propaga, un enclavamiento que se pierde entre ciclos, una línea de base que nunca acumula evidencia, un waypoint de desvío que nunca se produce (casos documentados en el capítulo 9, §9.4 y §9.5.4). Dos decisiones de diseño reducen esa superficie: los contadores de bloqueo viven en el `StallDetector` y no en el estado (§5.3.1), y el estado de un escaneo multiciclo se declara íntegramente con el prefijo `_scan_`.

## 5.3 Nodo `navigate`: política en tres capas

`navigate_node` (`graph.py`) recibe el estado ya enriquecido por `perception` y produce un `velocity_command`. Al entrar, siempre ejecuta dos pasos previos: actualiza el `StallDetector` y publica sus señales en el estado (§5.3.1), y —salvo en los brazos `reactive` y `fsm`, que se derivan aquí— consulta sin bloquear al `DeliberationService` (`_poll_vlm`, §5.10). Después evalúa las capas en un orden de prioridad estricto: **la primera condición que se cumple decide el ciclo** y las restantes no se evalúan.

### 5.3.1 `StallDetector`: señales de bloqueo como objeto de proceso

Los contadores de atasco no son campos del `DroneState`: viven en un objeto `StallDetector` (`src/agents/stall_detector.py`) instanciado una vez al construir los nodos (junto a `FlightTrajectory`) y que persiste entre invocaciones de `graph.invoke()`. Concentrar los contadores en un objeto de proceso tiene dos ventajas: reduce el `TypedDict` a los campos que realmente deben cruzar la frontera entre ciclos (y con ello la superficie del modo de falla de estado descartado, cap. 9), y hace cada detector comprobable de forma aislada. Cada ciclo, `update(state)` ejecuta los cinco detectores y `publish(state)` escribe las señales resultantes en el estado, únicamente para logging y para los consumidores que las leen del estado.

| Señal | Condición | Umbral |
|---|---|---|
| `imu_contact` | RMS de la aceleración lateral `(ax, ay)` ≥ `IMU_CONTACT_THRESHOLD_MPS2` (5.0 m/s²) con velocidad comandada > 0.3 m/s | ≥ 2 ciclos consecutivos |
| `blind_wall` | Comando frontal (`cmd_vx ≥ 0.45 m/s`) con velocidad real < 0.30 m/s y flujo óptico con corredor libre (`blocked_fraction < 0.25`); el dron debe haberse estado moviendo en el ciclo previo (`≥ 0.20 m/s`) | ≥ `CMD_BLIND_CYCLES` = 2 ciclos |
| `stopped_cycles` | Velocidad real < 0.10 m/s en cualquier ruta y sin pedido VLM pendiente; se reinicia apenas el dron se mueve o mientras el VLM procesa (tope 200) | `stopped_prolonged` ≥ `STOPPED_DELIBERATIVE_CYCLES` = 10; contribuye a `stuck_invisible` con ≥ `STOPPED_CYCLES_THRESHOLD` = 15 |
| `pos_freeze_cycles` | Desplazamiento XY neto respecto de una posición de referencia < `POS_FREEZE_DIST_M` (0.50 m); inmune a la velocidad instantánea. La referencia se refresca cada `POS_FREEZE_THRESHOLD` ciclos. No acumula con un pedido VLM pendiente ni con un barrido panorámico activo | ≥ `POS_FREEZE_THRESHOLD` = 30 ciclos (6 s) |
| `wp_no_progress` | La distancia al waypoint no mejora `WP_NO_PROGRESS_MIN_M` (2.0 m) respecto de la mejor distancia vista. No acumula con pedido VLM pendiente, barrido activo, altitud bajo el piso óptico, cambio de waypoint ni `_escape_reset` | ≥ `WP_NO_PROGRESS_THRESHOLD` = 50 ciclos (10 s) |

Además clasifica el nivel de vibración (`imu_jitter_level`: `"normal"`, `"elevado"` ≥ 3.0 m/s², `"critico"` ≥ 8.0 m/s²). La señal unificada `stuck_invisible` es el OR de cuatro de ellas:

```python
stuck_invisible = imu_contact OR blind_wall
                  OR (stopped_cycles   >= STOPPED_CYCLES_THRESHOLD)
                  OR (pos_freeze_cycles >= POS_FREEZE_THRESHOLD)
```

Cada señal cubre un modo de bloqueo que las demás no ven, y todas apuntan al mismo problema estructural del sensado monocular: un obstáculo que el flujo óptico no reporta (malla de colisión de un árbol, fachada lisa, moldura). `imu_contact` detecta el choque por su firma inercial; `blind_wall` detecta la divergencia entre lo comandado y lo medido; `stopped_cycles` cubre al dron detenido sin causa aparente (por ejemplo, con una pata trabada en una malla de colisión invisible, caso en que `RETROCEDER` no produce movimiento); `pos_freeze_cycles` cubre al dron que *oscila* dentro de un volumen pequeño con velocidad instantánea no nula (medido: ~1.85 m/s dentro de la malla convexa de un árbol), caso en que los contadores de velocidad se reinician cada ciclo y la tasa de stall de trayectoria no llega a su umbral; y `wp_no_progress` cubre el arrastre lateral contra una fachada, donde el contador de progreso del `WaypointTracker` queda congelado porque el error de rumbo es siempre mayor que el umbral de exención (§5.15). Las condiciones de supresión (VLM procesando, barrido activo, ascenso inicial) evitan que una inmovilidad *intencional* se interprete como atasco.

### 5.3.2 Orden de evaluación

| # | Capa | Condición | Acción |
|---|---|---|---|
| 1 | — | `AGENT_ARM = reactive` / `fsm` | `reactive_node` / `fsm_node` (§5.7, §5.11) |
| 2 | 1 | Hay maniobra comprometida (`active_maneuver` con `maneuver_cycles_left > 0`) | Continúa la maniobra, ruta `"evasive"` |
| 3 | 1 | `imu_contact` o `blind_wall` | `evasive_node` |
| 4 | 1 | Altitud < `OPTICAL_MIN_ALT_M` (4.5 m) | `reactive_node` |
| 5 | 2 | Escape vertical forzado debido (§5.3.4) | `GANAR_ALTURA` / `PERDER_ALTURA` |
| 6 | 2 | `stopped_prolonged` (≥ 10 ciclos parado) | `_deadlock_resolve` |
| 7 | 2 | `stuck_invisible` | `_deadlock_resolve` si `evasion_stuck_cycles ≥ hard_stall_threshold()` o `stopped_cycles ≥ STUCK_RETROCEDER_LIMIT` (30); si no, `evasive_node` |
| 8 | 2 | `wp_no_progress` | `_deadlock_resolve` |
| 9 | 2 | Stall frontal de trayectoria ≥ 70 % con ≥ 10 intentos (`TRAJ_STALL`) | `_deadlock_resolve` |
| 10 | 2 | `evasion_stuck_cycles ≥ effective_stall_threshold()` y (sin corredor transitable o ≥ umbral duro) | `_deadlock_resolve` |
| 11 | 3 | (efecto lateral) atasco incipiente | Pedido proactivo al VLM (`_maybe_request_vlm`); no decide el ciclo |
| 12 | 1 | TTC crítico (`center_ttc ≤ TTC_EVASION_THRESHOLD` 3.2 s) o centro bloqueado con `center_ttc ≤ TTC_SAFE_THRESHOLD` (4.6 s) | `GIRAR_90` si `blocked_fraction > FOV_BLOCKED_THRESHOLD` (0.6) y altitud ≥ `SLM_MIN_ALT_M` (8 m); intención del VLM vigente (< 5 s) contrastada con los overrides de trayectoria; o `evasive_node` |
| 13 | 1 | Centro bloqueado o `min_ttc ≤ TTC_SAFE_THRESHOLD` | `evasive_node` |
| 14 | 1 | Camino despejado | `reactive_node` (`MANTENER_RUMBO`) |

Tres decisiones de orden merecen explicación. **(i)** La continuación de maniobra (2) precede a todo lo demás, incluidos los disparadores de atasco, porque el contador de atasco sigue elevado en el ciclo posterior a un escape y volvería a enrutar hacia la resolución de atasco antes de que la maniobra comprometida se ejecute; la maniobra se completa y el contador se reinicia con `_escape_reset` (§5.3.4). No hay condición de TTC mínimo en esta continuación: el escape se ejecuta *hacia afuera* del obstáculo, por lo que un TTC bajo es el estado esperado durante la maniobra. **(ii)** Los contactos físicos (3) preceden a la altitud óptica (4) y a los disparadores de atasco, porque indican choque real y no dependen del sensado visual; el piso óptico (4) solo suprime los chequeos que dependen del flujo (que ve el suelo en movimiento durante el ascenso inicial y produce TTC falsos) y las señales de atasco. **(iii)** Los disparadores de atasco (6–10) se evalúan antes que el TTC (12–13) porque, cuando el dron está embebido en una malla de colisión, el campo óptico puede reportar un corredor libre espurio y la evidencia de trayectoria acumulada es más confiable que el campo instantáneo.

### 5.3.3 Capa 1: siempre reactiva (latencia 0)

Es la capa que puede actuar en cualquier ciclo sin depender del VLM ni de historia acumulada. Sus componentes son la continuación de maniobra comprometida (anti flip-flop: una maniobra se ejecuta completa antes de aceptar otra decisión táctica), la reacción a contacto (`evasive_node`, §5.8), el piso de altitud óptica, las reglas por TTC/ocupación descritas en la tabla anterior y el guiado nominal al waypoint (`reactive_node`, §5.7). Los umbrales de TTC (`TTC_EVASION_THRESHOLD = 3.2 s`, `TTC_SAFE_THRESHOLD = 4.6 s`, `FOV_BLOCKED_THRESHOLD = 0.6`) provienen de la calibración con datos de vuelo real (cap. 7).

El giro de 90° (`_dispatch_girar_90`, §5.9) es la respuesta determinista a un campo de visión casi totalmente obstruido, donde cualquier corrección lateral es inútil. A baja altitud (< 8 m) esa condición se resuelve con `evasive_node` en lugar de consultar al VLM: el ascenso inicial no debe disparar consultas.

### 5.3.4 Capa 2: táctica determinista (`_deadlock_resolve`)

Reúne los detectores de bloqueo (filas 5–10 de la tabla) y una única rutina de resolución, `_deadlock_resolve`, **que nunca espera al VLM para poder actuar**. Cada invocación incrementa `_deadlock_cycles` y aplica, en orden:

1. **Atasco extremo sin historia.** Si `evasion_stuck_cycles ≥ hard_stall_threshold()` y el buffer de trayectoria no tiene ningún evento (y la estrategia no es `deep_vlm`): `GANAR_ALTURA` mientras no se hayan agotado los escapes (`_consecutive_escapes < MAX_CONSECUTIVE_ESCAPES`) y, agotados, `RETROCEDER`.
2. **Estrategia configurada (`DEADLOCK_STRATEGY`).** Con `slam_assess` (valor de producción) o `deep_vlm`, delega en el módulo de escaneo (§5.12): el dron queda en hover (`ESCANEO`) mientras el VLM evalúa la escena junto con el contexto de trayectoria, con un watchdog de `SLM_DEEP_WATCHDOG_MS` (12 s), y la decisión se aplica tras contrastarla con los overrides deterministas (§5.12.2). Si el VLM no responde o su respuesta no es una acción válida, la rutina **continúa** con los pasos 3 a 5 en el mismo ciclo.
3. **Intención vigente del VLM.** Si `_vlm_intention` tiene menos de 10 s (respuesta a un pedido proactivo previo), se aplica tras los overrides de trayectoria; una acción vertical con el escape agotado o enclavado se sustituye por `_fallback_decision`.
4. **Pedido al VLM.** Si no hay ninguno pendiente, se encola uno (no bloqueante) para tenerlo disponible en ciclos siguientes.
5. **Resolución determinista por zonas.** Con `FlightTrajectory.zone_stats(heading)`: (a) si FRENTE, IZQUIERDA y DERECHA tienen stall ≥ 70 % con ≥ 3 intentos, `GANAR_ALTURA` mientras el escape no esté agotado y, agotado, se enclava (`_escape_locked`), se inyecta una esquina (`inject_corner`) y se emite `RETROCEDER`; (b) si una zona lateral no fue explorada, `EVADIR` hacia ella; (c) en otro caso, `EVADIR` hacia el lado con menor tasa de stall.

**Escape vertical forzado.** Un escaneo se considera *fútil* si, entre dos resoluciones consecutivas del escaneo, el dron se desplazó menos de `ESCAPE_MIN_DISP_M` (2.0 m). Tras `VERTICAL_ESCAPE_FUTILE_SCANS` (2) escaneos fútiles seguidos, o con `stuck_invisible` y posición congelada durante `VERTICAL_ESCAPE_FREEZE_CYCLES` (50) ciclos, `navigate` fuerza un escape vertical que alterna `GANAR_ALTURA` y `PERDER_ALTURA`. La condición se comprueba antes de los disparadores ordinarios de atasco y no se dispara mientras haya un barrido o un pedido VLM pendiente. Se salta `GANAR_ALTURA` (pasando a `PERDER_ALTURA`) si la altitud alcanza `VERTICAL_ESCAPE_MAX_ALT_M` (25 m) o si el tracker detectó un techo (§5.15.3). El escape vertical reinicia los contadores de inmovilidad (`StallDetector.reset_freeze()`), pide `_escape_reset` y registra un `_deadlock_event` con `strategy = "vertical_escape"`. Existe porque un vocabulario de escape puramente lateral no rompe el bloqueo cuando el obstáculo es una estructura horizontal o cuando el VLM repite una evasión lateral que no produce desplazamiento.

**Seguimiento de la resolución.** Cuando `_consecutive_escapes > 0`, el nodo compara en cada ciclo la distancia al waypoint con `_escape_baseline_dist`; si mejoró más de `WAYPOINT_PROGRESS_EPS_M` (0.5 m), el escape se considera resuelto y se reinician `_consecutive_escapes`, `_escape_locked` y `_escape_baseline_dist`. Un escape vertical que no produce progreso horizontal se cuenta contra `MAX_CONSECUTIVE_ESCAPES` (2 en producción) y, agotado, cambia la estrategia en lugar de frenar indefinidamente: se enclava el escape y se inyecta un waypoint de desvío lateral (`inject_corner`, §5.12.3).

### 5.3.5 Capa 3: consulta asíncrona al VLM

La capa 3 no decide por sí misma: produce **intenciones** que las capas 1 y 2 consumen cuando están vigentes. Su mecanismo tiene tres piezas (detalle en §5.10):

- **Pedido proactivo (`_maybe_request_vlm`).** Antes de que el bloqueo sea duro, si `evasion_stuck_cycles ≥ effective_stall_threshold()/2`, o `stuck_invisible`, o el stall frontal de trayectoria ≥ 50 % con ≥ 5 intentos, se encola un pedido al VLM y el vuelo continúa por las capas 1 y 2.
- **Almacén `_vlm_intention`.** `_poll_vlm` (no bloqueante) deposita en el estado la decisión parseada con su marca temporal y su latencia cuando llega la respuesta al pedido en vuelo.
- **Consumo con caducidad.** Las capas 1 y 2 usan la intención solo si es reciente; una respuesta tardía se descarta y el próximo pedido la sobrescribe (la cola del servicio tiene tamaño 1).

En la resolución de atasco con `slam_assess`, el VLM se consulta de forma **síncrona respecto del comportamiento** (el dron queda en hover mientras espera): es la única situación en que la espera es deliberada: la evidencia de bloqueo ya es suficiente para que quedarse quieto no cueste percepción útil, y la decisión es la de mayor impacto de todo el sistema. Aun así el watchdog garantiza que la falta de respuesta nunca deje al dron inmóvil más allá de 12 s: caso en que la capa 2 resuelve por su cuenta.

### 5.3.6 Ejemplo de escalamiento en un bloqueo típico

1. El TTC cae por debajo de 4.6 s → `evasive_node` corrige lateralmente (capa 1).
2. Si el dron sigue sin progresar (`evasion_stuck_cycles ≥ 10`) → `_deadlock_resolve` resuelve con la historia de zonas: evadir hacia el lado no explorado o menos bloqueado (capa 2).
3. Si las zonas están todas bloqueadas o el atasco persiste → `slam_assess` envía el fotograma y el contexto de trayectoria al VLM, mantiene hover hasta la respuesta, contrasta la acción con los overrides y la aplica (capa 3); si no hay respuesta válida, aplica el fallback determinista del paso 5.
4. Si tras dos escaneos el dron sigue sin desplazarse ≥ 2 m → escape vertical forzado.

## 5.4 Nodo `capture`

**Entradas:** cliente AirSim inyectado (singleton por proceso).
**Salidas:** `rgb_image`, `telemetry`, `degraded`, `frame_history`, `frame_history_ts`, `prev_image`, `prev_telemetry`.

Copia el frame y la telemetría del ciclo anterior a `prev_image` / `prev_telemetry`, luego llama a `airsim_client.capture()` para obtener el nuevo par imagen + telemetría. Si la imagen es `None` o `telemetry["source"] != "airsim"`, marca `degraded = True` y omite la actualización del ring buffer (un ciclo degradado no sobreescribe los frames válidos anteriores).

En modo normal, agrega el nuevo frame (y su timestamp real de captura del simulador) al ring buffer `frame_history` / `frame_history_ts` y lo trunca al tamaño `VLM_FRAME_HISTORY_SIZE` (default 2). El ring buffer proporciona al VLM el contexto temporal de dos instantes consecutivos, lo que le permite inferir dirección de movimiento a partir de la secuencia de fotogramas.

## 5.5 Nodo `degraded_hover`

**Activación:** `degraded_router` cuando `degraded = True`.
**Salidas:** `next_action = "FRENAR"`, `route = "degraded"`, `flight_status = "degradado"`.

Emite un comando FRENAR sin consultar percepción ni deliberación. El diseño no sustituye el dato faltante de AirSim por un dato sintético plausible: la razón es la misma que motiva el capítulo 9 — un dato sintético es indistinguible de un dato real para el resto del sistema y esconde exactamente el tipo de fallo silencioso que este trabajo documenta.

## 5.6 Nodo `perception`

**Entradas:** `rgb_image`, `prev_image`, `telemetry`, `prev_telemetry`, `velocity_command`, `obstacle_field`, estadísticas de trayectoria.
**Salidas:** `obstacle_field`, `estimated_ttc`, `scene_summary`, `_depth_proximity_m`, `_depth_below_cycles`, `_depth_obstacle_type`.

Invoca `FlowTTCEstimator.estimate()` con el par de frames consecutivos y la telemetría de ambos ciclos. El estimador produce un `ObstacleField` con tres sectores (centro, izquierda, derecha), cada uno con ocupación estimada por flujo óptico, TTC calculado y flag de bloqueo (cap. 6). El nodo escribe además `estimated_ttc = obstacle_field.min_ttc()` y `scene_summary = obstacle_field.summary_text()`.

`perception` no calcula señales de atasco: esas viven en el `StallDetector`, que `navigate` actualiza al entrar (§5.3.1). Tras el flujo óptico, el nodo agrega dos refinamientos y un aviso:

**Profundidad monocular (Depth Anything V2 Metric, [Yang et al., 2024](13-REFERENCIAS.md#ref-yang-2024)).** Cuando el drone avanza (`cmd_vx >= 0.30 m/s`), el flujo óptico reporta corredor libre (`blocked_fraction < 0.25`) y la ruta no es `"evasive"`, se solicita inferencia al `DepthEstimator` (hilo background). Si el resultado es reciente (`depth_age_ms < DEPTH_MAX_AGE_MS = 3000 ms`) y está por debajo del umbral de frenado (`depth_m < DEPTH_BRAKE_M = 5.0 m`) durante ≥ `DEPTH_BELOW_THRESHOLD = 2` ciclos consecutivos, la profundidad se **inyecta directamente en el `ObstacleField`** vía `field.merge_depth_estimate(depth_m, cmd_vx)`. Las tres celdas del sector centro quedan con `occupancy` por encima del umbral de bloqueo y `ttc_s = depth_m / cmd_vx`. El `source` del campo pasa a `"flow+depth"`, visible en `scene_summary`. Este diseño unificado garantiza que el router, el SLM y el logger vean un único campo de percepción coherente sin lógica especial en ninguna capa downstream — la profundidad no crea un path de routing separado.

**Clasificación de tipo de obstáculo.** `DepthEstimator.poll()` devuelve también un `obstacle_type`: `"follaje"` (CV alto + fracción de píxeles lejanos alta, firma de vegetación con huecos) o `"superficie plana"` (CV bajo, firma de muro o pared lisa). Cuando la señal V4 está activa, se añade al `scene_summary` una pista táctica: `"follaje"` sugiere evasión diagonal o +1 m; `"superficie plana"` sugiere evasión lateral amplia. El SLM recibe así contexto sobre la naturaleza del obstáculo sin que el router lo necesite.

**Aviso de obstáculo invisible por contraste campo/historia (G1).** Al final del nodo, si `_traj_frente_stall_rate >= G1_STALL_MIN = 0.20` **y** `_traj_frente_attempts >= G1_ATT_MIN = 3` **y** `blocked_fraction < G1_OCC_MAX = 0.15`, se añade a `scene_summary`:
```
AVISO [G1]: stall frontal 33% (30 intentos) con campo optico despejado
— posible obstaculo invisible (muro liso, baja textura).
MANTENER_RUMBO agravara el bloqueo. Priorizar GIRAR_90 o evasion lateral amplia.
```
El aviso existe porque, en una corrida extendida, el dron quedó contra una malla convexa con `occ = 0.0` y `foe_confidence ≈ 0.08` mientras la tasa de stall frontal era 33–40 %; sin él, el modelo respondía `MANTENER_RUMBO: "Frente libre"`. Llega al VLM en todos los pedidos (táctico y de resolución de atasco).

El `ObstacleField` resultante —potencialmente enriquecido con profundidad monocular— es el único objeto de percepción que consumen la capa reactiva, la resolución de atasco, el prompt del VLM y la FSM. Ningún consumidor accede a campos crudos de flujo óptico ni de profundidad.

## 5.7 Comportamiento reactivo (`reactive_node`)

**Función:** `reactive_node` en `src/agents/reactive.py`.
**Activación:** camino despejado (TTC alto, sin atasco), altitud bajo el piso óptico, o brazo `AGENT_ARM=reactive`.
**Salidas:** `next_action`, `velocity_command`, `route = "reactive"`.

Es el comportamiento más barato del sistema (costo de cómputo nulo: solo lee `waypoint_guidance`). Tres casos:

1. **Misión completada** (`mission_completed` o `guidance["is_completed"]`): emite `FRENAR` y `flight_status = "mision_completada"`.
2. **Waypoint activo disponible**: toma directamente los valores de `waypoint_guidance` producidos por `WaypointTracker.compute_guidance()` (§5.14) — `vx`, `vy`, `vz`, `yaw_rate` ya están calculados para seguir la trayectoria hacia el waypoint — y emite `MANTENER_RUMBO`.
3. **Sin waypoints** (fallback): avanza a `REACTIVE_FORWARD_SPEED` (default 5 m/s) con corrección vertical `-0.1 * vz_actual` para amortiguar deriva vertical.

## 5.8 Comportamiento de evasión (`evasive_node`)

**Función:** `evasive_node` en `src/agents/evasive.py`.
**Activación:** contacto inferido (`imu_contact` / `blind_wall`), TTC en ventana de advertencia (`TTC_SAFE_THRESHOLD`), atasco incipiente (`stuck_invisible` sin escalada) o fallback de baja altitud.
**Salidas:** `next_action`, `velocity_command`, `route = "evasive"`, actualización de `active_maneuver` / `maneuver_cycles_left`.

La continuación de una maniobra ya comprometida no pasa por este comportamiento: `navigate` la ejecuta directamente (§5.3.2, fila 2) y solo la señala con `route = "evasive"`. Este comportamiento decide, por lo tanto, únicamente evasiones **nuevas**.

**Selección del lado con memoria de stalls.** Compara la ocupación efectiva de cada sector lateral, penalizada por la historia de stalls:
```
eff_occ = sector_occupancy(sector) + stall_rate × 0.5
          si stall_rate >= 0.60 y attempts >= 3
```
Los campos `_traj_izq_stall_rate` / `_traj_izq_attempts` y sus equivalentes para `"der"` son publicados por `capture_node` en cada ciclo (vía `FlightTrajectory.zone_stats()`). Si ambos lados tienen stall_rate < 0.60 o `attempts < 3`, la penalización no aplica y la selección es idéntica a la original (occupancy pura). Si solo un lado supera el umbral, se evita ese lado aunque el flujo óptico lo vea despejado. El rationale en logs incluye los valores efectivos: `"eff_occ izq=0.382 vs der=0.004 [traj izq: 75%/4int]"`. En caso de empate final, desempata por TTC (sector con mayor TTC). Elige `EVADIR_IZQUIERDA` o `EVADIR_DERECHA` y llama a `action_to_command()` con `aggressive=True` (velocidad de evasión `vx = 1.2 m/s`).

`action_to_command()` para evasión lateral calcula `target_yaw` redondeado al múltiplo de 90° más cercano (`_manhattan_snap_yaw`), apropiado para la cuadrícula urbana de los escenarios de prueba. El comando resultante tiene `yaw_rate = ±EVASION_LATERAL_YAW_RATE` (15°/s). La maniobra se compromete durante `EVASIVE_MANEUVER_DURATION_S` × `LOOP_HZ` ciclos, guardada en `active_maneuver` / `maneuver_command` para que el router de política la respete.

## 5.9 Giro de 90° (`_dispatch_girar_90`)

**Función:** `_dispatch_girar_90` en `graph.py`.
**Activación:** `navigate` (capa 1) cuando `blocked_fraction() > FOV_BLOCKED_THRESHOLD` (0.6) — el FOV está tan obstruido que cualquier corrección lateral es inútil.
**Salidas:** `next_action = "GIRAR_90"`, `route = "girar_90"`, `flight_status = "exploracion_yaw"`, maniobra comprometida.

Genera un giro de 90° sin traslación. El **lado del giro** se determina en dos pasos:

1. **Historia de stalls laterales.** Si el lado preferido por bearing tiene `stall_rate >= GIRAR90_STALL_THRESHOLD = 0.70` con `>= GIRAR90_MIN_ATTEMPTS = 3` intentos, **y** el lado contrario NO supera ese umbral, se niega el `bearing_err_deg` para girar al lado contrario. Esto evita que el dron repita un giro hacia una zona ya conocida como bloqueada.

2. **Bearing al waypoint (fallback).** Si la historia no es concluyente (ambos lados con stall alto, o sin intentos suficientes), el giro sigue el error de rumbo estándar: waypoint a la izquierda → giro a la izquierda, y viceversa.

El comando usa `yaw_rate = ±20°/s` con `target_yaw` redondeado a la cuadrícula de 90°. La duración es `GIRAR90_DURATION_S` (default 1.0 s) × `LOOP_HZ` ciclos. La maniobra se compromete en `active_maneuver` / `maneuver_cycles_left` para que `navigate` la complete antes de permitir cualquier otra decisión táctica.

## 5.10 Consulta asíncrona al VLM

**Funciones:** `_send_vlm_request`, `_maybe_request_vlm` y `_poll_vlm` (dentro de `graph.py`); `_build_user_prompt`, `_parse_decision`, `_fallback_decision`, `parse_vlm_goal` y `vlm_goal_to_inject_corner` (`src/agents/deliberative.py`); `DeliberationService` (`src/agents/deliberation_service.py`). La consulta al VLM no es un nodo del grafo: es un servicio que la capa 3 de `navigate` (§5.3.5) y el módulo de escaneo (§5.12) utilizan sin bloquear el lazo.

### 5.10.1 Envío del pedido

`_send_vlm_request` construye el *user prompt* con `_build_user_prompt()` a partir del `ObstacleField` (resumen textual por sector, con las pistas de profundidad y el aviso G1 de §5.6), la meta y la altitud, el estado cinemático, avisos de contexto (ciclos sin progreso, tasa de stall frontal de la trayectoria, nivel de vibración del IMU) y una nota del motivo de la consulta que distingue el obstáculo medido de la falta de evidencia perceptual (descripción completa de los componentes en §8.5). Adjunta los fotogramas del `frame_history` (por defecto los instantes `t` y `t−1`), codificados como JPEG en base64 redimensionado a `VLM_IMAGE_MAX_SIZE = 384 px`, y encola el pedido en `DeliberationService.request()`. Guarda el identificador en `slm_request_id`, y el prompt y los fotogramas en `_pending_delib_prompt` / `_pending_delib_frames` para la auditoría. El pedido nunca detiene el vuelo: la función retorna de inmediato y el ciclo continúa por las capas 1 y 2.

### 5.10.2 Recepción: `_poll_vlm` e `_vlm_intention`

En cada ciclo, `_poll_vlm` consulta el servicio con `poll()` (idempotente: no consume el resultado). Si el resultado corresponde al pedido pendiente (`result.request_id == slm_request_id`):

1. Limpia `slm_request_id` y `_deliberation_pending`.
2. Agrega una **entrada completa de auditoría** a `deliberations[]` (`id`, `timestamp`, `arm = "vlm_tactical"`, `prompt`, `raw_response`, `macro_action`, `rationale`, `is_fallback`, `timeout`, `adherent`, `used_json_schema`, `latency_ms`). Se registra también la respuesta inválida (`adherent = False`) para poder auditarla.
3. Si la respuesta es parseable, la deposita en `_vlm_intention` junto con su marca temporal (`_ts`) y su latencia. Si contiene una sub-meta semántica (`VlmGoal`, abajo), la convierte en un `inject_corner`.
4. Traslada fotogramas y prompt al canal de una sola pasada `_last_delib_frames` para que `FlightLogger` los asocie a la fila del ciclo en que la respuesta llegó (§5.18).

La intención **no se aplica al llegar**: queda almacenada y es consumida por la capa que la necesite, con caducidad (5 s en la reacción por TTC, 10 s en la resolución de atasco). Antes de despacharla siempre pasa por `_apply_trajectory_overrides` (§5.12.2), y se pone a `None` al consumirla, de modo que una decisión no se aplica dos veces.

**Sub-meta semántica opcional (`VlmGoal`).** Además de la macro-acción, el esquema JSON admite campos opcionales `dx_m`, `dy_m`, `dz_m` (offset en el marco del cuerpo: adelante, derecha, abajo NED), `confidence`, `semantic_label` y `mode`. Si el VLM los emite con `confidence ≥ VLM_GOAL_MIN_CONFIDENCE = 0.7`, `vlm_goal_to_inject_corner()` rota el offset con el yaw actual y lo convierte en un `inject_corner` (waypoint de desvío en coordenadas NED de mundo), siempre que no haya ya un escape comprometido; se conservan las últimas tres sub-metas para el prompt siguiente.

### 5.10.3 `_fallback_decision()`: heurística determinista

Árbol de decisión sobre el `ObstacleField` cuando el VLM no responde o su respuesta no es parseable:

1. Sin evidencia de percepción → `FRENAR`.
2. Centro + izquierda + derecha bloqueados → `GANAR_ALTURA`.
3. Centro bloqueado + ambos laterales libres → evadir hacia el waypoint por `bearing_err_deg`.
4. Centro bloqueado + un lateral libre → evadir hacia el lado libre.
5. Centro libre → `MANTENER_RUMBO`.

### 5.10.4 `_parse_decision()`: parser tolerante

Red de seguridad para respuestas que no siguen el formato JSON exacto, incluso cuando se usó decodificación restringida (`response_format=json_schema`). Estrategias en cascada: (1) limpia markdown (fences ` ```json`), extrae el primer bloque JSON con regex y parsea con `json.loads()`; (2) reintenta reemplazando comillas simples por dobles; (3) busca `macro_action` con regex de campo nombrado; (4) escanea el texto completo buscando cualquiera de las acciones válidas como substring. Si ninguna produce una acción válida, retorna `None`, lo que activa el fallback determinista o el descarte del pedido.

### 5.10.5 `DeliberationService`: hilo worker asíncrono

`DeliberationService` mantiene un hilo daemon (`threading.Thread`) con una cola de entrada de tamaño 1 (`Queue(maxsize=1)`). `request(payload)` vacía la cola antes de poner el nuevo pedido (garantiza que el worker procese siempre el pedido más reciente, nunca uno obsoleto). `poll()` retorna `(resultado_más_reciente, edad_ms_pedido_pendiente, hay_pedido_pendiente)` con protección de lock. El servicio es único para toda la misión y lo comparten la consulta táctica, el módulo `deep_scan` y el brazo FSM.

La consulta HTTP al servidor (`_query_slm_impl`) intenta primero con `response_format=json_schema` (decodificación restringida, temperatura 0.2, `max_tokens` 200; timeout `SLM_HTTP_TIMEOUT_S = 15 s` en consultas tácticas y `SLM_DEEP_HTTP_TIMEOUT_S = 20 s` en el barrido profundo); si el servidor no soporta el modo o devuelve vacío, reintenta en modo libre y deja el parser tolerante como red de seguridad. El resultado incluye `used_json_schema` para auditoría. Los system prompts se cargan de `config/prompts/` (§8.5).

**Un solo canal, un solo pedido.** Como la cola tiene tamaño 1 y el servicio es compartido, un pedido nuevo (por ejemplo, el del escaneo de resolución de atasco) invalida al que estuviera en vuelo. Esto es deliberado: el pedido más reciente refleja la escena más reciente. Su consecuencia es que un resultado solo se considera vigente si su identificador coincide con el del pedido que espera cada consumidor (`slm_request_id` para el pedido táctico, `_deep_scan_request_id` para el escaneo).

### 5.10.6 Frescura de las respuestas

La coherencia temporal entre la escena sobre la que razonó el VLM y la escena actual se controla por dos medios: la caducidad de `_vlm_intention` (arriba) y el watchdog del escaneo de resolución de atasco (`SLM_DEEP_WATCHDOG_MS = 12 000 ms`). El watchdog es un parámetro calibrado contra la latencia medida (§8.6), no una constante de diseño, y debe mantenerse por debajo del corte HTTP correspondiente para que gane siempre el watchdog.

## 5.11 Nodo `fsm`

**Función:** `fsm_node(state, service)` en `src/agents/fsm.py`.
**Activación:** `AGENT_ARM = "fsm"`, para comparación experimental con el brazo SLM.

La FSM usa exactamente el mismo `ObstacleField`, el mismo vocabulario de macro-acciones y el mismo `action_to_command()` que el brazo SLM. Lo único que cambia es **quién elige la etiqueta de acción**: la FSM lo hace por umbrales deterministas, sin consultar ningún modelo.

**Estados internos y transiciones** (`_decide_state()`):

| Estado FSM | Macro-acción | Condición de transición |
|---|---|---|
| `CRUISE` | `MANTENER_RUMBO` | Centro despejado (default) |
| `AVOID_LEFT` | `EVADIR_IZQUIERDA` | Centro bloqueado/TTC≤3.5s, izquierda menos ocupada |
| `AVOID_RIGHT` | `EVADIR_DERECHA` | Centro bloqueado/TTC≤3.5s, derecha menos ocupada |
| `CLIMB` | `GANAR_ALTURA` | Todos los sectores bloqueados (intento par de escape) |
| `DESCEND` | `PERDER_ALTURA` | Todos los sectores bloqueados (intento impar de escape) |
| `BRAKE` | `FRENAR` | `center_ttc ≤ FSM_TTC_BRAKE_S` (1.5 s), un lateral libre |

La FSM implementa las mismas salvaguardas que el brazo SLM: persistencia de maniobra, alternancia CLIMB/DESCEND en el escape de deadlock, enclavamiento del escape agotado con GIRAR_90 + `inject_corner`, y (si `DEADLOCK_STRATEGY = "deep_vlm"`) delegación al módulo `deep_scan` antes de forzar el escape ciego. En el brazo FSM la resolución de atasco recibe el mismo `FlightTrajectory` y el mismo `DeliberationService` que en el brazo SLM. Esta simetría de salvaguardas es intencional: la comparación SLM vs FSM debe medir **quién elige mejor la acción**, no quién tiene mejor lógica de seguridad.

La diferencia de umbral clave: la FSM usa `FSM_TTC_BRAKE_S = 1.5 s` y `FSM_TTC_AVOID_S = 3.5 s` frente a los umbrales del router de política (`TTC_EVASION_THRESHOLD = 3.2 s`, `TTC_SAFE_THRESHOLD = 4.6 s`) que alimentan el brazo SLM. Esta diferencia existe porque la FSM decide sin información visual ni de dirección: sus umbrales son más conservadores para compensar la falta de contexto semántico.

## 5.12 Módulo de escaneo y evaluación en atasco duro (`deep_scan`)

**Archivo:** `src/agents/deep_scan.py`. Compartido entre los brazos SLM y FSM.
**Activación:** `DEADLOCK_STRATEGY` cuando se detecta atasco duro sin corredor transitable. El modo por defecto es `"slam_assess"` (`DEADLOCK_STRATEGY`). Los modos `"deep_vlm"` (barrido panorámico) y `"blind"` (escape sin VLM) se seleccionan por variable de entorno y sirven de comparación en el diseño factorial del capítulo 10.

El módulo implementa una máquina de estados de cuatro fases, sostenida a través de ciclos consecutivos vía los campos `_scan_*` del `DroneState`:

**Fase `None` (inicialización):** inicializa `_scan_phase = "rotando"`, `_scan_heading_index = 0`, `_scan_frames = []`, `_scan_start_yaw_deg = yaw_actual`. Cancela cualquier maniobra activa.

**Fase `"rotando"`:** comanda `target_yaw = start_yaw + index × (360° / SCAN_HEADING_COUNT_DEEP)` (con `SCAN_HEADING_COUNT_DEEP = 2` en la configuración de producción, los rumbos son +0° y +180° del rumbo de inicio; con 4 serían +0°, +90°, +180° y +270°). La traslación es cero (`vx = vy = vz = 0`). Cuando el yaw actual está dentro de `SCAN_YAW_TOLERANCE_DEG = 5°` del objetivo → transición a `"asentando"`. **Timeout de rotación:** si el dron no puede girar —pata trabada en la malla de un árbol— el contador `_scan_rot_stall` supera `SCAN_ROT_TIMEOUT_CYCLES = 10` (2 s a 5 Hz, por encima del tiempo de un giro libre de 90°), el barrido se abandona con `clear_scan_state()`, se registra `_deadlock_event` con `fell_back_to_blind = True` y el llamador cae al escape sincrónico.

**Fase `"asentando"`:** hover en el rumbo objetivo durante `SCAN_SETTLE_CYCLES_DEEP = 2` ciclos para que la física del simulador estabilice la actitud antes de capturar. Al terminar el asentamiento, captura el frame del `DroneState` (el que `capture_node` ya produjo en este ciclo, **nunca** una nueva llamada a AirSim), guarda la tupla `(heading_deg, rgb_frame, capture_ts)` en `_scan_frames`, avanza `_scan_heading_index` y vuelve a `"rotando"`. Al completar los cuatro rumbos → transición a `"capturado"`.

**Fase `"capturado"`:** construye el prompt del escaneo profundo (`_build_deep_scan_prompt()`) e invoca `service.request()` con los frames codificados como JPEG base64 y etiquetas por rumbo (`"[Rumbo 90.0°] (rumbo actual, el que viene fallando)"`). El modo del pedido es `"deep_scan"`, para que `_query_slm_impl()` use `SYSTEM_PROMPT_DEEP_SCAN` en vez del prompt táctico normal. En ciclos siguientes hace poll hasta que el resultado llegue o el watchdog `SLM_DEEP_WATCHDOG_MS = 12 000 ms` expire.

Si el resultado es una acción válida → `_apply_scan_resolution()`: emite la macro-acción, registra en `deliberations[]` con `arm = "{arm}_deep_scan"`, limpia el estado del escaneo, escribe `_deadlock_event` y pide `_escape_reset`. Retorna `True` al llamador (el escape sincrónico queda descartado este ciclo). Antes de emitir la acción, se aplica `_apply_trajectory_overrides(decision, trajectory, telemetry)` (§5.12.2) y `_apply_scan_resolution()` recibe la trayectoria para dimensionar la maniobra (§5.12.3). El prompt del barrido incluye `RETROCEDER` entre las acciones válidas (`SYSTEM_PROMPT_DEEP_SCAN`).

Si el resultado llega con acción no válida, o el watchdog expira → limpia el estado, escribe `_deadlock_event` con `fell_back_to_blind = True` y retorna `False`. El llamador continúa inmediatamente hacia el escape sincrónico (GANAR_ALTURA / PERDER_ALTURA) como red de seguridad final, **en el mismo ciclo**.

### Modo `slam_assess` (modo por defecto)

A diferencia de `deep_vlm`, el modo `slam_assess` **no realiza rotación panorámica**. En su lugar, envía al VLM el frame frontal del ciclo actual junto con el contexto de trayectoria acumulado generado por `FlightTrajectory.trajectory_context_text()` (§5.12.1). El system prompt (`SYSTEM_PROMPT_SLAM_ASSESS`) instruye al modelo a razonar sobre el historial de intentos/stalls por zona, no sobre el panorama visual de múltiples rumbos.

**Ventaja operacional**: el modo `slam_assess` resuelve el atasco dentro del mismo ciclo, sin incurrir en los 8–20 ciclos del barrido de rotación de `deep_vlm`. No interrumpe el flujo de telemetría ni produce artefactos de percepción por giros en el lugar.

**Limitación**: depende de la acumulación de historia en `FlightTrajectory`. En los primeros 3–5 ciclos de una misión (buffer vacío), el contexto dice "sin datos disponibles aún" y el VLM razona solo con el frame visual. Equivale a `deep_vlm` con un único frame.

### §5.12.1 `FlightTrajectory` y `trajectory_context_text`

`FlightTrajectory` (`src/agents/spatial_history.py`) es un ring buffer de eventos de vuelo (`TrajectoryEvent`) instanciado una vez en `_build_nodes()` y actualizado al inicio de cada ciclo por `capture_node`. Cada evento registra posición, rumbo, acción tomada, Δ distancia al waypoint y si fue stall. El buffer guarda `SLAM_HISTORY_SIZE` eventos (80 en la configuración de producción, ≈ 16 s a 5 Hz; el contexto textual usa como máximo `SLAM_CONTEXT_MAX_EVENTS = 30`).

`trajectory_context_text(current_heading_deg)` agrupa los últimos 30 eventos en cuatro zonas angulares relativas (FRENTE ±30°, IZQUIERDA, DERECHA, ATRÁS) y produce un resumen por zona: intentos, stalls, progreso promedio. Si el progreso promedio de una zona es `< SLAM_MARGINAL_PROGRESS_M = 0.28 m/ciclo`, se emite un ADVERTENCIA de obstáculo invisible incluso cuando hay ciclos con aparente progreso (avance marginal con stalls = firma de muro liso o malla convexa). El texto diferencia dos sub-casos: `stalls == 0` con avance marginal (obstáculo 100% invisible al flujo) vs. `stalls > 0` con avance neto nulo (muro liso con rebotes físicos ocasionales).

`zone_stats(current_heading_deg)` devuelve el mismo desglose como dict `{zona: {"attempts", "stall_rate", "delta_sum", "avg_prog"}}` (con `avg_prog = -delta_sum / attempts`, el mismo criterio que `trajectory_context_text`), usado directamente por `capture_node` para publicar `_traj_frente_stall_rate` / `_traj_izq_stall_rate` / `_traj_der_stall_rate` en el estado del grafo cada ciclo.

Durante todo el barrido, `_deliberation_pending = True` congela el contador `evasion_stuck_cycles` para que `main.py` no lo resetee por accidente mientras el dron gira en el lugar.

### §5.12.2 Overrides deterministas de trayectoria (`_apply_trajectory_overrides`)

El VLM decide con un único fotograma frontal y, por construcción, no ve los obstáculos que el flujo óptico tampoco ve. La historia de zonas de `FlightTrajectory` sí los delata (stall alto, avance marginal). Por eso toda decisión de escape del VLM pasa por una capa determinista que la contrasta con esa historia antes de despacharla. Se aplica en `slam_assess`, en `deep_vlm` (salvo en el escaneo posterior a un retroceso, §5.12.3), a la intención proactiva del VLM que consume `navigate` (§5.10.2) y antes de despachar una decisión guardada en `_vlm_intention`. Las reglas se evalúan en este orden y la primera que dispara devuelve su acción:

| Override | Condición (estadísticas por zona sobre los últimos eventos) | Acción forzada |
|---|---|---|
| **1a** | FRENTE con stall ≥ 70 %, e IZQUIERDA y DERECHA con ≥ 3 intentos y stall ≥ 70 % | `RETROCEDER` (tres zonas bloqueadas) |
| **1b** | FRENTE con stall ≥ 90 % y ≥ 20 eventos, sin intentos laterales | `RETROCEDER` (dron inmovilizado: `EVADIR` se ejecutó pero no pudo rotar, así que los eventos siguen en la zona FRENTE) |
| **1c** | FRENTE con stall ≥ 90 % y ≥ 20 eventos, laterales sin intentos o con stall ≥ 70 % | `RETROCEDER` (cierra el hueco entre 1a y 1b: laterales intentadas una o dos veces y fallidas) |
| **3a** | El VLM propone `MANTENER_RUMBO` o `EVADIR_*`; FRENTE con ≥ 3 intentos y avance medio < `SLAM_MARGINAL_PROGRESS_M` (0.28 m/ciclo); altitud ≤ `SLAM_CEILING_ALT_MAX_M` (7.5 m); laterales sin rotar | `PERDER_ALTURA` (firma de techo: autopista elevada o estructura horizontal) |
| **3b** | Igual que 3a pero sin cumplir la condición de techo | `EVADIR_IZQUIERDA` si la izquierda no se probó; si no, `EVADIR_DERECHA`; si ambas se probaron, `GIRAR_90` (firma de muro o árbol) |
| **2** | El VLM propone `GANAR_ALTURA` o `PERDER_ALTURA`; FRENTE con stall ≥ 70 %; algún lateral sin explorar | `EVADIR` hacia el lateral sin explorar (*lateral-first*: no escalar en vertical antes de probar los costados) |

El Override 3 discrimina por altitud y no por tasa de stall porque `EVADIR_*` estrafa sin rotar: sus eventos quedan registrados en la zona FRENTE e inflan `frente_stall_rate` a 0.40–1.00 incluso bajo un techo, sin choque frontal real. La altitud de crucero bajo la autopista elevada de CitySim es ~6 m; el umbral de 7.5 m la cubre. La regla actúa sobre `MANTENER_RUMBO` y sobre `EVADIR_IZQUIERDA` / `EVADIR_DERECHA` porque un `EVADIR` sin rotación real es tan inútil como `MANTENER_RUMBO`: el dron se desplaza lateralmente sin girar y el bloqueo no se resuelve. Validación sobre corridas piloto:

| Caso | Stall FRENTE | Sub-rama de Override 3 |
|---|---|---|
| Autopista elevada de CitySim (c449) | 0.0 % | 3a → `PERDER_ALTURA` |
| Estructura final de TownSim (c1121) | 6.7 % | 3a → `PERDER_ALTURA` |
| Edificio de TownSim (sesión 3, 2000 ciclos) | 40 % | 3b → `EVADIR` lateral |

Los tres casos provienen de corridas de depuración (n = 1 por caso) y sirvieron para fijar el umbral; no constituyen validación estadística.

### §5.12.3 `RETROCEDER`, esquina post-retroceso y control de bucles de evasión

`RETROCEDER` es la octava acción del vocabulario del sistema (§5.14) y la respuesta al caso en que las tres zonas frontales están cerradas. Se ejecuta durante `MANEUVER_DURATION_S × RETROCEDER_DURATION_FACTOR` (2.0 s × 2.5 = 5 s, ≈ 6 m a 1.2 m/s): un retroceso de 3 m resultó insuficiente para salir de la «burbuja» de colisión de 4–5 m de radio de una malla de árbol, y el dron volvía al mismo árbol en todos los casos observados. Si la historia registra stalls en la zona ATRÁS (≥ 2 intentos, ≥ 70 %), el factor se reduce a 1.5 para no chocar contra un obstáculo trasero. La duración de las maniobras `EVADIR_*` y de escape vertical también es adaptativa: ×2 con stall frontal ≥ 70 % y ×1.5 con stall ≥ 50 %, siempre a la velocidad estándar (0.8 m/s): la evasión agresiva (1.2 m/s) se descartó porque el estrafeo a alta velocidad junto a fachadas con molduras en pasillos urbanos estrechos producía contactos.

**Retroceso previo al barrido (`deep_vlm`).** Antes de iniciar un barrido panorámico, el dron retrocede: un barrido de varios segundos en hover pegado a una fachada deriva físicamente contra ella. El retroceso da distancia segura y una vista despejada para el VLM. Esa acción marca `_post_retroceder_corner_pending` y el barrido comienza en el ciclo siguiente a su finalización.

**Esquina post-retroceso.** Al despachar `RETROCEDER` **no se inyecta una esquina a ciegas** (una esquina fija a 90° podía llevar al dron contra otro obstáculo): se marca `_post_retroceder_corner_pending` y se espera al escaneo siguiente, que ve la escena despejada tras el retroceso. Cuando esa segunda consulta elige una acción lateral, el sistema inyecta un waypoint de esquina a `CORNER_OFFSET_M` metros (30 m en la configuración de producción; 12 m por defecto en código), calculado así:

```
bearing_to_wp = yaw_actual + bearing_err_deg          # rumbo absoluto al waypoint
corner_yaw    = bearing_to_wp ± 90°                    # perpendicular al camino
signo         = +1 si el VLM dijo EVADIR_IZQUIERDA, -1 en otro caso   # lado OPUESTO
```

Dos decisiones no obvias. Primero, la referencia angular es el rumbo *al waypoint* y no el rumbo del dron: el rumbo al waypoint solo cambia cuando el dron se desplaza, no cuando rota, mientras que el yaw del dron puede distar ~90° del camino real. En el caso que motivó el diseño (`citysim_pilot`, ciclo 1703) el dron apuntaba al norte (−9°) con el waypoint al oeste (−88°); una esquina calculada sobre el yaw caía dentro de la fachada del edificio y el dron oscilaba a 12.8 m de ella indefinidamente. Segundo, el lado se **invierte** respecto del que sugiere el VLM: el modelo percibe apertura visual en la dirección de la cámara, que cuando el rumbo está desfasado del camino suele ser el lado paralelo a la fachada bloqueante; el lado opuesto es el que queda libre en el plano del waypoint. La inversión está verificada geométricamente en un caso (esquina en (72, −110), al norte del edificio) y no está validada estadísticamente. Si tras el retroceso el VLM vuelve a pedir `RETROCEDER`, el sistema lo interpreta como esquina cerrada y fuerza `GANAR_ALTURA`: sin esa ruptura, el barrido posterior veía paredes, el VLM recomendaba `RETROCEDER` de nuevo y el ciclo se repetía hasta el timeout de la corrida. En el escaneo posterior a un retroceso, las estadísticas de trayectoria acumuladas (muchos `EVADIR` fallidos previos) dispararían el Override 1a aunque el dron ya se hubiera alejado del muro; por eso ese escaneo confía en la vista fresca del VLM y **no aplica los overrides**.

**Detección de bucles de evasión.** El escaneo lleva el último lado de evasión despachado (`_scan_last_evadir_dir`) y un contador de repeticiones (`_scan_evadir_count`). Cuando el VLM alterna de lado (`DERECHA → IZQUIERDA` o viceversa) o repite el mismo lado `SCAN_EVADIR_REPEAT_LIMIT` (2) veces seguidas sin progreso al waypoint, la decisión se escala a `RETROCEDER`: ambas firmas indican que las evasiones laterales no rompen el bloqueo. Los contadores se reinician cuando un escape resuelve el atasco.

**Registro de escaneos fallidos.** Un escaneo que no resuelve (respuesta sin acción viable o watchdog expirado) deja una entrada auditable en `deliberations[]` (`arm = "deep_scan_failed"`, con el prompt, la respuesta cruda si la hubo y el motivo) y expone sus fotogramas por `_last_delib_frames`: son justamente los casos que más interesa auditar.

## 5.13 Nodo `motor`

**Función:** `motor_node` en `graph.py`. Único nodo que interactúa con el actuador.
**Entradas:** `velocity_command`, `telemetry`.
**Salidas:** emisión de comando a AirSim, actualización de `last_deliberation`, corrección de `_hover_alt_anchor`.

Lee `velocity_command` del estado (producido por `navigate` o por `degraded_hover`). Manejo especial para `FRENAR`:

- En el **primer ciclo** de FRENAR, ancla `_hover_alt_anchor = current_z` (coordenada Z de la posición NED actual).
- En **ciclos siguientes** de FRENAR, computa `dz = anchor - current_z` y, si `|dz| > HOVER_ALT_DEADZONE_M = 0.3 m`, inyecta `vz = clamp(HOVER_ALT_KP × dz, ±HOVER_ALT_MAX_VZ)` con `HOVER_ALT_KP = 0.35` y `HOVER_ALT_MAX_VZ = 0.8 m/s`. Este controlador P corrige la deriva vertical que ocurre cuando `moveByVelocityBodyFrameAsync(vz=0)` se reemite repetidamente (medido: hasta 9 m de deriva en 120 s de FRENAR sostenido sin corrección).
- En cualquier otro comando, limpia `_hover_alt_anchor = None`.

Finalmente llama a `airsim_client.execute_velocity(vx, vy, vz, yaw_rate, target_yaw)`. Cuando `target_yaw` no es `None`, AirSimClient usa `YawMode(is_rate=False, yaw_or_rate=target_yaw)` (orientación absoluta); cuando es `None`, usa `YawMode(is_rate=True, yaw_or_rate=yaw_rate)` (velocidad angular).

## 5.14 Mapa de macro-acciones (`action_to_command`)

Todos los comportamientos (reactivo, evasivo, giro, escape, FSM y escaneo) comparten `action_to_command()` (`src/agents/action_map.py`) como fuente única de verdad para la cinemática de cada macro-acción. Esto garantiza que `GANAR_ALTURA` tenga la misma velocidad vertical ya sea que lo elija el VLM, la FSM o el escape sincrónico.

| Macro-acción | `vx` (m/s) | `vy` | `vz` (m/s) | `yaw_rate` (°/s) | `target_yaw` |
|---|---|---|---|---|---|
| `MANTENER_RUMBO` | guidance | 0 | guidance | guidance | None |
| `EVADIR_DERECHA` | 1.2 (agg.) / 0.3–0.8 | 0 | guidance | +15 | snap 90° dcha. |
| `EVADIR_IZQUIERDA` | 1.2 (agg.) / 0.3–0.8 | 0 | guidance | −15 | snap 90° izq. |
| `GANAR_ALTURA` | 0 | 0 | −`EVASION_UP_SPEED` (1.5) | guidance | None |
| `PERDER_ALTURA` | 1.0 | 0 | +`EVASION_DOWN_SPEED` (0.8) | 0 | None |
| `GIRAR_90` | 0 | 0 | 0 | ±20 | snap 90° hacia WP |
| `RETROCEDER` | −`EVASION_BACK_SPEED` (1.2) | 0 | guidance | 0 | None (rumbo congelado) |
| `FRENAR` | 0 | 0 | 0 | 0 | None |

`RETROCEDER` usa `yaw_rate = 0` con `vx < 0`: `execute_velocity` detecta la marcha atrás y congela el rumbo (`MaxDegreeOfFreedom` con tasa cero). Con el modo por defecto para `yaw_rate = 0` (`ForwardOnly`), AirSim gira la proa hacia la dirección de traslación en el marco de mundo y el dron completaba un giro de ~180° en lugar de retroceder (confirmado en corridas de diagnóstico). No está en `PROMPT_ACTIONS` del nodo deliberativo regular —el enum del esquema JSON no la admite— pero sí en el del barrido `deep_vlm`/`slam_assess` y en los overrides deterministas (§5.12.2).

`GANAR_ALTURA` usa `vx = 0` (asciende en el lugar) y sin deriva lateral: un desplazamiento lateral constante alejaría el waypoint en el plano XY, la misma métrica que mide si el atasco se resolvió, y produciría un escape que se retroalimenta a sí mismo.

## 5.15 Guiado a waypoint: `WaypointTracker`

`WaypointTracker` (`src/navigation/waypoint_tracker.py`) corre en el bucle externo (`main.py` / `experiments/runner.py`) **fuera del grafo**, una vez por ciclo, antes de invocar `graph.invoke()`. Produce `waypoint_guidance` que `navigate` consume para orientarse.

`compute_guidance()` calcula `vx`, `vy`, `vz`, `yaw_rate` en Body Frame hacia el waypoint activo, con:
- Corrección de rumbo por cross-track error y error de yaw.
- Zona muerta angular: desvíos menores a un umbral no generan corrección de yaw para evitar oscilaciones.
- Saturación de tasa de yaw diferenciada: tasa de giro suave para desvíos pequeños, tasa brusca para desvíos grandes.
- Suavizado EMA sobre los comandos de guiado para reducir cabeceos.
- Comportamiento `near_vertical`: si `dist_xy < 1 m` y `|dz| > 0.3 m`, fuerza `vx = 0` para ascenso/descenso puramente vertical. Imprescindible para el patrón *climb-first* de Tier 2 (§3.2).

### 5.15.1 Contador de progreso

`record_progress(dist_xy, bearing_err_deg)` actualiza `evasion_stuck_cycles`:
- Si `dist_xy` disminuyó en más de `WAYPOINT_PROGRESS_EPS_M` respecto al mínimo visto → resetea el contador, actualiza el mínimo y cancela la racha de exenciones.
- Si `|bearing_err_deg| > PROGRESS_STALL_BEARING_EXEMPT_DEG` (30°) → el ciclo se exime (el dron está girando activamente hacia el waypoint, no atascado), pero solo hasta `PROGRESS_STALL_BEARING_EXEMPT_MAX_CYCLES = 15` ciclos consecutivos.
- En caso contrario → incrementa `evasion_stuck_cycles`.

La racha de exenciones se cancela **únicamente con progreso real** hacia el waypoint, no cuando el error de rumbo baja momentáneamente del umbral (por ejemplo durante un `GIRAR_90`): si se cancelara con el giro, cada maniobra de rotación renovaría el tope y un dron que gira contra una fachada sin acercarse al waypoint podría eximirse indefinidamente. Aun así, un contador basado en error de rumbo puede quedar congelado cuando el dron roza una fachada en diagonal (todos los ciclos son «exentos»); por eso el `StallDetector` mantiene un contador de progreso neto independiente del rumbo (`wp_no_progress`, §5.3.1).

### 5.15.2 Umbrales de atasco

`effective_stall_threshold()` calcula el umbral mínimo de ciclos sin progreso que es **físicamente demostrable**: `eps_m / (min_speed × 1/loop_hz)`. Con los defaults (`eps_m = 0.5 m`, `min_speed = 0.25 m/s`, `loop_hz = 5`), el umbral coherente es 10 ciclos. `hard_stall_threshold()` es `STUCK_HARD_FACTOR` veces ese valor, a partir del cual el escape se fuerza aunque la percepción crea ver un corredor libre. El factor por defecto en código es 3.0 (30 ciclos, 6 s), pero la configuración de producción lo fija en **1.5** (15 ciclos, 3 s a 5 Hz): con 3.0, en una corrida de diagnóstico el dron tardó 254 ciclos en llegar al primer `RETROCEDER` y ya estaba físicamente embebido en la malla del árbol; con 1.5 el escape se activa antes de la embebida.

### 5.15.3 Detección de techo

Con un waypoint a altitud fija bajo una estructura horizontal (la autopista elevada de CitySim, con un techo físico a ~6 m frente a un waypoint a 10 m), la corrección de altitud del guiado empuja siempre hacia arriba contra la losa y el rozamiento anula toda evasión lateral (en una corrida de diagnóstico, 1360 de 1399 ciclos dentro de una caja de ~5 m). El tracker lo detecta observando la altitud: si durante `CEILING_DETECT_CYCLES` (10) ciclos seguidos se demanda ascenso (`vz < −0.3 m/s`, con altitud ≥ `CEILING_MIN_ALT_M` = 3 m) y la cota no varía más de `CEILING_DETECT_DZ_M` (0.15 m), declara un techo en esa cota y limita la altitud objetivo a `ceiling_z + CEILING_MARGIN_M` (1 m por debajo). El techo se libera al alejarse `CEILING_RELEASE_M` (15 m) del punto de detección o al cambiar de waypoint. El valor `ceiling_z` se publica en `waypoint_guidance`, y el escape vertical (§5.3.4) lo usa para no comandar `GANAR_ALTURA` contra la losa.

### 5.15.4 Cadena de esquinas

Una esquina inyectada (`inject_corner`, §5.12.3) saca al dron del punto de contacto, pero el waypoint siguiente suele seguir apuntando contra el mismo edificio (en un caso observado, la esquina en (102, −126) y de ahí recta al waypoint 3, cuya recta pasaba exactamente por la fachada del otro lateral). El tracker registra los **puntos de contacto** (`record_contact`, invocado por el bucle externo cuando se resuelve un atasco; se fusionan los contactos a menos de `CONTACT_MERGE_M` = 3 m). Al alcanzar una esquina, si el tramo hacia el siguiente waypoint real pasa a menos de `CORNER_CHAIN_CLEARANCE_M` (10 m) de un contacto, inserta otra esquina temporal `CORNER_CHAIN_k` a `CORNER_CHAIN_STEP_M` (12 m por defecto, hasta `CORNER_CHAIN_MAX` = 4 por waypoint objetivo) hacia el lado contrario al contacto; si el lado elegido cae sobre otro contacto (a menos de 6 m), usa el opuesto, y si el contacto está sobre la recta, sigue el sentido de giro de la esquina previa. Los contactos y la cadena se limpian al alcanzar un waypoint real. Se desactiva con `CORNER_CHAIN_ENABLED=false`.

## 5.16 Salvaguardas y contratos de diseño

**Principio de deliberación por excepción.** La mayoría de los ciclos deben resolverse por el comportamiento reactivo o el evasivo (deterministas y de costo casi nulo). El VLM solo se consulta cuando hay evidencia clara de riesgo o atasco. En las corridas de validación sobre CITYSIM_CLEAR (brazo SLM), la tasa de ciclos deliberativos fue menor al 20% del total.

**Exclusión total de profundidad.** Ningún nodo del grafo pide el canal de profundidad de AirSim. El esquema `DroneState` actúa como segunda red de esta guardia: cualquier clave que intente transportar datos de profundidad entre invocaciones es descartada en silencio por LangGraph si no está declarada. El test estático `tests/test_no_depth_in_flight_path.py` verifica esta propiedad sin necesitar AirSim.

**Contrato de `deliberations[]`.** Es de solo agregado: se le suman entradas pero nunca se borran campos. Los análisis del capítulo 10 y el capítulo 9 se derivan de este registro.

**Cliente AirSim como singleton.** `compile_workflow(airsim_client)` recibe un cliente ya conectado (inyección de dependencia). Hay un único cliente por proceso: un segundo cliente tendría su propio `takeoffAsync`, desconectado del grafo real.

## 5.17 Modo degradado

Cuando `degraded = True` (AirSim no disponible), el sistema no sustituye el dato faltante por uno sintético plausible: el ciclo va directo a `degraded_hover`, se comanda hover explícito y se omiten percepción y deliberación por completo. La razón de este diseño es la misma que motiva el capítulo 9: un dato sintético "razonable" en lugar de un dato ausente es indistinguible, para el resto del sistema, de un dato real, y esconde exactamente el tipo de fallo silencioso que este trabajo documenta.

## 5.18 Registro de vuelo y auditoría post-vuelo

Cada ejecución del lazo táctico —tanto la de `main.py` como la de cada celda del ejecutor de experimentos— genera una carpeta autocontenida `<escenario>/<brazo>/<estrategia>/seed_N_<timestamp>/` (descripción de la estructura en §4.4), con traza JSONL y CSV, resumen por waypoint, fotogramas de auditoría del VLM, video anotado (`.webm`) y visor HTML. La traza es el contrato de evidencia primaria del que se derivan las métricas del capítulo 10 y el análisis de modos de falla del capítulo 9.

**Traza completa del `DroneState`.** El JSONL conserva por ciclo el `DroneState` anidado completo (sin imágenes), serializado por `src/logging/state_serializer.py`. El CSV es plano, sin campos JSON: los campos escalares del estado se aplanan como columnas `state.<ruta>` (diccionarios con punto, listas cortas como `.0 .1`, listas de diccionarios como `state.waypoints.0.x`; las listas largas quedan como un único valor JSON). Como el conjunto de columnas `state.*` solo se conoce al final de la corrida (~220 en el brazo `slm`), el CSV se escribe en streaming con las columnas fijas y se reescribe completo al cerrar el registrador. La latencia por ciclo se desagrega en `latency_graph_ms` y `latency_telemetry_ms`. La telemetría incluye `landed_state` de AirSim (0 = en tierra, 1 = en vuelo), diagnóstico pasivo del dron «posado» sobre una moldura de fachada, que queda con pitch y roll nulos exactos y no ejecuta comandos de velocidad.

**Auditoría del VLM.** Cada consulta resuelta deja una entrada en `deliberations[]` con el prompt, la respuesta cruda y la latencia, y los fotogramas RAW se asocian a la fila del ciclo en que la respuesta llegó (canal de una sola pasada `_last_delib_frames`). Los escaneos fallidos también se registran (§5.12.3).

**Video en un hilo aparte.** La codificación VP8 ([Bankoski et al., 2011](13-REFERENCIAS.md#ref-bankoski-2011)) del video se ejecuta en un hilo con cola acotada (`FLIGHT_VIDEO_QUEUE_MAX = 300`) y el cuadro se reduce a `FLIGHT_VIDEO_SCALE = 0.6`. La razón es de control, no de comodidad: codificar a 1080×720 dentro del lazo costaba ~275 ms por cuadro y llevaba el período del ciclo de 0.21 s a 0.45 s. Con ese período, el estimador de flujo óptico quedaba degradado en el 64–82 % de los ciclos y el control daba tirones mayores (|Δ pitch| de 3–5° por ciclo frente a 0.1–2° con ciclo de 0.20 s), lo que producía evasiones espurias. Con el hilo, `write_frame` bloquea ~0.03 ms y el codificador sigue el ritmo del lazo (~0.07 MB por cuadro). El overlay del video (`src/logging/flight_overlay.py`) es común a `main.py` y al ejecutor de experimentos y agrega `ceil=` cuando el tracker detectó un techo.

**Visor HTML.** Sincroniza en ambos sentidos el video con la traza por **índice de ciclo** (no por tiempo de video, que deriva respecto del reloj de simulación) y muestra el árbol colapsable del `DroneState` de cada ciclo, leído del JSONL. Un fallo de grabación de video o visor nunca interrumpe el vuelo.

## 5.19 Cierre de misión y seguridad de proximidad

**Aterrizaje suave (`land_smooth`).** Al completar la misión, `main.py` y el runner de experimentos llaman a `AirSimClient.land_smooth()` en lugar de `land()`. Con `landAsync()` invocado desde la altura de crucero (~10 m) SimpleFlight producía una caída libre; la secuencia actual es: (1) 1.5 s de hover para anular la velocidad horizontal; (2) descenso con `moveToZAsync` a `LAND_DESCENT_SPEED_MPS = 0.5 m/s` hasta z = −0.3 m NED, con un timeout proporcional a la distancia; (3) `armDisarm(False)` desde 30 cm de altura. Ante cualquier excepción desarma igualmente. A 0.5 m/s el descenso desde 10 m tarda ~20 s.

**Aborto por proximidad crítica (`DEPTH_EMERGENCY`).** El runner de experimentos mide la distancia mínima al obstáculo con la cámara de profundidad del simulador **solo como métrica de evaluación** (nunca como entrada del lazo de vuelo, §5.16) y aborta la corrida si el dron está físicamente embebido en la malla: distancia mínima < `DEPTH_EMERGENCY_DIST_M` **y** velocidad < `DEPTH_EMERGENCY_MAX_SPEED_MPS`. La condición de velocidad es necesaria: sin ella, un umbral de distancia holgado dispararía durante la navegación normal al aproximarse a un obstáculo y abortaría corridas válidas. En las corridas piloto de TownSim el dron llega naturalmente a ~10 cm de los árboles (mínimo registrado: 0.104 m en una corrida exitosa) y se recupera, por lo que los umbrales son `DEPTH_EMERGENCY_DIST_M = 0.05 m` y `DEPTH_EMERGENCY_MAX_SPEED_MPS = 0.10 m/s`: solo dispara si la profundidad medida es prácticamente nula con el dron detenido. Poner `DEPTH_EMERGENCY_DIST_M=0.0` deshabilita el chequeo.


