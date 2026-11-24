# Anexo 16: Ingeniería del VLM: parser, geometría de las consultas, prompts y latencia

El capítulo 8 presenta la selección del modelo de visión-lenguaje, la salida estructurada y la pregunta que se le hace. Este anexo reúne el detalle de implementación que la sostiene: el parser, la geometría de la grilla estratégica y del barrido, el vocabulario de macro-acciones y su traducción a cinemática, las reglas de los prompts, la gestión de la latencia y la alternativa de ajuste fino no adoptada. Con la configuración evaluada el VLM no interviene en el vuelo (cap. 11, IT.11.0): lo que sigue vale para el planificador de ruta y para las fuentes alternativas del lazo lento evaluadas en el banco.

---

## A16.1 Parser como red de seguridad

Si el servidor no soporta el esquema, la consulta se repite en modo libre; en ambos casos el parser extrae el primer objeto JSON del texto y lo valida contra el modo: una respuesta estratégica con algún sector ausente o fuera del enum se rechaza completa. Una respuesta rechazada **no se sustituye por una decisión determinista**: la capa estratégica no propone sub-meta en ese ciclo, y un barrido sin respuesta válida cae al escape vertical (cap. 5, IT.5.3.4) como ante cualquier otra falla.

## A16.2 Geometría de la grilla estratégica

La traducción a una sub-meta usa la pose **del fotograma** (cap. 5, IT.5.5.3), de modo que la geometría que el modelo describió se transporta al mundo sin depender de hacia dónde mira el dron cuando la respuesta llega. El recorte cuadrado deja los sectores laterales y los verticales a la misma distancia angular del centro (±24°), para que la preferencia entre rodear por el costado o por arriba no la decida la forma del cuadro; ante un empate, con un margen de 10°, gana la fila del medio, porque con empate exacto una meta medio grado por debajo del dron haría ganar siempre a la fila de abajo y el dron podría descender hasta apoyarse en una autopista elevada.

## A16.3 Barrido: imágenes numeradas, rumbos medidos

En el barrido (cap. 5, IT.5.6), el modelo describe cuatro imágenes numeradas, y el código asigna a cada una el yaw **medido** al capturarla. Así se evita el error de marco de referencia documentado en el capítulo 9 (IT.9.8.1): con imágenes etiquetadas por su rumbo absoluto y un ángulo relativo pedido al modelo, el modelo copiaba la etiqueta, y «la dirección hacia la meta está libre» terminaba ejecutándose como una evasión hacia el lado contrario. Por la misma razón los esquemas identifican las imágenes por número y no por ángulo: el rumbo real de cada una lo conoce el código.

## A16.4 Vocabulario de macro-acciones

El vocabulario del sistema es fijo: `MANTENER_RUMBO`, `EVADIR_IZQUIERDA`, `EVADIR_DERECHA`, `GANAR_ALTURA`, `PERDER_ALTURA`, `FRENAR`, `GIRAR_90` y `RETROCEDER`. El modelo no elige ninguna. Sus descripciones producen, a través del código, `MANTENER_RUMBO` hacia una sub-meta o un escape vertical cuando el barrido no encuentra rumbos transitables; el resto las emite el lazo rápido o la FSM, y `RETROCEDER`, aunque está definido, ningún comportamiento del brazo `depth2loop` lo emite (cap. 5, IT.5.3.4).

## A16.5 `action_to_command`: la frontera entre decisión y cinemática

Cada macro-acción se traduce a un comando cinemático en una única función compartida por el lazo rápido, el barrido y la FSM (cap. 5, IT.5.4; tabla en el Anexo 10, IT.A10.4.7). Centralizar la traducción impide que una misma macro-acción tenga cinemáticas distintas según quién la active: si cada brazo tuviera su propia tabla de velocidades, divergirían sutilmente y producirían diferencias de trayectoria que no provienen de la decisión.

## A16.6 Ingeniería del prompt

Los prompts siguen cinco reglas:

1. **Solo hechos, ninguna sugerencia de acción.** Un prompt que pide «describir sin decidir» y a la vez sugiere qué maniobra priorizar es contradictorio (cap. 9, IT.9.8.3). Los prompts dan solo lo que el modelo no puede ver en la imagen (distancia al destino, sector de la meta, altura).
2. **Sin ejemplos.** El esquema ya fija la forma de la respuesta, y un modelo pequeño copia los valores de cualquier ejemplo en sus respuestas (cap. 9, IT.9.8.3).
3. **La geometría la aporta el código.** El modelo nunca reporta ángulos ni posiciones: identifica sectores o imágenes por su etiqueta.
4. **Lo visual en la imagen, no en el texto.** La meta se marca **sobre** el fotograma, no se describe como «X grados a la derecha».
5. **En inglés y breves.** Los modelos de este tamaño siguen mejor instrucciones en inglés, y cada token del prompt se procesa en cada consulta: tres o cuatro oraciones por prompt de sistema. Ningún prompt nombra objetos de un escenario en particular (cap. 10, IT.10.2).

Los prompts completos, los parámetros de inferencia y la elección de nombres de campo cortos para acotar la decodificación están en el Anexo 4 (IT.A4.9).

## A16.7 Gestión de latencia

El tiempo de inferencia del VLM es un orden de magnitud mayor que el período del lazo (200 ms). La consulta corre en un hilo de servicio (Anexo 10, IT.A10.6.2) y nunca bloquea al grafo: es la separación entre una capa de ejecución que siempre responde y una capa deliberativa lenta de las arquitecturas de tres capas ([Gat, 1998](../13-REFERENCIAS.md#ref-gat-1998)).

| Fuente | Condición | Latencia |
|---|---|---|
| Piloto con el VLM como fuente estratégica (65 consultas, sin *timeouts*) | Capa estratégica, un fotograma de 384 px | mediana 0.77 s · p90 0.80 s · máx 2.8 s |
| Banco de prueba (cap. 11, IT.11.0) | Grilla 3×3, un fotograma | 0.88 s |
| Banco de prueba | Barrido de cuatro imágenes de 256 px | 2.6–3.1 s |

Las cifras no provienen de una medición controlada que aísle la carga de GPU o el arranque en frío; Qwen2.5-VL-3B, como referencia, tarda 5.3 s de mediana con un fotograma. Ninguna cabe en el ciclo de 200 ms: en 0.8 s el dron avanza unos metros y gira. Por eso, con la capa estratégica el dron **no se frena** —la respuesta, cuando llega, se traduce con la pose del fotograma, y mantener el avance preserva la traslación que el flujo óptico necesita—, y solo el barrido lo mantiene en el lugar, bajo un watchdog que lo hace caer al escape vertical. La validez de una respuesta se controla geométricamente: se descarta si tiene más de 10 s, si cambió el waypoint o si el dron ya superó la sub-meta que produciría.

## A16.8 LoRA como alternativa explorada y no adoptada

El ajuste fino ligero vía LoRA (*Low-Rank Adaptation*) podría especializar el modelo con pares (imagen, respuesta correcta) derivados de las corridas del sistema ([Anexo 3](A3-OPTIMIZACION-LORA.md)). No se implementa por decisión de alcance, no por omisión: las corridas contienen situaciones homogéneas y un adaptador entrenado sobre ellas podría sobreajustar a los escenarios vistos, y versionarlo y evaluarlo junto con el modelo base tiene un costo que el beneficio esperado no justifica. El trabajo futuro lo retoma con otro objetivo —la calidad de la respuesta— y un conjunto de entrenamiento distinto (cap. 12, IT.12.4).
