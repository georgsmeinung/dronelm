# 9. Modos de falla en un lazo de control híbrido con un modelo de visión-lenguaje

## 9.1 El argumento central: contratos de interfaz como vector de falla primario

En un sistema robótico que combina percepción clásica, un grafo de control y un modelo de lenguaje, la intuición apunta al modelo como fuente de fallas: respuestas alucinadas, razonamiento incorrecto, formato inválido. La auditoría de este sistema señala otra dirección: los fallos más costosos de diagnosticar ocurrieron en los **contratos de interfaz entre componentes**. Los casos provienen de corridas de diagnóstico anteriores a la configuración evaluada en el capítulo 11, y se documentan como casos, sin una medición de su frecuencia. Mientras existieron, impidieron saber si el modelo discriminaba la escena; contenidos, el banco de prueba mostró que no lo hace (IT.9.9, riesgo D; cap. 11, IT.11.0).

Un modelo de lenguaje razona sobre lo que recibe, no sobre la realidad: cualquier corrupción u omisión en los datos que lo alimentan produce decisiones estructuralmente correctas y factualmente equivocadas, sin excepciones y con JSON válido ([Ji et al., 2023](13-REFERENCIAS.md#ref-ji-2023)), agravado porque la salida no la lee una persona sino el control de un vehículo. El capítulo documenta seis familias de fallas, por la capa donde se originan, con su contención; los casos completos están en el [Anexo 11](anexos/A11-CATALOGO-INCIDENTES-INTEGRACION.md).

| # | Categoría | Capa de origen | ¿Genera excepción? | Consecuencia en vuelo |
|---|---|---|---|---|
| 1 | Schema drift / campo ciego | Contrato percepción→control | No | Navegación a ciegas hacia obstáculos |
| 2 | Desalineación temporal de fotogramas | Buffer de historial visual | No | Movimiento inferido incorrectamente |
| 3 | Descalibración de escala en divergencia | Operador diferencial en flujo | No | Saturación del canal de ocupación |
| 4 | State clipping + ciclos límite en LangGraph | Orquestación de grafo | No | Ascenso acumulado de >350 m |
| 5 | Degradación sensorial silenciosa | Captura de imagen y telemetría | No | Deliberación sobre datos corruptos |
| 6 | Integración del VLM: marco de referencia, defaults silenciosos y reglas apiladas | Interfaz VLM → control | No | Respuestas correctas del modelo ejecutadas al revés o ignoradas |

El denominador común es la ausencia de excepción en tiempo de ejecución, cuya consecuencia metodológica se discute en IT.9.7.

## 9.2 Falla 1 — Schema drift: el campo nulo leído como ausencia de peligro

Si la percepción comunica los obstáculos como una lista con una lista vacía por defecto, la lista vacía es ambigua: «no detectó nada» o «no corrió, no tiene confianza o falló». Los consumidores la leyeron como lo primero: en una configuración de diagnóstico, el prompt afirmaba «trayectoria frontal sin obstáculos detectados», el VLM respondía que se podía seguir y el lazo ejecutaba el crucero sin ninguna alerta. Es tratar el valor neutro de un tipo como ausencia del fenómeno y no como ausencia de información ([Altman y Bland, 1995](13-REFERENCIAS.md#ref-altman-1995)).

**Contención.** El contrato es el tipo inmutable `ObstacleField`, que distingue percepción con evidencia, sin evidencia confiable e inhibida, y ningún consumidor puede tratar la falta de evidencia como espacio libre (cap. 6, IT.6.10; Anexo 11, IT.A11.5).

## 9.3 Falla 2 — Desalineación temporal del historial de fotogramas

Un historial de dos fotogramas enviado al modelo para estimar el movimiento depende de que sean distintos en el tiempo; un búfer sin verificar timestamps produce fotogramas de otro punto de la misión o duplicados, y con dos iguales el modelo infiere que nada se acerca.

**Contención.** El sistema no envía historial temporal: cada consulta lleva su fotograma con su timestamp y su pose de captura, y el riesgo equivalente, que pasa a ser espacial, se contiene anclando cada respuesta a esa pose (IT.9.8.1; Anexo 11, IT.A11.6).

## 9.4 Falla 3 — Descalibración de escala en el canal de divergencia

Un cálculo de la divergencia con gradientes de Sobel sin su factor de normalización (1/8) produce divergencias unas 8 veces mayores, y el canal de ocupación satura con cualquier gradiente, incluso en espacio abierto. Como el predicado de bloqueo es una disyunción entre ocupación y TTC (cap. 6, IT.6.9), el canal sobre-estimado domina y el TTC, el validado, pierde toda influencia; el caso inverso, un umbral de ocupación demasiado alto, deja mudo a ese canal (cap. 7, IT.7.5).

**Contención.** La divergencia se calcula con un operador normalizado, el umbral de ocupación está calibrado por curva ROC y los dos canales tienen umbrales de confianza diferenciados (Anexo 11, IT.A11.7).

## 9.5 Falla 4 — State clipping y ciclos límite en LangGraph

LangGraph conserva en cada invocación solo las claves declaradas del estado: cualquier otra que un nodo escriba se **descarta en silencio** (cap. 5, IT.5.2). En corridas de diagnóstico convergieron cuatro vulnerabilidades: claves de control no declaradas —entre ellas la que reiniciaba el contador de bloqueo—, una red de seguridad que se reseteaba a sí misma, un umbral de progreso derivado de parámetros incoherentes y un escape evaluado antes de leer la percepción. Combinadas, produjeron en una corrida un **ascenso acumulado de ~356 m** que desde afuera era una misión «sin errores» que no llegó a destino (Anexo 11, IT.A11.1–IT.A11.2).

**Contención.** Todo campo que cruza la frontera entre invocaciones está declarado, el estado de control vive en objetos de proceso y los tests corren el **grafo compilado** verificando que las claves de control sobreviven; el escape es absorbente, el progreso usa umbrales físicamente alcanzables y el orden de las reglas es fijo y justificado (cap. 5, IT.5.3.2).

## 9.6 Falla 5 — Degradaciones sensoriales silenciosas

Tres degradaciones de la entrada pasaron sin aviso, porque cada consumidor procesa lo que recibe sin poder saber que está corrupto (Anexo 11, IT.A11.3): una **inversión de canales RGB/BGR**, que el VLM procesaba sin reducir su confianza y que solo se detectó guardando las imágenes exactas enviadas al modelo; **primitivas de depuración** que persistían entre vuelos de una misma sesión y la cámara capturaba como estructuras ([Jansen et al., 2023](13-REFERENCIAS.md#ref-jansen-2023)); y una **actitud suprimida** por el binding de Cosys-AirSim, que reportaba pitch y roll en 0° y dejaba a la derotación del flujo con un solo eje.

**Contención.** La conversión de canales se hace en el punto de captura (cap. 3, IT.3.3), cada sesión empieza borrando las primitivas, la actitud se calcula del cuaternión con un test contra valores conocidos, y cada consulta guarda sus fotogramas exactos (cap. 4, IT.4.4).

## 9.7 Por qué el sistema sigue funcionando: el problema de la observabilidad

Ninguno de los seis modos de falla produce un error visible: el modelo responde JSON válido, el lazo ejecuta sin excepciones y las métricas agregadas no distinguen estas corridas de las fallidas por otras causas. Observar la salida, monitorear métricas o leer el log de errores es ciego a esta clase de error, porque el sistema se comporta *de manera consistente con sus premisas internas*, aunque estén corrompidas; los componentes de aprendizaje automático son más difíciles de aislar, probar y depurar que el código determinista ([Amershi et al., 2019](13-REFERENCIAS.md#ref-amershi-2019)). Lo que sí funciona:

1. **Auditar los contratos en la frontera de cada componente:** qué devuelve el productor cuando no tiene información y cómo lo interpreta el consumidor.
2. **Guardar los datos crudos enviados al modelo** —fotograma, prompt, respuesta y estado de cada ciclo, sincronizados con el video (cap. 4, IT.4.4)—: así se detectaron la inversión RGB/BGR y la Falla 6.
3. **Testear invariantes de contrato, no comportamiento:** «sin evidencia, ningún consumidor reporta el campo como despejado» captura la Falla 1 sin un vuelo.
4. **Testear el grafo compilado:** el descarte de la Falla 4 ocurre en el runtime de LangGraph y no aparece en tests sobre nodos sueltos.

## 9.8 Falla 6 — Integración del VLM: respuestas correctas ejecutadas al revés, ignoradas o casi constantes

Esta familia se identificó en corridas de diagnóstico sobre `citysim_pilot` con el VLM como fuente del lazo lento (doce corridas, ninguna completó la misión), comparando ciclo a ciclo la respuesta cruda del modelo con la acción ejecutada y con la profundidad de referencia, consultada a posteriori solo para la auditoría. Ninguno de los mecanismos produce una excepción, y las métricas agregadas registraban deadlocks «resueltos» en el 75–80 % de los casos.

### 9.8.1 Error de marco de referencia: «libre hacia la meta» ejecutado como «evadir a la izquierda»

El primer barrido respondió correctamente que la imagen tomada a ~16° del rumbo al waypoint estaba libre, y la acción ejecutada fue `EVADIR_IZQUIERDA`: el dron giró alejándose de la meta. Las imágenes se etiquetaban con su **rumbo absoluto** y el prompt pedía un ángulo **relativo**, de modo que el modelo copiaba la etiqueta y el parser la interpretaba como relativa. En las tres corridas analizadas, el dron se alejó de 82.6 m a 94–95 m del waypoint y tardó ~37 s en volver a la distancia de partida.

**Contención.** El modelo nunca reporta ángulos: identifica las imágenes por número y el código asigna a cada una el yaw **medido** al capturarla (cap. 5, IT.5.6). Un test reproduce el caso.

### 9.8.2 Default silencioso: la respuesta del modelo nunca llega a la decisión

El productor devolvía una descripción por sectores y el consumidor leía `decision.get("macro_action", "EVADIR_DERECHA")`: la clave no existía y **toda respuesta se ejecutaba como `EVADIR_DERECHA`**, 11 de 15 despachos, 5 de ellos contra un lado que el propio modelo había descrito como bloqueado. Es un *schema drift* (IT.9.2) en sentido inverso, y ningún test recorría el camino completo desde la respuesta hasta la acción.

**Contención.** Cada modo de consulta tiene un esquema estricto; una respuesta que no coincide no produce ninguna acción, nunca un valor por defecto (Anexo 16, IT.A16.1), y los tests de integración recorren el grafo compilado desde la respuesta del modelo hasta la sub-meta.

### 9.8.3 Salida casi constante del modelo

Comparadas con la profundidad de referencia, **52 de 53 respuestas por sectores declararon el frente transitable**, y 18 de 19 lo hicieron con la superficie más cercana a ≤ 1.2 m; en los barridos, la primera imagen salió transitable casi siempre, con los valores del ejemplo del prompt. La respuesta no dependía de la escena, y ninguno de los 8 deadlocks «resueltos» por el modelo produjo avance neto hacia el waypoint. El hallazgo no se puede atribuir solo al modelo: el prompt tenía un ejemplo con valores concretos y una instrucción contradictoria, y las imágenes eran de 256–384 px.

**Contención.** La pregunta, la granularidad y el prompt se rediseñaron contra estas causas (cap. 8, IT.8.3; Anexo 16, IT.A16.6), y se construyó el banco de prueba para medir si el modelo discrimina (cap. 10, IT.10.2). No lo hace (IT.9.9, riesgo D); las corridas piloto posteriores muestran el mismo patrón por posición, con independencia de la imagen (Anexo 11, IT.A11.4.5–IT.A11.4.7).

### 9.8.4 Reglas apiladas sobre la decisión del modelo

Compensar cada falla de una corrida piloto con una regla determinista había acumulado hasta seis capas de reescritura sobre la decisión del modelo —retrocesos, desvíos perpendiculares, reglas sobre la historia de la trayectoria, escapes tras escaneos «fútiles»—, y el brazo evaluado medía esas reglas tanto como al modelo. Medidas contra el avance hacia el waypoint real en los 10–20 s siguientes, ninguna mostró beneficio: los retrocesos tuvieron avance mediano negativo y 74 desvíos deterministas avanzaron 0.35 m de mediana en 20 s (Anexo 11, IT.A11.8). Una regla que corrige un síntoma sin medir su efecto agregado no se distingue, desde las métricas de éxito, de una que empeora el sistema.

**Contención.** La respuesta de la fuente se traduce a geometría y se aplica sin reglas que la reemplacen (cap. 5, IT.5.8). El criterio para incluir un componente en el lazo es haber mostrado avance hacia el waypoint real, o ser parte del lazo rápido común a los tres brazos.

### 9.8.5 Otros casos

Las corridas de diagnóstico y piloto mostraron otros siete casos de la misma clase, documentados con su contención en el Anexo 11:

| Caso | Qué pasó | Detalle |
|---|---|---|
| Deadlock falso en el despegue | El contador de «detenido» sumaba los ciclos de ascenso | IT.A11.4.1 |
| Señal de referencia dentro del brazo evaluado | La profundidad del simulador, capturada «solo como métrica», alimentaba un freno que el grafo consumía | IT.A11.4.2 |
| Causa física de los `physics_locked` | El dron quedaba apoyado sobre superficies horizontales a la altura de vuelo que el flujo frontal no ve | IT.A11.4.3 |
| Señales que se tapan entre sí | Un techo inventado durante un giro y una velocidad reportada con el dron inmóvil ocultaron un bloqueo de 220 ciclos | IT.A11.4.4 |
| Sub-metas que ocultan al waypoint real | 573 ciclos a menos de 3.5 m del waypoint sin aceptarlo, con una sub-meta dentro de un edificio | IT.A11.4.5 |
| Respuesta cortada y capa sin voz | Un tope de tokens truncaba 5 de 12 barridos; la capa no consultaba con la meta fuera de cuadro | IT.A11.4.6 |
| Barrido que no describe la escena | 19 de 19 barridos con el mismo patrón de rumbos transitables | IT.A11.4.7 |

## 9.9 Riesgos residuales y trabajo pendiente

Los modos de falla documentados tienen su contención y los casos de IT.9.8 están cubiertos por tests de regresión, pero la arquitectura admite instancias análogas. **Riesgo A — nuevas claves de estado**: falta un test de contrato que recorra el código y falle ante cualquier clave no declarada. **Riesgo B — cambios en el binding de AirSim** ([Jansen et al., 2023](13-REFERENCIAS.md#ref-jansen-2023)), que pueden alterar métodos como la conversión de actitud (IT.9.6). **Riesgo C — imágenes fuera del dominio de entrenamiento**: la brecha entre el render de AirSim y las imágenes reales con que se entrenaron el VLM y la red de profundidad (cap. 6, IT.6.12.4).

**Riesgo D — Que el VLM no discrimine (materializado).** El diseño corrige cómo se pregunta y cómo se usa la respuesta, pero no puede garantizar que el modelo distinga sectores volables de bloqueados (IT.9.8.3). El banco de prueba lo confirma: la grilla queda en AUC 0.53 y el barrido declara transitables todos los rumbos (cap. 11, IT.11.0). La respuesta del diseño no es una regla que compense al modelo, sino una fuente que sí responde la pregunta, la profundidad estimada (cap. 6, IT.6.12), con el VLM donde aporta: el plan de ruta (cap. 4, IT.4.3.1).
