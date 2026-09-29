# 8. Ingeniería de decisiones del SLM

El capítulo 5 documenta la *arquitectura interna* de la consulta asíncrona al VLM (cuándo se solicita, cómo se integra en el grafo LangGraph, qué hace el sistema con la respuesta del modelo). El capítulo 6 documenta *por qué* hace falta un VLM (los puntos ciegos estructurales del estimador de flujo). Este capítulo documenta las decisiones de ingeniería que hacen que ese VLM *funcione de forma confiable en la práctica*: selección del modelo bajo restricciones de hardware, mecanismos de salida estructurada, diseño del espacio de acción, ingeniería del prompt y trazabilidad de las decisiones.

## 8.1 Selección del modelo: restricciones de hardware como parámetro de diseño

La selección del modelo de lenguaje no fue un proceso de *benchmark* abstracto sino un proceso de diseño con restricciones duras. El sistema corre en una RTX 5060 con 8 GB de VRAM compartidos con una simulación de Unreal Engine 5.5. AirSim sobre UE5.5 consume, en condiciones de vuelo activo, entre 4.5 y 6 GB de VRAM ([Turco et al., 2024](13-REFERENCIAS.md#ref-turco-2024)). El presupuesto efectivo disponible para la inferencia del modelo es de **2 a 3.5 GB de VRAM**, incluyendo la KV cache del historial de prompt.

Esta restricción excluye inmediatamente a los modelos de referencia del estado del arte (GPT-4o, Claude 3.5, Gemini 1.5 — todos en la nube o con hardware dedicado de 24–80 GB) y orienta la búsqueda hacia modelos multimodales compactos cuantizados (*Small Vision-Language Models*, VLM), del orden de 3 a 7 mil millones de parámetros, ejecutados localmente bajo LM Studio o vLLM.

### 8.1.1 El requisito de visión directa

Una distinción de diseño previa a la selección del modelo es si la consulta al modelo debe usar un modelo textual puro (recibe solo telemetría y resúmenes de percepción serializados) o un VLM multimodal (recibe además el fotograma de la cámara). El sistema adopta un VLM multimodal por razones que no son de conveniencia sino de cobertura funcional:

- **Puntos ciegos del flujo óptico** (§6.1, §6.12): cuando el estimador de flujo carece de evidencia (hover, giro puro, baja textura), el `ObstacleField` entregado al modelo es esencialmente vacío. Un modelo textual no puede razonar sobre la escena sin ese resumen; un VLM puede observar directamente el fotograma y evaluar el contexto visual.
- **Semántica que el flujo no codifica**: la distinción entre "árbol vs. edificio", "sombra vs. obstáculo sólido", o "calle con objetos vs. calle vacía" no está presente en el campo de divergencia. El VLM puede discriminar escenas semánticamente similares en percepción pero distintas en consecuencias de navegación.
- **Historial temporal mínimo**: el campo `VLM_FRAME_HISTORY_SIZE = 2` envía los frames $t$ y $t-1$ juntos, permitiendo al modelo estimar la dirección de aproximación a partir de la diferencia visual entre frames, sin necesidad de que el flujo óptico sea confiable.

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

## 8.2 Salida estructurada: decodificación restringida y parser tolerante

La primera causa observada de fallo de la consulta al VLM no fue una decisión de navegación incorrecta, sino una respuesta JSON malformada que rompía el parser y dejaba al dron sin maniobra durante 3–5 ciclos. La solución adoptada opera en dos capas complementarias.

### 8.2.1 Decodificación restringida (`json_schema`)

La respuesta del modelo se solicita con el parámetro `response_format={"type": "json_schema", "json_schema": {...}}`, disponible en LM Studio (a partir de la versión con llama.cpp ≥ 0.5) y en el backend OpenAI-compatible de Ollama. La decodificación restringida opera durante la generación token a token: en cada paso, el motor de inferencia evalúa las reglas del esquema y enmascara los logits de tokens que resultarían en JSON inválido para el esquema declarado, forzando al modelo a muestrear únicamente de los tokens válidos. El mecanismo subyacente —reformular la gramática del esquema como una máquina de estados finitos y usarla para restringir, en cada paso de generación, el conjunto de tokens admisibles— es el que formalizan [Willard y Louf (2023)](13-REFERENCIAS.md#ref-willard-2023), cuya implementación de referencia (la biblioteca *Outlines*) es la base de la decodificación guiada que hoy exponen backends como llama.cpp; [Raspanti et al. (2025)](13-REFERENCIAS.md#ref-raspanti-2025) y [Geng et al. (2025)](13-REFERENCIAS.md#ref-geng-2025) evalúan empíricamente el impacto de esa misma técnica sobre la fiabilidad de la salida en tareas de análisis estructurado (el desarrollo formal, la formulación matemática de autómatas, los mecanismos de aceleración y la optimización del grafo de control se detallan exhaustivamente en el [Anexo 4](anexos/A4-DECODIFICACION-RESTRINGIDA.md)).

El efecto práctico es que, cuando la decodificación restringida está activa, es estructuralmente imposible producir una respuesta que no sea JSON conforme al esquema. El `adherence_rate` (fracción de respuestas parseables al primer intento) medido en los escenarios de validación sube de ~73% (solo prompt) a ~98% (con `json_schema`).

El esquema declarado (`RESPONSE_JSON_SCHEMA`, `deliberative.py`) tiene la forma mínima necesaria para la toma de decisión, más un grupo de campos opcionales de sub-meta (§8.3):

```json
{
  "type": "object",
  "properties": {
    "macro_action": { "type": "string", "enum": ["EVADIR_DERECHA", "EVADIR_IZQUIERDA", "FRENAR",
                                                "GANAR_ALTURA", "MANTENER_RUMBO", "PERDER_ALTURA"] },
    "rationale":    { "type": "string" },
    "dx_m": { "type": "number" }, "dy_m": { "type": "number" }, "dz_m": { "type": "number" },
    "confidence": { "type": "number" }, "semantic_label": { "type": "string" },
    "mode": { "type": "string", "enum": ["navegar", "inspeccionar", "buscar", "esperar"] }
  },
  "required": ["macro_action", "rationale"],
  "additionalProperties": false
}
```

La enumeración explícita de los valores posibles de `macro_action` (§8.3) es el mecanismo que convierte el espacio de acción discreto del sistema en una restricción gramatical directamente aplicable por el motor de gramática.

### 8.2.2 Parser tolerante como red de seguridad

La garantía de `json_schema` depende de que el backend local soporte la versión de llama.cpp que implementa esa funcionalidad. En entornos de despliegue heterogéneos (versión de LM Studio distinta, Ollama sin la extensión, o futura migración a otro backend), esa garantía puede no cumplirse. Por eso, `_parse_decision()` (`src/agents/deliberative.py`) se conserva como red de seguridad y aplica tres estrategias de extracción en orden creciente de tolerancia:

1. **`json.loads()` directo**: para respuestas bien formadas sin envoltura.
2. **Extracción de bloque JSON con regex**: detecta el bloque `{...}` más externo en una respuesta que incluye markdown, texto explicativo o prefijos conversacionales.
3. **Búsqueda de campo `macro_action` por expresión regular** (y, en última instancia, búsqueda de cualquier acción válida como subcadena del texto): extrae el valor sin necesidad de parsear el JSON completo, como último recurso cuando la respuesta está truncada o mal formada.

Si las estrategias fallan, `_fallback_decision()` entra en vigor: un árbol de decisión determinista sobre el `ObstacleField` (§5.10) —`FRENAR` sin evidencia de percepción, `GANAR_ALTURA` con los tres sectores bloqueados, evasión hacia el lado libre, `MANTENER_RUMBO` con el centro libre— con una nota de error auditable en el log. Desde 2026-09-22 el fallback por *timeout* del watchdog pasa además por los overrides deterministas de trayectoria (§5.12.2), para que no repita una acción que la historia de vuelo ya refutó.

La métrica `adherence_rate` es una fila explícita de la tabla de resultados (cap. 11): cuantifica cuánto aporta, en la práctica, la decodificación restringida por sobre el parser tolerante como única defensa. Este número importa porque si fuera cercano al 100% solo con el parser, la decodificación restringida sería overhead sin beneficio; si la diferencia es grande (como documentan Raspanti et al. [2025] y Geng et al. [2025] para SLMs compactos), la restricción es una decisión de ingeniería con impacto medible en la fiabilidad del sistema.

## 8.3 Espacio de acción discreto: lista blanca de macro-acciones

El VLM no produce comandos cinemáticos directamente (velocidades en m/s, tasas de guiñada en rad/s). Elige una etiqueta de un conjunto fijo de macro-acciones definido en `PROMPT_ACTIONS` (`deliberative.py`):

| Macro-acción | Significado navegacional |
|---|---|
| `MANTENER_RUMBO` | Continuar hacia el waypoint activo sin alterar la velocidad ni el rumbo |
| `EVADIR_IZQUIERDA` | Iniciar evasión lateral hacia la izquierda (yaw −15°/s, vx = 0.3–1.2 m/s) |
| `EVADIR_DERECHA` | Iniciar evasión lateral hacia la derecha (yaw +15°/s, vx = 0.3–1.2 m/s) |
| `GANAR_ALTURA` | Ascender en el lugar (vz = −1.5 m/s, vx = 0) para sobrevolar el obstáculo |
| `PERDER_ALTURA` | Descender con avance lento (vz = +0.8 m/s, vx = 1.0 m/s) |
| `FRENAR` | Detener el drone en el lugar (hover) con corrección de altitud por controlador P |
| `RETROCEDER` | Marcha atrás con rumbo congelado (vx = −1.2 m/s) durante ~5 s (≈ 6 m) para salir de la malla de colisión de un obstáculo (§5.12.3) |

El vocabulario completo del sistema tiene **ocho** acciones (`VALID_ACTIONS` en `action_map.py`), pero no todas son elegibles por el VLM en todos los caminos:

- `GIRAR_90` **no está en ningún `PROMPT_ACTIONS`**: es un bypass determinista que la capa reactiva de `navigate` activa directamente cuando `blocked_fraction > 0.6`, sin consultar al VLM. Si el modelo lo intentara, el parser lo descartaría.
- `RETROCEDER` está en el `PROMPT_ACTIONS` del escaneo de resolución de atasco (`slam_assess` / `deep_vlm`) y en los overrides deterministas (§5.12.2), pero **no** en el de la consulta táctica ordinaria (seis acciones): su enum de decodificación restringida no la admite y `_parse_decision()` la descartaría. Los archivos de system prompt (§8.5) sí la listan entre los valores permitidos; es una inconsistencia conocida entre prompt y esquema, sin efecto observado porque la consulta táctica nunca puede producirla, y que debe resolverse alineando ambos.

El schema JSON declarado para la decodificación restringida tiene la forma:

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "macro_decision",
    "schema": {
      "type": "object",
      "properties": {
        "macro_action": {
          "type": "string",
          "enum": ["EVADIR_DERECHA", "EVADIR_IZQUIERDA", "FRENAR",
                   "GANAR_ALTURA", "MANTENER_RUMBO", "PERDER_ALTURA"]
        },
        "rationale": {"type": "string"},
        "dx_m": {"type": "number"}, "dy_m": {"type": "number"}, "dz_m": {"type": "number"},
        "confidence": {"type": "number"}, "semantic_label": {"type": "string"},
        "mode": {"type": "string", "enum": ["navegar", "inspeccionar", "buscar", "esperar"]}
      },
      "required": ["macro_action", "rationale"],
      "additionalProperties": false
    }
  }
}
```

**Poda del enum por motivo de consulta.** En lugar de enviar siempre el enum completo, `_schema_for_reason(reason_key)` genera un schema podado según el contexto:
- `"TTC_CRITICO"`: excluye `MANTENER_RUMBO` (hay colisión inminente confirmada).
- `"DEADLOCK_ESCAPE"`: excluye `MANTENER_RUMBO` y `FRENAR` (el drone ya está atascado; detenerse o insistir al frente es contraproducente).

Esta poda semántica concentra la distribución de muestreo del modelo en las acciones físicamente coherentes con la causa de la consulta, sin requerir fine-tuning. Su efecto sobre la tasa de respuestas subóptimas no se ha medido de forma aislada.

**Sub-meta semántica (`VlmGoal`).** Los campos opcionales `dx_m`, `dy_m`, `dz_m`, `confidence`, `semantic_label` y `mode` permiten que el VLM, además de la etiqueta de macro-acción, proponga un punto de destino próximo en el marco del cuerpo (adelante, derecha, abajo NED). El sistema solo lo adopta si `confidence >= 0.7` y lo convierte en un waypoint de desvío en coordenadas de mundo (`inject_corner`, §5.10). La macro-acción sigue siendo la decisión de seguridad; la sub-meta solo orienta *hacia dónde*.

Esta arquitectura de lista blanca tiene tres propiedades de diseño que se derivan mutuamente:

**1. Compatibilidad directa con la decodificación restringida.** Un espacio de acción finito y conocido a priori puede representarse como una enumeración JSON (`enum`), lo que hace posible convertir la restricción de salida en una gramática aplicable en tiempo de inferencia. Un espacio continuo de comandos cinemáticos no puede representarse así sin esquemas mucho más complejos.

**2. Comparación limpia entre brazos.** El VLM, la FSM y el brazo reactivo comparten el mismo espacio de macro-acciones y el mismo traductor a comandos `action_to_command()`. La única variable que difiere entre ellos es *quién elige la etiqueta*, no *qué puede elegir ni cómo se ejecuta*. Esto hace posible la comparación experimental de los tres brazos (cap. 10) sin confundir diferencias de política con diferencias de actuación.

**3. Auditabilidad.** Una secuencia de etiquetas de macro-acción es legible por humanos y directamente graféable (cap. 4, viewer). Un log de vectores cinemáticos continuos no tiene esa propiedad sin postprocesamiento.

La lista de macro-acciones es fija en el diseño actual y no extensible dinámicamente: agregar una nueva macro-acción requiere modificar el esquema JSON, el `action_to_command()`, los prompts y la FSM. Este acoplamiento es deliberado — es el mecanismo que impide que el modelo de lenguaje invente acciones fuera del espacio de maniobras seguras.

## 8.4 `action_to_command`: la frontera entre lenguaje y cinemática

Cada macro-acción se traduce a un comando cinemático concreto a través de `action_to_command()` (`src/agents/action_map.py`), función compartida de forma estricta por el VLM, la evasión, la capa táctica y la FSM. La traducción completa es:

| Macro-acción | vx (frontal) | vy (lateral) | vz (vertical) | yaw_rate |
|---|---|---|---|---|
| `MANTENER_RUMBO` | `FORWARD_SPEED` | 0 | 0 | toward wp |
| `EVADIR_IZQUIERDA` | `EVASION_FORWARD` | `-EVASION_LATERAL` | 0 | `EVASION_LATERAL_YAW_RATE` |
| `EVADIR_DERECHA` | `EVASION_FORWARD` | `+EVASION_LATERAL` | 0 | `-EVASION_LATERAL_YAW_RATE` |
| `GANAR_ALTURA` | 0 | 0 | `-EVASION_UP_SPEED` | 0 |
| `PERDER_ALTURA` | 0 | 0 | `+EVASION_DOWN_SPEED` | 0 |
| `FRENAR` | 0 | 0 | (P-ctrl. alt.) | 0 |
| `GIRAR_90` | (manejado por `_dispatch_girar_90`) | — | — | — |
| `RETROCEDER` | `-EVASION_BACK_SPEED` | 0 | según guiado | 0 (rumbo congelado) |

Los valores constantes son variables de entorno: `EVASION_LATERAL_YAW_RATE = 15.0` °/s, `EVASION_UP_SPEED = 1.5` m/s, `EVASION_DOWN_SPEED = 0.8` m/s, `EVASION_BACK_SPEED = 1.2` m/s, `CORNER_OFFSET_M = 12.0` m (15.0 m en la configuración de producción).

**Invariante de diseño.** Centralizar la traducción en una sola función garantiza que ninguna macro-acción puede tener definiciones cinemáticas distintas según quién la active (VLM, FSM, escape o capa táctica). Si cada brazo tuviera su propia tabla de velocidades, divergirían sutilmente (por ejemplo, distinta velocidad vertical para `GANAR_ALTURA`) y producirían trayectorias asimétricas entre brazos que confundirían la comparación A/B. La función centralizada elimina esa clase de divergencia estructuralmente.

## 8.5 Ingeniería del prompt: componentes

El prompt de usuario construido por `_build_user_prompt()` tiene los siguientes componentes estructurados, cada uno respondiendo a una pregunta específica que el VLM necesita para decidir:

**Componente 1 — Estado de vuelo y telemetría.** Velocidad horizontal, velocidad vertical, altitud, actitud (pitch, roll), estado de misión, waypoint activo y distancia restante. Este componente traduce telemetría numérica cruda a descripciones en lenguaje natural ("el dron vuela a 4.2 m/s, con 23 m al próximo waypoint, pitch -3.1°"). La verbalización explícita se prefiere a la telemetría cruda por dos razones convergentes: los SLMs de 3B parámetros razonan más confiablemente sobre descripciones en lenguaje natural que sobre tuplas de números ([Zhu et al., 2024](13-REFERENCIAS.md#ref-zhu-2024)), y la práctica de convertir retroalimentación de sensores y de entorno a lenguaje natural antes de dársela a un modelo de lenguaje para planificación robótica está empíricamente validada en el patrón de "monólogo interno": [Huang et al. (2022)](13-REFERENCIAS.md#ref-huang-2022) muestran que un LLM que recibe la retroalimentación del entorno verbalizada explícitamente —en lugar de como estado estructurado— mejora significativamente la tasa de éxito en la ejecución de instrucciones de alto nivel en múltiples dominios robóticos.

**Componente 2 — Resumen del `ObstacleField` enriquecido.** El resultado de `ObstacleField.summary_text()` para cada sector activo: TTC, ocupación, confianza, estado de bloqueo y **fuente** del campo (`"flujo óptico"`, `"flujo óptico + profundidad monocular (Depth Anything V2)"`, etc.). Cuando el campo tiene evidencia, este componente provee información cuantitativa sobre la geometría del obstáculo. Cuando no la tiene, el componente dice explícitamente "percepción SIN evidencia".

`scene_summary` puede además incluir avisos adicionales generados por `perception_node`:
- **E2**: `"Obstáculo frontal (profundidad monocular): follaje. Posibles huecos entre ramas — evasión diagonal o +1 m de altura puede ser viable."` (cuando Depth Anything V2 clasifica el obstáculo como vegetación).
- **G1**: `"AVISO [G1]: stall frontal 33% (30 intentos) con campo óptico despejado — posible obstáculo invisible (muro liso, baja textura). MANTENER_RUMBO agravará el bloqueo. Priorizar GIRAR_90 o evasión lateral amplia."` (cuando el historial acumulado contradice la ausencia de bloqueo óptico).

Estos avisos llegan al VLM en todos los pedidos (táctico, `slam_assess`, `deep_vlm`), permitiéndole ajustar la decisión a la naturaleza específica del obstáculo invisible.

**Componente 3 — Avisos de contexto.** Cuando corresponde, se agregan tres avisos que le dan al modelo la evidencia de bloqueo que el flujo óptico no ve: los ciclos sin progreso hacia el waypoint (a partir de 5, con la indicación de preferir `GANAR_ALTURA` si los tres sectores están bloqueados), la tasa de stall frontal de la trayectoria reciente (a partir de 50 % con 5 o más intentos) y el nivel de vibración del IMU cuando no es normal. Estos avisos son la forma en que la memoria de trayectoria y la inferencia inercial (cap. 5) llegan al modelo como texto.

**Componente 4 — Motivo explícito de consulta.** La nota `_query_reason_note` distingue tres situaciones: `"el sector CENTRO muestra un obstáculo real (TTC = …)"`; `"baja confianza de los sensores de flujo"` (sin evidencia: vegetación densa, baja velocidad o movimiento caótico, lo que no implica necesariamente un obstáculo) y `"bloqueo lateral o corredor cerrado, sin peligro central inmediato"`. En el caso de baja confianza y con imagen adjunta, le indica al modelo que use **la imagen como fuente primaria**, sin sobre-indexar en los sectores «sin evidencia». Es crítico para calibrar la respuesta: con baja confianza, el VLM no debe reportar obstáculos que no ve; con obstáculo central real, debe priorizar la evasión inmediata.

El constructor admite además, como componentes opcionales, un historial de las últimas decisiones con su resultado medido (variación de distancia al waypoint y de TTC mínimo) y las sub-metas semánticas previas; el pedido táctico del lazo no los incluye, de modo que el modelo razona sobre la escena y el estado actuales sin arrastrar decisiones anteriores.

**Componente 5 — Instrucción de formato de salida.** Reiteración explícita del esquema JSON esperado y de los valores posibles del campo `action`, coherente con el `json_schema` declarado en el parámetro de formato. Esta redundancia entre prompt y schema es intencional: para modelos pequeños, la instrucción textual explícita mejora el `adherence_rate` incluso cuando la decodificación restringida está activa, especialmente en la elección del campo `action` dentro del dominio de la enumeración ([Geng et al., 2025](13-REFERENCIAS.md#ref-geng-2025)).

**Prompts de sistema externalizados.** Los system prompts no están fijos en el código: `SYSTEM_PROMPT_VISION_FILE` y `SYSTEM_PROMPT_TEXT_FILE` (`config/prompts/system_vision.txt`, `system_text.txt`) permiten editarlos sin tocar Python; el archivo admite el placeholder `{safe_margin_ttc_s}`, sustituido al cargar, y si no existe se usa el prompt interno como fallback. Ambos comparten la misma jerarquía de reglas, en orden de prioridad: (1) `MANTENER_RUMBO` solo con trayectoria libre hacia el waypoint; (2) evasión lateral si el sector lateral está despejado; (3) `GANAR_ALTURA` solo con bloqueo total por estructuras sólidas, `PERDER_ALTURA` si el obstáculo es vegetación con espacio debajo, `RETROCEDER` si el dron está pegado al obstáculo o las maniobras previas no avanzaron; (4) `FRENAR` ante peligro crítico en todas las direcciones. La variante con visión añade la regla «imagen frente a sensores» —la imagen es la fuente primaria cuando el prompt indica baja confianza— y la solicitud de sub-meta opcional con offsets de escala real (6–20 m). La regla estricta común prohíbe `MANTENER_RUMBO` si el sector central está bloqueado con TTC menor que `SAFE_MARGIN_TTC_S`, y declara `GANAR_ALTURA` como último recurso: un corredor lateral, aunque estrecho, es preferible a subir.

**Imagen adjunta.** Los pedidos tácticos y los del escaneo de resolución de atasco adjuntan fotogramas: los tácticos, los del `frame_history` (por defecto los instantes `t` y `t−1`); el escaneo `slam_assess`, el fotograma frontal del ciclo; el barrido `deep_vlm`, un fotograma por rumbo etiquetado con su orientación. Las imágenes se codifican como JPEG base64 redimensionado a 384 px de lado mayor. El registro de auditoría de cada deliberación indica en `vision_enabled` si la consulta usó imagen.

**Parámetros de inferencia.** `temperature = 0.2` (baja entropía, respuestas reproducibles y conservadoras), `max_tokens = 200` (suficiente para la estructura JSON más una razón breve; limita la longitud de generación y, con ella, la latencia y la presión sobre la KV cache).

## 8.6 Gestión de latencia: consulta asíncrona y watchdog

El tiempo de inferencia del VLM es un orden de magnitud mayor que el período del lazo de control (200 ms a 5 Hz). Esto hace imposible bloquear el lazo esperando la respuesta; la consulta opera de forma asincrónica a través de `DeliberationService` (§5.10), que corre en un daemon thread independiente. Esta separación entre una capa de ejecución rápida que nunca deja de responder y una capa de razonamiento lenta que se consulta de forma desacoplada no es una solución ad hoc de este sistema: es la instancia concreta, con un VLM en el rol deliberativo, del patrón de arquitecturas de tres capas (reactiva / secuenciamiento / deliberativa) documentado como solución general al problema de integrar planificación lenta con control robótico en tiempo real ([Gat, 1998](13-REFERENCIAS.md#ref-gat-1998)). En la implementación, las capas 1 y 2 de `navigate` cumplen los roles reactivo y de secuenciamiento —incluida la decisión de cuándo una respuesta del VLM es aún aplicable— y la capa 3 es la deliberativa (§5.3).

**Latencia observada.** La latencia del VLM no es un número único; depende de si la consulta lleva imagen, de la carga de la GPU compartida con Unreal Engine y del arranque en frío del modelo. Las fuentes disponibles, que no provienen de una medición controlada que aísle esos factores, son:

| Fuente | Condición | Latencia |
|---|---|---|
| Diseño del sistema | Prompt de ~500 tokens, `max_tokens = 200` | ≈ 0.85–1.4 s |
| Calibración de régimen de vuelo (comentario de `config/.env`) | Régimen de vuelo; arranque en frío | 2–3.5 s; ~8 s en frío |
| Piloto `townsim_ini`, `slm`, semilla 99 (traza JSONL, 102 invocaciones) | Configuración de producción | mediana 1.46 s · p95 3.73 s · máx 4.57 s · mín 1.24 s; 0 *fallbacks*, 0 *timeouts* |
| Depuración (comentario de `config/.env`) | Consulta con imagen base64 | ≈ 10–11 s |
| Ídem | Consulta de texto puro | ≈ 0.6 s |

La discrepancia entre las dos últimas filas y el piloto no se ha resuelto con los datos disponibles: el sistema registra `latency_ms` por invocación en cada corrida, lo que permitirá caracterizar la distribución real por condición en el capítulo 11. Lo que sí es firme es la consecuencia de diseño: ninguna de estas latencias cabe en el ciclo de 200 ms.

**Consecuencia para el comportamiento del dron.** Depende del tipo de consulta:

- **Pedido proactivo o táctico.** El dron **no se frena**: las capas 1 y 2 siguen gobernando el vuelo con la guía nominal al waypoint y sus reglas de TTC y de atasco, y el resultado, cuando llega, queda en `_vlm_intention` con su marca temporal. Mantener el avance preserva la traslación que el estimador de flujo óptico necesita para generar evidencia perceptual: si el dron frenara mientras el VLM procesa, el campo de flujo colapsaría justo cuando el sistema lo necesita (frenar → sin flujo → sin confianza → nueva consulta → frenar).
- **Escaneo de resolución de atasco (`slam_assess` / `deep_vlm`).** El dron permanece en hover mientras espera, con un watchdog de `SLM_DEEP_WATCHDOG_MS = 12 000 ms` que garantiza que la falta de respuesta nunca lo deje inmóvil más allá de ese plazo. Al expirar, o si la respuesta no es una acción válida, la capa táctica resuelve con la historia de zonas.

**Caducidad de las respuestas.** El compromiso de una latencia larga es la **frescura**: una respuesta de 10 s se refiere a una escena que, a la velocidad de crucero, quedó varios metros atrás. Por eso `_vlm_intention` caduca (5 s en la reacción por TTC, 10 s en la resolución de atasco) y toda decisión guardada se contrasta con los overrides de trayectoria antes de despacharse (§5.12.2). Para las consultas que llevan imagen y pueden tardar ~10 s, el watchdog del escaneo se fija por encima de esa latencia y por debajo del corte HTTP del cliente (`SLM_HTTP_TIMEOUT_S = 15 s`; `SLM_DEEP_HTTP_TIMEOUT_S = 20 s`), de modo que gane siempre el watchdog. Esto refuerza la elección del modelo de 3B: una respuesta de calidad media entregada rápido vale más en este sistema que una respuesta de calidad alta entregada tarde.

## 8.7 Nota: LoRA como alternativa explorada y no adoptada

El fine-tuning ligero vía LoRA (*Low-Rank Adaptation*) fue evaluado durante la etapa de planificación como posible vía de especialización del modelo para el espacio de maniobras de este sistema ([Anexo 3](anexos/A3-OPTIMIZACION-LORA.md)). El argumento a favor era que un conjunto de pares (prompt, acción correcta) derivados de las corridas exitosas del sistema podría reducir la frecuencia de respuestas subóptimas sin reentrenar el modelo base.

No se implementó en el pipeline final por dos razones:

1. **Cobertura de datos insuficiente.** El conjunto de corridas disponible en el momento de la evaluación (piloto de 3 tiers, cap. 11) contiene situaciones de evasión relativamente homogéneas. Un LoRA entrenado sobre ese conjunto podría sobreajustar a los escenarios vistos y degradar la generalización en configuraciones urbanas no ensayadas.

2. **Complejidad de mantenimiento.** Un adaptador LoRA es un artefacto de entrenamiento que requiere ser versionado, evaluado y actualizado junto con el modelo base. Para el alcance de esta tesis, el beneficio esperado no justificó el costo de infraestructura. Se deja constancia explícita de que es una alternativa explorada y no adoptada por decisión de alcance, no por omisión.
