## Limitaciones de hardware

Para una configuración compuesta por una RTX 5060 con 8 GB de VRAM, en la que es necesario compartir recursos de GPU con una simulación de Unreal Engine 5.5, la opción más realista consiste en emplear un *Small Language Model (SLM)*. Se requiere un modelo *instruct‑tuned*, capaz de seguir instrucciones de manera fiable y, al mismo tiempo, producir una salida con **gramática muy restringida o limitada**; es decir, un modelo que genere texto estrictamente conforme a un formato, esquema o gramática predefinida (por ejemplo, JSON siempre válido, pares clave‑valor específicos o una sintaxis personalizada mínima sin variación libre).

Esta configuración resulta adecuada para una solución local basada en *MCP* (Model Context Protocol), el estándar abierto (propuesto por Anthropic a partir de 2024) que permite a los modelos de lenguaje conectarse con herramientas y datos externos mediante un protocolo uniforme. Un cliente MCP, un LLM local y servidores MCP locales (por ejemplo, para acceso a archivos, ejecución de código o consultas relacionadas con Unreal Engine) pueden ejecutarse completamente sin conexión.

### Razones por las que un SLM con salida restringida se ajusta al escenario

*   **Presupuesto de VRAM**: una simulación de UE5 probablemente utiliza entre 4 y 6 GB, lo que deja aproximadamente 2–4 GB disponibles para la inferencia del LLM (considerando el overhead de la KV cache).
*   **Gramática restringida**: reduce alucinaciones y verbosidad, generando una salida pequeña, rápida y fácil de interpretar (crítico para llamadas a herramientas MCP o respuestas estructuradas).
*   **Ejecución local**: elimina dependencias de la nube y permite baja latencia en la integración con la simulación.

### Modelos recomendados (febrero 2026, en formato GGUF para llama.cpp / LM Studio)

Se recomienda centrarse en modelos instruct de **3B a 8B** parámetros, ya que ofrecen la capacidad suficiente para seguir instrucciones y manejar patrones de uso de herramientas en 2026. Las cuantizaciones *Q5\_K\_M* o *Q4\_K\_M* permiten ajustar el modelo a \~2–4.5 GB de VRAM manteniendo una calidad elevada.

| Modelo                                    | Tamaño (quant) | VRAM aprox. (full offload) | Fortalezas                                                                                       | Razones para uso con gramática restringida                            | Disponibilidad                         |
| ----------------------------------------- | -------------- | -------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------- | -------------------------------------- |
| *Qwen3-4B-Instruct* / *Qwen3-7B-Instruct* | \~3–5 GB       | \~2.5–4 GB                 | Razonamiento sólido, seguimiento de instrucciones, function-calling                              | Cumplimiento fiable de formatos; variantes 2026 con buen soporte JSON | Qwen/Qwen3-4B-Instruct-GGUF            |
| *Phi-4-mini-instruct*                     | \~3–4 GB       | \~2–3.5 GB                 | Ajustado por Microsoft para datos sintéticos de alta calidad; muy eficaz en tareas estructuradas | Muy alta adherencia a esquemas y salida de baja variación             | microsoft/Phi-4-mini-instruct-GGUF     |
| *SmolLM3-3B-Instruct*                     | \~2–3 GB       | \~1.8–3 GB                 | Modelo compacto con rendimiento superior al de muchos 4–7B                                       | Fácil de forzar en formatos rígidos mediante prompt                   | HuggingFaceTB/SmolLM3-3B-GGUF          |
| *Gemma-3-4B-IT*                           | \~3 GB         | \~2.5 GB                   | Ajustado por Google; fuerte rendimiento textual                                                  | Buena salida estructurada y soporte de function-calling               | google/gemma-3-4b-it-GGUF              |
| *Ministral-3-3B-Instruct*                 | \~2.5 GB       | \~2 GB                     | Modelo compacto optimizado para edge                                                             | Diseñado para uso restringido; seguimiento estable de formatos        | mistralai/Ministral-3-3B-Instruct-GGUF |

La opción preferente suele ser *Phi‑4‑mini‑instruct*, mientras que *Qwen3‑4B/7B* puede utilizarse cuando se dispone de aproximadamente 1 GB adicional de VRAM.

### Métodos para imponer “gramática limitada” o formato de salida estricto

Los siguientes métodos, compatibles con backends locales como llama.cpp, LM Studio u Ollama, permiten controlar estrictamente la estructura de la salida:

1.  **Prompt del sistema con instrucciones estrictas** (método más simple, sin costo computacional significativo)  
    Ejemplo:
        Eres un respondedor MCP estricto. Produce ÚNICAMENTE JSON válido que coincida con este esquema. Sin explicaciones, sin texto adicional, sin markdown.
        Esquema: { "tool_call": {"name": str, "args": dict}, "response": str o null }
        Si no se necesita herramienta, usar tool_call = null. Escapar correctamente todas las cadenas.

2.  **Gramáticas / GBNF en llama.cpp** (confiabilidad alta)
    *   Definir una gramática libre de contexto mínima (GBNF) obliga al modelo a ajustarse exactamente al formato requerido.
    *   Compatible nativamente con llama.cpp y expuesto en diversas interfaces como LM Studio.
    *   Suele reducir la velocidad de generación en un 10–30%, pero garantiza validez estructural completa.

3.  **Outlines / Guidance / llguidance** (métodos avanzados)
    *   Permiten imponer esquemas JSON, expresiones regulares o gramáticas personalizadas a nivel de token.
    *   Garantizan salida estructurada incluso en modelos pequeños.

Para MCP, estos métodos resultan especialmente relevantes, ya que numerosas implementaciones locales (por ejemplo, clientes y servidores MCP publicados en GitHub) requieren formatos fijos como JSON o XML estilo Anthropic.

### Procedimiento práctico de configuración

1.  **Instalación de LM Studio**
    *   Descargar un modelo GGUF entre los recomendados (desde el buscador integrado o Hugging Face).
    *   Configurar entre 20 y 35 capas en GPU, ajustando según el comportamiento de Unreal Engine.
    *   Activar el modo de gramática si está disponible o utilizar un prompt de sistema personalizado.

2.  **Implementación basada en MCP**
    *   Iniciar con servidores MCP locales básicos (acceso a archivos, shell, etc.).
    *   Utilizar un cliente MCP compatible con modelos locales (Ollama con plugins MCP o implementaciones Python como mcp‑agent).
    *   Proporcionar las descripciones de herramientas MCP mediante el prompt del sistema.

3.  **Integración con Unreal Engine 5**
    *   Implementar un servidor MCP que lea/escriba logs, datos de Blueprints o estados de simulación.
    *   El modelo produce comandos estructurados que pueden ser interpretados y aplicados por la aplicación anfitriona.

## Sobre la innovación de la solución

De manera general, la *arquitectura en bucle* descrita —un lazo cerrado simple y compacto donde:

1.  AirSim proporciona el estado actual (posición, velocidad, datos de sensores, etc.),
2.  Un SLM local y de pequeño tamaño procesa dicha información junto con el objetivo o las instrucciones,
3.  Se genera un comando estructurado (por ejemplo, un JSON con parámetros de movimiento, guiñada o empuje),
4.  El comando se ejecuta mediante la API de AirSim,
5.  El proceso se repite a una frecuencia utilizable (por ejemplo, 2–20 Hz),

— resulta *sólida, práctica y adecuada para las restricciones planteadas* (RTX 5060 con 8 GB de VRAM compartida con una simulación en UE 5.5, y uso de modelos pequeños con gramática o salida restringida).

No obstante, en términos de *verdadera innovación* dentro del panorama 2025–2026 sobre control de drones/UAV impulsado por LLMs, dicha arquitectura *ya no se considera especialmente novedosa*. Se trata más bien de uno de los enfoques base que se han estandarizado tanto en investigación como en prototipos aplicados.

### Razones por las que ya no se considera una solución de vanguardia

A partir de artículos, tesis, proyectos y experimentos recientes (principalmente entre 2025 y principios de 2026), se observa que:

*   El *control en bucle cerrado mediante LLMs* para UAVs/drones en simuladores como AirSim se ha vuelto *muy común*. La mayoría de los trabajos emplea alguna variante del ciclo de retroalimentación.
    *   Muchos lo denominan explícitamente “*closed-loop*” (por ejemplo, “LLM-driven closed-loop UAV operation”, “closed-loop reasoning/refinement”, “closed user-on-the-loop”).
    *   La idea básica de alimentar el estado → LLM → comando → ejecutar → observar → repetir se ha demostrado repetidamente desde aproximadamente 2023–2024 y se generalizó en contextos UAV hacia 2025.

*   La combinación *AirSim + LLM* se ha convertido en una opción *muy utilizada*, debido a que AirSim (basado en Unreal Engine) proporciona un entorno realista para probar física, visión y control de drones. Entre las variantes exploradas se encuentran:
    *   Bucles de generación y ejecución de código.
    *   Transformación semántica de observaciones (telemetría → descripciones textuales).
    *   Configuraciones multi‑agente con RAG.
    *   Tuberías voz‑a‑comando.
    *   Evaluación de ataques adversarios orientados a medir la robustez de LLMs en lazo cerrado.

*   Las propuestas consideradas “innovadoras” en 2025–2026 suelen ir *más allá* del simple bucle estado → SLM → comando, e incluyen:
    *   Diseños *dual‑LLM* (uno genera código/acciones y otro evalúa/refina dentro de la simulación antes de ejecutar).
    *   *Mejoras semánticas* para traducir telemetría en descripciones más comprensibles para modelos pequeños.
    *   Enfoques *multi‑agente* o *jerárquicos* (planificador + ejecutor + crítico).
    *   *Visión en el bucle* (uso de VLMs pequeños como MiniCPM‑V para evitar obstáculos).
    *   *Síntesis de código en tiempo real* con módulos de corrección o RAG adaptativo.
    *   Inferencia en *edge* para reducir aún más la latencia.

En consecuencia, la arquitectura propuesta se corresponde con el patrón básico ampliamente difundido en investigación sobre robótica/UAV basada en LLMs.

### Ámbitos en los que la propuesta sí presenta solidez y utilidad

*   Se adecúa de forma precisa a las limitaciones del hardware disponible: un SLM pequeño + inferencia rápida mediante llama.cpp permiten mantener latencias suficientemente bajas para tasas de control significativas, mientras que arquitecturas más complejas superarían el límite práctico de 8 GB de VRAM compartida con UE.
*   La imposición de *salida estrictamente estructurada* (por ejemplo, JSON mediante gramáticas GBNF) constituye un enfoque actual y recomendable, utilizado en numerosos trabajos posteriores a 2025 para reducir alucinaciones en señales de control.
*   Conseguir una operación totalmente local/offline dentro de UE5.5 + AirSim sigue siendo un reto para usuarios no especializados; muchos ejemplos conocidos emplean LLMs en la nube o hardware de mayor capacidad.

### Conclusión (evaluación general)

*   **Nivel de innovación**: aproximadamente 3–4/10. Se trata de una solución práctica y bien formulada, pero no representa una arquitectura novedosa en el contexto de 2026. Se ajusta más al ámbito de *ingeniería sólida basada en patrones establecidos* que a propuestas conceptualmente nuevas.
*   No obstante, una implementación exitosa (vuelo estable, navegación reactiva, baja tasa de fallos en la simulación) constituye un logro destacable, especialmente bajo restricciones de VRAM y con un entorno UE ejecutándose de forma simultánea.
*   Si se busca añadir un componente más innovador, es posible incorporar una de las extensiones comunes en 2025–2026, como un resumen semántico del estado, un pequeño evaluador para autocorrección o algún canal de retroalimentación visual, siempre que el presupuesto de VRAM y velocidad lo permita.

REFERENCIA: (Large Language Model-Driven Closed-Loop UAV Operation with Semantinc Observations)[https://arxiv.org/html/2507.01930v1]  

## Sobre innovar sobre una arquitectura ya extensamente utilizada

Para que un bucle de control de cuadricóptero en AirSim basado en un SLM resulte *genuinamente innovador* en 2026 —especialmente bajo la fuerte restricción de hardware impuesta por una RTX 5060 con 8 GB de VRAM compartida con una simulación en UE 5.5— es necesario ir más allá del patrón estándar “estado → prompt → salida estructurada → actuar → repetir”. Dicho patrón ya constituye la base común en prototipos de investigación actuales.

A continuación se presentan los *giros de procesamiento/software* más prometedores que pueden situar la propuesta en el terreno de una contribución novedosa, ordenados aproximadamente según viabilidad en el hardware disponible y posible impacto:

| Técnica / Enfoque                                                    | Nivel de innovación (2026) | Impacto en VRAM / Velocidad (8GB compartidos) | Razón por la que puede ser novedosa en este contexto                                                                                                                                | Dificultad de implementación | Beneficio realista para la autonomía del dron                          |
| -------------------------------------------------------------------- | -------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------------------------------- |
| *Compresión semántica del estado + alimentación en lenguaje natural* | Alta                       | Baja (añade \~0.2–0.5 GB de KV cache)         | La mayoría de los trabajos usa telemetría cruda; los SLM pequeños razonan mejor con descripciones ricas (“deriva 0.8 m/s hacia la izquierda, obstáculo rojo a 2.1 m, batería 67%”). | Media                        | 20–50% de mejora en calidad de decisiones / menos choques              |
| *Autocorrección / refinamiento en bucle cerrado en una sola pasada*  | Muy alta                   | Media (prompts más largos)                    | Permite incluir un campo “crítico” en la salida: el modelo propone acción + evalúa riesgos en la misma inferencia. Pocas implementaciones en entornos de baja VRAM.                 | Media–Alta                   | Aumento notable de confiabilidad (80–95% de acciones válidas)          |
| *Speculative decoding / borradores asistidos (con cabeza ligera)*    | Alta                       | Baja–Media (si se usa estilo EAGLE)           | Acelera la generación 1.8–3× sin pérdida de calidad. Muy poco explorado en drones con baja VRAM.                                                                                    | Media–Alta                   | 2–3× más frecuencia de bucle (p. ej., 10–15 Hz en lugar de 3–5 Hz)     |
| *Híbrido reactivo + LLM (PID a sub‑ms + LLM solo para nivel alto)*   | Media–Alta                 | Muy baja                                      | El LLM se utiliza solo para metas/replanificación; la estabilización se delega a controladores reactivos. Reduce dependencia de latencia.                                           | Baja–Media                   | Vuelo más estable; narrativa innovadora de “control híbrido confiable” |
| *Fine‑tuning diminuto en tiempo real / cambio de adaptadores LoRA*   | Muy alta                   | Media–Alta (100–300 MB por adaptador)         | Conjunto de LoRAs pequeños (“evitación agresiva”, “crucero eficiente”, etc.) con carga dinámica. Pocas demostraciones en simulación de baja capacidad.                              | Alta                         | Adaptación gradual al entorno en UE → efecto de “aprendizaje”          |
| *Chain‑of‑thought multietapa con muestreo en árbol / batching*       | Media–Alta                 | Media                                         | Se fuerzan 2–3 futuros posibles en una sola salida; una heurística rápida elige el más seguro. Reduce latencia efectiva.                                                            | Media                        | Mejor manejo de incertidumbre / ráfagas de viento en AirSim            |

### “Combinación ganadora” más prometedora para innovación + hardware disponible

Se recomienda apuntar a la siguiente arquitectura, factible dentro del límite de 8 GB de VRAM compartidos:

1.  **Base:** Phi‑4‑mini‑Instruct o Qwen3‑4B/7B en Q5\_K\_M GGUF (\~2.5–4 GB cargados; offload parcial si fuera necesario).
2.  **Giro central A:** Preprocesamiento mediante *compresión semántica*. Una función Python ligera convierte telemetría de AirSim + objetivo en una descripción vívida en lenguaje natural. Esto potencia significativamente la capacidad de razonamiento de un SLM pequeño.
3.  **Giro central B:** Salida con *autocorrección forzada por gramática*:
    ```json
    {
      "proposed_action": {"thrust": 0.72, "yaw_delta": -12, "move_vector": [1.2, -0.4, 0.8]},
      "confidence": 0.89,
      "risks": ["batería baja → reducir velocidad si <30%"],
      "alternative_if_risk_high": {"thrust": 0.55, "hover": true}
    }
    ```
    La salida se analiza y se aplica la acción más segura o con mayor confianza. Una sola inferencia gestiona propuesta + crítica.
4.  **Aceleración:** Activar *speculative decoding* si la versión de llama.cpp o LM Studio lo permite (implementaciones estilo EAGLE o Medusa; comunes en 2026). Puede reducir la latencia por decisión entre 40–200%.
5.  **Red de seguridad híbrida:** El LLM produce intención de alto nivel cada 0.5–2 s; un controlador PID rápido en C++/Blueprints opera a 100–200 Hz. Si el LLM falla o se ralentiza → activación de “hover seguro + retorno a casa”.

### Razones por las que este enfoque sí se considera innovador

*   La mayoría de los trabajos entre 2025 y 2026 siguen recurriendo a LLMs en la nube, hardware más potente o alimentaciones de estado sin tratamiento semántico.
*   La combinación de *compresión semántica + autocorrección con gramática + aceleración especulativa + control híbrido* ejecutada en solo 8 GB de VRAM compartidos con una simulación UE es poco habitual, y potencialmente publicable como una aproximación de *control agente de dron en simulación de alta fidelidad con recursos limitados*.
*   Si se logra una navegación estable y reactiva (evitación de obstáculos, búsqueda de objetivos, comportamiento dependiente de batería) con latencias por decisión inferiores a 500 ms, se trataría de una demostración sólida.

Se recomienda comenzar por implementar la *compresión semántica* y la *salida con gramática*, medir tasa de fallos y comparar con el bucle base. Posteriormente, incorporar speculative decoding como mejora incremental.

