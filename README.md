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
   * **Grafo de Decisión por Tick (LangGraph):** Bucle continuo de percepción-decisión-actuación estructurado como un `StateGraph` ejecutado a `LOOP_HZ` (5–10 Hz). Cada ciclo recorre el grafo desde `capture` hasta `motor` y termina en `__end__`; la ciclicidad es aportada por el bucle externo (`main.py`), ya que el grafo se recompila y evalúa desde cero en cada tick sin aristas de retorno internas.
   * **Modo Degradado (`degraded_hover`):** Si la fuente de telemetría o imagen no proviene de AirSim (`source != "airsim"`), el ciclo salta directamente a `degraded_hover` comandando hover preventivo, evitando la inyección de datos sintéticos plausibles y omitiendo percepción y deliberación.
   * **Percepción Monocular por Flujo Óptico (`perception`):** Estimación continua del `ObstacleField` (grilla sector × banda, FOE por mínimos cuadrados ponderados y TTC en segundos) mediante flujo óptico derotado con la actitud inercial — sin red neuronal de detección. Es el único contrato de percepción consumido por las políticas de control.
   * **Enrutador de Política (`policy_router`), seleccionable por brazo (`AGENT_ARM`):**
     * **Crucero Nominal (`keep_going`):** Avance fluido guiado por `WaypointTracker` (con corrección de rumbo por *cross-track error*, zona muerta angular y suavizado EMA).
     * **Evasión Reactiva (`evasive`):** Desvíos suaves de corto plazo con persistencia táctica (*Maneuver Lock*) ante proximidad moderada de obstáculos.
     * **Bypass Determinista (`girar_90`):** Maniobra ortogonal de escape rápido ante bloqueo severo o esquinas de cuadrícula urbana.
     * **Brazo FSM Determinista (`fsm`):** Política de máquina de estados finitos que comparte el mismo espacio de macro-acciones y cinemática para benchmarking.
     * **Deliberación por Excepción (`deliberative`, brazo `slm`):** La consulta al SLM es la excepción, no la regla. Ante bloqueo estructural aplica **freno previo (`FRENAR`)**, consulta asíncrona en hilo desacoplado (`DeliberationService`), watchdog (`SLM_WATCHDOG_MS`), decodificación restringida (`response_format=json_schema`) con parser tolerante como red de seguridad, persistencia de maniobra y fallback determinista.
   * **Navegación Urbana en Cuadrícula (Manhattan Detour & Cornering):** Inyección dinámica de sub-waypoints de esquina (`CORNER_WP`) con alineación ortogonal estricta ($0^\circ, \pm 90^\circ, 180^\circ$), permitiendo rodear manzanas completas sin "efecto imán" ni giros en círculos.
   * **Actuación Motriz (`motor`):** Traducción unificada de la macro-acción a comandos cinemáticos en coordenadas de chasis (Body Frame) con saturación de guiñada y emisión hacia `Cosys-AirSim`.

Para ilustrar el flujo completo:

<img src="informe/2026-0825 Inforgrafia Nuevo Grafo de Control Autonomo.jpg"/>

1. **Ground Station (WebDCS):** Planificación en lenguaje natural y compilación del manifiesto inmutable `MissionManifest.json`.
2. **Captura y Modo Degradado (`capture`):** Adquisición de fotograma y telemetría; desvío inmediato a `degraded_hover` si la fuente no es AirSim.
3. **Percepción Monocular (`perception`):** Generación del contrato `ObstacleField` (ocupación por sector, TTC real y foco de expansión) derotado por la actitud del dron.
4. **Enrutamiento de Política (`policy_router`):**
   - **Camino Despejado:** Ejecución de `keep_going` guiado por `WaypointTracker`.
   - **Proximidad Moderada:** Desvío con `evasive` y persistencia táctica (*Maneuver Lock*).
   - **Bloqueo Severo / Bypass:** Giro ortogonal rápido con `girar_90`.
   - **Brazo de Referencia FSM:** Enrutamiento a la política determinista `fsm`.
   - **Bloqueo Estructural (Brazo SLM):** Freno preventivo (`FRENAR`) y activación asíncrona del nodo `deliberative` bajo watchdog.
5. **Actuación Motriz (`motor`):** Conversión de la macro-acción a comando cinemático en Body Frame sobre `Cosys-AirSim` y cierre de tick hacia `__end__`.

---

## 📂 Estructura del Repositorio

El código del proyecto se organiza en los siguientes componentes:

*   **[`airsim-plan`](./airsim-plan):** Planificador de misiones y Ground Control Station. Contiene el CLI `airsim-plan` y el servidor web **WebDCS** con streaming de video, telemetría e inspector de auditoría SLM.
*   **[`airsim-loop`](./airsim-loop):** Lazo de control táctico autónomo del dron. Implementa el grafo de navegación en LangGraph (Captura, Percepción por Flujo Óptico/TTC, Router Táctico, brazos SLM/FSM/Reactivo y Control de Waypoints), la suite de tests (94 tests) y el framework de experimentación (`experiments/runner.py` y `experiments/analyze.py` para corridas batch N misiones × M escenarios × K semillas comparando los tres brazos; `experiments/collect_ttc_dataset.py` y `experiments/analyze_ttc.py` para calibrar los umbrales de TTC contra el canal depth).
*   **[`airsim-mcp`](./airsim-mcp):** Servidor de Model Context Protocol (MCP) que expone herramientas de telemetría y control de AirSim para interactuar con agentes autónomos externos.
*   **[`airsim-kc`](./airsim-kc):** Scripts de control manual mediante teclado (`kc_control.py`) para pilotaje directo y configuración de segmentación en AirSim.
*   **[`airsim-poc`](./airsim-poc):** Pruebas de concepto iniciales de conexión, telemetría y maniobras básicas.
*   **[`airsim-settings`](./airsim-settings):** Archivos de configuración de AirSim / Cosys-AirSim (`settings.json`, perfiles predefinidos y guía de enlaces).
*   **[`callibration_flight`](./callibration_flight):** Scripts de calibración y notebooks estadísticos que comparan la variabilidad inercial y física del simulador vs. drones reales (DJI).
*   **[`local-llm-eval`](./local-llm-eval):** Suite de benchmarking para evaluar latencias (ms), tokens/segundo y adherencia a esquemas JSON de modelos locales (Phi-3, Qwen 2.5, Gemma 2, Llama 3.2, Liquid LFM).
*   **[`plan_tesis`](./plan_tesis), [`docs`](./docs) e [`informe`](./informe):** Documentación del plan de tesis, objetivos aprobados, changelogs e informes gráficos de resultados.

---

## 🛠️ Stack Tecnológico

*   **Simulación:** Unreal Engine 5.5 + Cosys-AirSim.
*   **Lenguajes y Entorno:** Python 3.10+, Conda / Miniconda.
*   **Visión por Computadora:** OpenCV (flujo óptico denso Farnebäck/DIS) para estimación de `ObstacleField` y TTC; sin red de detección.
*   **Modelos de Lenguaje (SLM):** LM Studio / Ollama (API local compatible con OpenAI) para inferencia local de `qwen2.5`, `phi-3/phi-4`, `llama3.2`, `gemma2`.
*   **Control y Orquestación:** LangGraph (grafo de decisión por tick), Pydantic (validación de esquemas JSON).
*   **Ground Control Station:** FastAPI, WebSockets / SSE, HTML5, Vanilla CSS / JS.
*   **Evaluación y Calibración:** Promptfoo (benchmarking de prompts) y Jupyter Notebooks (SciPy / NumPy / Matplotlib).

---

## 🚀 Instalación y Uso

> [!TIP]
> **Guía detallada de instalación y entornos:** Para instrucciones exhaustivas paso a paso sobre la creación del entorno Conda, la preparación de entornos en Unreal Engine 5.5 (`CitySim` / `CityParkSim`, `City Sample`), la integración del plugin Cosys-AirSim y las opciones avanzadas de `settings.json`, consulta el archivo **[`CREATEENV.md`](CREATEENV.md)**.
>
> 🔗 **Descarga de Entornos Precompilados:** Los binarios y proyectos de simulación (incluyendo **`CitySim`**, el entorno principal de validación experimental y benchmark) se encuentran disponibles en la carpeta compartida de **[Google Drive](https://drive.google.com/drive/folders/1roLmbGFNsHXZyT3NaNzNYMuaBQ8CulX7)**.

### Prerrequisitos
*   GPU NVIDIA con soporte CUDA (ej. RTX 4060 / 5060 o superior) para simulación fluida y para acelerar la inferencia del SLM local.
*   Unreal Engine 5.5 con el entorno de simulación compilado o binario precompilado (ej. **`CitySim` / `CityParkSim`** para validación, o `City Sample`).
*   LM Studio o Ollama sirviendo el SLM en `LOCAL_LLM_URL` (puerto `1234` o `11434`); puede correr en la misma máquina o en otra de la LAN, ya que la consulta es asíncrona y no bloquea el lazo de percepción.

> **Nota de topología (2026-08):** AirSim y `airsim-loop` deben ejecutarse en la **misma máquina** (loopback `127.0.0.1`). Un benchmark de `simGetImages` sobre AirSim remoto en LAN mostró que prácticamente todas las capturas agotaban un timeout de 8s independientemente de la resolución (ver `CHANGELOG.md`, sección F0.0), por lo que solo el servidor del SLM puede quedar en otra máquina de la red.

### 1. Configuración del Entorno Python
Crea y activa el entorno de Conda utilizando el archivo `environment.yml` (o `environment-arm64.yml` para ARM):

```bash
conda env create -f environment.yml
conda activate airsimenv
```

### 2. Preparar el Simulador (Cosys-AirSim en Unreal Engine 5.5)
*   Abre y ejecuta el proyecto de Unreal Engine o el binario precompilado (ej. `CitySim` / `CityParkSim`, disponible en [Google Drive](https://drive.google.com/drive/folders/1roLmbGFNsHXZyT3NaNzNYMuaBQ8CulX7)) en modo **Play**.
*   Asegúrate de que la configuración en `%USERPROFILE%\Documents\AirSim\settings.json` (ver [`airsim-settings/settings.json`](airsim-settings/settings.json)) apunte a la IP y puertos correctos (`41451`) con `SimMode: "Multirotor"`.
*   Detalles de instalación del plugin y ajustes de UE en [CREATEENV.md](CREATEENV.md).

### 3. Lanzar la Ground Control Station (WebDCS)
Inicia la estación de control web:

```bash
cd airsim-plan
# Iniciar el servidor FastAPI con recarga automática
python -m uvicorn webdcs.main:app --reload
```

Abre en tu navegador `http://localhost:8000` para acceder a la interfaz WebDCS, cargar misiones, visualizar el feed de video y telemetría en tiempo real, e interactuar con el inspector de decisiones SLM.

---

## 📊 Evaluación y Calibración del Simulador

En [`callibration_flight`](./callibration_flight) y [`CHANGELOG.md`](CHANGELOG.md) se documentan:
*   **Fidelidad Cinemática:** Calibración de la rigidez inercial en giros de actitud y control de guiñada amortiguado para replicar límites de aeronaves reales.
*   **Robustez de Visión Monocular Pura:** Desacople del Time-To-Collision de la distancia estática, eliminando oscilaciones en zigzag (*slalom*) y adaptando el crucero al ancho de calle.
*   **Calibración de TTC contra el canal depth:** `TTC_EVASION_THRESHOLD`/`TTC_SAFE_THRESHOLD` calibrados con 3735 registros de vuelo real (aproximación frontal, cañón recto, giros de yaw) — AUC 0.96–0.97 para el evento "colisión dentro de τ segundos" pese a correlación puntual baja del valor estimado.
*   **Benchmark de Inferencia Local:** Tiempos de respuesta de modelos compactos de 2B-4B parámetros corriendo en paralelo con el lazo de percepción por flujo óptico.
*   **Comparación de brazos (SLM vs FSM vs Reactivo):** primeros batches end-to-end con `experiments/runner.py` validaron el pipeline de instrumentación (logging, latencias por ciclo, SPL) y expusieron y corrigieron un deadlock real en el mecanismo de escape por altura. La corrida comparativa final de la tesis, con el servidor SLM disponible durante toda la corrida, está pendiente.

---

## 📄 Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE.md).

"Under Construction" Image by <a href="https://pixabay.com/users/josethestoryteller-5100055/?utm_source=link-attribution&utm_medium=referral&utm_campaign=image&utm_content=2408061">Jose R. Cabello</a> from <a href="https://pixabay.com//?utm_source=link-attribution&utm_medium=referral&utm_campaign=image&utm_content=2408061">Pixabay</a>
