# 12. Conclusiones

> **Estado:** pendiente del capítulo de resultados (cap. 11), que a su vez depende de la corrida experimental comparativa descrita en el capítulo 10.

## 12.1 Retomar el hilo conductor

Cerrar aquí el argumento declarado en la introducción (§1.4) y desarrollado con evidencia medida en el capítulo 9: en un sistema de control donde un modelo de lenguaje consume descripciones de escena, el error más caro está en la interfaz que lo alimenta, no en el razonamiento del modelo, y las instancias documentadas de ese patrón —desincronización de esquemas de percepción y campos nulos, desalineación en secuencias temporales, saturación por descalibración de escala diferencial, y descarte silencioso en grafos de estado— se detectaron auditando formalmente los contratos de datos y la propagación de estado, nunca observando únicamente el comportamiento superficial del vuelo.

## 12.2 Respuesta a la pregunta de investigación

¿Aporta el SLM sobre la FSM? Síntesis de §11.4, con los matices por tipo de escenario que surjan de la corrida experimental — evitar una respuesta única y agregada si los datos sostienen una respuesta más matizada por escenario.

## 12.3 Limitaciones

- Validación exclusivamente en simulación (AirSim); sin validación en hardware físico (Jetson Nano + dron real), que el plan de trabajo aprobado (`plan_tesis/plan-tesis.md`, §"Transferencia de los resultados obtenidos") sitúa como siguiente etapa fuera del alcance de este trabajo.
- Calibración del canal de ocupación de `ObstacleField` pendiente al cierre de este escrito (cap. 6, §6.3), con el canal de TTC como el único de los dos formalmente validado contra profundidad (cap. 7).
- Tamaño de muestra y generalización: a determinar según el número final de semillas y escenarios de la corrida de tesis (cap. 10).

## 12.4 Trabajo futuro y mejoras

Las líneas de continuidad y optimización derivadas de este trabajo se estructuran en cuatro ejes prioritarios, integrando tanto la transferencia física como las arquitecturas de optimización del nodo deliberativo analizadas teóricamente pero no desplegadas en la corrida experimental base:

- **Especialización y adaptación ligera del modelo deliberativo vía LoRA/QLoRA (Anexo 3):**
  En la implementación evaluada, el modelo multimodal (**Qwen2.5-VL-3B-Instruct**) opera en régimen *zero-shot / in-context learning*, lo cual exige verbalizar en cada ciclo la telemetría, el resumen del `ObstacleField`, el historial y las restricciones sintácticas (~500 tokens de prompt), empujando la latencia de inferencia (850–1400 ms) hacia el límite del perro guardián (`SLM_WATCHDOG_MS = 1500 ms`). Como se fundamenta en el capítulo 8 (§8.7) y se desarrolla en detalle en el [Anexo 3](anexos/A3-OPTIMIZACION-LORA.md), la sintonización fina de bajo rango (*Low-Rank Adaptation*, LoRA / QLoRA / DoRA) quedó excluida del alcance inmediato por escasez de diversidad en el dataset de maniobras inicial y para evitar riesgos de sobreajuste a geometrías urbanas particulares. Como trabajo futuro, se proyecta entrenar adaptadores sobre las matrices de atención ($W_q, W_v$) y proyecciones MLP del LLM (manteniendo congelado el codificador visual ViT) utilizando la telemetría de vuelos exitosos. Esto permitirá internalizar el espacio cinemático y el formato estructurado en los pesos de la red, reduciendo el prompt a <100 tokens y la latencia a <500 ms sin incurrir en degradaciones por timeout.

- **Decodificación restringida con gramáticas reducidas y dinámicas condicionadas por el grafo (Anexo 4):**
  La versión actual del lazo táctico emplea un esquema estático global (`DroneTacticalDecision`) con el abanico completo de 5 macro-acciones acoplado a un analizador tolerante (§8.2). En el [Anexo 4](anexos/A4-DECODIFICACION-RESTRINGIDA.md), §A4.4.2, se documenta la especificación técnica de una optimización no implementada en el ciclo actual: la **inyección dinámica de gramáticas acotadas según el estado de vuelo y el motivo de consulta (`reason_note`)**. Como línea de mejora, se propone parametrizar el autómata de decodificación (GBNF / JSON Schema) en tiempo real:
  - Ante colisiones inminentes (`"TTC_CRITICO"`), restringir la gramática estrictamente a `["evasive", "girar_90"]`, podando sintácticamente cualquier token asociado a acciones pasivas (`keep_going`).
  - Ante atascos cinemáticos (`"DEADLOCK_ESCAPE"`), forzar alternativas de escape (`["girar_90", "fsm", "degraded"]`), impidiendo bucles de evasión redundantes.
  - Esta poda semántica *a priori* concentrará la distribución de probabilidad en alternativas físicamente coherentes, reducirá la entropía de muestreo y acelerará la decodificación aprovechando el salto de tokens (*token fast-forwarding*).

- **Perfeccionamiento del lazo perceptual monocular (Anexo 5):**
  - Calibración formal del canal de ocupación de `ObstacleField` contra el mapa de profundidad de ground truth (cap. 6, §6.3; [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md)), completando el protocolo de curva ROC y derivación del umbral óptimo por índice de Youden de forma análoga a la validación del TTC (cap. 7, §7.5).
  - Validación y robustecimiento de la compensación de flujo óptico por derotación angular frente a maniobras de guiñada (*yaw*) agresivas (> 0.3 rad/s), superando el rango acotado del dataset preliminar (cap. 7, §7.4, §7.6; [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md), §A5.3).

- **Transferencia a hardware embebido y navegación en enjambre:**
  - Validación en plataforma física real: integración en una *companion computer* de bajo consumo (e.g., NVIDIA Jetson Nano / Orin) conectada vía MAVLink/ROS a un cuadrirrotor físico con sensor monocular, evaluando el lazo reactivo-táctico en entornos reales según las fases delineadas en el plan de trabajo aprobado (`plan_tesis/plan-tesis.md`).
  - Extensión a navegación cooperativa en enjambre y fusión sensorial con sensores complementarios (e.g., flujo óptico diferencial con sensores acústicos o ToF ultraligeros).

