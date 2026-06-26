Te lo desgrano en dos bloques: primero el mapa del código (cómo casa cada archivo con los pasos 1-6) y después la receta concreta para correr YOLO contra un AirSim real, punto a punto.

## Cómo está cableado el pipeline

El estado [`DroneState`](/Users/jenic/Documents/dronelm/airsim-loop/src/agents/graph.py:24) viaja por los nodos del grafo en [src/agents/graph.py](/Users/jenic/Documents/dronelm/airsim-loop/src/agents/graph.py:24). El grafo final tiene esta forma:

```
perception -> gatekeeper -> { reactive -> motor -> END
                              deliberative -> motor -> END }
```

**Paso 1 — Captura sensorial.** Lo hace [airsim_client.py:AirSimClient.capture](/Users/jenic/Documents/dronelm/airsim-loop/src/hardware/airsim_client.py:97). Llama a `simGetImages` con la cámara `"0"` y a `getMultirotorState` para obtener posición/velocidad/orientación en marco NED. Devuelve un `np.ndarray` RGB y un dict de telemetría. Si no hay simulador, devuelve un frame sintético con un cuadrado central (modo simulado) para que el grafo no se rompa.

**Paso 2 — Traducción píxeles-a-palabras.** Lo hace `perception_node` en [graph.py:54](/Users/jenic/Documents/dronelm/airsim-loop/src/agents/graph.py:54). Encadena [`YoloDetector.detect`](/Users/jenic/Documents/dronelm/airsim-loop/src/perception/detector.py:55) y [`translate_detections`](/Users/jenic/Documents/dronelm/airsim-loop/src/perception/translator.py:88). El primero corre `ultralytics.YOLO(weights/yolov8n.pt).predict(...)` y devuelve dataclasses `Detection(object, confidence, bbox=[x1,y1,x2,y2])`. El segundo clasifica el `cx` del bbox en sector (`Izquierda`/`Centro`/`Derecha`) según una banda central configurable (`CENTER_BAND_RATIO`) y estima la distancia con la heurística de cobertura vertical del frame, mapeando a `Inminente` / `Cerca` / `Lejos` con los umbrales `PROXIMITY_NEAR_M` y `PROXIMITY_FAR_M` del `.env`. El resumen textual sale de [`summarize_scene`](/Users/jenic/Documents/dronelm/airsim-loop/src/perception/translator.py:135).

**Paso 3 — Gatekeeper.** [`gatekeeper_router`](/Users/jenic/Documents/dronelm/airsim-loop/src/agents/graph.py:114) recorre `detected_obstacles`. Si alguno tiene `sector == "Centro"` y `proximity` ∈ `{Inminente, Cerca}`, devuelve `"deliberative"`; si no, `"reactive"`. Esa cadena cablea el `add_conditional_edges` del grafo.

**Paso 4A — Reflejo rápido.** [`reactive_node`](/Users/jenic/Documents/dronelm/airsim-loop/src/agents/reactive.py:24) fija `MANTENER_RUMBO` con velocidad hacia adelante por defecto (`REACTIVE_FORWARD_SPEED`) y una micro-corrección de altitud. Sin LLM.

**Paso 4B — Cerebro deliberativo.** [`deliberative_node`](/Users/jenic/Documents/dronelm/airsim-loop/src/agents/deliberative.py:153) arma el prompt con `_build_user_prompt` (resumen de obstaculos + telemetría), llama al servidor compatible con OpenAI en `LOCAL_LLM_URL` (sirve para LM Studio y Ollama con su adaptador), parsea JSON estricto con `_parse_decision` y valida que la macro-acción esté en `VALID_ACTIONS`. Si el SLM no responde o devuelve JSON inválido, `_fallback_decision` aplica una heurística determinista (frontal → evadir al lado libre; lateral → abrir; limpio → mantener) para que el bucle no quede colgado.

**Paso 5 — Ejecución motriz.** `motor_node` en [graph.py:75](/Users/jenic/Documents/dronelm/airsim-loop/src/agents/graph.py:75) toma el `velocity_command` del nodo que ganó y llama a [`AirSimClient.execute_velocity`](/Users/jenic/Documents/dronelm/airsim-loop/src/hardware/airsim_client.py:135), que internamente usa `moveByVelocityAsync` con `yaw_mode` en rate. En modo simulado solo loguea el comando.

**Paso 6 — Bucle continuo.** [main.py:main](/Users/jenic/Documents/dronelm/airsim-loop/main.py:38) entra en un `while True`, invoca `graph.invoke({...})` con estado vacío y duerme `1/LOOP_HZ` segundos. Cuando el estado llega vacío, el nodo `perception_node` se encarga de capturar imagen+telemetría desde AirSim. Al recibir `KeyboardInterrupt`, llama a `airsim_client.disconnect()` para armar/desarmar de forma limpia.

## Receta punto a punto: YOLO + AirSim real

**0. Prerrequisitos.**
- Simulador corriendo (Unreal + AirSim plugin) con `Settings.json` configurado en modo `Multirotor` (no confundir con `Car`). Lo más limpio es el Block environment oficial de AirSim.
- La máquina donde corre AirSim y la que corre Python deben verse por red. Si es la misma, `127.0.0.1`; si no, la IP LAN del equipo con Unreal.

**1. Bajar los pesos reales de YOLO.** El archivo [weights/yolov8n.pt](/Users/jenic/Documents/dronelm/airsim-loop/weights/yolov8n.pt) está en 0 bytes; ultralytics te lo descarga solo la primera vez, o lo bajás vos manualmente:

```bash
mkdir -p weights
# Opción A: dejar que ultralytics lo baje en el primer predict()
# Opción B: forzar la descarga
python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

Después asegurate de que el archivo `weights/yolov8n.pt` tenga varios megas (≈ 6 MB para `yolov8n`). Si está vacío, el primer `predict` levantará `RuntimeError`.

**2. Ajustar el `.env`** ([.env](/Users/jenic/Documents/dronelm/airsim-loop/.env)). Lo crítico para el escenario real:

```
AIRSIM_MODE=Drone
AIRSIM_IP=<IP_de_la_maquina_con_AirSim>   # 127.0.0.1 si es la misma
AIRSIM_PORT=41451
PROXIMITY_THRESHOLD_METERS=5.0
LOCAL_LLM_URL=http://localhost:1234/v1
LOCAL_LLM_MODEL_NAME=phi-3   # o el que tengas cargado en LM Studio/Ollama
```

Si tu dron se llama distinto de `Drone1` o la cámara frontal no es `"0"`, exportá `AIRSIM_VEHICLE_NAME` y `AIRSIM_CAMERA_NAME` antes de correr `main.py`. Lo lee [airsim_client.py:23-29](/Users/jenic/Documents/dronelm/airsim-loop/src/hardware/airsim_client.py:23).

**3. Instalar dependencias.** En un entorno con Python 3.10+:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`cosys-airsim` y `ultralytics` pesan bastante (PyTorch incluido). En Mac Apple Silicon conviene la rueda CPU-only de PyTorch que ya trae ultralytics.

**4. Verificar que AirSim responde.** Antes de tocar el grafo, un handshake rápido:

```python
import airsim
c = airsim.MultirotorClient(ip="127.0.0.1", port=41451)
c.confirmConnection()
c.enableApiControl(True)
print(c.getMultirotorState())
```

Si esto falla, el resto no va a funcionar. Casi siempre el motivo es firewall de Windows, IP mal puesta, o el plugin de AirSim no se cargó en Unreal.

**5. (Opcional pero recomendado) Precalentar YOLO.** La primera inferencia tarda segundos por la carga del modelo. Para evitar que el primer ciclo se vea "lento", podés forzar la carga antes:

```bash
python3 -c "from src.perception import YoloDetector; YoloDetector('weights/yolov8n.pt')._ensure_model()"
```

Si no querés SLM por ahora, dejá `LOCAL_LLM_URL` apuntando a un servidor caído: el código ya cae en `_fallback_decision` sin romper el bucle.

**6. Arrancar el bucle.**

```bash
python3 main.py
```

Lo que vas a ver en consola, ciclo a ciclo:

```
[Ciclo] Capturando sensores y ejecutando grafo...
  detecciones: - tree sector=Centro proximidad=Inminente dist=2.1m
  resumen: Detecciones: tree centro (Inminente, 2.1m).
  ruta   : deliberative
  accion : EVADIR_DERECHA
  motor  : vx=+1.00 vy=+2.50 vz=+0.00 yaw=-0.20 (Fallback: ...)
```

Mientras la decisión sea `MANTENER_RUMBO`, el log va a mostrar `ruta: reactive` y velocidades constantes hacia adelante; en cuanto YOLO detecte algo en el sector central con `proximity Inminente/Cerca`, el Gatekeeper dispara el cerebro y vas a ver `ruta: deliberative` con un vector lateral.

## Verificación punto a punto

Para saber en qué capa está fallando algo, probá cada eslabón por separado:

1. **AirSim solo**: ¿llega imagen y telemetría? Usá el snippet del paso 4.
2. **YOLO solo**: ¿detecta bien sobre una captura fija? Corré `python3 -c "from src.perception import YoloDetector; d=YoloDetector(); print(d.detect('ruta/a/imagen.jpg'))"`.
3. **Traductor solo**: ¿los sectores y la proximidad tienen sentido? `python3 -c "from src.perception import translate_detections, Detection; print(translate_detections([Detection('tree',0.9,[40,30,80,120])]))"`.
4. **Gatekeeper solo**: ya lo probé arriba con `gatekeeper_router` y responde correcto a las cuatro variantes (`empty`, `izq-lejos`, `centro-inminente`, `centro-cerca`).
5. **SLM solo**: si usás LM Studio, abrí la pestaña `Developer`/server local y verificá que `curl http://localhost:1234/v1/models` devuelva el modelo. Si devuelve JSON inválido, `_parse_decision` filtra y cae al fallback, así que el bucle sigue vivo.
6. **Grafo entero en modo simulado**: corré `python3 main.py` con la lib `airsim` no instalada. Vas a ver `[AirSimClient] Libreria cosys-airsim no disponible. Modo simulado.` y `[AirSimClient][simulado] vx=...` — eso confirma que el grafo completo ejecuta sin tocar el simulador.

## Tips finos que te van a ahorrar tiempo

- Si YOLO te marca todo como `person`/`car` con confianza bajísima en el frame de AirSim, subí `YOLO_CONF` (en `.env`) hasta `0.5` y volvé a probar. El bloque sintético del modo simulado siempre va a generar detecciones cerca del centro, así que es un buen banco de pruebas antes de gastar GPU contra el simulador.
- Si el dron “se queda quieto” en el simulador, lo más probable es que `enableApiControl` no se haya podido llamar. Mirá si en consola aparece `[AirSimClient] No se pudo armar/despegar (...)` — eso significa que el grafo ya está corriendo pero el dron no responde a `moveByVelocityAsync`.
- Si querés que el cerebro deliberativo se active con umbrales más finos, agregá `PROXIMITY_NEAR_M=2.5` y `PROXIMITY_FAR_M=6.0` en el `.env` y revalidá con `translate_detections`.
- Cuando empieces a iterar con el SLM real, setea `temperature=0.2` (ya está) y limitá `max_tokens=200` (ya está) para que cada ciclo deliberativo gaste poco y responda rápido.

Si querés, puedo dejarte un script de `sanity_check.py` que ejecute los seis pasos de verificación aisladamente y te diga exactamente dónde se corta la cadena cuando algo falla.