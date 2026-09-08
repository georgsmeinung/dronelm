# 9. Modos de falla en lazos de control híbridos con LLM

## 9.1 El argumento central: contratos de interfaz como vector de falla primario

En sistemas robóticos que combinan percepción clásica, orquestación de grafo de control y un modelo de lenguaje, la intuición natural sobre modos de falla apunta al modelo: respuestas alucinadas, razonamiento incorrecto, formato inválido. La experiencia de desarrollo de este sistema señala en una dirección diferente: los fallos más costosos —en términos de horas de diagnóstico y de consecuencias en vuelo— ocurrieron en los **contratos de interfaz entre componentes**, no en el razonamiento del modelo.

Un modelo de lenguaje tiene una propiedad que lo hace especialmente peligroso en este contexto: raciocina sobre lo que recibe, no sobre la realidad. Si recibe un resumen de percepción que dice "camino despejado", produce una respuesta consistente con esa premisa. No tiene acceso privilegiado a la verdad del mundo — solo al texto que se le entrega. El corolario es que cualquier corrupción, omisión o malinterpretación en los datos que llegan al modelo produce decisiones estructuralmente correctas pero factualmente equivocadas, sin que el modelo (ni el sistema) lo detecte como error. El sistema "funciona" — no arroja excepciones, no se cae, produce salida JSON válida — mientras toma decisiones sistemáticamente incorrectas.

Este capítulo documenta cinco familias de fallas estructurales identificadas experimentalmente en la arquitectura, organizadas por la capa del sistema donde se originan. La tabla siguiente resume su taxonomía:

| # | Categoría | Capa de origen | ¿Genera excepción? | Consecuencia en vuelo |
|---|---|---|---|---|
| 1 | Schema drift / campo ciego | Contrato percepción→control | No | Navegación a ciegas hacia obstáculos |
| 2 | Desalineación temporal de frames | Buffer de historial visual | No | FOE/movimiento inferido incorrectamente |
| 3 | Descalibración de escala en divergencia | Operador diferencial en flujo | No | Saturación del canal de ocupación |
| 4 | State clipping + ciclos límite en LangGraph | Orquestación de grafo | No | Ascenso acumulado de >350 m |
| 5 | Degradación sensorial silenciosa | Captura de imagen y telemetría | No | Deliberación sobre datos corruptos |

El denominador común en los cinco casos es la ausencia de excepción en tiempo de ejecución. Este resultado metodológico se discute en §9.7.

## 9.2 Falla 1 — Schema drift: el campo nulo leído como ausencia de peligro

### 9.2.1 Descripción del modo de falla

En una arquitectura temprana del sistema, el estado del campo de obstáculos se comunicaba como una lista de objetos detectados (`detected_obstacles: List[dict]`), con una lista vacía como valor por defecto. La decisión de qué hacer cuando la lista estaba vacía era ambigua: podía significar "la percepción corrió y no detectó nada" (espacio despejado) o "la percepción no corrió, no tiene confianza, o falló silenciosamente" (ausencia de información).

Los módulos consumidores — el router de política, el constructor del prompt del VLM, el nodo FSM — resolvían esa ambigüedad en favor de la primera interpretación. El resultado en la práctica fue:

1. El generador de contexto construía un prompt que afirmaba al modelo "trayectoria frontal sin obstáculos detectados".
2. El VLM, actuando con perfecta coherencia lógica respecto de la información provista, emitía `keep_going` con alta confianza.
3. El lazo ejecutaba la maniobra de crucero normal.
4. No se generaba ninguna excepción ni alerta de log, porque desde la perspectiva del código, la lista vacía es un valor válido.

Este patrón es una instancia del anti-patrón de diseño conocido como *"zero as absence of evidence"*: tratar el valor neutro de un tipo de dato como evidencia de ausencia de fenómeno (Zhu et al., 2024). En señales de seguridad, la convención correcta es la inversa: la ausencia de evidencia no es evidencia de ausencia de peligro.

### 9.2.2 Mecanismo de contención

La solución adoptada fue rediseñar el contrato de percepción como el tipo `ObstacleField` (cap. 6): un objeto inmutable que distingue explícitamente tres estados epistémicos:

- `source = "flow"`, `foe_confidence > 0`: la percepción corrió con evidencia real. Los valores de TTC y ocupación son interpretables.
- `source = "flow"`, `foe_confidence = 0`: la percepción corrió pero no produjo evidencia confiable (FOE fuera de imagen, menos de 30 inliers). Interpretable como "sin información".
- `source = "degraded"`: la percepción fue inhibida activamente (guard de rotación, modo degradado, primer ciclo). El campo no contiene ninguna información sobre el mundo.

La invariante que impone `ObstacleField` es que **ningún consumidor puede confundir "sin obstáculos detectados" con "sin información"** sin leer explícitamente `has_evidence()`. El prompt del VLM verbaliza esta distinción en el componente 2 (§8.5): "percepción SIN evidencia por baja velocidad traslacional" es un texto distinto de "todos los sectores despejados".

En los nodos de control, `degraded_hover_node` es el destino de cualquier ciclo donde `has_evidence()` es `False` y el router no tiene una maniobra persistente activa — el sistema no puede decidir "avanzar" si no sabe nada del entorno.

## 9.3 Falla 2 — Desalineación temporal del historial de frames

### 9.3.1 Descripción del modo de falla

El nodo deliberativo multimodal envía al VLM un historial de `VLM_FRAME_HISTORY_SIZE = 2` frames (frames $t$ y $t-1$) para que el modelo pueda estimar la dirección de movimiento comparando dos instantes temporales distintos. Esta funcionalidad depende de que los dos frames sean genuinamente distintos en el tiempo.

En versiones tempranas, el buffer de historial era una lista Python simple que se actualizaba sin verificación de timestamps. Dos situaciones producían frames duplicados silenciosamente:

1. **Reinicio del buffer sin vaciado:** al saltar al siguiente waypoint, se vaciaba el historial pero el nodo de captura podía inyectar el último frame del waypoint anterior como "t-1" del nuevo waypoint. El VLM recibía el frame de un punto de la misión completamente distinto como contexto temporal inmediato.

2. **Ciclos donde `capture_node` no producía un frame nuevo:** si AirSim no respondía a tiempo (picos de carga de GPU), el buffer retenía el frame anterior. Bajo la etiqueta `[Fotograma t-1]` y `[Fotograma t]` aparecía la misma imagen.

El VLM, recibiendo dos frames idénticos, infería dos conclusiones posibles: el dron está estático (lo que puede ser correcto en hover pero es incorrecto durante crucero), o los objetos en escena están expandiéndose a velocidad cero (sin señal de aproximación). En ambos casos, la deliberación sobre movimiento y peligro era incorrecta de forma sistemática.

### 9.3.2 Mecanismo de contención

El buffer de historial se reimplementó como un `deque` de capacidad fija con control estricto de timestamps. Antes de incluir un frame en el prompt, se verifica:

- `timestamp_actual > timestamp_anterior` (frames genuinamente distintos en el tiempo)
- `delta_t < FRAME_HISTORY_MAX_STALENESS_MS` (el frame anterior no es demasiado antiguo — un frame de hace 3 s no aporta contexto temporal útil a 5 Hz)

Si la verificación falla, el prompt se adapta dinámicamente: en lugar de enviar dos frames etiquetados como `[t-1]` y `[t]`, envía un único frame etiquetado como `[ciclo actual]` con una nota explícita: "historial visual no disponible en este ciclo". Esto es más conservador pero menos peligroso que fabricar una secuencia temporal falsa.

## 9.4 Falla 3 — Descalibración de escala en el canal de divergencia

### 9.4.1 Descripción del modo de falla

El canal de divergencia del `ObstacleField` (cap. 6, §6.7) estima $\partial u / \partial x + \partial v / \partial y$ usando `np.gradient()` sobre el campo de flujo. En versiones anteriores, el cálculo usaba gradientes de Sobel 3×3 sin el factor de normalización $1/8$ que el kernel estándar requiere para ser un estimador de derivada de primer orden en unidades de píxel-por-píxel:

$$K_{\text{Sobel}} = \frac{1}{8}\begin{pmatrix} -1 & 0 & 1 \\ -2 & 0 & 2 \\ -1 & 0 & 1 \end{pmatrix}$$

Sin la normalización, el estimador de divergencia producía valores aproximadamente 8 veces mayores que los correctos. Con el factor de ocupación original calibrado sobre esa escala inflada, el canal de ocupación saturaba a `1.0` en condiciones de textura moderada — es decir, prácticamente siempre que hubiera cualquier gradiente de flujo en la imagen, incluso en vuelo en espacio abierto sin obstáculos cercanos.

La consecuencia operativa era que el predicado disyuntivo `is_blocked()` (§6.9) estaba dominado completamente por el canal de ocupación: aunque el TTC indicara una zona segura (> 4 s), la ocupación saturada votaba bloqueo. El canal de TTC calibrado quedaba efectivamente anulado.

### 9.4.2 Interacción con la lógica disyuntiva

Este modo de falla ilustra un problema de diseño de predicados disyuntivos en sistemas con múltiples canales de diferente confianza. La lógica $\text{is\_blocked} = (\text{occ} \geq 0.35) \lor (\text{conf} \geq 0.35 \land \text{ttc} \leq 2.5)$ asume que ambos canales están calibrados en la misma escala de confianza. Si un canal está sistemáticamente sobre-estimado, la disyunción lo convierte en el canal dominante, anulando la información del otro. El TTC, que tiene validación empírica (cap. 7), perdía toda influencia frente a una ocupación descalibrada.

### 9.4.3 Mecanismo de contención

La corrección fue triple:
1. Migrar a `np.gradient()` (diferencias centradas de segundo orden, normalizadas intrínsecamente) para el cómputo de divergencia.
2. Recalibrar el factor de ocupación contra datos de profundidad de referencia, con el proceso de curva ROC descrito en el cap. 7 (§7.5 — estado pendiente de completar para el canal de ocupación).
3. Introducir los umbrales diferenciados de confianza para los dos canales (`MIN_CONFIDENCE_FOR_BLOCKED = 0.15` vs. `MIN_CONFIDENCE_FOR_TTC_BLOCKED = 0.35`), de modo que el canal de TTC requiera mayor confianza para votar solo que el canal de ocupación acompañado de confianza mínima.

La tercera medida es especialmente importante: aunque la normalización del kernel corrige la escala, el sistema necesita ser robusto a futuras recalibraciones. Los umbrales diferenciados hacen que ningún canal pueda dominar completamente al otro sin confianza suficiente.

## 9.5 Falla 4 — State clipping y ciclos límite en LangGraph

Esta instancia fue la más costosa en consecuencias observadas (un ascenso acumulado de ~356 m en una sola corrida de validación) y la más ilustrativa de los riesgos de orquestadores de grafos que descartan silenciosamente estado no declarado.

### 9.5.1 El mecanismo de descarte silencioso de LangGraph

LangGraph construye los canales de estado de un `StateGraph` a partir de un `TypedDict` declarado en tiempo de compilación (`build_workflow()`). En cada invocación del grafo (`graph.invoke(state)`), el runtime serializa el estado de salida de cada nodo y lo fusiona con el estado entrante usando únicamente las claves presentes en el `TypedDict`. Cualquier clave que un nodo escriba en su diccionario de retorno pero que no esté declarada en el `TypedDict` es **descartada silenciosamente** — sin excepción, sin advertencia, sin registro en el log. El nodo siguiente recibe un estado donde esa clave simplemente no existe o tiene el valor por defecto del último ciclo donde sí estaba declarada.

Esta propiedad del runtime es documentada en la implementación (§5.2 del cap. 5) como la causa de cuatro bugs históricos. Su mecanismo específico es importante: el `TypedDict` de Python es una anotación de tipos, no una estructura de datos con validación en tiempo de ejecución. `state["clave_nueva"] = valor` no falla aunque `clave_nueva` no esté en el `TypedDict`; simplemente el runtime de LangGraph no la persiste en el canal de estado entre nodos.

### 9.5.2 Las cuatro vulnerabilidades identificadas

**Vulnerabilidad A — Claves de control no declaradas.**

Tres claves de control cruzaban la frontera entre nodo y lazo sin estar declaradas en `DroneState`:

- `_reset_stall_counter`: debía reiniciar el contador de progreso estancado al llegar a un waypoint. No declarada → el contador crecía monótonamente desde el inicio de la misión, independientemente del progreso real.
- `_delib_memory`: debía acumular un historial corto de resultados del deliberativo para que el VLM pudiera referirse a decisiones previas. No declarada → el historial siempre estaba vacío; cada ciclo el VLM era consultado sin contexto de lo que había decidido un ciclo antes.
- `_corner_wp`: debía inyectar un sub-waypoint de esquina intermedia para la maniobra `GIRAR_90`. No declarada → el nodo de girar_90 lo escribía en su retorno, el router lo leía en el ciclo siguiente... como el valor inicial (None), nunca como el punto calculado.

El diagnóstico de estas tres claves requirió instrumentar el runtime con un interceptor de estado entre cada par de nodos — el equivalente de "printear el estado completo antes y después de cada nodo" — porque ningún log de nivel de aplicación mostraba el descarte.

**Vulnerabilidad B — Ciclo límite de período 3 en la red de seguridad.**

El mecanismo de reintento de maniobra de escape funcionaba así (versión con el bug):

```
si stall_count > hard_threshold:
    activar FRENAR (ciclo 1)
    si stall_count > hard_threshold + N:
        resetear stall_count = 0  ← la red de seguridad se resetea a sí misma
```

El reseteo de `stall_count` en la propia rama de escape convertía el estado "atasco severo → acción de escape" en un estado transitorio: al ciclo siguiente, `stall_count = 0 < hard_threshold` y el sistema volvía a modo crucero. Tres ciclos después, el atasco se re-detectaba y el ciclo se repetía. El período 3 (crucero → pre-stall → escape → reseteo → crucero) no era observable como un error — era un patrón de comportamiento que en el viewer se veía como "el dron frenaba ocasionalmente sin razón aparente".

La corrección convierte el estado de escape en **absorbente**: una vez que `stall_count > hard_threshold`, el sistema transiciona a `DEADLOCK_ESCAPE` y no retorna a crucero hasta completar la secuencia de escape (deep_scan o girar_90), independientemente de cómo evolucione el contador.

**Vulnerabilidad C — Métrica de progreso auto-inconsistente.**

El predicado de atasco evaluaba `ciclos_sin_progreso > effective_stall_threshold` donde `effective_stall_threshold = max(10, eps_m / (min_speed / loop_hz))`. El problema era que `eps_m` (distancia mínima de avance por ciclo, en metros) y `min_speed` (velocidad mínima de crucero) estaban definidos en unidades y archivos distintos, y su combinación imponía una exigencia de velocidad de aproximación que el guiado en curva nunca podía satisfacer:

- `eps_m = 0.5 m` (distancia mínima de avance por ciclo)
- `min_speed = 2.0 m/s`, `loop_hz = 5 Hz` → velocidad de avance mínima implícita = `0.5 × 5 = 2.5 m/s`
- En un giro de 90°, la velocidad de aproximación al waypoint oscila entre 0 y `vx · cos(θ)`, con media aproximadamente `vx/2 ≈ 1.25 m/s`

Resultado: `effective_stall_threshold ≈ max(10, 0.5/(2.0/5)) = max(10, 1.25) = 10` ciclos, pero el sistema detectaba atasco en ciclos 3–5 por el perfil de velocidad del giro. El mecanismo de atasco se disparaba prácticamente al inicio de cada waypoint que requiriera maniobra.

La corrección fue medir el progreso solo en el plano horizontal XY (distancia 2D al waypoint), que es monotónicamente decreciente durante el giro aunque la componente frontal oscile, y ajustar `eps_m` al valor que es físicamente alcanzable en el peor caso del perfil de giro.

**Vulnerabilidad D — Escape ciego a la percepción.**

En la versión con el bug, el `policy_router` evaluaba las condiciones de escape de atasco *antes* de leer el `ObstacleField`:

```python
# versión con bug
if state["stall_count"] > hard_threshold:
    return "deadlock_escape"   # ← sin verificar percepción
if field.is_blocked("centro"):
    return "evasive"
```

La consecuencia era que en ciclos donde el estimador de flujo tenía evidencia válida de que un sector lateral estaba despejado (`has_open_corridor() = True`), el router seleccionaba igualmente la rama de escape de atasco. El dron ascendía aunque la percepción indicara una salida horizontal disponible. La corrección fue consultar `has_open_corridor()` como condición de guarda antes de activar el escape: si hay evidencia de corredor, la maniobra de escape no se activa aunque el contador de atasco haya excedido su umbral.

### 9.5.3 El ascenso acumulado como síntoma compuesto

La combinación de las cuatro vulnerabilidades produjo en una corrida de validación un ascenso acumulado de ~356 m en una sola misión. La secuencia causal fue:

1. `_reset_stall_counter` no declarada → `stall_count` creció desde el ciclo 1 sin resetearse al llegar a cada waypoint.
2. A los ~8 ciclos de misión, `stall_count > hard_threshold` a pesar de que el dron avanzaba normalmente.
3. El router activó `deadlock_escape` (ciego a percepción), que en esa versión ejecutaba `GANAR_ALTURA` con deriva lateral no justificada.
4. `stall_count` se reseteó (ciclo límite B) → el siguiente ciclo, el router volvió a crucero normal.
5. `stall_count` volvió a crecer rápidamente (umbral demasiado bajo por la métrica inconsistente C).
6. El ciclo se repitió centenares de veces, produciendo un ascenso neto acumulado.

Desde el exterior, la corrida registraba una misión "sin errores" (no hay excepciones en el log) que simplemente "no llegó a destino". Sin el análisis del viewer frame a frame y la lectura del JSONL de auditoría, el patrón era opaco.

## 9.6 Falla 5 — Degradaciones sensoriales silenciosas

### 9.6.1 Inversión de canales de color RGB/BGR

Durante varios meses de experimentación, el cliente de captura de AirSim (`AirSimClient.capture()`) entregaba el buffer de imagen en el orden de canales RGB nativo del motor Unreal, mientras que el pipeline asumía la convención BGR de OpenCV — la convención estándar de OpenCV en la que el canal azul ocupa el índice 0.

El efecto fotométrico es una inversión de los canales rojo y azul en cada píxel: fachadas de ladrillo rojo aparecen en tonos azulados, el cielo azul aparece amarillento, la vegetación adquiere colores no naturales. El VLM deliberativo — entrenado sobre datos fotométricamente correctos — deliberó durante esos meses sobre imágenes con espectro cromático sistemáticamente falso. En ningún momento emitió una queja sobre la calidad de las imágenes ni redujo su confianza en la decisión: el modelo de lenguaje no tiene acceso directo al historial de la distribución de datos sobre la que fue entrenado, y no puede detectar que la imagen recibida está fuera de distribución por inversión de canal.

El diagnóstico requirió guardar físicamente las imágenes enviadas al VLM al disco y abrirlas en un visor externo — el análogo de "mirar los datos crudos" que es el primer paso de depuración en visión por computadora pero que en un sistema integrado es fácil de omitir cuando el modelo "parece razonar correctamente".

La corrección fue añadir `cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)` en el punto de captura, con un test unitario que verifica el orden de canales comparando estadísticas de cada canal en una imagen de referencia conocida.

### 9.6.2 Contaminación por primitivas de depuración persistentes

El simulador AirSim/cosysairsim permite dibujar primitivas geométricas en el mundo virtual (`simPlotLineStrip`, `simPlotPoints`, `simPlotArrows`) para visualización durante el desarrollo: trayectorias planificadas, sectores del `ObstacleField`, vectores de flujo. Estas primitivas son *persistentes* en la sesión del simulador: no se borran al reiniciar el script de control, solo al llamar explícitamente `simFlushPersistentMarkers()`.

En varias sesiones de desarrollo, al relanzar el vuelo sin reiniciar AirSim, las primitivas de la sesión anterior permanecían en el mundo virtual. La cámara a bordo las capturaba como geometría física en la escena: franjas de colores brillantes cruzando el campo visual que el VLM interpretaba como cables, estructuras metálicas o señales de tráfico dependiendo del color y orientación.

La consecuencia fue particularmente difícil de diagnosticar porque el comportamiento variaba según el historial de la sesión: un vuelo iniciado después de reiniciar AirSim se comportaba normalmente, mientras que el mismo vuelo iniciado sin reiniciar producía evasiones espurias repetidas. Jansen et al. (2023) documentan comportamientos similares de estado persistente en CosysAirSim como fuente de irreproducibilidad entre corridas.

La corrección fue añadir `simFlushPersistentMarkers()` al inicio de cada sesión de vuelo, con un segundo vaciado de primitivas antes de iniciar la fase de captura de imágenes para el VLM.

### 9.6.3 Supresión de ángulos de actitud en la telemetría

El binding `cosysairsim` usado en este proyecto (fork de AirSim con soporte UE5 — Jansen et al., 2023) no implementaba el método `to_eularian_angles()` del binding oficial de Microsoft AirSim. La llamada al método retornaba silenciosamente $(0, 0, 0)$ en lugar de lanzar `AttributeError`. El resultado era que los ángulos de pitch y roll reportados al VLM en cada prompt eran siempre `0.0°`, independientemente de la inclinación física real del vehículo.

Durante maniobras de aceleración (pitch negativo ~ −8° a −12°), descenso agresivo (pitch positivo) o giros (roll lateral), el VLM recibía la información de que el dron estaba perfectamente nivelado. La estimación de la componente de velocidad de cierre perpendicular al plano focal — que depende del pitch — era incorrecta, y la interpretación de la escena visual (la posición aparente del horizonte en la imagen) estaba desalineada con la información verbal de actitud.

La corrección fue implementar la conversión directa desde el cuaternión de orientación, disponible en la telemetría de CosysAirSim, a ángulos de Euler (roll, pitch, yaw) usando las fórmulas estándar de Wahba (1965), sin depender del método del binding:

$$\phi = \arctan2(2(q_w q_x + q_y q_z),\ 1 - 2(q_x^2 + q_y^2))$$
$$\theta = \arcsin(2(q_w q_y - q_z q_x))$$
$$\psi = \arctan2(2(q_w q_z + q_x q_y),\ 1 - 2(q_y^2 + q_z^2))$$

Un test unitario verifica, contra una tabla de cuaterniones conocidos (identidad, 90° en cada eje, 45° combinado), que la conversión produce los ángulos correctos con error < 0.01°.

## 9.7 Por qué el sistema seguía funcionando: el problema de la observabilidad

Ninguno de los cinco modos de falla descritos se manifestó como un error visible en tiempo de ejecución. En todos los casos:

- El modelo de lenguaje seguía produciendo respuestas JSON válidas y plausibles.
- El lazo de control ejecutaba el ciclo sin excepciones.
- Las métricas agregadas de la corrida (distancia recorrida, waypoints completados, velocidad media) no distinguían estas corridas de corridas fallidas por otras causas.

Esta propiedad tiene una implicación metodológica directa: las técnicas de depuración habituales para sistemas de software — observar el output, monitorear las métricas, leer el log de errores — son ciegas a esta clase de error. La observación del comportamiento es precisamente la herramienta menos útil porque el sistema exhibe comportamiento *consistente con sus premisas internas*, aunque esas premisas estén corrompidas.

Las técnicas de diagnóstico que sí funcionaron en este proyecto fueron:

**1. Auditoría de contratos en la frontera de cada componente.** Para cada par (productor, consumidor) de datos de estado, verificar explícitamente: ¿qué valor devuelve el productor cuando no tiene información? ¿Cómo interpreta el consumidor ese valor? La pregunta "¿qué pasa cuando este campo es None/vacío/cero?" tiene que tener una respuesta documentada y verificable.

**2. Guardar los datos crudos enviados al modelo.** El viewer (`airsim-runs/*.viewer.html`) guarda el fotograma anotado y el estado completo de cada ciclo precisamente para hacer auditable lo que el modelo recibía. Sin esa capacidad de inspección retroactiva, la falla de inversión RGB/BGR habría sido indetectable.

**3. Tests de invariantes de contrato, no de comportamiento.** Un test que verifique "el dron evadió el obstáculo" es frágil y dependiente de la escena. Un test que verifique "si `has_evidence()` es False, ningún consumidor reporta el campo como 'despejado'" es un test de contrato que captura la Falla 1 sin necesitar una corrida de vuelo.

**4. Inyección de valores límite en el estado de LangGraph.** Para detectar las claves no declaradas (Falla 4-A), la técnica fue instrumentar el lazo con un interceptor que comparaba `state` al entrar a cada nodo con `state` al salir, reportando cualquier clave presente en la salida que no estuviera en el `TypedDict`. Esta verificación se convirtió en un modo de debug permanente activable via variable de entorno (`LANGGRAPH_DEBUG_STATE_CLIPPING=1`).

## 9.8 Riesgos residuales y trabajo pendiente

Los cinco modos de falla documentados están corregidos en la implementación actual. Pero la arquitectura contiene puntos donde pueden aparecer instancias análogas:

**Riesgo A — Nuevas claves de DroneState.** Cada vez que se añade una funcionalidad que requiere persistir estado entre ciclos, existe el riesgo de que la clave correspondiente no se declare en `DroneState`. La mitigación es el modo `LANGGRAPH_DEBUG_STATE_CLIPPING=1` y el proceso de revisión de `DroneState` en el CHANGELOG antes de cada nueva feature.

**Riesgo B — Cambios de API del binding de AirSim.** El binding `cosysairsim` es un fork activamente mantenido (Jansen et al., 2023). Actualizaciones del binding pueden modificar el comportamiento de métodos (como ocurrió con la corrección del cuaternión). Los tests unitarios de conversión de telemetría son la mitigación; deben ejecutarse tras cada actualización del binding.

**Riesgo C — Distribución de imágenes fuera del dominio de entrenamiento del VLM.** La corrección de inversión RGB/BGR es una transformación fija. Pero la brecha de dominio entre imágenes de AirSim/UE5 y el dominio de entrenamiento del VLM (predominantemente imágenes reales del mundo) es una fuente estructural de error que no se elimina con ninguna corrección puntual. La calibración de la frecuencia de respuestas subóptimas del VLM en los escenarios de esta tesis (cap. 11) es el mecanismo de caracterización de ese riesgo residual.
