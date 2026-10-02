# 8. Ingeniería del VLM: percepción semántica y decisiones de implementación

El capítulo 5 documenta la arquitectura de la consulta asíncrona al VLM (cuándo se solicita, cómo se integra al grafo, qué hace el sistema con la respuesta). El capítulo 6 documenta por qué hace falta un VLM (los puntos ciegos del estimador de flujo). Este capítulo documenta las decisiones de ingeniería que hacen que ese VLM funcione de forma confiable: selección del modelo bajo restricciones de hardware, salida estructurada, rol del modelo como perceptor semántico, ingeniería del prompt y gestión de la latencia.

## 8.1 Selección del modelo: restricciones de hardware como parámetro de diseño

La selección del modelo de lenguaje no fue un proceso de *benchmark* abstracto sino un proceso de diseño con restricciones duras. El sistema corre en una RTX 5060 con 8 GB de VRAM compartidos con una simulación de Unreal Engine 5.5. AirSim sobre UE5.5 consume, en condiciones de vuelo activo, entre 4.5 y 6 GB de VRAM ([Turco et al., 2024](13-REFERENCIAS.md#ref-turco-2024)). El presupuesto efectivo disponible para la inferencia del modelo es de **2 a 3.5 GB de VRAM**, incluyendo la KV cache del historial de prompt.

Esta restricción excluye inmediatamente a los modelos de referencia del estado del arte (GPT-4o, Claude 3.5, Gemini 1.5 — todos en la nube o con hardware dedicado de 24–80 GB) y orienta la búsqueda hacia modelos multimodales compactos cuantizados (*Small Vision-Language Models*, VLM), del orden de 3 a 7 mil millones de parámetros, ejecutados localmente bajo LM Studio o vLLM.

### 8.1.1 El requisito de visión directa

Una distinción de diseño previa a la selección del modelo es si la consulta al modelo debe usar un modelo textual puro (recibe solo telemetría y resúmenes de percepción serializados) o un VLM multimodal (recibe además el fotograma de la cámara). El sistema adopta un VLM multimodal por razones que no son de conveniencia sino de cobertura funcional:

- **Puntos ciegos del flujo óptico** (§6.1, §6.12): cuando el estimador de flujo carece de evidencia (hover, giro puro, baja textura), el `ObstacleField` entregado al modelo es esencialmente vacío. Un modelo textual no puede razonar sobre la escena sin ese resumen; un VLM puede observar directamente el fotograma y evaluar el contexto visual.
- **Semántica que el flujo no codifica**: la distinción entre "árbol vs. edificio", "sombra vs. obstáculo sólido", o "calle con objetos vs. calle vacía" no está presente en el campo de divergencia. El VLM puede discriminar escenas semánticamente similares en percepción pero distintas en consecuencias de navegación.
- **Geometría que el flujo no representa**: las superficies horizontales a la altura de vuelo (tablero de una autopista elevada, cornisas, balcones) no producen expansión en el sector frontal; el fotograma sí las muestra. En las corridas de diagnóstico fue el obstáculo sobre el que el dron quedó apoyado e inmovilizado (cap. 9, §9.8.7).

### 8.1.2 Modelo adoptado y candidatos evaluados

El modelo adoptado en la implementación definitiva es **Qwen2.5-VL-3B-Instruct** (cuantización Q4_K_M, ~2.0 GB de VRAM), ejecutado vía LM Studio. Combina capacidad de razonamiento simbólico, comprensión visual real de la cámara y seguimiento de instrucciones estructuradas. Los modelos candidatos evaluados durante el diseño (documentados en `informe/anexos/A1-EXPLORACION-SLM-GGUF.md`) son:

| Modelo | Tamaño (cuant.) | VRAM aprox. | Descartado por |
|---|---|---|---|
| Phi-4-mini-Instruct | ~2.5 GB | ~2–3 GB | Sin capacidad de visión nativa |
| Qwen3-4B-Instruct | ~3 GB | ~2.5–3.5 GB | Sin soporte visual en la rama 3B |
| SmolLM3-3B | ~2 GB | ~1.8 GB | Sin soporte visual; razonamiento débil |
| **Qwen2.5-VL-3B-Instruct** | ~2 GB | **~2.0 GB** | **Adoptado** |
| Qwen2.5-VL-7B-Instruct | ~4.5 GB | ~4–5 GB | VRAM insuficiente con UE5.5 activo |

El criterio de selección fue: **(a)** soporte de visión nativa, **(b)** VRAM < 2.5 GB con Q4_K_M, **(c)** soporte de `response_format: json_schema` en el backend de inferencia, **(d)** latencia de inferencia < 2 s en el hardware disponible para prompts de ~500 tokens con dos imágenes. Es un criterio de diseño; las latencias efectivamente observadas en la configuración de producción, que en consultas con imagen lo superan, se documentan en §8.6.

### 8.1.3 Posicionamiento respecto al estado del arte

La arquitectura de lazo cerrado estado→VLM→macro-acción→ejecución no es, hacia 2025–2026, una contribución conceptualmente novedosa: es un patrón estandarizado en investigación y prototipos de UAVs controlados por modelos de lenguaje (véase la discusión en `informe/anexos/A1-EXPLORACION-SLM-GGUF.md`). [Hwang et al. (2024)](13-REFERENCIAS.md#ref-hwang-2024) en EMMA y [Saxena et al. (2025)](13-REFERENCIAS.md#ref-saxena-2025) en UAV-VLN son trabajos representativos del patrón. El aporte de esta tesis no está en la novedad de la arquitectura general, sino en la ingeniería de su interfaz con la percepción monocular (cap. 6) y en la caracterización sistemática de sus modos de falla (cap. 9).

## 8.2 Salida estructurada: decodificación restringida y parser

La primera causa observada de fallo de la consulta al VLM no fue una decisión incorrecta, sino una respuesta JSON malformada que rompía el parser. La salida se asegura en dos capas.

### 8.2.1 Decodificación restringida (`json_schema`)

La respuesta se solicita con `response_format={"type": "json_schema", "json_schema": {...}}`, disponible en LM Studio y en el backend OpenAI-compatible de Ollama. Durante la generación, el motor enmascara los logits de los tokens que producirían JSON inválido para el esquema, de modo que el modelo solo muestrea tokens válidos. El mecanismo —reformular la gramática del esquema como una máquina de estados finitos que restringe el conjunto de tokens admisibles en cada paso— es el que formalizan [Willard y Louf (2023)](13-REFERENCIAS.md#ref-willard-2023), base de la decodificación guiada que exponen hoy backends como llama.cpp; [Raspanti et al. (2025)](13-REFERENCIAS.md#ref-raspanti-2025) y [Geng et al. (2025)](13-REFERENCIAS.md#ref-geng-2025) evalúan empíricamente su impacto sobre la fiabilidad de la salida (desarrollo formal en el [Anexo 4](anexos/A4-DECODIFICACION-RESTRINGIDA.md)). Con la decodificación activa, el `adherence_rate` medido en escenarios de validación pasa de ~73 % (solo prompt) a ~98 %.

Hay **dos esquemas**, uno por modo de consulta (§5.10.5), y ninguno contiene un campo de acción: el modelo describe, el código traduce.

**Esquema estratégico** (`RESPONSE_JSON_SCHEMA_STRATEGIC`, `vlm_strategic.py`): una entrada por sector de la grilla de 3×3 del fotograma con valor `libre` o `bloqueado` (enum cerrado); los nueve sectores son obligatorios.

```json
{
  "type": "object",
  "properties": {
    "sectores": {
      "type": "object",
      "properties": {"A1": {"enum": ["libre", "bloqueado"]}, "B1": {...}, ..., "C3": {...}},
      "required": ["A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3", "C3"],
      "additionalProperties": false
    }
  },
  "required": ["sectores"],
  "additionalProperties": false
}
```

**Esquema panorámico** (`RESPONSE_JSON_SCHEMA_PANORAMA`, `deep_scan.py`): un array `rumbos` de objetos `{img, tipo, ok, conf}` —número de imagen, superficie predominante (enum de seis tipos: `libre`, `fachada`, `muro`, `vegetacion`, `interior`, `indeterminado`), transitable y certeza— más `degradada`, que se registra pero no decide (en las corridas piloto el modelo lo marcó `true` en todas las respuestas). Una entrada `ok: true` cuyo tipo no es `libre` se contradice a sí misma y no cuenta como transitable (cap. 5, §5.12). Las imágenes se identifican por número y no por ángulo: el rumbo real de cada imagen lo conoce el código, no el modelo (§8.3.3).

### 8.2.2 Parser como red de seguridad

La garantía de `json_schema` depende de que el backend la soporte. Si la llamada con esquema falla, `vlm_client._query_slm_impl()` reintenta en modo libre; en ambos casos `_extract_json_object()` elimina cercos de markdown y extrae el primer objeto `{...}` del texto, y el parser del modo (`parse_strategic` o `parse_panorama_description`) lo valida: una respuesta estratégica con algún sector ausente o con un valor fuera del enum se rechaza completa, y una respuesta panorámica sin array `rumbos` también. Una respuesta rechazada **no se sustituye por una decisión determinista**: la capa estratégica simplemente no propone sub-meta en ese ciclo (motivo `no_parseable`), y un barrido sin respuesta válida cae al escape vertical de §5.3.4 como cualquier otra falla del modelo.

## 8.3 Rol del VLM: percepción semántica anclada al mundo

El VLM **no elige macro-acciones**: describe lo que ve, y la capa de navegación convierte esa descripción en geometría. Lo que se le pregunta está elegido para que la respuesta siga siendo válida cuando llega.

### 8.3.1 Por qué esta pregunta

Una interfaz aparentemente más simple —pedir al modelo que describa tres sectores relativos al cuerpo (`frente`, `izquierda`, `derecha`)— tiene dos problemas, medidos en corridas de diagnóstico (cap. 9, §9.8):

1. **Latencia.** Una respuesta con imagen tarda 5.3 s de mediana (p95 12.9 s, 73 consultas). A 5 Hz son ~26 ciclos: el «frente» de la respuesta ya no es el frente del dron.
2. **Contenido informativo.** En 52 de 53 respuestas sectoriales (excluida una corrida en vegetación) el modelo declaró el frente transitable, incluso cuando la profundidad de referencia del simulador, consultada a posteriori, marcaba una superficie a 0.1–1 m. La respuesta era casi constante.

El diseño responde al primero anclando la respuesta a la pose del fotograma (§8.3.2) y, al segundo, con más granularidad (una grilla de 3×3, con la meta marcada en la imagen) y un prompt sin ejemplos de valores concretos que un modelo de 3B pueda copiar (§8.5.1). Si esto alcanza para que el modelo discrimine es una pregunta empírica abierta, que el registro de auditoría (§5.10.4) permite responder.

### 8.3.2 Capa estratégica: grilla de 3×3 con dirección absoluta

Un recorte cuadrado del centro del fotograma frontal —se cortan los dos costados del ancho— se divide en una grilla de 3×3 por tercios —la grilla de composición fotográfica—: columnas A, B, C (izquierda a derecha) y filas 1, 2, 3 (arriba, a la altura del dron, abajo). Se marca en la imagen la dirección del destino, en azimut y elevación. Para cada sector el modelo dice si se puede volar en esa dirección al menos 15 m.

Una partición en columnas solo describe el eje horizontal. La grilla agrega el vertical: permite que la respuesta diga que un obstáculo a la altura del dron se pasa por arriba (fila 1 libre, fila 2 bloqueada) y que una superficie horizontal se ve en la fila del medio, sin pedir al modelo un concepto abstracto como «estructura debajo». En corridas de diagnóstico, una pregunta de ese tipo («¿hay una estructura horizontal cercana?») recibió `true` en 5 de 6 consultas, con imágenes muy distintas (cap. 9, §9.8.9).

La traducción (`decide_subgoal`, detalle en §5.10.3) usa la pose **del fotograma**: la dirección absoluta del sector es el yaw del ancla más el azimut del centro del sector, con la elevación del centro del sector. La sub-meta se fija desde la posición del ancla, a no más de 15 m y nunca más lejos que el waypoint real, con la misma función que usa el barrido. El recorte cuadrado deja los sectores laterales y los verticales a la misma distancia angular del centro (±24°), de modo que la preferencia entre un rodeo por el costado y uno por arriba no la decide la forma del cuadro: a igual distancia gana la fila del medio. Así, la geometría que el modelo describió se transporta al mundo sin depender de hacia dónde mira el dron cuando la respuesta llega. Si el sector de la meta está libre, la capa no agrega nada y descarta cualquier desvío pendiente: la respuesta más frecuente esperable («el camino directo está libre») no genera maniobras.

### 8.3.3 Barrido: imágenes numeradas, rumbos medidos

En el barrido de resolución de atasco (§5.12), el modelo recibe cuatro imágenes numeradas y describe cada una (`img`, `tipo`, `ok`, `conf`). El código asigna a cada imagen el yaw **medido** en el ciclo en que se capturó y elige, entre las transitables, la de rumbo absoluto más cercano al rumbo absoluto hacia el waypoint real. Las entradas se asignan por número de imagen (o por orden si falta), y las entradas que el modelo inventa de más se descartan.

El diseño evita un error de marco de referencia documentado en el capítulo 9 (§9.8.1): si las imágenes se etiquetan con su rumbo absoluto y se pide al modelo un ángulo relativo, el modelo copia la etiqueta y el código la interpreta como relativa, de modo que «la dirección hacia la meta está libre» termina ejecutándose como una evasión hacia el lado contrario.

### 8.3.4 Vocabulario de macro-acciones

El vocabulario del sistema es fijo (`VALID_ACTIONS`, `action_map.py`): `MANTENER_RUMBO`, `EVADIR_IZQUIERDA`, `EVADIR_DERECHA`, `GANAR_ALTURA`, `PERDER_ALTURA`, `FRENAR`, `GIRAR_90` y `RETROCEDER`. El modelo no elige ninguna. Las descripciones del VLM producen, a través del código, `MANTENER_RUMBO` hacia una sub-meta, `GANAR_ALTURA` o `PERDER_ALTURA` (barrido sin rumbos transitables); el resto las emite el lazo rápido (evasión, `GIRAR_90`) o la FSM. `RETROCEDER` está definido pero ningún comportamiento del brazo `slm` lo emite (cap. 5, §5.3.4).

## 8.4 `action_to_command`: la frontera entre decisión y cinemática

Cada macro-acción se traduce a un comando cinemático en `action_to_command()` (`src/agents/action_map.py`), función compartida por el lazo rápido, el barrido y la FSM (tabla completa en cap. 5, §5.14). Valores relevantes: evasión lateral con `yaw_rate` ±15°/s y `target_yaw` redondeado a la cuadrícula de 90°, `vx` de 1.2 m/s en la evasión agresiva del lazo rápido; `GANAR_ALTURA` a −1.5 m/s en el lugar; `PERDER_ALTURA` a +0.8 m/s con avance de 1.0 m/s; `GIRAR_90` a ±20°/s sin traslación; `RETROCEDER` a −1.2 m/s con rumbo congelado.

**Invariante de diseño.** Centralizar la traducción impide que una misma macro-acción tenga cinemáticas distintas según quién la active. Si cada brazo tuviera su propia tabla de velocidades, divergirían sutilmente (por ejemplo, distinta velocidad vertical para `GANAR_ALTURA`) y producirían diferencias de trayectoria entre brazos que no provienen de la decisión.

## 8.5 Ingeniería del prompt

### 8.5.1 Principios

Los prompts siguen cuatro reglas:

1. **Solo hechos, ninguna sugerencia de acción.** Un prompt que pide al modelo «describir sin decidir» y a la vez le sugiere qué maniobra priorizar es contradictorio (cap. 9, §9.8.3). Los prompts describen la situación (distancia y dirección del destino, altura, qué imagen es cuál) y piden una descripción.
2. **Ejemplos sin valores concretos.** El ejemplo del esquema se escribe con marcadores (`<bool>`, `<0-1>`), no con valores. Un modelo de 3B tiende a copiar los valores del ejemplo (`"ok": true, "conf": 0.9`) en sus respuestas (cap. 9, §9.8.3).
3. **La geometría la aporta el código.** El modelo nunca reporta ángulos ni posiciones: identifica sectores o imágenes por su etiqueta, y el código conoce su dirección.
4. **Lo visual en la imagen, no en el texto.** La meta se marca **sobre** el fotograma (marca roja «META» en su dirección, dentro de la grilla) en lugar de describirse como «X grados a la derecha».

### 8.5.2 Prompt de la capa estratégica

**System prompt** (`SYSTEM_PROMPT_STRATEGIC`): rol de sistema de percepción de un dron a ~10 m de altura; descripción de la grilla (columnas, filas y qué significa cada fila); definición operativa de `libre` («se ve cielo, calle, plaza o espacio abierto en ese sector») y de `bloqueado` (edificio, fachada, vidrio, muro, árbol, puente, autopista elevada, cornisa, balcón, techo o el interior de un edificio a menos de 15 m); instrucción de responder solo el JSON con los nueve sectores.

**User prompt** (`build_request`): distancia al destino y su etiqueta, sector en el que cae la meta, altura del dron y la disposición de los sectores. Una única imagen de 384 px con la grilla y la marca de la meta dibujadas.

### 8.5.3 Prompt del barrido

**System prompt** (`SYSTEM_PROMPT_DEEP_SCAN`): las imágenes son direcciones distintas vistas desde el mismo punto (no fotogramas consecutivos); una entrada por imagen, en orden; definición de los seis tipos de superficie; `ok` verdadero **solo** si se puede volar recto 15 m sin chocar.

**User prompt** (`_build_panorama_prompt`): cuántos ciclos lleva el atasco, altura, y para cada imagen su ángulo respecto de la dirección en que el dron venía volando, cuál es la dirección en la que no pudo avanzar y cuál la más cercana al destino; distancia al destino. Hasta cinco imágenes de 256 px etiquetadas «Imagen 1…N».

### 8.5.4 Parámetros de inferencia

`temperature = 0.2`; tope de 384 tokens en el modo estratégico (nueve valores de enum) y 512 en el barrido. El tope no fija la longitud de la respuesta —con decodificación restringida, la generación termina al cerrar el esquema—: solo corta una generación desbocada, y una respuesta cortada se reporta como falla (`respuesta_truncada`), nunca se interpreta. Las respuestas no tienen campos de texto libre: no hay razonamiento que generar, lo que acota la latencia de decodificación.

Los system prompts están en el código (`vlm_strategic.py`, `deep_scan.py`).

## 8.6 Gestión de latencia

El tiempo de inferencia del VLM es un orden de magnitud mayor que el período del lazo (200 ms). La consulta corre en el hilo de `DeliberationService` (§5.10.5) y nunca bloquea al grafo. Esta separación entre una capa de ejecución rápida que siempre responde y una capa de razonamiento lento desacoplada es la instancia concreta, con un VLM como capa deliberativa, del patrón de arquitecturas de tres capas ([Gat, 1998](13-REFERENCIAS.md#ref-gat-1998)).

**Latencia observada.** Las fuentes disponibles no provienen de una medición controlada que aísle carga de GPU, tamaño de imagen y arranque en frío:

| Fuente | Condición | Latencia |
|---|---|---|
| Piloto `townsim_ini`, `slm`, semilla 99 (102 consultas) | Un fotograma, prompt textual de ~500 tokens | mediana 1.46 s · p95 3.73 s · máx 4.57 s |
| Corridas de diagnóstico `citysim_pilot` (73 consultas) | Un fotograma de 384 px, descripción por sectores | mediana 5.3 s · p95 12.9 s · máx 14.8 s |
| Ídem (36 consultas) | Barrido de 2 imágenes de 256 px | mediana 5.6 s · p95 11.6 s · máx 12.9 s |
| Ídem, total (185 consultas) | Todas las consultas de esas corridas | mediana 3.8 s · máx 18.1 s |

La diferencia entre el piloto y las corridas de diagnóstico no se ha atribuido con los datos disponibles (difieren el tamaño de imagen, el prompt y la carga del servidor). Lo que es firme es la consecuencia de diseño: ninguna de estas latencias cabe en el ciclo de 200 ms, y en el rango de 5 s el dron recorre ~10 m y puede girar más de 90°.

**Consecuencia para el comportamiento del dron.**

- **Capa estratégica.** El dron **no se frena**: el lazo rápido sigue volando y la respuesta, cuando llega, se traduce con la pose del fotograma (§5.10.3). Mantener el avance preserva además la traslación que el flujo óptico necesita.
- **Barrido de resolución de atasco.** El dron permanece en el lugar mientras espera, bajo el watchdog `SLM_DEEP_WATCHDOG_MS` (18 s en producción, por encima del p95 medido y por debajo del corte HTTP de 20 s). Al expirar, cae al escape vertical.

**Validez de las respuestas.** La validez se controla geométricamente, no solo por edad: la respuesta se descarta si tiene más de 10 s, si cambió el waypoint o si el dron ya superó la sub-meta que produciría; dentro de esos límites, girar mientras el modelo piensa no invalida la respuesta, porque está anclada al fotograma.

## 8.7 Nombres de campo compactos

A ~15 tokens/s de generación, cada token de la respuesta cuesta ~67 ms. El esquema panorámico usa nombres compactos (`img`, `ok`, `conf`, `degradada`) en lugar de nombres descriptivos (`relativo_deg`, `transitable`, `confianza`, `imagen_degradada_global`) y no exige un campo de razonamiento (`r`); con nombres compactos, una respuesta de cuatro rumbos baja de ~80–95 a ~40–55 tokens. El esquema estratégico lleva la idea al extremo: siete valores de enum o booleanos y ningún texto libre. El parser panorámico acepta ambos vocabularios y normaliza internamente a los nombres largos.

## 8.8 Nota: LoRA como alternativa explorada y no adoptada

El fine-tuning ligero vía LoRA (*Low-Rank Adaptation*) fue evaluado durante la etapa de planificación como posible vía de especialización del modelo para el espacio de maniobras de este sistema ([Anexo 3](anexos/A3-OPTIMIZACION-LORA.md)). El argumento a favor era que un conjunto de pares (prompt, acción correcta) derivados de las corridas exitosas del sistema podría reducir la frecuencia de respuestas subóptimas sin reentrenar el modelo base.

No se implementó en el pipeline final por dos razones:

1. **Cobertura de datos insuficiente.** El conjunto de corridas disponible en el momento de la evaluación (piloto de 3 tiers, cap. 11) contiene situaciones de evasión relativamente homogéneas. Un LoRA entrenado sobre ese conjunto podría sobreajustar a los escenarios vistos y degradar la generalización en configuraciones urbanas no ensayadas.

2. **Complejidad de mantenimiento.** Un adaptador LoRA es un artefacto de entrenamiento que requiere ser versionado, evaluado y actualizado junto con el modelo base. Para el alcance de esta tesis, el beneficio esperado no justificó el costo de infraestructura. Se deja constancia explícita de que es una alternativa explorada y no adoptada por decisión de alcance, no por omisión.
