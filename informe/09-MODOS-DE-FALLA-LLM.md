# 9. Modos de falla en lazos de control híbridos con LLM

## 9.1 El argumento central: contratos de interfaz como vector de falla primario

En sistemas robóticos que combinan percepción clásica, orquestación de grafo de control y un modelo de lenguaje, la intuición natural sobre modos de falla apunta al modelo: respuestas alucinadas, razonamiento incorrecto, formato inválido. La auditoría de este sistema señala, durante el desarrollo, en una dirección diferente: los fallos más costosos de diagnosticar —en horas de trabajo y en consecuencias en vuelo— ocurrieron en los **contratos de interfaz entre componentes**, no en las respuestas del modelo. Los casos de este capítulo son de corridas de diagnóstico con configuraciones anteriores a la evaluada en el capítulo 11, no de la corrida v4, y se documentan como casos, sin una medición de su frecuencia. Su importancia no termina en el costo de diagnóstico: mientras estas fallas existieron, impidieron saber si el modelo discriminaba la escena. Una vez contenidas, el banco de prueba mostró que no lo hace (§9.9, riesgo D; cap. 11, §11.0): el límite final fue la capacidad del modelo, y la interfaz fue lo que impidió verlo antes.

Un modelo de lenguaje tiene una propiedad que lo hace especialmente peligroso en este contexto: raciocina sobre lo que recibe, no sobre la realidad. Si recibe un resumen de percepción que dice "camino despejado", produce una respuesta consistente con esa premisa. No tiene acceso privilegiado a la verdad del mundo — solo al texto que se le entrega. El corolario es que cualquier corrupción, omisión o malinterpretación en los datos que llegan al modelo produce decisiones estructuralmente correctas pero factualmente equivocadas, sin que el modelo (ni el sistema) lo detecte como error. El sistema "funciona" — no arroja excepciones, no se cae, produce salida JSON válida — mientras toma decisiones sistemáticamente incorrectas. Esta propiedad no es una idiosincrasia de este sistema: es la manifestación, en un lazo de control robótico, del problema general de las respuestas fluidas y plausibles pero no fundamentadas en la entrada real (*hallucination*) documentado extensamente en la literatura de generación de lenguaje natural ([Ji et al., 2023](13-REFERENCIAS.md#ref-ji-2023)), agravado aquí por el hecho de que la salida del modelo no es texto para un lector humano crítico, sino una entrada del control de un vehículo físico. En la arquitectura vigente esa salida ya no comanda: se traduce a una sub-meta geométrica que el lazo rápido persigue (cap. 5, §5.10), y en la configuración evaluada el modelo no interviene en vuelo.

Este capítulo documenta seis familias de fallas estructurales, observadas en corridas de diagnóstico de la arquitectura y organizadas por la capa del sistema donde se originan. Para cada una se describe el mecanismo, la evidencia que lo muestra y el mecanismo de contención que tiene el sistema. La tabla siguiente resume la taxonomía:

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

Si el estado del campo de obstáculos se comunica como una lista de objetos detectados (`detected_obstacles: List[dict]`), con una lista vacía como valor por defecto, la lista vacía es ambigua: puede significar "la percepción corrió y no detectó nada" (espacio despejado) o "la percepción no corrió, no tiene confianza, o falló silenciosamente" (ausencia de información).

Los consumidores —la capa de decisión, el constructor del prompt del VLM y la FSM— tienden a resolver esa ambigüedad en favor de la primera interpretación. En una configuración de diagnóstico con ese contrato, la cadena fue:

1. El generador de contexto construía un prompt que afirmaba al modelo "trayectoria frontal sin obstáculos detectados".
2. El VLM, con perfecta coherencia lógica respecto de la información provista, respondía que se podía seguir con alta confianza.
3. El lazo ejecutaba la maniobra de crucero normal.
4. No se generaba ninguna excepción ni alerta de log, porque desde la perspectiva del código la lista vacía es un valor válido.

Este patrón es una instancia de un anti-patrón de diseño general — tratar el valor neutro de un tipo de dato (lista vacía, cero, `None`) como evidencia de ausencia de fenómeno, en lugar de como ausencia de información — que colapsa dos estados epistémicos distintos en una única representación. En señales de seguridad la distinción es crítica y la convención correcta es la inversa: la ausencia de evidencia no es evidencia de ausencia de peligro, principio formulado explícitamente para la interpretación de resultados nulos en [Altman y Bland (1995)](13-REFERENCIAS.md#ref-altman-1995) y que aquí se aplica a un contrato de datos entre percepción y control en lugar de a la interpretación estadística de un experimento.

### 9.2.2 Mecanismo de contención

El contrato de percepción es el tipo `ObstacleField` (cap. 6): un objeto inmutable que distingue explícitamente tres estados epistémicos:

- `source = "flow"`, `foe_confidence > 0`: la percepción corrió con evidencia real. Los valores de TTC y ocupación son interpretables.
- `source = "flow"`, `foe_confidence = 0`: la percepción corrió pero no produjo evidencia confiable (FOE fuera de imagen, menos de 30 inliers). Interpretable como "sin información".
- `source = "degraded"`: la percepción fue inhibida activamente (guard de rotación, modo degradado, primer ciclo). El campo no contiene ninguna información sobre el mundo.

La invariante que impone `ObstacleField` es que **ningún consumidor puede confundir "sin obstáculos detectados" con "sin información"** sin leer explícitamente `has_evidence()`. La falta de evidencia tiene consecuencias explícitas: el gobernador de velocidad limita el avance tras varios ciclos sin evidencia (cap. 5, §5.13) y `has_open_corridor()` no declara corredor libre sin evidencia (cap. 6, §6.11). La capa estratégica no recibe el campo: mira el fotograma directamente (cap. 5, §5.10).

## 9.3 Falla 2 — Desalineación temporal del historial de frames

### 9.3.1 Descripción del modo de falla

Una consulta multimodal que envía al VLM un historial de dos frames ($t$ y $t-1$), para que el modelo estime la dirección de movimiento, depende de que los dos frames sean genuinamente distintos en el tiempo. Un buffer implementado como lista simple, actualizado sin verificar timestamps, produce frames duplicados o fuera de contexto en dos situaciones:

1. **Cambio de waypoint:** si al saltar al siguiente waypoint el nodo de captura inyecta el último frame del tramo anterior como "t-1", el VLM recibe el frame de un punto de la misión completamente distinto como contexto temporal inmediato.
2. **Ciclos sin frame nuevo:** si AirSim no responde a tiempo (picos de carga de GPU), el buffer retiene el frame anterior, y bajo las etiquetas `[Fotograma t-1]` y `[Fotograma t]` aparece la misma imagen.

Con dos frames idénticos, el modelo infiere que el dron está estático o que nada se acerca. En ambos casos, la deliberación sobre movimiento y peligro es incorrecta de forma sistemática.

### 9.3.2 Mecanismo de contención

El sistema no envía historial temporal al VLM: `VLM_FRAME_HISTORY_SIZE` vale 1, y la capa estratégica usa el fotograma del ciclo y el barrido un fotograma por rumbo, cada uno con su timestamp y su pose de captura (cap. 5, §5.4, §5.10, §5.12). El riesgo equivalente pasa a ser espacial: enviar al modelo una etiqueta de orientación que no corresponde al fotograma (§9.8.1), y se contiene anclando cada respuesta a la pose medida del fotograma que la originó.

## 9.4 Falla 3 — Descalibración de escala en el canal de divergencia

### 9.4.1 Descripción del modo de falla

El canal de divergencia del `ObstacleField` (cap. 6, §6.7) estima $\partial u / \partial x + \partial v / \partial y$ sobre el campo de flujo. Un cálculo con gradientes de Sobel 3×3 sin el factor de normalización $1/8$, que el kernel estándar requiere para ser un estimador de derivada de primer orden en unidades de píxel-por-píxel,

$$K_{\text{Sobel}} = \frac{1}{8}\begin{pmatrix} -1 & 0 & 1 \\ -2 & 0 & 2 \\ -1 & 0 & 1 \end{pmatrix}$$

produce divergencias aproximadamente 8 veces mayores que las correctas. Con un factor de ocupación ajustado sobre esa escala inflada, el canal de ocupación satura a `1.0` en condiciones de textura moderada — es decir, prácticamente siempre que haya cualquier gradiente de flujo en la imagen, incluso en vuelo en espacio abierto sin obstáculos cercanos.

La consecuencia operativa es que el predicado disyuntivo `is_blocked()` (§6.9) queda dominado completamente por el canal de ocupación: aunque el TTC indique una zona segura (> 4 s), la ocupación saturada vota bloqueo, y el canal de TTC calibrado queda efectivamente anulado.

### 9.4.2 Interacción con la lógica disyuntiva

Este modo de falla ilustra un problema de diseño de predicados disyuntivos en sistemas con múltiples canales de diferente confianza. La lógica $\text{is\_blocked} = (\text{occ} \geq t_{occ}) \lor (\text{conf} \geq 0.35 \land \text{ttc} \leq 2.5)$ asume que ambos canales están calibrados en escalas comparables. Si un canal está sistemáticamente sobre-estimado, la disyunción lo convierte en el canal dominante y anula la información del otro. El TTC, que tiene validación empírica (cap. 7), pierde toda influencia frente a una ocupación descalibrada. El caso inverso también ocurre: un umbral de ocupación demasiado alto para la escala real del canal lo deja mudo y la detección recae solo en el TTC (cap. 7, §7.5).

### 9.4.3 Mecanismo de contención

La contención tiene tres partes:
1. La divergencia se calcula con `np.gradient()` (diferencias centradas de segundo orden, normalizadas intrínsecamente).
2. El umbral de ocupación está calibrado contra profundidad de referencia por curva ROC (cap. 7, §7.5: `OBSTACLE_OCCUPANCY_BLOCKED` = 0.011).
3. Los dos canales tienen umbrales de confianza diferenciados (`MIN_CONFIDENCE_FOR_BLOCKED = 0.15` vs. `MIN_CONFIDENCE_FOR_TTC_BLOCKED = 0.35`), de modo que el canal de TTC requiere mayor confianza para votar solo que el canal de ocupación acompañado de confianza mínima.

La tercera medida es especialmente importante: la normalización corrige la escala, pero el sistema necesita ser robusto a recalibraciones futuras. Los umbrales diferenciados hacen que ningún canal pueda dominar completamente al otro sin confianza suficiente.

## 9.5 Falla 4 — State clipping y ciclos límite en LangGraph

Esta familia es la más costosa en consecuencias observadas (un ascenso acumulado de ~356 m en una sola corrida de diagnóstico) y la más ilustrativa de los riesgos de orquestadores de grafos que descartan silenciosamente estado no declarado.

### 9.5.1 El mecanismo de descarte silencioso de LangGraph

LangGraph construye los canales de estado de un `StateGraph` a partir de un `TypedDict` declarado en tiempo de compilación (`build_workflow()`). En cada invocación del grafo (`graph.invoke(state)`), el runtime fusiona el estado de salida de cada nodo con el estado entrante usando únicamente las claves presentes en el `TypedDict`. Cualquier clave que un nodo escriba en su diccionario de retorno pero que no esté declarada es **descartada silenciosamente** — sin excepción, sin advertencia, sin registro en el log. El nodo siguiente recibe un estado donde esa clave no existe o tiene el valor por defecto del último ciclo en que sí estaba.

El mecanismo específico importa: el `TypedDict` de Python es una anotación de tipos, no una estructura de datos con validación en tiempo de ejecución. `state["clave_nueva"] = valor` no falla aunque `clave_nueva` no esté en el `TypedDict`; simplemente el runtime de LangGraph no la persiste en el canal de estado entre invocaciones (cap. 5, §5.2).

### 9.5.2 Cuatro vulnerabilidades

**Vulnerabilidad A — Claves de control no declaradas.**

En corridas de diagnóstico, tres claves de control cruzaban la frontera entre nodo y lazo sin estar declaradas en `DroneState`:

- `_reset_stall_counter`: debía reiniciar el contador de progreso estancado al llegar a un waypoint. No declarada, el contador crece monótonamente desde el inicio de la misión, independientemente del progreso real.
- `_delib_memory`: debía acumular un historial corto de resultados de la consulta al VLM. No declarada, el historial está siempre vacío y el VLM se consulta sin contexto de lo que decidió un ciclo antes.
- `_corner_wp`: debía inyectar un sub-waypoint de esquina para la maniobra `GIRAR_90`. No declarada, el decisor la lee en el ciclo siguiente como el valor inicial (`None`), nunca como el punto calculado.

Ningún log de nivel de aplicación muestra el descarte; diagnosticarlo exige comparar el estado completo antes y después de cada invocación.

**Vulnerabilidad B — Ciclo límite de período 3 en la red de seguridad.**

Un mecanismo de escape que se resetea a sí mismo,

```
si stall_count > hard_threshold:
    activar FRENAR (ciclo 1)
    si stall_count > hard_threshold + N:
        resetear stall_count = 0  ← la red de seguridad se resetea a sí misma
```

convierte el estado "atasco severo → acción de escape" en un estado transitorio: al ciclo siguiente, `stall_count = 0 < hard_threshold` y el sistema vuelve a crucero; tres ciclos después, el atasco se re-detecta y el ciclo se repite. El período 3 (crucero → pre-stall → escape → reseteo → crucero) no es observable como un error: en el visor se ve como "el dron frena ocasionalmente sin razón aparente".

**Vulnerabilidad C — Métrica de progreso auto-inconsistente.**

Un predicado de atasco `ciclos_sin_progreso > effective_stall_threshold`, con `effective_stall_threshold = max(10, eps_m / (min_speed / loop_hz))`, combina `eps_m` (distancia mínima de avance por ciclo) y `min_speed` (velocidad mínima de crucero), definidos en unidades y archivos distintos. Con `eps_m = 0.5 m`, `min_speed = 2.0 m/s` y `loop_hz = 5 Hz`, la velocidad de avance implícita es 2.5 m/s, mientras que en un giro de 90° la velocidad de aproximación al waypoint oscila entre 0 y `vx · cos(θ)`, con media ≈ 1.25 m/s. El resultado es un detector de atasco que se dispara prácticamente al inicio de cada waypoint que requiera maniobra.

**Vulnerabilidad D — Escape ciego a la percepción.**

Si el decisor evalúa las condiciones de escape de atasco *antes* de leer el `ObstacleField`,

```python
if state["stall_count"] > hard_threshold:
    return "deadlock_escape"   # ← sin verificar percepción
if field.is_blocked("centro"):
    return "evasive"
```

el dron asciende aunque el estimador de flujo tenga evidencia válida de un sector lateral despejado.

### 9.5.3 El ascenso acumulado como síntoma compuesto

La combinación de las cuatro vulnerabilidades produjo, en una corrida de diagnóstico, un ascenso acumulado de ~356 m en una sola misión:

1. `_reset_stall_counter` no declarada → `stall_count` creció desde el ciclo 1 sin resetearse al llegar a cada waypoint.
2. A los ~8 ciclos de misión, `stall_count > hard_threshold` a pesar de que el dron avanzaba normalmente.
3. El decisor activó el escape (ciego a la percepción), que ejecutaba `GANAR_ALTURA` con deriva lateral.
4. `stall_count` se reseteó (ciclo límite B) → al ciclo siguiente, el decisor volvió a crucero.
5. `stall_count` volvió a crecer rápidamente (umbral demasiado bajo por la métrica inconsistente C).
6. El ciclo se repitió centenares de veces, con un ascenso neto acumulado.

Desde el exterior, la corrida registraba una misión "sin errores" (no hay excepciones en el log) que simplemente "no llegó a destino". Sin el análisis del visor cuadro a cuadro y la lectura del JSONL de auditoría, el patrón es opaco.

### 9.5.4 Instancias adicionales: estado descartado y precedencia entre rutas

Otras tres situaciones comparten la propiedad que organiza el capítulo: el sistema produce respuestas válidas y plausibles, sin excepciones en el log, y aun así no las ejecuta.

**(a) Un flag descartado por LangGraph.** Un indicador que difería la inyección de un desvío hasta el escaneo siguiente se escribía correctamente pero no estaba declarado en `DroneState`; desaparecía entre invocaciones y el desvío nunca se inyectaba, de modo que el dron volvía a la misma fachada. Es otra instancia de la Vulnerabilidad A.

**(b) Resultados válidos del VLM que nunca se ejecutan.** Dos errores de *precedencia* entre rutas, no de estado descartado, con el mismo síntoma:

- *Maniobra cancelada por un disparador de atasco.* Si al despachar `EVADIR_DERECHA` no se reinicia el contador de atasco, en el ciclo siguiente un disparador basado en ese contador vuelve a enrutar hacia una nueva consulta, cuyo resultado sobrescribe la maniobra comprometida antes de que se ejecute. En una corrida de diagnóstico, el VLM devolvió `EVADIR_DERECHA` durante 200 ciclos consecutivos sin que la maniobra se ejecutara una sola vez.
- *Resultado huérfano por el camino de deadlock.* Si la rama de escape por deadlock se evalúa antes que la lectura del pedido pendiente, y el contador de progreso queda congelado por encima del umbral, la rama intercepta todos los ciclos y el resultado nunca se lee: durante 80 ciclos, el log del VLM contenía la respuesta correcta y la acción ejecutada era `MANTENER_RUMBO` o `FRENAR`.

Ninguno de los dos se ve en las métricas agregadas; los muestra la comparación, ciclo a ciclo, del campo `slm.raw_response` de la traza JSONL con la acción realmente ejecutada (técnica 2 de §9.7).

**(c) Un pedido pendiente que nunca se cierra.** Si la consulta estratégica y el barrido comparten la cola del servicio (tamaño 1), un barrido que se encola mientras hay una consulta estratégica en vuelo la invalida. Si el sistema solo cerrara el pedido al llegar un resultado con *ese* identificador, el pedido quedaría activo indefinidamente, y un detector de atasco que interpretara la espera como intencional detendría sus contadores.

### 9.5.5 Mecanismo de contención

- **Estado declarado y verificado sobre el grafo compilado.** Todo campo que cruza la frontera entre invocaciones está declarado en `DroneState`, los contadores de atasco y el estado de la capa estratégica viven en objetos de proceso (`StallDetector`, `StrategicLayer`) y no en el estado, y los tests de integración corren el **grafo compilado** y verifican que las claves de control (`inject_corner`, `_escape_reset`, `_deadlock_event`, `_vlm_strategic`) cruzan la frontera (cap. 5, §5.2; `tests/test_graph_integration.py`, `tests/test_vlm_strategic_graph.py`).
- **Escape absorbente.** Un barrido en curso es dueño del dron hasta resolver o caer por sus watchdogs, y el deadlock se reinicia solo cuando se resuelve (`_escape_reset`), nunca dentro de su propia rama (cap. 5, §5.3.2, §5.3.4).
- **Progreso físicamente alcanzable.** El progreso se mide como distancia horizontal al objetivo, y los umbrales de atasco se derivan del avance mínimo demostrable a la velocidad mínima (cap. 5, §5.3.1, §5.15.2).
- **Precedencia explícita.** El orden de las reglas de `navigate` es fijo y está justificado (cap. 5, §5.3.2): barrido en curso, deadlock, maniobra comprometida, contacto, piso óptico y TTC. El resultado de cada consulta se recupera por su identificador (`get_result`) al inicio de cada ciclo, de modo que no depende de qué ruta tome el ciclo. En la FSM, el escape exige además que la percepción no muestre un corredor libre (`has_open_corridor()`, cap. 6, §6.11).
- **Pedidos perdidos.** La capa estratégica da por perdido un pedido reemplazado si el servicio no tiene resultado ni pedido pendiente durante 3 s, o al cumplir 10 s, y el deadlock cancela explícitamente la consulta estratégica en vuelo (cap. 5, §5.10.3, §5.3.4).

## 9.6 Falla 5 — Degradaciones sensoriales silenciosas

### 9.6.1 Inversión de canales de color RGB/BGR

`simGetImages` entrega el buffer de imagen en el orden RGB del motor, mientras que OpenCV y el resto del pipeline asumen la convención BGR, en la que el canal azul ocupa el índice 0. Sin conversión, cada píxel tiene los canales rojo y azul invertidos: fachadas de ladrillo rojo en tonos azulados, cielo amarillento, vegetación de colores no naturales. Un VLM entrenado sobre datos fotométricamente correctos delibera sobre esas imágenes sin emitir ninguna queja sobre su calidad ni reducir su confianza: no tiene cómo detectar que la imagen recibida está fuera de distribución por inversión de canal.

Detectarlo exige guardar en disco las imágenes exactas enviadas al VLM y abrirlas en un visor externo — el análogo de "mirar los datos crudos", primer paso de depuración en visión por computadora pero fácil de omitir en un sistema integrado cuando el modelo "parece razonar correctamente".

**Mecanismo de contención.** `AirSimClient.capture()` invierte el orden de canales en el punto de captura (cap. 3, §3.3), y cada consulta del lazo lento guarda sus fotogramas exactos como `photo-*.png` de auditoría (cap. 4, §4.4).

### 9.6.2 Contaminación por primitivas de depuración persistentes

El simulador AirSim/cosysairsim permite dibujar primitivas geométricas en el mundo virtual (`simPlotLineStrip`, `simPlotPoints`, `simPlotArrows`) para visualización durante el desarrollo: trayectorias planificadas, sectores del `ObstacleField`, vectores de flujo. Estas primitivas son *persistentes* en la sesión del simulador: no se borran al reiniciar el script de control, solo al llamar explícitamente `simFlushPersistentMarkers()`.

Al relanzar un vuelo sin reiniciar AirSim, las primitivas de la sesión anterior permanecen en el mundo virtual y la cámara a bordo las captura como geometría física: franjas de colores brillantes que el VLM interpreta como cables, estructuras metálicas o señales de tráfico. El comportamiento depende entonces del historial de la sesión: un vuelo iniciado tras reiniciar AirSim se comporta normalmente, y el mismo vuelo sin reiniciar produce evasiones espurias repetidas. [Jansen et al. (2023)](13-REFERENCIAS.md#ref-jansen-2023) documentan comportamientos similares de estado persistente en CosysAirSim como fuente de irreproducibilidad entre corridas.

**Mecanismo de contención.** Cada sesión de conexión empieza con `AirSimClient.clear_debug_markers()`, que invoca `simFlushPersistentMarkers()` (cap. 3, §3.3).

### 9.6.3 Supresión de ángulos de actitud en la telemetría

El binding `cosysairsim` (fork de AirSim con soporte UE5 — Jansen et al., 2023) no implementa el método `to_eularian_angles()` del binding oficial de Microsoft AirSim. Un fallback que no lo note reporta pitch y roll en `0.0°` en cada ciclo, independientemente de la inclinación física del vehículo. Durante maniobras de aceleración (pitch de −8° a −12°), descenso agresivo o giros, el sistema recibe la información de que el dron está perfectamente nivelado: la derotación del flujo óptico pierde dos de sus tres ejes y cualquier consumidor de la actitud queda desalineado con la imagen.

**Mecanismo de contención.** El cliente convierte directamente el cuaternión de orientación, disponible en la telemetría de CosysAirSim, a ángulos de Euler (roll, pitch, yaw) con las fórmulas estándar de [Wahba (1965)](13-REFERENCIAS.md#ref-wahba-1965), sin depender del método del binding:

$$\phi = \arctan2(2(q_w q_x + q_y q_z),\ 1 - 2(q_x^2 + q_y^2))$$
$$\theta = \arcsin(2(q_w q_y - q_z q_x))$$
$$\psi = \arctan2(2(q_w q_z + q_x q_y),\ 1 - 2(q_y^2 + q_z^2))$$

Un test unitario (`tests/test_airsim_client_telemetry.py`) verifica la conversión contra cuaterniones conocidos.

## 9.7 Por qué el sistema sigue funcionando: el problema de la observabilidad

Ninguno de los seis modos de falla descritos se manifiesta como un error visible en tiempo de ejecución. En todos los casos:

- El modelo de lenguaje sigue produciendo respuestas JSON válidas y plausibles.
- El lazo de control ejecuta el ciclo sin excepciones.
- Las métricas agregadas de la corrida (distancia recorrida, waypoints completados, velocidad media) no distinguen estas corridas de corridas fallidas por otras causas.

Esta propiedad tiene una implicación metodológica directa: las técnicas de depuración habituales para sistemas de software — observar el output, monitorear las métricas, leer el log de errores — son ciegas a esta clase de error. La observación del comportamiento es precisamente la herramienta menos útil porque el sistema exhibe comportamiento *consistente con sus premisas internas*, aunque esas premisas estén corrompidas. Esta dificultad no es exclusiva de este proyecto: el estudio de campo de [Amershi et al. (2019)](13-REFERENCIAS.md#ref-amershi-2019) sobre equipos de ingeniería de software que incorporan componentes de aprendizaje automático en Microsoft identifica, entre las diferencias estructurales frente al desarrollo de software tradicional, precisamente que los componentes de IA son más difíciles de aislar, probar y depurar como módulos independientes que el código determinista convencional — la ausencia de una frontera de excepción clara entre "el componente falló" y "el componente decidió mal" es un síntoma de esa misma dificultad, no una particularidad de los modos de falla de este capítulo.

Las técnicas de diagnóstico que sí funcionan son:

**1. Auditoría de contratos en la frontera de cada componente.** Para cada par (productor, consumidor) de datos de estado, verificar explícitamente: ¿qué valor devuelve el productor cuando no tiene información? ¿Cómo interpreta el consumidor ese valor? La pregunta "¿qué pasa cuando este campo es None/vacío/cero?" tiene que tener una respuesta documentada y verificable.

**2. Guardar los datos crudos enviados al modelo.** El registro de vuelo guarda el fotograma exacto de cada consulta, el prompt, la respuesta cruda y el estado completo de cada ciclo, y el visor (`*.viewer.html`) los muestra sincronizados con el video (cap. 4, §4.4), precisamente para hacer auditable lo que el modelo recibió. Sin esa capacidad de inspección retroactiva, la inversión RGB/BGR sería indetectable.

**3. Tests de invariantes de contrato, no de comportamiento.** Un test que verifique "el dron evadió el obstáculo" es frágil y dependiente de la escena. Un test que verifique "si `has_evidence()` es False, ningún consumidor reporta el campo como 'despejado'" es un test de contrato que captura la Falla 1 sin necesitar una corrida de vuelo.

**4. Tests sobre el grafo compilado.** Las claves no declaradas (Falla 4-A) no aparecen en tests que llaman a los nodos como funciones sueltas, porque el descarte ocurre en el runtime de LangGraph. Los tests de integración del sistema compilan el grafo y verifican qué claves sobreviven a `graph.invoke()` (§9.5.5), y cada secuencia de falla observada en una corrida piloto tiene un test de regresión que la reproduce sobre el grafo compilado (§9.8).

## 9.8 Falla 6 — Integración del VLM: respuestas correctas ejecutadas al revés, ignoradas o casi constantes

Esta familia se identifica auditando corridas de diagnóstico sobre `citysim_pilot` con el VLM como fuente del lazo lento (doce corridas, ninguna completó la misión; tres terminaron por `physics_locked`) con la técnica 2 de §9.7: comparar, ciclo a ciclo, la respuesta cruda del modelo con la acción ejecutada y con la profundidad de referencia del simulador, consultada a posteriori solo para la auditoría. Como en las fallas anteriores, ninguno de los mecanismos produce una excepción: el modelo responde JSON válido, el lazo ejecuta una acción en cada ciclo y las métricas agregadas registran deadlocks «resueltos» en el 75–80 % de los casos.

### 9.8.1 Error de marco de referencia: «libre hacia la meta» ejecutado como «evadir a la izquierda»

En las tres corridas analizadas con una interfaz de barrido basada en ángulos, el primer barrido respondió correctamente: `{"deg": -53, "tipo": "libre", "ok": true}` para la imagen tomada en el rumbo −53°, a ~16° del rumbo al waypoint. La acción ejecutada fue `EVADIR_IZQUIERDA`, y el dron giró alejándose de la meta. Dos inconsistencias de marco se combinaban:

1. Las imágenes se etiquetaban con su **rumbo absoluto** («[Rumbo −53°]») y el prompt pedía un ángulo **relativo**; el modelo copiaba la etiqueta y el parser interpretaba siempre el valor como relativo.
2. El error de rumbo hacia la meta se medía respecto del yaw **al final** del barrido (153°), no del yaw de cada imagen.

El dron se alejó de 82.6 m a 94–95 m del primer waypoint y tardó ~37 s en volver a la distancia de partida, en las tres corridas.

**Mecanismo de contención.** El modelo nunca reporta ángulos: identifica las imágenes por número, y el código asigna a cada una el yaw **medido** al capturarla y compara rumbos absolutos, calculando el rumbo a la meta desde las posiciones (cap. 5, §5.12). Un test reproduce el caso (`tests/test_deep_vlm_world_frame.py`).

### 9.8.2 Default silencioso: la respuesta del modelo nunca llega a la decisión

Si el productor de la respuesta devuelve una descripción de escena por sectores y el consumidor lee `decision.get("macro_action", "EVADIR_DERECHA")`, la clave no existe y **toda respuesta se ejecuta como `EVADIR_DERECHA`**, con razonamiento vacío: 11 de 15 despachos en las tres corridas, 5 de ellos contra un lado que el propio modelo había descrito como bloqueado. Es un caso de *schema drift* (§9.2) en sentido inverso: el productor y el consumidor no comparten esquema y el consumidor, en lugar de fallar, funciona con un valor por defecto plausible. Ningún test recorría el camino completo desde la respuesta hasta la acción.

**Mecanismo de contención.** Cada modo de consulta tiene un esquema estricto y un parser que lo valida; una respuesta que no coincide no produce ninguna acción (motivo `no_parseable`, registrado), nunca un valor por defecto (cap. 8, §8.2.2). Los tests de integración corren el grafo compilado de punta a punta, desde la respuesta del modelo hasta la sub-meta que llega al bucle externo (§9.9, riesgo A).

### 9.8.3 Salida casi constante del modelo

Las 185 respuestas del VLM de esas corridas se compararon con la profundidad de referencia registrada. En las consultas por sectores, excluida una corrida en vegetación, **52 de 53 respuestas declararon el frente transitable**; con la superficie más cercana a ≤ 1.2 m en los 8 s previos, 18 de 19 lo declararon igual. En los barridos, la primera imagen salió marcada como transitable en la gran mayoría de los casos, con valores (`"ok": true, "conf": 0.9`) idénticos al ejemplo del prompt. La respuesta, en la práctica, no dependía de la escena. Ninguno de los 8 deadlocks «resueltos» por el modelo en las tres corridas analizadas produjo avance neto hacia el waypoint (máximo 2.2 m en 10 s).

El hallazgo no se puede atribuir solo al modelo: el prompt contenía un ejemplo con valores concretos y una frase que pedía priorizar evasiones, contradictoria con la instrucción de solo describir, y la pregunta («¿se puede avanzar en este sector?») se hacía sobre imágenes de 256–384 px.

**Mecanismo de contención.** La pregunta, la granularidad y el prompt están diseñados contra estas causas (cap. 8, §8.3–§8.5), y el banco de prueba contra etiquetas de referencia mide si el modelo discrimina (cap. 10, §10.13). No lo hace (§9.9, riesgo D).

### 9.8.4 Deadlock falso en el despegue

En todas las corridas de diagnóstico, el primer deadlock se declaró en los ciclos 17–18, con el dron todavía subiendo a la altitud de crucero. Durante el despegue el guiado ordena subir y girar en el lugar hacia el primer waypoint con `vx = 0`; un contador de «detenido» que suma esos ciclos dispara la resolución de atasco al cruzar el piso óptico de 4.5 m.

**Mecanismo de contención.** «Detenido» se define como «se ordenó avanzar y el dron no se movió», y no se cuenta bajo el piso óptico ni durante el despegue (cap. 5, §5.3.1). Aplicada sobre la telemetría registrada, esa definición no declara el deadlock en ninguna de las tres corridas.

### 9.8.5 Una señal de referencia dentro del brazo evaluado

Un runner que captura el canal de profundidad del simulador «solo como métrica» puede terminar alimentando al brazo evaluado: en una configuración de diagnóstico, esa captura armaba un freno de proximidad que el grafo consumía, cancelaba maniobras, inyectaba retrocesos y registraba puntos de contacto que el tracker usaba para validar desvíos. El brazo evaluado tenía así acceso indirecto a la profundidad exacta del simulador, lo que invalida su comparación con un sistema monocular, y una guardia estática limitada a `src/` no lo detecta porque el runner está fuera de su alcance.

**Mecanismo de contención.** Ningún componente del lazo de vuelo lee el canal de profundidad, tampoco como métrica, y la guardia (`test_no_depth_in_flight_path.py`) cubre el runner, `main.py` y todos los módulos de vuelo, incluido el canal indirecto; la distancia mínima a obstáculo la mide un hilo de auditoría aislado (cap. 5, §5.16).

### 9.8.6 Reglas apiladas sobre la decisión del modelo

Compensar cada falla observada en una corrida piloto con una regla determinista acumula capas de reescritura sobre la decisión del modelo. En una configuración de diagnóstico había retrocesos antes del barrido, escalamiento a un retroceso si el modelo alternaba de lado, un desvío perpendicular con el lado invertido respecto del modelo, cinco reglas sobre la historia de la trayectoria, un escape vertical tras escaneos «fútiles» y, en el tracker, filtros que reflejaban o descartaban los desvíos: la decisión del VLM pasaba por hasta seis capas de reescritura, y el brazo `slm` medía esas reglas tanto como al modelo.

Medidas contra el avance hacia el waypoint real en los 10–20 s siguientes, ninguna mostró beneficio. Los retrocesos tuvieron avance mediano negativo (en el 31–43 % de los casos alejaron al dron más de 2 m); 74 desvíos deterministas dieron una mediana de 0.35 m de avance en 20 s, 16 de ellos alejaron al dron más de 2 m y lo llevaron sobre la autopista elevada; y un disparador de deadlock basado en la historia de la trayectoria produjo 45 deadlocks sin avance posterior. Solo el lazo reactivo (guiado, evasión por flujo, giro de 90°) mostró avance mediano positivo.

La lección metodológica es la de §9.7 aplicada al diseño: una regla que corrige un síntoma observado en una corrida, sin medir su efecto agregado, no se puede distinguir —desde las métricas de éxito— de una regla que empeora el sistema.

**Mecanismo de contención.** La respuesta de la fuente se traduce a geometría y se aplica sin reglas que la reemplacen; solo se descartan respuestas obsoletas (cap. 5, §5.16). El criterio para incluir un componente en el lazo es haber mostrado avance hacia el waypoint real, o ser parte del lazo rápido común a los tres brazos.

### 9.8.7 La causa física de los `physics_locked`

En las tres corridas el dron no chocó de frente: quedó apoyado sobre una **superficie horizontal a la altura de crucero** —el tablero de una autopista elevada (dos corridas) y la cornisa de un edificio (una)—, con los sectores frontales del flujo libres (`occ = 0`, TTC infinito). En una corrida, un `GANAR_ALTURA` liberó al dron hasta −12.2 m y el guiado de altitud lo devolvió a −10 m, sobre la cornisa. Ni el flujo óptico ni una descripción por columnas representan ese tipo de obstáculo.

**Mecanismo de contención.** El manifiesto evita la autopista (`WP_0_SUR`, cap. 10 §10.3.3); la capa estratégica juzga el fotograma en una grilla de 3×3, de modo que un obstáculo a la altura del dron puede rodearse por la fila de arriba; y el escape determinista ante falla de la fuente es `GANAR_ALTURA` (cap. 5, §5.3.4, §5.10).

### 9.8.8 Señales que se tapan entre sí: un techo inventado y una velocidad que no existe

En una corrida piloto sobre `citysim_pilot`, el dron quedó 220 ciclos apoyado sobre el parapeto de la autopista elevada, pegada al punto de partida, sin que se declarara un solo deadlock. Tres mecanismos, cada uno razonable por separado, se encadenaron:

1. **Avance durante el ascenso.** El guiado avanzaba hacia el primer waypoint mientras subía; a 7.4 m, todavía por debajo del borde del parapeto, el TTC frontal cayó a 0.23 s y el lazo ejecutó `GIRAR_90`.
2. **Un techo inventado.** La detección de techo contaba los ciclos en que el *guiado* pedía subir sin que la cota cambiara. Durante el giro el comando vertical era cero, de modo que diez ciclos de giro se leyeron como diez ciclos empujando contra una losa: techo en z = −7.44. Con ese techo, el waypoint a −10 m quedó «bloqueado verticalmente» y el lazo ordenó `PERDER_ALTURA` en cada ciclo, contra el parapeto.
3. **Una velocidad que no existe.** Con el dron apoyado en la estructura, AirSim reportaba 0.31 m/s horizontales y 0.75 m/s verticales con la posición inmóvil. El contador de «detenido» leía esa velocidad y nunca avanzó; el de «sin progreso» sí llegó a 200 ciclos, pero la regla de descenso por techo se evaluaba antes que la de deadlock y tomaba el ciclo.

Ninguna de las tres produjo un error: cada ciclo tenía una acción válida y una justificación registrada. Es la misma clase de falla que §9.5 y §9.7 —el sistema «funciona» mientras repite indefinidamente una acción inútil—, en este caso entre señales del lazo rápido y no entre el modelo y el lazo.

**Mecanismo de contención.** El despegue es vertical hasta la altitud del primer objetivo (cap. 5, §5.15); la detección de techo usa el comando efectivamente ejecutado, no la demanda del guiado (§5.15.3); el `StallDetector` mide la velocidad por desplazamiento entre ciclos (§5.3.1); y el deadlock se evalúa antes que cualquier otra regla salvo el barrido en curso (§5.3.2), de modo que ninguna acción que se repita sin mover al dron puede taparlo. Un test reproduce la secuencia sobre el grafo compilado (`tests/test_pilot_seed99_regressions.py`).

### 9.8.9 Sub-metas que ocultan al waypoint real

En otra corrida piloto, el dron llegó a la zona del primer waypoint a los 40 s y pasó el resto de la corrida —más de cuatro minutos— pegado a la fachada vidriada del edificio contiguo. Estuvo **573 ciclos a menos de 3.5 m del waypoint**, el radio de aceptación, sin aceptarlo nunca. Cinco mecanismos se encadenaron:

1. **La sub-meta ocultaba al waypoint.** El tracker solo medía la llegada al objetivo activo. En los 573 ciclos el objetivo activo era una sub-meta del VLM (332 de la capa estratégica, 241 del barrido), de modo que pasar por encima del waypoint no contaba.
2. **Sub-metas más lejos que el waypoint.** La sub-meta se fijaba siempre a 15 m. Con el waypoint a 6 m, una sub-meta a 15 m queda 9 m más allá: en este caso, dentro del edificio. A 1 m del waypoint, el rumbo hacia la meta que usa el barrido es casi ruido, y la sub-meta lo amplifica.
3. **Sin re-planificación.** La capa estratégica solo consultaba con un waypoint real como objetivo. Con una sub-meta mala activa quedaba muda, y el lazo rápido entraba en un ciclo límite: el guiado apuntaba a la sub-meta dentro del edificio, el TTC caía a 0–0.2 s, `GIRAR_90` desviaba un segundo y el guiado volvía a apuntar a la fachada (cinco giros en 55 ciclos, seis en 50). Solo un deadlock, 10 s después, reemplazaba la sub-meta.
4. **Respuestas casi constantes, incluso sobre imágenes del interior del edificio.** La capa estratégica, con una partición en columnas, respondió «la primera columna bloqueada, las demás libres» en 5 de 6 consultas, incluida una con la fachada ocupando casi todo el cuadro, y marcó «estructura debajo» en 5 de 6, lo que subía todas las sub-metas 4 m. En los 8 barridos, las imágenes 2 y 4 salieron libres y la 1 y la 3 bloqueadas, sin importar hacia dónde miraba el dron. Con el dron pegado a la fachada, la cámara quedó dentro de la malla del edificio en dos barridos: el modelo marcó el interior de una oficina como `libre, ok: true` y, como apuntaba hacia el waypoint, el barrido lo eligió.
5. **Un techo inventado por una pared.** Con el dron trabado contra la fachada, el roce impedía subir y la detección de techo declaró una losa a −11.8 m; los escapes `GANAR_ALTURA` subieron después hasta −16 m sin obstáculo, y la regla de techo los devolvía hacia abajo.

Además, el waypoint mismo estaba mal ubicado: sus coordenadas se habían tomado del mapa y caían sobre la fachada, en contra del principio de derivar coordenadas solo de posiciones ya voladas (cap. 10, §10.3.0).

**Mecanismo de contención.** El tracker acepta el waypoint real aunque haya una sub-meta activa y descarta los desvíos pendientes (cap. 5, §5.15.4); ninguna sub-meta queda más lejos que el waypoint real, y a menos de 8 m del waypoint no se consulta a la capa estratégica ni se barre (§5.10.1, §5.12); la capa estratégica re-planifica con una sub-meta activa, y si ve libre el camino directo descarta el desvío (§5.10.3); el barrido no usa entradas que se contradicen (`free: true` con una vista distinta de `open`), lo que no reemplaza la decisión de la fuente sino que descarta respuestas internamente inconsistentes, igual que una respuesta mal formada (§5.12); la capa estratégica juzga una grilla de 3×3 en lugar de columnas, de modo que el eje vertical sale de la descripción y no de una pregunta abstracta (cap. 8, §8.3.2); la detección de techo no cuenta los ciclos en que el dron está trabado de costado (§5.15.3); y los waypoints de los manifiestos están en puntos ya volados. Los tests `tests/test_pilot_190842z_regressions.py` reproducen cada mecanismo.

Estas medidas no corrigen el punto 4: que el modelo casi no distinga escenas. Con ellas, una respuesta mala deja de atrapar al dron; que la fuente aporte información es la pregunta de §9.9, riesgo D.

### 9.8.10 Una respuesta cortada y una capa sin voz

En una tercera corrida piloto, el dron llegó a los tres primeros waypoints —incluido el que está detrás de una manzana— y quedó trabado en el tramo hacia el cuarto, contra la fachada de un edificio que la recta atraviesa. Tres mecanismos lo dejaron sin salida:

1. **El modelo marcó libres los costados de una fachada.** En las cinco consultas del tramo marcó bloqueado el sector de frente —lo correcto— y libres los demás, incluso en fotogramas en los que la fachada ocupaba todo el cuadro. En las 28 consultas de la corrida, el sector de la izquierda a la altura del dron salió libre las 28 veces y el de arriba a la izquierda, bloqueado 24: un sesgo por posición en la grilla, no una descripción de la escena. La sub-meta elegida quedó del otro lado de la fachada, y el dron se deslizó a lo largo de ella unos 180 ciclos.
2. **La capa estratégica no consultó en todo ese tiempo.** El dron miraba a lo largo de la pared, con la meta fuera de los ±40° del eje óptico, la condición para consultar: justo cuando hacía falta replanificar, la capa no tenía cómo hacerlo.
3. **Los barridos se perdían por el tope de tokens.** Un tope de 160 tokens cortaba la respuesta del barrido —un JSON con indentación— antes de la llave final, en 5 de 12 barridos; esos barridos caían al escape vertical sin usar la respuesta del modelo. La falla no se veía: el registro la clasificaba como «sin formato válido», igual que una respuesta mal formada.

La corrida terminó por `physics_locked`, con el dron apoyado en la baranda de un balcón (§9.8.7). Además, se ejecutó con cambios sin commitear y quedó registrada con el mismo `code_version` que otra corrida con distinto código: un criterio de descarte por versión basado solo en el hash no la distingue.

**Mecanismo de contención.** Los topes de tokens son 384 (estratégico) y 512 (barrido), y una respuesta cortada se reporta como `respuesta_truncada`, separada de las respuestas mal formadas (cap. 5, §5.10.5); la capa estratégica consulta con la meta fuera de cuadro cuando el dron lleva `VLM_STUCK_QUERY_CYCLES` (15 ciclos, 3 s) sin acercarse a su objetivo, sin interpretar nunca esa respuesta como «camino directo libre» (§5.10.1); y `code_version` lleva el sufijo `-dirty` si hay cambios sin commitear, lo que excluye la corrida de un lote (cap. 10, §10.12). Los tests `tests/test_pilot_193631z_regressions.py` reproducen cada caso. El punto 1 —que el modelo describa la grilla por posición y no por contenido— no tiene mecanismo de contención dentro del VLM: es la pregunta de §9.9, riesgo D, y la medición que la responde es la comparación sector por sector contra una etiqueta de referencia (cap. 10, §10.13).

### 9.8.11 Un barrido que no describe la escena

Con las respuestas del barrido completas, tres corridas piloto suman 19 respuestas utilizables. En las 19 el patrón de transitabilidad fue el mismo: las imágenes 2 y 4 —a 90° a cada lado del rumbo inicial— transitables, y la 1 y la 3 —el frente y la dirección de la que venía el dron— bloqueadas, sin importar dónde estaba el dron ni qué mostraban las imágenes. La dirección de la que venía el dron, casi siempre libre, salió bloqueada las 19 veces. Además, el modelo marcó todas las respuestas como degradadas, incluidas imágenes nítidas de calle abierta, y en varias asignó `ok: true` a imágenes de tipo `fachada` o `interior`. Medido contra el avance hacia el waypoint real, las sub-metas del barrido no mostraron efecto: en la mayoría de los casos el avance a los 20 s fue nulo, y en dos el dron se alejó más de 5 m.

La consecuencia de diseño es doble. Primero, una respuesta constante convierte al barrido, en la práctica, en una regla fija («girar 90° hacia el lado más cercano a la meta»), y una regla de falla basada en el indicador de imagen degradada lo convertiría en un escape vertical ciego (en una de esas corridas habría descartado los 8 barridos). Segundo, elegir el rumbo transitable más cercano a la meta devuelve al dron, deadlock tras deadlock, contra el mismo obstáculo.

**Mecanismo de contención.** El esquema no pide indicador de imagen degradada ni certeza (cap. 8, §8.2.1); y la salida del deadlock descarta el rumbo que falló y los rumbos ya probados en la zona, y con deadlocks repetidos explora el rumbo libre más distinto de lo ya probado (cap. 5, §5.12). Esto no corrige que el modelo responda lo mismo siempre: con una respuesta constante, la salida queda determinada por la historia del dron y no por la imagen. El registro de la selección permite separar ambos efectos.

## 9.9 Riesgos residuales y trabajo pendiente

Los modos de falla documentados tienen su mecanismo de contención en el sistema y los de §9.8 están cubiertos por tests de regresión sobre el grafo compilado. La arquitectura contiene puntos donde pueden aparecer instancias análogas:

**Riesgo A — Nuevas claves de DroneState.** Cada funcionalidad que requiere persistir estado entre ciclos corre el riesgo de que la clave correspondiente no se declare en `DroneState`. Las mitigaciones son mantener el estado de control en objetos de proceso y los tests de integración sobre el grafo compilado, que verifican que las claves de control (`inject_corner`, `_escape_reset`, `_deadlock_event`, `_vlm_strategic`) cruzan la frontera de `graph.invoke()` (`tests/test_graph_integration.py`, `tests/test_vlm_strategic_graph.py`). Esos tests cubren las claves conocidas, no las nuevas: una defensa más general sería un test de contrato que recorra el código fuente de `src/agents/`, extraiga todas las claves `state["_..."]` y `state.get("...")` y falle si alguna no pertenece a `DroneState`; no existe.

**Riesgo B — Cambios de API del binding de AirSim.** El binding `cosysairsim` es un fork activamente mantenido ([Jansen et al., 2023](13-REFERENCIAS.md#ref-jansen-2023)). Sus actualizaciones pueden modificar el comportamiento de métodos (como la conversión de actitud de §9.6.3). Los tests unitarios de conversión de telemetría son la mitigación; deben ejecutarse tras cada actualización del binding.

**Riesgo C — Distribución de imágenes fuera del dominio de entrenamiento.** La conversión RGB/BGR es una transformación fija. La brecha de dominio entre imágenes de AirSim/UE5 y el dominio de entrenamiento del VLM y de la red de profundidad (predominantemente imágenes reales) es una fuente estructural de error que no se elimina con ninguna corrección puntual (cap. 6, §6.14.5).

**Riesgo D — Que el VLM no discrimine (materializado).** El diseño corrige cómo se pregunta y cómo se usa la respuesta, pero no puede garantizar que el modelo distinga sectores volables de bloqueados (§9.8.3). El banco de prueba con el modelo de vuelo (LFM2.5-VL-1.6B, `lfm2.5-vl-1.6b:q4km-ctx8k`) confirma el riesgo: la grilla queda en AUC 0.53 y el barrido declara transitables todos los rumbos (cap. 11, §11.0). La respuesta del diseño no es una regla que compense al modelo, sino una fuente que sí responde la pregunta, la profundidad estimada (cap. 6, §6.14), con el VLM donde aporta, el plan de ruta (cap. 4, §4.3.1).
