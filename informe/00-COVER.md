<div align="center">
  <img src="Austral-Ingenieria.png" width="33%" alt="Universidad Austral - Facultad de Ingeniería">
</div>

# Navegación Autónoma de Drones Urbanos con Visión Monocular y Small Language Model (SLM)

## Tesis para Magister en Ciencia de Datos 

### Maestría en Ciencia de Datos - 2024/2025

Directores:

-   [DEL ROSSO, Rodrigo](https://www.linkedin.com/in/rodrigodelrosso/)
-   [NUSKE, Ezequiel](https://www.linkedin.com/in/ezequiel-nuske-15137862/)

Alumno:

-   [NICOLAU, Jorge Enrique](https://www.linkedin.com/in/jorgenicolau/)

<div class="page-break" style="page-break-before: always; break-before: page;"></div>

## Resumen

La navegación autónoma de cuadricópteros eVTOL en entornos urbanos densos —como el de Buenos Aires— enfrenta severos desafíos derivados de la alta densidad de obstáculos, la degradación de señales satelitales y las restricciones presupuestarias que descartan sensores de alto costo como LiDAR. Para abordar esta problemática bajo estrictas restricciones de hardware y en conformidad con las normativas locales ([ANAC Res. 880/2019](13-REFERENCIAS.md#ref-anac-880-2019)), esta tesis presenta un sistema integral de planificación previa, percepción monocular y decisión táctica basado exclusivamente en **visión monocular** y **modelos de lenguaje pequeños (SLM)** locales.

La arquitectura desacopla un módulo de planificación deliberativa en tierra (estación de control WebDCS, que compila directivas en lenguaje natural a un manifiesto inmutable de navegación) de un lazo táctico a bordo de alta frecuencia. El módulo de percepción implementa un pipeline ligero de **flujo óptico denso derotado** mediante telemetría de actitud, mapeo de ocupación espacial (`ObstacleField`) y estimación de **Tiempo-a-Colisión (TTC)** a partir de la divergencia del campo de flujo, con un área bajo la curva ROC de 0.96–0.97 frente a etiquetas de referencia tomadas de la profundidad del simulador (0.85–0.93 en la aproximación frontal). En la capa de decisión a bordo, un grafo de estados separa dos lazos: un lazo rápido de guiado y evasión por flujo óptico, único responsable de los comandos de velocidad, y un lazo lento asíncrono que juzga qué sectores del fotograma son volables y traduce la respuesta a sub-metas en coordenadas del mundo ancladas a la pose del fotograma observado, de modo que la latencia no las invalida. El lazo lento se diseñó para un modelo de visión-lenguaje pequeño (LFM2.5-VL-1.6B, ejecutado en la misma GPU que la simulación con decodificación estructurada `json_schema`); medido contra etiquetas de referencia, el modelo no distinguió sectores libres de bloqueados (AUC 0.53), mientras que una red de profundidad monocular de ~25 M de parámetros (Depth Anything V2) sí lo hizo (AUC 0.83–0.87) en ~110 ms. La configuración final usa esa red en el lazo lento y en la resolución de atascos, y reserva el modelo de visión-lenguaje para la planificación de ruta sobre el mapa cenital antes del vuelo, la única tarea en la que aportó una señal medible (AUC 0.81).

El desarrollo y la experimentación se realizan en el simulador **Cosys-AirSim** sobre **Unreal Engine 5.5**, en tres entornos de dificultad creciente (`MiniSim`, `TownSim` con vegetación densa y `CitySim`, basado en *Sample City*), y calibrando la dinámica de vuelo contra conjuntos de datos de telemetría de drones comerciales reales. El trabajo compara esa arquitectura de dos lazos —sin modelo de lenguaje en vuelo— con una Máquina de Estados Finitos (FSM) y con un control puramente reactivo, en 210 corridas sobre seis escenarios, con tasa de éxito de misión, tiempo de reacción y longitud de trayectoria ponderada por éxito (SPL). En ruta libre la arquitectura cuesta entre 1.4 y 2 veces el tiempo del control reactivo sin ganar éxito; donde la ruta directa se tranca, lo que permite completar la misión es la evasión por flujo óptico junto con una salida de los atascos, que el control reactivo no tiene; y la ventaja frente a la FSM no queda demostrada, porque la FSM evaluada tiene defectos de implementación que la desfavorecen. Asimismo, se documentan los modos de falla de la integración del modelo de lenguaje con el lazo de control: fallas silenciosas del contrato de datos entre percepción, estado y decisión, que fueron las más costosas de diagnosticar y que, mientras existieron, ocultaron que el modelo no discriminaba la escena.

### Palabras clave
Navegación Autónoma de Drones | Visión Monocular | Flujo Óptico | Tiempo-a-Colisión (TTC) | Small Language Models (SLM) | Máquinas de Estados Finitos (FSM) | Control Táctico Híbrido | Simulación en Unreal Engine / Cosys-AirSim | Robótica Urbana de Bajo Costo
