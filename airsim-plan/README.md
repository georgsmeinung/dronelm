# airsim-plan — Planificador de Misiones de Estación Terrena

> Traduce instrucciones en lenguaje natural a un **Manifiesto de Misión** estructurado que el SLM táctico en vuelo (en `/airsim-loop`) puede ejecutar.

Este paquete implementa la **mitad terrestre** (estación terrena) de la arquitectura de dos cerebros: se ejecuta **antes** de que el dron despegue, puede tomar de 5 a 10 segundos para pensar y produce un contrato JSON que el cerebro táctico obedece durante el vuelo.

<img src="../informe/2026-0625 Planificacion de Mision.png"/>

El paquete es intencionalmente ligero en cuanto a frameworks: Pydantic para el esquema, el SDK oficial de `openai` para comunicarse con LM Studio/Ollama, y Typer + Rich para la interfaz de línea de comandos (CLI).

## ¿Por qué un planificador independiente?

* El SLM de vuelo (Phi-3 en una Jetson Nano) está limitado por la latencia; no puede permitirse diseñar misiones.
* LM Studio puede servir el mismo Llama-3-8B localmente sin necesidad de configuración adicional.
* El desacoplamiento nos permite validar, persistir y versionar misiones *antes* del despegue.

## Estructura del Proyecto

```
airsim-plan/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── examples/
│   └── perimeter_north_01.json
├── missions/                       # Directorio de salida (un archivo .json por misión compilada)
├── src/airsim_plan/
│   ├── __init__.py
│   ├── config.py                   # Ajustes (respaldados por variables de entorno)
│   ├── llm/
│   │   ├── client.py               # LMStudioClient + PlannerLLM
│   │   └── json_extract.py         # Coerción JSON para la salida del SLM
│   ├── missions/
│   │   ├── manifest.py             # MissionManifest (Pydantic)
│   │   └── planner.py              # Planificador de Misiones (LN -> Manifiesto)
│   ├── bridge/
│   │   ├── airsim_bridge.py        # Enlace con AirSim (armado + despegue)
│   │   └── loop_runner.py          # Inyecta el manifiesto en airsim-loop
│   ├── cli/main.py                 # CLI de Typer (`airsim-plan …`)
│   ├── prompts/
│   │   ├── compiler_system.md      # Prompt del sistema para el Paso 2
│   │   └── tactical_system.md      # Plantilla del prompt del sistema táctico para el Paso 3
│   └── schemas/manifest_schema.json
├── webdcs/                         # Aplicación web FastAPI (Estación Terrena)
│   ├── main.py                     # Entrypoint del servidor FastAPI
│   └── static/                     # Archivos estáticos de la interfaz de usuario (HTML/CSS/JS)
└── tests/                          # pytest, 37 pruebas
```

## Instalación

```bash
cd airsim-plan
python -m pip install -r requirements.txt
# o en modo editable:
python -m pip install -e .
```

Copia `.env.example` a `.env` y ajusta los valores de `LMSTUDIO_*` y `AIRSIM_*`.

## WebDCS — Planificador de Estación Terrena (Interfaz Web)

WebDCS es una aplicación web interactiva basada en FastAPI que sirve como estación terrena de control para planificar y gestionar misiones. Proporciona una interfaz gráfica moderna para interactuar con el planificador sin usar la línea de comandos.

<img src="../informe/2026-0723 New DCS.png"/>

### Características Principales

* **Compilador de Lenguaje Natural**: Permite escribir instrucciones de vuelo en lenguaje natural y utilizar el LLM local para generar automáticamente el Manifiesto de Misión en JSON.
* **Mapa de Ruta Interactivo**: Visualiza la trayectoria planificada y los waypoints (puntos de control) sobre una carta de territorio satelital utilizando un Canvas 2D en coordenadas NED (Norte-Este-Abajo).
* **Editor JSON con Validación en Vivo**: Permite inspeccionar y editar manualmente el código JSON del manifiesto, con indicadores de estado de validación.
* **Estrategias de Integración de Waypoints**: Al recibir nuevos puntos de un plano compilado, permite elegir entre sobrescribir la lista actual, agregar al final (Append) o agregar al principio (Prepend).
* **Gestión de Manifiestos**: Soporte completo para listar, cargar, guardar y eliminar manifiestos de vuelo directamente en el sistema de archivos (`missions/flightplans/`).

### Cómo ejecutar la aplicación web

Para iniciar el servidor de desarrollo de WebDCS, asegúrate de tener instalados `fastapi` y `uvicorn` y ejecuta:

```bash
cd airsim-plan
# Iniciar el servidor FastAPI con recarga automática
python -m uvicorn webdcs.main:app --reload
```

Una vez iniciado, abre tu navegador e ingresa a `http://127.0.0.1:8000`.

## Estructura del Manifiesto de Misión

```json
{
  "mission_id": "PERIMETER_NORTH_01",
  "summary": "Recorre el perimetro norte hasta [50, 100, -10] ignorando personas y vehiculos.",
  "waypoints": [
    {"x": 0,  "y": 50,  "z": -10, "label": "north_edge"},
    {"x": 50, "y": 100, "z": -10, "label": "target"}
  ],
  "rules_of_engagement": {
    "ignore_objects": ["person", "car"],
    "return_to_launch_battery_threshold": 20.0,
    "max_speed_mps": 5.0,
    "min_altitude_m": -10.0
  },
  "tactical_system_prompt": "Eres el navegador tactico …"
}
```

Consulta `src/airsim_plan/schemas/manifest_schema.json` para ver el contrato formal del esquema.

## Pruebas

```bash
python -m pytest -q
```

Las 37 pruebas cubren la validación de esquemas, la extracción de JSON, rutas de error del planificador, la simulación del puente (`dry-run`) y pruebas de humo de la CLI.

## API Programática

```python
from airsim_plan import MissionPlanner

planner = MissionPlanner()
manifest, path = planner.compile_and_save(
    "Revisa el perimetro de la zona industrial norte (X:50, Y:100). "
    "Si ves personas, ignóralas. Si la batería cae por debajo del 20%, "
    "regresa inmediatamente a la base."
)
print(manifest.mission_id, path)
```

Para transferir el control a AirSim + airsim-loop:

```python
from airsim_plan import MissionPlanner
from airsim_plan.bridge import LoopRunner

manifest = MissionPlanner().compile("...")
LoopRunner(manifest).run(takeoff_altitude=-10.0)
```

En el código anterior se hace uso de las clases principales:
* `MissionPlanner` (en `src/airsim_plan/missions/planner.py`): Se encarga de procesar la instrucción en lenguaje natural para compilar un `MissionManifest`.
* `LoopRunner` (en `src/airsim_plan/bridge/loop_runner.py`): Facilita el inicio de la simulación enviando el manifiesto a la ejecución del control táctico.

## CLI (Interfaz de Línea de Comandos)

Después de realizar la instalación con `pip install -e .` obtendrás el punto de entrada `airsim-plan`.

| Comando | Propósito |
| --- | --- |
| `airsim-plan plan -i "…"` | Compila un manifiesto a partir de una instrucción en lenguaje natural y lo guarda en `missions/`. |
| `airsim-plan validate manifest.json` | Valida un manifiesto contra el esquema de Pydantic y el JSON Schema. |
| `airsim-plan show manifest.json` | Muestra el manifiesto formateado y su prompt de sistema táctico. |
| `airsim-plan prompt manifest.json` | Imprime únicamente el prompt del sistema táctico que se inyectará. |
| `airsim-plan takeoff -a -10` | Solo realiza el armado y despegue (sin el bucle de control del SLM). |
| `airsim-plan run -i "…"` | Flujo completo: compila, despega e inicia el control en `airsim-loop`. |
| `airsim-plan run -m manifest.json --dry-run` | Compila y muestra el manifiesto sin iniciar ninguna ejecución. |
| `airsim-plan interactive` | Consola interactiva (REPL) para compilar, editar, guardar y lanzar de forma rápida. |
| `airsim-plan dump-schema -o schema.json` | Exporta el esquema JSON del manifiesto. |

El comando `run` inyecta el manifiesto compilado en `airsim-loop`, ya sea **en el mismo proceso** (cuando el paquete se puede importar como `airsim_loop`) o como un **subproceso** si pasas el argumento `--loop-path /ruta/a/airsim-loop/main.py`.
