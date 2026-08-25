# 8. Modos de falla de lazos de control híbridos con LLM

## 8.1 El patrón común

Este capítulo desarrolla el argumento central declarado en la introducción (§1.4): en un sistema de
control donde un modelo de lenguaje consume descripciones de escena, el error más caro no está en el
modelo sino en la interfaz que lo alimenta, y no se detecta observando el comportamiento porque el
modelo siempre produce una respuesta plausible. Documenta tres instancias concretas de ese patrón,
encontradas en distintas etapas del proyecto y con evidencia medida, y luego una cuarta sección con
una cadena de fallas de un tipo distinto pero relacionado: fallas del propio grafo de control que,
igual que las anteriores, no se manifestaban como errores explícitos sino como comportamiento
plausible pero incorrecto.

## 8.2 Instancia 1 — `detected_obstacles = []` tras el retiro de YOLO

Como se describe en el capítulo 5, el detector YOLO fue retirado del pipeline por costo computacional,
pero sus consumidores (el enrutador de decisiones, el mecanismo de respaldo determinista, el resumen
de sectores para el prompt) siguieron leyendo el campo `detected_obstacles` que ese detector producía.
Al quedar ese campo permanentemente en `[]`, la percepción afirmaba, de forma sistemática, "despejado"
— no porque el entorno estuviera efectivamente despejado, sino porque el productor de esa información
había dejado de existir sin que sus consumidores lo supieran.

## 8.3 Instancia 2 — `frame_history` vacío con etiquetas `[Fotograma t-3]`

El prompt enviado al modelo de lenguaje incluía etiquetas de historial temporal (`[Fotograma t-3]`,
`[Fotograma t-2]`…), pero el buffer de historial (`frame_history`) del que debían provenir esos
fotogramas nunca se poblaba: el modelo recibía un único fotograma real, etiquetado como si formara
parte de una secuencia temporal de varios pasos. Se le afirmaba al modelo una historia que no existía.
La corrección implementó un *ring buffer* real y, para el tamaño de historial efectivamente
configurado, retiró las etiquetas temporales del prompt cuando no hay más de un fotograma para
etiquetar — de modo que la cantidad de etiquetas coincida siempre con la cantidad de imágenes
efectivamente enviadas.

## 8.4 Instancia 3 — el canal de ocupación satura por un error de escala

Como se documenta en el capítulo 5 (§5.3) y el capítulo 6 (§6.3), la divergencia del campo de flujo se
calcula actualmente con un kernel de Sobel sin normalizar, lo que sobreestima la ocupación de forma
sistemática. Porque `is_blocked()` combina ocupación y TTC con un operador lógico OR, un canal de
ocupación saturado puede anular en la práctica al canal de TTC —el único de los dos validado contra
profundidad—, y la percepción puede afirmar "bloqueado" incluso ante evidencia que, correctamente
escalada, no debería disparar ese estado. A diferencia de las dos instancias anteriores, esta no está
corregida a la fecha de este escrito: se documenta aquí como la tercera instancia del mismo patrón, y
como trabajo pendiente antes de dar por cerrada la calibración del canal de ocupación.

## 8.5 Una cadena de fallas del propio grafo de control

Una revisión diagnóstica sobre un vuelo real en el que el dron quedó atrapado ascendiendo
indefinidamente —sin colisionar y sin consultar al modelo de lenguaje ni una sola vez— identificó
cuatro problemas compuestos en el grafo de control, ninguno de los cuales se manifestaba como un error
explícito:

1. **Claves de control descartadas silenciosamente por el esquema del grafo.** LangGraph construye los
   canales de estado a partir de un `TypedDict` y descarta, sin aviso, cualquier clave que un nodo
   escriba pero que no esté declarada en ese esquema. Tres claves de control —una que debía reiniciar
   el contador de progreso estancado, una que acumulaba la memoria corta de resultados de decisiones
   previas, y una que inyectaba sub-waypoints de esquina— cruzaban la frontera entre nodo y lazo sin
   estar declaradas, y se perdían en cada invocación del grafo. La consecuencia más grave fue que el
   contador de ciclos sin progreso nunca se reiniciaba, y crecía de forma monótona.
2. **Un ciclo límite de período 3 en la propia red de seguridad.** El mecanismo pensado para limitar
   los reintentos de una maniobra de escape frenaba el vuelo pero, en la misma rama de código, también
   reseteaba a cero el contador de reintentos — es decir, la red de seguridad se reseteaba a sí misma,
   convirtiendo lo que debía ser un estado terminal en un ciclo que se repetía indefinidamente.
3. **Una métrica de progreso auto-inconsistente por unidades mezcladas.** El umbral de "ciclos sin
   progreso" se expresaba en ciclos, y el umbral de distancia mínima de progreso se expresaba en
   metros, definidos de forma independiente entre sí; combinados, exigían una velocidad de acercamiento
   sostenida mayor a la que el guiado en un giro cerrado podía físicamente entregar. El resultado era
   que el mecanismo de "atasco" se disparaba de forma prácticamente garantizada a los pocos ciclos de
   iniciar la misión, sin que hubiera ningún obstáculo real de por medio.
4. **Un mecanismo de escape ciego a la percepción.** El enrutador de decisiones activaba la rama de
   escape por atasco antes de consultar el campo de obstáculos, así que en varios ciclos consecutivos
   en los que la percepción reportaba con evidencia válida un sector lateral despejado, el dron siguió
   ascendiendo de todos modos: la evidencia de que existía una salida disponible no llegaba a
   considerarse antes de decidir.

La combinación de estos cuatro problemas, más una macro-acción de ascenso con una deriva lateral no
justificada en su definición cinemática (corregida junto con el resto de esta cadena; ver §7.4),
produjo en una corrida de validación un ascenso acumulado del orden de 356 metros en una sola misión,
sin que el sistema lo reportara como una falla — desde la perspectiva de las métricas agregadas de esa
corrida, era simplemente una misión que no llegó a destino, no un ciclo de control atrapado en un
estado absorbente. La corrección de estos cuatro problemas —declarar explícitamente las claves de
estado, hacer que el reintento agotado enclave y cambie de estrategia en lugar de resetearse, medir el
progreso por distancia horizontal en vez de tridimensional, y consultar la evidencia de percepción
antes de decidir el escape— está incorporada en la arquitectura descrita en el capítulo 4.

## 8.6 Por qué el sistema seguía volando y el modelo seguía respondiendo

Ninguno de los cuatro modos de falla descritos en este capítulo se manifestó como un error visible en
tiempo de ejecución: en las tres primeras instancias, el modelo de lenguaje seguía recibiendo un
prompt bien formado y devolvía una decisión estructurada y plausible; en la cuarta, el grafo de
control seguía ejecutándose sin excepciones, ciclo tras ciclo. En los cuatro casos, el sistema
"funcionaba" en el sentido más superficial de la palabra — no se caía, no arrojaba errores — mientras
tomaba decisiones sistemáticamente equivocadas por razones que solo se hacían visibles leyendo el
contrato entre quien produce un dato y quien lo consume, nunca observando el comportamiento agregado
del vuelo. Es, en conjunto, un resultado metodológico sobre cómo depurar lazos de control híbridos con
modelos de lenguaje, no una lista de anécdotas de desarrollo: la observación del comportamiento —la
herramienta de depuración más natural para un sistema que "parece" razonar— es precisamente la que
menos sirve para encontrar esta clase de error.
