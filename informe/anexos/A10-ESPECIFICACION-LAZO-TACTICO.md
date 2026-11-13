# Anexo 10: Especificación del lazo táctico: estado, nodos, máquinas de estado y umbrales

El capítulo 5 presenta la arquitectura del lazo táctico en el nivel necesario para seguir el argumento de la tesis: los dos lazos desacoplados, la política de `navigate`, la capa estratégica con sus sub-metas ancladas, el barrido de atascos y las salvaguardas. Este anexo reúne la especificación de implementación que lo sostiene: los campos del estado compartido, las señales de atasco con sus umbrales, el detalle de cada nodo y comportamiento, el mapa de macro-acciones, el gobernador de velocidad, el servicio de deliberación, la máquina de estados del barrido, el `WaypointTracker`, el registro de vuelo y el cierre de misión. Los valores de las variables de entorno están en el Anexo 6 (IT.A6.3). NB3 ejecuta este código sin AirSim: compila el grafo, dispara cada regla de `navigate` con un estado construido a mano y reproduce las decisiones de una corrida de la v4 desde su registro.

---

## A10.1 Escaneo espacial pre-vuelo (`spatial_scan`)

Antes de entrar al lazo, `main.py` llama de forma bloqueante a `run_initial_scan()` (`src/agents/spatial_scan.py`). No es un nodo del `StateGraph`: se ejecuta una sola vez, entre la conexión con AirSim y la compilación del grafo. Realiza un barrido de yaw en el lugar hacia `SCAN_HEADING_COUNT` (6) rumbos equiespaciados, captura un fotograma por rumbo y envía todas las imágenes en una única consulta al VLM, que devuelve un contexto cualitativo de la escena y un rumbo recomendado.

Con la configuración por defecto es la única consulta al VLM que hace `main.py`, y el resultado es **solo un chequeo de cordura del plan de misión**: si el rumbo recomendado difiere más de 90° del rumbo al primer waypoint, `main.py` emite un aviso por consola. No se transfiere al grafo ni modifica el vuelo. El ejecutor de experimentos (`experiments/runner.py`) **no** lo ejecuta, de modo que no interviene en ninguna corrida experimental. Si el VLM no responde, la misión arranca igual.

---

## A10.2 El estado compartido: `DroneState`

`DroneState` (`graph.py`) es el único canal de comunicación entre nodos y entre el grafo y el bucle externo.

**Datos sensoriales y percepción:**

| Campo | Tipo | Descripción |
|---|---|---|
| `rgb_image` / `prev_image` | `ndarray` | Fotograma del ciclo actual y del anterior (el par que usa el flujo óptico) |
| `frame_history` / `frame_history_ts` | `List` | Ring buffer de `VLM_FRAME_HISTORY_SIZE` fotogramas (1 en producción) con sus timestamps de captura |
| `telemetry` / `prev_telemetry` | `Dict` | Posición NED, velocidad, orientación, colisión, `landed_state`, timestamp y `source` |
| `degraded` | `bool` | `True` si AirSim no respondió este ciclo |
| `obstacle_field` | `ObstacleField` | Contrato único de percepción (cap. 6) |
| `estimated_ttc` / `scene_summary` | `float` / `str` | Derivados del campo, para logging y overlay |

**Misión y guiado** (los escribe el bucle externo): `waypoints`, `current_wp_index`, `target_waypoint`, `waypoint_guidance` (salida de `WaypointTracker.compute_guidance()`), `mission_completed`, `evasion_stuck_cycles` (contador de progreso del tracker; lo usa el brazo `fsm`).

**Decisión y actuación:**

| Campo | Tipo | Descripción |
|---|---|---|
| `next_action` | `str` | Macro-acción del ciclo |
| `velocity_command` | `Dict` | `{macro_action, vx, vy, vz, yaw_rate, target_yaw, rationale}` para `motor_node` |
| `route` | `str` | Origen del comando: `reactive`, `evasive` (incluye continuación de maniobra), `girar_90`, `tactical` (escape de deadlock sin VLM), `deliberative` (barrido), `fsm`, `degraded` |
| `flight_status` | `str` | Estado textual para logging y overlay |
| `active_maneuver` / `maneuver_cycles_left` / `maneuver_command` | — | Maniobra comprometida (anti flip-flop) |
| `_hover_alt_anchor` / `_speed_cap` | `float\|None` | Ancla de altitud en `FRENAR` y tope del gobernador de velocidad (IT.A10.5) |

**Lazo lento y canales hacia el bucle externo:**

| Campo | Tipo | Descripción |
|---|---|---|
| `deliberations` | `List[Dict]` | Registro de solo agregado de todas las consultas del lazo lento, a la profundidad o al VLM (estratégicas, de barrido y fallidas) |
| `last_deliberation` | `Dict\|None` | Última entrada, actualizada por `motor_node` |
| `_vlm_strategic` | `Dict\|None` | Último resultado de la capa estratégica: `outcome`, motivo, latencia, sector de la meta, ancla y sub-meta (IT.5.5) |
| `_clear_subgoals` | `bool` | La capa estratégica vio libre el camino directo al waypoint real: el bucle externo descarta la sub-meta pendiente (IT.A10.8.4) |
| `inject_corner` | `Dict\|None` | Sub-meta `{x, y, z, label}` en coordenadas del mundo que el bucle externo inserta en el tracker (IT.A10.8.4) |
| `_deliberation_pending` | `bool` | `True` durante un barrido: el bucle externo no cuenta esos ciclos como falta de progreso |
| `_pending_delib_prompt` / `_pending_delib_frames` / `_last_delib_frames` | — | Auditoría: prompt y fotogramas enviados; `_last_delib_frames` es un canal de una sola pasada hacia `FlightLogger` |

**Deadlock y barrido panorámico:**

| Campo | Tipo | Descripción |
|---|---|---|
| `_escape_reset` | `bool` | Señal de flanco: el bucle externo llama a `WaypointTracker.reset_progress()` en el ciclo en que un deadlock se resuelve |
| `_deadlock_cycles` | `int` | Ciclos dentro del deadlock en curso |
| `_deadlock_event` | `Dict\|None` | Métricas de resolución (estrategia, resuelto por el barrido o no, respuesta cruda, sub-meta), consumidas por `FlightLogger` |
| `_scan_phase` | `str\|None` | `rotando` \| `asentando` \| `capturado` \| `None` |
| `_scan_heading_index` / `_scan_start_yaw_deg` / `_scan_settle_left` / `_scan_rot_stall` | — | Progreso del barrido |
| `_scan_frames` | `List` | `[(rumbo_medido_deg, frame, capture_ts)]` |
| `_deep_scan_request_id` / `_deep_scan_request_ts` / `_scan_started_ts` | — | Pedido del barrido en vuelo |

**Señales del `StallDetector`** (publicadas solo para logging, IT.A10.3): `imu_jitter_level`, `imu_contact_event`, `blind_wall_event`, `_stopped_cycles`, `_wp_no_progress_cycles`. El bucle externo agrega `_freeze_cycles` (vigilante de congelamiento físico, IT.A10.9.2).

---

## A10.3 `StallDetector`: señales de atasco

Los contadores de atasco viven en un objeto `StallDetector` (`src/agents/stall_detector.py`) que persiste entre invocaciones. En cada ciclo, `update(state)` actualiza cuatro señales y `publish(state)` las escribe en el estado solo para logging.

| Señal | Condición | Umbral | Uso en `navigate` |
|---|---|---|---|
| `imu_contact` | RMS de la aceleración lateral ≥ `IMU_CONTACT_THRESHOLD_MPS2` (5 m/s²) con velocidad comandada > 0.3 m/s | ≥ 2 ciclos | Regla 4: evasión inmediata |
| `blind_wall` | Avance comandado (`vx ≥ 0.45 m/s`) con velocidad medida < 0.30 m/s, campo óptico con corredor libre (`blocked_fraction < 0.25`) y el dron moviéndose en el ciclo previo | ≥ 2 ciclos | Regla 4: evasión inmediata |
| `stopped_prolonged` | **Se ordenó avanzar** (velocidad horizontal comandada ≥ `STOPPED_MIN_CMD_MPS` = 0.30 m/s) y la velocidad medida es < 0.10 m/s; no cuenta bajo el piso óptico ni durante el despegue | ≥ `STOPPED_DELIBERATIVE_CYCLES` = 10 ciclos | Regla 2: deadlock (trabado) |
| `wp_no_progress` | La distancia al objetivo actual no mejora `WP_NO_PROGRESS_MIN_M` (2 m); se reinicia al cambiar el objetivo, durante un barrido, con `_escape_reset`, bajo el piso óptico y durante el despegue | ≥ `WP_NO_PROGRESS_THRESHOLD` = 50 ciclos (10 s) | Regla 2: deadlock (sin progreso) |

Tres decisiones de diseño:

- **«Detenido» significa «se le ordenó moverse y no se movió».** Durante el despegue, el guiado ordena subir y girar en el lugar hacia el primer waypoint con `vx = 0` durante ~3 s; un contador que sumara cualquier ciclo sin velocidad horizontal declararía un deadlock al cruzar el piso óptico (Anexo 11, IT.A11.4.1). Girar, subir o mantener un hover a propósito no es estar trabado.
- **La velocidad se mide por desplazamiento, no se lee de la telemetría.** Con el dron apoyado contra una estructura, AirSim reporta una velocidad cercana a la comandada aunque la posición no cambie (Anexo 11, IT.A11.4.4). `stopped_prolonged` y `blind_wall` usan la velocidad horizontal calculada con la diferencia de posición entre ciclos consecutivos.
- **El objetivo se identifica por su etiqueta y posición, no por su índice.** Una sub-meta se inserta en el mismo índice que el waypoint al que precede (IT.A10.8.4); identificar el objetivo por índice heredaría la «mejor distancia» del objetivo anterior y dispararía un deadlock falso 10 s después de cada sub-meta.

---

## A10.4 Nodos y comportamientos

### A10.4.1 Nodo `capture`

**Salidas:** `rgb_image`, `telemetry`, `degraded`, `frame_history`, `frame_history_ts`, `prev_image`, `prev_telemetry`.

Copia el par imagen–telemetría del ciclo anterior a `prev_*`, llama a `airsim_client.capture()` y, si la imagen es `None` o `telemetry["source"] != "airsim"`, marca `degraded = True` sin tocar el ring buffer. En modo normal agrega el fotograma y su timestamp a `frame_history` (tamaño `VLM_FRAME_HISTORY_SIZE` = 1). Las consultas del lazo lento no usan historial temporal: la capa estratégica toma el fotograma del ciclo y el barrido, uno por rumbo.

### A10.4.2 Nodo `degraded_hover` y modo degradado

Activado por `degraded_router` cuando `degraded = True`. Emite `FRENAR` sin percepción ni decisión. El diseño no sustituye el dato faltante por uno sintético plausible, por la misma razón que motiva el capítulo 9: un dato sintético es indistinguible de uno real y esconde el tipo de fallo silencioso que este trabajo documenta.

### A10.4.3 Nodo `perception`

**Salidas:** `obstacle_field`, `estimated_ttc`, `scene_summary`.

Invoca `FlowTTCEstimator.estimate()` con el par de fotogramas y la telemetría de ambos ciclos y produce el `ObstacleField` de tres sectores con ocupación, TTC y bloqueo por sector (cap. 6). Es el único objeto de percepción que consumen el lazo rápido, la FSM y el logger.

### A10.4.4 Comportamiento reactivo (`reactive_node`)

**Función:** `reactive_node` en `src/agents/reactive.py`. **Activación:** camino despejado, altitud bajo el piso óptico, o brazo `reactive`.

1. **Misión completada:** `FRENAR`, `flight_status = "mision_completada"`.
2. **Waypoint activo:** toma `vx`, `vy`, `vz`, `yaw_rate` de `waypoint_guidance` (IT.A10.8) y emite `MANTENER_RUMBO`. Con el centro a TTC < `TTC_BLOCKED_THRESHOLD_S` limita la tasa de guiñada para no superar el rango de derotación del estimador de flujo.
3. **Sin waypoints:** avance a `REACTIVE_FORWARD_SPEED` (3 m/s en producción) con amortiguación de la deriva vertical.

### A10.4.5 Comportamiento de evasión (`evasive_node`)

**Función:** `evasive_node` en `src/agents/evasive.py`. **Activación:** contacto (`imu_contact` / `blind_wall`) o peligro frontal sin FOV mayormente bloqueado (reglas 3, 7 y 7b).

Compara la ocupación de los sectores laterales del `ObstacleField` y elige `EVADIR_IZQUIERDA` o `EVADIR_DERECHA` hacia el menos ocupado (a igualdad, el de mayor TTC), con velocidad de evasión agresiva (`vx` = 1.2 m/s). `action_to_command()` fija un `target_yaw` redondeado al múltiplo de 90° más cercano (`_manhattan_snap_yaw`), adecuado a la cuadrícula urbana. La evasión lateral **no se compromete**: `evasive_node` no escribe `active_maneuver`, de modo que el lado se vuelve a elegir en cada ciclo con el campo de ese ciclo y, con ocupaciones laterales parecidas, puede alternar de un ciclo al siguiente (NB3.3).

### A10.4.6 Giro de 90° (`GIRAR_90`)

**Activación:** regla 7, cuando `blocked_fraction > FOV_BLOCKED_THRESHOLD` (0.6): el campo de visión está tan obstruido que una corrección lateral no tiene sentido.

Gira 90° sin traslación (`yaw_rate` ±20°/s, `target_yaw` redondeado a la cuadrícula) **hacia el lado del waypoint**, durante `GIRAR90_DURATION_S` (1 s). En el mismo ciclo, `navigate` llama a `StrategicLayer.expedite()` y vuelve a ejecutar `tick()`: si la capa estratégica no tiene un pedido en vuelo y la meta está dentro del campo visual, el fotograma que ve el muro se envía de inmediato a la fuente, sin esperar el período.

### A10.4.7 Mapa de macro-acciones (`action_to_command`)

Todos los comportamientos comparten `action_to_command()` (`src/agents/action_map.py`) como fuente única de la cinemática de cada macro-acción.

| Macro-acción | `vx` (m/s) | `vy` | `vz` (m/s) | `yaw_rate` (°/s) | `target_yaw` |
|---|---|---|---|---|---|
| `MANTENER_RUMBO` | guiado | 0 | guiado | guiado | — |
| `EVADIR_DERECHA` / `EVADIR_IZQUIERDA` | 1.2 (agresiva) / 0.3–0.8 | 0 | guiado | ±15 | snap 90° |
| `GANAR_ALTURA` | 0 | 0 | −1.5 | guiado | — |
| `PERDER_ALTURA` | 1.0 | 0 | +0.8 | 0 | — |
| `GIRAR_90` | 0 | 0 | 0 | ±20 | snap 90° hacia el WP |
| `FRENAR` | 0 | 0 | 0 (+ ancla) | 0 | — |
| `RETROCEDER` | −1.2 | 0 | guiado | 0 (rumbo congelado) | — |

`RETROCEDER` forma parte del vocabulario, pero **ningún comportamiento del brazo `slm` lo emite** (IT.5.3.4). `GANAR_ALTURA` asciende en el lugar y sin deriva lateral: una deriva alejaría el waypoint en el plano XY, la métrica que decide si el atasco se resolvió.

Las duraciones de las maniobras comprometidas del brazo `slm` son: `MANEUVER_DURATION_S` (2.0 s en producción) para la macro resuelta por el barrido; `ESCAPE_MANEUVER_DURATION_S` (1.6 s) para el escape vertical; `GIRAR90_DURATION_S` (1.0 s) para el giro. Las evasiones laterales de `evasive_node` no se comprometen (IT.A10.4.5): la entrada `EVADIR_*` de `_MANEUVER_DURATION` en `graph.py` solo se usaría si la decidiera `_dispatch`, y en la configuración evaluada ninguna regla lo hace. El brazo `fsm`, en cambio, compromete `EVADIR_*`, `GANAR_ALTURA` y `PERDER_ALTURA` durante `FSM_MANEUVER_DURATION_S` (1.5 s).

### A10.4.8 Detalle del brazo `fsm`

Su detección de atasco usa el contador de progreso del tracker (`evasion_stuck_cycles`) con los umbrales efectivo y duro (IT.A10.8.2). Ante un atasco, si `DEADLOCK_STRATEGY` es `depth` o `deep_vlm`, delega en el mismo barrido panorámico del brazo `slm` (IT.5.6); si no, alterna `CLIMB`/`DESCEND` hasta `MAX_CONSECUTIVE_ESCAPES` (2) y luego cambia de estrategia con `GIRAR_90` y una esquina de desvío propia.

---

## A10.5 Nodo `motor`

Único nodo que interactúa con el actuador. Lee `velocity_command` y aplica, en orden:

**Ancla de altitud en `FRENAR`.** En el primer ciclo de `FRENAR` ancla `_hover_alt_anchor = z`; en los siguientes, si `|anchor − z| > 0.3 m`, inyecta `vz = clamp(0.35 × dz, ±0.8 m/s)`. Corrige la deriva vertical de reemitir `moveByVelocityBodyFrameAsync(vz = 0)` (medido: hasta 9 m en 120 s sin corrección).

**Gobernador de velocidad** (`src/navigation/speed_governor.py`). Limita solo el avance de `MANTENER_RUMBO`, según cuánta evidencia perceptual hay y qué pasó recientemente: sin flujo válido durante 3 ciclos seguidos, tope de 1.5 m/s, y durante 8, de 1.0 m/s; tras un frente bloqueado (GIRAR_90 o `blocked_fraction` ≈ 1), tope de 1.0 m/s durante 40 ciclos; al terminar una maniobra, rampa lineal del tope de 1.0 a 6.0 m/s en 15 ciclos (por encima de la velocidad de crucero, el tope deja de actuar). Su función es que la ausencia de evidencia no se trate como espacio libre: sin él, con el campo sin evidencia y una pared a 4 m, el guiado puede acelerar al dron hacia ella. Se desactiva con `GOV_ENABLED = false`.

**Actuación no bloqueante.** `execute_velocity(vx, vy, vz, yaw_rate, target_yaw)`: con `target_yaw` usa orientación absoluta (`YawMode(is_rate=False)`); sin él, tasa angular.

---

## A10.6 Capa estratégica: auditoría y servicio de deliberación

**Archivos:** `src/agents/vlm_strategic.py` (`StrategicLayer`), `src/agents/vlm_client.py` (consulta al VLM), `src/agents/depth_client.py` y `src/perception/depth_estimator.py` (consulta a la red de profundidad), `src/agents/deliberation_service.py` (hilo worker). El módulo y varios de sus parámetros (`VLM_STRATEGIC_*`, `VLM_SUBGOAL_*`) llevan «VLM» en el nombre porque en las primeras versiones la capa consultaba al modelo; hoy valen para cualquier fuente (Anexo 12, IT.A12.1).

### A10.6.1 Auditoría

Cada respuesta deja una entrada en `deliberations[]` con `arm = "{fuente}_strategic"` (`vlm_strategic` o `depth_strategic`), el prompt (vacío con la profundidad), la respuesta cruda (con la profundidad, el p5 estimado por sector, en metros), el motivo de la decisión (`directo_libre`, `sector C2 (+34 deg, +0 deg, 15 m)`, `vencida`, `wp_cambio`, `superada`, `sin_sector_libre`, `no_parseable`) y la latencia; el fotograma exacto que vio la fuente se guarda como `photo-*.png` vía `_last_delib_frames`. El último resultado queda en `_vlm_strategic`. Esto permite medir, por corrida, con qué frecuencia la capa propone un rodeo, hacia qué fila, y con qué frecuencia declara «todo libre».

### A10.6.2 `DeliberationService`

Un hilo daemon con cola de entrada de tamaño 1: `request(payload)` vacía la cola antes de encolar, de modo que el worker procese siempre el pedido más reciente. Los resultados se guardan por identificador (últimos 16), y cada consumidor recupera el suyo con `get_result(request_id)`, de modo que un pedido posterior no pisa un resultado ya producido. Hay a lo sumo dos servicios por misión, cada uno con su hilo, y cada uno se crea solo si alguna capa lo usa: el del VLM (capa estratégica `vlm` o barrido `deep_vlm`) y el de la profundidad (capa `depth` o barrido `depth`). Con la configuración por defecto (`depth`/`depth`) el VLM no corre durante el vuelo: queda en la planificación de ruta previa (cap. 4), y el ejecutor de experimentos solo verifica que el servidor de inferencia responda si alguna capa lo va a usar. El barrido y el brazo FSM usan el servicio de su estrategia.

Si el servicio no tiene el resultado y no hay pedido pendiente durante más de `VLM_STRATEGIC_LOST_GRACE_S` (3 s) —porque un pedido de barrido lo reemplazó en la cola—, la capa lo da por perdido.

`vlm_client._query_slm_impl()` atiende dos modos, cada uno con su system prompt, esquema JSON y parser: `strategic` (una imagen, tope `VLM_MAX_TOKENS_STRATEGIC` = 384 tokens, timeout HTTP `SLM_HTTP_TIMEOUT_S` = 15 s) y `deep_scan` (N imágenes, tope `VLM_MAX_TOKENS_DEEP` = 512, timeout `SLM_DEEP_HTTP_TIMEOUT_S` = 20 s). Con decodificación restringida la generación termina sola al cerrar el esquema; el tope solo protege de una generación desbocada en modo libre, y tiene que sobrar. Si el servidor informa que la respuesta se cortó por el tope (`finish_reason = length`), la consulta devuelve el error `respuesta_truncada` y no se interpreta (Anexo 11, IT.A11.4.6). Intenta primero con `response_format = json_schema` y, si el servidor no lo soporta, reintenta en modo libre; el parser extrae el primer objeto JSON del texto y lo valida contra el formato del modo.

### A10.6.3 Servicio de profundidad

`make_depth_service()` envuelve la red en un `DeliberationService` con la misma interfaz que el del VLM; los pedidos llevan el fotograma crudo, no JPEG en base64. La red corre en el hilo del servicio, nunca en el lazo: ~110 ms por consulta con la GPU compartida con Unreal, frente a ~790 ms del VLM local, y ~440 MiB de VRAM adicionales. Al crearse, el servicio carga la red con un fotograma vacío, para que la primera consulta en vuelo no pague la carga. Una falla de la red se reporta como error y el llamador cae a su camino de falla, como ante un timeout del VLM.

**La fila de abajo a nivel de calle.** El borde inferior del recorte mira a −33.7° del eje óptico y, a 10 m de altura, corta el suelo a 15 m (a 8 m, a 12 m): sobre terreno plano el p5 de un sector de la fila 3 no llega a 15 m, y en la corrida de referencia de NB2.6 (`citysim_pilot`, a −10 m) los tres sectores de esa fila salen bloqueados en el 100 % de las consultas. En los tramos a nivel de calle, por lo tanto, la capa con profundidad propone rodeos por el costado o por arriba, nunca por abajo. A 30 m el borde corta el suelo a 45 m y la fila sí puede salir libre. La geometría se desarrolla en NB4.9.

### A10.6.4 Geometría del ancla

NB4.9 recalcula, con el ancla y la respuesta registradas, las sub-metas de una corrida del lote 6 y obtiene los mismos puntos que se inyectaron en vuelo. El ancla guarda posición (x, y, z) y yaw del fotograma, timestamp, etiqueta del waypoint real y su distancia horizontal, la dirección de la meta (azimut y elevación respecto del eje óptico) y el sector en el que cae. El rumbo de cada sector es el yaw del ancla más el azimut del centro del sector, y su elevación la del centro del sector, ambos calculados con proyección *pinhole* sobre los tercios del recorte, con la focal del fotograma completo: para un fotograma de 3:2 y 90° de campo horizontal, el recorte abarca ±33.7° y los centros de los sectores quedan a ±24.0° tanto en azimut como en elevación. La altitud de la sub-meta cambia `d · tan(elevación del sector)`, acotada a ±`VLM_MAX_DZ_M` (4 m) y sin bajar de `VLM_SUBGOAL_MIN_ALT_M` (6 m); una sub-meta que el dron ya superó (a menos de `VLM_SUBGOAL_MIN_AHEAD_M` = 4 m) se descarta.

---

## A10.7 Barrido panorámico en deadlock (`deep_scan`): máquina de estados

**Archivo:** `src/agents/deep_scan.py`. **Activación:** regla 2 (o el atasco de la FSM) con `DEADLOCK_STRATEGY` en `depth` o `deep_vlm`. La estrategia `blind` no ejecuta barrido (IT.5.3.4). Valores admitidos: `depth` (default en `config/.env` y en el runner), `deep_vlm` (ablación) y `blind`; cualquier otro valor aborta el arranque. La máquina de estados es la misma para las dos fuentes; solo cambia quién juzga cada imagen en la fase `capturado`. La sostienen entre ciclos los campos `_scan_*`:

**Inicio.** Si el waypoint real está a menos de `VLM_NEAR_WP_M` (8 m) en horizontal, no barre: desde tan cerca el rumbo a la meta es casi ruido y una sub-meta la saltearía; devuelve `False` (escape de IT.5.3.4). Si no, `_scan_phase = "rotando"`, `_scan_start_yaw_deg = yaw actual`, cancela cualquier maniobra activa. Durante todo el barrido, `_deliberation_pending = True` evita que el bucle externo cuente el giro en el lugar como falta de progreso.

**`rotando`.** Comanda `target_yaw = yaw_inicial + i × 360° / SCAN_HEADING_COUNT_DEEP` (4 rumbos: 0°, +90°, +180°, +270°), sin traslación. Al llegar a `SCAN_YAW_TOLERANCE_DEG` (5°) pasa a `asentando`. Si en `SCAN_ROT_TIMEOUT_CYCLES` (10) ciclos no alcanza el rumbo —dron trabado en una malla—, abandona el barrido y devuelve `False`.

**`asentando`.** Hover durante `SCAN_SETTLE_CYCLES_DEEP` (2) ciclos; luego guarda `(rumbo_medido, frame, capture_ts)` con el **yaw medido** en ese ciclo (no el objetivo del giro) y el fotograma que `capture_node` ya produjo (nunca una captura adicional).

**`capturado`.** Envía un único pedido con hasta `MAX_DEEP_SCAN_IMAGES` (5) imágenes a 256 px, rotuladas solo `[Image 1]` … `[Image N]`. El prompt (`_build_panorama_prompt`) da únicamente la cantidad de imágenes y la altura; no da ángulos, meta ni sugerencias de acción, porque el modelo solo describe y el rumbo de cada imagen lo conoce el código. El modelo responde una entrada por imagen:

```json
{"views": [{"img": 1, "view": "facade", "free": false},
           {"img": 2, "view": "open",   "free": true}, ...]}
```

Con la profundidad, el pedido lleva los fotogramas crudos de los rumbos; un rumbo es transitable si el p5 del sector central (`B2`) es ≥ `DEPTH_FREE_M` (15 m), y la respuesta tiene la misma forma (`view` = `open` o `wall`).

**Interpretación en marco mundo (`panorama_to_subgoal`).** Las entradas se asignan a las imágenes por el campo `img` (o por orden si falta); las entradas sobrantes que el modelo inventa se descartan. Una imagen es transitable si se marcó `free: true` **y** con vista `open`: una entrada `free: true` con otra vista (`inside`, `facade`) se contradice a sí misma y no se usa. La sub-meta se fija con la misma función que la capa estratégica (`subgoal.build_subgoal`), a la altitud actual del dron —las imágenes del barrido no describen filas, de modo que la elevación es cero—, con macro `MANTENER_RUMBO`. Sin imágenes transitables: `GANAR_ALTURA` (con el VLM, `PERDER_ALTURA` si todo es vegetación). La resolución se registra en `deliberations[]` (`arm = "{brazo}_deep_scan"`), escribe `_deadlock_event` con la sub-meta y pide `_escape_reset`.

**Selección de salida, en detalle.** Entre los rumbos transitables, el código descarta: (1) los que caen a menos de `SCAN_FAILED_SECTOR_DEG` (45°) del **rumbo que falló** —la dirección hacia el objetivo activo al iniciar el barrido—; y (2) los que caen a menos de 45° de un rumbo **ya probado** —fallado o elegido— en un deadlock anterior a menos de `SCAN_REPEAT_RADIUS_M` (10 m), para el mismo waypoint. Entre los que quedan, sin historia en la zona se elige el más cercano a la meta (`hacia_meta`); con historia, el más distinto de los ya probados (`exploracion`). Si todos los transitables estaban descartados: `GANAR_ALTURA` (`sin_rumbo_nuevo`). La historia (`_deadlock_history`, últimos 12 deadlocks, incluidos los barridos que fallaron) y la selección completa —candidatos, descartados con su motivo, rumbo que falló, rumbos probados, modo y rumbo elegido— quedan en `_deadlock_event["scan_selection"]`.

**Fallas.** Watchdog `SLM_DEEP_WATCHDOG_MS` (18 s en producción) vencido, pedido perdido (`SCAN_LOST_GRACE_MS`, 3 s), respuesta sin el formato del modo o respuesta cortada por el tope de tokens: el barrido deja una entrada `arm = "deep_scan_failed"` con sus fotogramas y devuelve `False`.

---

## A10.8 Guiado a waypoint: `WaypointTracker`

`WaypointTracker` (`src/navigation/waypoint_tracker.py`) corre en el bucle externo, **fuera del grafo**, una vez por ciclo antes de `graph.invoke()`. `update(pos)` avanza el waypoint activo al entrar en el radio de aceptación (3.5 m; bajo un techo detectado, por distancia horizontal) y `compute_guidance()` produce `vx`, `vy`, `vz`, `yaw_rate` en marco del cuerpo, con corrección de *cross-track*, zona muerta angular, tope de guiñada diferenciado (15°/s, 45°/s con desvío > 60°), histéresis entre regímenes, suavizado EMA y el modo `near_vertical` (`vx = 0` si `dist_xy < 1 m` y `|dz| > 0.3 m`, necesario para el patrón *climb-first* de Tier 2).

**Despegue vertical.** Hasta que el dron llega a `TAKEOFF_ALT_TOL_M` (1 m) de la altitud del primer objetivo, `compute_guidance()` no avanza en horizontal (`vx = 0`): sube en el lugar mientras alinea el rumbo, y exporta `takeoff = True`. La fase ocurre una vez por misión y termina antes si se detecta un techo. Avanzar mientras se sube puede llevar al dron contra una estructura más baja que la altitud de crucero pero más alta que la altitud de ese momento (Anexo 11, IT.A11.4.4). Durante la fase, los tres brazos usan `reactive_node` y el `StallDetector` no cuenta atasco.

### A10.8.1 Contador de progreso

`record_progress(dist_xy, bearing_err_deg)` mantiene `evasion_stuck_cycles`: se reinicia cuando la distancia mejora `WAYPOINT_PROGRESS_EPS_M` (0.5 m) sobre la mínima vista; se exime al dron que gira activamente (error de rumbo > 30°) hasta 15 ciclos consecutivos; en otro caso, se incrementa. Este contador lo consume el brazo `fsm`; el brazo `slm` usa las señales del `StallDetector` (IT.A10.3).

### A10.8.2 Umbrales de atasco

`effective_stall_threshold()` es el mínimo de ciclos sin progreso físicamente demostrable: con `eps = 0.5 m`, velocidad mínima 0.25 m/s y 5 Hz, 10 ciclos. `hard_stall_threshold()` lo multiplica por `STUCK_HARD_FACTOR` (1.5 en producción: 15 ciclos). Ambos los usa la FSM.

### A10.8.3 Detección de techo

Con un waypoint bajo una estructura horizontal, la corrección de altitud empuja al dron contra la losa. El tracker lo detecta: si durante 10 ciclos, con el dron libre en horizontal, se **ordena** ascenso (`vz < −0.3 m/s` en el comando efectivamente ejecutado, que el bucle externo le informa con `note_executed_command()`; altitud ≥ 3 m) sin que la cota varíe más de 0.15 m, declara un techo (`ceiling_z`), liberado al alejarse 15 m o al cambiar de waypoint. Con techo, `compute_guidance()` limita la altitud objetivo a `ceiling_z + CEILING_MARGIN_M` (0.8 m) y, si el waypoint cae dentro de `CEILING_SAFE_GAP_M` (3 m) del techo, lo baja a esa banda y exporta `z_path_blocked = True`, que `navigate` resuelve con `PERDER_ALTURA` (regla 6). Usar el comando ejecutado y no la demanda del guiado importa: durante un `GIRAR_90` o un `FRENAR` el comando vertical es cero aunque el guiado pida subir, y esos ciclos no prueban que haya una losa encima. Por la misma razón no cuentan los ciclos en que el dron está trabado de costado —se ordenó avanzar y no se desplazó más de `CEILING_SIDEWAYS_STUCK_M` (3 cm por ciclo)—: el roce contra una pared también impide subir, y ese caso lo resuelve el deadlock.

### A10.8.4 Sub-metas del lazo lento

`inject_corner_waypoint(x, y, z, label)` inserta una sub-meta temporal delante del waypoint activo. Todas las sub-metas del brazo `slm` provienen del lazo lento (capa estratégica o barrido, con la red de profundidad o con el VLM) y se insertan **tal cual**: una sub-meta nueva reemplaza a las temporales pendientes y reinicia el contador de progreso. La única condición es la deduplicación: si la sub-meta pendiente está a menos de `SUBGOAL_DEDUP_M` (10 m) de la nueva, la nueva se ignora; reemplazarla por otra casi igual reiniciaría el contador de progreso y un dron atascado nunca declararía el deadlock.

`update()` mide en cada ciclo la distancia al waypoint **real** aunque el objetivo activo sea una sub-meta: si el dron entra en el radio de aceptación del waypoint real, descarta las sub-metas pendientes (`drop_temporary()`) y lo acepta. El bucle externo también las descarta cuando la capa estratégica marca `_clear_subgoals`.

---

## A10.9 Registro de vuelo y cierre de misión

### A10.9.1 Registro de vuelo y auditoría post-vuelo

Cada ejecución —de `main.py` o de cada celda del runner— genera una carpeta autocontenida con traza JSONL y CSV, resumen de la corrida y por objetivo, muestras de DistMin, copia de la consola, fotogramas de cada consulta del lazo lento, video anotado de la cámara frontal (`.webm`), video de la cámara de seguimiento externa (`.follow.webm`, solo auditoría) y visor HTML. El capítulo 4 (IT.4.4) describe cada archivo, cada campo y el uso del visor. El runner graba video por defecto (`--no-video` lo desactiva).

**Traza completa del `DroneState`.** El JSONL conserva por ciclo el estado completo sin imágenes (`src/logging/state_serializer.py`); el CSV lo aplana en columnas `state.<ruta>`. La telemetría incluye `landed_state`.

**Auditoría del lazo lento.** Cada consulta resuelta —estratégica o de barrido, a la profundidad o al VLM— deja una entrada en `deliberations[]` y sus fotogramas RAW se asocian a la fila del ciclo en que la respuesta llegó (`_last_delib_frames`). Cada deliberación nueva se cuenta en `slm_invocations` en el ciclo en que aparece, cualquiera sea la ruta del ciclo. Los barridos fallidos también se registran. El registro `deliberations[]` es de solo agregado: se suman entradas, nunca se borran campos; los análisis de los capítulos 9 a 11 se derivan de él.

**Video en un hilo aparte.** La codificación VP8 ([Bankoski et al., 2011](../13-REFERENCIAS.md#ref-bankoski-2011)) corre en un hilo con cola acotada y el cuadro se reduce a 0.6: codificar a 1080×720 dentro del lazo cuesta ~275 ms por cuadro, lleva el período de 0.21 a 0.45 s y degrada el flujo óptico en el 64–82 % de los ciclos.

**Visor HTML.** Sincroniza los dos videos y la traza por índice de ciclo y muestra, para cada ciclo, el campo de obstáculos, la consulta del lazo lento con sus fotogramas y el árbol del `DroneState` (cap. 4 IT.4.4).

**Cliente AirSim como singleton.** `compile_workflow(airsim_client)` recibe un cliente ya conectado; un segundo cliente tendría su propio `takeoffAsync`, desconectado del grafo.

### A10.9.2 Cierre de misión y vigilancia de congelamiento

**Aterrizaje suave (`land_smooth`).** Hover de 1.5 s, descenso con `moveToZAsync` a 0.5 m/s hasta z = −0.3 m y desarmado; evita la caída libre de `landAsync()` desde la altura de crucero.

**Vigilante de congelamiento físico** (`src/navigation/freeze_watchdog.py`, en el bucle externo). Si el estado físico del dron (posición, actitud y velocidad) queda idéntico durante `FREEZE_CYCLES` (25) ciclos, el dron está incrustado en la malla: con `FREEZE_RECOVERY = abort` (producción) la corrida termina con `termination_reason = "physics_locked"`; con `teleport`, vuelve a la última pose libre hasta `FREEZE_MAX_RECOVERIES` veces y lo registra como evento.

Ningún criterio de terminación usa la distancia al obstáculo: medirla en vuelo requeriría el canal de profundidad del simulador (IT.5.8). La métrica `min_obstacle_dist_m` la mide el hilo de auditoría y `finalize_run` la consolida en el `summary.json` al cerrar la corrida (cap. 10 IT.10.6.1).
