# Mapeo de Código a Grafo de Loop de Control Autónomo Jerárquico

Este submódulo (`airsim-loop`) implementa el bucle de control reactivo/deliberativo de navegación autónoma para drones cuadricópteros usando **LangGraph**, **YOLO** (visión monocular), estimación no neuronal de **TTC (Time-To-Collision)** y un **SLM Local** (Small Language Model).

## Arquitectura del Bucle de Control Jerárquico

El pipeline de vuelo sigue un gating multinivel diseñado para economizar recursos computacionales y maximizar el vuelo fluido (*Keep Going*), reservando las llamadas al SLM únicamente para situaciones de alta incertidumbre o peligro inminente.

```
                  ┌─────────────────┐
                  │  capture_node   │ (Captura RGB + Telemetría NED)
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │ canny_xor_gate  │ (Paso 1: XOR Canny < 2% cambio?)
                  └────────┬────────┘
                           │
                 ┌─────────┴─────────┐
       (Si < 2%) │                   │ (Si ≥ 2%)
                 ▼                   ▼
         ┌──────────────┐   ┌──────────────────┐
         │  keep_going  │   │ roi_yolo_detect  │ (Paso 2: Crop ROI 62° + YOLO)
         └───────┬──────┘   └────────┬─────────┘
                 │                   │
                 │          ┌────────▼─────────┐
                 │          │   ttc_estimate   │ (Paso 3: Estimación TTC BB-w)
                 │          └────────┬─────────┘
                 │                   │
                 │          ┌────────┴────────────────────────┐
                 │          │ Router de 3 Vías (TTC Router)   │
                 │          └────────┬──────────────┬─────────┘
                 │                   │              │
                 │   (TTC > 5.0s)    │ (2.0s < TTC  │ (TTC ≤ 2.0s)
                 │   Sin Peligro     │    ≤ 5.0s)   │ Peligro Inminente
                 │                   ▼              ▼
                 │            ┌───────────┐   ┌────────────────┐
                 │            │  evasive  │   │ hover_and_slm  │ (Hover + SLM)
                 │            └─────┬─────┘   └───────┬────────┘
                 │                  │                 │
                 └──────────────────┼─────────────────┘
                                    │
                           ┌────────▼────────┐
                           │   motor_node    │ (Ejecución Motriz AirSim API)
                           └────────┬────────┘
                                    │
                                   END
```

---

## Detalle de Pasos Nodos del Grafo (`DroneState`)

El estado [`DroneState`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/graph.py#L21) circula entre los nodos del grafo en [`src/agents/graph.py`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/graph.py).

### **Paso 0 — Captura Sensorial (`capture_node`)**
Llama a [`AirSimClient.capture`](file:///d:/TesisMCD/dronelm/airsim-loop/src/hardware/airsim_client.py) para obtener el fotograma RGB de la cámara frontal (`"0"`) y la telemetría del cuadricóptero (posición/velocidad/orientación). Si el simulador no está conectado, genera un fotograma de prueba sintético (modo simulado).

### **Paso 1 — Gating de Bordes Ultra Rápido (`canny_xor_gate_node`)**
Inspirado en el filtrado de bordes de Kaneko et al. (2017), se extraen los bordes Canny del fotograma actual y se realiza una operación **XOR binaria entre el frame actual y el anterior**.
* **Router XOR (`xor_router`)**: Si la tasa de cambio (`xor_change_ratio`) es menor a `CANNY_XOR_THRESHOLD` (`0.02` por defecto, indicando cielo abierto o textura homogénea), se transiciona directamente a `keep_going` salteando YOLO y SLM en **< 3 ms**.

### **Paso 2 — Recorte ROI de 62° e Inferencia YOLO (`roi_yolo_detect_node`)**
Siguiendo a Al-Kaff et al. (2017), la imagen se recorta a una **Región de Interés (ROI) con campo visual diagonal de 62°**. YOLO (ej. `yolov8n.pt` o `yolo26n`) procesa únicamente dicho recorte para ahorrar hardware y reducir latencia. Traduce las detecciones a sectores (`Izquierda`/`Centro`/`Derecha`) y genera un resumen cualitativo de escena.

### **Paso 3 — Estimación de Tiempo de Colisión No Neuronal (`ttc_estimate_node`)**
Implementa la estrategia de expansión de cajas delimitadoras (Rill & Faragó / Looming). Extrae el ancho de la bounding box (`BB-w`) de cada obstáculo en la ROI y monitorea su tasa de expansión temporal para calcular el **TTC (Time-To-Collision)** estimado en segundos.

### **Paso 4 — Bifurcación de Control (Router de 3 Vías `ttc_router`)**
1. **Caso A: Sin Peligro (`TTC > 5.0s` o sin obstáculos)**: Transiciona a `keep_going` (Reflejo Rápido con velocidad frontal constante `REACTIVE_FORWARD_SPEED`).
2. **Caso B: Maniobra Evasiva Local Directa (`2.0s < TTC ≤ 5.0s`)**: Transiciona al nodo [`evasive_node`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/evasive.py). Calcula si hay mayor masa de obstáculos a la izquierda o derecha en la ROI y ejecuta una corrección física simple lateral (`EVADIR_IZQUIERDA` / `EVADIR_DERECHA`) **sin detener el dron ni llamar al SLM**.
3. **Caso C: Peligro Inminente o Zona de Incertidumbre (`TTC ≤ 2.0s`)**: Transiciona a `hover_and_slm`.

### **Paso 5 — Parada de Seguridad y Consulta al SLM (`hover_and_slm_node`)**
1. **Parada de seguridad**: Llama inmediatamente a `AirSimClient.execute_velocity(vx=0, vy=0, vz=0)` entrando en modo **Hover** para congelar el avance del cuadricóptero y prevenir colisiones por latencia de inferencia.
2. **Llamada al SLM**: Invoca a [`deliberative_node`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/deliberative.py), que envía el prompt estructurado al servidor de LLM local (`LOCAL_LLM_URL` OpenAI-compatible) con decodificación restringida JSON. Devuelve la macro-acción evasiva compleja.

### **Paso 6 — Ejecución Motriz (`motor_node`)**
Toma el comando final de velocidad (`vx`, `vy`, `vz`, `yaw_rate`) generado por el nodo activo y lo envía a la API de AirSim mediante `moveByVelocityAsync`.

---

## Estructura del Código

- [`main.py`](file:///d:/TesisMCD/dronelm/airsim-loop/main.py): Punto de entrada que ejecuta el bucle `while True` invocando el grafo compilado.
- [`src/agents/graph.py`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/graph.py): Define `DroneState`, nodos del pipeline jerárquico y los routers condicionales `xor_router` y `ttc_router`.
- [`src/agents/reactive.py`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/reactive.py): Lógica del estado "Sigue Adelante" (`keep_going`).
- [`src/agents/evasive.py`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/evasive.py): Lógica de maniobra evasiva local rápida sin SLM.
- [`src/agents/deliberative.py`](file:///d:/TesisMCD/dronelm/airsim-loop/src/agents/deliberative.py): Inferencia deliberativa del SLM local con fallback determinista.
- [`src/perception/`](file:///d:/TesisMCD/dronelm/airsim-loop/src/perception):
  - `canny_gate.py`: Operaciones de bordes Canny y XOR binario entre frames.
  - `roi.py`: Recorte geométrico de la ROI de 62°.
  - `ttc.py`: Estimación geométrica no neuronal del Time-To-Collision a partir del ancho `BB-w`.
  - `detector.py`: Wrapper de inferencia YOLOv8 / YOLO26.
  - `translator.py`: Traductor de cajas/máscaras a lenguaje natural.
- [`src/hardware/airsim_client.py`](file:///d:/TesisMCD/dronelm/airsim-loop/src/hardware/airsim_client.py): Cliente de API AirSim con soporte para fallback simulado.

---

## Configuración y Ejecución

### **1. Variables de Entorno (`.env`)**

```ini
AIRSIM_MODE=Drone
AIRSIM_IP=127.0.0.1
AIRSIM_PORT=41451
YOLO_WEIGHTS=weights/yolov8n.pt
YOLO_CONF=0.35
CANNY_XOR_THRESHOLD=0.02
TTC_EVASION_THRESHOLD=2.0
TTC_SAFE_THRESHOLD=5.0
REACTIVE_FORWARD_SPEED=2.0
EVASION_LATERAL_SPEED=2.5
LOCAL_LLM_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL_NAME=lfm2.5-1.2b-instruct
```

### **2. Ejecución**

```bash
# Activar entorno
conda activate airsimenv

# Iniciar el bucle de control
python main.py
```

### **3. Ejecución de Tests**

Para validar el grafo y todos los componentes:

```bash
pytest
```