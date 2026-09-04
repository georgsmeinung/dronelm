# 8. Ingeniería de decisiones del SLM

## 8.1 Selección del modelo

La restricción de hardware determina buena parte de las decisiones de este capítulo: compartir GPU con una simulación de Unreal Engine 5.5 deja un presupuesto de VRAM acotado para la inferencia a bordo, lo que orienta la elección hacia modelos multimodales compactos (*Small Vision-Language Models*, VLM) del orden de 3 a 7 mil millones de parámetros. En la implementación definitiva, el sistema adopta **Qwen2.5-VL-3B-Instruct** (ejecutado localmente bajo LM Studio o vLLM), el cual combina capacidad de razonamiento simbólico con comprensión visual directa de la cámara a bordo.

A diferencia de un SLM textual puro que únicamente lee resúmenes serializados de la percepción, el nodo deliberativo multimodal procesa:

1. **Historial temporal de fotogramas (`VLM_FRAME_HISTORY_SIZE = 2`):** Envío conjunto de los fotogramas en tiempo real correspondientes al ciclo actual ($t$) y al ciclo previo ($t-1$), permitiendo al modelo estimar la dirección visual de aproximación o desvío.
2. **Dinámica de vuelo y actitud:** Inyección de la velocidad horizontal estimada y los ángulos de orientación física (`pitch` y `roll` reales, obtenidos tras la corrección del cuaternión en `cosysairsim`), alertando explícitamente si el cuadricóptero se encuentra en traslación activa o prácticamente detenido.
3. **Motivo explícito de consulta:** Distinción estructurada en el prompt entre consultas forzadas por un obstáculo frontal severo con TTC bajo frente a consultas disparadas por pérdida transitoria de confianza del flujo óptico (evitando que el modelo alucine bloqueos inexistentes en maniobras de rotación sobre el eje).

El detalle de modelos preliminares explorados (Phi-4-mini-instruct, Qwen-Coder-7B, entre otros), su huella de VRAM estimada y el procedimiento de configuración quedan documentados en `informe/anexos/A1-EXPLORACION-SLM-GGUF.md` y `informe/anexos/A2-SLM-CONCEPTO-Y-VENTAJAS.md`.

Es relevante señalar, para el posicionamiento de este trabajo frente al estado del arte (cap. 2), que la arquitectura de lazo cerrado estado→SLM→comando→ejecución no es, hacia 2025-2026, especialmente novedosa: es uno de los patrones ya estandarizados en investigación y prototipos aplicados de UAVs controlados por modelos de lenguaje (ver `informe/anexos/A1-EXPLORACION-SLM-GGUF.md`). El aporte de este trabajo no está en la novedad de esa arquitectura general, sino en la ingeniería de su interfaz con la percepción (cap. 6) y en la documentación medida de sus modos de falla (cap. 9).

## 8.2 Decodificación restringida vs. parser tolerante

La respuesta del modelo se solicita con `response_format={"type": "json_schema", ...}` —soportado tanto por LM Studio como por Ollama— en lugar de depender únicamente de un parser por expresiones regulares sobre texto libre. La decodificación restringida reduce la superficie de respuestas inválidas o verborrágicas, pero no sustituye por completo al parser: `_parse_decision()` se conserva como red de seguridad, capaz de tolerar markdown, texto conversacional o JSON truncado, precisamente porque la garantía de `json_schema` depende de que el backend local la soporte en la versión efectivamente desplegada, algo que no puede darse por sentado sin verificarlo en cada entorno.

La métrica que resume esta capa es `adherence_rate`: la fracción de respuestas parseables al primer intento, medida con y sin decodificación restringida. Es, en sí misma, una fila de la tabla de resultados (cap. 11) y no solo una decisión de ingeniería: cuantifica cuánto aporta, en la práctica, la gramática restringida por sobre el parser tolerante como única defensa.

## 8.3 Espacio de acción discreto

El modelo de lenguaje —al igual que la FSM y el brazo puramente reactivo (cap. 10)— no produce comandos cinemáticos directamente: elige entre un conjunto acotado y auditable de macro-acciones (`keep_going`, `evasive`, `girar_90`, y las que resuelve el nodo deliberativo o la FSM según el brazo activo, incluida una ruta `fsm` cuando ese es el brazo seleccionado, y un estado `degraded` para modo degradado). Restringir la salida a una lista blanca de acciones válidas — en lugar de permitir que el modelo produzca parámetros cinemáticos libres — es la decisión de diseño que hace posible, a la vez, la decodificación restringida de la sección 8.2 y la comparación limpia entre brazos del capítulo 10: los tres brazos comparten el mismo espacio de acciones y el mismo traductor a comandos (sección 8.4), de modo que lo único que difiere entre ellos es **quién** elige la etiqueta, no **qué puede** elegir.

## 8.4 `action_to_command`: la frontera entre lenguaje y cinemática

Cada macro-acción se traduce a un comando cinemático concreto (velocidades lineales en los tres ejes y tasa de guiñada) a través de una única función centralizada (`action_to_command`, `src/agents/action_map.py`), compartida de forma estricta por los nodos deliberativo, de evasión y de FSM.

Esta frontera desacopla la semántica de alto nivel del control de bajo nivel y garantiza un invariante crítico de diseño: **ninguna macro-acción puede poseer definiciones cinemáticas dispares o no coordinadas en el sistema**. Al centralizar la traducción, se previene la introducción de derivas asimétricas no deseadas en maniobras de evasión o ascenso (capítulo 9), asegurando que tanto las decisiones generadas por el modelo de lenguaje como las derivadas por la máquina de estados o el control reactivo se ejecuten bajo idénticas restricciones y perfiles de velocidad.

## 8.5 Nota: LoRA como alternativa no adoptada

El pipeline final usa el SLM tal como se distribuye en formato GGUF cuantizado, sin ajuste fino. LoRA (*Low-Rank Adaptation*) se evaluó en la etapa de planificación como una posible vía de especialización del modelo —documentada en `informe/anexos/A4-OPTIMIZACION-LORA.md`— pero no hay evidencia en el código actual de que se haya implementado en el pipeline final. Se deja constancia explícita de que es una alternativa explorada y no adoptada, por decisión de alcance y no por omisión.
