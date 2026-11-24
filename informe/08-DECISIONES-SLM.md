# 8. Ingeniería del VLM: percepción semántica y decisiones de implementación

Este capítulo documenta cómo se eligió el modelo de visión-lenguaje, cómo se asegura su salida y qué se le pregunta. El detalle de implementación —parser, geometría de las consultas, vocabulario de macro-acciones, prompts y latencia— está en el Anexo 16.

> **Rol del VLM.** Con la configuración por defecto el VLM no interviene en el vuelo. Medido contra etiquetas de referencia, no distingue sectores volables de bloqueados ni rumbos abiertos de cerrados (cap. 11, IT.11.0). La capa estratégica y el barrido usan la profundidad estimada (cap. 6, IT.6.12), y el VLM trabaja en la planificación de ruta previa al vuelo (cap. 4, IT.4.3.1), la única tarea en la que aporta una señal medible. Lo que sigue describe la ingeniería del VLM, compartida por el planificador de ruta y por las fuentes alternativas del lazo lento.

## 8.1 Selección del modelo: restricciones de hardware como parámetro de diseño

El sistema corre en una RTX 5060 con 8 GB de VRAM compartidos con Unreal Engine 5.5, que en vuelo consume entre 4.5 y 6 GB ([Turco et al., 2024](13-REFERENCIAS.md#ref-turco-2024)): quedan **2 a 3.5 GB** para el modelo, incluida su caché de atención. Eso excluye a los modelos de referencia del estado del arte y orienta la búsqueda hacia modelos multimodales compactos cuantizados, de 1.5 a 7 mil millones de parámetros, ejecutados localmente. La arquitectura estado→VLM→acción es un patrón establecido en UAVs, representado por EMMA ([Hwang et al., 2024](13-REFERENCIAS.md#ref-hwang-2024)) y UAV-VLN ([Saxena et al., 2025](13-REFERENCIAS.md#ref-saxena-2025)); el aporte de esta tesis está en la interfaz con la percepción monocular (cap. 6) y en la caracterización de sus modos de falla (cap. 9).

### 8.1.1 El requisito de visión directa

El sistema usa un modelo multimodal, que recibe el fotograma, y no uno textual que solo recibiría la telemetría y un resumen de percepción. Cuando el flujo óptico no tiene evidencia (hover, giro puro, baja textura; cap. 6, IT.6.11), el resumen está vacío y un modelo textual no tiene sobre qué razonar. El flujo tampoco codifica semántica —árbol o edificio, sombra u obstáculo sólido— ni representa las superficies horizontales a la altura de vuelo, como el tablero de una autopista elevada (Anexo 11, IT.A11.4.3); el fotograma sí las muestra.

### 8.1.2 Modelo adoptado y candidatos evaluados

El modelo adoptado es **LFM2.5-VL-1.6B** (Liquid AI; Q4_K_M, GGUF), servido por Ollama en la **misma GPU** que la simulación y el grafo de control, la condición representativa de un dron real. Combina un núcleo de lenguaje de 1.2 B parámetros con un codificador visual SigLIP2 de 400 M y, con el contexto limitado a 8192 tokens, ocupa ~1.6 GB de VRAM. Frente a **Qwen2.5-VL-3B-Instruct**, el otro candidato con visión que cabe en la VRAM, gana por latencia —Qwen tarda ~10–12 s por consulta con imagen— sin discriminar peor (cap. 9, IT.9.8.3); ningún *benchmark* público mide la tarea de vuelo, que decide el banco de prueba (cap. 11, IT.11.0). Es también el modelo del planificador de ruta. La variante *Extract* se descartó porque completa el esquema sin mirar la imagen. La exploración de candidatos está en el [Anexo 1](anexos/A1-EXPLORACION-SLM-GGUF.md):

| Modelo | Tamaño (cuant.) | VRAM aprox. | Descartado por |
|---|---|---|---|
| Phi-4-mini-Instruct | ~2.5 GB | ~2–3 GB | Sin capacidad de visión nativa |
| Qwen3-4B-Instruct | ~3 GB | ~2.5–3.5 GB | Sin soporte visual en la rama 3B |
| SmolLM3-3B | ~2 GB | ~1.8 GB | Sin soporte visual; razonamiento débil |
| **LFM2.5-VL-1.6B** (Q4_K_M, GGUF) | 0.73 GB + codificador visual | **~1.6 GB** (contexto 8 k) | **Adoptado** |
| Qwen2.5-VL-3B-Instruct (Q4_K_M) | ~2 GB | ~2.0 GB | ~10–12 s por consulta con imagen, sin mejor discriminación |
| Qwen2.5-VL-7B-Instruct | ~4.5 GB | ~4–5 GB | VRAM insuficiente con UE5.5 activo |

El criterio fue: visión nativa, menos de 2.5 GB cuantizado, salida restringida por esquema JSON en el servidor de inferencia y latencia menor a 2 s por consulta (las latencias medidas están en el Anexo 16, IT.A16.7).

## 8.2 Salida estructurada: decodificación restringida

Sin restricciones sobre la salida, la causa más frecuente de fallo de una consulta no es una decisión incorrecta sino un JSON malformado. La respuesta se pide con un esquema JSON, y durante la generación el servidor enmascara los tokens que producirían una salida inválida, de modo que el modelo solo muestrea tokens válidos ([Willard y Louf, 2023](13-REFERENCIAS.md#ref-willard-2023); [Raspanti et al., 2025](13-REFERENCIAS.md#ref-raspanti-2025); [Geng et al., 2025](13-REFERENCIAS.md#ref-geng-2025); desarrollo formal en el [Anexo 4](anexos/A4-DECODIFICACION-RESTRINGIDA.md)). Con la decodificación activa, la adherencia al esquema pasa de ~73 % (solo prompt) a ~98 %.

Hay **dos esquemas**, uno por modo de consulta, y ninguno contiene un campo de acción: el modelo describe, el código traduce. El **estratégico** pide los nueve sectores de la grilla, cada uno `free` o `blocked`; el **panorámico** pide, por imagen del barrido, qué hay delante a la altura del dron y si se puede volar recto 15 m. Una respuesta que no valida contra su esquema se rechaza completa y **no se sustituye por una decisión determinista** (Anexo 16, IT.A16.1). Los esquemas completos están en el Anexo 4 (IT.A4.9.1).

## 8.3 Rol del VLM: percepción semántica anclada al mundo

El VLM **no elige macro-acciones**: describe lo que ve, y la navegación convierte esa descripción en geometría. Lo que se le pregunta está elegido para que la respuesta siga siendo válida cuando llega.

### 8.3.1 Por qué esta pregunta

Una interfaz aparentemente más simple —describir tres sectores relativos al cuerpo (`frente`, `izquierda`, `derecha`)— tuvo dos problemas en las corridas de diagnóstico (cap. 9, IT.9.8). **Latencia**: una respuesta con imagen tarda varios ciclos, y el «frente» de la respuesta ya no es el frente del dron. **Contenido**: en 52 de 53 respuestas el modelo declaró el frente transitable, incluso con una superficie a 0.1–1 m según la profundidad de referencia. El diseño responde al primero anclando la respuesta a la pose del fotograma y, al segundo, con más granularidad y un prompt sin ejemplos que un modelo pequeño pueda copiar. El banco de prueba responde si eso alcanza: no alcanza. La grilla queda en 53 % de exactitud balanceada (AUC 0.53), con las filas de arriba y de abajo «libres» en todas las muestras y la del medio dependiente de la posición del sector más que de la escena (cap. 11, IT.11.0).

### 8.3.2 Capa estratégica: grilla de 3×3 con dirección absoluta

Un recorte cuadrado del centro del fotograma se divide en una grilla de 3×3 —columnas de izquierda a derecha, filas arriba, a la altura del dron y abajo—, con la dirección del destino marcada en azimut y elevación, y para cada sector el modelo dice si se puede volar al menos 15 m en esa dirección. La grilla agrega el eje vertical a una partición en columnas y permite decir que un obstáculo a la altura del dron se pasa por arriba, sin pedir al modelo un concepto abstracto como «estructura debajo», que en las consultas de diagnóstico respondía `true` casi siempre (Anexo 11, IT.A11.4.5). La respuesta se traduce a una sub-meta con la pose del fotograma (cap. 5, IT.5.5.3); la geometría del recorte y del desempate entre sectores está en el Anexo 16 (IT.A16.2).

## 8.4 Prompts, latencia y vocabulario

Los prompts dan solo hechos que el modelo no ve en la imagen, sin ejemplos ni sugerencias de acción, con la meta marcada sobre el fotograma y en tres o cuatro oraciones en inglés (Anexo 16, IT.A16.6). La consulta tarda 0.77–0.88 s con un fotograma y 2.6–3.1 s con las cuatro imágenes del barrido, un orden de magnitud más que el ciclo de 200 ms: corre en un hilo propio, nunca bloquea al grafo, y con la capa estratégica el dron no se frena a esperarla (IT.A16.7). El modelo no elige macro-acciones del vocabulario fijo del sistema, que una única función traduce a cinemática para todos los brazos (IT.A16.4–IT.A16.5). El ajuste fino con LoRA se exploró y no se adoptó (IT.A16.8).
