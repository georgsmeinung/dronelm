Te paso el desglose pieza por pieza y luego la receta concreta para unir YOLO + AirSim en una prueba end-to-end. Lo que ya quedó armado en `/Users/jenic/Documents/dronelm/airsim-plan`:

### 1. El esqueleto y la idea

El paquete se llama `dronelm` y está en `src/dronelm/`. La regla de oro es que **el planificador de tierra y el navegador táctico son dos CLIs separados** que se comunican por un archivo JSON. Eso te da la tolerancia a fallos de la arquitectura de dos cerebros: si se corta el enlace con la estación de tierra, el dron ya lleva el plan cargado.

```
[src/dronelm/]
├── models/          ← contrato JSON (la "mochila" del dron)
├── planner/         ← Cerebro 1: NL → MissionManifest  (LM Studio, sin prisa)
├── tactical/        ← Cerebro 2: LangGraph + Phi-3      (rápido, en vuelo)
├── bridge/          ← Adaptador AirSim (import perezoso, opcional)
└── scripts/
    ├── plan.py      ← CLI: dronelm-plan "..."
    └── fly.py       ← CLI: dronelm-fly manifests/X.json
```

### 2. Capa `models/` — el contrato

- [src/dronelm/models/manifest.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/models/manifest.py) define `MissionManifest`: `mission_id`, `waypoints[]` (NED, z negativo = altura), `rules` (objetos a ignorar, umbral de batería para RTL, clases que abortan), `cruise_speed_m_s`, `takeoff_altitude`. Todo está validado con Pydantic, así que un plan malformado **nunca** puede entrar al grafo.
- [src/dronelm/models/tactical.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/models/tactical.py) define `TacticalState` (lo que el grafo arrastra entre ticks), `TacticalObservation` (telemetría + detecciones de un frame) y `TacticalAction` (`MOVE_TO_WAYPOINT | HOVER | EVADE | RETURN_TO_LAUNCH | LAND`). `TacticalState` recibe el `MissionManifest` en su inicialización — eso **es** la inyección de contexto del Paso 3 de tu diseño.

### 3. Capa `planner/` — el cerebro lento

- [src/dronelm/planner/lmstudio.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/planner/lmstudio.py) es un cliente OpenAI-compatible muy fino contra LM Studio. Lee `LMSTUDIO_BASE_URL`, `LMSTUDIO_API_KEY` y `LMSTUDIO_MODEL` del entorno — exactamente lo que LM Studio expone en `/v1`.
- [src/dronelm/planner/compiler.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/planner/compiler.py) lleva el `SYSTEM_PROMPT` que obliga al modelo a devolver **solo** el JSON del manifiesto (con `response_format={"type":"json_object"}`). `compile_mission(intent, ...)` lo parsea y lo valida con Pydantic; `save_manifest(...)` lo escribe a disco.

Flujo: `dronelm-plan "Revisa el perimetro norte (50,100). Ignora personas. Regresa si batería <20%"` → `manifests/PERIMETER_NORTH_01.json`.

### 4. Capa `tactical/` — el cerebro rápido

- [src/dronelm/tactical/prompts.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/tactical/prompts.py) genera el **pre-prompt** del SLM a partir del manifiesto (id, waypoints, ROE, umbral de batería). Es texto frío, sin inglés forzado, y se construye **una vez** antes del primer tick.
- [src/dronelm/tactical/graph.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/tactical/graph.py) arma el grafo de LangGraph:

  ```
  START → observe ──► decide ──► (END si misión completa, si no: observe)
  ```

  - `observe_node` recibe un `sensor(state)` que devuelve `TacticalObservation`. Por defecto hay un *stub* para dry-run, **pero se puede inyectar uno real** (YOLO + AirSim).
  - `decide_node` aplica primero un *safety override* duro: si `battery_percent <= rules.return_to_launch_battery_threshold`, la única acción posible es `RETURN_TO_LAUNCH`. Después llama al SLM táctico con `response_format=json_object`, parsea la salida a `TacticalAction`, y por último aplica `_enforce_roe` (chequea `abort_on_class`).
  - `run_one_tick(observation)` es el wrapper que el script de vuelo llama en bucle.

### 5. Capa `bridge/` — AirSim sin contaminar el resto

[src/dronelm/bridge/client.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/bridge/client.py) hace **una sola cosa**: envuelve `airsim.MultirotorClient`. La clave es que `import airsim` está dentro de `__post_init__`, así que podés importar `dronelm` sin tener AirSim instalado (los tests pasan aunque `airsim` no exista, y `is_available()` devuelve `False`).

Exposiciones de alto nivel que usa el script de vuelo: `arm_and_takeoff(alt_ned)`, `move_to(x,y,z,speed)`, `hover()`, `land()`, `get_state()`, `get_battery_percent()`.

### 6. Los dos CLIs

- [src/dronelm/scripts/plan.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/scripts/plan.py): recibe la intención en NL, la compila y guarda `manifests/<MISSION_ID>.json`. Acepta `--id`, `--takeoff-altitude`, `--print`.
- [src/dronelm/scripts/fly.py](/Users/jenic/Documents/dronelm/airsim-plan/src/dronelm/scripts/fly.py): lee el manifiesto, construye el grafo, llama `arm_and_takeoff`, y entra en el loop tick → `run_one_tick(observation)` → `bridge.move_to(...)`. Termina con `land()`.

---

## Cómo conectar YOLO real

La forma idiomática es **inyectar el sensor** al construir el grafo. YOLO nunca entra al paquete `dronelm`; vive afuera y le pasás una función `sensor(state) -> TacticalObservation`. Ejemplo concreto (no está en el repo todavía, podés tirarlo en un archivo aparte o en un Jupyter):

```python
# ejemplo: my_yolo_sensor.py
import airsim, numpy as np, cv2
from ultralytics import YOLO
from dronelm.models import TacticalObservation, Detection

_model = YOLO("yolov8n.pt")            # liviano, ideal para pruebas
_IGNORED = {"person", "car", "truck"}

def make_airsim_yolo_sensor(client: airsim.MultirotorClient,
                            vehicle: str = "Drone0"):
    def sensor(state):
        # 1) imagen RGB desde la cámara frontal
        resp = client.simGetImage("0", airsim.ImageType.Scene, vehicle_name=vehicle)
        img_bgr = cv2.imdecode(np.frombuffer(resp, np.uint8), cv2.IMREAD_COLOR)

        # 2) inferencia YOLO
        results = _model.predict(img_bgr, verbose=False, conf=0.35)[0]
        detections = [
            Detection(label=r.names[int(r.boxes.cls[i])],
                      confidence=float(r.boxes.conf[i]))
            for i in range(len(r.boxes))
        ]

        # 3) telemetría cruda de AirSim
        s = client.getMultirotorState(vehicle_name=vehicle)
        pos = s.kinematics_estimated.position
        vel = s.kinematics_estimated.linear_velocity
        battery = float(getattr(s, "battery_percent", 100.0) or 100.0)

        return TacticalObservation(
            battery_percent=battery,
            position={"x": pos.x_val, "y": pos.y_val, "z": pos.z_val},
            velocity={"x": vel.x_val, "y": vel.y_val, "z": vel.z_val},
            heading_deg=0.0,
            detections=detections,
        )
    return sensor
```

Y se enchufa así (reemplazá el loop de `dronelm/scripts/fly.py` o importalo desde tu propio runner):

```python
from dronelm.models import MissionManifest
from dronelm.tactical import build_tactical_graph
from dronelm.bridge import AirSimBridge
from my_yolo_sensor import make_airsim_yolo_sensor

manifest = MissionManifest.model_validate_json(open("manifests/PERIMETER_NORTH_01.json").read())
bridge   = AirSimBridge()
sensor   = make_airsim_yolo_sensor(bridge.client, bridge.vehicle_name)

bridge.arm_and_takeoff(manifest.takeoff_altitude)
graph = build_tactical_graph(manifest, sensor=sensor)   # <-- inyección clave

state = graph.initial_state
for tick in range(600):
    state = graph.run_one_tick(sensor(state))            # una vuelta del grafo
    # acá traducís state.last_action a comandos AirSim (move_to / hover / land…)
    if state.mission_complete:
        break
bridge.land()
```

El grafo no se entera de YOLO: solo ve un `TacticalObservation` por tick. Cuando cambies de modelo (YOLOv8 → YOLO-NAS → RT-DETR) o de sensor (RGB → estéreo), solo tocás el sensor.

---

## Cómo conectar AirSim real

1. **Instalar el paquete de Python** (la extra `airsim` solo se baja si tenés el simulador; el resto del código no la requiere):
   ```bash
   cd /Users/jenic/Documents/dronelm/airsim-plan
   python3 -m venv .venv && source .venv/bin/activate
   pip install -U pip
   pip install -e ".[dev,airsim]"   # ultralytics va aparte
   pip install ultralytics          # para YOLO
   ```

2. **Levantar AirSim (Unreal)**: lanzá el bloque `Blocks` o el `LandscapeMountains` que viene con AirSim. Configurá `Documents/AirSim/settings.json` con la cámara RGB en `0` y un dron multirrotor con nombre `Drone0`:
   ```json
   {
     "SettingsVersion": 1.2,
     "SimMode": "Multirotor",
     "Vehicles": {
       "Drone0": { "VehicleType": "SimpleFlight", "Cameras": { "0": { "CaptureSettings": [{ "ImageType": 0, "Width": 640, "Height": 360 }] } } }
     }
   }
   ```

3. **Apuntar `.env`** (copiá `.env.example`):
   ```
   AIRSIM_HOST=127.0.0.1
   AIRSIM_VEHICLE_NAME=Drone0
   LMSTUDIO_BASE_URL=http://localhost:1234/v1
   LMSTUDIO_MODEL=llama-3-8b-instruct
   TACTICAL_BASE_URL=http://localhost:1234/v1
   TACTICAL_MODEL=phi-3-mini-4k-instruct
   ```

4. **Levantar LM Studio** y arrancar el servidor local con el modelo del planificador. Para el SLM táctico podés usar el mismo LM Studio con el modelo Phi-3 cargado en otra pestaña, o un segundo servidor en otro puerto.

---

## Receta end-to-end punto a punto

1. Simulador AirSim abierto, escena cargada.
2. LM Studio corriendo en `localhost:1234` con `llama-3-8b-instruct` (y opcionalmente Phi-3).
3. En la terminal, con el venv activado y la `.env` cargada:
   ```bash
   # Paso 1: el operador habla; el planificador escribe el manifiesto.
   dronelm-plan "Revisa el perimetro de la zona industrial norte \
                 en X:50 Y:100 Z:-10. Ignora personas. \
                 Si la bateria cae bajo 20%, regresa a base."

   # Paso 2: inspección rápida.
   cat manifests/PERIMETER_NORTH_01.json

   # Paso 3: el dron despega y el grafo toma el control.
   dronelm-fly manifests/PERIMETER_NORTH_01.json --max-ticks 600
   ```
4. Para meter YOLO en el loop, en lugar de `dronelm-fly` corré tu propio script que llame a `build_tactical_graph(manifest, sensor=make_airsim_yolo_sensor(...))` y al `run_one_tick(sensor(state))` en bucle, exactamente como en el snippet de arriba.

### Qué verificar en la primera corrida
- Que `print(f"tick={tick:03d} action={action.name} rationale=...")` salga por stderr y la acción cambie cuando YOLO detecte algo nuevo.
- Que cuando bajes la batería a mano (`simSetBatteryLevel` desde el cliente de AirSim o el slider de Unreal), el SLM siga emitiendo `RETURN_TO_LAUNCH` por el *override* de `decide_node`, sin importar lo que el modelo "quiera" hacer.
- Que si matás el proceso del planificador a mitad del vuelo, el dron **siga volando**, porque el manifiesto ya está en el estado del grafo.

Si querés, en el próximo paso te escribo el script completo `fly_with_yolo.py` (sensor + loop + bridge) listo para correr, y un manifest de ejemplo en `manifests/` para no tener que tipear la intención cada vez.