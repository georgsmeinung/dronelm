# 9. Modos de falla de lazos de control híbridos con LLM

## 9.1 El patrón común: integridad de contratos de interfaz

Este capítulo desarrolla el argumento central declarado en la introducción (§1.4): en un sistema robótico híbrido donde un modelo de lenguaje consume descripciones estructuradas del entorno para emitir decisiones de control, el modo de falla más crítico no radica en el razonamiento sintáctico del modelo, sino en la **consistencia e integridad del contrato de datos** que lo alimenta. 

Los modelos de lenguaje poseen una notable capacidad para racionalizar cualquier entrada estructurada y emitir respuestas plausibles, bien formadas y ejecutables, aun cuando las premisas subyacentes provengan de campos nulos, sensores degradados o datos descalibrados. Este capítulo documenta una taxonomía de cinco modos de falla estructurales identificados
experimentalmente en la arquitectura híbrida, analizando su origen, su impacto en la toma de decisiones
y los mecanismos de contención implementados.

## 9.2 Instancia 1 — Desincronización de esquemas y campos ciegos (Schema Drift)

Una de las fallas más críticas en pipelines multimodales ocurre cuando existe una desincronización de contrato (*contract drift*) entre los productores de percepción y los módulos consumidores (enrutador de política, mecanismo de respaldo determinista y constructor del prompt del SLM).

Cuando un campo de estado de obstáculos permanece en un valor nulo por defecto (por ejemplo, una lista vacía `detected_obstacles = []`), los módulos consumidores interpretan semánticamente ese valor como *"espacio aéreo totalmente despejado"* en lugar de *"sensor no disponible o no calibrado"*. En consecuencia:
1. El generador de contexto construye un prompt que afirma al modelo de lenguaje que la trayectoria frontal carece de obstáculos.
2. El SLM, actuando con perfecta coherencia lógica respecto de la información provista, comanda velocidad de crucero constante (`keep_going`).
3. El sistema no genera excepciones de ejecución ni errores en los registros, pero el dron navega a ciegas hacia los obstáculos físicos de la escena.

**Mecanismo de contención:** La arquitectura resuelve este modo de falla unificando toda la percepción en el contrato tipado `ObstacleField` (capítulo 6). Si la estimación de flujo o telemetría no es confiable, el campo reporta explícitamente `confidence = 0` y `ttc_s = inf`, forzando al lazo de control a ingresar en modo de maniobra determinista segura o `degraded_hover` (capítulo 5), impidiendo que la ausencia de señal se disfrace de ausencia de peligro.

## 9.3 Instancia 2 — Desalineación temporal en secuencias contextuales

El constructor de prompts para modelos de lenguaje multimodales o secuenciales frecuentemente incluye etiquetas temporales relativas (`[Fotograma t-2]`, `[Fotograma t-1]`, `[Fotograma t]`) para facilitar el análisis de velocidad de aproximación. Si el buffer histórico subyacente (`frame_history`) no se gestiona como una estructura de anillo sincrónica con marcas de tiempo verificadas, pueden inyectarse fotogramas estáticos duplicados o no sincronizados bajo rótulos de secuencia temporal activa.

En este escenario, el modelo de lenguaje intenta inferir vectores de movimiento a partir de una secuencia temporal inexistente o artificialmente congelada.

**Mecanismo de contención:** Implementación de un *ring buffer* estricto con validación de estampas de tiempo ($\Delta t > 0$) y adaptación dinámica del prompt: las etiquetas secuenciales solo se generan si el buffer cuenta con fotogramas temporales efectivamente diferenciados y verificados.

## 9.4 Instancia 3 — Descalibración de escala en operadores diferenciales y saturación disyuntiva

Como se documenta en el capítulo 6 (§6.3) y el capítulo 7 (§7.3), el cálculo de derivadas espaciales mediante operadores de gradiente discretos (como Sobel de 3×3 sin factor de normalización $1/8$) induce un factor de escala de amplificación sobre la divergencia estimada.

Cuando la regla de decisión integra la ocupación y el Tiempo-a-Colisión mediante una compuerta lógica disyuntiva ($OR$):
$$\text{is\_blocked} = (\text{occupancy} \ge \tau_{\text{occ}}) \lor (\text{ttc\_s} \le \tau_{\text{ttc}})$$
la saturación artificial del canal de ocupación anula la influencia del canal de TTC calibrado, provocando declaraciones sistemáticas de bloqueo ante variaciones menores de textura visual.

**Mecanismo de contención:** Normalización analítica de los kernels diferenciales y calibración cruzada de los umbrales de activación mediante curvas ROC contra canales de profundidad de referencia (capítulo 7).

## 9.5 Instancia 4 — Fallas compuestas en orquestadores de grafos (State Clipping y Ciclos Límite)

El análisis de ejecución del grafo de control por ciclo identificó cuatro vulnerabilidades estructurales en la propagación de variables de estado entre nodos, ninguna de las cuales arrojaba excepciones en tiempo de ejecución:

1. **Claves de control descartadas silenciosamente por el esquema del grafo.** LangGraph construye los canales de estado a partir de un `TypedDict` y descarta, sin aviso, cualquier clave que un nodo escriba pero que no esté declarada en ese esquema. Tres claves de control —una que debía reiniciar el contador de progreso estancado, una que acumulaba la memoria corta de resultados de decisiones previas, y una que inyectaba sub-waypoints de esquina— cruzaban la frontera entre nodo y lazo sin estar declaradas, y se perdían en cada invocación del grafo. La consecuencia más grave fue que el contador de ciclos sin progreso nunca se reiniciaba, y crecía de forma monótona.
2. **Un ciclo límite de período 3 en la propia red de seguridad.** El mecanismo pensado para limitar los reintentos de una maniobra de escape frenaba el vuelo pero, en la misma rama de código, también reseteaba a cero el contador de reintentos — es decir, la red de seguridad se reseteaba a sí misma, convirtiendo lo que debía ser un estado terminal en un ciclo que se repetía indefinidamente.
3. **Una métrica de progreso auto-inconsistente por unidades mezcladas.** El umbral de "ciclos sin progreso" se expresaba en ciclos, y el umbral de distancia mínima de progreso se expresaba en metros, definidos de forma independiente entre sí; combinados, exigían una velocidad de acercamiento sostenida mayor a la que el guiado en un giro cerrado podía físicamente entregar. El resultado era que el mecanismo de "atasco" se disparaba de forma prácticamente garantizada a los pocos ciclos de iniciar la misión, sin que hubiera ningún obstáculo real de por medio.
4. **Un mecanismo de escape ciego a la percepción.** El enrutador de decisiones activaba la rama de escape por atasco antes de consultar el campo de obstáculos, así que en varios ciclos consecutivos en los que la percepción reportaba con evidencia válida un sector lateral despejado, el dron siguió ascendiendo de todos modos: la evidencia de que existía una salida disponible no llegaba a considerarse antes de decidir.

La combinación de estos cuatro problemas, más una macro-acción de ascenso con una deriva lateral no justificada en su definición cinemática (corregida junto con el resto de esta cadena; ver §8.4), produjo en una corrida de validación un ascenso acumulado del orden de 356 metros en una sola misión, sin que el sistema lo reportara como una falla — desde la perspectiva de las métricas agregadas de esa corrida, era simplemente una misión que no llegó a destino, no un ciclo de control atrapado en un estado absorbente. La corrección de estos cuatro problemas —declarar explícitamente las claves de estado, hacer que el reintento agotado enclave y cambie de estrategia en lugar de resetearse, medir el progreso por distancia horizontal en vez de tridimensional, y consultar la evidencia de percepción antes de decidir el escape— está incorporada en la arquitectura descrita en el capítulo 5.

## 9.6 Instancia 5 — Degradaciones silenciosas en el canal de visión y telemetría de actitud

La transición hacia una deliberación multimodal directa (VLM) expuso una quinta categoría de fallas de contrato, vinculadas a la fidelidad sensorial de los datos crudos presentados al modelo:

1. **Inversión cromática persistente (RGB vs. BGR):** Durante meses de experimentación, el cliente de captura de simulación entregó el buffer de imagen de Unreal Engine en formato RGB nativo a un pipeline que asumía la convención BGR de OpenCV. En consecuencia, el modelo de visión deliberó sistemáticamente sobre imágenes con canales rojo y azul invertidos (fachadas terracota observadas en tonos fríos azulados y cielos amarillentos). El VLM jamás emitió una queja sintáctica ni interrumpió su servicio: procesaba los fotogramas y emitía decisiones plausibles a partir de un espectro cromático falso.
2. **Contaminación por primitivas de depuración en el espacio 3D:** Trazas visuales dibujadas en el mundo virtual por scripts de inspección previa (`simPlotLineStrip` en Unreal Engine) no se limpiaban al iniciar el vuelo. La cámara a bordo las capturaba como franjas geométricas reales en la escena, induciendo al VLM a interpretar líneas de depuración como cables u obstáculos físicos delante del dron.
3. **Supresión espuria de ángulos de actitud:** Debido a que el binding `cosysairsim` no implementaba `to_eularian_angles`, los ángulos de *pitch* y *roll* permanecían fijados en $0.0^\circ$ en cada prompt, privando al modelo de conocer la inclinación física real del vehículo durante maniobras de aceleración.

**Mecanismos de contención:** Corrección de la transposición de canales en memoria en el punto de captura (`AirSimClient.capture()`), llamada obligatoria de limpieza de primitivas (`simFlushPersistentMarkers()`) al inicializar la conexión, y cálculo matemático directo de ángulos de Euler a partir del cuaternión de orientación.

## 9.7 Por qué el sistema seguía volando y el modelo seguía respondiendo

Ninguno de los cinco modos de falla descritos en este capítulo se manifestó como un error visible en tiempo de ejecución: en las instancias multimodales y de prompt, el modelo de lenguaje seguía recibiendo entradas bien formadas y devolvía decisiones estructuradas y plausibles; en la orquestación del grafo, el lazo táctico seguía ejecutándose sin excepciones, ciclo tras ciclo. En todos los casos, el sistema "funcionaba" en el sentido más superficial de la palabra — no se caía, no arrojaba errores — mientras tomaba decisiones sistemáticamente equivocadas por razones que solo se hacían visibles leyendo el contrato entre quien produce un dato y quien lo consume, nunca observando el comportamiento agregado del vuelo. Es, en conjunto, un resultado metodológico sobre cómo depurar lazos de control híbridos con modelos de lenguaje, no una lista de anécdotas de desarrollo: la observación del comportamiento —la herramienta de depuración más natural para un sistema que "parece" razonar— es precisamente la que menos sirve para encontrar esta clase de error.
