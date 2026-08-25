# Guía de Configuración del Entorno de Simulación y Ejecución

Esta guía detalla paso a paso la preparación integral del entorno necesario para ejecutar el sistema de navegación autónoma:
1. [Entorno Python con Conda](#1-entorno-python-con-conda)
2. [Configuración de Cosys-AirSim y `settings.json`](#2-configuración-de-cosys-airsim-y-settingsjson)
3. [Entornos de Simulación en Unreal Engine 5.5](#3-entornos-de-simulación-en-unreal-engine-55)
4. [Configuración del Servidor SLM Local (Opcional para brazo SLM)](#4-configuración-del-servidor-slm-local)
5. [Verificación de Conectividad y Ejecución](#5-verificación-de-conectividad-y-ejecución)

---

## 1. Entorno Python con Conda

El proyecto requiere **Python 3.10+** y dependencias específicas para el lazo táctico (`airsim-loop`), la estación de tierra (`airsim-plan` / WebDCS), el servidor MCP (`airsim-mcp`), y las herramientas de evaluación.

### Creación del entorno

Desde la raíz del repositorio, ejecuta:

```bash
# Para arquitecturas x86_64 / Windows / Linux:
conda env create -f environment.yml

# O para arquitecturas ARM64 (ej. macOS Apple Silicon):
# conda env create -f environment-arm64.yml
```

### Activación del entorno

```bash
conda activate airsimenv
```

> [!TIP]
> Si deseas actualizar dependencias existentes en un entorno ya creado:
> ```bash
> conda env update -f environment.yml --prune
> ```

---

## 2. Configuración de Cosys-AirSim y `settings.json`

Cosys-AirSim lee su configuración principal desde el archivo `settings.json` ubicado en el directorio de documentos del usuario.

### Ubicación del archivo de configuración
* **Windows:** `%USERPROFILE%\Documents\AirSim\settings.json` (o `%USERPROFILE%\OneDrive\Documents\AirSim\settings.json`)
* **Linux:** `~/Documents/AirSim/settings.json`

### Vinculación con el repositorio (Recomendado en Windows)
Para mantener versionadas las configuraciones, puedes crear un enlace simbólico / *Junction* desde una terminal de PowerShell como Administrador:

```powershell
New-Item -ItemType Junction -Path ".\airsim-settings" -Value "$env:USERPROFILE\Documents\AirSim"
```

El repositorio incluye plantillas en la carpeta [`airsim-settings/`](airsim-settings/):
- `settings.json`: Configuración activa para el proyecto (cámaras RGB/Depth a 1080x720, modo Multirotor, puerto 41451).
- `settings-default.json`: Configuración estándar de Cosys-AirSim.
- `settings-api-enabled.json`: Perfil mínimo con servidor API habilitado.
- `settings-px4.json`: Configuración para integración con PX4 SITL/HITL.

### Contenido recomendado de `settings.json`

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
  "ClockSpeed": 1.0,
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

> [!IMPORTANT]
> **Topología de red:** AirSim y `airsim-loop` deben ejecutarse en la **misma máquina física** (loopback `127.0.0.1`). La captura de imágenes sobre RPC remoto introduce una latencia inadmisible para el lazo táctico.

---

## 3. Entornos de Simulación en Unreal Engine 5.5

El proyecto utiliza **Unreal Engine 5.5** junto con el plugin **Cosys-AirSim** (fork activo mantenido por Cosys-Lab).

> [!IMPORTANT]
> **Descarga de Entornos de Simulación:**
> Los proyectos y ejecutables precompilados de los entornos de simulación se encuentran disponibles en la carpeta compartida de Google Drive:
> 🔗 **[Entornos de Simulación DroneLM (Google Drive)](https://drive.google.com/drive/folders/1roLmbGFNsHXZyT3NaNzNYMuaBQ8CulX7)**
>
> Desde este enlace se pueden descargar directamente los binarios ejecutables para pruebas rápidas sin necesidad de compilar el proyecto en Unreal Engine, así como los archivos fuentes de los mapas.

### 3.1 Entornos disponibles y evaluados

| Entorno | Propósito / Uso en la Tesis | Estado |
| :--- | :--- | :--- |
| **`CitySim` / `CityParkSim`** | **Entorno principal de validación experimental y benchmark.** Utilizado para ejecutar los escenarios de prueba estándar (`manhattan_a`, `manhattan_b`), la navegación urbana autónoma con evasión de obstáculos y la evaluación comparativa de los brazos FSM, SLM y reactivo. | **Activo / Validación Principal** |
| **`City Sample` (Epic Games / Fab)** | Ciudad densa fotorrealista con tráfico y peatones IA (`Small_City_LVL`). Utilizado para pruebas de estrés visual y realismo extendido. | Activo / Evaluación |
| **`Downtown West Modular Pack`** | Entorno semi-urbano con alto detalle arquitectónico y volumétrico. | Activo / Referencia |
| **`Landscape Mountains` / `Blocks`** | Entornos estándar para calibración cinemática, ajuste de controladores PID y pruebas básicas. | Pruebas unitarias |
| *`Dynamic City Creator`* | Generación procedural de ciudad. | Descartado (incompatibilidad con mallas de colisión en Cosys-AirSim) |

---

### 3.2 Integración del Plugin Cosys-AirSim en un Proyecto de Unreal Engine

#### Método A: Desde binarios precompilados (Recomendado)
1. Descarga el paquete precompilado de **Cosys-AirSim** para Unreal Engine 5.5 desde [Cosys-AirSim Releases](https://github.com/Cosys-Lab/Cosys-AirSim/releases).
2. Dentro de la carpeta de tu proyecto de Unreal (ej. `CityParkSim/`), crea una subcarpeta llamada `Plugins/`.
3. Copia la carpeta `AirSim` descomprimida dentro de `Plugins/` (quedando `MiProyecto/Plugins/AirSim`).
4. Edita el archivo `MiProyecto.uproject` para habilitar el plugin `AirSim` y `ChaosVehiclesPlugin`:

```json
{
  "FileVersion": 3,
  "EngineAssociation": "5.5",
  "Category": "Simulation",
  "Description": "",
  "Plugins": [
    {
      "Name": "AirSim",
      "Enabled": true
    },
    {
      "Name": "ChaosVehiclesPlugin",
      "Enabled": true
    }
  ]
}
```

5. Agrega las directivas de empaquetado y cocinado al final de `Config/DefaultGame.ini`:

```ini
+MapsToCook=(FilePath="/AirSim/AirSimAssets")
+DirectoriesToAlwaysCook=(Path="/AirSim/HUDAssets")
+DirectoriesToAlwaysCook=(Path="/AirSim/Beacons")
+DirectoriesToAlwaysCook=(Path="/AirSim/Blueprints")
+DirectoriesToAlwaysCook=(Path="/AirSim/Models")
+DirectoriesToAlwaysCook=(Path="/AirSim/Sensors")
+DirectoriesToAlwaysCook=(Path="/AirSim/StarterContent")
+DirectoriesToAlwaysCook=(Path="/AirSim/VehicleAdv")
+DirectoriesToAlwaysCook=(Path="/AirSim/Weather")
```

---

### 3.3 Ajustes Críticos de Unreal Engine

Para garantizar la estabilidad física y el correcto funcionamiento del lazo táctico:

1. **GameMode Override:**
   * Abre el nivel en el Editor de Unreal Engine.
   * Ve a **Window -> World Settings**.
   * Establece `GameMode Override` en `AirSimGameMode`.

2. **Evitar ahorro de CPU en segundo plano:**
   * En el Unreal Editor, ve a **Edit -> Editor Preferences**.
   * Busca `CPU`.
   * **Desmarca** la casilla `Use Less CPU when in Background`.
   * *Si no se desmarca, la simulación física se ralentizará drásticamente cada vez que cambies de ventana.*

3. **Corrección de Renderizado de Cámara en UE 5.3+:**
   * En versiones recientes de Unreal Engine, el renderizado de captura de escena puede requerir fijar el nivel de detalle.
   * Crea o edita el archivo `Config/DefaultScalability.ini` en tu proyecto Unreal con:

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

4. **Punto de inicio (`PlayerStart`):**
   * Asegúrate de que exista un actor `PlayerStart` en el nivel y que no esté intersecando el suelo ni colocado excesivamente alto.

---

## 4. Configuración del Servidor SLM Local

El brazo deliberativo (`AGENT_ARM=slm`) interactúa con un modelo de lenguaje local mediante una API compatible con OpenAI (LM Studio u Ollama).

- **LM Studio:** Cargar el modelo deseado (ej. `Qwen/Qwen2.5-Coder-3B-Instruct`, `Phi-3.5-mini-instruct`, `Llama-3.2-3B-Instruct`) e iniciar el Local Server en el puerto `1234`.
- **Ollama:** Iniciar el servicio (`ollama serve`) en el puerto `11434`.

Variables de entorno configurables en `.env`:
```env
LOCAL_LLM_URL=http://localhost:1234/v1
LOCAL_LLM_MODEL=qwen2.5-coder-3b-instruct
```

> [!NOTE]
> A diferencia de AirSim, el servidor SLM **sí puede** residir en otra máquina de la red local (LAN) ya que las consultas deliberativas son asíncronas y no bloquean el lazo de percepción por flujo óptico.

---

## 5. Verificación de Conectividad y Ejecución

Una vez configurados Conda, AirSim y Unreal Engine:

1. **Iniciar el Simulador:** Abre el proyecto en Unreal Engine y presiona **Play** (o ejecuta el binario empaquetado).
2. **Probar el control manual básico:**
   ```bash
   conda activate airsimenv
   python airsim-kc/kc_control.py
   ```
3. **Iniciar la Ground Control Station (WebDCS):**
   ```bash
   cd airsim-plan
   python -m airsim_plan.webdcs.server
   ```
   Accede a `http://localhost:8000`.
4. **Ejecutar el lazo táctico autónomo:**
   ```bash
   cd airsim-loop
   python main.py
   ```