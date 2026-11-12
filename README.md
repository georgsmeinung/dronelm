<img src="https://www.austral.edu.ar/wp-content/uploads/2022/10/facultades-horizontales-03.png" width="50%" alt="Universidad Austral - Facultad de Ingeniería">

# Navegación Autónoma de Drones en Entornos Urbanos con Visión Monocular y Small Language Model (SLM)
### Tesis para Magister en Ciencia de Datos | Maestría en Ciencia de Datos 2024/2025

Directores:

-   [DEL ROSSO, Rodrigo](https://www.linkedin.com/in/rodrigodelrosso/)
-   [NUSKE, Ezequiel](https://www.linkedin.com/in/ezequiel-nuske-15137862/)

Alumno:

-   [NICOLAU, Jorge Enrique](https://jorgenicolau.ar)

Este repositorio contiene la implementación del Trabajo Final de Máster en Ingeniería (Ciencia de Datos) de la **Universidad Austral**.

---

#### Proyecto:

[![Website](https://img.shields.io/badge/Project-Website-white.svg)](https://jorgenicolau.ar/dronelm)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Activity](https://img.shields.io/badge/CHANGELOG-2026--1028-teal)](CHANGELOG.md) 
[![Plan](https://img.shields.io/badge/Plan-Aprobado_2025--0829-drakgray)](./plan-tesis/plan-tesis.md)
[![Objetivos](https://img.shields.io/badge/Ver-Objetivos-orange)](./plan-tesis/plan-tesis.md#objetivo-del-trabajo)
[![Infome](https://img.shields.io/badge/Informe-Tesis_MCD-172187)](https://jorgenicolau.ar/dronelm/informe/00-COVER.html)




#### Plataforma:

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![UnrealEngine](https://img.shields.io/badge/Simulator-Unreal_Engine_5.5-green)](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-5-documentation?application_version=5.5)
[![AirSim](https://img.shields.io/badge/Plug_in-Cosys_AirSim-critical)](https://github.com/Cosys-Lab/Cosys-AirSim/)
[![FastAPI](https://img.shields.io/badge/GCS-FastAPI_WebDCS-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

---

## 📋 Resumen del Proyecto

Este proyecto desarrolla y evalúa un sistema de **navegación autónoma para drones** (cuadricópteros eVTOL) en entornos urbanos simulados, con **visión monocular (una cámara RGB)** y modelos que corren localmente, sin LiDAR ni profundidad del simulador en el lazo de vuelo.

La arquitectura separa un **plan en tierra** (manifiesto de misión y plan de ruta) de un **lazo táctico a bordo** de dos escalas de tiempo: un lazo rápido de guiado y evasión por flujo óptico, único que comanda velocidades, y un lazo lento que propone sub-metas en coordenadas del mundo. La evaluación compara esa arquitectura (brazo `slm`) con una máquina de estados finitos (`fsm`) y con un control solo de guiado (`reactive`), en 210 corridas sobre seis escenarios.

El nombre del brazo `slm` viene de las primeras versiones, en las que el lazo lento consultaba a un modelo de visión-lenguaje (LFM2.5-VL-1.6B). El banco de prueba a bordo mostró que el modelo no distingue sectores volables de bloqueados (AUC 0.53), y la misma pregunta pasó a responderla una red de profundidad monocular (Depth Anything V2, AUC 0.83–0.87). **En la configuración evaluada ningún modelo de lenguaje decide en vuelo**: el VLM planifica la ruta sobre el mapa cenital antes del despegue (informe, IT.10.2.1, «Nombres heredados»).

La simulación corre en **Unreal Engine 5.5** con el plugin **Cosys-AirSim**, en tres entornos de dificultad creciente: `MiniSim`, `TownSim` y `CitySim`.

---

## 🏗️ Arquitectura del Sistema

<img src="informe/2026-1028 dos_cerebros.png"/>

1. **En tierra, antes del vuelo (`airsim-plan`).**
   * **WebDCS:** estación de control web (FastAPI) para editar waypoints sobre la carta de navegación y compilar el manifiesto inmutable de la misión.
   * **Plan de ruta con el VLM** (`airsim-loop/src/planning/route_planner.py`): para cada tramo genera rutas candidatas (recta, en L y desvíos paralelos), el VLM clasifica parches del mapa cenital registrado y gana la candidata con mayor probabilidad media de «calle». Se usa en los escenarios con obstrucción.
2. **A bordo, en vuelo (`airsim-loop`).** Un `StateGraph` de LangGraph (`capture` → `perception` → `navigate` → `motor`, con `degraded_hover` si AirSim no responde) que el bucle externo ejecuta a 5 Hz:
   * **Percepción** (`src/perception/flow_ttc.py`): flujo óptico denso (DIS) derotado con la actitud, Foco de Expansión y Tiempo-a-Colisión por celda en una grilla 3×3; el resultado es el `ObstacleField`, único contrato de percepción.
   * **`navigate`** (`src/agents/graph.py`): ocho reglas en orden fijo; la primera que se cumple decide el ciclo (barrido en curso, deadlock, maniobra comprometida, contacto, piso óptico, techo, peligro frontal por TTC, guiado nominal).
   * **Lazo lento** (`src/agents/vlm_strategic.py`, en un hilo aparte): cada 1 s juzga qué sectores del fotograma están libres a 15 m con la profundidad estimada y fija una sub-meta en coordenadas del mundo, anclada a la pose del fotograma; el dron nunca frena a esperarla.
   * **Deadlock** (`src/agents/deep_scan.py`): barrido de 4 rumbos juzgado por la profundidad estimada; sin rumbo libre, escape vertical.
   * **`motor`:** ancla de altitud en `FRENAR`, gobernador de velocidad y comando a Cosys-AirSim.
3. **Después del vuelo (`airsim-runs`).** Cada corrida deja su traza por ciclo (JSONL y CSV), `summary.json`, videos frontal y de seguimiento, la auditoría de distancia mínima y un visor HTML autocontenido. `airsim-loop/experiments/analyze_lotes.py` produce el análisis estadístico de los lotes.

<img src="informe/2026-1028 grafo_control.png"/>

La descripción completa está en el capítulo 5 del informe y en [`airsim-loop/GRAFO-DE-CONTROL.md`](airsim-loop/GRAFO-DE-CONTROL.md).

---

## 📓 Cuadernos de Cálculo (NB1–NB5)

Los cálculos del informe se pueden reproducir en cinco cuadernos de Jupyter, en [`airsim-loop/`](airsim-loop). Corren sin AirSim, Ollama ni GPU, con el entorno `airsimenv` y `airsim-loop/` como directorio de trabajo, sobre los datos guardados en `airsim-runs/`. El informe los cita como `NBk.n` (por ejemplo, NB1.10), del mismo modo que cita sus propias secciones como `IT.x`.

| Cuaderno | Qué detalla | Secciones del informe |
|---|---|---|
| [`NB1_analisis_estadistico_resultados.ipynb`](airsim-loop/NB1_analisis_estadistico_resultados.ipynb) | El análisis estadístico de la corrida v4 paso a paso, con las mismas funciones de `analyze_lotes.py`: filtros de validez, SPL, éxito con IC de Wilson, una comparación desarrollada completa (delta de Cliff, *bootstrap*, permutación exacta, Bonferroni), las 18 comparaciones, H2 y latencias. Verifica que sus tablas coinciden con `analisis_lotes.md`. Agrega la fuente del campo de obstáculos por celda y el sector central frente a la distancia mínima (NB1.11), y la prueba de *inliers* del FOE en los dos sentidos sobre el video frontal (NB1.12). | IT.10.7, IT.11, IT.7.7 |
| [`NB2_auditoria_interactiva_telemetria.ipynb`](airsim-loop/NB2_auditoria_interactiva_telemetria.ipynb) | Una corrida de la v4 por dentro: los archivos que deja, cómo de la traza por ciclo sale cada métrica del `summary.json`, el ritmo del lazo, la traza de decisión, el `ObstacleField` en el tiempo, la capa estratégica, los atascos y el gobernador, la trayectoria sobre el mapa cenital y la misma semilla volada por los cuatro brazos. Es el equivalente en Python del visor HTML. | IT.4.4, IT.10.6, IT.11.6 |
| [`NB3_explicacion_nodos_langgraph.ipynb`](airsim-loop/NB3_explicacion_nodos_langgraph.ipynb) | El grafo de control ejecutando el código de vuelo sin AirSim: topología, `DroneState`, ciclos completos con un cliente simulado de TTC conocido, los cinco pasos del estimador de flujo, las ocho reglas de `navigate` disparadas una por una, la cinemática de cada macro-acción, el motor y un *replay* de `navigate` sobre una corrida real (99 % de las decisiones reproducidas). | IT.5, IT.6 |
| [`NB4_planificacion_vlm.ipynb`](airsim-loop/NB4_planificacion_vlm.ipynb) | Dónde interviene el VLM: el plan de ruta sobre el mapa cenital (candidatas, juicio por parches, *logprobs* → probabilidad de «calle», elección reproducida desde el plan guardado) y la geometría con la que la capa estratégica y el barrido convierten una respuesta en una sub-meta en el mundo. | IT.4.3, IT.5.10, IT.5.12 |
| [`NB5_banco_vlm_decisiones.ipynb`](airsim-loop/NB5_banco_vlm_decisiones.ipynb) | Las decisiones de diseño que salen de mediciones: el banco de prueba del VLM contra etiquetas de referencia, la misma pregunta con profundidad y segmentación, el reconocimiento de parches del mapa, las rutas contra AirSim, el lote piloto de fuentes de la capa estratégica, los umbrales de TTC por Youden y el umbral de ocupación (D2), cada una con su variable de `config/.env`. | IT.7, IT.10.13, IT.11.0 |

Las salidas que exportan (tablas y figuras de la v4, y los cálculos por ciclo que NB1.12 reusa) quedan en `airsim-loop/notebooks/output/`.

---

## 📂 Estructura del Repositorio

*   **[`airsim-plan`](./airsim-plan):** planificador de misiones y estación de control (CLI `airsim-plan` y servidor web **WebDCS**).
*   **[`airsim-loop`](./airsim-loop):** lazo táctico a bordo (grafo de LangGraph, percepción por flujo óptico, capa estratégica, barrido, guiado a waypoint y registro de vuelo), plan de ruta con el VLM, los cuadernos NB1–NB5, la suite de tests (321) y los scripts de experimentación y análisis (`experiments/runner.py`, `experiments/analyze_lotes.py`, `experiments/vlm_bench/`).
*   **[`experiments`](./experiments):** lanzadores de los seis lotes de la corrida v4 (`run_loteN_*.ps1`, `run_lotes.ps1`) y su descripción.
*   **[`config`](./config):** `config/.env`, fuente única de la configuración de vuelo, y los *prompts* del VLM.
*   **[`airsim-mcp`](./airsim-mcp):** servidor de Model Context Protocol con herramientas de telemetría y control de AirSim.
*   **[`airsim-kc`](./airsim-kc):** control manual por teclado y configuración de segmentación.
*   **[`airsim-poc`](./airsim-poc):** pruebas de concepto iniciales de conexión y telemetría.
*   **[`airsim-settings`](./airsim-settings):** configuraciones de Cosys-AirSim (`settings.json`).
*   **[`callibration-flight`](./callibration-flight):** calibración del simulador frente a vuelos reales y los experimentos de calibración del campo de obstáculos (D2, D3).
*   **[`local-llm-eval`](./local-llm-eval):** benchmark de modelos locales (latencia, tokens por segundo, adherencia a esquemas JSON).
*   **[`plan-tesis`](./plan-tesis), [`informe`](./informe) y [`docs`](./docs):** plan de tesis aprobado; capítulos y anexos del informe en Markdown; sitio del proyecto y versión HTML y PDF del informe (`informe/build.ps1`, MkDocs).
*   **`airsim-runs/`** (fuera de git): resultados de las corridas, incluida la corrida productiva v4 en `airsim-runs/produccion/v4/`.

---

## 🛠️ Stack Tecnológico

*   **Simulación:** Unreal Engine 5.5 + Cosys-AirSim.
*   **Entorno:** Python 3.10, Conda (`airsimenv`).
*   **Visión por computadora:** OpenCV (flujo óptico denso DIS) para el `ObstacleField` y el TTC; Depth Anything V2 Metric Outdoor Small (~25 M parámetros, `transformers`) para la profundidad estimada del lazo lento.
*   **Modelo de visión-lenguaje:** LFM2.5-VL-1.6B Q4_K_M en Ollama (`lfm2.5-vl-1.6b:q4km-ctx8k`), en la misma GPU que Unreal, con decodificación restringida por `json_schema`; en la configuración evaluada solo planifica la ruta.
*   **Control y orquestación:** LangGraph, Pydantic.
*   **Estación de control:** FastAPI, HTML5, CSS y JS sin *framework*.
*   **Análisis:** Jupyter, pandas, SciPy, NumPy, Matplotlib y seaborn; Promptfoo para el benchmark de *prompts*.

---

## 🚀 Instalación y Uso

> [!TIP]
> **Guía detallada de instalación y entornos:** Para instrucciones exhaustivas paso a paso sobre la creación del entorno Conda, la preparación de entornos en Unreal Engine 5.5 (`CitySim` / `CityParkSim`, `City Sample`), la integración del plugin Cosys-AirSim y las opciones avanzadas de `settings.json`, consulta el archivo **[`CREATEENV.md`](CREATEENV.md)**.
>
> 🔗 **Descarga de Entornos Precompilados:** Los binarios y proyectos de simulación (incluyendo **`CitySim`**, el entorno principal de validación experimental y benchmark) se encuentran disponibles en la carpeta compartida de **[Google Drive](https://drive.google.com/drive/folders/1roLmbGFNsHXZyT3NaNzNYMuaBQ8CulX7)**.

### Prerrequisitos
*   GPU NVIDIA con soporte CUDA (por ejemplo, RTX 4060 / 5060 o superior) para la simulación, la red de profundidad y el VLM local.
*   Unreal Engine 5.5 con el entorno de simulación compilado o el binario precompilado (`MiniSim`, `TownSim` o `CitySim`).
*   Ollama en `127.0.0.1:11434` con el modelo `lfm2.5-vl-1.6b:q4km-ctx8k`, solo para el plan de ruta (lotes con obstrucción). Corre en la misma máquina y la misma GPU que Unreal.

> **Nota de topología:** AirSim y `airsim-loop` deben ejecutarse en la **misma máquina** (`127.0.0.1`): con AirSim remoto en la LAN, prácticamente todas las capturas de imagen agotaban el *timeout* (ver `CHANGELOG.md`).

### 1. Configuración del Entorno Python
Crea y activa el entorno de Conda utilizando el archivo `environment.yml` (o `environment-arm64.yml` para ARM):

```bash
conda env create -f environment.yml
conda activate airsimenv
```

### 2. Preparar el Simulador (Cosys-AirSim en Unreal Engine 5.5)
*   Abre y ejecuta el proyecto de Unreal Engine o el binario precompilado (ej. `CitySim` o `TownSim`, disponibles en [Google Drive](https://drive.google.com/drive/folders/1roLmbGFNsHXZyT3NaNzNYMuaBQ8CulX7)) en modo **Play**.
*   Asegúrate de que la configuración en `%USERPROFILE%\Documents\AirSim\settings.json` (ver [`airsim-settings/settings.json`](airsim-settings/settings.json)) apunte a la IP y puertos correctos (`41451`) con `SimMode: "Multirotor"`.
*   Detalles de instalación del plugin y ajustes de UE en [CREATEENV.md](CREATEENV.md).

### 3. Lanzar la Ground Control Station (WebDCS)
Inicia la estación de control web:

```bash
cd airsim-plan
# Iniciar el servidor FastAPI con recarga automática
python -m uvicorn webdcs.main:app --reload
```

Abre en tu navegador `http://localhost:8000` para acceder a la interfaz WebDCS y planificar misiones manualmente. La auditoría de cada corrida se hace *post-vuelo*, con el visor HTML que la corrida genera automáticamente.

### 4. Correr los lotes de la corrida v4
Los lanzadores están en [`experiments/`](experiments) (descripción de cada lote en [`experiments/README.md`](experiments/README.md)):

```powershell
cd experiments
.\run_lote3_townsim_ini.ps1 -Pilot    # piloto con la semilla 99
.\run_lote3_townsim_ini.ps1           # lote completo
```

El análisis de los seis lotes se reproduce con `airsim-loop/experiments/analyze_lotes.py` o, paso a paso, en NB1.

---

## 📊 Evaluación y Resultados

*   **Calibración del simulador:** la cinemática de Cosys-AirSim se contrastó con telemetría de drones comerciales reales (`callibration-flight/`, informe IT.3).
*   **Validación del TTC:** contra etiquetas de referencia tomadas de la profundidad del simulador, AUC 0.96–0.97 para el evento «colisión dentro de τ s» (0.85–0.93 en la aproximación frontal); los umbrales de evasión salen del índice de Youden (IT.7, NB5.10). En las escenas de los lotes el campo de obstáculos discrimina poco más que al azar (IT.7.7, NB1.11).
*   **Banco de prueba del VLM a bordo:** ninguna de las ocho preguntas pasa el criterio; la grilla del lazo lento queda en AUC 0.53. La profundidad estimada responde la misma pregunta con AUC 0.83–0.87 (IT.11.0, NB5).
*   **Corrida productiva v4:** seis lotes, uno por escenario, 10 semillas por celda, 210 corridas; análisis con permutación exacta, delta de Cliff y Bonferroni sobre 18 comparaciones (IT.11, NB1). En ruta libre el brazo `slm` cuesta entre 1.4 y 2 veces el tiempo del control reactivo; con obstrucción, lo que permite completar la misión es la evasión por flujo óptico junto con una salida de los atascos; la ventaja de la capa estratégica frente a la FSM no está demostrada, porque la FSM evaluada tiene dos defectos de implementación que la desfavorecen (IT.12).
*   **Auditoría post-corrida:** cada ejecución queda en una carpeta autocontenida con un visor HTML que sincroniza los videos con la traza por ciclo (IT.4.4, NB2).

---

## 📄 Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE.md).

"Under Construction" Image by <a href="https://pixabay.com/users/josethestoryteller-5100055/?utm_source=link-attribution&utm_medium=referral&utm_campaign=image&utm_content=2408061">Jose R. Cabello</a> from <a href="https://pixabay.com//?utm_source=link-attribution&utm_medium=referral&utm_campaign=image&utm_content=2408061">Pixabay</a>
