# Anexo 6: Configuración del entorno de simulación, variables de sistema y protocolo de reproducibilidad

La reproducibilidad empírica constituye un pilar metodológico indispensable para la investigación en robótica aérea y sistemas ciberfísicos guiados por inteligencia artificial (§10.9). En arquitecturas híbridas como DroneLM —donde interactúan un motor de simulación física en tiempo real (Unreal Engine 5.5 + Cosys-AirSim), un grafo de decisión táctico asíncrono (LangGraph) y un servidor local de inferencia para modelos de lenguaje y visión (LM Studio / `llama.cpp`)—, garantizar que un evaluador independiente pueda replicar con fidelidad idéntica los resultados experimentales exige documentar exhaustivamente los archivos de configuración, los perfiles de escalabilidad gráfica, el diccionario completo de variables de entorno y los manifiestos de misión.

Este anexo consolida todos los parámetros operativos y el procedimiento de despliegue paso a paso que hicieron posible la batería de vuelos evaluada a lo largo de los tres Tiers de experimentación (§10.3).

---

## A6.1 Archivo de configuración de AirSim (`settings.json`) anotado

El plugin Cosys-AirSim lee su configuración al inicio desde el archivo `settings.json`, ubicado en Windows en `%USERPROFILE%\Documents\AirSim\settings.json`. La siguiente es la configuración formal utilizada durante los vuelos de calibración y experimentación de la tesis:

```json
{
  "SeeDocsAt": "https://github.com/Cosys-Lab/Cosys-AirSim/blob/main/docs/settings.md",
  "SettingsVersion": 2.0,
  "LogMessagesVisible": false,
  "SimMode": "Multirotor",
  "LocalHostIp": "0.0.0.0",
  "ApiServerPort": 41451,
  "RecordUIVisible": false,
  "ClockType": "SteppableClock",
  "OriginGeopoint": {
    "Latitude": 47.641468,
    "Longitude": -122.140165,
    "Altitude": 122
  },
  "CameraDefaults": {
    "CaptureSettings": [
      {
        "ImageType": 0,
        "Width": 1080,
        "Height": 720
      },
      {
        "ImageType": 3,
        "Width": 1080,
        "Height": 720
      },
      {
        "ImageType": 5,
        "Width": 1080,
        "Height": 720
      },
      {
        "ImageType": 1,
        "Width": 1080,
        "Height": 720
      }
    ]
  },
  "SubWindows": [
    {
      "WindowID": 2,
      "CameraName": "Front Camera",
      "ImageType": 0,
      "Visible": true
    }
  ]
}
```

### Anotaciones de ingeniería del archivo de configuración:
1. **`SimMode: "Multirotor"`**: instruye a AirSim a instanciar el modelo físico cinemático de cuadricóptero gobernado por el controlador interno `SimpleFlight`, con dinámica de 6 grados de libertad (6-DoF).
2. **`ClockType: "SteppableClock"`**: sincroniza el paso temporal de la simulación física con las consultas RPC de la API. A diferencia de `ScalableClock` o el reloj de pared del sistema, `SteppableClock` garantiza que cuando la GPU experimenta caídas momentáneas de tasa de cuadros por la inferencia del modelo multimodal, la física de vuelo no sufra aceleraciones destructivas ni inestabilidades de integración numérica en el estimador inercial.
3. **`ApiServerPort: 41451`**: puerto TCP de enlace Msgpack-RPC por el que se comunican `AirSimClient` y el motor de Unreal Engine.
4. **`CameraDefaults.CaptureSettings`**:
   * `ImageType 0` (`Scene`): captura RGB del fotograma en color natural, utilizada por el estimador de flujo óptico (`FlowTTCEstimator`) y por el modelo deliberativo (`Qwen2.5-VL-3B`).
   * `ImageType 3` (`DepthPlanar`) / `ImageType 1` (`DepthPerspective`): canal de profundidad en punto flotante utilizado exclusivamente para la validación cruzada del TTC monocular (§10.2).
   * `ImageType 5` (`Segmentation`): canal de segmentación semántica de mallas para auditoría visual.
   * `Width: 1080, Height: 720`: resolución nativa del render target frontal.
5. **`SubWindows`**: habilita una ventana secundaria flotante en el visor de Unreal Engine mostrando la cámara frontal a bordo en tiempo real, facilitando la supervisión visual del operador durante las corridas experimentales.

---

## A6.2 Perfil de escalabilidad gráfica de Unreal Engine 5.5 y preservación de gradientes

En estaciones de trabajo con una única GPU de consumo (NVIDIA GeForce RTX 5060 de 8 GB de VRAM), la simulación gráfica fotorrealista compite directamente por la memoria de video con los tensores del modelo de lenguaje (§8.1). Para permitir la coexistencia de ambos procesos sin provocar desbordamientos (*Out-Of-Memory*), es imperativo optimizar el rendimiento gráfico del motor.

Sin embargo, reducir indiscriminadamente la calidad gráfica introduce un problema crítico en la visión artificial: **los algoritmos de flujo óptico denso (Farnebäck y DIS) requieren textura visual y gradientes de intensidad espacial para calcular correspondencias entre fotogramas**. Si se desactivan las sombras o se aplica un desenfoque excesivo en las texturas de los edificios y el suelo, el flujo óptico decae por debajo del piso de ruido (`0.35 px`), dejando ciego al estimador de colisión.

### A6.2.1 Configuración forzada en `Config/DefaultScalability.ini`
Para impedir que Unreal Engine 5.5 reduzca dinámicamente la resolución interna de los búferes de captura de cámara al aplicar presets bajos, se fijó el modo de detalle en el archivo de configuración del proyecto:

```ini
[EffectsQuality@0]
r.DetailMode=2
[EffectsQuality@1]
r.DetailMode=2
[EffectsQuality@2]
r.DetailMode=2
[EffectsQuality@3]
r.DetailMode=2
[EffectsQuality@Cine]
r.DetailMode=2
```

### A6.2.2 Preset de escalabilidad en el Editor de Unreal Engine
Para las corridas de producción se configuró el siguiente perfil dentro del editor de Unreal Engine:
* **Resolution Scale:** 100% (sin reescalado espacial en el motor).
* **View Distance:** Medium (suficiente para el horizonte visual del dron).
* **Anti-Aliasing:** TSR (Temporal Super Resolution) en Medium.
* **Post-Processing:** Low (suprime desenfoques cinemáticos artificiales).
* **Shadows:** **Epic** (crucial para proyectar sombras nítidas sobre el pavimento, proporcionando los gradientes texturales que explota el flujo óptico).
* **Global Illumination:** Lumen en Low / Screen Space.
* **Reflections:** Screen Space.
* **Effects:** **Epic** (garantiza la resolución completa del render target de la cámara virtual de AirSim).

*(Véase captura de referencia en el repositorio: `informe/2026-0907 Scalability Config for Airsim and Shadows needed for TTC estimation.png`).*

---

## A6.3 Especificación exhaustiva de variables de entorno (`config/.env`)

Toda la configuración operativa de DroneLM está centralizada en un único archivo de configuración (`config/.env`, basado en la plantilla committeable `config/.env.example`). Los submódulos acceden a estas variables con ruta absoluta resuelta desde la raíz del repositorio.

A continuación se detalla el diccionario completo de variables y su impacto de ingeniería:

### 1. Hardware y Conexión RPC AirSim
| Variable | Valor Nominal | Justificación y Efecto |
|---|---|---|
| `AIRSIM_IP` | `"127.0.0.1"` | Dirección loopback local. En pruebas sobre LAN (`192.168.110.110`), la latencia RPC superaba los 8 s por congestión en `simGetImages`; ejecutar en localhost redujo la llamada a < 45 ms. |
| `AIRSIM_PORT` | `41451` | Puerto TCP estándar de la API de AirSim. |
| `AIRSIM_VEHICLE_NAME` | `"SimpleFlight"` / `"Drone1"` | Nombre del vehículo en el árbol de actores de Unreal Engine. |
| `AIRSIM_CAMERA_NAME` | `"0"` | Identificador de la cámara frontal montada en el fuselaje. |
| `DEFAULT_FRAME_WIDTH` | `1080` | Ancho de captura nativo devuelto por el sensor virtual. |
| `DEFAULT_FRAME_HEIGHT` | `720` | Alto de captura nativo devuelto por el sensor virtual. |
| `AIRSIM_RPC_TIMEOUT` | `8` | Segundos de espera máxima por llamada RPC antes de declarar timeout. |
| `AIRSIM_STRICT` | `true` | Si es `true`, la falla de conexión con AirSim marca `degraded=True` y entra en hover de seguridad; si es `false` (solo en tests unitarios), permite generar fotogramas sintéticos. |

### 2. Servidor de Inferencia Local (VLM / SLM)
| Variable | Valor Nominal | Justificación y Efecto |
|---|---|---|
| `LOCAL_LLM_URL` | `"http://192.168.110.101:1234/v1"` | Endpoint OpenAI-compatible del servidor local de inferencia (LM Studio / `llama.cpp`). |
| `LOCAL_LLM_MODEL_NAME`| `"qwen/qwen2.5-vl-3b"` | Identificador del modelo cuantizado cargado en VRAM (`Qwen2.5-VL-3B-Instruct.Q4_K_M`). |
| `VLM_VISION_ENABLED` | `true` | Habilita el envío del fotograma visual en base64 en el prompt multimodal. |
| `VLM_IMAGE_MAX_SIZE` | `384` | Resolución máxima de la imagen enviada al VLM. Limita la cantidad de tokens visuales generados por el codificador ViT, manteniendo la latencia acotada. |
| `VLM_USE_JSON_SCHEMA` | `true` | Activa la decodificación gramaticalmente restringida por esquema JSON (Anexo 4). |
| `SLM_WATCHDOG_MS` | `6000` | Tiempo límite del perro guardián (en ms) para la respuesta del SLM en hilo asíncrono. Si expira, se cancela y se aplica el fallback determinista. |
| `DEADLOCK_STRATEGY` | `"deep_vlm"` | Estrategia ante atasco: `"deep_vlm"` ejecuta barrido panorámico de 6 rumbos con consulta VLM; `"blind"` realiza escape puramente vertical por FSM. |

### 3. Lazo de Control Táctico
| Variable | Valor Nominal | Justificación y Efecto |
|---|---|---|
| `LOOP_HZ` | `5.0` | Frecuencia objetivo del bucle de control ($200\text{ ms}$ por ciclo). Calibrada para absorber la captura y el flujo óptico con margen holgado. |
| `AGENT_ARM` | `slm` | Brazo de política activo en el lazo de control: `slm` (deliberativo jerárquico), `fsm` (máquina de estados determinista) o `reactive` (línea base). |
| `AIRSIM_SEED` | `1` | Semilla de aleatoriedad para la corrida. En modo `--seed-jitter`, perturba levemente la pose inicial ($\pm 1.5\text{ m}$, $\pm 10^\circ$). |
| `CMD_DURATION_S` | `120.0` | Vigencia asignada al comando de velocidad en AirSim. Previene cabeceos parásitos (*pitch jerk*) causados por reemisiones continuas de comandos idénticos al PID interno de SimpleFlight. |

### 4. Percepción, Flujo Óptico y TTC
| Variable | Valor Nominal | Justificación y Efecto |
|---|---|---|
| `FLOW_ALGORITHM` | `"dis"` | Backend de flujo óptico: `"dis"` (Dense Inverse Search, rápido) o `"farneback"`. |
| `FLOW_DOWNSCALE_WIDTH`| `320` | Ancho al que se reduce el fotograma antes de calcular el flujo óptico ($320 \times 213\text{ px}$). |
| `CAMERA_FX` / `CAMERA_FY`| `554.0` | Distancia focal calibrada de la cámara en píxeles. |
| `FLOW_NOISE_FLOOR_PX` | `0.35` | Magnitud mínima en píxeles para considerar que un vector es señal física y no ruido numérico. |
| `FOE_OUTLIER_ANGLE_RAD`| `0.35` | Umbral angular en radianes ($\approx 20^\circ$) para el filtro de consistencia *RANSAC-lite* del FOE. |
| `TTC_AGGREGATION_PERCENTILE`| `20` | Percentil espacial de orden utilizado para resumir el TTC de una celda ($P_{20}$). |
| `FLOW_MAX_ROTATION_DEG`| `2.0` | Rotación angular máxima admisible entre cuadros sucesivos antes de declarar flujo degradado. |

### 5. Umbrales del `ObstacleField`
| Variable | Valor Nominal | Justificación y Efecto |
|---|---|---|
| `OBSTACLE_OCCUPANCY_BLOCKED`| `0.35` | Fracción mínima de la celda con TTC $< 2.5\text{ s}$ para declarar bloqueo por ocupación. |
| `OBSTACLE_TTC_BLOCKED_S` | `2.5` | Umbral temporal de TTC (en segundos) por debajo del cual una celda se considera en colisión inminente. |
| `OBSTACLE_MIN_CONFIDENCE` | `0.15` | Piso de píxeles válidos para que una celda participe en la votación. |
| `OBSTACLE_MIN_CONFIDENCE_TTC`| `0.35` | Piso de confianza exigido para que el TTC por sí solo bloquee una celda sin apoyo de ocupación. |

### 6. Grabación de Video y Viewport
| Variable | Valor nominal | Default si ausente | Justificación y efecto |
|---|---|---|---|
| `FLIGHT_RECORD_VIDEO` | `true` | `false` | Habilita la grabación del video de auditoría `.webm` (VP8) por corrida. Desactivar en lotes *headless* elimina la escritura de un frame por ciclo a disco, reduciendo la carga de CPU en ≈ 30 %. |
| `FLIGHT_RECORD_VIEWPORT` | `false` | `false` | Activa el modo *split-screen*: el video resultante tiene doble ancho horizontal, con la cámara del drone a la izquierda y el viewport de Unreal Engine Editor a la derecha. Requiere las dependencias adicionales `mss` y `pywin32`. Si alguna de las dos no está instalada, o la ventana de UE no es visible en pantalla, el panel derecho se rellena con negro y la grabación continúa sin interrupción (degradación silenciosa). Debe desactivarse en corridas *batch* o *headless* donde el editor no está en pantalla. |
| `VIEWPORT_WINDOW_TITLE` | `"UnrealEditor"` | `"UnrealEditor"` | Subcadena del título de la ventana de Unreal Engine que utiliza `ViewportCapture` para localizar la ventana. La comparación ignora mayúsculas y minúsculas. Se selecciona la primera ventana visible que contenga la subcadena y tenga dimensiones superiores a $100 \times 100\text{ px}$. En UE5 el título suele seguir el patrón `"UnrealEditor – <NombreProyecto>"`. |
| `VIEWPORT_REGION` | *(vacío)* | *(detección automática)* | Coordenadas absolutas de pantalla en píxeles para capturar una región fija, con formato `left,top,right,bottom`. Cuando se define, `ViewportCapture` omite la búsqueda por título y captura exactamente esa región, lo que permite recortar el *chrome* del editor y mostrar únicamente el panel de viewport interior. Ejemplo para un viewport que ocupa la mitad derecha de un monitor de $1920 \times 1080\text{ px}$: `VIEWPORT_REGION=960,0,1920,1080`. Si está vacío, la localización se delega a `VIEWPORT_WINDOW_TITLE`. |

---

## A6.4 Estructura del repositorio y artefactos de corrida (`airsim-runs/`)

Cada vuelo ejecutado en simulación (sea manual o en batch mediante el runner experimental) genera un registro inmutable en el directorio `airsim-runs/<MISSION_ID>-<TIMESTAMP>/`.

```
airsim-runs/
└── CITYSIM_CLEAR-20260907T191226Z/
    ├── CITYSIM_CLEAR-20260907T191226Z.summary.json    <- Métricas consolidadas
    ├── CITYSIM_CLEAR-20260907T191226Z.jsonl           <- Telemetría ciclo a ciclo
    ├── CITYSIM_CLEAR-20260907T191226Z.csv             <- Dataset con Telemetría 
    └── CITYSIM_CLEAR-20260907T191226Z.webmp           <- Video de auditoría con HUD 
```

### A6.4.1 Estructura del archivo de resumen (`.summary.json`)
Contiene los metadatos globales del experimento y los indicadores clave de rendimiento (KPIs):

```json
{
  "mission_id": "CITYSIM_CLEAR",
  "arm": "slm",
  "seed": 1,
  "code_version": "a37b7030",
  "start_time": "2026-09-07T19:12:26.104Z",
  "end_time": "2026-09-07T19:14:18.420Z",
  "duration_s": 112.316,
  "total_cycles": 561,
  "success": true,
  "collision_count": 0,
  "total_distance_m": 312.45,
  "average_speed_mps": 2.78,
  "waypoints_reached": 4,
  "waypoints_total": 4,
  "deliberations_count": 3,
  "deliberations_timeout_count": 0,
  "deadlock_escapes_count": 0,
  "action_distribution": {
    "keep_going": 482,
    "evasive": 61,
    "girar_90": 15,
    "deliberative": 3
  }
}
```

*Nota sobre trazabilidad:* el campo `code_version` almacena el hash SHA-1 de Git del commit exacto sobre el que se ejecutó el vuelo, asegurando trazabilidad matemática estricta con el código fuente.

### A6.4.2 Estructura del log de telemetría ciclo a ciclo (`.jsonl`)
Cada línea del archivo es un registro JSON generado a la frecuencia de 5 Hz por `FlightLogger`, capturando el estado completo del sistema:
* `timestamp`: tiempo Unix en segundos con precisión de microsegundos.
* `cycle`: índice secuencial del bucle.
* `pose`: posición $(X, Y, Z)$ en marco local NED y ángulos de Euler (pitch, roll, yaw).
* `velocity`: velocidades lineales $(v_x, v_y, v_z)$ en m/s.
* `active_waypoint`: índice y distancia euclidiana hacia el waypoint objetivo.
* `obstacle_field`: matriz de TTC, ocupación y confianza por celda sector $\times$ banda.
* `policy_decision`: macro-acción seleccionada, justificación textual y tiempo de cómputo del ciclo.

---

## A6.5 Manifiestos de misión y diseño de escenarios evaluados (Tiers 0, 1 y 2)

Los planes de vuelo se definen como manifiestos JSON ubicados en `airsim-plan/missions/flightplans/`. A continuación se especifican los escenarios representativos empleados en la tesis:

### A6.5.1 Manifiesto Tier 1: Perímetro semiurbano (`townsim_clear.json`)
Evalúa el crucero perimetral sobre el mapa `TownSim` (Downtown West Modular Pack) a una altitud de tránsito de $-30\text{ m}$ (30 m AGL):

```json
{
  "mission_id": "TOWNSIM_CLEAR",
  "summary": "Tier 1: perímetro completo de townsim_calib.png a altitud de tránsito (-30m), sin cruzar ninguna fachada. Rol análogo a minisim_clear para Tier 0: control/smoke-test de crucero largo sin obstáculos deliberativos.",
  "map": "townsim_calib.png",
  "waypoints": [
    { "x": 0.0,    "y": 0.4,   "z": -10.0, "label": "WP_1" },
    { "x": 0.4,    "y": -71.6, "z": -30.0, "label": "WP_2" },
    { "x": -145.2, "y": -70.8, "z": -30.0, "label": "WP_3" },
    { "x": -146.8, "y": 83.6,  "z": -30.0, "label": "WP_4" },
    { "x": 1.2,    "y": 84.8,  "z": -30.0, "label": "WP_5" },
    { "x": 0.0,    "y": 27.2,  "z": 0.0,   "label": "WP_6" }
  ]
}
```

### A6.5.2 Manifiesto Tier 1: Bloqueo frontal forzado (`townsim_calib_cruce_frontal.json`)
Diseñado para forzar una colisión inminente contra un edificio alto con aproximación frontal ortogonal:

```json
{
  "mission_id": "TOWNSIM_CALIB_CRUCE_FRONTAL",
  "summary": "Tier 1: trayectoria ortogonal directa hacia la fachada principal de la manzana central. Obliga al lazo táctico a detectar TTC crítico, disparar giro o evasión de 90° o deliberar con el SLM para rodear la estructura.",
  "map": "townsim_calib.png",
  "waypoints": [
    { "x": 0.0,   "y": 0.0,   "z": -10.0, "label": "WP_START" },
    { "x": -72.0, "y": 0.0,   "z": -10.0, "label": "WP_OBSTACULO_FRONTAL" },
    { "x": -72.0, "y": 80.0,  "z": -10.0, "label": "WP_DESVIO_LATERAL" }
  ]
}
```

### A6.5.3 Manifiesto Tier 2: Cañón urbano denso con ascenso inicial (`citysim_clear.json`)
El mapa `CitySim` presenta rascacielos masivos. Para evitar atravesar estructuras en el despegue, la misión implementa un patrón **climb-first** (ascenso vertical puro en el mismo punto de coordenadas horizontales hasta $-70\text{ m}$ AGL antes de iniciar el crucero horizontal):

```json
{
  "mission_id": "CITYSIM_CLEAR",
  "summary": "Tier 2: perímetro de una manzana del grid regular en citysim_calib.png. Altitud de tránsito -70m (70m AGL) para superar edificios altos de CitySim. Estructura climb-first: WP_2 sube vertical puro antes de mover en horizontal.",
  "map": "citysim_calib.png",
  "waypoints": [
    { "x": 0.0,   "y": 75.0, "z": -10.0, "label": "WP_1" },
    { "x": 130.0, "y": 75.0, "z": -30.0, "label": "WP_2" },
    { "x": 130.0, "y": 0.0,  "z": -50.0, "label": "WP_3" },
    { "x": 0.0,   "y": 0.0,  "z": -10.0, "label": "WP_4" }
  ]
}
```

---

## A6.6 Protocolo de reproducción experimental paso a paso

Para replicar de forma independiente los experimentos documentados en el capítulo 10, siga la secuencia metodológica descrita a continuación:

### Paso 1: Verificación de software y dependencias
1. Sistema operativo: Windows 10/11 (64-bit).
2. Entorno virtual de Python 3.10+:
   ```bash
   cd airsim-loop
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Verificar la disponibilidad del plugin binario de Cosys-AirSim en el proyecto de Unreal Engine 5.5 correspondiente (MiniSim, TownSim o CitySim).

### Paso 2: Instalación del archivo `settings.json`
Copiar el archivo de configuración del Anexo 6 (§A6.1) en el directorio de usuario:
```powershell
Copy-Item "config/settings.json" "$HOME\Documents\AirSim\settings.json" -Force
```

### Paso 3: Inicialización del servidor de modelos (LM Studio)
1. Abrir **LM Studio** (o instancia de `llama.cpp` / Ollama).
2. Cargar el modelo multimodal `Qwen/Qwen2.5-VL-3B-Instruct` cuantizado en `Q4_K_M`.
3. Iniciar el servidor local en el puerto `1234` con compatibilidad de API OpenAI (`http://127.0.0.1:1234/v1`).
4. Verificar la respuesta del servidor mediante:
   ```bash
   curl http://127.0.0.1:1234/v1/models
   ```

### Paso 4: Lanzamiento de la simulación
1. Abrir el proyecto de Unreal Engine deseado (e.g., `TownSim`).
2. Presionar **Play** (PIE) o ejecutar el binario *standalone*.
3. Constatar que en la esquina superior aparezca la notificación de conexión de AirSim en el puerto 41451.

### Paso 5: Ejecución del lote de pruebas (*Runner*)
Para correr una comparación experimental balanceada entre los tres brazos de control sobre un escenario:
```bash
python experiments/runner.py \
    --scenarios ../airsim-plan/missions/flightplans/townsim_clear.json \
    --arms slm fsm reactive \
    --seeds 1 2 3 \
    --out-dir airsim-runs/
```

### Paso 6: Procesamiento de datos y consolidación estadística
Una vez finalizadas las corridas, compilar los resultados y generar las tablas estadísticas comparativas:
```bash
python experiments/analyze.py --runs-dir airsim-runs/
python experiments/analyze_tesis_results.py
```
Los reportes estadísticos consolidados (tests de Mann-Whitney U, frecuencias de acción y tasas de éxito) se volcarán automáticamente en formato Markdown y CSV listos para su contrastación con las tablas de los capítulos 10 y 11.
