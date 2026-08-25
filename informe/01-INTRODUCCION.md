# 1. Introducción

## 1.1 Motivación y contexto

La navegación autónoma de drones en entornos urbanos densos —como el de Buenos Aires— enfrenta un
conjunto de restricciones que no aparecen en espacios abiertos: alta densidad de obstáculos fijos y
móviles, degradación de la señal GPS por la altura de los edificios, condiciones de iluminación
variables y, en el contexto latinoamericano en particular, escasez de conjuntos de datos locales y
restricciones de presupuesto que descartan sensores costosos como el LiDAR. Un dron que carezca de
percepción confiable y de una capacidad de decisión robusta representa un riesgo tangible: puede
colisionar, invadir zonas sensibles o interferir con otras operaciones, con consecuencias humanas y
económicas concretas (Samy et al., 2019; Aldao et al., 2022).

Este trabajo se enmarca en esa tensión: cómo dotar a un cuadricóptero eVTOL de navegación autónoma
reactiva usando exclusivamente visión monocular y hardware de bajo costo, cumpliendo además con el
marco regulatorio local (Resolución ANAC 880/2019), sin resignar seguridad ni rigor metodológico. La
motivación original —detallada en el plan de trabajo aprobado (`plan_tesis/plan-tesis.md`)— incluye
aplicaciones de logística de última milla, inspección de infraestructura y gestión de emergencias
urbanas, todas ellas dominadas por el mismo problema técnico de fondo: decidir, en tiempo real y con
percepción limitada, si el camino hacia adelante está despejado.

## 1.2 Objetivos

**Objetivo general.** Desarrollar un sistema de visión por computadora basado en visión monocular
con capacidad de navegación autónoma de cuadricópteros eVTOL, aplicable a logística urbana,
mantenimiento de infraestructura y atención de emergencias en entornos como el de Buenos Aires.

**Objetivos específicos:**

1. Implementar un pipeline reproducible sobre el simulador AirSim (basado en Unreal Engine) que
   permita validar el desempeño del sistema de navegación en condiciones controladas y repetibles.
2. Integrar detección de obstáculos y navegación reactiva a partir de percepción monocular ligera,
   optimizada para hardware de bajo costo, de modo de sostener un caso de negocio viable para
   economías con recursos limitados.
3. Evaluar el rendimiento de un modelo de lenguaje pequeño (SLM) como capa de decisión táctica frente
   a una máquina de estados finitos (FSM) —el estándar de facto en pilotos automáticos—, usando tasa
   de éxito de misión, tiempo de reacción y consumo computacional como métricas de comparación.

## 1.3 Alcance y diseño de la arquitectura

El sistema de navegación propuesto implementa una arquitectura de percepción monocular ligera **sin redes neuronales de detección**, basada en flujo óptico denso derotado mediante telemetría de actitud y estimación física de tiempo-a-colisión (TTC). Esta elección de diseño responde a fundamentos técnicos y computacionales concretos:

1. **Eficiencia y presupuesto de cómputo:** En plataformas robóticas de bajo costo que comparten GPU o CPU con la inferencia de un modelo de lenguaje local, la estimación geométrica por flujo óptico reduce drásticamente la latencia por ciclo frente a detectores de objetos basados en aprendizaje profundo.
2. **Robustez fuera de distribución (OOD):** A diferencia de modelos supervisados dependientes de categorías predefinidas de obstáculos (vehículos, peatones, postes), el cálculo de divergencia del campo de flujo modela directamente el fenómeno físico de aproximación, reaccionando ante cualquier geometría sin importar su textura o clase semántica.
3. **Adecuación a la geometría del vuelo urbano:** Para un cuadricóptero con cámara frontal en cañón urbano, el campo visual está dominado por estructuras verticales y fachadas; el flujo óptico traslacional permite estimar la ocupación espacial (`ObstacleField`) en cuadrantes discretos de forma directa y determinista.

El capítulo 6 desarrolla en detalle los fundamentos matemáticos y la implementación de este módulo de percepción.

## 1.4 El hilo conductor de la tesis

En arquitecturas robóticas híbridas donde un modelo de lenguaje consume descripciones simbólicas o estructuradas del entorno para tomar decisiones de navegación, la integridad del contrato de interfaz entre la percepción y el modelo resulta crítica. La experiencia experimental demuestra que **el fallo más severo en estos sistemas no radica en la capacidad de razonamiento del modelo de lenguaje, sino en la fidelidad y consistencia del contrato de datos que lo alimenta**.

Cuando la capa de percepción o el estado del sistema entrega representaciones desincronizadas, degradadas o vacías, los modelos de lenguaje tienden a generar respuestas sintácticamente válidas y aparentemente razonables a partir de premisas falsas. Dado que el modelo no se interrumpe con excepciones visibles y el vehículo continúa su trayectoria, estas fallas resultan estructuralmente invisibles si solo se observa el comportamiento cinemático superficial.

Este principio —la necesidad de validación formal, auditoría de contratos de datos y salvaguardas deterministas en lazos de control asistidos por SLM— constituye el hilo conductor de este trabajo. El capítulo 9 documenta de manera sistemática los modos de falla estructurales identificados en la integración de estos componentes y las salvaguardas implementadas para mitigarlos, retomándose como conclusión central en el capítulo 12.

## 1.5 Estructura del informe

El capítulo 2 sitúa este trabajo respecto de la literatura sobre navegación autónoma de UAVs,
percepción monocular para detección de obstáculos y arquitecturas de control asistidas por modelos de
lenguaje. El capítulo 3 describe la construcción del entorno de simulación —Unreal Engine 5.5 con
Cosys-AirSim y los entornos urbanos empleados— y su validación estadística frente a telemetría de
vuelos reales. El capítulo 4 documenta la planificación deliberativa en tierra y la estación de control
WebDCS. Los capítulos 5 a 9 documentan la arquitectura del lazo táctico a bordo: el lazo táctico de
control (cap. 5), la percepción monocular sin redes neuronales (cap. 6), la estimación y validación del
TTC (cap. 7), la capa de decisión del SLM (cap. 8) y los modos de falla específicos de lazos de
control híbridos con modelos de lenguaje (cap. 9). El capítulo 10 describe la metodología
experimental —diseño, brazos de comparación y métricas— con la que se evalúa el sistema. Los
capítulos 11 y 12 (resultados comparativos y conclusiones) sintetizan los hallazgos y el trabajo
futuro, complementados por las referencias bibliográficas estructuradas en el capítulo 13.
