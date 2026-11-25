<div align="center">
  <img src="Austral-Ingenieria.png" width="33%" alt="Universidad Austral - Facultad de Ingeniería">
</div>

# Navegación Autónoma de Drones en Entornos Urbanos Simulados con Visión Monocular: Flujo Óptico, Profundidad Estimada y los Límites de un Modelo de Visión-Lenguaje Pequeño

## Tesis para Magister en Explotación de Datos y Gestión del Conocimiento

### Maestría en Explotación de Datos y Gestión del Conocimiento (MEDGC/2020)
### Cohorte 2024/2025

Directores:

-   [DEL ROSSO, Rodrigo](https://www.linkedin.com/in/rodrigodelrosso/)
-   [NUSKE, Ezequiel](https://www.linkedin.com/in/ezequiel-nuske-15137862/)

Alumno:

-   [NICOLAU, Jorge Enrique](https://jorgenicolau.ar/)

<div class="page-break" style="page-break-before: always; break-before: page;"></div>

## Resumen

La navegación autónoma de cuadricópteros eVTOL en entornos urbanos densos como Buenos Aires enfrenta alta densidad de obstáculos, señal satelital degradada y presupuestos que descartan sensores como LiDAR. Bajo esas restricciones y la normativa local ([ANAC Res. 880/2019](13-REFERENCIAS.md#ref-anac-880-2019)), esta tesis evalúa en simulación un sistema de navegación basado en **visión monocular** y mide si un **modelo de visión-lenguaje pequeño** ejecutado localmente puede actuar como capa de decisión a bordo.

La arquitectura separa la planificación en tierra (estación WebDCS, donde el operador fija los waypoints en un manifiesto inmutable) de un lazo táctico a bordo. La percepción usa **flujo óptico denso derotado** con la telemetría de actitud, un mapa de ocupación (`ObstacleField`) y **Tiempo-a-Colisión (TTC)** estimado por la divergencia del flujo. En escenarios guiados, el TTC discrimina el riesgo de colisión con AUC 0.96–0.97 (0.85–0.93 en aproximación frontal) frente a la profundidad del simulador; en vuelo no se reproduce: el sector central figura bloqueado en el 23 % de los positivos y en el 17 % de los negativos. Un grafo de estados separa un lazo rápido de guiado y evasión, único que comanda velocidades, de un lazo lento asíncrono que juzga qué sectores son volables y emite sub-metas en coordenadas del mundo ancladas a la pose del fotograma, para que la latencia no las invalide. En ese lazo, LFM2.5-VL-1.6B (en la misma GPU que la simulación, con salida `json_schema`) no distinguió sectores libres de bloqueados (AUC 0.53), mientras que la red de profundidad monocular Depth Anything V2 (~25 M de parámetros) sí lo hizo (AUC 0.83–0.87, ~110 ms). La configuración final usa esa red en vuelo y reserva el modelo de lenguaje para planificar la ruta sobre el mapa cenital antes del despegue, la única tarea con señal medible (AUC 0.81).

Los experimentos usan **Cosys-AirSim** sobre **Unreal Engine 5.5** en tres entornos de dificultad creciente (`MiniSim`, `TownSim` con vegetación densa y `CitySim`, basado en *Sample City*), con la dinámica contrastada con telemetría de drones comerciales. En 210 corridas sobre seis escenarios se compara la arquitectura de dos lazos con una Máquina de Estados Finitos (FSM) y con control reactivo, midiendo éxito, tiempo de reacción y SPL. En ruta libre cuesta 1.4–2 veces el tiempo del reactivo sin ganar éxito; donde la ruta directa se tranca, completa la misión gracias a la evasión por flujo y a la salida de bloqueos, que el reactivo no tiene; la ventaja sobre la FSM no queda demostrada por defectos de implementación de esta; y las sub-metas estratégicas, medidas a 20 s, acercan al waypoint tanto como el camino directo. Se documentan además las fallas silenciosas del contrato de datos entre percepción, estado y decisión: las más costosas de diagnosticar y las que ocultaron que el modelo no discriminaba la escena.

### Palabras clave
Navegación Autónoma de Drones | Visión Monocular | Flujo Óptico | Tiempo-a-Colisión (TTC) | Profundidad Monocular Estimada | Modelos de Visión-Lenguaje Pequeños (VLM) | Máquinas de Estados Finitos (FSM) | Control Táctico Híbrido | Simulación en Unreal Engine / Cosys-AirSim | Robótica Urbana de Bajo Costo
