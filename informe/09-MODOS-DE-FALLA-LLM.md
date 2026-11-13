# 9. Modos de falla en lazos de control híbridos con LLM

## 9.1 El argumento central: contratos de interfaz como vector de falla primario

En un sistema robótico que combina percepción clásica, un grafo de control y un modelo de lenguaje, la intuición apunta al modelo como fuente de fallas: respuestas alucinadas, razonamiento incorrecto, formato inválido. La auditoría de este sistema señala otra dirección: los fallos más costosos de diagnosticar —en horas de trabajo y en consecuencias en vuelo— ocurrieron en los **contratos de interfaz entre componentes**. Los casos provienen de corridas de diagnóstico anteriores a la configuración evaluada en el capítulo 11, y se documentan como casos, sin una medición de su frecuencia. Su importancia excede el costo de diagnóstico: mientras existieron, impidieron saber si el modelo discriminaba la escena; contenidos, el banco de prueba mostró que no lo hace (IT.9.9, riesgo D; cap. 11, IT.11.0).

Un modelo de lenguaje razona sobre lo que recibe, no sobre la realidad: si el resumen de percepción dice "camino despejado", responde de forma consistente con esa premisa. Cualquier corrupción u omisión en los datos que lo alimentan produce decisiones estructuralmente correctas y factualmente equivocadas, sin excepciones y con JSON válido. Es el problema de las respuestas fluidas pero no fundamentadas en la entrada (*hallucination*; [Ji et al., 2023](13-REFERENCIAS.md#ref-ji-2023)), agravado porque la salida no la lee una persona sino el control de un vehículo. En la arquitectura vigente esa salida ya no comanda: se traduce a una sub-meta geométrica (cap. 5, IT.5.5), y en la configuración evaluada el modelo no interviene en vuelo.

El capítulo documenta seis familias de fallas, organizadas por la capa donde se originan, con su mecanismo de contención; los casos completos están en el [Anexo 11](anexos/A11-CATALOGO-INCIDENTES-INTEGRACION.md).

| # | Categoría | Capa de origen | ¿Genera excepción? | Consecuencia en vuelo |
|---|---|---|---|---|
| 1 | Schema drift / campo ciego | Contrato percepción→control | No | Navegación a ciegas hacia obstáculos |
| 2 | Desalineación temporal de frames | Buffer de historial visual | No | FOE/movimiento inferido incorrectamente |
| 3 | Descalibración de escala en divergencia | Operador diferencial en flujo | No | Saturación del canal de ocupación |
| 4 | State clipping + ciclos límite en LangGraph | Orquestación de grafo | No | Ascenso acumulado de >350 m |
| 5 | Degradación sensorial silenciosa | Captura de imagen y telemetría | No | Deliberación sobre datos corruptos |
| 6 | Integración del VLM: marco de referencia, defaults silenciosos y reglas apiladas | Interfaz VLM → control | No | Respuestas correctas del modelo ejecutadas al revés o ignoradas |

El denominador común en los seis casos es la ausencia de excepción en tiempo de ejecución, cuya consecuencia metodológica se discute en IT.9.7.

## 9.2 Falla 1 — Schema drift: el campo nulo leído como ausencia de peligro

Si el estado del campo de obstáculos se comunica como una lista de objetos detectados, con una lista vacía como valor por defecto, la lista vacía es ambigua: puede significar "la percepción corrió y no detectó nada" o "la percepción no corrió, no tiene confianza, o falló silenciosamente". Los consumidores —la capa de decisión, el constructor del prompt del VLM y la FSM— tienden a resolver la ambigüedad en favor de la primera lectura. En una configuración de diagnóstico con ese contrato, el prompt afirmaba al modelo "trayectoria frontal sin obstáculos detectados", el VLM respondía con perfecta coherencia que se podía seguir, el lazo ejecutaba el crucero y no se generaba ninguna alerta, porque la lista vacía es un valor válido.

Es una instancia de un anti-patrón general: tratar el valor neutro de un tipo (lista vacía, cero, `None`) como evidencia de ausencia de fenómeno en lugar de como ausencia de información. En señales de seguridad la convención correcta es la inversa: la ausencia de evidencia no es evidencia de ausencia de peligro ([Altman y Bland, 1995](13-REFERENCIAS.md#ref-altman-1995)).

**Mecanismo de contención.** El contrato de percepción es el tipo inmutable `ObstacleField` (cap. 6), que distingue tres estados epistémicos: percepción con evidencia real (`source = "flow"`, `foe_confidence > 0`), percepción que corrió sin evidencia confiable (`foe_confidence = 0`) y percepción inhibida activamente (`source = "degraded"`). **Ningún consumidor puede confundir "sin obstáculos detectados" con "sin información"** sin leer explícitamente `has_evidence()`, y la falta de evidencia tiene consecuencias explícitas: el gobernador de velocidad limita el avance (cap. 5, IT.5.4) y `has_open_corridor()` no declara corredor libre sin evidencia (cap. 6, IT.6.10).

## 9.3 Falla 2 — Desalineación temporal del historial de frames

Una consulta que envía al VLM un historial de dos frames ($t$ y $t-1$) para que estime la dirección de movimiento depende de que los dos frames sean genuinamente distintos en el tiempo. Un buffer actualizado sin verificar timestamps produce frames fuera de contexto al cambiar de waypoint (el "t-1" es un fotograma de otro punto de la misión) o duplicados cuando el simulador no entrega uno nuevo a tiempo. Con dos frames idénticos, el modelo infiere que el dron está estático o que nada se acerca.

**Mecanismo de contención.** El sistema no envía historial temporal al VLM: la capa estratégica usa el fotograma del ciclo y el barrido un fotograma por rumbo, cada uno con su timestamp y su pose de captura (cap. 5, IT.5.4, IT.5.5, IT.5.6). El riesgo equivalente pasa a ser espacial —una etiqueta de orientación que no corresponde al fotograma (IT.9.8.1)— y se contiene anclando cada respuesta a la pose medida del fotograma que la originó.

## 9.4 Falla 3 — Descalibración de escala en el canal de divergencia

El canal de divergencia del `ObstacleField` (cap. 6, IT.6.7) estima $\partial u / \partial x + \partial v / \partial y$ sobre el campo de flujo. Un cálculo con gradientes de Sobel 3×3 sin el factor de normalización $1/8$ que el kernel requiere para estimar una derivada en unidades de píxel,

$$K_{\text{Sobel}} = \frac{1}{8}\begin{pmatrix} -1 & 0 & 1 \\ -2 & 0 & 2 \\ -1 & 0 & 1 \end{pmatrix}$$

produce divergencias unas 8 veces mayores que las correctas, y el canal de ocupación satura a `1.0` con cualquier gradiente de flujo, incluso en espacio abierto.

La consecuencia ilustra un problema de diseño de predicados disyuntivos sobre canales de distinta confianza. Una celda $c$ se declara bloqueada (cap. 6, IT.6.9) si

$$\text{bloqueada}(c) = \big(o_c \geq t_o\big) \lor \big(\kappa_c \geq 0.35 \land \hat{\tau}_c \leq 2.5\,\text{s}\big)$$

con $o_c$ la ocupación, $\kappa_c$ la confianza y $\hat{\tau}_c$ el TTC de la celda (IT.6.8). La disyunción asume canales calibrados en escalas comparables: si uno está sobre-estimado, se vuelve dominante y anula al otro, y el TTC, que tiene validación empírica (cap. 7), pierde toda influencia. El caso inverso también ocurre: un umbral de ocupación demasiado alto deja mudo a ese canal y la detección recae solo en el TTC (cap. 7, IT.7.5).

**Mecanismo de contención.** La divergencia se calcula con `np.gradient()`, normalizado intrínsecamente; el umbral de ocupación está calibrado contra profundidad de referencia por curva ROC (cap. 7, IT.7.5); y los dos canales tienen umbrales de confianza diferenciados (0.15 para ocupación, 0.35 para TTC), de modo que ningún canal puede dominar al otro sin confianza suficiente, aun ante recalibraciones futuras.

## 9.5 Falla 4 — State clipping y ciclos límite en LangGraph

LangGraph construye los canales de estado a partir de un `TypedDict` declarado al compilar el grafo, y en cada invocación conserva solo las claves declaradas: cualquier otra que un nodo escriba se **descarta en silencio**, sin excepción ni registro (cap. 5, IT.5.2). En corridas de diagnóstico convergieron cuatro vulnerabilidades (Anexo 11, IT.A11.1.1): **(A)** claves de control no declaradas, entre ellas la que debía reiniciar el contador de bloqueo en cada waypoint; **(B)** una red de seguridad que se reseteaba a sí misma, con un ciclo límite que en el visor parecía "el dron frena sin razón"; **(C)** un umbral de ciclos sin progreso derivado de parámetros incoherentes, que se disparaba al inicio de cada maniobra; y **(D)** un escape evaluado antes de leer la percepción. Combinadas, produjeron en una sola corrida un **ascenso acumulado de ~356 m** que desde afuera era una misión "sin errores" que no llegó a destino. Variantes de la misma familia —maniobras válidas sobrescritas antes de ejecutarse durante 200 ciclos, resultados que nunca se leían— están en el Anexo 11 (IT.A11.2).

**Mecanismo de contención.** Todo campo que cruza la frontera entre invocaciones está declarado en `DroneState`, el estado de control vive en objetos de proceso, y los tests de integración corren el **grafo compilado** verificando que las claves de control sobreviven a cada invocación (cap. 5, IT.5.2). El escape es absorbente y solo se reinicia al resolverse; el progreso se mide como distancia horizontal al objetivo con umbrales físicamente alcanzables; y el orden de las reglas de decisión es fijo y justificado, con el resultado de cada consulta recuperado por su identificador al inicio de cada ciclo, sea cual sea la ruta que tome (cap. 5, IT.5.3.1, IT.5.3.2, IT.5.3.4).

## 9.6 Falla 5 — Degradaciones sensoriales silenciosas

Tres degradaciones de la entrada sensorial pasaron sin ningún aviso, porque cada consumidor procesa lo que recibe sin poder saber que está corrupto (detalle en el Anexo 11, IT.A11.3):

- **Inversión de canales RGB/BGR.** El simulador entrega la imagen en RGB y el pipeline asume BGR: fachadas rojas azuladas, cielo amarillento. El VLM delibera sobre esas imágenes sin reducir su confianza. Solo se detecta guardando y mirando las imágenes exactas enviadas al modelo.
- **Primitivas de depuración persistentes.** Las líneas y puntos dibujados en el simulador para depurar sobreviven entre vuelos de una misma sesión y la cámara las captura como geometría: franjas que el modelo interpreta como cables o estructuras. El mismo vuelo se comporta distinto según el historial de la sesión ([Jansen et al., 2023](13-REFERENCIAS.md#ref-jansen-2023)).
- **Actitud suprimida.** El binding de CosysAirSim no implementa la conversión a ángulos de Euler del binding oficial; un fallback silencioso reporta pitch y roll en 0° en todo momento, y la derotación del flujo óptico pierde dos de sus tres ejes.

**Mecanismo de contención.** La conversión de canales se hace en el punto de captura (cap. 3, IT.3.3) y cada consulta guarda sus fotogramas exactos para auditoría (cap. 4, IT.4.4); cada sesión empieza borrando las primitivas persistentes; y la actitud se calcula directamente del cuaternión de orientación, con un test unitario contra cuaterniones conocidos.

## 9.7 Por qué el sistema sigue funcionando: el problema de la observabilidad

Ninguno de los seis modos de falla produce un error visible: el modelo responde JSON válido, el lazo ejecuta sin excepciones y las métricas agregadas no distinguen estas corridas de las fallidas por otras causas. Las técnicas habituales de depuración —observar la salida, monitorear métricas, leer el log de errores— son ciegas a esta clase de error, porque el sistema se comporta *de manera consistente con sus premisas internas*, aunque estén corrompidas. La dificultad no es exclusiva de este proyecto: [Amershi et al. (2019)](13-REFERENCIAS.md#ref-amershi-2019) identifican que los componentes de aprendizaje automático son más difíciles de aislar, probar y depurar que el código determinista. Las técnicas que sí funcionan son:

**1. Auditoría de contratos en la frontera de cada componente.** Para cada par productor-consumidor: ¿qué devuelve el productor cuando no tiene información, y cómo lo interpreta el consumidor?

**2. Guardar los datos crudos enviados al modelo.** El fotograma exacto, el prompt, la respuesta cruda y el estado de cada ciclo, sincronizados con el video (cap. 4, IT.4.4). Sin eso la inversión RGB/BGR sería indetectable, y comparar ciclo a ciclo la respuesta con la acción ejecutada es lo que reveló la Falla 6.

**3. Tests de invariantes de contrato, no de comportamiento.** "Si no hay evidencia, ningún consumidor reporta el campo como despejado" captura la Falla 1 sin necesitar un vuelo; "el dron evadió el obstáculo" depende de la escena.

**4. Tests sobre el grafo compilado.** El descarte de la Falla 4 ocurre en el runtime de LangGraph y no aparece en tests sobre nodos sueltos; cada secuencia de falla observada tiene un test de regresión sobre el grafo compilado.

## 9.8 Falla 6 — Integración del VLM: respuestas correctas ejecutadas al revés, ignoradas o casi constantes

Esta familia se identificó auditando corridas de diagnóstico sobre `citysim_pilot` con el VLM como fuente del lazo lento (doce corridas, ninguna completó la misión; tres terminaron por `physics_locked`) con la técnica 2 de IT.9.7: comparar, ciclo a ciclo, la respuesta cruda del modelo con la acción ejecutada y con la profundidad de referencia del simulador, consultada a posteriori solo para la auditoría. Ninguno de los mecanismos produce una excepción: el modelo responde JSON válido, el lazo ejecuta una acción en cada ciclo y las métricas agregadas registran deadlocks «resueltos» en el 75–80 % de los casos.

### 9.8.1 Error de marco de referencia: «libre hacia la meta» ejecutado como «evadir a la izquierda»

Con una interfaz de barrido basada en ángulos, el primer barrido respondió correctamente: `{"deg": -53, "tipo": "libre", "ok": true}` para la imagen tomada a ~16° del rumbo al waypoint. La acción ejecutada fue `EVADIR_IZQUIERDA`, y el dron giró alejándose de la meta. Dos inconsistencias de marco se combinaban: las imágenes se etiquetaban con su **rumbo absoluto** y el prompt pedía un ángulo **relativo**, de modo que el modelo copiaba la etiqueta y el parser la interpretaba como relativa; y el error de rumbo hacia la meta se medía respecto del yaw al final del barrido, no del de cada imagen. En las tres corridas analizadas, el dron se alejó de 82.6 m a 94–95 m del waypoint y tardó ~37 s en volver a la distancia de partida.

**Mecanismo de contención.** El modelo nunca reporta ángulos: identifica las imágenes por número, y el código asigna a cada una el yaw **medido** al capturarla y compara rumbos absolutos, calculando el rumbo a la meta desde las posiciones (cap. 5, IT.5.6). Un test reproduce el caso.

### 9.8.2 Default silencioso: la respuesta del modelo nunca llega a la decisión

Si el productor devuelve una descripción de escena por sectores y el consumidor lee `decision.get("macro_action", "EVADIR_DERECHA")`, la clave no existe y **toda respuesta se ejecuta como `EVADIR_DERECHA`**: 11 de 15 despachos en las tres corridas, 5 de ellos contra un lado que el propio modelo había descrito como bloqueado. Es un *schema drift* (IT.9.2) en sentido inverso: productor y consumidor no comparten esquema, y el consumidor, en lugar de fallar, funciona con un valor por defecto plausible. Ningún test recorría el camino completo desde la respuesta hasta la acción.

**Mecanismo de contención.** Cada modo de consulta tiene un esquema estricto y un parser que lo valida; una respuesta que no coincide no produce ninguna acción —se registra como no parseable—, nunca un valor por defecto (cap. 8, IT.8.2.2). Los tests de integración recorren el grafo compilado de punta a punta, desde la respuesta del modelo hasta la sub-meta que llega al bucle externo.

### 9.8.3 Salida casi constante del modelo

Las 185 respuestas del VLM de esas corridas se compararon con la profundidad de referencia. En las consultas por sectores, **52 de 53 respuestas declararon el frente transitable**; con la superficie más cercana a ≤ 1.2 m en los 8 s previos, 18 de 19 lo declararon igual. En los barridos, la primera imagen salió marcada como transitable en la gran mayoría de los casos, con valores idénticos al ejemplo del prompt. La respuesta, en la práctica, no dependía de la escena, y ninguno de los 8 deadlocks «resueltos» por el modelo produjo avance neto hacia el waypoint. El hallazgo no se puede atribuir solo al modelo: el prompt contenía un ejemplo con valores concretos y una instrucción contradictoria, y la pregunta se hacía sobre imágenes de 256–384 px.

**Mecanismo de contención.** La pregunta, la granularidad y el prompt se rediseñaron contra estas causas (cap. 8, IT.8.3–IT.8.5), y se construyó el banco de prueba contra etiquetas de referencia para medir si el modelo discrimina (cap. 10, IT.10.2). No lo hace (IT.9.9, riesgo D). Las corridas piloto posteriores muestran el mismo patrón por posición en la grilla y en el barrido, con independencia de la imagen (Anexo 11, IT.A11.4.5–IT.A11.4.7).

### 9.8.4 Reglas apiladas sobre la decisión del modelo

Compensar cada falla observada en una corrida piloto con una regla determinista acumula capas de reescritura sobre la decisión del modelo. En una configuración de diagnóstico había retrocesos antes del barrido, escalamiento a un retroceso si el modelo alternaba de lado, un desvío perpendicular con el lado invertido respecto del modelo, cinco reglas sobre la historia de la trayectoria, un escape vertical tras escaneos «fútiles» y filtros en el tracker que reflejaban o descartaban los desvíos: la decisión del VLM pasaba por hasta seis capas de reescritura, y el brazo `slm` medía esas reglas tanto como al modelo.

Medidas contra el avance hacia el waypoint real en los 10–20 s siguientes, ninguna mostró beneficio: los retrocesos tuvieron avance mediano negativo, 74 desvíos deterministas avanzaron 0.35 m de mediana en 20 s, y un disparador de deadlock produjo 45 deadlocks sin avance posterior; solo el lazo reactivo mostró avance positivo. Es la lección de IT.9.7 aplicada al diseño: una regla que corrige un síntoma, sin medir su efecto agregado, no se distingue —desde las métricas de éxito— de una que empeora el sistema.

**Mecanismo de contención.** La respuesta de la fuente se traduce a geometría y se aplica sin reglas que la reemplacen; solo se descartan respuestas obsoletas (cap. 5, IT.5.8). El criterio para incluir un componente en el lazo es haber mostrado avance hacia el waypoint real, o ser parte del lazo rápido común a los tres brazos.

### 9.8.5 Otros casos

Las corridas de diagnóstico y piloto mostraron otros siete casos de la misma clase, documentados con su contención en el Anexo 11:

| Caso | Qué pasó | Contención | Detalle |
|---|---|---|---|
| Deadlock falso en el despegue | El contador de «detenido» sumaba los ciclos de ascenso y declaraba bloqueo antes de llegar a la altitud de crucero | «Detenido» = se ordenó avanzar y el dron no se movió; no se cuenta durante el despegue | IT.A11.4.1 |
| Señal de referencia dentro del brazo evaluado | Una captura de la profundidad del simulador «solo como métrica» alimentaba un freno de proximidad que el grafo consumía | Ningún componente del lazo lee la profundidad; una guardia automatizada lo verifica | IT.A11.4.2 |
| Causa física de los `physics_locked` | El dron quedaba apoyado sobre superficies horizontales a la altura de vuelo (autopista elevada, cornisas) que el flujo frontal no ve | Waypoints que evitan la autopista, grilla de 3×3 con fila superior, escape vertical | IT.A11.4.3 |
| Señales que se tapan entre sí | Un techo inventado durante un giro y una velocidad reportada con el dron inmóvil ocultaron un bloqueo de 220 ciclos | Techo según el comando ejecutado, velocidad por desplazamiento, deadlock antes que otras reglas | IT.A11.4.4 |
| Sub-metas que ocultan al waypoint real | 573 ciclos a menos de 3.5 m del waypoint sin aceptarlo, porque el objetivo activo era una sub-meta dentro de un edificio | Aceptación del waypoint real con sub-meta activa, sub-metas nunca más lejos que el waypoint, re-planificación | IT.A11.4.5 |
| Respuesta cortada y capa sin voz | Un tope de tokens truncaba 5 de 12 barridos, registrados como mal formados; la capa no consultaba con la meta fuera de cuadro | Topes mayores, motivo `respuesta_truncada` separado, consulta por estancamiento | IT.A11.4.6 |
| Barrido que no describe la escena | 19 de 19 barridos con el mismo patrón de rumbos transitables, sin importar qué mostraban las imágenes | Esquema sin indicador de certeza; la salida del bloqueo descarta los rumbos ya probados | IT.A11.4.7 |

## 9.9 Riesgos residuales y trabajo pendiente

Los modos de falla documentados tienen su contención y los casos de IT.9.8 están cubiertos por tests de regresión, pero la arquitectura admite instancias análogas. **Riesgo A — nuevas claves de estado**: los tests cubren las claves conocidas, no las nuevas, y falta un test de contrato que recorra el código y falle ante cualquier clave no declarada. **Riesgo B — cambios en el binding de AirSim** ([Jansen et al., 2023](13-REFERENCIAS.md#ref-jansen-2023)), que pueden alterar métodos como la conversión de actitud (IT.9.6); los tests de telemetría deben correr tras cada actualización. **Riesgo C — imágenes fuera del dominio de entrenamiento**: la brecha entre el render de AirSim y las imágenes reales con que se entrenaron el VLM y la red de profundidad no se elimina con correcciones puntuales (cap. 6, IT.6.12.4).

**Riesgo D — Que el VLM no discrimine (materializado).** El diseño corrige cómo se pregunta y cómo se usa la respuesta, pero no puede garantizar que el modelo distinga sectores volables de bloqueados (IT.9.8.3). El banco de prueba con el modelo de vuelo (LFM2.5-VL-1.6B) confirma el riesgo: la grilla queda en AUC 0.53 y el barrido declara transitables todos los rumbos (cap. 11, IT.11.0). La respuesta del diseño no es una regla que compense al modelo, sino una fuente que sí responde la pregunta, la profundidad estimada (cap. 6, IT.6.12), con el VLM donde aporta: el plan de ruta (cap. 4, IT.4.3.1).
