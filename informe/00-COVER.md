<img src="Austral-Ingenieria.png" width="50%" alt="Universidad Austral - Facultad de Ingeniería">

# Navegación Autónoma de Drones Urbanos con Visión Monocular y Small Language Model (SLM)

### Tesis para Magister en Ciencia de Datos 

#### Maestría en Ciencia de Datos - 2024/2025

Directores:

-   [DEL ROSSO, Rodrigo](https://www.linkedin.com/in/rodrigodelrosso/)
-   [NUSKE, Ezequiel](https://www.linkedin.com/in/ezequiel-nuske-15137862/)

Alumno:

-   [NICOLAU, Jorge Enrique](https://www.linkedin.com/in/jorgenicolau/)

***

## Resumen

La navegación autónoma de drones en entornos urbanos complejos, como Buenos Aires, enfrenta desafíos significativos debido a su infraestructura densa, obstáculos dinámicos y condiciones de iluminación variables, además de la escasez de conjuntos de datos locales adaptados. Las soluciones existentes a menudo son costosas o no están optimizadas para hardware de bajo costo, lo que limita su implementación práctica en contextos latinoamericanos y la capacidad de cumplir con regulaciones locales como las de la ANAC. Este trabajo busca superar estas limitaciones. Para abordar estos retos, se desarrolla un pipeline para la navegación autónoma de cuadricópteros eVTOL con visión monocular, diseñado específicamente para ser ejecutado en hardware de bajo costo. El sistema propuesto integra un Modelo de Lenguaje Ligero para la planificación de trayectorias previas al vuelo utilizando datos públicos. Para la navegación reactiva en tiempo real, se emplea un Modelo de Aprendizaje Ligero, que procesa las salidas de modelos de visión por computadora ligeros como YOLOv8n (detección de obstáculos), MobileNetV3+U-Net (segmentación semántica) y ORBSLAM2 (SLAM visual) para generar comandos específicos de control. El desarrollo y la validación se realizan en AirSim (basado en Unreal Engine), utilizando un entorno virtual 3D personalizado de Buenos Aires generado a partir del uso de RealityCapture, OpenStreet Maps y Blender, y un dataset mixto que incluye videos públicos de YouTube. Se realiza una evaluación comparativa del SLM frente a Máquinas de Estados Finitos (FSM), estándar en pilotos automáticos, analizando su desempeño en métricas clave como la tasa de éxito de misión, el tiempo de reacción y el consumo computacional en escenarios simulados. Este trabajo contribuye con una solución accesible y escalable para ciudades latinoamericanas, aplicable en áreas como la logística de última milla, la inspección de infraestructura y la gestión de emergencias urbanas. La optimización para hardware de bajo costo como el Jetson Nano y el uso de herramientas abiertas reducen la dependencia de equipos costosos, facilitando la implementación de drones autónomos en la región y proporcionando un análisis novedoso sobre la viabilidad del SLM frente a las FSM en entornos con recursos limitados.

### Palabras claves
Navegación Autónoma de Drones | Entornos Urbanos | Visión Monocular | Hardware de Bajo Costo | Modelo deAprendizaje Ligero (SLM) | Simulación en AirSim
