# 8. Ingeniería del VLM: percepción semántica y decisiones de implementación

Este capítulo documenta las decisiones de ingeniería del modelo de visión-lenguaje: selección bajo restricciones de hardware, salida estructurada, rol del modelo como perceptor semántico, ingeniería del prompt y gestión de la latencia.

> **Rol del VLM.** Con la configuración por defecto el VLM no interviene en el vuelo. Medido contra etiquetas de referencia, no distingue sectores volables de bloqueados ni rumbos abiertos de cerrados (cap. 11, IT.11.0). La capa estratégica y el barrido usan la profundidad estimada (cap. 6, IT.6.12), y el VLM trabaja en la planificación de ruta previa al vuelo (cap. 4, IT.4.3.1), la única tarea en la que aporta una señal medible. Lo que sigue describe la ingeniería del VLM, compartida por el planificador de ruta y por las fuentes alternativas del lazo lento.

## 8.1 Selección del modelo: restricciones de hardware como parámetro de diseño

La selección del modelo es un proceso de diseño con restricciones duras. El sistema corre en una RTX 5060 con 8 GB de VRAM compartidos con Unreal Engine 5.5, que en vuelo consume entre 4.5 y 6 GB ([Turco et al., 2024](13-REFERENCIAS.md#ref-turco-2024)): quedan **2 a 3.5 GB** para el modelo, incluida su caché de atención. Eso excluye a los modelos de referencia del estado del arte, en la nube o con hardware de 24–80 GB, y orienta la búsqueda hacia modelos multimodales compactos cuantizados, de 1.5 a 7 mil millones de parámetros, ejecutados localmente.

### 8.1.1 El requisito de visión directa

El sistema usa un modelo multimodal, que recibe el fotograma, y no uno textual que solo recibiría la telemetría y un resumen de percepción, por cobertura funcional. Cuando el flujo óptico no tiene evidencia (hover, giro puro, baja textura; cap. 6, IT.6.11), el resumen está vacío y un modelo textual no tiene sobre qué razonar. El flujo tampoco codifica semántica —árbol o edificio, sombra u obstáculo sólido— ni representa las superficies horizontales a la altura de vuelo, como el tablero de una autopista elevada, sobre las que el dron puede quedar apoyado (Anexo 11, IT.A11.4.3); el fotograma sí las muestra.

### 8.1.2 Modelo adoptado y candidatos evaluados

El modelo adoptado es **LFM2.5-VL-1.6B** (Liquid AI; cuantización Q4_K_M, formato GGUF), servido por Ollama en la **misma GPU** que la simulación y el grafo de control, que es la condición representativa de un dron real: un modelo a bordo comparte el cómputo con el resto del sistema de vuelo. Combina un núcleo de lenguaje de 1.2 B parámetros con decodificación rápida y un codificador visual SigLIP2 de 400 M; con el contexto limitado a 8192 tokens ocupa ~1.6 GB de VRAM, y la consulta más pesada del sistema, un barrido de cuatro imágenes, usa ~800 tokens de entrada. Frente a **Qwen2.5-VL-3B-Instruct**, el otro candidato con visión que cabe en la VRAM, gana por latencia —Qwen tarda ~10–12 s por consulta con imagen— sin discriminar peor (cap. 9, IT.9.8.3); en los *benchmarks* públicos ambos están en el mismo rango, y ninguno mide la tarea de vuelo, que decide el banco de prueba (cap. 11, IT.11.0). Es también el modelo del planificador de ruta (cap. 4, IT.4.3.1). La variante *Extract* del mismo modelo se descartó porque completa el esquema sin mirar la imagen. La exploración de candidatos está en el [Anexo 1](anexos/A1-EXPLORACION-SLM-GGUF.md):

| Modelo | Tamaño (cuant.) | VRAM aprox. | Descartado por |
|---|---|---|---|
| Phi-4-mini-Instruct | ~2.5 GB | ~2–3 GB | Sin capacidad de visión nativa |
| Qwen3-4B-Instruct | ~3 GB | ~2.5–3.5 GB | Sin soporte visual en la rama 3B |
| SmolLM3-3B | ~2 GB | ~1.8 GB | Sin soporte visual; razonamiento débil |
| **LFM2.5-VL-1.6B** (Q4_K_M, GGUF) | 0.73 GB + codificador visual | **~1.6 GB** (contexto 8 k) | **Adoptado** |
| Qwen2.5-VL-3B-Instruct (Q4_K_M) | ~2 GB | ~2.0 GB | ~10–12 s por consulta con imagen, sin mejor discriminación |
| Qwen2.5-VL-7B-Instruct | ~4.5 GB | ~4–5 GB | VRAM insuficiente con UE5.5 activo |

El criterio de selección fue: visión nativa, menos de 2.5 GB cuantizado, soporte de salida restringida por esquema JSON en el servidor de inferencia y latencia menor a 2 s para un prompt típico (las latencias medidas están en IT.8.6).

### 8.1.3 Posicionamiento respecto al estado del arte

La arquitectura de lazo cerrado estado→VLM→acción no es, hacia 2025–2026, una contribución novedosa: es un patrón establecido en UAVs controlados por modelos de lenguaje, representado por EMMA ([Hwang et al., 2024](13-REFERENCIAS.md#ref-hwang-2024)) y UAV-VLN ([Saxena et al., 2025](13-REFERENCIAS.md#ref-saxena-2025)). El aporte de esta tesis está en la ingeniería de su interfaz con la percepción monocular (cap. 6) y en la caracterización de sus modos de falla (cap. 9).

## 8.2 Salida estructurada: decodificación restringida y parser

Sin restricciones sobre la salida, la causa más frecuente de fallo de una consulta no es una decisión incorrecta sino un JSON malformado que rompe el parser. La salida se asegura en dos capas.

### 8.2.1 Decodificación restringida (`json_schema`)

La respuesta se pide con un esquema JSON, y durante la generación el servidor enmascara los tokens que producirían una salida inválida para ese esquema, de modo que el modelo solo muestrea tokens válidos. El mecanismo —la gramática del esquema como una máquina de estados que restringe los tokens admisibles en cada paso— lo formalizan [Willard y Louf (2023)](13-REFERENCIAS.md#ref-willard-2023), y [Raspanti et al. (2025)](13-REFERENCIAS.md#ref-raspanti-2025) y [Geng et al. (2025)](13-REFERENCIAS.md#ref-geng-2025) evalúan su efecto sobre la fiabilidad de la salida (desarrollo formal en el [Anexo 4](anexos/A4-DECODIFICACION-RESTRINGIDA.md)). Con la decodificación activa, la adherencia al esquema medida pasa de ~73 % (solo prompt) a ~98 %.

Hay **dos esquemas**, uno por modo de consulta, y ninguno contiene un campo de acción: el modelo describe, el código traduce. El **estratégico** pide los nueve sectores de la grilla, cada uno `free` o `blocked`; el **panorámico** pide, por imagen del barrido, qué hay delante a la altura del dron (un enum de seis valores) y si se puede volar recto 15 m. Ninguno pide certeza ni un indicador de imagen degradada: el modelo los rellenaba con valores fijos y ninguno decidía nada. Las imágenes se identifican por número y no por ángulo, porque el rumbo real de cada una lo conoce el código (IT.8.3.3). Los esquemas completos están en el Anexo 4 (IT.A4.9.1).

### 8.2.2 Parser como red de seguridad

Si el servidor no soporta el esquema, la consulta se repite en modo libre; en ambos casos el parser extrae el primer objeto JSON del texto y lo valida contra el modo: una respuesta estratégica con algún sector ausente o fuera del enum se rechaza completa. Una respuesta rechazada **no se sustituye por una decisión determinista**: la capa estratégica no propone sub-meta en ese ciclo, y un barrido sin respuesta válida cae al escape vertical (IT.5.3.4) como ante cualquier otra falla.

## 8.3 Rol del VLM: percepción semántica anclada al mundo

El VLM **no elige macro-acciones**: describe lo que ve, y la navegación convierte esa descripción en geometría. Lo que se le pregunta está elegido para que la respuesta siga siendo válida cuando llega.

### 8.3.1 Por qué esta pregunta

Una interfaz aparentemente más simple —describir tres sectores relativos al cuerpo (`frente`, `izquierda`, `derecha`)— tuvo dos problemas en las corridas de diagnóstico (cap. 9, IT.9.8). **Latencia**: una respuesta con imagen tarda varios ciclos, y el «frente» de la respuesta ya no es el frente del dron. **Contenido**: en 52 de 53 respuestas el modelo declaró el frente transitable, incluso con una superficie a 0.1–1 m según la profundidad de referencia. El diseño responde al primero anclando la respuesta a la pose del fotograma y, al segundo, con más granularidad (una grilla de 3×3 con la meta marcada en la imagen) y un prompt sin ejemplos que un modelo pequeño pueda copiar (IT.8.5). El banco de prueba responde si eso alcanza: no alcanza. La grilla queda en 53 % de exactitud balanceada (AUC 0.53), con las filas de arriba y de abajo «libres» en todas las muestras y la del medio dependiente de la posición del sector más que de la escena (cap. 11, IT.11.0).

### 8.3.2 Capa estratégica: grilla de 3×3 con dirección absoluta

Un recorte cuadrado del centro del fotograma se divide en una grilla de 3×3 —columnas de izquierda a derecha, filas arriba, a la altura del dron y abajo—, con la dirección del destino marcada en azimut y elevación, y para cada sector el modelo dice si se puede volar al menos 15 m en esa dirección. Una partición en columnas solo describe el eje horizontal; la grilla agrega el vertical y permite decir que un obstáculo a la altura del dron se pasa por arriba, sin pedir al modelo un concepto abstracto como «estructura debajo», que en las consultas de diagnóstico respondía `true` casi siempre (Anexo 11, IT.A11.4.5).

La traducción a una sub-meta usa la pose **del fotograma** (cap. 5, IT.5.5.3), de modo que la geometría que el modelo describió se transporta al mundo sin depender de hacia dónde mira el dron cuando la respuesta llega. El recorte cuadrado deja los sectores laterales y los verticales a la misma distancia angular del centro (±24°), para que la preferencia entre rodear por el costado o por arriba no la decida la forma del cuadro; ante un empate, con un margen de 10°, gana la fila del medio, porque con empate exacto una meta medio grado por debajo del dron haría ganar siempre a la fila de abajo y el dron podría descender hasta apoyarse en una autopista elevada.

### 8.3.3 Barrido: imágenes numeradas, rumbos medidos

En el barrido (cap. 5, IT.5.6), el modelo describe cuatro imágenes numeradas, y el código asigna a cada una el yaw **medido** al capturarla. Así se evita el error de marco de referencia documentado en el capítulo 9 (IT.9.8.1): con imágenes etiquetadas por su rumbo absoluto y un ángulo relativo pedido al modelo, el modelo copiaba la etiqueta, y «la dirección hacia la meta está libre» terminaba ejecutándose como una evasión hacia el lado contrario.

### 8.3.4 Vocabulario de macro-acciones

El vocabulario del sistema es fijo: `MANTENER_RUMBO`, `EVADIR_IZQUIERDA`, `EVADIR_DERECHA`, `GANAR_ALTURA`, `PERDER_ALTURA`, `FRENAR`, `GIRAR_90` y `RETROCEDER`. El modelo no elige ninguna. Sus descripciones producen, a través del código, `MANTENER_RUMBO` hacia una sub-meta o un escape vertical cuando el barrido no encuentra rumbos transitables; el resto las emite el lazo rápido o la FSM, y `RETROCEDER`, aunque está definido, ningún comportamiento del brazo `slm` lo emite (cap. 5, IT.5.3.4).

## 8.4 `action_to_command`: la frontera entre decisión y cinemática

Cada macro-acción se traduce a un comando cinemático en una única función compartida por el lazo rápido, el barrido y la FSM (cap. 5, IT.5.4; tabla en el Anexo 10, IT.A10.4.7). Centralizar la traducción impide que una misma macro-acción tenga cinemáticas distintas según quién la active: si cada brazo tuviera su propia tabla de velocidades, divergirían sutilmente y producirían diferencias de trayectoria que no provienen de la decisión.

## 8.5 Ingeniería del prompt

Los prompts siguen cinco reglas:

1. **Solo hechos, ninguna sugerencia de acción.** Un prompt que pide «describir sin decidir» y a la vez sugiere qué maniobra priorizar es contradictorio (cap. 9, IT.9.8.3). Los prompts dan solo lo que el modelo no puede ver en la imagen (distancia al destino, sector de la meta, altura).
2. **Sin ejemplos.** El esquema ya fija la forma de la respuesta, y un modelo pequeño copia los valores de cualquier ejemplo en sus respuestas (cap. 9, IT.9.8.3).
3. **La geometría la aporta el código.** El modelo nunca reporta ángulos ni posiciones: identifica sectores o imágenes por su etiqueta.
4. **Lo visual en la imagen, no en el texto.** La meta se marca **sobre** el fotograma, no se describe como «X grados a la derecha».
5. **En inglés y breves.** Los modelos de este tamaño siguen mejor instrucciones en inglés, y cada token del prompt se procesa en cada consulta: tres o cuatro oraciones por prompt de sistema. Ningún prompt nombra objetos de un escenario en particular (cap. 10, IT.10.2).

Los prompts completos, los parámetros de inferencia y la elección de nombres de campo cortos para acotar la decodificación están en el Anexo 4 (IT.A4.9).

## 8.6 Gestión de latencia

El tiempo de inferencia del VLM es un orden de magnitud mayor que el período del lazo (200 ms). La consulta corre en un hilo de servicio (Anexo 10, IT.A10.6.2) y nunca bloquea al grafo: es la separación entre una capa de ejecución que siempre responde y una capa deliberativa lenta de las arquitecturas de tres capas ([Gat, 1998](13-REFERENCIAS.md#ref-gat-1998)).

| Fuente | Condición | Latencia |
|---|---|---|
| Piloto con el VLM como fuente estratégica (65 consultas, sin *timeouts*) | Capa estratégica, un fotograma de 384 px | mediana 0.77 s · p90 0.80 s · máx 2.8 s |
| Banco de prueba (cap. 11, IT.11.0) | Grilla 3×3, un fotograma | 0.88 s |
| Banco de prueba | Barrido de cuatro imágenes de 256 px | 2.6–3.1 s |

Las cifras no provienen de una medición controlada que aísle la carga de GPU o el arranque en frío; Qwen2.5-VL-3B, como referencia, tarda 5.3 s de mediana con un fotograma. Ninguna cabe en el ciclo de 200 ms: en 0.8 s el dron avanza unos metros y gira. Por eso, con la capa estratégica el dron **no se frena** —la respuesta, cuando llega, se traduce con la pose del fotograma, y mantener el avance preserva la traslación que el flujo óptico necesita—, y solo el barrido lo mantiene en el lugar, bajo un watchdog que lo hace caer al escape vertical. La validez de una respuesta se controla geométricamente: se descarta si tiene más de 10 s, si cambió el waypoint o si el dron ya superó la sub-meta que produciría.

## 8.7 Nota: LoRA como alternativa explorada y no adoptada

El ajuste fino ligero vía LoRA (*Low-Rank Adaptation*) podría especializar el modelo con pares (imagen, respuesta correcta) derivados de las corridas del sistema ([Anexo 3](anexos/A3-OPTIMIZACION-LORA.md)). No se implementa por decisión de alcance, no por omisión: las corridas contienen situaciones homogéneas y un adaptador entrenado sobre ellas podría sobreajustar a los escenarios vistos, y versionarlo y evaluarlo junto con el modelo base tiene un costo que el beneficio esperado no justifica.
