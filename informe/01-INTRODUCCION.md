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

## 1.3 Alcance y desvíos respecto del plan aprobado

El plan de trabajo aprobado (`plan_tesis/plan-tesis.md`) describía una arquitectura de percepción
basada en tres redes neuronales especializadas: YOLOv8n para detección de obstáculos, MobileNetV3 +
U-Net para segmentación semántica de zonas de aterrizaje, y ORB-SLAM2 para SLAM visual. Durante la
implementación, esa arquitectura fue reemplazada por una de percepción monocular **sin redes
neuronales de detección**, basada en flujo óptico y estimación de tiempo-a-colisión (TTC). El
capítulo 5 desarrolla en detalle esta decisión de diseño; vale adelantar aquí el porqué, porque
determina buena parte del resto del trabajo.

El motivo del cambio no fue exploratorio sino correctivo: durante el desarrollo se constató que el
retiro del detector YOLO —hecho por razones de costo computacional— había dejado el campo
`detected_obstacles` permanentemente vacío, mientras el resto del sistema (enrutador de decisiones,
mecanismo de respaldo determinista, generación del prompt del modelo de lenguaje) seguía escrito
como si ese campo llevara información real. El sistema volaba y el modelo de lenguaje seguía
respondiendo con normalidad, pero ambos lo hacían sobre una percepción que afirmaba sistemáticamente
"despejado". Reparar ese contrato de percepción exigió reconstruirlo desde cero, y la reconstrucción
—descrita en el capítulo 5— se apoyó en flujo óptico derotado y TTC en lugar de volver a introducir
una red de detección. Un segmentador basado en mapeo de perspectiva inversa (IPM), evaluado como
posible reemplazo de la segmentación semántica, fue retirado por una razón distinta: la hipótesis
geométrica de la que depende (un plano de suelo dominante en el campo de visión) no se cumple con una
cámara frontal a ~10 m de altura en un cañón urbano (ver `legacy/README.md`).

Este desvío respecto del plan aprobado no es un detalle a minimizar: es, en sí mismo, un resultado de
diseño defendible, y se documenta como tal en el capítulo 5 en lugar de tratarse como una nota de
implementación.

## 1.4 El hilo conductor de la tesis

A lo largo del desarrollo del proyecto se repitió, en formas distintas, un mismo patrón de falla: un
componente de percepción dejaba de producir información válida, pero ningún consumidor de esa
información —incluido el modelo de lenguaje— lo notaba, porque el sistema seguía produciendo una
salida sintácticamente correcta y plausible. El dron seguía volando; el modelo seguía respondiendo.
El error no estaba en el razonamiento del modelo sino en el contrato de datos que lo alimentaba, y
esa clase de error es estructuralmente invisible si el único punto de observación es el
comportamiento agregado del sistema.

Ese patrón —**en un sistema de control donde un modelo de lenguaje consume descripciones de escena,
el error más caro no está en el modelo sino en la interfaz que lo alimenta, y no se detecta
observando el comportamiento porque el modelo siempre produce una respuesta plausible**— es el hilo
conductor que atraviesa este trabajo y se retoma explícitamente en las conclusiones (capítulo 11). El
capítulo 8 documenta tres instancias concretas y con evidencia medida del mismo patrón, encontradas
en distintas etapas del proyecto: una percepción que afirmaba "despejado" cuando en realidad no había
señal, un historial de fotogramas etiquetado como si existiera cuando en la práctica estaba vacío, y
un canal de ocupación que, por un error de escala en su cálculo, puede afirmar "bloqueado" incluso
ante evidencia inofensiva. En los tres casos, el fallo se detectó leyendo el contrato entre productor
y consumidor de datos, no observando el vuelo.

## 1.5 Estructura del informe

El capítulo 2 sitúa este trabajo respecto de la literatura sobre navegación autónoma de UAVs,
percepción monocular para detección de obstáculos y arquitecturas de control asistidas por modelos de
lenguaje. El capítulo 3 describe la construcción del entorno de simulación —Unreal Engine 5.5 con
Cosys-AirSim y los entornos urbanos empleados— y su validación estadística frente a telemetría de
vuelos reales. Los capítulos 4 a 8 documentan la arquitectura efectivamente implementada: el lazo
táctico de control (cap. 4), la percepción monocular sin redes neuronales (cap. 5), la estimación y
validación del TTC (cap. 6), la capa de decisión del SLM (cap. 7) y los modos de falla específicos de
lazos de control híbridos con modelos de lenguaje (cap. 8). El capítulo 9 describe la metodología
experimental —diseño, brazos de comparación y métricas— con la que se evalúa el sistema. Los
capítulos 10 y 11 (resultados comparativos y conclusiones) dependen de una corrida experimental aún
no completada a la fecha de este escrito, y quedan señalados como tales.
