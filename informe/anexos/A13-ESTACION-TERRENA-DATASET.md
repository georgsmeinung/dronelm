# Anexo 13: Estación terrena WebDCS, plan de ruta y dataset de corridas

El capítulo 4 presenta la arquitectura de dos cerebros, el manifiesto de misión, el plan de ruta con el VLM sobre el mapa cenital y el rol de la estación terrena en la auditoría. Este anexo reúne el detalle de implementación: la alternativa de juicio por imagen del planificador, la construcción del mapa cenital registrado, la interfaz WebDCS, la estructura completa del dataset de corridas y el visor de auditoría con las anotaciones del video.

---

## A13.1 Plan de ruta: detalle

### A13.1.1 Juicio por imagen (alternativa de contraste)

El código conserva una alternativa, `ROUTE_JUDGE=image`, que sirve de contraste para justificar la elección: dibuja cada candidata como un **pasillo** del ancho que necesita el dron (`ROUTE_RENDER=corridor`, `ROUTE_CORRIDOR_M` = 10 m) o como una línea (`ROUTE_RENDER=line`), sobre su propio recorte del mapa. El recorte se rota para que la ruta vaya del inicio (abajo, verde) al destino (arriba, azul), se acerca a la candidata (672 × 672 px) y fuera del pasillo el mapa se oscurece. Se le pregunta al modelo si todo el pasillo es calle o terreno abierto, con este prompt de sistema:

> You see a top-down city map. The bright strip outlined in red is a drone path from the green dot (bottom) to the blue dot; the rest is darkened. Answer yes only if the whole strip covers street or open ground, with no building, trees or elevated road inside it. Reply with JSON only.

y el mensaje, `Drone altitude 10 m. Is the whole bright strip street or open ground? yes or no.` La respuesta se fuerza a `yes`/`no` y la probabilidad de `yes` se lee de los *logprobs* del token de la respuesta.

### A13.1.2 Construcción del mapa cenital registrado

El plan de ruta solo tiene sentido si el mapa coincide con el mundo de vuelo. Los mapas de CitySim y TownSim se construyen con el propio simulador (`airsim-plan/scripts/capture_ortho_map.py`): el dron se reubica sobre una grilla de puntos a 1000 m de altura con la cámara frontal apuntando 90° hacia abajo y un campo visual de 15°, de modo que la vista es casi ortográfica. De cada toma se usa la mitad central y se la pega en el lienzo a 2 px/m en CitySim y 4 px/m en TownSim, con el origen NED en el centro de la imagen, el norte arriba y el este a la derecha. La orientación y la escala se verifican en el arranque desplazando el dron 20 m al norte y 20 m al este y midiendo el corrimiento de la imagen por correlación de fase.

Unreal Engine carga el escenario por zonas alrededor del punto de vista, y desde 1000 m no carga la zona de abajo: la imagen muestra solo calles y bases vacías. Por eso, antes de cada toma el dron baja a 40 m sobre el punto (la carga se completa en unos 3 s), vuelve a subir y captura enseguida. La toma se acepta cuando la fracción de píxeles de edificio, medida con la profundidad, deja de crecer entre dos capturas; un criterio por color no sirve, porque el agua animada nunca se estabiliza y una zona sin cargar está quieta. El resultado, `citysim_ortho.png`, cubre la ciudad completa (1920 m norte-sur por 1640 m este-oeste) y es el mapa de todas las misiones de CitySim. El de TownSim, `townsim_ortho.png` (24 tomas, 4 px/m), cubre 500 × 500 m alrededor del origen; superpuestas las trayectorias voladas, ninguna muestra de casi-contacto cae sobre pasto sin obstáculo. Las demás imágenes de esos niveles (`citymap.png`, `citysim_calib.png`, `townsim.png`, `townsim_calib.png`) no están registradas con el mundo y `airsim-plan/missions/maps/map_scales.json` las marca así.

---

## A13.2 Interfaz WebDCS

**WebDCS** (*Web-based Drone Control Station*) es la interfaz de control en tierra, construida sobre **FastAPI** con frontend en HTML5, CSS y JavaScript. Expone su API REST en `http://localhost:8000` y sirve el panel de operación como aplicación web estática.

![Interfaz de la Estación Terrena WebDCS](../2026-0903%20Nueva%20UX%20WebDCS.png)


1. **Gestión interactiva de cartas y waypoints:**
   El panel incorpora un visor Canvas 2D que superpone la trayectoria del manifiesto sobre la carta del entorno urbano (`CitySim`). El operador puede cargar manifiestos existentes desde `airsim-plan/missions/flightplans/`, visualizar la ruta proyectada y editar waypoints interactivamente sobre la carta — agregar, reordenar, eliminar y ajustar altitud — antes de guardar o lanzar.

2. **Lanzamiento y detención de misión:**
   El botón *Lanzar* invoca `POST /api/launch`, que persiste el manifiesto y arranca `airsim-loop` en un hilo de fondo sin bloquear la interfaz. `POST /api/stop` detiene todos los runners activos. `POST /api/reset` reinicia el simulador AirSim y libera el control de la API.

---

## A13.3 Dataset de corridas: estructura de `airsim-runs/`

Cada ejecución de una misión escribe una carpeta autocontenida en `airsim-runs/`. Desde `main.py` (WebDCS), el nombre de la carpeta y el prefijo común (`<stem>`) de sus archivos es `<MISSION_ID>-<YYYYMMDDTHHMMSSZ>`: el `mission_id` del manifiesto más la hora de inicio en UTC, en ISO 8601 compacto (por ejemplo, `CITYSIM_CLEAR-20260907T191226Z`). El ejecutor de experimentos (`experiments/runner.py`) ubica cada corrida en una jerarquía por celda experimental, `<escenario>/<brazo>/<celda>/seed_<N>_<timestamp>/`, con `<stem>` = `seed_<N>_<timestamp>`; la celda es la estrategia de deadlock (`depth`, `deep_vlm`, `blind`) o, si el lote varía la fuente de la capa estratégica, `strat_<fuente>__<estrategia>` (Anexo 12, IT.A12.9.1). En ningún caso una corrida sobrescribe a otra.

### A13.3.1 Archivos de una corrida

| Archivo | Lo escribe | Contenido |
|---|---|---|
| `<stem>.jsonl` | `FlightLogger`, ciclo a ciclo | Traza completa: un objeto JSON por ciclo, con el `DroneState` serializado |
| `<stem>.csv` | `FlightLogger` | La misma traza en columnas, más el `DroneState` aplanado en columnas `state.<ruta>` |
| `<stem>.summary.json` | `FlightLogger.close()` y `finalize_run` | Indicadores de la corrida: éxito, colisiones, DistMin, recorrido, consultas, deadlocks, plan de ruta, versión del código |
| `<stem>.summary_by_wp.csv` | `FlightLogger.close()` | Ciclos, duración, ciclos de barrido y eventos de barrido por objetivo |
| `<stem>.distmin.ndjson` | hilo de auditoría (`distmin_audit.py`) | Muestras de distancia mínima a obstáculo, una por segundo |
| `<stem>.console.log` | runner | Copia de la salida de consola de la corrida (stdout y stderr) |
| `<stem>.webm` | `FlightVideoRecorder` | Video de la cámara frontal, un cuadro por ciclo, con overlay |
| `<stem>.follow.webm` | `follow_cam.py` | Video de la cámara externa `FollowCam` (si está definida en `settings.json`), un cuadro por ciclo |
| `<stem>.viewer.html` | `flight_viewer.py` | Visor de auditoría autocontenido |
| `photo-<ISO_UTC>.png` | `FlightLogger` | Fotogramas de cada consulta del lazo lento (capa estratégica y barrido), a resolución completa |

Además, a nivel de escenario, el runner deja `route_plan/` con el plan de ruta y sus imágenes (cap. 4 IT.4.3.1), y `batch_runner.py` agrega en la raíz `RESULTS_SUMMARY.json` (una fila por corrida) y `RESULTS_SUMMARY.batch_version.txt`.

**Traza por ciclo (`.jsonl`).** Cada línea es un ciclo del lazo y tiene estos campos:

| Campo | Contenido |
|---|---|
| `t`, `cycle` | Segundos desde el inicio de la corrida y número de ciclo |
| `arm`, `scenario`, `seed` | Celda de la corrida |
| `pos`, `vel`, `yaw_deg`, `pitch_deg`, `roll_deg` | Posición NED, velocidad (`vx`, `vy`, `vz`) y actitud |
| `route`, `action` | Ruta que decidió el ciclo y macro-acción emitida (cap. 5 IT.5.3) |
| `obstacle_field` | `ObstacleField` completo: por sector, ocupación, TTC, confianza y bloqueo; fuente (`flow`, `holdover`, `degraded`) y confianza del FOE (cap. 6) |
| `latency_ms` | Duración del ciclo del grafo (`graph`) y de la lectura de telemetría (`telemetry`) |
| `slm` | Presente en los ciclos con una consulta del lazo lento: identificador, latencia, *fallback*, *timeout*, adherencia al esquema, prompt (vacío con la profundidad), respuesta cruda (con la profundidad, el p5 estimado por sector en metros) y rutas de los fotogramas (`frame_paths`) |
| `collision` | Colisión y objeto contra el que ocurrió |
| `wp_index`, `dist_to_wp_m` | Objetivo activo y distancia horizontal a él |
| `degraded` | AirSim no respondió en el ciclo (cap. 5 IT.5.4) |
| `deadlock_event` | Solo en el ciclo en que un deadlock se resuelve o cae al escape: estrategia, si lo resolvió el barrido, ciclos que llevó, si cayó al escape vertical, la macro, la respuesta cruda y la selección del rumbo de salida (`scan_selection`: candidatos, descartados con su motivo, rumbo que falló, modo y rumbo elegido; cap. 5 IT.5.6) |
| `perception` | Señales del `StallDetector` (contacto por IMU, avance sin movimiento, nivel de vibración, ciclos detenido) |
| `state` | El `DroneState` completo del ciclo |
| `min_obstacle_dist_m` | Siempre vacío: la distancia mínima la mide la auditoría aparte (`.distmin.ndjson`) |

El campo `state` hace que la traza no dependa de haber previsto qué registrar: guarda todas las claves del estado (cap. 5 IT.5.2) con reglas fijas (`state_serializer.py`). Las imágenes y los búferes de fotogramas se reemplazan por su forma (`<ndarray shape=(720, 1080, 3)>`); `deliberations` se resume en su cantidad y la última entrada, sin prompts (que ya están en el bloque `slm`); los textos se cortan a 600 caracteres, las listas a 40 elementos y el anidamiento a 6 niveles, y los valores no finitos se escriben como texto (`"inf"`, `"nan"`) para que cada línea sea JSON válido. La serialización nunca detiene el vuelo: si falla, el ciclo registra el error en lugar del estado.

**Traza plana (`.csv`).** Durante el vuelo se escribe en *streaming* con un conjunto fijo de columnas, que sirve de respaldo si el proceso muere: identificación (`t`, `cycle`, `arm`, `scenario`, `seed`, `route`, `action`, `wp_index`, `dist_to_wp_m`, `degraded`), cinemática (`pos_*`, `vel_*`, actitud), colisión, latencias, la consulta del ciclo (`slm_invoked`, `slm_latency_ms`, `slm_fallback`, `slm_timeout`, `slm_adherent`, `slm_prompt`, `slm_raw_response`, `slm_delib_id`, `slm_frame_paths`), estado de control (`ctrl_*`: contador de atasco, maniobra comprometida y ciclos restantes, señales del `StallDetector`, ciclos sin progreso) y el campo de obstáculos por sector (`field_<sector>_occ`, `_ttc_s`, `_conf`, `_blocked`, `field_source`). Algunas columnas `ctrl_*` (`ctrl_depth_m`, `ctrl_traj_*`, `ctrl_stuck_invisible`) quedan siempre vacías: el grafo no las llena, pero forman parte del esquema fijo de columnas que esperan las herramientas de análisis. Al cerrar la corrida, el CSV se reescribe agregando el `DroneState` aplanado: una columna `state.<ruta>` por cada valor escalar del árbol (por ejemplo `state._vlm_strategic.outcome`). El prompt y la respuesta completos están en el CSV, y no solo en el JSONL, para poder analizar las consultas sin cruzar archivos.

**Resumen de corrida (`.summary.json`).** Lo consumen `analyze_lotes.py` (cap. 10 IT.10.7), `analyze.py`, `analyze_tesis_results.py` y `analyze_strategic_batch.py`. Campos:

- **Identificación:** `scenario`, `seed`, `arm`, `code_version` (hash del commit, con sufijo `-dirty` si había cambios sin confirmar; Anexo 12, IT.A12.9.3), `deadlock_strategy`, `strategic_source` y `route_plan` (modo y plan con el que voló).
- **Misión:** `success`, `cycles`, `duration_s`, `path_length_m` y, cuando corresponde, `termination_reason` (por ejemplo `physics_locked`) y `freeze_recoveries`.
- **Seguridad:** `collisions` y DistMin (`min_obstacle_dist_m`, con `min_obstacle_dist_t`, `min_obstacle_dist_source` y `min_obstacle_dist_samples`).
- **Lazo lento:** `slm_invocations` (consultas nuevas, contadas una vez por identificador), `deliberation_rate`, `slm_fallback_rate`, `slm_timeout_rate`.
- **Rutas:** `route_histogram`, ciclos por ruta.
- **Atascos:** `deadlock_events`, `deep_scan_events`, `deep_scan_resolution_rate`, `deep_scan_avg_cycles_to_resolve`, `deep_scan_fallback_rate`, `deep_scan_futile_rate`, `vertical_escapes`.

**Resumen por objetivo (`.summary_by_wp.csv`).** Columnas `wp_index`, `wp_label`, `cycles`, `duration_s`, `deliberative_cycles`, `deliberative_rate` y `deep_scan_events`. El índice cuenta los objetivos tal como los recorrió el tracker, incluidas las sub-metas insertadas, y la etiqueta es la del waypoint de misión al que pertenecen: varias filas pueden tener la misma etiqueta. Sirve para ver en qué tramo se concentra la dificultad sin abrir la traza.

**Auditoría de DistMin (`.distmin.ndjson`).** Una línea por muestra, cada `DISTMIN_TRACK_PERIOD_S` (1 s): `t` (hora epoch), `dist_m` (percentil 5 del tercio central de la profundidad de la cámara frontal) y la posición `x`, `y`, `z` en el instante de la muestra. La escribe un hilo aislado, con su propia conexión al simulador, que no comparte nada con el grafo (cap. 5 IT.5.8); `finalize_run` consolida el mínimo en el resumen. Como cada muestra lleva su posición, se puede calcular DistMin por tramo; su `t` es hora epoch, distinta del `t` relativo de la traza.

**Fotogramas (`photo-<ISO>.png`).** Cada consulta del lazo lento guarda el fotograma crudo que le dio origen, a resolución completa (no la versión reducida que viaja en el pedido), nombrado con su hora de captura en UTC con milisegundos; un barrido guarda sus cuatro imágenes. La columna `slm_frame_paths` de la traza enlaza cada consulta con sus archivos. Con la capa estratégica de profundidad hay del orden de un fotograma por segundo de vuelo.

**Cierre y reparación (`finalize_run`).** Es el último paso de toda corrida del runner y es idempotente: consolida DistMin en el resumen y, si el proceso murió antes de cerrar, reconstruye el CSV con las columnas `state.*` a partir del JSONL (que se vacía a disco ciclo a ciclo), repara el índice de los videos y regenera el visor. Una corrida interrumpida se cierra a mano con `python experiments/finalize_run.py <carpeta>` (o `--all <raíz>` para todas las incompletas).

---

## A13.4 Visor de auditoría (`.viewer.html`)

NB2 es su equivalente en Python: abre una corrida de la v4, recalcula desde el registro por ciclo las métricas del `summary.json` y grafica la traza de decisión, el `ObstacleField`, la capa estratégica y la trayectoria sobre el mapa.

<img src="../2026-1028 visor_auditoria.png"/>

*Visor de una corrida `slm:depth` de `townsim_ini` (corrida v4, lote 3, semilla 89) en el ciclo 398: un muro cubre el campo, el lazo rápido gira 90° y adelanta la consulta estratégica #40.*

El visor es un único archivo HTML que se genera al cerrar cada corrida. Lleva la traza embebida como JSON dentro de la página, de modo que se abre con doble clic, sin servidor: un navegador bloquea, desde `file://`, la lectura de otro archivo local con `fetch`, pero sí reproduce un video de la misma carpeta. Tiene cuatro partes:

1. **Videos sincronizados.** El video frontal (lo que ve el grafo) y, si existe, el de la cámara externa `FollowCam`, uno al lado del otro. El externo sigue al frontal en reproducción, pausa, velocidad y saltos. Los dos tienen un cuadro por ciclo, de modo que la correspondencia entre video y traza es por número de ciclo y no por tiempo: el período real del lazo varía y el tiempo derivaría.
2. **Barra de ciclos.** Un control deslizante sobre todos los ciclos, sincronizado en ambos sentidos con el video, con el ciclo y el tiempo actuales.
3. **Panel de detalle del ciclo.** Todas las columnas del CSV del ciclo; los tres sectores del `ObstacleField` como recuadros (ocupación, TTC, confianza, resaltados si están bloqueados); el prompt y la respuesta cruda si en ese ciclo llegó una consulta; las imágenes exactas de esa consulta, y el `DroneState` completo como árbol desplegable.
4. **Tabla de ciclos.** Una fila por ciclo con ciclo, tiempo, ruta, acción, objetivo, distancia, TTC y bloqueo del sector central, colisión e identificador de consulta. La fila actual se resalta y se centra al avanzar el video; un clic en una fila lleva el video a ese ciclo.

El uso típico es partir de un evento del resumen —un deadlock, una colisión, la muestra de DistMin más baja— y llevar el visor a ese ciclo: el video muestra la escena, el panel muestra qué percibió el sistema y qué decidió, y el árbol del estado muestra por qué (contadores de atasco, sub-meta activa, resultado de la capa estratégica). Así se auditaron los modos de falla del capítulo 9.

### A13.4.1 Anotaciones del video

El video (`.webm`) registra un fotograma por ciclo del lazo, a la misma cadencia de `LOOP_HZ`. Cada fotograma lleva un overlay de cuatro líneas superpuesto **sobre una copia del fotograma**; el original, que usan la percepción y la capa estratégica y que se guarda como `.png` de auditoría, queda sin modificar para no contaminar la evidencia perceptual.

**Línea 1 — ruta activa y macro-acción** (texto grande, color codificado):

```
[KEEP_GOING] ACT: MANTENER_RUMBO  WP 3/7 (42m)
```

- El tag entre corchetes es la **ruta** (`route`) del comportamiento que resolvió el ciclo (cap. 5 IT.5.3): `REACTIVE` (crucero sin novedad, vuelo bajo el piso óptico o descenso bajo un techo), `EVASIVE` (evasión reactiva o continuación de una maniobra comprometida), `GIRAR_90` (giro ante un frente bloqueado), `DELIBERATIVE` (barrido de resolución de atasco en curso o resuelto), `TACTICAL` (escape vertical cuando el barrido no resolvió o con `blind`), `FSM` (brazo FSM) o `DEGRADED` (modo degradado, cap. 5 IT.5.4).
- `ACT:` es la **macro-acción** traducida a comando cinemático por el nodo `motor`.
- `WP X/N (Ym)` indica el objetivo activo y la distancia restante según `WaypointTracker` (cap. 5 IT.5.4). `N` cuenta también las sub-metas insertadas en vuelo, de modo que crece durante la misión.
- **Color:** verde para `MANTENER_RUMBO`, naranja para maniobras de evasión, giro o escape vertical, rosa para `FRENAR`.

**Línea 2 — TTC frontal y estado de vuelo** (derecha del fotograma):

```
TTC: 3.2s | vuelo
```

- `TTC` es el tiempo estimado a colisión del sector frontal según el `ObstacleField` del ciclo (cap. 6); `inf` significa sector despejado.
- El campo de texto refleja el estado general de la misión (`vuelo`, `completada`, `colisión`).

**Línea 3 — telemetría del ciclo:**

```
t= 18.4s cy=92 | pos=(+26.1,-78.2,-10.0) | v=2.31m/s pitch=-3.2deg roll=+0.8deg
```

- `t` y `cy` permiten cruzar el fotograma con la fila exacta del CSV por número de ciclo (la sincronización por tiempo es aproximada, la de ciclo es exacta; ver `flight_video.py`).
- `pos` es la posición 3D en el marco NED del simulador; si el guiado detectó un techo (IT.A10.8.3), se agrega `ceil=<cota>` a continuación.
- `v`, `pitch`, `roll` son la velocidad horizontal y la actitud del vehículo en ese instante.

**Línea 4 — estado del ObstacleField por sector** (cap. 6):

```
C occ=0.62 ttc=3.2s! | I occ=0.11 ttc=inf | D occ=0.08 ttc=inf
```

- Los tres sectores son `C` (centro / frente), `I` (izquierda) y `D` (derecha).
- `occ` es la fracción de ocupación estimada por flujo óptico monocular; `ttc` es el tiempo a colisión estimado del sector; `!` marca el sector como bloqueado según el umbral de `is_blocked()`.
- Estos valores son los mismos que usa el lazo rápido de `navigate` (cap. 5 IT.5.3): el overlay permite ver, ciclo a ciclo, qué evidencia perceptual motivó la decisión visible en la línea 1. La capa estratégica no los recibe: mira el fotograma directamente (cap. 5 IT.5.5).

La combinación de estas cuatro líneas permite reconstruir, para cualquier instante del vuelo, exactamente qué percibió el sistema, por qué se activó el comportamiento que aparece en el tag, y qué orden cinemática emitió — sin necesidad de cruzar a mano el video con el CSV.
