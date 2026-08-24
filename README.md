<img src="https://www.austral.edu.ar/wp-content/uploads/2022/10/facultades-horizontales-03.png" width="50%" alt="Universidad Austral - Facultad de Ingeniería">

# Navegación Autónoma de Drones en Entornos Urbanos con Visión Monocular y Small Language Model (SLM)
### Tesis para Magister en Ciencia de Datos | Maestría en Ciencia de Datos 2024/2025

Directores:

-   [DEL ROSSO, Rodrigo](https://www.linkedin.com/in/rodrigodelrosso/)
-   [NUSKE, Ezequiel](https://www.linkedin.com/in/ezequiel-nuske-15137862/)

Alumno:

-   [NICOLAU, Jorge Enrique](https://www.linkedin.com/in/jorgenicolau/)

Este repositorio contiene la implementación del Trabajo Final de Máster en Ingeniería (Ciencia de Datos) de la **Universidad Austral**.

---

<img src="informe/josethestoryteller-under-construction-2408061.png" alt="Under Construction" width="15%"/>
<br/>

**Este proyecto es un TRABAJO EN PROGRESO**
<br/>
a la fecha de la última actualización del CHANGELOG. 

---

#### Proyecto:

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Activity](https://img.shields.io/badge/CHANGELOG-2026--0824-teal)](CHANGELOG.md) 
[![Plan](https://img.shields.io/badge/Plan-Aprobado_2025--0829-drakgray)](./plan_tesis/plan-tesis.md)
[![Objetivos](https://img.shields.io/badge/Ver-Objetivos-orange)](./plan_tesis/plan-tesis.md#objetivo-del-trabajo)

#### Plataforma:

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![UnrealEngine](https://img.shields.io/badge/Simulator-Unreal_Engine_5.5-green)](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-5-documentation?application_version=5.5)
[![AirSim](https://img.shields.io/badge/Plug_in-Cosys_AirSim-critical)](https://github.com/Cosys-Lab/Cosys-AirSim/)
[![TensorRT](https://img.shields.io/badge/Inference-NVIDIA_TensorRT_2ms-76B900?logo=nvidia)](https://developer.nvidia.com/tensorrt)
[![FastAPI](https://img.shields.io/badge/GCS-FastAPI_WebDCS-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

---

## 📋 Resumen del Proyecto

Este proyecto consiste en el desarrollo, implementación y evaluación de un sistema de **navegación autónoma para drones** (cuadricópteros eVTOL) en entornos urbanos simulados mediante **visión monocular pura (RGB)** y **Modelos de Lenguaje Pequeños (SLMs)** que se ejecutan localmente.

El objetivo central es diseñar un pipeline desacoplado de dos niveles (lazo de planificación en tierra y lazo táctico en vuelo) y contrastar la toma de decisiones basada en SLMs con lógicas tradicionales (reactivas y deterministas), analizando latencias, consumo computacional, robustez ante obstáculos e imprecisiones físicas en maniobras urbanas.

La simulación se ejecuta sobre **Unreal Engine 5.5** utilizando el plugin **Cosys-AirSim**, recreando entornos urbanos fotorrealistas calle por calle.

---

## 🏗️ Arquitectura del Sistema

El sistema implementa una arquitectura desacoplada de dos cerebros:

1. **Lazo de Planificación y Control en Tierra (Ground Station & WebDCS - `airsim-plan`):**
   * **WebDCS (Ground Control Station Web):** Interfaz web completa basada en FastAPI que permite planificar misiones en lenguaje natural, supervisar el vuelo en vivo con video anotado y telemetría en tiempo real, y auditar el razonamiento del SLM con un panel de inspección interactivo paso a paso.
   * **Compilador de Misiones:** Procesa instrucciones en lenguaje natural mediante LLMs locales/remotos para generar un manifiesto estructurado (`MissionManifest.json`) con waypoints georreferenciados en la cuadrícula urbana y reglas de comportamiento.

2. **Lazo Táctico Autónomo en Vuelo (`airsim-loop`):**
   * **Orquestación con LangGraph:** Bucle continuo de percepción-decisión-actuación de baja latencia estructurado como un grafo de estados (`StateGraph`).
   * **Percepción Monocular con YOLO TensorRT:** Inferencia ultra-rápida ($2\text{ms}$ por frame en GPU NVIDIA) para detección y segmentación semántica de estructuras (`building`, `wall`, `house`), obstáculos dinámicos y mobiliario urbano.
   * **Estimación Geométrica Continua y Time-To-Collision (TTC):** Cálculo de ocupación visual bidimensional ($\text{area\_ratio}$, $\text{width\_ratio}$, $\text{height\_ratio}$) y seguimiento multiobjeto por solapamiento ($\text{IoU}$) y centroides para calcular la tasa de expansión radial (*looming*) $\Delta w/\Delta t$.
   * **Enrutador Táctico Jerárquico:**
     * **Crucero Nominal (`keep_going`):** Avance fluido a velocidad de crucero ($5.0\text{ m/s}$) guiado por el corredor central de las calles mediante `WaypointTracker`.
     * **Evasión Reactiva (`evasive`):** Desvíos suaves con persistencia táctica (*Maneuver Lock*) ante proximidad moderada.
     * **Cerebro Deliberativo SLM (`hover_and_slm`):** Ante un bloqueo frontal masivo (por ejemplo, una manzana en una bocacalle), el dron estabiliza el vuelo y consulta al SLM local para decidir maniobras de escape en cuadrícula urbana.
   * **Navegación Urbana en Cuadrícula (Manhattan Detour & Cornering):** Inyección dinámica de sub-waypoints de esquina (`CORNER_WP`) con alineación ortogonal estricta ($0^\circ, \pm 90^\circ, 180^\circ$), permitiendo rodear manzanas completas sin "efecto imán" ni giros en círculos.

Para ilustrar el flujo completo:

<img src="informe/Infografia README Fondo Blanco.png"/>

1. **Ground Station (WebDCS):** Planificación en lenguaje natural y compilación del `MissionManifest.json`.
2. **Inyección al Lazo Táctico:** Transferencia del manifiesto al bucle autónomo en vuelo (`airsim-loop`).
3. **Percepción Monocular TensorRT:** Inferencia YOLO a $2\text{ms}$ y traducción continua de píxeles a descripción contextual estructurada.
4. **Enrutamiento (Gatekeeper / TTC Router):**
   - **Camino Despejado:** Guiado nominal por corredor hacia waypoints.
   - **Bloqueo Estructural:** Activación del SLM deliberativo para planificar desvíos ortogonales y esquinas de escape.
5. **Actuación Motriz:** Control en coordenadas de chasis (Body Frame) con giros amortiguados y ejecución sobre `Cosys-AirSim`.

---

## 📂 Estructura del Repositorio

El código del proyecto se organiza en los siguientes componentes:

*   **[`airsim-plan`](./airsim-plan):** Planificador de misiones y Ground Control Station. Contiene el CLI `airsim-plan` y el servidor web **WebDCS** con streaming de video, telemetría e inspector de auditoría SLM.
*   **[`airsim-loop`](./airsim-loop):** Lazo de control táctico autónomo del dron. Implementa el grafo de navegación en LangGraph (Captura, YOLO TensorRT, Estimador de TTC, Router Táctico, SLM Deliberativo y Control de Waypoints).
*   **[`airsim-mcp`](./airsim-mcp):** Servidor de Model Context Protocol (MCP) que expone herramientas de telemetría y control de AirSim para interactuar con agentes autónomos externos.
*   **[`airsim-kc`](./airsim-kc):** Scripts de control manual mediante teclado (`kc_control.py`) para pilotaje directo y configuración de segmentación en AirSim.
*   **[`airsim-poc`](./airsim-poc):** Pruebas de concepto iniciales de conexión, telemetría y maniobras básicas.
*   **[`callibration_flight`](./callibration_flight):** Scripts de calibración y notebooks estadísticos que comparan la variabilidad inercial y física del simulador vs. drones reales (DJI).
*   **[`local-llm-eval`](./local-llm-eval):** Suite de benchmarking para evaluar latencias (ms), tokens/segundo y adherencia a esquemas JSON de modelos locales (Phi-3, Qwen 2.5, Gemma 2, Llama 3.2, Liquid LFM).
*   **[`plan_tesis`](./plan_tesis), [`docs`](./docs) e [`informe`](./informe):** Documentación del plan de tesis, objetivos aprobados, changelogs e informes gráficos de resultados.

---

## 🛠️ Stack Tecnológico

*   **Simulación:** Unreal Engine 5.5 + Cosys-AirSim.
*   **Lenguajes y Entorno:** Python 3.10+, Conda / Miniconda.
*   **Visión por Computadora:** YOLOv8 / YOLO26 (Ultralytics) compilados a **NVIDIA TensorRT Engine** para inferencia ultra-rápida ($2\text{ms}$ en GPU RTX).
*   **Modelos de Lenguaje (SLM):** LM Studio / Ollama (API local compatible con OpenAI) para inferencia local de `qwen2.5`, `phi-3/phi-4`, `llama3.2`, `gemma2`.
*   **Control y Orquestación:** LangGraph (grafo de navegación cíclica), Pydantic (validación de esquemas JSON).
*   **Ground Control Station:** FastAPI, WebSockets / SSE, HTML5, Vanilla CSS / JS.
*   **Evaluación y Calibración:** Promptfoo (benchmarking de prompts) y Jupyter Notebooks (SciPy / NumPy / Matplotlib).

---

## 🚀 Instalación y Uso

### Prerrequisitos
*   GPU NVIDIA con soporte CUDA (ej. RTX 4060 / 5060 o superior) para simulación fluida e inferencia simultánea de TensorRT y SLM local.
*   Unreal Engine 5.5 con el entorno de simulación compilado (ej. `CitySim` / `A_CITY`).
*   LM Studio o Ollama corriendo localmente en el puerto `1234` o `11434`.

### 1. Configuración del Entorno Python
Crea y activa el entorno de Conda utilizando el archivo `environment.yml`:

```bash
conda env create -f environment.yml
conda activate airsimenv
```

### 2. Preparar el Simulador (Cosys-AirSim)
*   Abre y ejecuta el proyecto de Unreal Engine en modo **Play**.
*   Asegúrate de que la configuración en `Settings.json` de AirSim apunte a la IP y puertos correctos (`41451`).

### 3. Lanzar la Ground Control Station (WebDCS)
Inicia la estación de control web:

```bash
cd airsim-plan
python -m airsim_plan.webdcs.server
```

Abre en tu navegador `http://localhost:8000` para acceder a la interfaz WebDCS, cargar misiones, visualizar el feed de video y telemetría en tiempo real, e interactuar con el inspector de decisiones SLM.

---

## 📊 Evaluación y Calibración del Simulador

En [`callibration_flight`](./callibration_flight) y [`CHANGELOG.md`](CHANGELOG.md) se documentan:
*   **Fidelidad Cinemática:** Calibración de la rigidez inercial en giros de actitud y control de guiñada amortiguado para replicar límites de aeronaves reales.
*   **Robustez de Visión Monocular Pura:** Desacople del Time-To-Collision de la distancia estática, eliminando oscilaciones en zigzag (*slalom*) y adaptando el crucero al ancho de calle.
*   **Benchmark de Inferencia Local:** Tiempos de respuesta de modelos compactos de 2B-4B parámetros corriendo en paralelo con YOLO TensorRT.

---

## 📄 Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE.md).

"Under Construction" Image by <a href="https://pixabay.com/users/josethestoryteller-5100055/?utm_source=link-attribution&utm_medium=referral&utm_campaign=image&utm_content=2408061">Jose R. Cabello</a> from <a href="https://pixabay.com//?utm_source=link-attribution&utm_medium=referral&utm_campaign=image&utm_content=2408061">Pixabay</a>
