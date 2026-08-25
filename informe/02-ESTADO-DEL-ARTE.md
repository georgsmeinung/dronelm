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
`manhattan_b`; ver capítulo 9—.

Frente a estos enfoques deliberativos, las máquinas de estados finitos (FSM) siguen siendo el
estándar de facto en pilotos automáticos por su predictibilidad y bajo costo computacional: Hu et al.
(2024) las emplean para coordinación cooperativa de enjambres en emergencias, y Hoang et al. (2024)
las utilizan como base de un sistema de recarga autónoma sobre líneas de alta tensión. Su limitación
es estructural: una FSM no interpreta contexto más allá de los umbrales sobre los que fue diseñada.
Ese contraste —predictibilidad y bajo costo de la FSM frente a la promesa de adaptabilidad contextual
de un modelo de lenguaje— es precisamente el eje de la comparación experimental de este trabajo (cap.
9), y es también donde AlMahamid y Grolinger (2022) y Bouhamed et al. (2020) sitúan al aprendizaje
por refuerzo como tercera vía: políticas aprendidas en lugar de reglas explícitas o inferencia de un
modelo de lenguaje.

## 2.2 Percepción monocular para detección y evitación de obstáculos

La decisión de este trabajo de prescindir de redes neuronales de detección (cap. 5) se apoya en una
línea de investigación consolidada sobre detección de obstáculos a partir de una única cámara, sin
aprendizaje profundo. Kaneko et al. (2017) proponen un método de detección rápida para robots móviles
monoculares basado en mapeo de perspectiva inversa (IPM) sobre un plano de suelo asumido —la misma
técnica que este trabajo evalúa y descarta en el capítulo 5, por no cumplirse su hipótesis geométrica
de base con cámara frontal en cañón urbano—. Badrloo y Varshosaz (2017) revisan el estado de la
detección de obstáculos por visión monocular en general, mientras que Molineros et al. (2012) y Chen
et al. (2016) abordan variantes del problema con flujo residual y detección 3D respectivamente, en el
dominio de vehículos terrestres.

Más cerca de la técnica finalmente adoptada, Vera-Yanez et al. (2024) desarrollan un detector de
obstáculos aéreos basado íntegramente en flujo óptico —morfología, expansión del foco (*focus of
expansion*, FOE) y agrupamiento— sin depender de datos de entrenamiento, con el argumento explícito de
que el flujo óptico separa el movimiento propio de la cámara del inducido por objetos que se acercan,
sin necesidad de una red entrenada. Es el mismo principio físico —divergencia del campo traslacional
como proxy de tiempo-a-colisión— sobre el que se construye el estimador de TTC de este trabajo (cap.
6). Rill y Faragó (2021) y Shi et al. (2024), en cambio, sí emplean aprendizaje profundo monocular
para evitar colisiones, y Zhou et al. (2026) retoman el IPM pero para un caso de uso distinto
(vehículos terrestres con cámaras *around-view*, no un UAV con cámara frontal), lo que ilustra que la
inadecuación del IPM a este trabajo es específica de la geometría del caso de uso, no del método en
general.

## 2.3 Arquitecturas de control asistidas por modelos de lenguaje

La incorporación de modelos de lenguaje al lazo de control de UAVs se ha vuelto, hacia 2025-2026, un
patrón relativamente estandarizado: un ciclo cerrado en el que el estado del vehículo se traduce a
lenguaje natural, un modelo (grande o pequeño) produce una decisión estructurada, y esa decisión se
ejecuta y se vuelve a observar. Chahine et al. (2023) muestran robustez fuera de distribución con
redes neuronales líquidas como capa de control; Zhu et al. (2024) estudian específicamente hasta qué
punto los modelos de lenguaje entienden el contexto que se les provee, una pregunta directamente
relevante para el capítulo 8 de este trabajo, donde el problema no es la capacidad de razonamiento
del modelo sino la integridad del contexto que efectivamente recibe.

Dos líneas de trabajo son especialmente pertinentes para la ingeniería de decisiones del SLM descripta
en el capítulo 7. Por un lado, la generación de salida estructurada y restringida: Geng et al. (2025)
sistematizan el estado del arte en generación de salidas estructuradas desde modelos de lenguaje —el
problema exacto que resuelve, en este trabajo, la decodificación restringida vía `json_schema` con
parser tolerante como red de contención (cap. 7)—, y Raspanti et al. (2025) muestran que la
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
resultado que —según constata el propio capítulo 8— es poco frecuente en la literatura publicada,
que tiende a reportar arquitecturas que funcionan más que arquitecturas que fallaron de una manera
instructiva y cómo se detectó y corrigió esa falla.
