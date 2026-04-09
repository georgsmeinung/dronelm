<img src="https://www.austral.edu.ar/wp-content/uploads/2022/10/facultades-horizontales-03.png" width="50%" alt="Universidad Austral - Facultad de Ingeniería">

# Navegación Autónoma de Drones Urbanos con Visión Monocular y Small Language Model (SLM)
### Tesis para Magister en Ciencia de Datos | Maestría en Ciencia de Datos 2024/2025

Directores:

-   [DEL ROSSO, Rodrigo](https://www.linkedin.com/in/rodrigodelrosso/)
-   [NUSKE, Ezequiel](https://www.linkedin.com/in/ezequiel-nuske-15137862/)

Alumno:

-   [NICOLAU, Jorge Enrique](https://www.linkedin.com/in/jorgenicolau/)

Este repositorio contiene la implementación del Trabajo Final de Máster en Ingeniería (Ciencia de Datos) de la **Universidad Austral**.

#### Proyecto:

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Activity](https://img.shields.io/badge/Log-2026--0205-teal)](CHANGELOG.md) 
[![Plan](https://img.shields.io/badge/Plan-Aprobado_2025--0829-drakgray)](./plan_tesis/nicolau-plan-aprobado.pdf)

#### Plataforma:

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![UnrealEngine](https://img.shields.io/badge/Simulator-Unreal_Engine_5.5-green)](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-5-documentation?application_version=5.5)
[![AirSim](https://img.shields.io/badge/Plug_in-Cosys_AirSim-critical)](https://github.com/Cosys-Lab/Cosys-AirSim/)

---

## 📋 Resumen del Proyecto

La navegación autónoma de drones en entornos urbanos densos, como la ciudad de Buenos Aires, presenta desafíos críticos debido a la pérdida de señal GPS, obstáculos dinámicos y regulaciones estrictas. Este proyecto desarrolla un pipeline integral para la navegación autónoma de cuadricópteros eVTOL utilizando **visión monocular** y **hardware de bajo costo**.

El sistema integra:
* **Modelos de Lenguaje Ligero (SLM)** para la toma de decisiones reactiva.
* **Visión por Computadora** (YOLOv8n, ORB-SLAM2) para percepción.
* **Simulación Realista** en AirSim con entornos urbanos.

El objetivo principal es comparar el rendimiento de los SLM frente a las tradicionales Máquinas de Estados Finitos (FSM) en tareas de detección, mapeo y aterrizaje.

## 🏗️ Arquitectura del Sistema

El proyecto se divide en dos pipelines principales de procesamiento:

### 1. Pipeline de Digitalización de Entornos (Digital Twin)
Generación de escenarios 3D fotorrealistas de Buenos Aires para la simulación.
1.  **Adquisición:** Extracción de frames de videos públicos (YouTube) de drones en la ciudad.
2.  **Preprocesamiento:** Filtrado y selección de diversidad visual.
3.  **Modelado 3D:** Reconstrucción mediante **RealityCapture** y optimización de malla en **Blender**.
4.  **Despliegue:** Integración de los modelos en **Unreal Engine / AirSim**.

### 2. Pipeline de Navegación Autónoma (SITL)
Ejecución de la lógica de vuelo y percepción.
* **Simulador:** AirSim provee datos sensoriales (Cámara RGB, IMU, GPS).
* **Companion Computer Simulada:** Contenedor **Docker** emulando una **NVIDIA Jetson Nano** (L4T).
* **Stack de Percepción:**
    * *Detección:* YOLOv8n (Obstáculos).
    * *Segmentación:* MobileNetV3 + U-Net (Zonas de aterrizaje).
    * *SLAM:* ORB-SLAM2 (Localización y Mapeo).
* **Control:** Interacción vía **MAVLink** con un controlador de vuelo **PX4** virtual.

## 🛠️ Stack Tecnológico

* **Lenguaje:** Python, C++.
* **Simulación:** Microsoft AirSim, Unreal Engine 5.5.
* **Visión por Computadora:** OpenCV, YOLOv8, ORB-SLAM2.
* **Deep Learning:** PyTorch / TensorFlow (para SLM y segmentación).
* **Infraestructura:** Docker, NVIDIA TensorRT (para optimización en Jetson).
* **Protocolos:** MAVLink, ROS (Robot Operating System).

## 🚀 Instalación y Uso

### Prerrequisitos
* NVIDIA GPU con soporte para CUDA (para correr Unreal Engine y entrenamiento).
* Docker Desktop instalado.
* Unreal Engine (versión compatible con AirSim).

### Configuración del Entorno

1. **Clonar el repositorio:**
```bash
   git clone https://github.com/georgsmeinung/lm-drone.git
   cd lm-drone
```

2. **Iniciar la Simulación (AirSim):**
* Descargar el proyecto `CityParkSim` con el plugin de AirSim compilado. El proyecto es muy pesado para subir a GitHub por lo que está en [Google Drive](https://drive.google.com/drive/folders/1ImTngQAt0gAlrXNOfOYs5csRWQt3IhS_?usp=sharing).
* Lanzar el entorno de virtual desde Unreal Engine editor en modo play.

3. **Probar conexión al Drone mediante:**
* Scripts de navegación autónoma en `./python_poc/my_hello_drone.py` 
* O iniciando el Servidor MCP para control con LLMs (Model Context Protocol) en `./airsim-mcp/mcp_server.py` (ver [README del Servidor MCP](./airsim-mcp/README.md)).

## 📊 Evaluación y Métricas

El sistema se evalúa comparativamente (SLM vs FSM) utilizando las siguientes métricas:

* **Tasa de Éxito de Misión:** Porcentaje de recorridos completados sin colisiones.
* **Tiempo de Reacción:** Latencia entre percepción y comando de control.
* **Consumo Computacional:** Uso de CPU/GPU y memoria (FPS), crucial para validar la viabilidad en Jetson Nano.

## 🤝 Créditos

Este trabajo ha sido desarrollado como parte de la Maestría en Ciencia de Datos de la Universidad Austral.

* **Investigación y Desarrollo:** Jorge Enrique Nicolau
* **Supervisión:** Rodrigo Del Rosso & Ezequiel Omar Nuske

## 📄 Licencia

Este proyecto está bajo la Licencia MIT - ver el archivo [LICENSE.md](LICENSE.md) para más detalles.
