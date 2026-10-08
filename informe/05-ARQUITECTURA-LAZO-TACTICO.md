# 5. Arquitectura del lazo táctico

## 5.0 Escaneo espacial pre-vuelo (`spatial_scan`)

Antes de entrar al lazo, `main.py` llama de forma bloqueante a `run_initial_scan()` (`src/agents/spatial_scan.py`). No es un nodo del `StateGraph`: se ejecuta una sola vez, entre la conexión con AirSim y la compilación del grafo. Realiza un barrido de yaw en el lugar hacia `SCAN_HEADING_COUNT` (6) rumbos equiespaciados, captura un fotograma por rumbo y envía todas las imágenes en una única consulta al VLM, que devuelve un contexto cualitativo de la escena y un rumbo recomendado.

El resultado es **solo un chequeo de cordura del plan de misión**: si el rumbo recomendado difiere más de 90° del rumbo al primer waypoint, `main.py` emite un aviso por consola. No se transfiere al grafo ni modifica el vuelo. El ejecutor de experimentos (`experiments/runner.py`) **no** lo ejecuta, de modo que no interviene en ninguna corrida experimental. Si el VLM no responde, la misión arranca igual.

## 5.1 Visión general del lazo

El lazo se ejecuta sobre el entorno de simulación del capítulo 3 (Unreal Engine 5.5 con Cosys-AirSim), siguiendo los manifiestos compilados por la estación terrena (capítulo 4). Es un **grafo de decisión por ciclo** (`StateGraph` de LangGraph, [LangChain, 2024](13-REFERENCIAS.md#ref-langchain-2024)) que corre a `LOOP_HZ` = 5 Hz (ciclo de ≈ 0.2 s).

El grafo se compila **una vez** y el bucle externo (`main.py` o `experiments/runner.py`) lo invoca con `graph.invoke()` en cada ciclo. El grafo es acíclico: la naturaleza cíclica de la navegación la aporta el bucle externo. Esta distinción importa porque LangGraph construye los canales del estado a partir del `TypedDict` declarado (`DroneState`, §5.2): una clave que un nodo escriba sin estar declarada se **descarta en silencio** al terminar `graph.invoke()`. Esa propiedad es la causa raíz de varios modos de falla del capítulo 9.

### 5.1.1 Topología: cuatro nodos y una arista condicional

```
capture ──(ok)──────────► perception ──► navigate ──► motor ──► FIN
   │                                                    ▲
   └──(AirSim sin datos)──► degraded_hover ─────────────┘
```

`navigate` es un **único nodo** que contiene la política. Los comportamientos concretos (guiado, evasión lateral, giro de 90°, escape vertical, barrido panorámico) son funciones que `navigate` invoca, no nodos del grafo.

<img src="2026-0930 grafo_control.png"/>

*Figura 5.1. Grafo de control. El lazo rápido (izquierda) es el único que comanda velocidades; el lazo lento (derecha) consulta al VLM de forma asíncrona y devuelve sub-metas en coordenadas del mundo, que el bucle externo inserta en el `WaypointTracker`.*

### 5.1.2 Dos lazos desacoplados

La organización responde a un hecho medido: la inferencia del VLM tarda entre 3 y 6 s (mediana de 3.8 s sobre 185 consultas, §8.6), es decir, entre 15 y 30 ciclos del lazo. Cualquier respuesta expresada **en el marco del cuerpo** del dron («el frente está libre», «evadir a la izquierda») describe un fotograma que ya no existe cuando la respuesta llega: el dron giró y avanzó varios metros. El capítulo 9 (§9.8) documenta las fallas que produce usar una respuesta así: maniobras hacia el lado equivocado y respuestas que llegan tarde y se descartan.

El sistema separa entonces dos escalas de tiempo:

1. **Lazo rápido (5 Hz).** Guiado al waypoint, evasión por flujo óptico, reacción a contacto y detección de atasco. Es el **único** que comanda velocidades y el responsable de todo lo inminente.
2. **Lazo lento (VLM, asíncrono).** El modelo mira un fotograma y responde una pregunta cuya respuesta es **válida en el mundo**, no en el cuerpo: por cuál dirección se puede volar hacia la meta. Cada pedido guarda la pose del fotograma (ancla); la respuesta se traduce a una **sub-meta en coordenadas del mundo** con esa pose, de modo que sigue siendo correcta aunque el dron haya girado mientras el modelo pensaba (§5.10).

El patrón es el de las arquitecturas de capas para robots móviles, con un controlador reactivo de respuesta inmediata y una capa deliberativa que opera a otra escala temporal ([Gat, 1998](13-REFERENCIAS.md#ref-gat-1998)), en la que las capas inferiores conservan siempre la capacidad de actuar ([Brooks, 1986](13-REFERENCIAS.md#ref-brooks-1986)). La particularidad es la interfaz entre ambas: la capa lenta no emite acciones sino **metas geométricas ancladas**, que la capa rápida persigue con su guiado normal.

Tres principios de diseño acompañan esta separación:

- **El VLM decide; las reglas no lo reescriben.** No hay reglas deterministas que corrijan la respuesta del modelo: una capa de reglas sobre la decisión del modelo haría que la comparación entre brazos midiera esas reglas y no al modelo (cap. 9, §9.8.6). El fallback determinista existe solo ante **falla** del modelo: timeout, formato inválido o rotación imposible durante un barrido.
- **El dron nunca espera al VLM en vuelo normal.** La capa estratégica no frena al vehículo; solo el barrido de resolución de atasco (§5.12) mantiene al dron en el lugar, porque ese es justamente el momento en que avanzar ya no es posible.
- **Sin profundidad del simulador.** Ni el grafo, ni `main.py`, ni `experiments/runner.py` leen el canal de profundidad de AirSim, ni para control ni como métrica (§5.16).

## 5.2 El estado compartido: `DroneState`

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
| `_hover_alt_anchor` / `_speed_cap` | `float\|None` | Ancla de altitud en `FRENAR` y tope del gobernador de velocidad (§5.13) |

**VLM y canales hacia el bucle externo:**

| Campo | Tipo | Descripción |
|---|---|---|
| `deliberations` | `List[Dict]` | Registro de solo agregado de todas las consultas al VLM (estratégicas, de barrido y fallidas) |
| `last_deliberation` | `Dict\|None` | Última entrada, actualizada por `motor_node` |
| `_vlm_strategic` | `Dict\|None` | Último resultado de la capa estratégica: `outcome`, motivo, latencia, sector de la meta, ancla y sub-meta (§5.10) |
| `_clear_subgoals` | `bool` | La capa estratégica vio libre el camino directo al waypoint real: el bucle externo descarta la sub-meta pendiente (§5.15.4) |
| `inject_corner` | `Dict\|None` | Sub-meta `{x, y, z, label}` en coordenadas del mundo que el bucle externo inserta en el tracker (§5.15.4) |
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

**Señales del `StallDetector`** (publicadas solo para logging, §5.3.1): `imu_jitter_level`, `imu_contact_event`, `blind_wall_event`, `_stopped_cycles`, `_wp_no_progress_cycles`. El bucle externo agrega `_freeze_cycles` (vigilante de congelamiento físico, §5.19).

**Regla de diseño crítica.** Todo campo que cruce la frontera entre invocaciones de `graph.invoke()` debe estar declarado en este `TypedDict`: LangGraph no lanza error si un nodo escribe una clave no declarada, la descarta en silencio (cap. 9, §9.4). Dos decisiones reducen esa superficie: los contadores de atasco y el estado de la capa estratégica viven en objetos de proceso (`StallDetector`, `StrategicLayer`) y no en el estado, y los tests de integración corren el **grafo compilado** y verifican que las claves de control (`inject_corner`, `_escape_reset`, `_deadlock_event`, `_vlm_strategic`) cruzan la frontera (`tests/test_graph_integration.py`, `tests/test_vlm_strategic_graph.py`).

## 5.3 Nodo `navigate`

`navigate_node` (`graph.py`) recibe el estado enriquecido por `perception` y produce un `velocity_command`. Durante el despegue vertical (§5.15), los tres brazos delegan en `reactive_node`: el guiado sube en el lugar y el flujo óptico de un ascenso puro no es válido para evadir. Fuera del despegue, para los brazos de comparación delega de inmediato: `AGENT_ARM = reactive` → `reactive_node`; `AGENT_ARM = fsm` → `fsm_node` (§5.11). Para el brazo `slm`, ejecuta dos pasos previos en cada ciclo y luego una cascada de ocho reglas en orden estricto: **la primera que se cumple decide el ciclo**.

### 5.3.1 `StallDetector`: señales de atasco

Los contadores de atasco viven en un objeto `StallDetector` (`src/agents/stall_detector.py`) que persiste entre invocaciones. En cada ciclo, `update(state)` actualiza cuatro señales y `publish(state)` las escribe en el estado solo para logging.

| Señal | Condición | Umbral | Uso en `navigate` |
|---|---|---|---|
| `imu_contact` | RMS de la aceleración lateral ≥ `IMU_CONTACT_THRESHOLD_MPS2` (5 m/s²) con velocidad comandada > 0.3 m/s | ≥ 2 ciclos | Regla 4: evasión inmediata |
| `blind_wall` | Avance comandado (`vx ≥ 0.45 m/s`) con velocidad medida < 0.30 m/s, campo óptico con corredor libre (`blocked_fraction < 0.25`) y el dron moviéndose en el ciclo previo | ≥ 2 ciclos | Regla 4: evasión inmediata |
| `stopped_prolonged` | **Se ordenó avanzar** (velocidad horizontal comandada ≥ `STOPPED_MIN_CMD_MPS` = 0.30 m/s) y la velocidad medida es < 0.10 m/s; no cuenta bajo el piso óptico ni durante el despegue | ≥ `STOPPED_DELIBERATIVE_CYCLES` = 10 ciclos | Regla 2: deadlock (trabado) |
| `wp_no_progress` | La distancia al objetivo actual no mejora `WP_NO_PROGRESS_MIN_M` (2 m); se reinicia al cambiar el objetivo, durante un barrido, con `_escape_reset`, bajo el piso óptico y durante el despegue | ≥ `WP_NO_PROGRESS_THRESHOLD` = 50 ciclos (10 s) | Regla 2: deadlock (sin progreso) |

Tres decisiones de diseño:

- **«Detenido» significa «se le ordenó moverse y no se movió».** Durante el despegue, el guiado ordena subir y girar en el lugar hacia el primer waypoint con `vx = 0` durante ~3 s; un contador que sumara cualquier ciclo sin velocidad horizontal declararía un deadlock al cruzar el piso óptico (cap. 9, §9.8.4). Girar, subir o mantener un hover a propósito no es estar trabado.
- **La velocidad se mide por desplazamiento, no se lee de la telemetría.** Con el dron apoyado contra una estructura, AirSim reporta una velocidad cercana a la comandada aunque la posición no cambie (cap. 9, §9.8.8). `stopped_prolonged` y `blind_wall` usan la velocidad horizontal calculada con la diferencia de posición entre ciclos consecutivos.
- **El objetivo se identifica por su etiqueta y posición, no por su índice.** Una sub-meta del VLM se inserta en el mismo índice que el waypoint al que precede (§5.15.4); identificar el objetivo por índice heredaría la «mejor distancia» del objetivo anterior y dispararía un deadlock falso 10 s después de cada sub-meta.

### 5.3.2 Pasos previos y orden de evaluación

**Pasos previos (cada ciclo):** `StallDetector.update()` y `StrategicLayer.tick()` (capa estratégica del VLM, §5.10). El segundo nunca comanda velocidades: envía un pedido si corresponde, o procesa una respuesta y deposita una sub-meta en `inject_corner`.

| # | Condición | Acción | Por qué |
|---|---|---|---|
| 1 | Barrido panorámico en curso (`_scan_phase` o pedido de barrido pendiente) | Continuar el barrido (`_deadlock_resolve` → `deep_scan_cycle`) | Un barrido es dueño del dron hasta resolver o caer por sus watchdogs (§5.12); si otra regla tomara el ciclo a mitad del barrido, éste quedaría sin completar. |
| 2 | `stopped_prolonged` o `wp_no_progress` | `_deadlock_resolve` (§5.3.4) | Dron trabado o sin acercarse al objetivo. |
| 3 | Maniobra comprometida (`active_maneuver`, `maneuver_cycles_left > 0`) | Continuarla; ruta `evasive` | Anti flip-flop: una maniobra se completa antes de aceptar otra decisión. |
| 4 | `imu_contact` o `blind_wall` | `evasive_node` | Contacto que el flujo óptico no ve. |
| 5 | Altitud < `OPTICAL_MIN_ALT_M` (4.5 m) y sin techo detectado | `reactive_node` | Aterrizaje y vuelo bajo: el flujo ve el suelo en movimiento y produce TTC falsos. |
| 6 | `z_path_blocked` y `dz > 1 m` (waypoint dentro de la banda de seguridad de un techo, §5.15.3) | `PERDER_ALTURA`; ruta `reactive` | Obstáculo vertical → desplazarse en z, simétrico a la evasión en xy. |
| — | Altitud < 4.5 m bajo un techo detectado | `reactive_node` | Vuelo bajo deliberado: sin evasión basada en flujo. |
| 7 | TTC central ≤ `TTC_EVASION_THRESHOLD` (3.2 s), o centro bloqueado con TTC ≤ `TTC_SAFE_THRESHOLD` (4.6 s) | Si `blocked_fraction > FOV_BLOCKED_THRESHOLD` (0.6): `GIRAR_90` hacia el lado del waypoint **y** consulta inmediata a la capa estratégica (§5.9); si no: `evasive_node` | Peligro frontal: el lazo rápido esquiva; el rodeo lo decide el VLM. |
| 7b | Centro bloqueado o TTC mínimo ≤ 4.6 s | `evasive_node` | Ventana de advertencia. |
| 8 | — | `reactive_node` | Camino despejado: guiado nominal. |

Los umbrales de TTC provienen de la calibración del capítulo 7. El orden tiene tres justificaciones: el barrido (1) precede a todo porque, una vez iniciado, es dueño del dron hasta resolver; el deadlock (2) precede a toda otra regla porque cualquier acción que se repita sin mover al dron —una maniobra comprometida, una evasión por contacto, un descenso hacia un techo— taparía al detector de atasco indefinidamente (cap. 9, §9.8.8), y una maniobra que no mueve al dron en 2 s no es una decisión en curso sino un atasco; y el contacto físico (4) precede al piso óptico y al TTC porque no depende del sensado visual.

### 5.3.3 Lazo rápido: reacción sin VLM

Las reglas 3, 4, 5, 7 y 8 forman el lazo rápido: actúan en el mismo ciclo, sin depender del modelo. Son compartidas en espíritu con los otros brazos —misma percepción, mismo `action_to_command()` (§5.14)— de modo que la comparación entre brazos mide quién decide los rodeos y los deadlocks, no quién reacciona mejor a un muro inminente.

### 5.3.4 Resolución de deadlock (`_deadlock_resolve`)

Al entrar, `_deadlock_resolve` cancela cualquier consulta estratégica en vuelo (el barrido es más reciente y su sub-meta no debe ser pisada por una respuesta más vieja) e incrementa `_deadlock_cycles`. Luego:

1. **`DEADLOCK_STRATEGY = deep_vlm` (default):** ejecuta un paso de `deep_scan_cycle()` (§5.12). Mientras el barrido gira, se asienta o espera al VLM, retorna sin más. Cuando el barrido se resuelve, reinicia el `StallDetector` y el bucle externo reinicia el contador del tracker (`_escape_reset`).
2. **Sin resolución del VLM** (estrategia `blind`, o el barrido falló por watchdog, formato inválido o rotación imposible): escape determinista `GANAR_ALTURA` durante `ESCAPE_MANEUVER_DURATION_S` (1.6 s); si la altitud ya supera `MAX_ESCAPE_ALT_M` (30 m), `GIRAR_90` hacia el waypoint. Se registra un `_deadlock_event` con `fell_back_to_blind = True`.

`GANAR_ALTURA` es el escape determinista porque, en las corridas de diagnóstico sobre `citysim_pilot`, fue la única maniobra que liberó al dron de una estructura en la que había quedado apoyado (una cornisa); un retroceso (`RETROCEDER`), en cambio, tuvo un avance mediano negativo hacia el waypoint (cap. 9, §9.8.6). Por eso el lazo no emite `RETROCEDER`.

## 5.4 Nodo `capture`

**Salidas:** `rgb_image`, `telemetry`, `degraded`, `frame_history`, `frame_history_ts`, `prev_image`, `prev_telemetry`.

Copia el par imagen–telemetría del ciclo anterior a `prev_*`, llama a `airsim_client.capture()` y, si la imagen es `None` o `telemetry["source"] != "airsim"`, marca `degraded = True` sin tocar el ring buffer. En modo normal agrega el fotograma y su timestamp a `frame_history` (tamaño `VLM_FRAME_HISTORY_SIZE` = 1). Las consultas al VLM no usan historial temporal: la capa estratégica toma el fotograma del ciclo y el barrido, uno por rumbo.

## 5.5 Nodo `degraded_hover`

Activado por `degraded_router` cuando `degraded = True`. Emite `FRENAR` sin percepción ni decisión. El diseño no sustituye el dato faltante por uno sintético plausible, por la misma razón que motiva el capítulo 9: un dato sintético es indistinguible de uno real y esconde el tipo de fallo silencioso que este trabajo documenta.

## 5.6 Nodo `perception`

**Salidas:** `obstacle_field`, `estimated_ttc`, `scene_summary`.

Invoca `FlowTTCEstimator.estimate()` con el par de fotogramas y la telemetría de ambos ciclos y produce el `ObstacleField` de tres sectores con ocupación, TTC y bloqueo por sector (cap. 6). Es el único objeto de percepción que consumen el lazo rápido, la FSM y el logger.

## 5.7 Comportamiento reactivo (`reactive_node`)

**Función:** `reactive_node` en `src/agents/reactive.py`. **Activación:** camino despejado, altitud bajo el piso óptico, o brazo `reactive`.

1. **Misión completada:** `FRENAR`, `flight_status = "mision_completada"`.
2. **Waypoint activo:** toma `vx`, `vy`, `vz`, `yaw_rate` de `waypoint_guidance` (§5.15) y emite `MANTENER_RUMBO`. Con el centro a TTC < `TTC_BLOCKED_THRESHOLD_S` limita la tasa de guiñada para no superar el rango de derotación del estimador de flujo.
3. **Sin waypoints:** avance a `REACTIVE_FORWARD_SPEED` (3 m/s en producción) con amortiguación de la deriva vertical.

## 5.8 Comportamiento de evasión (`evasive_node`)

**Función:** `evasive_node` en `src/agents/evasive.py`. **Activación:** contacto (`imu_contact` / `blind_wall`) o peligro frontal sin FOV mayormente bloqueado (reglas 3, 7 y 7b).

Compara la ocupación de los sectores laterales del `ObstacleField` y elige `EVADIR_IZQUIERDA` o `EVADIR_DERECHA` hacia el menos ocupado (a igualdad, el de mayor TTC), con velocidad de evasión agresiva (`vx` = 1.2 m/s). `action_to_command()` fija un `target_yaw` redondeado al múltiplo de 90° más cercano (`_manhattan_snap_yaw`), adecuado a la cuadrícula urbana. La maniobra se compromete en `active_maneuver` y `navigate` la continúa (regla 2).

## 5.9 Giro de 90° (`GIRAR_90`)

**Activación:** regla 7, cuando `blocked_fraction > FOV_BLOCKED_THRESHOLD` (0.6): el campo de visión está tan obstruido que una corrección lateral no tiene sentido.

Gira 90° sin traslación (`yaw_rate` ±20°/s, `target_yaw` redondeado a la cuadrícula) **hacia el lado del waypoint**, durante `GIRAR90_DURATION_S` (1 s). En el mismo ciclo, `navigate` llama a `StrategicLayer.expedite()` y vuelve a ejecutar `tick()`: si la capa estratégica no tiene un pedido en vuelo y la meta está dentro del campo visual, el fotograma que ve el muro se envía de inmediato al VLM, sin esperar el período de 3 s. Así el rodeo del edificio lo decide el modelo con la imagen que justamente lo motiva.

## 5.10 Capa estratégica del VLM (`vlm_strategic.py`)

**Archivos:** `src/agents/vlm_strategic.py` (`StrategicLayer`), `src/agents/vlm_client.py` (consulta), `src/agents/deliberation_service.py` (hilo worker). La capa no es un nodo del grafo: `navigate` llama a `StrategicLayer.tick(state)` una vez por ciclo.

### 5.10.1 Cuándo se consulta

`tick()` envía un pedido solo si se cumplen todas las condiciones:

- pasó `VLM_STRATEGIC_PERIOD_S` (3 s) desde el último pedido, o la regla 7 llamó a `expedite()`;
- no hay barrido en curso ni pedido de barrido pendiente (comparten la cola del servicio);
- altitud ≥ `VLM_STRATEGIC_MIN_ALT_M` (8 m);
- el waypoint real está a más de `VLM_NEAR_WP_M` (8 m) en horizontal: más cerca, el guiado directo alcanza, y una sub-meta lo saltearía;
- la meta cae dentro del recorte cuadrado que analiza el modelo (±33.7° en un fotograma de 3:2 con 90° de campo horizontal; `VLM_STRATEGIC_MAX_GOAL_OFF_DEG` puede acotarlo más): si no, el guiado todavía está girando hacia ella y el fotograma no muestra lo que importa. La excepción es un dron que lleva `VLM_STUCK_QUERY_CYCLES` (15) ciclos sin acercarse a su objetivo —por ejemplo, deslizándose a lo largo de una fachada, de costado a la meta—: entonces se consulta igual, porque conviene mirar hacia donde está el dron. En ese caso no hay sector de la meta, la marca «GOAL» queda en el borde del lado del destino, el prompt dice que el destino está fuera de la imagen y la respuesta nunca se interpreta como «camino directo libre».

La consulta se hace **también con una sub-meta activa**. La pregunta es siempre sobre el waypoint real, y una respuesta nueva reemplaza a la sub-meta pendiente: así una sub-meta mala se corrige en la consulta siguiente, en lugar de persistir hasta que el detector de atasco la saque (cap. 9, §9.8.9).

### 5.10.2 Qué ve el modelo y qué responde

El pedido lleva **un fotograma**: un **recorte cuadrado** del centro del fotograma del ciclo —se cortan los dos costados del ancho—, reescalado a 384 × 384 px y dividido en una **grilla de 3×3 por tercios**, la grilla de composición fotográfica. El original, que usa el flujo óptico, no se modifica. El recorte hace que los sectores laterales y los verticales queden a la misma distancia angular del centro; sobre el fotograma completo de 3:2, un sector lateral quedaba a 33.7° y uno vertical a 24°, y un rodeo por arriba o por abajo ganaba siempre a uno por el costado por la forma del cuadro y no por la escena. Las columnas A, B y C van de izquierda a derecha; las filas 1, 2 y 3, de arriba abajo. La fila 2 es la altura del dron; la fila 1, pasar por arriba; la fila 3, por abajo. Cada sector lleva su etiqueta (`A1` … `C3`) y una marca roja «GOAL» señala la dirección del destino en azimut **y** elevación.

Una partición en columnas solo describe el eje horizontal: no puede decir que un obstáculo se pasa por arriba, ni distinguir un tablero de autopista a la altura del dron de la calle que se ve debajo. La grilla separa las dos dimensiones.

El modelo responde, con decodificación restringida por esquema JSON (§8.2):

```json
{"cells": {"A1": "free",    "B1": "free",    "C1": "free",
           "A2": "blocked", "B2": "blocked", "C2": "free",
           "A3": "blocked", "B3": "blocked", "C3": "blocked"}}
```

`free` significa «se puede volar al menos 15 m en la dirección de ese sector»; `blocked`, que un edificio, muro, árbol, puente o techo está a menos de 15 m. El prompt y los valores están en inglés (cap. 8, §8.5); internamente se registran como `libre` y `bloqueado`.

### 5.10.3 Ancla y sincronización

Al enviar, la capa guarda un **ancla**: posición (x, y, z) y yaw del fotograma, timestamp, etiqueta del waypoint real y su distancia horizontal, la dirección de la meta (azimut y elevación respecto del eje óptico) y el sector en el que cae. Cada sector tiene así una **dirección absoluta**: rumbo = yaw del ancla + azimut del centro del sector, y elevación del centro del sector, ambos calculados con proyección *pinhole* sobre los tercios del recorte, con la focal del fotograma completo (para un fotograma de 3:2 y 90° de campo horizontal, el recorte abarca ±33.7° y los centros de los sectores quedan a ±24.0° tanto en azimut como en elevación). Cuando la respuesta llega (`get_result(request_id)`), `decide_subgoal()` la traduce y valida contra el presente:

1. Descarta la respuesta si pasaron más de `VLM_STRATEGIC_MAX_AGE_S` (10 s) o si el waypoint real cambió.
2. Si el sector de la meta está libre: **no agrega nada** (`directo_libre`). Si había una sub-meta pendiente, la marca para descartar (`_clear_subgoals`): el camino directo está libre y el desvío sobra.
3. Si no: elige el sector libre más cercano en ángulo a la dirección de la meta —entre los que quedan a menos de `VLM_SUBGOAL_TIE_DEG` (10°) del más cercano, la fila del medio, después la de arriba, después la de abajo, de modo que con la meta de frente un rodeo por el costado precede a uno vertical— y fija una sub-meta **desde el ancla** en la dirección de ese sector (`subgoal.build_subgoal`, la misma función que usa el barrido, §5.12), a una distancia horizontal `d = min(VLM_SUBGOAL_DIST_M, distancia al waypoint real)` —15 m como máximo, y **nunca más lejos que el waypoint**—. La altitud cambia `d · tan(elevación del sector)`, acotada a ±`VLM_MAX_DZ_M` (4 m) y sin bajar de `VLM_SUBGOAL_MIN_ALT_M` (6 m). Sin sectores libres: nada (`sin_sector_libre`).
4. Descarta la sub-meta si el dron ya la superó mientras el modelo pensaba (quedó a menos de `VLM_SUBGOAL_MIN_AHEAD_M` = 4 m).

La sub-meta se deposita en `inject_corner`; el bucle externo la inserta en el tracker (§5.15.4) y el guiado normal la persigue. **El dron nunca se detiene a esperar.** Como la geometría está anclada al fotograma, girar mientras el modelo piensa no invalida la respuesta; solo la invalida el paso del tiempo o haberla superado, y ambos casos se verifican.

Si el servicio no tiene el resultado y no hay pedido pendiente durante más de `VLM_STRATEGIC_LOST_GRACE_S` (3 s) —porque un pedido de barrido lo reemplazó en la cola—, la capa lo da por perdido.

### 5.10.4 Auditoría

Cada respuesta deja una entrada en `deliberations[]` con `arm = "vlm_strategic"`, el prompt, la respuesta cruda, el motivo de la decisión (`directo_libre`, `sector C2 (+34 deg, +0 deg, 15 m)`, `vencida`, `wp_cambio`, `superada`, `sin_sector_libre`, `no_parseable`) y la latencia; el fotograma exacto que vio el modelo se guarda como `photo-*.png` vía `_last_delib_frames`. El último resultado queda en `_vlm_strategic`. Esto permite medir, por corrida, con qué frecuencia la capa propone un rodeo, hacia qué fila, y con qué frecuencia el modelo declara «todo libre».

### 5.10.5 `DeliberationService`

Un hilo daemon con cola de entrada de tamaño 1: `request(payload)` vacía la cola antes de encolar, de modo que el worker procese siempre el pedido más reciente. Los resultados se guardan por identificador (últimos 16), y cada consumidor recupera el suyo con `get_result(request_id)`, de modo que un pedido posterior no pisa un resultado ya producido. El servicio es único por misión y lo comparten la capa estratégica, el barrido y el brazo FSM.

`vlm_client._query_slm_impl()` atiende dos modos, cada uno con su system prompt, esquema JSON y parser: `strategic` (una imagen, tope `VLM_MAX_TOKENS_STRATEGIC` = 384 tokens, timeout HTTP `SLM_HTTP_TIMEOUT_S` = 15 s) y `deep_scan` (N imágenes, tope `VLM_MAX_TOKENS_DEEP` = 512, timeout `SLM_DEEP_HTTP_TIMEOUT_S` = 20 s). Con decodificación restringida la generación termina sola al cerrar el esquema; el tope solo protege de una generación desbocada en modo libre, y tiene que sobrar. Si el servidor informa que la respuesta se cortó por el tope (`finish_reason = length`), la consulta devuelve el error `respuesta_truncada` y no se interpreta (cap. 9, §9.8.10). Intenta primero con `response_format = json_schema` y, si el servidor no lo soporta, reintenta en modo libre; el parser extrae el primer objeto JSON del texto y lo valida contra el formato del modo.

## 5.11 Nodo `fsm`

**Función:** `fsm_node(state, service)` en `src/agents/fsm.py`. **Activación:** `AGENT_ARM = "fsm"`.

La FSM usa el mismo `ObstacleField`, el mismo vocabulario de macro-acciones y el mismo `action_to_command()` que el brazo `slm`; lo que cambia es quién elige la acción: umbrales deterministas.

| Estado FSM | Macro-acción | Condición |
|---|---|---|
| `CRUISE` | `MANTENER_RUMBO` | Centro despejado (default) |
| `AVOID_LEFT` / `AVOID_RIGHT` | `EVADIR_*` | Centro bloqueado o TTC ≤ 3.5 s; lado menos ocupado |
| `CLIMB` / `DESCEND` | `GANAR_ALTURA` / `PERDER_ALTURA` | Atasco con todos los sectores bloqueados (alternados) |
| `BRAKE` | `FRENAR` | TTC central ≤ 1.5 s con un lateral libre |

Su detección de atasco usa el contador de progreso del tracker (`evasion_stuck_cycles`) con los umbrales efectivo y duro (§5.15.2). Ante un atasco, si `DEADLOCK_STRATEGY = deep_vlm`, delega en el mismo barrido panorámico del brazo `slm` (§5.12); si no, alterna `CLIMB`/`DESCEND` hasta `MAX_CONSECUTIVE_ESCAPES` (2) y luego cambia de estrategia con `GIRAR_90` y una esquina de desvío propia.

**Dos asimetrías con el brazo `slm` que deben tenerse en cuenta al comparar.** Primero, con `deep_vlm` el brazo `fsm` **también consulta al VLM** en los deadlocks: la comparación `slm` vs. `fsm` aísla la capa estratégica y la política del lazo rápido, no la presencia del VLM en la resolución de atascos; para un brazo sin VLM en ningún punto se usa `fsm` con `--deadlock-strategies blind`. Segundo, la FSM tiene su propia lógica de atasco y escape (con esquinas de desvío deterministas), distinta de la del brazo `slm`.

## 5.12 Barrido panorámico en deadlock (`deep_scan`)

**Archivo:** `src/agents/deep_scan.py`. **Activación:** regla 2 (o el atasco de la FSM) con `DEADLOCK_STRATEGY = deep_vlm`. La estrategia `blind` no ejecuta barrido (§5.3.4). Valores admitidos: `deep_vlm` (default en `config/.env` y en el runner) y `blind`; cualquier otro valor aborta el arranque.

Máquina de estados sostenida entre ciclos por los campos `_scan_*`:

**Inicio.** Si el waypoint real está a menos de `VLM_NEAR_WP_M` (8 m) en horizontal, no barre: desde tan cerca el rumbo a la meta es casi ruido y una sub-meta la saltearía; devuelve `False` (escape de §5.3.4). Si no, `_scan_phase = "rotando"`, `_scan_start_yaw_deg = yaw actual`, cancela cualquier maniobra activa. Durante todo el barrido, `_deliberation_pending = True` evita que el bucle externo cuente el giro en el lugar como falta de progreso.

**`rotando`.** Comanda `target_yaw = yaw_inicial + i × 360° / SCAN_HEADING_COUNT_DEEP` (4 rumbos: 0°, +90°, +180°, +270°), sin traslación. Al llegar a `SCAN_YAW_TOLERANCE_DEG` (5°) pasa a `asentando`. Si en `SCAN_ROT_TIMEOUT_CYCLES` (10) ciclos no alcanza el rumbo —dron trabado en una malla—, abandona el barrido y devuelve `False` (escape de §5.3.4).

**`asentando`.** Hover durante `SCAN_SETTLE_CYCLES_DEEP` (2) ciclos; luego guarda `(rumbo_medido, frame, capture_ts)` con el **yaw medido** en ese ciclo (no el objetivo del giro) y el fotograma que `capture_node` ya produjo (nunca una captura adicional).

**`capturado`.** Envía un único pedido con hasta `MAX_DEEP_SCAN_IMAGES` (5) imágenes a 256 px, rotuladas solo `[Image 1]` … `[Image N]`. El prompt (`_build_panorama_prompt`) da únicamente la cantidad de imágenes y la altura; no da ángulos, meta ni sugerencias de acción, porque el modelo solo describe y el rumbo de cada imagen lo conoce el código. El modelo responde una entrada por imagen:

```json
{"views": [{"img": 1, "view": "facade", "free": false},
           {"img": 2, "view": "open",   "free": true}, ...]}
```

**Interpretación en marco mundo (`panorama_to_subgoal`).** Las entradas se asignan a las imágenes por el campo `img` (o por orden si falta); las entradas sobrantes que el modelo inventa se descartan. Una imagen es transitable si el modelo la marcó `free: true` **y** con vista `open`: una entrada `free: true` con otra vista (`inside`, `facade`) se contradice a sí misma y no se usa. Entre las imágenes transitables se elige la de **rumbo absoluto** más cercano al rumbo absoluto hacia el waypoint real (calculado con posiciones, no con el yaw), y se fija una sub-meta en ese rumbo con la misma función y las mismas reglas que la capa estratégica (`subgoal.build_subgoal`, §5.10.3): `VLM_SUBGOAL_DIST_M` (15 m) como máximo, nunca más lejos que el waypoint real, a la altitud actual del dron —las imágenes del barrido no describen filas, de modo que la elevación es cero—, con macro `MANTENER_RUMBO`: el guiado la persigue. Sin imágenes transitables: `GANAR_ALTURA` (`PERDER_ALTURA` si todo es vegetación). La resolución se registra en `deliberations[]` (`arm = "{brazo}_deep_scan"`), escribe `_deadlock_event` con la sub-meta y pide `_escape_reset`.

**Selección de salida.** Un deadlock es evidencia de que el rumbo que el dron intentaba no funciona, y elegir el transitable más cercano a la meta suele devolverlo contra el mismo obstáculo. Por eso, entre los rumbos que el modelo marcó transitables, el código descarta: (1) los que caen a menos de `SCAN_FAILED_SECTOR_DEG` (45°) del **rumbo que falló** —la dirección hacia el objetivo activo al iniciar el barrido—; y (2) los que caen a menos de 45° de un rumbo **ya probado** —fallado o elegido— en un deadlock anterior a menos de `SCAN_REPEAT_RADIUS_M` (10 m), para el mismo waypoint. Entre los que quedan, sin historia en la zona se elige el más cercano a la meta (`hacia_meta`); con historia, el más distinto de los ya probados (`exploracion`). Si todos los transitables estaban descartados: `GANAR_ALTURA` (`sin_rumbo_nuevo`). El modelo sigue decidiendo qué está libre: el código solo elige entre sus opciones usando lo que el dron ya comprobó al quedar trabado. La historia (`_deadlock_history`, últimos 12 deadlocks, incluidos los barridos que fallaron) y la selección completa —candidatos, descartados con su motivo, rumbo que falló, rumbos probados, modo y rumbo elegido— quedan en `_deadlock_event["scan_selection"]` para medir si la selección ayuda.

Este diseño evita dos errores de marco de referencia que convierten una respuesta correcta en una maniobra en sentido contrario (cap. 9, §9.8.1): etiquetar las imágenes con el rumbo absoluto y pedir al modelo un ángulo relativo, y medir el error de rumbo a la meta desde el yaw final del barrido en lugar del de cada imagen. Por eso el modelo nunca reporta ángulos: identifica imágenes por número y el código usa el yaw medido.

**Fallas.** Watchdog `SLM_DEEP_WATCHDOG_MS` (18 s en producción) vencido, pedido perdido (`SCAN_LOST_GRACE_MS`, 3 s), respuesta sin el formato del modo o respuesta cortada por el tope de tokens: el barrido deja una entrada `arm = "deep_scan_failed"` con sus fotogramas y devuelve `False`.

## 5.13 Nodo `motor`

Único nodo que interactúa con el actuador. Lee `velocity_command` y aplica, en orden:

**Ancla de altitud en `FRENAR`.** En el primer ciclo de `FRENAR` ancla `_hover_alt_anchor = z`; en los siguientes, si `|anchor − z| > 0.3 m`, inyecta `vz = clamp(0.35 × dz, ±0.8 m/s)`. Corrige la deriva vertical de reemitir `moveByVelocityBodyFrameAsync(vz = 0)` (medido: hasta 9 m en 120 s sin corrección).

**Gobernador de velocidad** (`src/navigation/speed_governor.py`). Limita solo el avance de `MANTENER_RUMBO`, según cuánta evidencia perceptual hay y qué pasó recientemente: sin flujo válido durante 3 ciclos seguidos, tope de 1.5 m/s, y durante 8, de 1.0 m/s; tras un frente bloqueado (GIRAR_90 o `blocked_fraction` ≈ 1), tope de 1.0 m/s durante 40 ciclos; al terminar una maniobra, rampa lineal del tope de 1.0 a 6.0 m/s en 15 ciclos (por encima de la velocidad de crucero, el tope deja de actuar). Su función es que la ausencia de evidencia no se trate como espacio libre: sin él, con el campo sin evidencia y una pared a 4 m, el guiado puede acelerar al dron hacia ella. Se desactiva con `GOV_ENABLED = false`.

**Actuación no bloqueante.** `execute_velocity(vx, vy, vz, yaw_rate, target_yaw)`: con `target_yaw` usa orientación absoluta (`YawMode(is_rate=False)`); sin él, tasa angular.

## 5.14 Mapa de macro-acciones (`action_to_command`)

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

`RETROCEDER` forma parte del vocabulario, pero **ningún comportamiento del brazo `slm` lo emite** (§5.3.4). `GANAR_ALTURA` asciende en el lugar y sin deriva lateral: una deriva alejaría el waypoint en el plano XY, la métrica que decide si el atasco se resolvió.

Las duraciones de las maniobras comprometidas son: `MANEUVER_DURATION_S` (2.0 s en producción) para `EVADIR_*` y para la macro resuelta por el barrido; `ESCAPE_MANEUVER_DURATION_S` (1.6 s) para el escape vertical; `GIRAR90_DURATION_S` (1.0 s) para el giro.

## 5.15 Guiado a waypoint: `WaypointTracker`

`WaypointTracker` (`src/navigation/waypoint_tracker.py`) corre en el bucle externo, **fuera del grafo**, una vez por ciclo antes de `graph.invoke()`. `update(pos)` avanza el waypoint activo al entrar en el radio de aceptación (3.5 m; bajo un techo detectado, por distancia horizontal) y `compute_guidance()` produce `vx`, `vy`, `vz`, `yaw_rate` en marco del cuerpo, con corrección de *cross-track*, zona muerta angular, tope de guiñada diferenciado (15°/s, 45°/s con desvío > 60°), histéresis entre regímenes, suavizado EMA y el modo `near_vertical` (`vx = 0` si `dist_xy < 1 m` y `|dz| > 0.3 m`, necesario para el patrón *climb-first* de Tier 2).

**Despegue vertical.** Hasta que el dron llega a `TAKEOFF_ALT_TOL_M` (1 m) de la altitud del primer objetivo, `compute_guidance()` no avanza en horizontal (`vx = 0`): sube en el lugar mientras alinea el rumbo, y exporta `takeoff = True`. La fase ocurre una vez por misión y termina antes si se detecta un techo. Avanzar mientras se sube puede llevar al dron contra una estructura más baja que la altitud de crucero pero más alta que la altitud de ese momento (cap. 9, §9.8.8). Durante la fase, los tres brazos usan `reactive_node` y el `StallDetector` no cuenta atasco.

### 5.15.1 Contador de progreso

`record_progress(dist_xy, bearing_err_deg)` mantiene `evasion_stuck_cycles`: se reinicia cuando la distancia mejora `WAYPOINT_PROGRESS_EPS_M` (0.5 m) sobre la mínima vista; se exime al dron que gira activamente (error de rumbo > 30°) hasta 15 ciclos consecutivos; en otro caso, se incrementa. Este contador lo consume el brazo `fsm`; el brazo `slm` usa las señales del `StallDetector` (§5.3.1).

### 5.15.2 Umbrales de atasco

`effective_stall_threshold()` es el mínimo de ciclos sin progreso físicamente demostrable: con `eps = 0.5 m`, velocidad mínima 0.25 m/s y 5 Hz, 10 ciclos. `hard_stall_threshold()` lo multiplica por `STUCK_HARD_FACTOR` (1.5 en producción: 15 ciclos). Ambos los usa la FSM.

### 5.15.3 Detección de techo

Con un waypoint bajo una estructura horizontal, la corrección de altitud empuja al dron contra la losa. El tracker lo detecta: si durante 10 ciclos, con el dron libre en horizontal, se **ordena** ascenso (`vz < −0.3 m/s` en el comando efectivamente ejecutado, que el bucle externo le informa con `note_executed_command()`; altitud ≥ 3 m) sin que la cota varíe más de 0.15 m, declara un techo (`ceiling_z`), liberado al alejarse 15 m o al cambiar de waypoint. Con techo, `compute_guidance()` limita la altitud objetivo a `ceiling_z + CEILING_MARGIN_M` (0.8 m) y, si el waypoint cae dentro de `CEILING_SAFE_GAP_M` (3 m) del techo, lo baja a esa banda y exporta `z_path_blocked = True`, que `navigate` resuelve con `PERDER_ALTURA` (regla 6). Usar el comando ejecutado y no la demanda del guiado importa: durante un `GIRAR_90` o un `FRENAR` el comando vertical es cero aunque el guiado pida subir, y esos ciclos no prueban que haya una losa encima. Por la misma razón no cuentan los ciclos en que el dron está trabado de costado —se ordenó avanzar y no se desplazó más de `CEILING_SIDEWAYS_STUCK_M` (3 cm por ciclo)—: el roce contra una pared también impide subir, y ese caso lo resuelve el deadlock.

### 5.15.4 Sub-metas del VLM

`inject_corner_waypoint(x, y, z, label)` inserta una sub-meta temporal delante del waypoint activo. Todas las sub-metas del brazo `slm` provienen del VLM (capa estratégica o barrido) y se insertan **tal cual**: una sub-meta nueva reemplaza a las temporales pendientes y reinicia el contador de progreso. La única condición es la deduplicación: si la sub-meta pendiente está a menos de `SUBGOAL_DEDUP_M` (10 m) de la nueva, la nueva se ignora; reemplazarla por otra casi igual reiniciaría el contador de progreso y un dron atascado nunca declararía el deadlock.

**Una sub-meta es un medio, no una condición.** `update()` mide en cada ciclo la distancia al waypoint **real** aunque el objetivo activo sea una sub-meta: si el dron entra en el radio de aceptación del waypoint real, descarta las sub-metas pendientes (`drop_temporary()`) y lo acepta. El bucle externo también las descarta cuando la capa estratégica marca `_clear_subgoals` (§5.10.3).

## 5.16 Salvaguardas y contratos de diseño

**Exclusión total de profundidad.** Ningún componente del lazo de vuelo —nodos del grafo, `main.py`, `experiments/runner.py`, módulos de navegación— lee el canal de profundidad del simulador. El test estático `tests/test_no_depth_in_flight_path.py` lo verifica sobre todos los módulos de `src/agents`, `src/perception` y `src/navigation` y sobre ambos puntos de entrada, buscando también canales indirectos, como un tope de velocidad armado desde el runner con la cámara de profundidad (`_depth_brake_left`), que daría al brazo evaluado acceso a la profundidad del simulador, de la que salen las etiquetas de referencia (cap. 9, §9.8.5). Solo los scripts de calibración offline (cap. 7) y la auditoría de la distancia mínima a obstáculo (`src/logging/distmin_audit.py`, cap. 10 §10.6.1) usan el canal de profundidad. La auditoría es un hilo aislado con su propia conexión al simulador, que solo escribe un archivo de muestras; la guardia verifica que no importe ningún módulo del grafo, que el runner se limite a arrancarlo y detenerlo, y que ningún otro módulo de vuelo lo referencie.

**El VLM sin overrides.** La respuesta del modelo se traduce a geometría y se aplica; no pasa por reglas deterministas que la reemplacen. Las validaciones que sí existen (edad, cambio de waypoint, sub-meta superada, deduplicación) descartan respuestas **obsoletas**, no respuestas que una regla considere equivocadas.

**Contrato de `deliberations[]`.** Solo agregado: se suman entradas, nunca se borran campos. Los análisis de los capítulos 9 a 11 se derivan de este registro.

**Cliente AirSim como singleton.** `compile_workflow(airsim_client)` recibe un cliente ya conectado; un segundo cliente tendría su propio `takeoffAsync`, desconectado del grafo.

## 5.17 Modo degradado

Cuando `degraded = True`, el ciclo va directo a `degraded_hover`: hover explícito, sin percepción ni decisión, sin sustituir el dato faltante por uno sintético.

## 5.18 Registro de vuelo y auditoría post-vuelo

Cada ejecución —de `main.py` o de cada celda del runner— genera una carpeta `<escenario>/<brazo>/<estrategia>/seed_N_<timestamp>/` con traza JSONL y CSV, resumen por waypoint, fotogramas de auditoría del VLM, video anotado de la cámara frontal (`.webm`), video de la cámara de seguimiento externa (`.follow.webm`, solo auditoría) y visor HTML. El runner graba video por defecto (`--no-video` lo desactiva).

**Traza completa del `DroneState`.** El JSONL conserva por ciclo el estado completo sin imágenes (`src/logging/state_serializer.py`); el CSV lo aplana en columnas `state.<ruta>`. La telemetría incluye `landed_state`.

**Auditoría del VLM.** Cada consulta resuelta —estratégica o de barrido— deja una entrada en `deliberations[]` y sus fotogramas RAW se asocian a la fila del ciclo en que la respuesta llegó (`_last_delib_frames`). Cada deliberación nueva se cuenta en `slm_invocations` en el ciclo en que aparece, cualquiera sea la ruta del ciclo (la capa estratégica resuelve mientras el dron vuela por la ruta reactiva o evasiva). Los barridos fallidos también se registran.

**Video en un hilo aparte.** La codificación VP8 ([Bankoski et al., 2011](13-REFERENCIAS.md#ref-bankoski-2011)) corre en un hilo con cola acotada y el cuadro se reduce a 0.6: codificar a 1080×720 dentro del lazo costaba ~275 ms por cuadro, llevaba el período de 0.21 a 0.45 s y degradaba el flujo óptico en el 64–82 % de los ciclos.

**Visor HTML.** Sincroniza video y traza por índice de ciclo y muestra el árbol del `DroneState` de cada ciclo.

## 5.19 Cierre de misión y vigilancia de congelamiento

**Aterrizaje suave (`land_smooth`).** Hover de 1.5 s, descenso con `moveToZAsync` a 0.5 m/s hasta z = −0.3 m y desarmado; evita la caída libre de `landAsync()` desde la altura de crucero.

**Vigilante de congelamiento físico** (`src/navigation/freeze_watchdog.py`, en el bucle externo). Si el estado físico del dron (posición, actitud y velocidad) queda idéntico durante `FREEZE_CYCLES` (25) ciclos, el dron está incrustado en la malla: con `FREEZE_RECOVERY = abort` (producción) la corrida termina con `termination_reason = "physics_locked"`; con `teleport`, vuelve a la última pose libre hasta `FREEZE_MAX_RECOVERIES` veces y lo registra como evento.

Ningún criterio de terminación usa la distancia al obstáculo: medirla en vuelo requeriría el canal de profundidad del simulador (§5.16). La métrica `min_obstacle_dist_m` la mide el hilo de auditoría y `finalize_run` la consolida en el `summary.json` al cerrar la corrida (cap. 10 §10.6.1).
