# Mapeo de Código a Grafo de Loop de Control Autónomo Jerárquico

Este submódulo (`airsim-loop`) implementa el bucle de control reactivo/deliberativo de navegación autónoma para drones cuadricópteros usando **LangGraph**, estimación de **TTC (Time-To-Collision) por flujo óptico** con derotación y estimación del FOE, y un **SLM/VLM Local** (Small/Vision Language Model) que corre de forma asíncrona respecto del lazo de control.

> **Nota de arquitectura (2026-08):** este README fue reescrito para reflejar el estado real del código tras la implementación de `PLAN-MEJORAS.md`. La versión anterior describía YOLO + ROI 62° + IoU/area_ratio, que fueron retirados (ver [`legacy/README.md`](legacy/README.md) para la justificación medida de cada retiro) y reemplazados por el contrato único de percepción `ObstacleField`.

## Arquitectura del Bucle de Control Jerárquico

El pipeline sigue un gating multinivel para economizar recursos y maximizar el vuelo fluido (*Keep Going*), reservando la deliberación del SLM para situaciones de alta incertidumbre o peligro inminente. La decisión de qué "cerebro" resuelve una situación de riesgo (SLM / FSM determinista / puramente reactivo) es seleccionable vía `AGENT_ARM`, para poder comparar los tres brazos sobre el mismo pipeline de percepción.

```
              ┌──────────────┐
              │ capture_node │ (RGB + telemetría; degradado si AirSim no responde)
              └──────┬───────┘
                     │
            ┌────────▼─────────┐
            │  degraded_router │──(degradado)──► degraded_hover ──► motor ──► END
            └────────┬─────────┘
                (ok)  │
                      ▼
              ┌──────────────┐
              │  perception  │ (flujo óptico + derotación + FOE → ObstacleField)
              └──────┬───────┘
                     │
            ┌────────▼─────────┐
            │  policy_router   │ (arma: slm | fsm | reactive)
            └─┬────┬────┬────┬─┘
       keep_going  evasive  girar_90  deliberative / fsm
                \    |      |      /
                 \   |      |     /
                  ▼  ▼      ▼    ▼
                 ┌────────────────┐
                 │   motor_node   │
                 └───────┬────────┘
                        END
```

> **Nodo retirado (F0.4, 2026-0824):** `canny_xor_gate` + `xor_router` (gate de bordes Canny+XOR que bypaseaba `perception` cuando la escena no cambiaba visualmente) se sacaron del grafo con evidencia medida en vuelo real — ver [`legacy/README.md`](legacy/README.md) y `CHANGELOG.md` 2026-0824. Resumen: a la frecuencia de vuelo el bypass casi nunca disparaba, y en el puñado de ciclos donde sí disparaba (hover post-`FRENAR`) saltaba `policy_router` entero, evitando re-evaluar el campo de obstáculos justo en el momento donde más importaba hacerlo.

---

## `ObstacleField`: el único contrato de percepción

`src/perception/obstacle_field.py` reemplaza a `detected_obstacles` (que desde el retiro de YOLO quedaba siempre en `[]`, dejando ciegos al router, al fallback determinista y al override de seguridad — ver `legacy/README.md`). Es una grilla de 3×3 celdas (sector `izquierda|centro|derecha` × banda `superior|medio|inferior`), cada una con `occupancy`, `ttc_s`, `divergence` y `confidence`. Router, `evasive_node`, `deliberative_node`, `fsm_node` y el logger de vuelo leen **únicamente** su API (`is_blocked`, `sector_ttc`, `blocked_fraction`, `summary_text`, `to_dict`); ninguno accede a campos crudos de flujo óptico.

`src/perception/flow_ttc.py` la produce: deroto el flujo óptico con la telemetría de actitud (pitch/roll/yaw), estimo el FOE (Focus of Expansion) por mínimos cuadrados ponderados con un paso de recorte de outliers, y calculo TTC en **segundos reales** (`dt` de telemetría, no el período nominal del lazo). Sin evidencia suficiente (hover, giro puro), el campo resultante tiene `confidence=0` y `ttc=inf`: no hay clamp cosmético que esconda la falta de señal.

## Nodos del Grafo (`DroneState`, `src/agents/graph.py`)

### `capture_node`
Llama a `AirSimClient.capture()`. En modo estricto (`AIRSIM_STRICT=true`, default en vuelo) si AirSim no responde, **no** genera un frame sintético: marca `state["degraded"]=True` y el ciclo va directo a `degraded_hover` (hover de seguridad, sin percepción ni deliberación).

### `perception`
Único nodo de percepción pesada: `FlowTTCEstimator` (instanciado una vez, no por frame) produce el `ObstacleField` completo del ciclo.

### `policy_router`
Router único de política. Reemplaza a la combinación `ttc_router` + `hover_before_slm_node` + `blind_wall_router_node` de la versión original, que por invocar un nodo dentro del cuerpo de otro más una arista adicional hacia el mismo destino, podía consultar al SLM **dos veces por ciclo**. Selecciona primero el brazo (`AGENT_ARM`):
- **`reactive`** (cota inferior): siempre `keep_going`, guiado a waypoint sin evasión.
- **`fsm`**: siempre `fsm_node`, máquina de estados determinista sobre el mismo `ObstacleField` y el mismo `action_to_command()` que usa el brazo SLM — para que la comparación SLM vs FSM sea limpia.
- **`slm`** (default): la lógica táctica jerárquica original (TTC + bloqueo por sector + persistencia de maniobra + escape de deadlock), resolviendo hacia `keep_going` / `evasive` / `girar_90` (bypass determinista si el FOV está mayormente bloqueado) / `deliberative`.

### `deliberative` (brazo `slm`)
Corre en un hilo aparte (`DeliberationService`, `src/agents/deliberation_service.py`): el nodo **nunca bloquea** el lazo de control. El ciclo en que se encola el pedido (o mientras se espera respuesta) el comando es `FRENAR`; si el SLM no responde dentro de `SLM_WATCHDOG_MS` (default 1500 ms), se aplica el fallback determinista y se marca `timeout=True` en `deliberations[]`. Usa decodificación restringida (`response_format=json_schema`) cuando el servidor la soporta, con el parser tolerante como red de seguridad.

### `evasive`, `fsm`, `girar_90`, `motor`
`evasive_node` y `fsm_node` comparten `action_to_command()` (`src/agents/action_map.py`) con `deliberative_node`: es la única fuente de verdad de la cinemática por macro-acción, para que ninguna tenga dos definiciones distintas según quién la ejecute. `motor_node` envía el comando final a `AirSimClient.execute_velocity()`, que ya no bloquea (`moveByVelocityBodyFrameAsync` es last-command-wins; antes un `.join()` fijaba el período del lazo en 2 s).

---

## Estructura del Código

- [`main.py`](main.py): punto de entrada. Crea el único `AirSimClient` del proceso y lo inyecta en `compile_workflow()`.
- [`src/agents/graph.py`](src/agents/graph.py): `DroneState`, nodos, `policy_router`, `degraded_router`.
- [`src/agents/action_map.py`](src/agents/action_map.py): cinemática única por macro-acción.
- [`src/agents/deliberation_service.py`](src/agents/deliberation_service.py): worker asíncrono para la consulta al SLM.
- [`src/agents/deliberative.py`](src/agents/deliberative.py), [`evasive.py`](src/agents/evasive.py), [`fsm.py`](src/agents/fsm.py), [`reactive.py`](src/agents/reactive.py): los tres brazos de política + el guiado nominal.
- [`src/perception/obstacle_field.py`](src/perception/obstacle_field.py): contrato único de percepción.
- [`src/perception/flow_ttc.py`](src/perception/flow_ttc.py): derotación + FOE + TTC.
- [`src/hardware/airsim_client.py`](src/hardware/airsim_client.py): cliente AirSim, actuador no bloqueante, modo estricto.
- [`src/navigation/waypoint_tracker.py`](src/navigation/waypoint_tracker.py): guiado a waypoint + seguimiento de progreso real (`progress_stall_cycles`).
- [`src/logging/flight_logger.py`](src/logging/flight_logger.py): JSONL estructurado por ciclo, para `experiments/`.
- [`legacy/`](legacy/): módulos retirados (YOLO, IPM, estimador de TTC anterior, gate de bordes XOR), con la justificación medida de cada retiro.
- [`experiments/`](experiments/): `runner.py` + `analyze.py` (comparación batch SLM/FSM/reactivo), `collect_ttc_dataset.py` + `analyze_ttc.py` (validación de TTC contra el canal depth).
- [`scripts/bench_capture.py`](scripts/bench_capture.py): mide el techo real de `simGetImages` sobre la conexión al simulador, para elegir `LOOP_HZ` con evidencia.

---

## Configuración y Ejecución

### **1. Variables de Entorno (`.env`)**

```ini
AIRSIM_MODE=Drone
AIRSIM_IP=127.0.0.1
AIRSIM_PORT=41451
AIRSIM_STRICT=true          # false solo para tests: permite frames sinteticos si AirSim no responde
LOOP_HZ=5.0                 # ajustar con scripts/bench_capture.py
AGENT_ARM=slm                # slm | fsm | reactive

TTC_EVASION_THRESHOLD=3.2    # calibrado F1.3 (umbral de Youden, ROC vs. canal depth)
TTC_SAFE_THRESHOLD=4.6       # idem
FOV_BLOCKED_THRESHOLD=0.6

REACTIVE_FORWARD_SPEED=2.0
SLM_WATCHDOG_MS=1500

LOCAL_LLM_URL=http://[IP_ADDRESS]/v1
LOCAL_LLM_MODEL_NAME=qwen/qwen2.5-vl-3b
VLM_VISION_ENABLED=true
VLM_FRAME_HISTORY_SIZE=1
VLM_USE_JSON_SCHEMA=true
```

### **2. Ejecución**

```bash
conda activate airsim
python main.py
```

### **3. Tests**

```bash
pytest tests/ -q
```

No requieren AirSim: usan un `AirSimClient` stub con la misma interfaz (`capture`/`execute_velocity`/`get_telemetry`).

### **4. Experimentos (requieren AirSim corriendo)**

```bash
python experiments/runner.py --scenarios missions/*.json --arms slm fsm reactive --seeds 1 2 3
python experiments/analyze.py runs/
```
