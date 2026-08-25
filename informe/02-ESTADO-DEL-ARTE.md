# 2. Estado del arte y trabajos relacionados

## 2.1 Navegación autónoma de UAVs: de la planificación clásica al control adaptativo

Los primeros enfoques de navegación autónoma en entornos urbanos combinan planificación global sobre
datos geográficos con evasión reactiva de obstáculos móviles. Castelli et al. (2016) proponen un
sistema híbrido para vuelo seguro a baja altitud que combina el algoritmo A* con datos GIS y
replanificación dinámica, priorizando rutas sobre techos en lugar de calles para aumentar la
distancia de seguridad frente a objetos en movimiento. Hughes y Engelbrecht (2023) extienden esta
idea a enjambres, con planificación de largo plazo y evasión cooperativa basada en *bounding volume
hierarchies* y diagramas de Voronoi sobre un modelo 3D tipo Manhattan —el mismo tipo de trazado
urbano en cuadrícula que emplean los escenarios de evaluación de este trabajo (`manhattan_a`,
`manhattan_b`; ver capítulo 10—.

Frente a estos enfoques deliberativos, las máquinas de estados finitos (FSM) siguen siendo el
estándar de facto en pilotos automáticos por su predictibilidad y bajo costo computacional: Hu et al.
(2024) las emplean para coordinación cooperativa de enjambres en emergencias, y Hoang et al. (2024)
las utilizan como base de un sistema de recarga autónoma sobre líneas de alta tensión. Su limitación
es estructural: una FSM no interpreta contexto más allá de los umbrales sobre los que fue diseñada.
Ese contraste —predictibilidad y bajo costo de la FSM frente a la promesa de adaptabilidad contextual
de un modelo de lenguaje— es precisamente el eje de la comparación experimental de este trabajo (cap.
10), y es también donde AlMahamid y Grolinger (2022) y Bouhamed et al. (2020) sitúan al aprendizaje
por refuerzo como tercera vía: políticas aprendidas en lugar de reglas explícitas o inferencia de un
modelo de lenguaje.

## 2.2 Percepción monocular para detección y evitación de obstáculos

La adopción de una arquitectura de percepción monocular ligera sin redes neuronales profundas (cap. 6) se fundamenta en una línea de investigación consolidada sobre detección de obstáculos por visión artificial clásica. Badrloo y Varshosaz (2017) revisan el estado del arte de la detección monocular en robótica móvil, mientras que Molineros et al. (2012) y Chen et al. (2016) analizan la estimación de riesgo mediante flujo residual y análisis 3D. 

Por otra parte, técnicas clásicas basadas en Mapeo de Perspectiva Inversa (IPM), como las propuestas por Kaneko et al. (2017) y retomadas por Zhou et al. (2026), asumen la existencia de un plano de suelo dominante en el campo de visión, una hipótesis adecuada para vehículos terrestres o cámaras cenitales pero inaplicable a cuadricópteros con cámara frontal a baja altitud en cañones urbanos, donde el campo visual está dominado por estructuras verticales y fachadas.

En contraste, el uso de flujo óptico denso traslacional constituye una solución físicamente rigurosa y libre de entrenamiento supervisado. Vera-Yanez et al. (2024) desarrollan un detector de obstáculos aéreos basado íntegramente en flujo óptico —morfología, foco de expansión (*focus of expansion*, FOE) y agrupamiento—, demostrando que desacoplar la rotación propia del movimiento traslacional permite aislar los vectores de aproximación generados por objetos en la trayectoria. Este principio físico —la divergencia del campo traslacional como estimador directo del Tiempo-a-Colisión (TTC)— constituye la base matemática del módulo de percepción y estimación de TTC implementado en este trabajo (cap. 6 y 7). Enfoques alternativos basados en aprendizaje profundo monocular (Rill y Faragó, 2021; Shi et al., 2024) logran estimaciones densas de profundidad pero introducen una alta carga computacional y sensibilidad a dominios no vistos, justificando la preferencia por métodos geométricos deterministas en plataformas de bajo costo.

## 2.3 Arquitecturas de control asistidas por modelos de lenguaje

La incorporación de modelos de lenguaje al lazo de control de UAVs se ha vuelto, hacia 2025-2026, un
patrón relativamente estandarizado: un ciclo cerrado en el que el estado del vehículo se traduce a
lenguaje natural, un modelo (grande o pequeño) produce una decisión estructurada, y esa decisión se
ejecuta y se vuelve a observar. Chahine et al. (2023) muestran robustez fuera de distribución con
redes neuronales líquidas como capa de control; Zhu et al. (2024) estudian específicamente hasta qué
punto los modelos de lenguaje entienden el contexto que se les provee, una pregunta directamente
relevante para el capítulo 9 de este trabajo, donde el problema no es la capacidad de razonamiento
del modelo sino la integridad del contexto que efectivamente recibe.

Dos líneas de trabajo son especialmente pertinentes para la ingeniería de decisiones del SLM descripta
en el capítulo 8. Por un lado, la generación de salida estructurada y restringida: Geng et al. (2025)
sistematizan el estado del arte en generación de salidas estructuradas desde modelos de lenguaje —el
problema exacto que resuelve, en este trabajo, la decodificación restringida vía `json_schema` con
parser tolerante como red de contención (cap. 8)—, y Raspanti et al. (2025) muestran que la
decodificación con gramática restringida mejora específicamente el desempeño en tareas de análisis
lógico estructurado. Por otro lado, la simulación de alta fidelidad como banco de pruebas: Shah et al.
(2017) introducen AirSim, el simulador sobre el que se desarrolla y valida este trabajo, y Jansen et
al. (2023) presentan una variante extendida (Cosys-AirSim) para aplicaciones industriales complejas,
evidencia de que AirSim sigue siendo, varios años después, una base activa para este tipo de
investigación.

## 2.4 Posicionamiento de este trabajo

Este trabajo se ubica en la intersección de esas tres líneas —percepción monocular sin redes
neuronales, control por FSM como línea de base, y un SLM con salida restringida como capa de decisión
alternativa— pero con un énfasis distinto al de buena parte de la literatura revisada: en lugar de
proponer una arquitectura novedosa de percepción o de razonamiento, documenta con evidencia medida los
modos de falla específicos de integrar un modelo de lenguaje en un lazo de control real, un tipo de
resultado que —según constata el propio capítulo 9— es poco frecuente en la literatura publicada,
que tiende a reportar arquitecturas que funcionan más que arquitecturas que fallaron de una manera
instructiva y cómo se detectó y corrigió esa falla.
