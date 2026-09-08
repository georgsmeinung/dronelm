# 8. Ingeniería de decisiones del SLM

El capítulo 5 documenta la *arquitectura interna* del nodo deliberativo (cuándo se activa, cómo se integra en el grafo LangGraph, qué hace con la respuesta del modelo). El capítulo 6 documenta *por qué* hace falta un VLM (los puntos ciegos estructurales del estimador de flujo). Este capítulo documenta las decisiones de ingeniería que hacen que ese VLM *funcione de forma confiable en la práctica*: selección del modelo bajo restricciones de hardware, mecanismos de salida estructurada, diseño del espacio de acción, ingeniería del prompt y trazabilidad de las decisiones.

## 8.1 Selección del modelo: restricciones de hardware como parámetro de diseño

La selección del modelo de lenguaje no fue un proceso de *benchmark* abstracto sino un proceso de diseño con restricciones duras. El sistema corre en una RTX 5060 con 8 GB de VRAM compartidos con una simulación de Unreal Engine 5.5. AirSim sobre UE5.5 consume, en condiciones de vuelo activo, entre 4.5 y 6 GB de VRAM (Turco et al., 2024). El presupuesto efectivo disponible para la inferencia del modelo es de **2 a 3.5 GB de VRAM**, incluyendo la KV cache del historial de prompt.

Esta restricción excluye inmediatamente a los modelos de referencia del estado del arte (GPT-4o, Claude 3.5, Gemini 1.5 — todos en la nube o con hardware dedicado de 24–80 GB) y orienta la búsqueda hacia modelos multimodales compactos cuantizados (*Small Vision-Language Models*, VLM), del orden de 3 a 7 mil millones de parámetros, ejecutados localmente bajo LM Studio o vLLM.

### 8.1.1 El requisito de visión directa

Una distinción de diseño previa a la selección del modelo es si el nodo deliberativo debe usar un modelo textual puro (recibe solo telemetría y resúmenes de percepción serializados) o un VLM multimodal (recibe además el fotograma de la cámara). El sistema adopta un VLM multimodal por razones que no son de conveniencia sino de cobertura funcional:

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

El criterio de selección fue: **(a)** soporte de visión nativa, **(b)** VRAM < 2.5 GB con Q4_K_M, **(c)** soporte de `response_format: json_schema` en el backend de inferencia, **(d)** latencia de inferencia < 2 s en el hardware disponible para prompts de ~500 tokens con dos imágenes.

### 8.1.3 Posicionamiento respecto al estado del arte

La arquitectura de lazo cerrado estado→VLM→macro-acción→ejecución no es, hacia 2025–2026, una contribución conceptualmente novedosa: es un patrón estandarizado en investigación y prototipos de UAVs controlados por modelos de lenguaje (véase la discusión en `informe/anexos/A1-EXPLORACION-SLM-GGUF.md`). Hwang et al. (2024) en EMMA y Saxena et al. (2025) en UAV-VLN son trabajos representativos del patrón. El aporte de esta tesis no está en la novedad de la arquitectura general, sino en la ingeniería de su interfaz con la percepción monocular (cap. 6) y en la caracterización sistemática de sus modos de falla (cap. 9).

## 8.2 Salida estructurada: decodificación restringida y parser tolerante

La primera causa documentada de fallo del nodo deliberativo en versiones tempranas del sistema no fue una decisión de navegación incorrecta, sino una respuesta JSON malformada que rompía el parser y dejaba al dron sin maniobra durante 3–5 ciclos. La solución adoptada opera en dos capas complementarias.

### 8.2.1 Decodificación restringida (`json_schema`)

La respuesta del modelo se solicita con el parámetro `response_format={"type": "json_schema", "json_schema": {...}}`, disponible en LM Studio (a partir de la versión con llama.cpp ≥ 0.5) y en el backend OpenAI-compatible de Ollama. La decodificación restringida opera durante la generación token a token: en cada paso, el motor de inferencia evalúa las reglas del esquema y enmascara los logits de tokens que resultarían en JSON inválido para el esquema declarado, forzando al modelo a muestrear únicamente de los tokens válidos (Raspanti et al., 2025; Geng et al., 2025).

El efecto práctico es que, cuando la decodificación restringida está activa, es estructuralmente imposible producir una respuesta que no sea JSON conforme al esquema. El `adherence_rate` (fracción de respuestas parseables al primer intento) medido en los escenarios de validación sube de ~73% (solo prompt) a ~98% (con `json_schema`).

El esquema declarado tiene la forma mínima necesaria para la toma de decisión:

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["keep_going", "evasive", "girar_90", "fsm", "degraded"]
    },
    "reason": { "type": "string", "maxLength": 120 }
  },
  "required": ["action", "reason"],
  "additionalProperties": false
}
```

La enumeración explícita de los valores posibles de `action` (§8.3) es el mecanismo que convierte el espacio de acción discreto del sistema en una restricción gramatical directamente aplicable por el motor de gramática.

### 8.2.2 Parser tolerante como red de seguridad

La garantía de `json_schema` depende de que el backend local soporte la versión de llama.cpp que implementa esa funcionalidad. En entornos de despliegue heterogéneos (versión de LM Studio distinta, Ollama sin la extensión, o futura migración a otro backend), esa garantía puede no cumplirse. Por eso, `_parse_decision()` (`src/agents/deliberative.py`) se conserva como red de seguridad y aplica tres estrategias de extracción en orden creciente de tolerancia:

1. **`json.loads()` directo**: para respuestas bien formadas sin envoltura.
2. **Extracción de bloque JSON con regex**: detecta el bloque `{...}` más externo en una respuesta que incluye markdown, texto explicativo o prefijos conversacionales.
3. **Búsqueda de campo `action` por expresión regular**: extrae el valor del campo `action` sin necesidad de parsear el JSON completo, como último recurso cuando la respuesta está truncada o mal formada.

Si las tres estrategias fallan, `_fallback_decision()` entra en vigor: devuelve `keep_going` con una nota de error, lo que es conservador (continuar la maniobra actual) y auditable (la nota aparece en el log).

La métrica `adherence_rate` es una fila explícita de la tabla de resultados (cap. 11): cuantifica cuánto aporta, en la práctica, la decodificación restringida por sobre el parser tolerante como única defensa. Este número importa porque si fuera cercano al 100% solo con el parser, la decodificación restringida sería overhead sin beneficio; si la diferencia es grande (como documentan Raspanti et al. [2025] y Geng et al. [2025] para SLMs compactos), la restricción es una decisión de ingeniería con impacto medible en la fiabilidad del sistema.

## 8.3 Espacio de acción discreto: lista blanca de macro-acciones

El VLM no produce comandos cinemáticos directamente (velocidades en m/s, tasas de guiñada en rad/s). Elige una etiqueta de un conjunto fijo de macro-acciones:

| Macro-acción | Significado navegacional |
|---|---|
| `keep_going` | Continuar hacia el waypoint activo sin alterar la velocidad ni el rumbo |
| `evasive` | Iniciar evasión lateral (dirección decidida por `evasive_node` según ocupación L/R) |
| `girar_90` | Ejecutar un giro de 90° en la dirección menos bloqueada para desatasco |
| `fsm` | Delegar la decisión a la máquina de estados FSM (brazo alternativo) |
| `degraded` | Declarar modo degradado; pasar a `degraded_hover_node` |

Esta arquitectura de lista blanca tiene tres propiedades de diseño que se derivan mutuamente:

**1. Compatibilidad directa con la decodificación restringida.** Un espacio de acción finito y conocido a priori puede representarse como una enumeración JSON (`enum`), lo que hace posible convertir la restricción de salida en una gramática aplicable en tiempo de inferencia. Un espacio continuo de comandos cinemáticos no puede representarse así sin esquemas mucho más complejos.

**2. Comparación limpia entre brazos.** El nodo deliberativo (VLM), el nodo FSM y el nodo reactivo comparten el mismo espacio de macro-acciones y el mismo traductor a comandos `action_to_command()`. La única variable que difiere entre ellos es *quién elige la etiqueta*, no *qué puede elegir ni cómo se ejecuta*. Esto hace posible la comparación experimental de los tres brazos (cap. 10) sin confundir diferencias de política con diferencias de actuación.

**3. Auditabilidad.** Una secuencia de etiquetas de macro-acción es legible por humanos y directamente graféable (cap. 4, viewer). Un log de vectores cinemáticos continuos no tiene esa propiedad sin postprocesamiento.

La lista de macro-acciones es fija en el diseño actual y no extensible dinámicamente: agregar una nueva macro-acción requiere modificar el esquema JSON, el `action_to_command()`, los prompts y la FSM. Este acoplamiento es deliberado — es el mecanismo que impide que el modelo de lenguaje invente acciones fuera del espacio de maniobras seguras.

## 8.4 `action_to_command`: la frontera entre lenguaje y cinemática

Cada macro-acción se traduce a un comando cinemático concreto a través de `action_to_command()` (`src/agents/action_map.py`), función compartida de forma estricta por los nodos deliberativo, de evasión y de FSM. La traducción completa es:

| Macro-acción | vx (frontal) | vy (lateral) | vz (vertical) | yaw_rate |
|---|---|---|---|---|
| `MANTENER_RUMBO` | `FORWARD_SPEED` | 0 | 0 | toward wp |
| `EVADIR_IZQUIERDA` | `EVASION_FORWARD` | `-EVASION_LATERAL` | 0 | `EVASION_LATERAL_YAW_RATE` |
| `EVADIR_DERECHA` | `EVASION_FORWARD` | `+EVASION_LATERAL` | 0 | `-EVASION_LATERAL_YAW_RATE` |
| `GANAR_ALTURA` | 0 | 0 | `-EVASION_UP_SPEED` | 0 |
| `PERDER_ALTURA` | 0 | 0 | `+EVASION_DOWN_SPEED` | 0 |
| `FRENAR` | 0 | 0 | (P-ctrl. alt.) | 0 |
| `GIRAR_90` | (manejado por `girar_90_node`) | — | — | — |

Los valores constantes son variables de entorno: `EVASION_LATERAL_YAW_RATE = 15.0` °/s, `EVASION_UP_SPEED = 1.5` m/s, `EVASION_DOWN_SPEED = 0.8` m/s, `CORNER_OFFSET_M = 12.0` m.

**Invariante de diseño.** Centralizar la traducción en una sola función garantiza que ninguna macro-acción puede tener definiciones cinemáticas distintas según quién la active. Antes de que `action_to_command()` fuera la única fuente de verdad, el nodo FSM y el nodo deliberativo tenían sus propias tablas de velocidades, que diveraron sutilmente (el FSM usaba `vx = 1.5 m/s` para `GANAR_ALTURA`, el deliberativo usaba `1.0 m/s`). Esa asimetría provocó trayectorias asimétricas entre brazos durante las pruebas A/B que dificultaron la comparación (CHANGELOG.md 2026-0824). La función centralizada elimina esa clase de divergencia estructuralmente.

## 8.5 Ingeniería del prompt: cinco componentes

El prompt de usuario construido por `_build_user_prompt()` tiene cinco componentes estructurados, cada uno respondiendo a una pregunta específica que el VLM necesita para decidir:

**Componente 1 — Estado de vuelo y telemetría.** Velocidad horizontal, velocidad vertical, altitud, actitud (pitch, roll), estado de misión, waypoint activo y distancia restante. Este componente traduce telemetría numérica cruda a descripciones en lenguaje natural ("el dron vuela a 4.2 m/s, con 23 m al próximo waypoint, pitch -3.1°"). La verbalización explícita se prefiere a la telemetría cruda porque los SLMs de 3B parámetros razonan más confiablemente sobre descripciones en lenguaje natural que sobre tuplas de números (Zhu et al., 2024).

**Componente 2 — Resumen del `ObstacleField`.** El resultado de `ObstacleField.summary_text()` para cada sector activo: TTC, ocupación, confianza, estado de bloqueo. Cuando el campo tiene evidencia, este componente provee información cuantitativa sobre la geometría del obstáculo. Cuando no la tiene, el componente dice explícitamente "percepción SIN evidencia" y describe la causa probable (velocidad baja, rotación activa), lo que permite al VLM distinguir "no hay obstáculo" de "no sé si hay obstáculo".

**Componente 3 — Historial de decisiones recientes.** Las últimas `N` acciones tomadas (con sus razones, si el deliberativo las reportó), incluyendo cuántos ciclos lleva activa la maniobra actual y si hay señales de atasco (progreso hacia el waypoint < umbral durante varios ciclos). Este componente provee contexto temporal que una sola imagen no puede dar: el VLM puede distinguir "empecé a evadir hace 1 ciclo" de "llevo 8 ciclos evasión sin avanzar".

**Componente 4 — Motivo explícito de consulta.** El campo `reason_note` codifica *por qué* el nodo deliberativo fue activado en este ciclo: `"TTC_CRITICO"` (TTC < umbral de evasión), `"TTC_ADVERTENCIA"` (zona de histéresis), `"FALTA_EVIDENCIA"` (flujo colapsado), `"DEADLOCK_ESCAPE"` (atasco detectado), `"DEEP_SCAN_RESULT"` (resultado de exploración rotacional). Este campo es crítico para calibrar la respuesta: ante `"FALTA_EVIDENCIA"`, el VLM no debe reportar obstáculos que no ve; ante `"TTC_CRITICO"`, debe priorizar evasión inmediata.

**Componente 5 — Instrucción de formato de salida.** Reiteración explícita del esquema JSON esperado y de los valores posibles del campo `action`, coherente con el `json_schema` declarado en el parámetro de formato. Esta redundancia entre prompt y schema es intencional: para modelos pequeños, la instrucción textual explícita mejora el `adherence_rate` incluso cuando la decodificación restringida está activa, especialmente en la elección del campo `action` dentro del dominio de la enumeración (Geng et al., 2025).

**Parámetros de inferencia.** `temperature = 0.2` (baja entropía, respuestas reproducibles y conservadoras), `max_tokens = 200` (suficiente para la estructura JSON más una razón breve; evita respuestas extensas que agoten el presupuesto de la KV cache y aumenten la latencia). El límite de tokens no es arbitrario: con `max_tokens = 200` y el esquema mínimo, la generación termina en 0.8–1.2 s en el hardware disponible; con `max_tokens = 500` subiría a 2–3 s, cruzando el watchdog `SLM_WATCHDOG_MS = 1500`.

## 8.6 Gestión de latencia: el watchdog y el creep speed

El tiempo de inferencia del VLM (0.8–2.0 s en el hardware disponible) es un orden de magnitud mayor que el período del lazo de control (200 ms a 5 Hz). Esto hace imposible bloquear el lazo esperando la respuesta; el nodo deliberativo opera de forma asincrónica a través de `DeliberationService` (§5.10 del cap. 5), que corre en un daemon thread independiente.

La consecuencia directa es que, durante el tiempo que el VLM procesa, el lazo de control continúa operando. En esos ciclos, el estado `"pending_deliberation"` activa `DELIB_WAIT_CREEP_SPEED_MPS = 0.5` m/s como velocidad de avance reducida — el dron continúa moviéndose muy lentamente en dirección al waypoint en lugar de detenerse, previniendo que la pérdida de velocidad traslacional colapse el campo de flujo óptico y elimine la evidencia perceptual justo cuando el sistema la necesita para la decisión pendiente.

El guard `SLM_WATCHDOG_MS = 1500` (§5.10) descarta respuestas que lleguen después de ese límite y activa `_fallback_decision()`. El watchdog tiene el efecto de que latencias de inferencia mayores a 1.5 s — frecuentes con el modelo de 7B bajo carga — equivalen a no tener deliberativo: el sistema cae en `keep_going` con nota de timeout. Esto refuerza la elección del modelo de 3B: una respuesta de calidad media entregada en 1.0 s vale más en este sistema que una respuesta de calidad alta entregada en 2.5 s.

## 8.7 Nota: LoRA como alternativa explorada y no adoptada

El fine-tuning ligero vía LoRA (*Low-Rank Adaptation*) fue evaluado durante la etapa de planificación como posible vía de especialización del modelo para el espacio de maniobras de este sistema (`informe/anexos/A4-OPTIMIZACION-LORA.md`). El argumento a favor era que un conjunto de pares (prompt, acción correcta) derivados de las corridas exitosas del sistema podría reducir la frecuencia de respuestas subóptimas sin reentrenar el modelo base.

No se implementó en el pipeline final por dos razones:

1. **Cobertura de datos insuficiente.** El conjunto de corridas disponible en el momento de la evaluación (piloto de 3 tiers, cap. 11) contiene situaciones de evasión relativamente homogéneas. Un LoRA entrenado sobre ese conjunto podría sobreajustar a los escenarios vistos y degradar la generalización en configuraciones urbanas no ensayadas.

2. **Complejidad de mantenimiento.** Un adaptador LoRA es un artefacto de entrenamiento que requiere ser versionado, evaluado y actualizado junto con el modelo base. Para el alcance de esta tesis, el beneficio esperado no justificó el costo de infraestructura. Se deja constancia explícita de que es una alternativa explorada y no adoptada por decisión de alcance, no por omisión.
