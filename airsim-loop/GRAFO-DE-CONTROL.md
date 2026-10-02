# Grafo de control

> Estado del lazo de `airsim-loop` al **2026-09-30**, despues de la simplificacion por evidencia. Describe la configuracion **tal como esta en el codigo** ([`src/agents/graph.py`](src/agents/graph.py)). La version anterior de este documento (policy_router de 5 ramas, nodo deliberativo, `slam_assess`) corresponde a codigo hoy congelado en [`src/agents/legacy/`](src/agents/legacy/).

---

## 1. Principios

1. **Dos lazos desacoplados.** El lazo rapido (5 Hz: guiado + evasion por flujo optico) es el unico que comanda velocidades. El VLM corre en un lazo lento, asincrono, y solo propone **sub-metas en coordenadas del mundo**.
2. **Lo que el VLM dice es valido cuando llega.** La inferencia tarda 3-6 s; cada pedido guarda la pose del frame (ancla) y la respuesta se traduce con esa pose, no con la actual. Rumbo absoluto, no "izquierda/derecha" del cuerpo.
3. **El VLM decide, las reglas no lo reescriben.** No hay overrides deterministas sobre su respuesta. El fallback determinista existe solo ante **falla** del modelo (timeout, formato, rotacion imposible).
4. **Sin profundidad del simulador.** Ni el grafo, ni `main.py`, ni `experiments/runner.py` leen el sensor de profundidad. Guardia: [`tests/test_no_depth_in_flight_path.py`](tests/test_no_depth_in_flight_path.py).

## 2. Topologia

```
capture -> (degradado?) -> perception -> navigate -> motor -> END
                 \-> degraded_hover ----------------/
```

| Nodo | Que hace |
|---|---|
| `capture` | RGB + telemetria. Si AirSim no responde: `degraded=True`. |
| `degraded_hover` | `FRENAR`: sin datos no se mueve. |
| `perception` | `FlowTTCEstimator` -> `ObstacleField` (flujo optico, FOE, TTC). Unica fuente de percepcion del lazo rapido. |
| `navigate` | Brazo `reactive` / `fsm` / `slm` (ver §3). |
| `motor` | Ancla de altitud en `FRENAR`, gobernador de velocidad, `execute_velocity` no bloqueante. |

## 3. `navigate_node` (brazo `slm`) — cascada de 8 reglas

Antes de la cascada, cada ciclo: `StallDetector.update()` y `StrategicLayer.tick()` (VLM estrategico, no bloqueante). Durante el **despegue vertical** (`guidance.takeoff`, hasta 1 m de la altitud del primer objetivo) los tres brazos usan `reactive_node`: sube en el lugar, sin evasion por flujo ni conteo de atasco.

La velocidad de "detenido" se mide por desplazamiento entre ciclos (AirSim reporta la comandada con el dron apoyado en una malla), y la deteccion de techo usa el comando ejecutado (`note_executed_command`), no la demanda del guiado.

| # | Condicion | Accion | Por que |
|---|---|---|---|
| 1 | Barrido panoramico en curso | seguir el barrido | Es duenio del dron hasta resolver o caer por sus watchdogs (reemplaza la deteccion de escaneo "huerfano", 71 descartes en las corridas v2). |
| 2 | Trabado (>=10 ciclos con orden de avanzar y sin desplazamiento medido) o ~10 s sin acercarse 2 m al objetivo | **deadlock** (§5) | Precede a todo salvo el barrido: una accion que se repite sin mover al dron (maniobra, evasion, descenso por techo) no puede taparlo (piloto v3 seed 99: 220 ciclos de PERDER_ALTURA sin deadlock). |
| 3 | Maniobra comprometida | continuarla | Anti flip-flop. |
| 4 | Contacto IMU o avance ordenado sin movimiento (2 ciclos) | `evasive_node` | Obstaculo que el flujo no ve. |
| 5 | Bajo el piso optico (4.5 m) sin techo | `reactive_node` | Aterrizaje/vuelo bajo: el flujo no es valido. |
| 6 | WP bajo un techo detectado | `PERDER_ALTURA` | z como dimension de navegacion. |
| 7 | TTC frontal critico | FOV >60% bloqueado: `GIRAR_90` hacia el WP **y** consulta inmediata al VLM con ese frame; si no: `evasive_node` | El lazo rapido esquiva; el rodeo lo decide el VLM. |
| 8 | — | `reactive_node` | Guiado nominal. |

Brazos de comparacion: `reactive` = solo `reactive_node`; `fsm` = [`fsm.py`](src/agents/fsm.py) (comparte el barrido de §5 si `DEADLOCK_STRATEGY=deep_vlm`).

## 4. Capa estrategica del VLM ([`vlm_strategic.py`](src/agents/vlm_strategic.py))

- **Cuando:** cada >=`VLM_STRATEGIC_PERIOD_S` (3 s), a >=8 m de altura, con el WP real a >`VLM_NEAR_WP_M` (8 m) y la meta dentro de +-40 deg del eje optico. Tambien con una sub-meta activa (re-planificacion: la pregunta es siempre sobre el WP real). De inmediato si la regla 7 ve un muro. Con la meta fuera de cuadro solo si el dron lleva >=15 ciclos sin acercarse (`VLM_STUCK_QUERY_CYCLES`): entonces no hay sector de la meta y nunca es `directo_libre`. Tope de tokens 384/512; una respuesta cortada (`finish_reason=length`) es `respuesta_truncada`, no se interpreta.
- **Que ve:** un recorte cuadrado del centro del frame (se cortan ambos costados del ancho; ~67 deg de campo) con una grilla de 3x3 por tercios; laterales y verticales a la misma distancia angular (+-24 deg), a igualdad gana la fila del medio (columnas A-C, filas 1 arriba / 2 altura del dron / 3 abajo) y una marca roja "META" en la direccion (azimut y elevacion) del destino. Cada sector tiene una **direccion absoluta** fijada con la pose del frame.
- **Que responde:** cada sector `libre`/`bloqueado` (volar 15 m en esa direccion).
- **Como se usa:** si el sector de la meta esta libre, nada (y si habia una sub-meta pendiente se descarta: `_clear_subgoals`). Si no, sub-meta en la direccion del sector libre mas cercano a la meta, a `min(15 m, distancia al WP real)` desde el ancla, con dz = d*tan(elevacion) acotado a +-4 m y altitud >= 6 m. Se descarta si paso >10 s, cambio el WP o el dron ya la supero.
- **Auditoria:** `deliberations[]` con `arm=vlm_strategic`, frame en `photo-*.png`, ultimo resultado en `_vlm_strategic`.

## 5. Deadlock

- **`deep_vlm` (default):** sub-meta con la misma funcion que la capa estrategica (`subgoal.build_subgoal`), a la altitud actual. Barrido de `SCAN_HEADING_COUNT_DEEP`=4 rumbos, una consulta con las imagenes numeradas. El modelo describe cada imagen; el codigo conoce el rumbo medido de cada una y fija una sub-meta sobre la transitable (`ok:true` **y** tipo `libre`) elegida asi: se descartan las que caen a <45 deg del rumbo que fallo (hacia el objetivo activo al iniciar el barrido) o de un rumbo ya probado en un deadlock a <10 m (mismo WP); sin historia, la mas cercana a la meta; con historia, la mas distinta de lo ya probado; si no queda ninguna, `GANAR_ALTURA`. Seleccion completa en `_deadlock_event.scan_selection`, historia en `_deadlock_history` ([`deep_scan.py`](src/agents/deep_scan.py)). `degradada` se registra, no decide (true en 19/19 respuestas de los pilotos). A <8 m del WP real no se barre. Si ninguna es transitable: `GANAR_ALTURA` (o `PERDER_ALTURA` si todo es vegetacion).
- **`blind`, o el VLM falla:** `GANAR_ALTURA` (por encima de `MAX_ESCAPE_ALT_M`: `GIRAR_90`). En las corridas fue la unica maniobra que libero al dron de una estructura; `RETROCEDER` tuvo avance mediano negativo y se elimino.

## 6. Sub-metas y tracker ([`waypoint_tracker.py`](src/navigation/waypoint_tracker.py))

Toda sub-meta viene del VLM y se inserta tal cual delante del WP activo, reemplazando la pendiente (salvo un duplicado a <10 m). El WP real se acepta aunque haya una sub-meta activa (descarta los desvios): en el piloto v3 190842Z el dron estuvo 573 ciclos a <3.5 m de WP_0_SUR sin aceptarlo. No hay esquinas deterministas, contactos, reflejos, compromiso ni cadena: 74 esquinas deterministas dieron una mediana de 0.35 m de avance hacia el WP real en 20 s.

## 7. Que se elimino y por que (evidencia: 12 corridas `citysim_pilot`, grafo v2)

| Componente | Evidencia |
|---|---|
| Consulta tactica por sector + default `EVADIR_DERECHA` | 52/53 respuestas "frente libre"; el contenido se ignoraba. |
| Fix M/L/L2/11/12/14/17, overrides 1a/1b/1c/2/3 | Reescribian al VLM; deadlocks resueltos sin avance. Movidos a `legacy/deep_scan_v2.py`. |
| `RETROCEDER` automatico (evasivo, depth-brake, fallback) | Avance mediano negativo; retrocede >2 m en 31-43%. |
| `FlightTrajectory` (C1, D1, `traj_stall`, fallback) | 45 deadlocks disparados solo por esta senal, sin avance posterior. `legacy/spatial_history_v2.py`. |
| Contador del tracker / eventos de "frentes bloqueados" / `stuck_invisible` / `pos_freeze` como disparadores | Solapados con las dos senales de la regla 6. |
| Escape vertical forzado, deteccion de escaneo huerfano | Overrides / reemplazados por la regla 1. |
| Profundidad monocular, aviso G1 | Desactivada en todas las corridas / solo alimentaba prompts legacy. |
| Nodo deliberativo legacy, `slam_assess` | Factorial 09-07..09-10: el brazo slm nunca supero al reactivo; slam_assess sin evidencia (5 corridas truncadas). |

**Conservado sin evidencia a favor ni en contra** (son parte del lazo rapido compartido por todos los brazos): evasion por flujo, `GIRAR_90`, contacto IMU / muro ciego, gobernador de velocidad, deteccion de techo, histeresis y suavizado del guiado.

## 8. Tests

```bash
python -m pytest tests -q
```

Los que cubren la frontera del grafo corren el **grafo compilado**: [`test_graph_integration.py`](tests/test_graph_integration.py) (atasco real -> barrido -> sub-meta), [`test_vlm_strategic_graph.py`](tests/test_vlm_strategic_graph.py), [`test_deep_vlm_world_frame.py`](tests/test_deep_vlm_world_frame.py) (regresion del marco de referencia), [`test_takeoff_no_false_deadlock.py`](tests/test_takeoff_no_false_deadlock.py).
