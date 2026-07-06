<img src="https://www.austral.edu.ar/wp-content/uploads/2022/10/facultades-horizontales-03.png" width="50%" alt="Universidad Austral - Facultad de Ingeniería">

# Navegación Autónoma de Drones en Entornos Urbanos con Visión Monocular y Small Language Model (SLM)
### Tesis para Magister en Ciencia de Datos | Maestría en Ciencia de Datos 2024/2025

Directores:

-   [DEL ROSSO, Rodrigo](https://www.linkedin.com/in/rodrigodelrosso/)
-   [NUSKE, Ezequiel](https://www.linkedin.com/in/ezequiel-nuske-15137862/)

Alumno:

-   [NICOLAU, Jorge Enrique](https://www.linkedin.com/in/jorgenicolau/)

Este repositorio contiene la implementación del Trabajo Final de Máster en Ingeniería (Ciencia de Datos) de la **Universidad Austral**.

#### Proyecto:

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Activity](https://img.shields.io/badge/Log-2026--0706-teal)](CHANGELOG.md) 
[![Plan](https://img.shields.io/badge/Plan-Aprobado_2025--0829-drakgray)](./plan_tesis/plan-tesis.md)
[![Objetivos](https://img.shields.io/badge/Ver-Objetivos-orange)](./plan_tesis/plan-tesis.md#objetivo-del-trabajo)

#### Plataforma:

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![UnrealEngine](https://img.shields.io/badge/Simulator-Unreal_Engine_5.5-green)](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-5-documentation?application_version=5.5)
[![AirSim](https://img.shields.io/badge/Plug_in-Cosys_AirSim-critical)](https://github.com/Cosys-Lab/Cosys-AirSim/)

---

## 📋 Resumen del Proyecto

Este proyecto consiste en el desarrollo y evaluación de un sistema de **navegación autónoma para drones** (cuadricópteros eVTOL) en entornos urbanos simulados mediante **visión monocular** y **Modelos de Lenguaje Pequeños (SLMs)** que corren localmente.

El objetivo central es diseñar un pipeline de dos niveles (lazo de planificación en tierra y lazo táctico en vuelo) y contrastar la toma de decisiones basada en SLMs con lógicas tradicionales (como Máquinas de Estados Finitos - FSM) y control manual, analizando latencias, consumo computacional, robustez ante obstáculos e imprecisiones físicas.

La simulación se ejecuta sobre **Unreal Engine 5.5** utilizando el plugin **Cosys-AirSim**, recreando entornos urbanos reales y sintéticos.

---

## 🏗️ Arquitectura del Sistema

El sistema implementa una arquitectura desacoplada de dos cerebros:

1. **Lazo de Planificación (Ground-Station - `airsim-plan`):** Se ejecuta en tierra antes del despegue. Recibe instrucciones en lenguaje natural y, a través de un LLM local, genera un manifiesto de misión estructurado ([`MissionManifest.json`](./airsim-plan/examples/perimeter_north_01.json)) con waypoints, reglas de empeño y prompts tácticos.
2. **Lazo de Vuelo Táctico (In-Flight - `airsim-loop`):** Es un bucle continuo de baja latencia basado en **LangGraph**. Procesa frames de cámara RGB con **YOLOv8n** para detectar obstáculos y mapear su distancia/posición. Si el camino está despejado, se navega mediante una regla reactiva rápida. Si detecta un obstáculo inminente, el *Gatekeeper* deriva el control al SLM local para decidir maniobras de evasión utilizando decodificación restringida o esquemas JSON estructurados.

Para ilustrar el flujo completo desde las instrucciones iniciales hasta la ejecución en el simulador:

<img src="informe/Infografia README Fondo Blanco.png"/>

1. **Ground Station:** Las *Instrucciones en Lenguaje Natural* son procesadas por `airsim-plan` para compilar el `MissionManifest.json` (Contrato de Vuelo).
2. **Inyección al Lazo Táctico:** El manifiesto se transfiere al bucle autónomo en vuelo (`airsim-loop`).
3. **Percepción y Traducción:** Los sensores capturan el entorno, el módulo de percepción (YOLOv8n) procesa la imagen y el *Traductor Pixeles a Palabras* genera un resumen de la escena.
4. **Enrutamiento (Gatekeeper):** - **Camino Libre:** Activa la *Navegación Reactiva* (regla directa).
   - **Obstáculo Central:** Activa el *Cerebro Deliberativo* (SLM Local) para calcular la evasión.
5. **Actuación:** El *Módulo Motor* recibe las velocidades o comandos JSON y ejecuta el control final sobre el simulador `Cosys-AirSim`.

---

## 📂 Estructura del Repositorio

El código del proyecto se organiza en los siguientes componentes:

*   **[`airsim-plan`](./airsim-plan):** Planificador de misiones en tierra. Contiene el CLI `airsim-plan` para compilar, validar y ejecutar misiones a partir de lenguaje natural.
*   **[`airsim-loop`](./airsim-loop):** Lazo de control autónomo del dron. Implementa el grafo de navegación (Percepción, Gatekeeper, SLM Táctico y ejecución motriz).
*   **[`airsim-mcp`](./airsim-mcp):** Servidor de Model Context Protocol (MCP) que expone herramientas de telemetría y control de AirSim para interactuar con agentes autónomos externos.
*   **[`airsim-kc`](./airsim-kc):** Scripts de control manual mediante teclado (`simple_control.py` y `advanced_control.py`) para volar el dron y configurar segmentación en AirSim.
*   **[`airsim-poc`](./airsim-poc):** Pruebas de concepto iniciales de conexión y telemetría rápida (`my_hello_drone.py`).
*   **[`callibration_flight`](./callibration_flight):** Scripts de automatización de trayectorias (`airsim_commander.py`, `airsim_iterator.py`) y notebooks de análisis estadístico (`telemetry_analysis_*.ipynb`) que comparan la variabilidad física y de actitud (pitch, roll, yaw y velocidad) de vuelos simulados vs. vuelos de drones reales (DJI) para la calibración del simulador.
*   **[`local-llm-eval`](./local-llm-eval):** Suite de evaluación y benchmarking para comparar la velocidad de generación (tokens/segundo), tiempos de carga y precisión estructural de diferentes SLMs locales (Gemma 2, Llama 3.2, Qwen 2.5, Liquid LFM, Phi) mediante `promptfoo` y `ollama-benchmark`.
*   **[`plan_tesis`](./plan_tesis), [`docs`](./docs) e [`informe`](./informe):** Documentación del plan de tesis, objetivos aprobados, bibliografía y borradores del reporte final del master.

---

## 🛠️ Stack Tecnológico

*   **Simulación:** Unreal Engine 5.5 + Cosys-AirSim.
*   **Lenguajes y Entorno:** Python 3.10+, Conda.
*   **Modelos de Visión:** YOLOv8n (Ultralytics) para detección de obstáculos en tiempo real.
*   **Modelos de Lenguaje (SLM):** Ollama / LM Studio (API local compatible con OpenAI) para inferencia de modelos locales (`llama3.2`, `gemma2:2b`, `qwen3.5:4b`, `phi-3/phi-4`, `Liquid LFM`).
*   **Control y Orquestación:** LangGraph (para la estructura del lazo de vuelo) y Pydantic (para validación de esquemas).
*   **Evaluación:** Promptfoo (para prompts y parsing JSON) y Jupyter Notebooks (análisis estadístico de telemetría con SciPy/Matplotlib).

---

## 🚀 Instalación y Uso

### Prerrequisitos
*   GPU NVIDIA con soporte para CUDA (esencial para la simulación y la inferencia ágil de visión/SLM).
*   Unreal Engine 5.5 con el entorno de simulación correspondiente.
*   Ollama o LM Studio corriendo localmente (para servir los SLMs).

### 1. Configuración del Entorno Python
Crea y activa el entorno de Conda utilizando el archivo `environment.yml` provisto en la raíz:

```bash
conda env create -f environment.yml
conda activate airsimenv
```

### 2. Preparar el Simulador (Cosys-AirSim)
*   Descarga el entorno virtual compilado (como `CitySim` desde Google Drive o el entorno ligero de prueba `MiniSim`).
*   Ejecuta el proyecto de Unreal Engine en modo **Play**.
*   Asegúrate de que la configuración de puertos y vehículo en tu archivo `Settings.json` de AirSim coincida con los puertos de tu script (puerto por defecto: `41451`).

### 3. Ejecución del Lazo Autónomo Completo
Para ejecutar una misión completa compilando una instrucción en lenguaje natural e invocando el lazo de vuelo:

1. Configura el archivo `.env` en `airsim-plan` y `airsim-loop` (especificando las URLs del LLM y de la simulación).
2. Ejecuta el planificador:
    ```bash
    cd airsim-plan
    pip install -e .
    airsim-plan run -i "Recorre el perímetro norte a 10 metros de altitud y a velocidad máxima de 5 m/s, esquiva obstáculos"
    ```
    Esto compilará el plan, armará el dron, despegará e iniciará el lazo táctico en `airsim-loop`.

---

## 📊 Evaluación y Calibración del Simulador

Uno de los aportes del proyecto es el análisis empírico de la fidelidad física de la simulación. En [`callibration_flight`](./callibration_flight) se incluyen estudios detallados que comparan:
*   **Variabilidad Inercial:** Evaluaciones estadísticas que prueban la rigidez física de la actitud en el simulador (AirSim tiende a generar variaciones extremas en giros bruscos para mantener la trayectoria exacta del PID) vs. drones reales (restringidos a límites físicos de ±30°).
*   **Ruido de Sensores:** Modelado del ruido ambiental real (viento, estocasticidad) ausente en las trayectorias de simulación.
*   **Benchmarking de SLMs:** Análisis comparativo de rendimiento (Tokens por segundo y latencia de carga) de modelos locales en hardware embebido/local.

---

## 📄 Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE.md).
