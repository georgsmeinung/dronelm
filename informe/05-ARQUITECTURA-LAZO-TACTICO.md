# 5. Arquitectura del lazo táctico

Este capítulo presenta la arquitectura del lazo táctico y las decisiones de diseño que la explican. La especificación de implementación —campos del estado, umbrales, máquinas de estado, gobernador de velocidad, servicio de deliberación y registro— está en el [Anexo 10](anexos/A10-ESPECIFICACION-LAZO-TACTICO.md). NB3 ejecuta el código de vuelo sin AirSim: compila el grafo, dispara cada regla de `navigate` con un estado construido a mano y reproduce las decisiones de una corrida de la v4 desde su registro.

## 5.1 Visión general del lazo

El lazo se ejecuta sobre el entorno de simulación del capítulo 3 (Unreal Engine 5.5 con Cosys-AirSim), siguiendo los manifiestos compilados por la estación terrena (capítulo 4). Es un **grafo de decisión por ciclo** (`StateGraph` de LangGraph, [LangChain, 2024](13-REFERENCIAS.md#ref-langchain-2024)) que corre a 5 Hz (ciclo de ≈ 0.2 s).

El grafo se compila **una vez** y el bucle externo (`main.py` o `experiments/runner.py`) lo invoca con `graph.invoke()` en cada ciclo. El grafo es acíclico: la naturaleza cíclica de la navegación la aporta el bucle externo. Esta distinción importa porque LangGraph construye los canales del estado a partir del `TypedDict` declarado (`DroneState`, IT.5.2): una clave que un nodo escriba sin estar declarada se **descarta en silencio** al terminar `graph.invoke()`, la causa raíz de varios modos de falla del capítulo 9.

### 5.1.1 Topología: cuatro nodos y una arista condicional

```
capture ──(ok)──────────► perception ──► navigate ──► motor ──► FIN
   │                                                    ▲
   └──(AirSim sin datos)──► degraded_hover ─────────────┘
```

`navigate` es un **único nodo** que contiene la política. Los comportamientos concretos (guiado, evasión lateral, giro de 90°, escape vertical, barrido panorámico) son funciones que `navigate` invoca, no nodos del grafo.

<img src="2026-1028 grafo_control.png"/>

*Figura 5.1. Grafo de control en tres capas. Arriba, el bucle externo da una vuelta cada 200 ms y en el paso ③ ejecuta un ciclo del grafo; el grafo (centro) es el único que comanda velocidades y `navigate` aplica la primera de sus ocho reglas que se cumple. El lazo lento (derecha) consulta de forma asíncrona a su fuente —la red de profundidad estimada (IT.5.5.4)— y devuelve sub-metas en coordenadas del mundo, que el paso ④ inserta en el `WaypointTracker`. Abajo, una consulta a lo largo de diez ciclos: con la profundidad la sub-meta se aplica en el ciclo siguiente; con el VLM, cuatro ciclos después y calculada con la pose del pedido.*

### 5.1.2 Dos lazos desacoplados

La organización responde a un hecho medido: la consulta al VLM local tarda ~0.8 s (IT.8.6), cuatro ciclos del lazo, y la de la red de profundidad ~0.1 s. Una respuesta expresada **en el marco del cuerpo** del dron («el frente está libre») describe un fotograma que ya no existe cuando llega: el dron giró y avanzó, y usarla produce maniobras hacia el lado equivocado (cap. 9, IT.9.8). El sistema separa entonces dos escalas de tiempo. El **lazo rápido** (5 Hz) —guiado, evasión por flujo óptico, reacción a contacto y detección de atasco— es el **único** que comanda velocidades. El **lazo lento**, asíncrono, mira un fotograma y responde una pregunta **válida en el mundo**: por cuál dirección se puede volar hacia la meta; cada pedido guarda la pose del fotograma, y la respuesta se traduce con esa pose a una **sub-meta en coordenadas del mundo**, que sigue siendo correcta aunque el dron haya girado mientras la fuente procesaba (IT.5.5). La fuente por defecto es una red de profundidad monocular estimada desde el mismo RGB (IT.5.5.4).

Es el patrón de las arquitecturas de capas para robots móviles, con un controlador reactivo inmediato y una capa deliberativa a otra escala temporal ([Gat, 1998](13-REFERENCIAS.md#ref-gat-1998)), en la que las capas inferiores conservan siempre la capacidad de actuar ([Brooks, 1986](13-REFERENCIAS.md#ref-brooks-1986)). La particularidad es la interfaz: la capa lenta no emite acciones sino **metas geométricas ancladas**, que la rápida persigue con su guiado normal.

Tres principios de diseño acompañan esta separación:

- **La fuente decide; las reglas no la reescriben.** No hay reglas deterministas que corrijan la respuesta de la fuente: una capa de reglas sobre su decisión haría que la comparación entre brazos midiera esas reglas y no a la fuente (cap. 9, IT.9.8.4). El fallback determinista existe solo ante **falla**: timeout, formato inválido o rotación imposible durante un barrido.
- **El dron nunca espera al lazo lento en vuelo normal.** La capa estratégica no frena al vehículo; solo el barrido de resolución de atasco (IT.5.6) mantiene al dron en el lugar, porque ese es justamente el momento en que avanzar ya no es posible.
- **Sin profundidad del simulador.** Ni el grafo, ni `main.py`, ni `experiments/runner.py` leen el canal de profundidad de AirSim, ni para control ni como métrica (IT.5.8). La profundidad **estimada** desde el RGB de la cámara (IT.5.5.4) sí se usa: equivale a una red a bordo de un dron sin sensor de profundidad.

## 5.2 El estado compartido: `DroneState`

`DroneState` es el único canal de comunicación entre nodos y entre el grafo y el bucle externo. Agrupa los datos sensoriales y el `ObstacleField` (cap. 6), la misión y el guiado que escribe el bucle externo, la decisión del ciclo (macro-acción, comando de velocidad, ruta que lo originó y maniobra comprometida), los canales del lazo lento hacia el bucle externo (la sub-meta a insertar, el registro de consultas) y el estado del barrido de atascos. La lista de campos está en el Anexo 10 (IT.A10.2).

**Regla de diseño crítica.** Todo campo que cruce la frontera entre invocaciones de `graph.invoke()` debe estar declarado en este `TypedDict`: LangGraph no lanza error si un nodo escribe una clave no declarada, la descarta en silencio (cap. 9, IT.9.5). Dos decisiones reducen esa superficie: los contadores de atasco y el estado de la capa estratégica viven en objetos de proceso (`StallDetector`, `StrategicLayer`) y no en el estado, y los tests de integración corren el **grafo compilado** y verifican que las claves de control cruzan la frontera.

## 5.3 La política del brazo `slm`: nodo `navigate`

`navigate` recibe el estado enriquecido por `perception` y produce un comando de velocidad. Durante el despegue vertical (IT.5.4), los tres brazos delegan en el guiado reactivo: el dron sube en el lugar y el flujo óptico de un ascenso puro no es válido para evadir. Fuera del despegue, los brazos de comparación delegan de inmediato en su propio nodo (`reactive` o `fsm`, IT.5.7). Para el brazo `slm`, `navigate` ejecuta dos pasos previos en cada ciclo —actualizar las señales de atasco y dar un paso de la capa estratégica, que nunca comanda velocidades— y luego una cascada de ocho reglas en orden estricto: **la primera que se cumple decide el ciclo**.

### 5.3.1 Señales de atasco

Los contadores de atasco viven en un objeto `StallDetector` que persiste entre invocaciones y produce cuatro señales: **contacto** detectado por la IMU, **muro ciego** (se ordena avanzar, el dron no avanza y el flujo no ve obstáculo), **detenido** durante 10 ciclos y **sin progreso** hacia el objetivo durante 50 ciclos (10 s). Las dos primeras disparan una evasión inmediata; las dos últimas, la resolución de deadlock. Tres decisiones las protegen de falsos positivos observados en corridas de diagnóstico: «detenido» significa «se le ordenó avanzar y no se movió», de modo que girar o subir a propósito no es estar trabado; la velocidad se mide por desplazamiento entre ciclos, porque con el dron apoyado en una estructura la telemetría reporta una velocidad que no existe; y el objetivo se identifica por etiqueta y posición, no por índice, para que una sub-meta nueva no herede la «mejor distancia» de la anterior. Los umbrales y su justificación están en el Anexo 10 (IT.A10.3).

### 5.3.2 Orden de evaluación

| # | Condición | Acción | Por qué |
|---|---|---|---|
| 1 | Barrido panorámico en curso | Continuar el barrido (IT.5.6) | Un barrido es dueño del dron hasta resolver o caer por sus watchdogs; si otra regla tomara el ciclo a mitad del barrido, éste quedaría sin completar |
| 2 | Detenido o sin progreso | Resolución de deadlock (IT.5.3.4) | Dron trabado o sin acercarse al objetivo |
| 3 | Maniobra comprometida en curso | Continuarla | Anti flip-flop: una maniobra se completa antes de aceptar otra decisión |
| 4 | Contacto o muro ciego | Evasión lateral | Contacto que el flujo óptico no ve |
| 5 | Altitud < 4.5 m (piso óptico) | Guiado reactivo | En vuelo bajo el flujo ve el suelo en movimiento y produce TTC falsos |
| 6 | Waypoint dentro de la banda de seguridad de un techo detectado | `PERDER_ALTURA` | Obstáculo vertical → desplazarse en z, simétrico a la evasión en xy |
| 7 | TTC central ≤ 3.2 s, o centro bloqueado con TTC ≤ 4.6 s | Con más del 60 % del campo visual bloqueado: `GIRAR_90` hacia el lado del waypoint **y** consulta inmediata a la capa estratégica; si no: evasión lateral | Peligro frontal: el lazo rápido esquiva; el rodeo lo decide la capa estratégica |
| 7b | Centro bloqueado o TTC mínimo ≤ 4.6 s | Evasión lateral | Ventana de advertencia |
| 8 | — | Guiado reactivo | Camino despejado: guiado nominal |

Los umbrales de TTC provienen de la calibración del capítulo 7. El orden tiene tres justificaciones: el barrido (1) precede a todo porque, una vez iniciado, es dueño del dron hasta resolver; el deadlock (2) precede a toda otra regla porque cualquier acción que se repita sin mover al dron —una maniobra comprometida, una evasión por contacto, un descenso hacia un techo— taparía al detector de atasco indefinidamente (Anexo 11, IT.A11.4.4); y el contacto físico (4) precede al piso óptico y al TTC porque no depende del sensado visual.

### 5.3.3 Lazo rápido: reacción sin el lazo lento

Las reglas 3, 4, 5, 7 y 8 forman el lazo rápido: actúan en el mismo ciclo, sin esperar al lazo lento. Los otros brazos usan la misma percepción y el mismo traductor de macro-acciones a cinemática (IT.5.4), pero no las mismas reglas: la FSM evade con sus propios umbrales (IT.5.7) y no tiene la reacción a contacto (regla 4), el descenso bajo un techo (regla 6) ni el `GIRAR_90` ante un frente bloqueado (regla 7); el brazo `reactive` no evade. La comparación entre brazos mide, por eso, el lazo rápido de cada uno junto con quién decide los rodeos y los deadlocks.

### 5.3.4 Resolución de deadlock

Al entrar en deadlock, el sistema cancela cualquier consulta estratégica en vuelo —el barrido es más reciente y su sub-meta no debe ser pisada por una respuesta más vieja— y, con la estrategia por defecto, ejecuta el barrido panorámico (IT.5.6). Si el barrido no resuelve —estrategia `blind`, ningún rumbo transitable, o falla por watchdog, formato inválido o rotación imposible—, cae al escape determinista: `GANAR_ALTURA` durante 1.6 s, o `GIRAR_90` hacia el waypoint si el dron ya supera los 30 m. Al resolverse, el sistema reinicia los contadores de atasco.

`GANAR_ALTURA` es el escape determinista porque es la maniobra que libera al dron de una estructura en la que quedó apoyado (una cornisa, en `citysim_pilot`); un retroceso, en cambio, tiene un avance mediano negativo hacia el waypoint (cap. 9, IT.9.8.4). Por eso el lazo no emite `RETROCEDER`.

## 5.4 Nodos, comportamientos y guiado

Los demás componentes son deliberadamente simples; su especificación está en el Anexo 10.

| Componente | Qué hace | Detalle |
|---|---|---|
| `capture` | Captura imagen y telemetría; si AirSim no responde, marca el ciclo como degradado | IT.A10.4.1 |
| `degraded_hover` | Ante un ciclo degradado, frena sin percepción ni decisión; no sustituye el dato faltante por uno sintético, que escondería el tipo de fallo silencioso del capítulo 9 | IT.A10.4.2 |
| `perception` | Produce el `ObstacleField` (cap. 6), único objeto de percepción del lazo rápido y la FSM | IT.A10.4.3 |
| Guiado reactivo | Sigue el guiado al waypoint; cerca de un obstáculo limita la guiñada | IT.A10.4.4 |
| Evasión lateral | Elige el lado menos ocupado; lo vuelve a elegir en cada ciclo | IT.A10.4.5 |
| `GIRAR_90` | Con el campo visual bloqueado, gira 90° hacia el lado del waypoint y adelanta una consulta estratégica con el fotograma que ve el muro | IT.A10.4.6 |
| Mapa de macro-acciones | Fuente única de la cinemática de cada macro-acción para los tres brazos | IT.A10.4.7 |
| `motor` | Único nodo que actúa; su **gobernador de velocidad** limita el avance sin evidencia perceptual o tras un frente bloqueado, para que la falta de evidencia no se trate como espacio libre | IT.A10.5 |
| `WaypointTracker` | En el bucle externo: guiado al waypoint, progreso, detección de techos e inserción de sub-metas. El **despegue es vertical**, porque avanzar mientras sube puede llevar al dron contra una estructura más baja que la de crucero | IT.A10.8 |
| Vigilante de congelamiento | Si el estado físico queda idéntico 25 ciclos, el dron está incrustado en la malla: `physics_locked` | IT.A10.9.2 |

## 5.5 Capa estratégica

La capa estratégica no es un nodo del grafo: `navigate` le da un paso por ciclo. Responde una sola pregunta —qué sectores de una grilla de 3×3 del fotograma frontal están libres— y la puede responder el VLM o la red de profundidad estimada, que devuelven la misma estructura, de modo que el ancla y la traducción a sub-metas son las mismas con cualquiera de las dos. Las subsecciones IT.5.5.1–IT.5.5.3 describen la capa con el VLM, porque esa fuente fija la forma de la pregunta y de la respuesta; IT.5.5.4 describe la fuente por defecto y por qué lo es. La auditoría de cada consulta y el servicio que la ejecuta en un hilo aparte están en el Anexo 10 (IT.A10.6).

### 5.5.1 Cuándo se consulta

La capa consulta cada 1 s con la profundidad (3 s con el VLM), o de inmediato cuando la regla 7 lo pide, siempre que no haya un barrido en curso, que el dron esté a 8 m de altura o más, que el waypoint real esté a más de 8 m —más cerca, una sub-meta lo saltearía— y que la meta caiga dentro del recorte que analiza la fuente. La excepción es un dron que lleva 3 s sin acercarse a su objetivo, por ejemplo deslizándose a lo largo de una fachada: entonces se consulta igual, y la respuesta nunca se interpreta como «camino directo libre».

La consulta se hace **también con una sub-meta activa**. La pregunta es siempre sobre el waypoint real, y una respuesta nueva reemplaza a la sub-meta pendiente: así una sub-meta mala se corrige en la consulta siguiente, en lugar de persistir hasta que el detector de atasco la saque (Anexo 11, IT.A11.4.5).

### 5.5.2 Qué ve la fuente y qué responde

El pedido lleva **un fotograma**: un **recorte cuadrado** del centro, dividido en una **grilla de 3×3 por tercios** —columnas A, B, C de izquierda a derecha; filas 1, 2, 3 de arriba abajo, con la fila 2 a la altura del dron— y una marca roja «GOAL» en la dirección del destino. El recorte deja los sectores laterales y los verticales a la misma distancia angular del centro, para que un rodeo por arriba no gane siempre a uno por el costado por la forma del cuadro. Una partición en columnas solo describe el eje horizontal; la grilla separa las dos dimensiones y permite decir que un obstáculo se pasa por arriba.

La respuesta, con decodificación restringida por esquema JSON (IT.8.2), marca cada sector como libre o bloqueado:

```json
{"cells": {"A1": "free",    "B1": "free",    "C1": "free",
           "A2": "blocked", "B2": "blocked", "C2": "free",
           "A3": "blocked", "B3": "blocked", "C3": "blocked"}}
```

`free` significa «se puede volar al menos 15 m en la dirección de ese sector»; `blocked`, que un edificio, muro, árbol, puente o techo está a menos de 15 m.

### 5.5.3 Ancla y sub-metas

Al enviar, la capa guarda un **ancla**: la pose del fotograma (posición y yaw), el instante, el waypoint real y la dirección de la meta. Cada sector tiene así una **dirección absoluta**: el yaw del ancla más el azimut del centro del sector, y la elevación del centro del sector. Cuando la respuesta llega, la capa la traduce y la valida contra el presente:

1. La descarta si pasaron más de 10 s o si el waypoint real cambió.
2. Si el sector de la meta está libre, **no agrega nada**; si había una sub-meta pendiente, la descarta: el camino directo está libre y el desvío sobra.
3. Si no, elige el sector libre más cercano en ángulo a la dirección de la meta —ante empate, la fila del medio, después la de arriba, después la de abajo, de modo que con la meta de frente un rodeo por el costado precede a uno vertical— y fija una sub-meta **desde el ancla** en la dirección de ese sector, a 15 m como máximo y **nunca más lejos que el waypoint real**. La altitud cambia según la elevación del sector, acotada a ±4 m.
4. Descarta la sub-meta si el dron ya la superó mientras la fuente procesaba.

La sub-meta se inserta en el `WaypointTracker` y el guiado normal la persigue. **El dron nunca se detiene a esperar.** Como la geometría está anclada al fotograma, girar mientras la fuente procesa no invalida la respuesta; solo la invalidan el paso del tiempo o haberla superado, y ambos casos se verifican. **Una sub-meta es un medio, no una condición:** el tracker mide en cada ciclo la distancia al waypoint real, y si el dron entra en su radio de aceptación, lo acepta y descarta las sub-metas pendientes. Los valores exactos y la geometría del ancla están en el Anexo 10 (IT.A10.6.4, IT.A10.8.4).

### 5.5.4 Fuente por defecto: profundidad monocular estimada

La red es Depth Anything V2 Metric Outdoor Small ([Yang et al., 2024](13-REFERENCIAS.md#ref-yang-2024)), de ~25 M de parámetros, que estima la profundidad **en metros** a partir del fotograma RGB (cap. 6, IT.6.12): lo que haría una red a bordo de un dron que solo tiene la cámara, no el sensor de profundidad de AirSim, que sigue fuera del lazo (IT.5.8). Sobre la misma grilla, un sector es libre si el percentil 5 de su profundidad estimada es ≥ 15 m, el mismo estadístico con que se construyeron las etiquetas del banco de prueba. Corre en un hilo aparte, en ~110 ms.

**Por qué la profundidad y no el VLM.** En el banco de prueba a bordo (cap. 11, IT.11.0) la grilla del VLM separa sectores libres de bloqueados con AUC 0.53 —azar— y el p5 de la profundidad estimada, con AUC 0.83–0.87 y exactitud balanceada del 75 %; sus errores son conservadores (2 % de sectores marcados libres con un obstáculo a menos de 5 m). Por eso la fuente por defecto es la profundidad. Si la capa con profundidad mejora el vuelo frente a no tenerla es una de las comparaciones del diseño experimental (`slm:depth` frente a `fsm:depth`, cap. 10 IT.10.3.3).

## 5.6 Barrido panorámico en deadlock

Ante un deadlock, el dron gira en el lugar hacia **4 rumbos** (0°, +90°, +180°, +270°), se asienta dos ciclos en cada uno y guarda el fotograma con el **yaw medido** en ese instante. Con los cuatro fotogramas hace una única consulta: la fuente dice, imagen por imagen, si el rumbo es transitable —con la profundidad, si el p5 del sector central llega a 15 m—, y el código fija una sub-meta en el rumbo elegido con la misma función y las mismas reglas que la capa estratégica (IT.5.5.3). Sin rumbos transitables, o ante una falla del barrido, cae al escape vertical (IT.5.3.4). Es la máquina de estados del Anexo 10 (IT.A10.7).

Dos decisiones importan para el argumento. **La fuente nunca reporta ángulos**: identifica las imágenes por número y el código usa el yaw medido de cada una, lo que evita el error de marco de referencia que convirtió una respuesta correcta en una maniobra en sentido contrario (cap. 9, IT.9.8.1). Y **la salida no repite lo que ya falló**: un deadlock es evidencia de que el rumbo intentado no funciona, de modo que el código descarta los rumbos cercanos al que falló y a los ya probados en la zona; la fuente sigue decidiendo qué está libre, y el código solo elige entre sus opciones con lo que el dron ya comprobó.

## 5.7 Brazo `fsm`

La FSM usa el mismo `ObstacleField`, el mismo vocabulario de macro-acciones y el mismo traductor a cinemática que el brazo `slm`; lo que cambia es quién elige la acción: umbrales deterministas.

| Estado FSM | Macro-acción | Condición |
|---|---|---|
| `CRUISE` | `MANTENER_RUMBO` | Centro despejado (default) |
| `AVOID_LEFT` / `AVOID_RIGHT` | `EVADIR_*` | Centro bloqueado o TTC ≤ 3.5 s; lado menos ocupado |
| `CLIMB` / `DESCEND` | `GANAR_ALTURA` / `PERDER_ALTURA` | Atasco con todos los sectores bloqueados (alternados) |
| `BRAKE` | `FRENAR` | TTC central ≤ 1.5 s con un lateral libre |

Detecta el atasco con el contador de progreso del tracker y, ante un atasco, delega en el mismo barrido panorámico del brazo `slm`, o, con la estrategia `blind`, alterna ascenso y descenso y luego gira con una esquina de desvío propia (IT.A10.4.8).

**Dos asimetrías con el brazo `slm` que deben tenerse en cuenta al comparar.** Primero, el brazo `fsm` resuelve los deadlocks con el **mismo barrido** que `slm`: la comparación `slm:depth` vs. `fsm:depth` aísla la capa estratégica y la política del lazo rápido, no el barrido; el brazo sin barrido es `fsm:blind` (cap. 10 IT.10.3.3). Segundo, la FSM tiene su propia lógica de atasco y escape, distinta de la del brazo `slm`.

## 5.8 Salvaguardas, contratos de diseño y registro

**Exclusión total de profundidad.** Ningún componente del lazo de vuelo lee el canal de profundidad del simulador, del que salen las etiquetas de referencia: darle acceso, aun indirecto, invalidaría la comparación con un sistema monocular (Anexo 11, IT.A11.4.2). Un test estático lo verifica sobre todos los módulos de vuelo y los puntos de entrada. Solo la calibración offline (cap. 7) y la auditoría de distancia mínima (cap. 10, IT.10.6.1), en un hilo aislado del grafo, usan ese canal.

**La fuente sin overrides.** La respuesta del VLM o de la red de profundidad se traduce a geometría y se aplica; no pasa por reglas deterministas que la reemplacen. Las validaciones que sí existen (edad, cambio de waypoint, sub-meta superada, deduplicación) descartan respuestas **obsoletas**, no respuestas que una regla considere equivocadas.

**Registro para la auditoría.** Cada ejecución guarda la traza completa del estado ciclo a ciclo, todas las consultas del lazo lento con sus fotogramas exactos y los videos de la corrida, sincronizados en un visor (cap. 4, IT.4.4); los análisis de los capítulos 9 a 11 se derivan de ese registro. El video se codifica en un hilo aparte: dentro del lazo duplicaba el período y degradaba el flujo óptico (IT.A10.9.1).
