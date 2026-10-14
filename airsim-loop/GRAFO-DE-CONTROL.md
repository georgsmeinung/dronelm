# Grafo de control

> Estado del lazo de `airsim-loop` al **2026-10-14**. Describe la configuracion **tal como esta en el codigo** ([`src/agents/graph.py`](src/agents/graph.py)) y en [`config/.env`](../config/.env): `STRATEGIC_SOURCE=depth`, `DEADLOCK_STRATEGY=depth`, `ROUTE_PLAN_MODE=vlm`. La version anterior de este documento (policy_router de 5 ramas, nodo deliberativo, `slam_assess`) corresponde a codigo hoy congelado en [`src/agents/legacy/`](src/agents/legacy/). Version extendida: informe, cap. 5 (arquitectura), cap. 6 §6.14 (profundidad estimada) y cap. 4 §4.4 (registro de corrida y visor).

---

## 1. Principios

1. **Dos lazos desacoplados.** El lazo rapido (5 Hz: guiado + evasion por flujo optico) es el unico que comanda velocidades. El lazo lento corre asincrono, en su propio hilo, y solo propone **sub-metas en coordenadas del mundo**.
2. **La fuente del lazo lento es configurable** (`STRATEGIC_SOURCE`): profundidad monocular **estimada** desde el RGB (`depth`, default), VLM (`vlm`, ablacion) u `off`. Las dos fuentes devuelven la misma estructura, de modo que ancla, sub-meta y validaciones son las mismas.
3. **Lo que la fuente dice es valido cuando llega.** Cada pedido guarda la pose del frame (ancla) y la respuesta se traduce con esa pose, no con la actual. Rumbo absoluto, no "izquierda/derecha" del cuerpo.
4. **La fuente decide, las reglas no la reescriben.** No hay overrides deterministas sobre su respuesta. El fallback determinista existe solo ante **falla** (timeout, formato, rotacion imposible, barrido sin rumbo transitable).
5. **Sin profundidad del simulador.** Ni el grafo, ni `main.py`, ni `experiments/runner.py` leen el sensor de profundidad de AirSim. La red de profundidad estimada recibe el mismo RGB que el flujo optico. Unica lectura del sensor: el hilo aislado de auditoria de DistMin ([`distmin_audit.py`](src/logging/distmin_audit.py)). Guardia: [`tests/test_no_depth_in_flight_path.py`](tests/test_no_depth_in_flight_path.py).
6. **El VLM no corre en vuelo** con la configuracion final: en el banco a bordo no separo sectores libres de bloqueados (AUC 0.53) ni rumbos del barrido (todo transitable); la profundidad estimada si (AUC 0.83-0.87). El VLM (`lfm2.5-vl-1.6b:q4km-ctx8k`, Ollama local, misma GPU) queda en el plan de ruta previo al vuelo ([`route_planner.py`](src/planning/route_planner.py), juicio por parches, AUC 0.81).

## 2. Topologia

```
capture -> (degradado?) -> perception -> navigate -> motor -> END
                 \-> degraded_hover ----------------/
```

| Nodo | Que hace |
|---|---|
| `capture` | RGB + telemetria. Si AirSim no responde: `degraded=True`. |
| `degraded_hover` | `FRENAR`: sin datos no se mueve. |
| `perception` | `FlowTTCEstimator` -> `ObstacleField` (flujo optico a 640 px, FOE, TTC). Unica fuente de percepcion del lazo rapido. |
| `navigate` | Brazo `reactive` / `fsm` / `slm` (ver §3). |
| `motor` | Ancla de altitud en `FRENAR`, gobernador de velocidad, `execute_velocity` no bloqueante. |

Servicios (un hilo cada uno, creados solo si alguna capa los usa): profundidad (`make_depth_service`, si `STRATEGIC_SOURCE=depth` o `DEADLOCK_STRATEGY=depth`) y VLM (`make_deliberation_service`, si `vlm` o `deep_vlm`). Con depth/depth no se crea el del VLM.

## 3. `navigate_node` (brazo `slm`) — cascada de 8 reglas

Antes de la cascada, cada ciclo: `StallDetector.update()` y `StrategicLayer.tick()` (capa estrategica, no bloqueante; no existe con `STRATEGIC_SOURCE=off`). Durante el **despegue vertical** (`guidance.takeoff`, hasta 1 m de la altitud del primer objetivo) los tres brazos usan `reactive_node`: sube en el lugar, sin evasion por flujo ni conteo de atasco.

La velocidad de "detenido" se mide por desplazamiento entre ciclos (AirSim reporta la comandada con el dron apoyado en una malla), y la deteccion de techo usa el comando ejecutado (`note_executed_command`), no la demanda del guiado.

| # | Condicion | Accion | Por que |
|---|---|---|---|
| 1 | Barrido panoramico en curso | seguir el barrido | Es duenio del dron hasta resolver o caer por sus watchdogs. |
| 2 | Trabado (>=10 ciclos con orden de avanzar y sin desplazamiento medido) o ~10 s sin acercarse 2 m al objetivo | **deadlock** (§5) | Precede a todo salvo el barrido: una accion que se repite sin mover al dron (maniobra, evasion, descenso por techo) no puede taparlo (piloto v3 seed 99: 220 ciclos de PERDER_ALTURA sin deadlock). |
| 3 | Maniobra comprometida | continuarla | Anti flip-flop. |
| 4 | Contacto IMU o avance ordenado sin movimiento (2 ciclos) | `evasive_node` | Obstaculo que el flujo no ve. |
| 5 | Bajo el piso optico (4.5 m) sin techo | `reactive_node` | Aterrizaje/vuelo bajo: el flujo no es valido. |
| 6 | WP bajo un techo detectado | `PERDER_ALTURA` | z como dimension de navegacion. |
| 7 | TTC frontal critico | FOV >60% bloqueado: `GIRAR_90` hacia el WP **y** consulta inmediata a la capa estrategica con ese frame; si no: `evasive_node` | El lazo rapido esquiva; el rodeo lo decide el lazo lento. |
| 8 | — | `reactive_node` | Guiado nominal. |

Brazos de comparacion: `reactive` = solo `reactive_node`; `fsm` = [`fsm.py`](src/agents/fsm.py) (comparte el barrido de §5 si `DEADLOCK_STRATEGY` es `depth` o `deep_vlm`; con `blind`, su propia alternancia CLIMB/DESCEND).

## 4. Capa estrategica ([`vlm_strategic.py`](src/agents/vlm_strategic.py))

- **Cuando:** cada >=`DEPTH_STRATEGIC_PERIOD_S` (1 s) con la profundidad, >=`VLM_STRATEGIC_PERIOD_S` (3 s) con el VLM; a >=8 m de altura, con el WP real a >`VLM_NEAR_WP_M` (8 m) y la meta dentro del recorte cuadrado (+-33.7 deg). Tambien con una sub-meta activa (re-planificacion: la pregunta es siempre sobre el WP real). De inmediato si la regla 7 ve un muro. Con la meta fuera de cuadro solo si el dron lleva >=15 ciclos sin acercarse (`VLM_STUCK_QUERY_CYCLES`): entonces no hay sector de la meta y nunca es `directo_libre`.
- **Que se juzga:** un recorte cuadrado del centro del frame (se cortan ambos costados del ancho) con una grilla de 3x3 por tercios (columnas A-C, filas 1 arriba / 2 altura del dron / 3 abajo); laterales y verticales a la misma distancia angular (+-24 deg). Cada sector tiene una **direccion absoluta** fijada con la pose del frame.
- **Fuente `depth`** ([`depth_client.py`](src/agents/depth_client.py), [`depth_estimator.py`](src/perception/depth_estimator.py)): Depth Anything V2 Metric Outdoor Small (~25 M parametros, metros) sobre el frame crudo; un sector es `libre` si el percentil 5 de su profundidad es >= `DEPTH_FREE_M` (15 m). ~110 ms por consulta en vuelo, ~440 MiB de VRAM, precarga al crear el grafo. Respuesta cruda en la auditoria: el p5 por sector en metros.
- **Fuente `vlm`** (ablacion): la misma grilla dibujada con una marca roja "GOAL"; el modelo responde `free`/`blocked` por sector con decodificacion restringida (`json_schema`). Tope de tokens 384/512; una respuesta cortada (`finish_reason=length`) es `respuesta_truncada`, no se interpreta.
- **Como se usa:** si el sector de la meta esta libre, nada (y si habia una sub-meta pendiente se descarta: `_clear_subgoals`). Si no, sub-meta en la direccion del sector libre mas cercano a la meta (a menos de 10 deg de diferencia, fila del medio, despues arriba, despues abajo), a `min(15 m, distancia al WP real)` desde el ancla, con dz = d*tan(elevacion) acotado a +-4 m y altitud >= 6 m. Se descarta si paso >10 s, cambio el WP o el dron ya la supero.
- **Auditoria:** `deliberations[]` con `arm={fuente}_strategic` (`depth_strategic` o `vlm_strategic`), frame en `photo-*.png`, ultimo resultado en `_vlm_strategic`.

## 5. Deadlock ([`deep_scan.py`](src/agents/deep_scan.py))

- **Barrido (`depth`, default; `deep_vlm`, ablacion):** gira a `SCAN_HEADING_COUNT_DEEP`=4 rumbos, toma el frame de cada uno con su yaw **medido** y hace una sola consulta. Con `depth`, un rumbo es transitable si el p5 del sector central `B2` es >= 15 m (en el banco: AUC 0.87); con `deep_vlm`, el modelo describe cada imagen numerada (`free:true` **y** vista `open`). Entre los transitables se descartan los que caen a <45 deg del rumbo que fallo (hacia el objetivo activo al iniciar el barrido) o de un rumbo ya probado en un deadlock a <10 m (mismo WP); sin historia, el mas cercano a la meta; con historia, el mas distinto de lo ya probado. Sub-meta con la misma funcion que la capa estrategica (`subgoal.build_subgoal`), a la altitud actual. Si no queda ninguno: `GANAR_ALTURA` (con el VLM, `PERDER_ALTURA` si todo es vegetacion). Seleccion completa en `_deadlock_event.scan_selection`, historia en `_deadlock_history`. A <8 m del WP real no se barre.
- **`blind`, o el barrido falla:** `GANAR_ALTURA` (por encima de `MAX_ESCAPE_ALT_M`: `GIRAR_90`). En las corridas fue la unica maniobra que libero al dron de una estructura; `RETROCEDER` tuvo avance mediano negativo y se elimino.
- **En vuelo** (lote TownSim de octubre): el barrido con profundidad resolvio 19 de 30 deadlocks; los no resueltos salieron por el escape vertical, sin abortos.

## 6. Sub-metas y tracker ([`waypoint_tracker.py`](src/navigation/waypoint_tracker.py))

Toda sub-meta viene del lazo lento (capa estrategica o barrido) y se inserta tal cual delante del WP activo, reemplazando la pendiente (salvo un duplicado a <10 m). El WP real se acepta aunque haya una sub-meta activa (descarta los desvios): en el piloto v3 190842Z el dron estuvo 573 ciclos a <3.5 m de WP_0_SUR sin aceptarlo. No hay esquinas deterministas, contactos, reflejos, compromiso ni cadena: 74 esquinas deterministas dieron una mediana de 0.35 m de avance hacia el WP real en 20 s.

## 7. Que se elimino y por que (evidencia: 12 corridas `citysim_pilot`, grafo v2; banco y lotes de octubre)

| Componente | Evidencia |
|---|---|
| Consulta tactica por sector + default `EVADIR_DERECHA` | 52/53 respuestas "frente libre"; el contenido se ignoraba. |
| Fix M/L/L2/11/12/14/17, overrides 1a/1b/1c/2/3 | Reescribian al VLM; deadlocks resueltos sin avance. Movidos a `legacy/deep_scan_v2.py`. |
| `RETROCEDER` automatico (evasivo, depth-brake, fallback) | Avance mediano negativo; retrocede >2 m en 31-43%. |
| `FlightTrajectory` (C1, D1, `traj_stall`, fallback) | 45 deadlocks disparados solo por esta senal, sin avance posterior. `legacy/spatial_history_v2.py`. |
| Contador del tracker / eventos de "frentes bloqueados" / `stuck_invisible` / `pos_freeze` como disparadores | Solapados con las dos senales de la regla 2. |
| Escape vertical forzado, deteccion de escaneo huerfano | Overrides / reemplazados por la regla 1. |
| Profundidad monocular como freno del lazo rapido, aviso G1 | Desactivada en todas las corridas / solo alimentaba prompts legacy. La profundidad estimada volvio en otro rol: fuente del lazo lento (§4), con el p5 por sector validado en el banco. |
| Nodo deliberativo legacy, `slam_assess` | Factorial 09-07..09-10: el brazo slm nunca supero al reactivo; slam_assess sin evidencia (5 corridas truncadas). |
| VLM en vuelo (capa estrategica y barrido) | Banco a bordo: grilla AUC 0.53, barrido "todo transitable" 14/14; lote CitySim: equivalente a no tener capa. Queda como ablacion (`vlm`, `deep_vlm`). |

**Conservado sin evidencia a favor ni en contra** (son parte del lazo rapido compartido por todos los brazos): evasion por flujo, `GIRAR_90`, contacto IMU / muro ciego, gobernador de velocidad, deteccion de techo, histeresis y suavizado del guiado.

## 8. Tests

```bash
python -m pytest tests -q
```

299 tests. Los que cubren la frontera del grafo corren el **grafo compilado**: [`test_graph_integration.py`](tests/test_graph_integration.py) (atasco real -> barrido -> sub-meta), [`test_vlm_strategic_graph.py`](tests/test_vlm_strategic_graph.py) (servicios segun fuente y estrategia, incluido depth sin servicio del VLM), [`test_deep_vlm_world_frame.py`](tests/test_deep_vlm_world_frame.py) (regresion del marco de referencia), [`test_takeoff_no_false_deadlock.py`](tests/test_takeoff_no_false_deadlock.py). La fuente de profundidad: [`test_depth_strategic.py`](tests/test_depth_strategic.py) (geometria de sectores, forma de las respuestas, umbral; los tests no cargan la red). La guardia de profundidad: [`test_no_depth_in_flight_path.py`](tests/test_no_depth_in_flight_path.py); la auditoria de DistMin: [`test_distmin_audit.py`](tests/test_distmin_audit.py).
