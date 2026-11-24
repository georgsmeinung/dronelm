# 5. Arquitectura del lazo táctico

Este capítulo presenta la arquitectura del lazo táctico y las decisiones de diseño que la explican. La especificación de implementación —campos del estado, umbrales, máquinas de estado, gobernador de velocidad, servicio de deliberación y registro— está en el [Anexo 10](anexos/A10-ESPECIFICACION-LAZO-TACTICO.md). NB3 ejecuta el código de vuelo sin AirSim: compila el grafo, dispara cada regla de `navigate` con un estado construido a mano y reproduce las decisiones de una corrida de la v4 desde su registro.

## 5.1 Visión general del lazo

El lazo es un **grafo de decisión por ciclo** (`StateGraph` de LangGraph, [LangChain, 2024](13-REFERENCIAS.md#ref-langchain-2024)) que corre a 5 Hz (ciclo de ≈ 0.2 s) sobre el entorno del capítulo 3, siguiendo los manifiestos de la estación terrena (capítulo 4). El grafo se compila una vez y el bucle externo lo invoca en cada ciclo; es acíclico, y la naturaleza cíclica de la navegación la aporta ese bucle. LangGraph construye los canales del estado a partir del `TypedDict` declarado (`DroneState`, IT.5.2): una clave que un nodo escriba sin estar declarada se **descarta en silencio**, la causa raíz de varios modos de falla del capítulo 9.

### 5.1.1 Topología: cuatro nodos y una arista condicional

<img src="2026-1113 topologia_grafo.png"/>

*Figura 5.1. Topología del grafo compilado. Si AirSim entrega imagen y telemetría, el ciclo pasa por `perception` y `navigate`; si no, la arista condicional lo lleva a `degraded_hover`, que frena sin percepción ni decisión. Los dos caminos terminan en `motor`, el único nodo que actúa.*

`navigate` es un **único nodo** que contiene la política. Los comportamientos concretos (guiado, evasión lateral, giro de 90°, escape vertical, barrido panorámico) son funciones que `navigate` invoca, no nodos del grafo.

<img src="2026-1028 grafo_control.png"/>

*Figura 5.2. Grafo de control en tres capas. Arriba, el bucle externo da una vuelta cada 200 ms y ejecuta un ciclo del grafo; el grafo (centro) es el único que comanda velocidades y `navigate` aplica la primera de sus ocho reglas que se cumple. El lazo lento (derecha) consulta de forma asíncrona a su fuente —la red de profundidad estimada (IT.5.5.4)— y devuelve sub-metas en coordenadas del mundo, que el bucle externo inserta en el `WaypointTracker`. Abajo, una consulta a lo largo de diez ciclos: con la profundidad la sub-meta se aplica en el ciclo siguiente; con el VLM —fuente opcional, no usada en la v4—, cuatro ciclos después y calculada con la pose del pedido.*

### 5.1.2 Dos lazos desacoplados

La organización responde a un hecho medido: la consulta al VLM local tarda ~0.8 s (IT.A16.7), cuatro ciclos del lazo, y la de la red de profundidad ~0.1 s. Una respuesta expresada **en el marco del cuerpo** del dron («el frente está libre») describe un fotograma que ya no existe cuando llega: el dron giró y avanzó, y usarla produce maniobras hacia el lado equivocado (cap. 9, IT.9.8). El sistema separa entonces dos escalas de tiempo. El **lazo rápido** (5 Hz) —guiado, evasión por flujo óptico, reacción a contacto y detección de bloqueo— es el **único** que comanda velocidades. El **lazo lento**, asíncrono, responde una pregunta **válida en el mundo** —por cuál dirección se puede volar hacia la meta— y la traduce, con la pose del fotograma que miró, a una **sub-meta en coordenadas del mundo**, que sigue siendo correcta aunque el dron haya girado mientras la fuente procesaba (IT.5.5).

Es el patrón de las arquitecturas de capas para robots móviles, con un controlador reactivo inmediato y una capa deliberativa a otra escala temporal ([Gat, 1998](13-REFERENCIAS.md#ref-gat-1998)), en la que las capas inferiores conservan siempre la capacidad de actuar ([Brooks, 1986](13-REFERENCIAS.md#ref-brooks-1986)). La particularidad es la interfaz: la capa lenta no emite acciones sino **metas geométricas ancladas**. Tres principios acompañan esta separación:

- **La fuente decide; las reglas no la reescriben.** Una capa de reglas sobre su respuesta haría que la comparación entre brazos midiera esas reglas y no a la fuente (cap. 9, IT.9.8.4); el fallback determinista existe solo ante **falla**.
- **El dron nunca espera al lazo lento en vuelo normal.** Solo el barrido de resolución de bloqueo (IT.5.6) lo mantiene en el lugar.
- **Sin profundidad del simulador.** Ningún componente del lazo lee el canal de profundidad de AirSim (IT.5.8); la profundidad **estimada** desde el RGB (IT.5.5.4) sí se usa, como lo haría una red a bordo de un dron sin sensor de profundidad.

## 5.2 El estado compartido: `DroneState`

`DroneState` es el único canal de comunicación entre nodos y entre el grafo y el bucle externo: datos sensoriales y `ObstacleField` (cap. 6), misión y guiado, decisión del ciclo, canales del lazo lento y estado del barrido (lista de campos en el Anexo 10, IT.A10.2). **Regla de diseño crítica:** todo campo que cruce la frontera entre invocaciones debe estar declarado, porque LangGraph descarta en silencio las claves no declaradas (cap. 9, IT.9.5). Por eso los contadores de bloqueo y el estado de la capa estratégica viven en objetos de proceso (`StallDetector`, `StrategicLayer`), y los tests de integración corren el **grafo compilado** y verifican que las claves de control cruzan la frontera.

## 5.3 La política del brazo `depth2loop`: nodo `navigate`

Durante el despegue vertical (IT.5.4) los tres brazos delegan en el guiado reactivo, porque el flujo óptico de un ascenso puro no sirve para evadir. Después, los brazos de comparación delegan en su propio nodo (`reactive` o `fsm`, IT.5.7). Para el brazo `depth2loop`, `navigate` actualiza las señales de bloqueo, da un paso de la capa estratégica —que nunca comanda velocidades— y aplica una cascada de ocho reglas: **la primera que se cumple decide el ciclo**.

### 5.3.1 Señales de bloqueo

Un objeto `StallDetector` produce cuatro señales: **contacto** detectado por la IMU, **muro ciego** (se ordena avanzar, el dron no avanza y el flujo no ve obstáculo), **detenido** durante 10 ciclos y **sin progreso** hacia el objetivo durante 50 ciclos (10 s). Las dos primeras disparan una evasión inmediata; las dos últimas, la resolución de deadlock. Los umbrales y las tres decisiones que las protegen de falsos positivos están en el Anexo 10 (IT.A10.3).

### 5.3.2 Orden de evaluación

| # | Condición | Acción | Por qué |
|---|---|---|---|
| 1 | Barrido panorámico en curso | Continuar el barrido (IT.5.6) | Un barrido es dueño del dron hasta resolver o caer por sus watchdogs |
| 2 | Detenido o sin progreso | Resolución de deadlock (IT.5.3.4) | Dron trabado o sin acercarse al objetivo |
| 3 | Maniobra comprometida en curso | Continuarla | Anti flip-flop: una maniobra se completa antes de aceptar otra decisión |
| 4 | Contacto o muro ciego | Evasión lateral | Contacto que el flujo óptico no ve |
| 5 | Altitud < 4.5 m (piso óptico) | Guiado reactivo | En vuelo bajo el flujo ve el suelo en movimiento y produce TTC falsos |
| 6 | Waypoint dentro de la banda de seguridad de un techo detectado | `PERDER_ALTURA` | Obstáculo vertical → desplazarse en z |
| 7 | TTC central ≤ 3.2 s, o centro bloqueado con TTC ≤ 4.6 s | Con más del 60 % del campo visual bloqueado: `GIRAR_90` hacia el lado del waypoint **y** consulta inmediata a la capa estratégica; si no: evasión lateral | Peligro frontal: el lazo rápido esquiva; el rodeo lo decide la capa estratégica |
| 7b | Centro bloqueado o TTC mínimo ≤ 4.6 s | Evasión lateral | Ventana de advertencia |
| 8 | — | Guiado reactivo | Camino despejado |

Los umbrales de TTC provienen de la calibración del capítulo 7. El deadlock (2) precede a las demás reglas porque cualquier acción que se repita sin mover al dron taparía al detector de bloqueo indefinidamente (Anexo 11, IT.A11.4.4), y el contacto (4) precede al piso óptico y al TTC porque no depende del sensado visual. Cuál de estos disparadores actúa en vuelo con el código evaluado —contacto, ocupación o TTC— se analiza en el cap. 7 (IT.7.7).

### 5.3.3 Lazo rápido: reacción sin el lazo lento

Las reglas 3, 4, 5, 7 y 8 forman el lazo rápido: actúan en el mismo ciclo, sin esperar al lazo lento. Los otros brazos usan la misma percepción y el mismo traductor a cinemática, pero no las mismas reglas: la FSM evade con sus propios umbrales (IT.5.7) y no tiene la reacción a contacto (regla 4), el descenso bajo un techo (regla 6) ni el `GIRAR_90` (regla 7); `reactive` no evade. La comparación entre brazos mide, por eso, el lazo rápido de cada uno junto con quién decide los rodeos y los deadlocks.

### 5.3.4 Resolución de deadlock

Al entrar en deadlock, el sistema cancela cualquier consulta estratégica en vuelo y, con la estrategia por defecto, ejecuta el barrido panorámico (IT.5.6). Si el barrido no resuelve —estrategia `blind`, ningún rumbo transitable o una falla—, cae al escape determinista: `GANAR_ALTURA` durante 1.6 s, o `GIRAR_90` hacia el waypoint por encima de 30 m. `GANAR_ALTURA` es el escape porque libera al dron de una estructura en la que quedó apoyado; un retroceso tiene avance mediano negativo hacia el waypoint (cap. 9, IT.9.8.4), y por eso el lazo no emite `RETROCEDER`.

## 5.4 Nodos, comportamientos y guiado

Los demás componentes son deliberadamente simples; su especificación está en el Anexo 10.

| Componente | Qué hace | Detalle |
|---|---|---|
| `capture` | Captura imagen y telemetría; si AirSim no responde, marca el ciclo como degradado | IT.A10.4.1 |
| `degraded_hover` | Frena sin percepción ni decisión; no sustituye el dato faltante por uno sintético | IT.A10.4.2 |
| `perception` | Produce el `ObstacleField` (cap. 6) | IT.A10.4.3 |
| Guiado reactivo | Sigue el guiado al waypoint; cerca de un obstáculo limita la guiñada | IT.A10.4.4 |
| Evasión lateral | Elige el lado menos ocupado en cada ciclo | IT.A10.4.5 |
| `GIRAR_90` | Gira 90° hacia el lado del waypoint y adelanta una consulta estratégica | IT.A10.4.6 |
| Mapa de macro-acciones | Fuente única de la cinemática de cada macro-acción para los tres brazos | IT.A10.4.7 |
| `motor` | Único nodo que actúa; su **gobernador de velocidad** limita el avance sin evidencia perceptual o tras un frente bloqueado | IT.A10.5 |
| `WaypointTracker` | En el bucle externo: guiado, progreso, detección de techos e inserción de sub-metas; **despegue vertical** | IT.A10.8 |
| Vigilante de congelamiento | Estado físico idéntico 25 ciclos: dron incrustado en la malla, `physics_locked` | IT.A10.9.2 |

## 5.5 Capa estratégica

La capa estratégica no es un nodo del grafo: `navigate` le da un paso por ciclo. Responde una sola pregunta —qué sectores de una grilla de 3×3 del fotograma frontal están libres— y la puede responder el VLM o la red de profundidad estimada, que devuelven la misma estructura, de modo que el ancla y la traducción a sub-metas son las mismas con cualquiera de las dos. La auditoría y el servicio que la ejecuta en un hilo aparte están en el Anexo 10 (IT.A10.6).

### 5.5.1 Cuándo se consulta

La capa consulta cada 1 s con la profundidad (3 s con el VLM), o de inmediato cuando la regla 7 lo pide, si no hay un barrido en curso y el dron y el waypoint real están lejos del suelo y de la meta. La consulta se hace **también con una sub-meta activa**: una respuesta nueva la reemplaza, de modo que una sub-meta mala se corrige en la consulta siguiente. Las condiciones exactas están en el Anexo 10 (IT.A10.6.5).

### 5.5.2 Qué ve la fuente y qué responde

El pedido lleva un recorte cuadrado del centro del fotograma, dividido en una grilla de 3×3 —columnas de izquierda a derecha, filas arriba, a la altura del dron y abajo— con una marca en la dirección del destino. La respuesta marca cada sector como libre —se puede volar al menos 15 m en esa dirección— o bloqueado (formato en el Anexo 10, IT.A10.6.6; esquema en el cap. 8, IT.8.2).

### 5.5.3 Ancla y sub-metas

Al enviar, la capa guarda un **ancla**: la pose del fotograma, el instante, el waypoint real y la dirección de la meta; cada sector tiene así una **dirección absoluta**. Cuando la respuesta llega, la capa la descarta si es vieja o si cambió el waypoint; si el sector de la meta está libre, no agrega nada y descarta cualquier sub-meta pendiente; si no, fija una sub-meta **desde el ancla** en el sector libre más cercano a la meta, a 15 m como máximo y nunca más lejos que el waypoint real, y la descarta si el dron ya la superó (IT.A10.6.6).

La sub-meta se inserta en el `WaypointTracker` y el guiado normal la persigue. **El dron nunca se detiene a esperar:** como la geometría está anclada al fotograma, girar mientras la fuente procesa no invalida la respuesta. **Una sub-meta es un medio, no una condición:** si el dron entra en el radio de aceptación del waypoint real, lo acepta y descarta las sub-metas pendientes (IT.A10.6.4, IT.A10.8.4).

### 5.5.4 Fuente por defecto: profundidad monocular estimada

La red es Depth Anything V2 Metric Outdoor Small ([Yang et al., 2024](13-REFERENCIAS.md#ref-yang-2024)), de ~25 M de parámetros, que estima la profundidad **en metros** a partir del fotograma RGB (cap. 6, IT.6.12). Un sector es libre si el percentil 5 de su profundidad estimada es ≥ 15 m, el mismo estadístico con que se construyeron las etiquetas del banco de prueba; corre en un hilo aparte, en ~110 ms.

**Por qué la profundidad y no el VLM.** En el banco de prueba a bordo (cap. 11, IT.11.0) la grilla del VLM separa sectores libres de bloqueados con AUC 0.53 —azar— y el p5 de la profundidad estimada, con AUC 0.83–0.87 y exactitud balanceada del 75 %, con errores conservadores. Si la capa con profundidad mejora el vuelo frente a no tenerla no lo responde el diseño: ninguna celda vuela `depth2loop` sin la capa (cap. 11, IT.11.4).

## 5.6 Barrido panorámico en deadlock

Ante un deadlock, el dron gira en el lugar hacia **4 rumbos** (0°, +90°, +180°, +270°), se asienta dos ciclos en cada uno y guarda el fotograma con el **yaw medido** en ese instante. Con los cuatro fotogramas hace una única consulta —con la profundidad, un rumbo es transitable si el p5 del sector central llega a 15 m—, y el código fija una sub-meta en el rumbo elegido con las mismas reglas que la capa estratégica. Sin rumbos transitables, o ante una falla, cae al escape vertical (IT.5.3.4).

Dos decisiones importan para el argumento. **La fuente nunca reporta ángulos**: identifica las imágenes por número y el código usa el yaw medido, lo que evita el error de marco de referencia del capítulo 9 (IT.9.8.1). Y **la salida no repite lo que ya falló**: el código descarta los rumbos cercanos al que falló y a los ya probados en la zona, y la fuente sigue decidiendo qué está libre. La máquina de estados está en el Anexo 10 (IT.A10.7).

## 5.7 Brazo `fsm`

La FSM usa el mismo `ObstacleField`, el mismo vocabulario de macro-acciones y el mismo traductor a cinemática que el brazo `depth2loop`; lo que cambia es quién elige la acción: una máquina de estados (`CRUISE → AVOID_LEFT | AVOID_RIGHT | CLIMB | BRAKE → CRUISE`) con umbrales fijos (tabla en el Anexo 10, IT.A10.4.8). Detecta el bloqueo con el contador de progreso del tracker y, ante un bloqueo, delega en el mismo barrido panorámico, o, con la estrategia `blind`, alterna ascenso y descenso y luego gira con una esquina de desvío propia.

**Dos asimetrías que deben tenerse en cuenta al comparar.** El brazo `fsm` resuelve los deadlocks con el **mismo barrido** que `depth2loop`, de modo que `depth2loop` vs. `fsm:depth` aísla la capa estratégica y la política del lazo rápido, no el barrido; el brazo sin barrido es `fsm:blind` (cap. 10, IT.10.3.3). Y la FSM tiene su propia lógica de bloqueo y escape, con los dos defectos documentados en el cap. 11 (IT.11.5).

## 5.8 Salvaguardas, contratos de diseño y registro

**Exclusión total de profundidad.** Ningún componente del lazo de vuelo lee el canal de profundidad del simulador, del que salen las etiquetas de referencia: darle acceso, aun indirecto, invalidaría la comparación con un sistema monocular (Anexo 11, IT.A11.4.2). Un test estático lo verifica; solo la calibración offline (cap. 7) y la auditoría de distancia mínima (cap. 10, IT.10.6.1), en un hilo aislado del grafo, usan ese canal.

**La fuente sin overrides.** La respuesta de la fuente se traduce a geometría y se aplica; las validaciones que existen (edad, cambio de waypoint, sub-meta superada, deduplicación) descartan respuestas **obsoletas**, no respuestas que una regla considere equivocadas.

**Registro para la auditoría.** Cada ejecución guarda la traza completa del estado ciclo a ciclo, todas las consultas del lazo lento con sus fotogramas y los videos de la corrida, sincronizados en un visor (cap. 4, IT.4.4); los análisis de los capítulos 9 a 11 se derivan de ese registro (detalle en el Anexo 10, IT.A10.9.1).
