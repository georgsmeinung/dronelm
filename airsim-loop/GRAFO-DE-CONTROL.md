# Configuración del Grafo de Control

> Estado del lazo táctico de `airsim-loop` al **2026-08-24**, después de la implementación de `PLAN-MEJORAS.md` (F0–F4) y de la corrección del deadlock del escape por altura. Este documento describe la configuración **tal como está en el código**, no un diseño propuesto: cada umbral, cada orden de evaluación y cada nombre de variable son verificables en los archivos referenciados.
>
> Para el porqué histórico de cada decisión ver `CHANGELOG.md` (2026-0824) y `legacy/README.md`; para el detalle de lo retirado, `legacy/`.

---

## 1. Panorama

El grafo es un **lazo de control jerárquico** compilado con LangGraph que corre a `LOOP_HZ = 5.0` (período nominal 200 ms). Cada ciclo captura un frame + telemetría, produce un descriptor de escena, elige **una** macro-acción y la traduce a un comando de velocidad en *body frame*.

Tres principios estructuran la configuración actual:

1. **Un solo camino por ciclo.** Un único router de política (`policy_router`) decide el destino táctico; no hay nodos que invoquen otros nodos dentro de su cuerpo. Esto elimina estructuralmente la posibilidad de consultar al SLM dos veces en el mismo ciclo (bug F0.2).
2. **El lazo nunca se bloquea.** La consulta al SLM corre en un hilo aparte (`DeliberationService`) y el actuador es *last-command-wins*: el período del lazo es consecuencia de la captura, no de la latencia del modelo ni del actuador.
3. **Un solo contrato de percepción.** Todos los consumidores leen `ObstacleField` y nada más. No hay acceso a flujo óptico crudo, máscaras ni detecciones desde la capa de política.

El "cerebro" que resuelve las situaciones de riesgo es seleccionable con `AGENT_ARM` (`slm` | `fsm` | `reactive`) sobre **el mismo pipeline de percepción y la misma cinemática**, de modo que la comparación entre brazos aísle exactamente la variable de interés: quién elige la macro-acción.

---

## 2. Topología

```
                        ┌──────────────────┐
   entry point ───────► │   capture_node   │  RGB + telemetría + ring buffer de frames
                        └────────┬─────────┘
                                 │
                      ┌──────────▼───────────┐
                      │   degraded_router    │  ¿AirSim respondió este ciclo?
                      └──┬────────────────┬──┘
                 degradado│                │ ok
                          ▼                ▼
                ┌──────────────────┐  ┌──────────────────┐
                │  degraded_hover  │  │    perception    │  flujo óptico → derotación
                └────────┬─────────┘  └────────┬─────────┘  → FOE → ObstacleField
                         │                     │
                         │           ┌─────────▼──────────┐
                         │           │   policy_router    │  brazo + decisión táctica
                         │           └─┬───┬───┬────┬───┬─┘
                         │             │   │   │    │   │
              ┌──────────┘   keep_going│   │   │    │   │fsm
              │                        │   │   │    │   │
              │        ┌───────────────┘   │   │    └───┼──────────────┐
              │        │      evasive ◄────┘   │        │              │
              │        │                girar_90        │              │
              │        │                       │   deliberative        │
              ▼        ▼                       ▼        ▼              ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                          motor_node                              │
        │      (ancla de altitud en FRENAR + execute_velocity no bloqueante)│
        └───────────────────────────────┬──────────────────────────────────┘
                                        ▼
                                       END
```

**Aristas** (`build_workflow`, [`src/agents/graph.py`](src/agents/graph.py)):

| Origen | Tipo | Destinos |
|---|---|---|
| *(entry)* | fija | `capture` |
| `capture` | condicional (`degraded_router`) | `degraded_hover`, `perception` |
| `perception` | condicional (`policy_router`) | `keep_going`, `evasive`, `girar_90`, `deliberative`, `fsm` |
| `degraded_hover`, `keep_going`, `evasive`, `girar_90`, `deliberative`, `fsm` | fijas | `motor` |
| `motor` | fija | `END` |

Todo ciclo termina en `motor_node`: **hay exactamente un comando de velocidad emitido por ciclo**, cualquiera sea la rama tomada.

---

## 3. El estado (`DroneState`)

`DroneState` es un `TypedDict` y LangGraph construye los **canales** del grafo a partir de él. Esto tiene una consecuencia operativa que es parte de la configuración, no un detalle de implementación:

> **Regla:** toda clave que cruce la frontera *nodo ↔ lazo externo* **debe estar declarada** en `DroneState`. Una clave que un nodo escriba sin declarar se descarta en silencio en `graph.invoke()` — no hay error, no hay warning, el dato simplemente no existe del otro lado.

Esa regla es la que se violaba antes del 2026-08-24 con `_escape_reset`, y produjo el deadlock documentado en `CHANGELOG.md`: el contador de atasco nunca se reiniciaba, el router quedaba clavado en la rama deliberativa y el SLM no se consultaba ni una vez en 76 ciclos de vuelo.

### Campos por rol

**Percepción y sensores**

| Campo | Tipo | Escrito por |
|---|---|---|
| `rgb_image`, `prev_image` | frame BGR | `capture` |
| `frame_history` | ring buffer de `VLM_FRAME_HISTORY_SIZE` frames | `capture` |
| `telemetry`, `prev_telemetry` | dict (posición, velocidad, actitud, colisión, `timestamp`) | `capture` / lazo |
| `degraded` | bool — AirSim no respondió | `capture` |
| `obstacle_field` | `ObstacleField` 3×3 | `perception` |
| `estimated_ttc`, `scene_summary` | derivados del campo, para display y logging | `perception` |

**Misión y guiado** — los escribe el **lazo externo**, no el grafo:

`waypoints`, `current_wp_index`, `target_waypoint`, `waypoint_guidance`, `mission_completed`.

**Decisión y actuación**

`next_action` (macro-acción elegida), `velocity_command` (comando final), `route` (rama tomada), `flight_status` (etiqueta de estado para UI/logging).

**Deliberación**

`deliberations[]` (auditoría completa: prompt, respuesta cruda, latencia, si fue fallback, si hubo timeout, si adhirió al esquema), `last_deliberation`, `slm_request_id`, `_deliberation_pending`, `_delib_outcomes`, `_delib_baseline`, `_delib_last_baselined_id`.

**Persistencia de maniobra**

`active_maneuver`, `maneuver_cycles_left`, `maneuver_command`.

**Escape de deadlock**

`evasion_stuck_cycles`, `_consecutive_escapes`, `_escape_locked`, `_escape_baseline_dist`, `_escape_reset`.

**Otros**

`_hover_alt_anchor` (altitud anclada durante `FRENAR` prolongado), `inject_corner` (sub-waypoint de esquina propuesto al tracker).

---

## 4. El lazo externo (`main.py`)

No todo vive en el grafo. El orden por ciclo en [`main.py`](main.py) es:

1. **Telemetría fresca** (`get_telemetry`) — independiente de la captura de imagen.
2. **`waypoint_tracker.update(pos)`** — avanza el waypoint activo si se entró en el radio de aceptación (`WAYPOINT_ACCEPTANCE_RADIUS = 3.5 m`).
3. **`compute_guidance(pos, yaw)`** — vector de guiado en body frame, con corrección de *cross-track error* al corredor de calle, histéresis de régimen y suavizado EMA.
4. **`record_progress(dist_xy)`** — actualiza el contador de atasco, **salvo** que `_deliberation_pending` esté activo (frenar a propósito esperando al SLM no es "no progresar"). Se usa distancia **horizontal**: subir no debe empeorar la métrica que decide si un escape por altura funcionó.
5. **`graph.invoke(drone_state)`** — un ciclo completo del grafo.
6. **`pop("_escape_reset")`** → si estaba marcado, `waypoint_tracker.reset_progress()`.
7. `_update_delib_outcomes()` — mide el efecto de la decisión deliberativa anterior (Δdistancia, ΔTTC) para realimentarlo al prompt.
8. `inject_corner` → `waypoint_tracker.inject_corner_waypoint()` si el grafo lo propuso.
9. Impresión de estado, logging JSONL, publicación al stream de WebDCS, chequeo de fin de misión.
10. `sleep` hasta completar el período de `LOOP_HZ`.

Los pasos 6 y 8 son exactamente los que dependen de la regla de declaración de la §3.

---

## 5. Nodos

### `capture_node`
Un único `AirSimClient` por proceso, inyectado en `compile_workflow()` (F0.3). Con `AIRSIM_STRICT=true` (default en vuelo), si AirSim no responde **no** fabrica un frame sintético: marca `degraded=True` y el ciclo deriva a hover de seguridad. Mantiene el ring buffer `frame_history` solo con frames reales.

### `degraded_hover_node`
`FRENAR` explícito, sin percepción ni deliberación. Es la rama de "no sé nada de mi entorno": la única respuesta correcta es no moverse.

### `perception_node`
Único punto de percepción pesada. `FlowTTCEstimator` (instanciado **una vez**, no por frame) produce el `ObstacleField` del ciclo: flujo óptico → derotación por actitud → FOE por mínimos cuadrados ponderados con recorte de outliers → TTC en segundos reales usando el `dt` de telemetría. Sin evidencia suficiente (hover, giro puro, flujo bajo el piso de ruido) devuelve `confidence = 0` y `ttc = inf`; no hay clamp cosmético que disfrace la falta de señal.

### `keep_going` (`reactive_node`)
Guiado nominal a waypoint. Toma `vx`/`vz`/`yaw_rate` directamente del `waypoint_guidance`. Es también el brazo completo cuando `AGENT_ARM=reactive` (cota inferior de la comparación: navega, no evade).

### `evasive_node`
Dos modos:
- **Continuación de maniobra comprometida** (anti flip-flop): si hay `active_maneuver` con ciclos restantes, la sostiene, cerrando el lazo sobre `target_yaw` (±15 °/s, con zona muerta de 3° y un empujón de `vx = 0.8` una vez alineado).
- **Corrección lateral rápida**: elige el lado con menor ocupación (a igualdad, mayor TTC) y avanza a `vx = 1.2` mientras gira.

### `girar_90_node`
Bypass determinista para FOV mayormente bloqueado: giro sobre el eje, sin traslación, con el rumbo objetivo *snapeado* a la cuadrícula Manhattan (múltiplo de 90°). **Elige el lado según el error de rumbo al waypoint**, no siempre a la derecha.

### `deliberative_node` (brazo `slm`)
Ver §7. Nunca bloquea: encola el pedido y frena ese ciclo; en ciclos siguientes hace `poll()` hasta que haya respuesta o expire el watchdog.

### `fsm_node` (brazo `fsm`)
Máquina de estados determinista (`CRUISE`, `AVOID_LEFT`, `AVOID_RIGHT`, `CLIMB`, `BRAKE`) sobre el **mismo** `ObstacleField` y la **misma** `action_to_command()` que usa el brazo SLM. Tiene la misma persistencia de maniobra y el mismo enclavamiento de escape, para que la comparación no mida quién tiene mejor puesta la salvaguarda sino quién elige mejor la acción.

### `motor_node`
Emite el comando final. Dos responsabilidades adicionales:
- **Ancla de altitud durante `FRENAR`.** `moveByVelocityBodyFrameAsync(vz=0)` reemitido cada ciclo es un controlador de *velocidad*, no de altitud: pedir "velocidad cero" repetidamente no es lo mismo que pedir "quedate en esta altura" (≈9 m de deriva medidos en 120 s de freno sostenido). El nodo ancla la altitud al primer ciclo de freno y corrige `vz` con zona muerta de 0.3 m, `kp = 0.35`, tope ±0.8 m/s.
- **Actuación no bloqueante.** `execute_velocity()` no hace `.join()` sobre el comando anterior; `cancelLastTask()` descarta el comando en curso sin bloquear, permitiendo abortar una maniobra a mitad de ejecución.

---

## 6. Routers

### `degraded_router`
Una línea: `degraded_hover` si `degraded`, si no `perception`.

### `policy_router` — cascada de decisión

El orden de evaluación **es** la política. Se evalúa de arriba hacia abajo y el primer match gana:

| # | Condición | Destino | Racional |
|---|---|---|---|
| 0 | `AGENT_ARM == "reactive"` | `keep_going` | Brazo cota inferior |
| 0 | `AGENT_ARM == "fsm"` | `fsm` | Brazo determinista |
| 1 | `active_maneuver` con ciclos restantes **y** `min_ttc > TTC_EVASION_THRESHOLD` | `evasive` | Persistencia anti flip-flop. Una maniobra comprometida no se preempta; la condición de TTC seguro garantiza que una emergencia real sí la interrumpa |
| 2 | `stuck ≥ umbral_efectivo` **y** (`stuck ≥ umbral_duro` **o** no hay corredor abierto) | `deliberative` | Escape de deadlock, ya **no** ciego a la percepción |
| 3 | `centro_ttc ≤ TTC_EVASION` **o** (`centro bloqueado` y `centro_ttc ≤ TTC_SAFE`) | `girar_90` si `blocked_fraction > FOV_BLOCKED_THRESHOLD`, si no `deliberative` | Peligro estructural al frente: bypass determinista si no hay nada que decidir (todo bloqueado), deliberación si hay opciones |
| 4 | `centro bloqueado` **o** `min_ttc ≤ TTC_SAFE` | `evasive` | Ventana de advertencia: corrección lateral rápida, sin gastar una consulta al SLM |
| 5 | — | `keep_going` | Camino despejado |

Dos propiedades del orden actual que importan:

- **La persistencia (paso 1) está por encima del escape (paso 2).** Si no lo estuviera, el giro de cambio de estrategia que emite el escape agotado sería preemptado por el propio contador de atasco antes de llegar a ejecutarse.
- **El escape (paso 2) ya no cortocircuita la percepción.** Con evidencia válida de sector transitable, manda la decisión táctica normal. El bypass tiene techo (`umbral_duro`) para que un campo "despejado" espurio no desactive el escape indefinidamente.

### `has_open_corridor()`

Consulta compartida por router, `deliberative` y `fsm` ([`src/perception/obstacle_field.py`](src/perception/obstacle_field.py)). Devuelve verdadero solo si:

1. el campo **tiene evidencia real** (`source == "flow"` y `foe_confidence > 0`), y
2. existe al menos un sector con confianza sobre el piso (`≥ 0.15`) y **no bloqueado**, priorizando el sector donde cae el waypoint (banda de ±15° de rumbo).

El requisito (1) es deliberado: *"sin evidencia" no es lo mismo que "despejado"*. Un hover sin flujo óptico produce exactamente ese vacío, y tratarlo como corredor abierto desactivaría el escape justo cuando más hace falta.

---

## 7. El nodo deliberativo, ciclo a ciclo

```
                    ┌──────────────────────────────┐
                    │  ¿hubo progreso horizontal    │
                    │  desde el último escape?      │──sí──► liberar enclavamiento,
                    └──────────────┬───────────────┘         contador de escapes = 0
                                   │ no
                    ┌──────────────▼───────────────┐
                    │  stuck ≥ umbral  Y            │
                    │  no enclavado    Y            │──no──►  DELIBERACIÓN NORMAL
                    │  sin corredor abierto         │
                    └──────────────┬───────────────┘
                                   │ sí
                         ESCAPE DE DEADLOCK
                                   │
              ┌────────────────────┴────────────────────┐
              │ escapes consecutivos ≤ MAX              │  ► GANAR_ALTURA
              │ y altitud ≤ MAX_ESCAPE_ALT_M            │    (maniobra de 1.6 s)
              └────────────────────┬────────────────────┘
                                   │ agotado o techo
                                   ▼
                       ENCLAVAR (_escape_locked = True)
                       + CAMBIO DE ESTRATEGIA: GIRAR_90
                       hacia el lado del waypoint
                                   │
                                   ▼
                  ciclos siguientes → DELIBERACIÓN NORMAL
```

### Deliberación normal (asíncrona)

| Situación | Comando del ciclo | Estado |
|---|---|---|
| Sin pedido pendiente | `FRENAR` | Encola el pedido, `_deliberation_pending = True` |
| Pedido pendiente, sin respuesta, dentro del watchdog | `FRENAR` | Sigue esperando, **no** re-encola |
| Llegó la respuesta | La macro-acción decidida | Registra la deliberación, libera el freno |
| Watchdog expirado (`SLM_WATCHDOG_MS = 6000`) | Fallback determinista | `timeout = True` en la auditoría |

`_deliberation_pending` es lo que hace que frenar a propósito esperando al SLM **no** cuente como "no progresar": sin esa marca, una latencia real de 2–8 s disparaba el escape antes de que el modelo pudiera responder.

### Salvaguardas sobre la decisión del modelo

- **Override de seguridad:** `MANTENER_RUMBO` con el centro bloqueado y `TTC ≤ SAFE_MARGIN_TTC_S (2.0 s)` se reemplaza por el fallback determinista. El modelo no puede decidir seguir de frente contra una estructura cercana.
- **Espacio de acciones acotado:** el SLM elige solo entre `MANTENER_RUMBO`, `EVADIR_IZQUIERDA`, `EVADIR_DERECHA`, `GANAR_ALTURA`, `PERDER_ALTURA`, `FRENAR`. `GIRAR_90` es un bypass determinista, nunca una elección del modelo.
- **Decodificación restringida** (`response_format=json_schema`) cuando el servidor la soporta, con parser ultratolerante como red de seguridad. Se registra `used_json_schema` y `adherent` por deliberación.
- **Fallback determinista** sobre `ObstacleField` cuando el modelo no responde o no adhiere: sin evidencia → `FRENAR`; centro bloqueado con ambos lados bloqueados → `GANAR_ALTURA`; centro bloqueado con lado libre → evadir hacia ese lado (a igualdad, hacia el waypoint).

### Contador de escapes: por qué se mide con distancia y no con el contador de atasco

El propio escape pide `_escape_reset`, que pone `evasion_stuck_cycles` en cero al ciclo siguiente. Si el contador de escapes consecutivos se colgara de esa señal, **cada escape "parecería" haber resuelto el atasco** y `MAX_CONSECUTIVE_ESCAPES` nunca se alcanzaría. La única evidencia válida de que subir sirvió es que la distancia **horizontal** al waypoint bajó de verdad (`_escape_baseline_dist`, margen `WAYPOINT_PROGRESS_EPS_M`).

---

## 8. Cinemática por macro-acción

`action_to_command()` ([`src/agents/action_map.py`](src/agents/action_map.py)) es la **única** fuente de verdad; `deliberative`, `evasive`, `fsm` y las ramas de escape la comparten. Body frame, NED (`vz` negativo = sube).

| Macro-acción | `vx` | `vy` | `vz` | `yaw_rate` | `target_yaw` |
|---|---|---|---|---|---|
| `MANTENER_RUMBO` | del guiado | 0 | del guiado | del guiado | — |
| `EVADIR_IZQUIERDA` | 0.8 (0.3 si estructura cercana) | 0 | del guiado | −15 °/s | snap −90° |
| `EVADIR_DERECHA` | 0.8 (0.3 si estructura cercana) | 0 | del guiado | +15 °/s | snap +90° |
| `GANAR_ALTURA` | 0 | 0 | −1.5 | **del guiado** | — |
| `PERDER_ALTURA` | 1.0 | 0 | +0.8 | 0 | — |
| `GIRAR_90` | 0 | 0 | 0 | ±20 °/s **según lado del waypoint** | snap ±90° |
| `FRENAR` *(y toda acción desconocida)* | 0 | 0 | 0 | 0 | — |

Dos entradas de esta tabla cambiaron el 2026-08-24 y conviene entender por qué:

- **`GANAR_ALTURA` llevaba `vy = 0.5` y `yaw_rate = 0`.** Una deriva lateral constante en una macro-acción de *ascenso* alejaba el waypoint en el plano XY — la misma métrica que decide si el atasco se resolvió — mientras el rumbo quedaba congelado. El escape se alimentaba a sí mismo.
- **`GIRAR_90` giraba siempre +90.** Podía mandar al dron en contra de la corrección que el guiado venía aplicando.

El *snap* Manhattan redondea el rumbo objetivo al múltiplo de 90° más cercano, alineando las maniobras con la cuadrícula urbana del escenario.

---

## 9. Umbrales y variables de entorno

### Percepción y disparo táctico

| Variable | Valor | Origen |
|---|---|---|
| `TTC_EVASION_THRESHOLD` | 3.2 s | **Calibrado** (F1.3): umbral de Youden, ROC contra el canal depth, τ = 2 s |
| `TTC_SAFE_THRESHOLD` | 4.6 s | **Calibrado** (F1.3): ídem, τ = 3 s |
| `FOV_BLOCKED_THRESHOLD` | 0.6 | Fracción de celdas bloqueadas que dispara `girar_90` |
| `OBSTACLE_OCCUPANCY_BLOCKED` | 0.35 | Umbral de ocupación de celda |
| `OBSTACLE_TTC_BLOCKED_S` | 2.5 s | TTC de celda que la marca bloqueada |
| `OBSTACLE_MIN_CONFIDENCE` | 0.15 | Piso de confianza: por debajo, la celda no aporta evidencia |
| `SAFE_MARGIN_TTC_S` | 2.0 s | Margen del override de seguridad sobre la decisión del modelo |

> **Caveat de calibración (F1.3):** AUC 0.96–0.97 para "colisión dentro de τ" pese a correlación punto a punto baja (r = −0.034, error relativo mediano 66 %) — el *ranking* de riesgo separa bien las clases aunque la magnitud puntual sea ruidosa. Una sola sesión de vuelo, sin variación de `|yaw_rate|`: valida la detección frontal, **no** valida aún la derotación en giros fuertes.

### Atasco y escape

| Variable | Valor | Rol |
|---|---|---|
| `EVASION_STUCK_THRESHOLD` | 10 ciclos | Valor configurado (piso) |
| `WAYPOINT_PROGRESS_EPS_M` | 0.5 m | Mejora mínima que cuenta como progreso |
| `MIN_PROGRESS_SPEED_MPS` | 0.25 m/s | Velocidad de acercamiento por debajo de la cual se acepta que no hay progreso |
| `STUCK_HARD_FACTOR` | 3.0 | Multiplicador del umbral duro |
| `MAX_CONSECUTIVE_ESCAPES` | 2 | Ascensos consecutivos sin progreso antes de enclavar |
| `MAX_ESCAPE_ALT_M` | 30.0 m | Techo del escape por altura |

El umbral efectivo **no** es el configurado: se deriva para que sea coherente con la métrica que lo alimenta.

```
umbral_efectivo = max(EVASION_STUCK_THRESHOLD, ceil(EPS_M × LOOP_HZ / MIN_PROGRESS_SPEED))
                = max(10, ceil(0.5 × 5.0 / 0.25)) = 10 ciclos  (2.0 s)

umbral_duro     = ceil(umbral_efectivo × STUCK_HARD_FACTOR) = 30 ciclos  (6.0 s)
```

**Por qué existe esta derivación.** Declarar el umbral en *ciclos* y el epsilon en *metros* de forma independiente produce combinaciones imposibles: para no acumular atasco hace falta una velocidad de acercamiento de `EPS × LOOP_HZ / umbral`. Con los valores anteriores (0.5 m, 5 ciclos, 5 Hz) eso exigía **0.5 m/s sostenidos**, mientras el guiado en giro cerrado limita `vx` a 0.8 m/s con el rumbo a ~70° del objetivo (≈0.25 m/s reales). El escape estaba **garantizado a los 5 ciclos de arrancar la misión, sin ningún obstáculo**.

### Guiado

| Variable | Valor | Rol |
|---|---|---|
| `REACTIVE_FORWARD_SPEED` | 2.0 m/s | Velocidad de crucero |
| `WAYPOINT_ACCEPTANCE_RADIUS` | 3.5 m | Radio de aceptación de waypoint |
| `GUIDANCE_SMOOTHING_ALPHA` | 0.5 | EMA de `vx`/`yaw_rate` (≈94 % de un escalón en ~4 ciclos) |
| `GUIDANCE_YAW_RATE_MAX_DPS` | 15 °/s | Tope de giro en régimen normal |
| `GUIDANCE_YAW_RATE_SHARP_MAX_DPS` | 45 °/s | Tope de giro con desvío > 60° |

El tope diferenciado existe porque con un único tope de 15 °/s realinear un desvío de ~70° tardaba más que lo que tarda el contador de atasco en dispararse: el dron se declaraba atascado por no terminar un giro que el propio limitador le impedía terminar a tiempo.

**Histéresis del guiado.** Tres regímenes con banda de entrada distinta a la de salida, para que un valor oscilando en el borde no alterne la fórmula cada ciclo (esa alternancia es el cabeceo observado en vuelo real): giro brusco (entra > 60°, sale < 50°), aproximación final (entra < 4.0 m, sale > 4.5 m), zona muerta de yaw (entra > 2.5°, sale < 1.5°).

### Deliberación

| Variable | Valor | Rol |
|---|---|---|
| `AGENT_ARM` | `slm` | Brazo activo: `slm` \| `fsm` \| `reactive` |
| `LOCAL_LLM_MODEL_NAME` | `qwen/qwen2.5-vl-3b` | Modelo local |
| `SLM_WATCHDOG_MS` | 6000 ms | **Calibrado**: 4 muestras reales dieron 8298 / 3405 / 2201 / 1911 ms (la primera es cold-start); el default anterior de 1500 ms garantizaba fallback en el 100 % de los casos aunque el servidor estuviera sano |
| `VLM_VISION_ENABLED` | `true` | Visión directa vs. texto puro |
| `VLM_IMAGE_MAX_SIZE` | 384 px | Reescalado antes de codificar |
| `VLM_FRAME_HISTORY_SIZE` | 1 | Frames enviados al VLM |
| `VLM_USE_JSON_SCHEMA` | `true` | Decodificación restringida |
| `MANEUVER_DURATION_S` | 1.0 s (5 ciclos) | Persistencia de maniobra deliberada |
| `ESCAPE_MANEUVER_DURATION_S` | 1.6 s (8 ciclos) | Persistencia de maniobra de escape |

### Infraestructura

`AIRSIM_IP=127.0.0.1` (mismo host que Unreal Engine), `AIRSIM_RPC_TIMEOUT=8 s`, `AIRSIM_STRICT=true`, `LOOP_HZ=5.0`, `GRAPH_TIMEOUT_S=30.0`.

> El simulador corre **local** y el servidor del SLM **remoto**: la latencia de red del modelo está absorbida por diseño (servicio asíncrono), la del RPC de AirSim no. Sobre LAN, `simGetImages` daba timeout de 8–9 s en **todas** las resoluciones por igual — independiente de la resolución, o sea el socket RPC, no el ancho de banda.

---

## 10. Invariantes

Lo que la configuración actual garantiza, y dónde se verifica:

| Invariante | Test |
|---|---|
| Como máximo una consulta al SLM por ciclo | `test_graph_integration.py::test_single_cycle_produces_at_most_one_new_deliberation` |
| El lazo nunca bloquea esperando al modelo | `test_escape_deadlock.py::test_waiting_for_slm_does_not_trigger_altitude_escape` |
| Las claves de control cruzan la frontera nodo ↔ lazo | `test_graph_integration.py::test_control_keys_survive_graph_invoke` |
| El contador de atasco se reinicia tras un escape | `test_graph_integration.py::test_stall_counter_resets_after_escape_in_main_loop` |
| El escape agotado enclava y no reintenta subir | `test_escape_deadlock.py::test_max_consecutive_escapes_latches_and_changes_strategy` |
| El enclavamiento se libera solo con progreso medido | `test_escape_deadlock.py::test_escape_lock_releases_after_real_horizontal_progress` |
| El escape no dispara con corredor visible | `test_escape_deadlock.py::test_escape_does_not_fire_when_perception_sees_an_open_corridor` |
| El atasco no cortocircuita la percepción (con techo) | `test_policy_router.py::test_stuck_does_not_short_circuit_an_open_corridor`, `::test_hard_stuck_overrides_the_open_corridor_bypass` |
| Una maniobra comprometida no se preempta | `test_policy_router.py::test_committed_maneuver_is_not_preempted_by_the_stall_counter` |
| El umbral de atasco es coherente con su métrica | `test_waypoint_tracker.py::test_effective_stall_threshold_is_coherent_with_the_progress_epsilon` |
| Ninguna macro-acción produce velocidades desbocadas | `test_action_map.py::test_every_valid_action_maps_to_bounded_command` |
| Sin AirSim, hover explícito y sin deliberación | `test_degraded_mode.py` |
| El giro puro no dispara freno espurio | `test_flow_ttc.py` |
| El prompt no inventa historia temporal | `test_prompt_invariants.py` |

**94 tests**, sin AirSim (stub con la misma interfaz):

```bash
pytest tests/ -q
```

Los tests que cubren la frontera del grafo corren el **grafo compilado**, no el nodo suelto: el bug de las claves descartadas solo existe en esa frontera y los tests que invocaban `deliberative_node(dict)` directamente pasaban con el bug presente.

---

## 11. Limitaciones conocidas

- **El TTC no es confiable durante el propio escape.** `FRENAR` no produce traslación (sin flujo → sin FOE → sin evidencia) y el ascenso puro produce flujo vertical que genera FOE espurio con TTC de 0.1–0.4 s. La maniobra viola los supuestos del estimador que la está justificando: es una realimentación positiva cerrada, visible como `SIN EVIDENCIA` ↔ `BLOQUEADO 100%` alternando en ciclos consecutivos.
- **La derotación no está validada para yaw fuerte** (caveat F1.3): el dataset de calibración quedó casi todo en el bin `|yaw_rate| ∈ [0, 0.05)` rad/s.
- **`main.py` no tiene tope de duración de misión.** `experiments/runner.py` sí (`max_cycles` / `max_seconds`): un atasco genuinamente irresoluble no termina la corrida por sí solo en vuelo interactivo.
- **`vy` es siempre 0 en el guiado nominal.** El desplazamiento es puramente frontal + yaw (estrategia *car-like*); no hay vuelo lateral coordinado.

---

## 12. Referencias

- [`README.md`](README.md) — mapeo de código a grafo, ejecución, experimentos.
- `CHANGELOG.md` (2026-0824) — historia y evidencia medida de cada decisión.
- `PLAN-MEJORAS.md` — plan F0–F4 del que sale esta arquitectura.
- [`legacy/README.md`](legacy/README.md) — módulos retirados (YOLO, IPM, TTC anterior, gate XOR) con la justificación de cada retiro.
