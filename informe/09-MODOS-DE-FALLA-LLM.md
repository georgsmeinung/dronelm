# 9. Modos de falla en lazos de control híbridos con LLM

## 9.1 El argumento central: contratos de interfaz como vector de falla primario

En sistemas robóticos que combinan percepción clásica, orquestación de grafo de control y un modelo de lenguaje, la intuición natural sobre modos de falla apunta al modelo: respuestas alucinadas, razonamiento incorrecto, formato inválido. La experiencia de desarrollo de este sistema señala en una dirección diferente: los fallos más costosos —en términos de horas de diagnóstico y de consecuencias en vuelo— ocurrieron en los **contratos de interfaz entre componentes**, no en el razonamiento del modelo.

Un modelo de lenguaje tiene una propiedad que lo hace especialmente peligroso en este contexto: raciocina sobre lo que recibe, no sobre la realidad. Si recibe un resumen de percepción que dice "camino despejado", produce una respuesta consistente con esa premisa. No tiene acceso privilegiado a la verdad del mundo — solo al texto que se le entrega. El corolario es que cualquier corrupción, omisión o malinterpretación en los datos que llegan al modelo produce decisiones estructuralmente correctas pero factualmente equivocadas, sin que el modelo (ni el sistema) lo detecte como error. El sistema "funciona" — no arroja excepciones, no se cae, produce salida JSON válida — mientras toma decisiones sistemáticamente incorrectas. Esta propiedad no es una idiosincrasia de este sistema: es la manifestación, en un lazo de control robótico, del problema general de las respuestas fluidas y plausibles pero no fundamentadas en la entrada real (*hallucination*) documentado extensamente en la literatura de generación de lenguaje natural ([Ji et al., 2023](13-REFERENCIAS.md#ref-ji-2023)), agravado aquí por el hecho de que la salida del modelo no es texto para un lector humano crítico, sino un comando que se ejecuta directamente sobre un vehículo físico.

Este capítulo documenta seis familias de fallas estructurales identificadas experimentalmente en la arquitectura, organizadas por la capa del sistema donde se originan. La tabla siguiente resume su taxonomía:

| # | Categoría | Capa de origen | ¿Genera excepción? | Consecuencia en vuelo |
|---|---|---|---|---|
| 1 | Schema drift / campo ciego | Contrato percepción→control | No | Navegación a ciegas hacia obstáculos |
| 2 | Desalineación temporal de frames | Buffer de historial visual | No | FOE/movimiento inferido incorrectamente |
| 3 | Descalibración de escala en divergencia | Operador diferencial en flujo | No | Saturación del canal de ocupación |
| 4 | State clipping + ciclos límite en LangGraph | Orquestación de grafo | No | Ascenso acumulado de >350 m |
| 5 | Degradación sensorial silenciosa | Captura de imagen y telemetría | No | Deliberación sobre datos corruptos |
| 6 | Integración del VLM: marco de referencia, defaults silenciosos y reglas apiladas | Interfaz VLM → control | No | Respuestas correctas del modelo ejecutadas al revés o ignoradas |

El denominador común en los seis casos es la ausencia de excepción en tiempo de ejecución. Este resultado metodológico se discute en §9.7.

## 9.2 Falla 1 — Schema drift: el campo nulo leído como ausencia de peligro

### 9.2.1 Descripción del modo de falla

En una de las configuraciones ensayadas durante el desarrollo, el estado del campo de obstáculos se comunicaba como una lista de objetos detectados (`detected_obstacles: List[dict]`), con una lista vacía como valor por defecto. La decisión de qué hacer cuando la lista estaba vacía era ambigua: podía significar "la percepción corrió y no detectó nada" (espacio despejado) o "la percepción no corrió, no tiene confianza, o falló silenciosamente" (ausencia de información).

Los módulos consumidores — la capa de decisión (`navigate`), el constructor del prompt del VLM y la FSM — resolvían esa ambigüedad en favor de la primera interpretación. El resultado en la práctica fue:

1. El generador de contexto construía un prompt que afirmaba al modelo "trayectoria frontal sin obstáculos detectados".
2. El VLM, actuando con perfecta coherencia lógica respecto de la información provista, emitía `keep_going` con alta confianza.
3. El lazo ejecutaba la maniobra de crucero normal.
4. No se generaba ninguna excepción ni alerta de log, porque desde la perspectiva del código, la lista vacía es un valor válido.

Este patrón es una instancia de un anti-patrón de diseño general — tratar el valor neutro de un tipo de dato (lista vacía, cero, `None`) como evidencia de ausencia de fenómeno, en lugar de como ausencia de información — que colapsa dos estados epistémicos distintos en una única representación. En señales de seguridad la distinción es crítica y la convención correcta es la inversa: la ausencia de evidencia no es evidencia de ausencia de peligro, principio formulado explícitamente para la interpretación de resultados nulos en [Altman y Bland (1995)](13-REFERENCIAS.md#ref-altman-1995) y que aquí se aplica a un contrato de datos entre percepción y control en lugar de a la interpretación estadística de un experimento.

### 9.2.2 Mecanismo de contención

La solución adoptada fue rediseñar el contrato de percepción como el tipo `ObstacleField` (cap. 6): un objeto inmutable que distingue explícitamente tres estados epistémicos:

- `source = "flow"`, `foe_confidence > 0`: la percepción corrió con evidencia real. Los valores de TTC y ocupación son interpretables.
- `source = "flow"`, `foe_confidence = 0`: la percepción corrió pero no produjo evidencia confiable (FOE fuera de imagen, menos de 30 inliers). Interpretable como "sin información".
- `source = "degraded"`: la percepción fue inhibida activamente (guard de rotación, modo degradado, primer ciclo). El campo no contiene ninguna información sobre el mundo.

La invariante que impone `ObstacleField` es que **ningún consumidor puede confundir "sin obstáculos detectados" con "sin información"** sin leer explícitamente `has_evidence()`. El prompt del VLM verbaliza esta distinción en el componente 2 (§8.5): "percepción SIN evidencia por baja velocidad traslacional" es un texto distinto de "todos los sectores despejados".

En los nodos de control, `degraded_hover_node` es el destino de cualquier ciclo donde `has_evidence()` es `False` y no hay una maniobra comprometida activa — el sistema no puede decidir "avanzar" si no sabe nada del entorno.

## 9.3 Falla 2 — Desalineación temporal del historial de frames

### 9.3.1 Descripción del modo de falla

La consulta multimodal envía al VLM un historial de `VLM_FRAME_HISTORY_SIZE = 2` frames (frames $t$ y $t-1$) para que el modelo pueda estimar la dirección de movimiento comparando dos instantes temporales distintos. Esta funcionalidad depende de que los dos frames sean genuinamente distintos en el tiempo.

Un buffer de historial implementado como lista Python simple, actualizada sin verificación de timestamps, es vulnerable. Dos situaciones producen frames duplicados silenciosamente:

1. **Reinicio del buffer sin vaciado:** al saltar al siguiente waypoint, se vaciaba el historial pero el nodo de captura podía inyectar el último frame del waypoint anterior como "t-1" del nuevo waypoint. El VLM recibía el frame de un punto de la misión completamente distinto como contexto temporal inmediato.

2. **Ciclos donde `capture_node` no producía un frame nuevo:** si AirSim no respondía a tiempo (picos de carga de GPU), el buffer retenía el frame anterior. Bajo la etiqueta `[Fotograma t-1]` y `[Fotograma t]` aparecía la misma imagen.

El VLM, recibiendo dos frames idénticos, infería dos conclusiones posibles: el dron está estático (lo que puede ser correcto en hover pero es incorrecto durante crucero), o los objetos en escena están expandiéndose a velocidad cero (sin señal de aproximación). En ambos casos, la deliberación sobre movimiento y peligro era incorrecta de forma sistemática.

### 9.3.2 Mecanismo de contención

El buffer de historial se reimplementó como un `deque` de capacidad fija con control estricto de timestamps. Antes de incluir un frame en el prompt, se verifica:

- `timestamp_actual > timestamp_anterior` (frames genuinamente distintos en el tiempo)
- `delta_t < FRAME_HISTORY_MAX_STALENESS_MS` (el frame anterior no es demasiado antiguo — un frame de hace 3 s no aporta contexto temporal útil a 5 Hz)

Si la verificación falla, el prompt se adapta dinámicamente: en lugar de enviar dos frames etiquetados como `[t-1]` y `[t]`, envía un único frame etiquetado como `[ciclo actual]` con una nota explícita: "historial visual no disponible en este ciclo". Esto es más conservador pero menos peligroso que fabricar una secuencia temporal falsa.

**En el sistema descrito en el capítulo 5** no se envía historial temporal al VLM: la capa estratégica usa el fotograma del ciclo y el barrido, un fotograma por rumbo, ambos con su timestamp y su pose de captura (cap. 5, §5.10, §5.12); `VLM_FRAME_HISTORY_SIZE` vale 1. La lección se trasladó de lo temporal a lo espacial: el riesgo equivalente es enviar al modelo una etiqueta de orientación que no corresponde al fotograma (§9.8.1).

## 9.4 Falla 3 — Descalibración de escala en el canal de divergencia

### 9.4.1 Descripción del modo de falla

El canal de divergencia del `ObstacleField` (cap. 6, §6.7) estima $\partial u / \partial x + \partial v / \partial y$ usando `np.gradient()` sobre el campo de flujo. Un cálculo con gradientes de Sobel 3×3 sin el factor de normalización $1/8$ que el kernel estándar requiere para ser un estimador de derivada de primer orden en unidades de píxel-por-píxel:

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
- `_delib_memory`: debía acumular un historial corto de resultados de la consulta al VLM para que el VLM pudiera referirse a decisiones previas. No declarada → el historial siempre estaba vacío; cada ciclo el VLM era consultado sin contexto de lo que había decidido un ciclo antes.
- `_corner_wp`: debía inyectar un sub-waypoint de esquina intermedia para la maniobra `GIRAR_90`. No declarada → el comportamiento de giro lo escribía en su retorno y el decisor lo leía en el ciclo siguiente... como el valor inicial (None), nunca como el punto calculado.

El diagnóstico de estas tres claves requirió instrumentar el runtime con un interceptor de estado entre cada par de nodos — el equivalente de "printear el estado completo antes y después de cada nodo" — porque ningún log de nivel de aplicación mostraba el descarte.

**Vulnerabilidad B — Ciclo límite de período 3 en la red de seguridad.**

El mecanismo de reintento de maniobra de escape, con el defecto, funcionaba así:

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

Con el defecto, el decisor evaluaba las condiciones de escape de atasco *antes* de leer el `ObstacleField`:

```python
# con el defecto
if state["stall_count"] > hard_threshold:
    return "deadlock_escape"   # ← sin verificar percepción
if field.is_blocked("centro"):
    return "evasive"
```

La consecuencia era que en ciclos donde el estimador de flujo tenía evidencia válida de que un sector lateral estaba despejado (`has_open_corridor() = True`), el decisor seleccionaba igualmente la rama de escape de atasco. El dron ascendía aunque la percepción indicara una salida horizontal disponible. La corrección fue consultar `has_open_corridor()` como condición de guarda antes de activar el escape: si hay evidencia de corredor, la maniobra de escape no se activa aunque el contador de atasco haya excedido su umbral.

### 9.5.3 El ascenso acumulado como síntoma compuesto

La combinación de las cuatro vulnerabilidades produjo en una corrida de validación un ascenso acumulado de ~356 m en una sola misión. La secuencia causal fue:

1. `_reset_stall_counter` no declarada → `stall_count` creció desde el ciclo 1 sin resetearse al llegar a cada waypoint.
2. A los ~8 ciclos de misión, `stall_count > hard_threshold` a pesar de que el dron avanzaba normalmente.
3. El decisor activó `deadlock_escape` (ciego a percepción), que ejecutaba `GANAR_ALTURA` con deriva lateral no justificada.
4. `stall_count` se reseteó (ciclo límite B) → el siguiente ciclo, el decisor volvió a crucero normal.
5. `stall_count` volvió a crecer rápidamente (umbral demasiado bajo por la métrica inconsistente C).
6. El ciclo se repitió centenares de veces, produciendo un ascenso neto acumulado.

Desde el exterior, la corrida registraba una misión "sin errores" (no hay excepciones en el log) que simplemente "no llegó a destino". Sin el análisis del viewer frame a frame y la lectura del JSONL de auditoría, el patrón era opaco.

### 9.5.4 Instancias adicionales: estado descartado y precedencia entre rutas

Otras tres situaciones comparten la propiedad que organiza el capítulo: el sistema producía respuestas válidas y plausibles, sin excepciones en el log, y aun así no las ejecutaba.

**(a) Un flag descartado por LangGraph.** Un indicador que difería la inyección de un desvío hasta el escaneo siguiente se escribía correctamente pero no estaba declarado en `DroneState`. Desaparecía entre invocaciones de `graph.invoke()` y el desvío nunca se inyectaba: el dron volvía a la misma fachada. Se diagnosticó en una corrida en la que el indicador desaparecía antes del ciclo 1783. Es otra instancia de la Vulnerabilidad A (§9.5.2).

**(b) Resultados válidos del VLM que nunca se ejecutan.** Dos errores de *precedencia* entre rutas, no de estado descartado, con el mismo síntoma:

- *Maniobra cancelada por un disparador de atasco.* Si al despachar `EVADIR_DERECHA` no se reinicia el contador de atasco, en el ciclo siguiente un disparador basado en ese contador vuelve a enrutar hacia una nueva consulta, cuyo resultado sobrescribe la maniobra comprometida antes de que se ejecute. En la corrida `seed_99` el VLM devolvió `EVADIR_DERECHA` durante 200 ciclos consecutivos (c2585–c2784) sin que la maniobra se ejecutara una sola vez.
- *Resultado huérfano por el camino de deadlock.* Si la rama de escape por deadlock se evalúa antes que la lectura del pedido pendiente, y el contador de progreso queda congelado por encima del umbral mientras hay un pedido pendiente, la rama intercepta todos los ciclos y el resultado nunca se lee: en c2048–c2135 (80 ciclos) el log del VLM contenía la respuesta correcta —latencia real de 3 731 ms— y la acción ejecutada era `MANTENER_RUMBO` o `FRENAR`.

Ninguno de los dos se veía en las métricas agregadas. Ambos se encontraron comparando, ciclo a ciclo, el campo `slm.raw_response` de la traza JSONL con la acción realmente ejecutada; es decir, la técnica 2 de §9.7 (guardar los datos crudos enviados y recibidos por el modelo) fue la que los hizo visibles. Se previenen por construcción: un barrido en curso y una maniobra comprometida son las dos primeras condiciones que evalúa `navigate`, antes que cualquier disparador de atasco (cap. 5, §5.3.2), y el resultado de cada consulta se recupera por su identificador (`get_result`) al inicio de cada ciclo, de modo que no depende de qué ruta tome el ciclo.

**(c) Un pedido pendiente que nunca se cierra.** Por lectura de código —no reproducido en una corrida— existe una interacción sin resolver entre el pedido proactivo y el escaneo de resolución de atasco: ambos comparten la cola del servicio (tamaño 1), de modo que un escaneo que se encola mientras hay un pedido proactivo en vuelo lo invalida, y `_poll_vlm` solo cierra `slm_request_id` cuando llega un resultado con *ese* identificador. Si eso ocurre, `slm_request_id` permanece activo: `StallDetector` interpreta la espera como intencional y detiene los contadores de inmovilidad, y se inhiben nuevos pedidos proactivos y el escape vertical forzado. **Mecanismo de contención:** la consulta estratégica no usa `slm_request_id`; la capa estratégica da por perdido un pedido reemplazado si el servicio no tiene resultado ni pedido pendiente durante 3 s, o al cumplir 10 s, y el deadlock cancela explícitamente la consulta estratégica en vuelo (cap. 5, §5.10.3, §5.3.4).

## 9.6 Falla 5 — Degradaciones sensoriales silenciosas

### 9.6.1 Inversión de canales de color RGB/BGR

Durante varios meses de experimentación, el cliente de captura de AirSim (`AirSimClient.capture()`) entregaba el buffer de imagen en el orden de canales RGB nativo del motor Unreal, mientras que el pipeline asumía la convención BGR de OpenCV — la convención estándar de OpenCV en la que el canal azul ocupa el índice 0.

El efecto fotométrico es una inversión de los canales rojo y azul en cada píxel: fachadas de ladrillo rojo aparecen en tonos azulados, el cielo azul aparece amarillento, la vegetación adquiere colores no naturales. El VLM deliberativo — entrenado sobre datos fotométricamente correctos — deliberó durante esos meses sobre imágenes con espectro cromático sistemáticamente falso. En ningún momento emitió una queja sobre la calidad de las imágenes ni redujo su confianza en la decisión: el modelo de lenguaje no tiene acceso directo al historial de la distribución de datos sobre la que fue entrenado, y no puede detectar que la imagen recibida está fuera de distribución por inversión de canal.

El diagnóstico requirió guardar físicamente las imágenes enviadas al VLM al disco y abrirlas en un visor externo — el análogo de "mirar los datos crudos" que es el primer paso de depuración en visión por computadora pero que en un sistema integrado es fácil de omitir cuando el modelo "parece razonar correctamente".

La corrección fue añadir `cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)` en el punto de captura, con un test unitario que verifica el orden de canales comparando estadísticas de cada canal en una imagen de referencia conocida.

### 9.6.2 Contaminación por primitivas de depuración persistentes

El simulador AirSim/cosysairsim permite dibujar primitivas geométricas en el mundo virtual (`simPlotLineStrip`, `simPlotPoints`, `simPlotArrows`) para visualización durante el desarrollo: trayectorias planificadas, sectores del `ObstacleField`, vectores de flujo. Estas primitivas son *persistentes* en la sesión del simulador: no se borran al reiniciar el script de control, solo al llamar explícitamente `simFlushPersistentMarkers()`.

En varias sesiones de desarrollo, al relanzar el vuelo sin reiniciar AirSim, las primitivas de la sesión anterior permanecían en el mundo virtual. La cámara a bordo las capturaba como geometría física en la escena: franjas de colores brillantes cruzando el campo visual que el VLM interpretaba como cables, estructuras metálicas o señales de tráfico dependiendo del color y orientación.

La consecuencia fue particularmente difícil de diagnosticar porque el comportamiento variaba según el historial de la sesión: un vuelo iniciado después de reiniciar AirSim se comportaba normalmente, mientras que el mismo vuelo iniciado sin reiniciar producía evasiones espurias repetidas. [Jansen et al. (2023)](13-REFERENCIAS.md#ref-jansen-2023) documentan comportamientos similares de estado persistente en CosysAirSim como fuente de irreproducibilidad entre corridas.

La corrección fue añadir `simFlushPersistentMarkers()` al inicio de cada sesión de vuelo, con un segundo vaciado de primitivas antes de iniciar la fase de captura de imágenes para el VLM.

### 9.6.3 Supresión de ángulos de actitud en la telemetría

El binding `cosysairsim` usado en este proyecto (fork de AirSim con soporte UE5 — Jansen et al., 2023) no implementaba el método `to_eularian_angles()` del binding oficial de Microsoft AirSim. La llamada al método retornaba silenciosamente $(0, 0, 0)$ en lugar de lanzar `AttributeError`. El resultado era que los ángulos de pitch y roll reportados al VLM en cada prompt eran siempre `0.0°`, independientemente de la inclinación física real del vehículo.

Durante maniobras de aceleración (pitch negativo ~ −8° a −12°), descenso agresivo (pitch positivo) o giros (roll lateral), el VLM recibía la información de que el dron estaba perfectamente nivelado. La estimación de la componente de velocidad de cierre perpendicular al plano focal — que depende del pitch — era incorrecta, y la interpretación de la escena visual (la posición aparente del horizonte en la imagen) estaba desalineada con la información verbal de actitud.

La corrección fue implementar la conversión directa desde el cuaternión de orientación, disponible en la telemetría de CosysAirSim, a ángulos de Euler (roll, pitch, yaw) usando las fórmulas estándar de [Wahba (1965)](13-REFERENCIAS.md#ref-wahba-1965), sin depender del método del binding:

$$\phi = \arctan2(2(q_w q_x + q_y q_z),\ 1 - 2(q_x^2 + q_y^2))$$
$$\theta = \arcsin(2(q_w q_y - q_z q_x))$$
$$\psi = \arctan2(2(q_w q_z + q_x q_y),\ 1 - 2(q_y^2 + q_z^2))$$

Un test unitario verifica, contra una tabla de cuaterniones conocidos (identidad, 90° en cada eje, 45° combinado), que la conversión produce los ángulos correctos con error < 0.01°.

## 9.7 Por qué el sistema seguía funcionando: el problema de la observabilidad

Ninguno de los seis modos de falla descritos se manifestó como un error visible en tiempo de ejecución. En todos los casos:

- El modelo de lenguaje seguía produciendo respuestas JSON válidas y plausibles.
- El lazo de control ejecutaba el ciclo sin excepciones.
- Las métricas agregadas de la corrida (distancia recorrida, waypoints completados, velocidad media) no distinguían estas corridas de corridas fallidas por otras causas.

Esta propiedad tiene una implicación metodológica directa: las técnicas de depuración habituales para sistemas de software — observar el output, monitorear las métricas, leer el log de errores — son ciegas a esta clase de error. La observación del comportamiento es precisamente la herramienta menos útil porque el sistema exhibe comportamiento *consistente con sus premisas internas*, aunque esas premisas estén corrompidas. Esta dificultad no es exclusiva de este proyecto: el estudio de campo de [Amershi et al. (2019)](13-REFERENCIAS.md#ref-amershi-2019) sobre equipos de ingeniería de software que incorporan componentes de aprendizaje automático en Microsoft identifica, entre las diferencias estructurales frente al desarrollo de software tradicional, precisamente que los componentes de IA son más difíciles de aislar, probar y depurar como módulos independientes que el código determinista convencional — la ausencia de una frontera de excepción clara entre "el componente falló" y "el componente decidió mal" es un síntoma de esa misma dificultad, no una particularidad de los modos de falla de este capítulo.

Las técnicas de diagnóstico que sí funcionaron en este proyecto fueron:

**1. Auditoría de contratos en la frontera de cada componente.** Para cada par (productor, consumidor) de datos de estado, verificar explícitamente: ¿qué valor devuelve el productor cuando no tiene información? ¿Cómo interpreta el consumidor ese valor? La pregunta "¿qué pasa cuando este campo es None/vacío/cero?" tiene que tener una respuesta documentada y verificable.

**2. Guardar los datos crudos enviados al modelo.** El viewer (`airsim-runs/*.viewer.html`) guarda el fotograma anotado y el estado completo de cada ciclo precisamente para hacer auditable lo que el modelo recibía. Sin esa capacidad de inspección retroactiva, la falla de inversión RGB/BGR habría sido indetectable.

**3. Tests de invariantes de contrato, no de comportamiento.** Un test que verifique "el dron evadió el obstáculo" es frágil y dependiente de la escena. Un test que verifique "si `has_evidence()` es False, ningún consumidor reporta el campo como 'despejado'" es un test de contrato que captura la Falla 1 sin necesitar una corrida de vuelo.

**4. Inyección de valores límite en el estado de LangGraph.** Para detectar las claves no declaradas (Falla 4-A), la técnica fue instrumentar el lazo con un interceptor que comparaba `state` al entrar a cada nodo con `state` al salir, reportando cualquier clave presente en la salida que no estuviera en el `TypedDict`. Esta verificación se convirtió en un modo de debug permanente activable via variable de entorno (`LANGGRAPH_DEBUG_STATE_CLIPPING=1`).

## 9.8 Falla 6 — Integración del VLM: respuestas correctas ejecutadas al revés, ignoradas o casi constantes

Esta familia de fallas se identificó auditando 12 corridas de diagnóstico sobre `citysim_pilot` (ninguna completó la misión; tres terminaron por `physics_locked`) con la técnica 2 de §9.7: comparar, ciclo a ciclo, la respuesta cruda del modelo con la acción ejecutada y con la profundidad de referencia del simulador, consultada a posteriori solo para la auditoría. Como en las fallas anteriores, ninguno de los mecanismos produjo una excepción: el modelo respondía JSON válido, el lazo ejecutaba una acción en cada ciclo y las métricas agregadas registraban deadlocks «resueltos» en el 75–80 % de los casos.

### 9.8.1 Error de marco de referencia: «libre hacia la meta» ejecutado como «evadir a la izquierda»

En las tres corridas analizadas, el primer barrido panorámico respondió correctamente: `{"deg": -53, "tipo": "libre", "ok": true}` para la imagen tomada en el rumbo −53°, a ~16° del rumbo al waypoint. La acción ejecutada fue `EVADIR_IZQUIERDA`, y el dron giró alejándose de la meta. Dos inconsistencias de marco se combinaban:

1. Las imágenes se etiquetaban con su **rumbo absoluto** («[Rumbo −53°]») y el prompt pedía un ángulo **relativo**; el modelo copiaba la etiqueta y el parser interpretaba siempre el valor como relativo.
2. El error de rumbo hacia la meta se medía respecto del yaw **al final** del barrido (153°), no del yaw de cada imagen.

El dron se alejó de 82.6 m a 94–95 m del primer waypoint y tardó ~37 s en volver a la distancia de partida, en las tres corridas.

**Mecanismo de contención.** El modelo nunca reporta ángulos: identifica las imágenes por número, y el código asigna a cada una el yaw **medido** al capturarla y compara rumbos absolutos, calculando el rumbo a la meta desde las posiciones (cap. 5, §5.12). Un test reproduce el caso (`tests/test_deep_vlm_world_frame.py`).

### 9.8.2 Default silencioso: la respuesta del modelo nunca llegaba a la decisión

El productor de la respuesta devolvía una descripción de escena por sectores, mientras el consumidor leía `decision.get("macro_action", "EVADIR_DERECHA")`. Como la clave no existía, **toda respuesta se ejecutaba como `EVADIR_DERECHA`**, con razonamiento vacío: 11 de 15 despachos en las tres corridas, 5 de ellos contra un lado que el propio modelo había descrito como bloqueado. Es un caso de *schema drift* (§9.2) en sentido inverso: el productor y el consumidor no compartían esquema y el consumidor, en lugar de fallar, funcionaba con un valor por defecto plausible. Ningún test recorría el camino completo desde la respuesta hasta la acción.

**Mecanismo de contención.** Cada modo de consulta tiene un esquema estricto y un parser que lo valida; una respuesta que no coincide no produce ninguna acción (motivo `no_parseable`, registrado), nunca un valor por defecto (cap. 8, §8.2.2). Los tests de integración corren el grafo compilado de punta a punta, desde la respuesta del modelo hasta la sub-meta que llega al bucle externo (§9.9, riesgo A).

### 9.8.3 Salida casi constante del modelo

Se compararon las 185 respuestas del VLM con la profundidad de referencia registrada en las mismas corridas. En las consultas por sectores, excluida una corrida en vegetación, **52 de 53 respuestas declararon el frente transitable**; con la superficie más cercana a ≤ 1.2 m en los 8 s previos, 18 de 19 lo declararon igual. En los barridos, la primera imagen salió marcada como transitable en la gran mayoría de los casos, con valores (`"ok": true, "conf": 0.9`) idénticos al ejemplo del prompt. La respuesta, en la práctica, no dependía de la escena. Ninguno de los 8 deadlocks «resueltos» por el modelo en las tres corridas analizadas produjo avance neto hacia el waypoint (máximo 2.2 m en 10 s).

El hallazgo no se puede atribuir solo al modelo: el prompt contenía un ejemplo con valores concretos y una frase que pedía priorizar evasiones, contradictoria con la instrucción de solo describir, y la pregunta («¿se puede avanzar en este sector?») se hacía sobre imágenes de 256–384 px.

**Mecanismo de contención.** La pregunta, la granularidad y el prompt del sistema están diseñados contra estas causas (cap. 8, §8.3–§8.5), y la métrica de distribución de resultados de la capa estratégica (cap. 10, §10.6.3) permite medir si el modelo discrimina. Que lo logre es una pregunta empírica abierta (§9.9, riesgo D).

### 9.8.4 Deadlock falso en el despegue

En el 100 % de las corridas el primer deadlock se declaró en los ciclos 17–18, con el dron todavía subiendo a la altitud de crucero. Durante el despegue el guiado ordena subir y girar en el lugar hacia el primer waypoint con `vx = 0`; un contador de «detenido» que sumaba esos ciclos disparó, al cruzar el piso óptico de 4.5 m, la resolución de atasco.

**Mecanismo de contención.** «Detenido» se define como «se ordenó avanzar y el dron no se movió», y no se cuenta bajo el piso óptico (cap. 5, §5.3.1). Reproduciendo esa definición sobre la telemetría registrada, ninguna de las tres corridas habría declarado ese deadlock.

### 9.8.5 Una señal de verdad de terreno dentro del brazo evaluado

El runner capturaba el canal de profundidad del simulador «solo como métrica». Esa misma captura terminó armando un freno de proximidad que el grafo consumía, cancelaba maniobras, inyectaba retrocesos y registraba puntos de contacto que el tracker usaba para validar desvíos. El brazo evaluado tenía, así, acceso indirecto a la profundidad exacta del simulador, lo que invalida su comparación con un sistema monocular. La guardia estática no lo detectó porque el runner estaba fuera de su alcance.

**Mecanismo de contención.** Ningún componente del lazo de vuelo lee el canal de profundidad, tampoco como métrica, y la guardia (`test_no_depth_in_flight_path.py`) cubre el runner, `main.py` y todos los módulos de vuelo, incluido el canal indirecto (cap. 5, §5.16).

### 9.8.6 Reglas apiladas sobre la decisión del modelo

Cada falla observada en corridas piloto se había compensado con una regla determinista: retroceder antes del barrido, escalar a un retroceso si el modelo alternaba de lado, inyectar un desvío perpendicular con el lado invertido respecto del modelo, cinco reglas sobre la historia de la trayectoria, un escape vertical tras escaneos «fútiles» y, en el tracker, filtros que reflejaban o descartaban los desvíos. Para cuando el VLM respondía, su decisión pasaba por hasta seis capas de reescritura; el brazo `slm` medía esas reglas tanto como al modelo.

Medidas contra el avance hacia el waypoint real en los 10–20 s siguientes, ninguna mostró beneficio. Los retrocesos tuvieron avance mediano negativo (en el 31–43 % de los casos alejaron al dron más de 2 m); 74 desvíos deterministas dieron una mediana de 0.35 m de avance en 20 s, 16 de ellos alejaron al dron más de 2 m y llevaron al dron sobre la autopista elevada; y un disparador de deadlock basado en la historia de la trayectoria produjo 45 deadlocks sin avance posterior. Solo el lazo reactivo (guiado, evasión por flujo, giro de 90°) mostró avance mediano positivo.

La lección metodológica es la de §9.7 aplicada al diseño: una regla que corrige un síntoma observado en una corrida, sin medir su efecto agregado, no se puede distinguir —desde las métricas de éxito— de una regla que empeora el sistema.

**Mecanismo de contención.** La respuesta del modelo se traduce a geometría y se aplica sin reglas que la reemplacen; solo se descartan respuestas obsoletas (cap. 5, §5.16). El criterio para incluir un componente en el lazo es haber mostrado avance hacia el waypoint real, o ser parte del lazo rápido común a los tres brazos.

### 9.8.7 La causa física de los `physics_locked`

En las tres corridas el dron no chocó de frente: quedó apoyado sobre una **superficie horizontal a la altura de crucero** —el tablero de una autopista elevada (dos corridas) y la cornisa de un edificio (una)—, con los sectores frontales del flujo libres (`occ = 0`, TTC infinito). En una corrida, un `GANAR_ALTURA` liberó al dron hasta −12.2 m y el guiado de altitud lo devolvió a −10 m, sobre la cornisa. Ni el flujo óptico ni una descripción por sectores representan ese tipo de obstáculo.

**Mecanismo de contención.** El manifiesto evita la autopista (`WP_0_SUR`, cap. 10 §10.3.3), la capa estratégica pregunta explícitamente por `estructura_debajo` y sube la sub-meta, y el escape determinista ante falla del VLM es `GANAR_ALTURA` (cap. 5, §5.3.4, §5.10).

## 9.9 Riesgos residuales y trabajo pendiente

Los modos de falla documentados tienen su mecanismo de contención en el sistema, incluido el caso (c) de §9.5.4. Los de §9.8 están contenidos en el código y cubiertos por tests, pero ninguna corrida en el simulador los ha verificado todavía. La arquitectura contiene puntos donde pueden aparecer instancias análogas:

**Riesgo A — Nuevas claves de DroneState.** Cada vez que se añade una funcionalidad que requiere persistir estado entre ciclos, existe el riesgo de que la clave correspondiente no se declare en `DroneState`. La mitigación es el modo `LANGGRAPH_DEBUG_STATE_CLIPPING=1` y el proceso de revisión de `DroneState` antes de cada nueva funcionalidad. El riesgo se materializó en más de una ocasión (§9.5.2 y §9.5.4), lo que indica que la mitigación depende demasiado de la disciplina manual. Los tests de integración corren el grafo compilado y verifican que las claves de control (`inject_corner`, `_escape_reset`, `_deadlock_event`, `_vlm_strategic`) cruzan la frontera de `graph.invoke()` (`tests/test_graph_integration.py`, `tests/test_vlm_strategic_graph.py`). Una defensa más general sería un test de contrato que recorra el código fuente de `src/agents/`, extraiga todas las claves `state["_..."]` y `state.get("...")` y falle si alguna no pertenece a `DroneState`; hoy no existe.

**Riesgo B — Cambios de API del binding de AirSim.** El binding `cosysairsim` es un fork activamente mantenido ([Jansen et al., 2023](13-REFERENCIAS.md#ref-jansen-2023)). Actualizaciones del binding pueden modificar el comportamiento de métodos (como ocurrió con la corrección del cuaternión). Los tests unitarios de conversión de telemetría son la mitigación; deben ejecutarse tras cada actualización del binding.

**Riesgo C — Distribución de imágenes fuera del dominio de entrenamiento del VLM.** La corrección de inversión RGB/BGR es una transformación fija. Pero la brecha de dominio entre imágenes de AirSim/UE5 y el dominio de entrenamiento del VLM (predominantemente imágenes reales del mundo) es una fuente estructural de error que no se elimina con ninguna corrección puntual. La calibración de la frecuencia de respuestas subóptimas del VLM en los escenarios de esta tesis (cap. 11) es el mecanismo de caracterización de ese riesgo residual.

**Riesgo D — Que el VLM no discrimine.** El diseño corrige cómo se pregunta y cómo se usa la respuesta, pero no puede garantizar que Qwen2.5-VL-3B distinga columnas volables de bloqueadas mejor de lo que distinguía sectores (§9.8.3). Si la distribución de resultados de la capa estratégica (cap. 10, §10.6.3) muestra `directo_libre` en casi todas las consultas, también en las corridas que terminan en deadlock, la conclusión correcta será que el modelo no aporta información útil en este dominio, no una nueva regla que lo compense.
