# 12. Conclusiones

## 12.1 Retomar el hilo conductor

Este trabajo partió de una constatación práctica: en un sistema de control donde un modelo de lenguaje visivo consume descripciones de escena para deliberar sobre maniobras de evasión, el error más caro no está en la política de decisión del modelo sino en la interfaz que lo alimenta.

La evidencia de esa afirmación —desincronización de esquemas de percepción, campos nulos por calibración de escala diferencial, descarte silencioso en grafos de estado— nunca emergió observando el comportamiento superficial del vuelo; emergió auditando formalmente los contratos de datos y la propagación de estado entre capas (cap. 9).

Los 75 runs del lote experimental (5 escenarios × 3 brazos × 5 semillas) validan la arquitectura resultante de ese proceso de depuración y permiten responder, con datos, a la pregunta de investigación central.

---

## 12.2 Respuesta a la pregunta de investigación

**¿Aporta el brazo deliberativo VLM (`slm`) sobre la máquina de estados (`fsm`) y sobre el control puramente reactivo (`reactive`) en navegación autónoma de dron en entornos urbanos simulados?**

La respuesta es matizada por escenario y no puede reducirse a un único enunciado:

### En entornos de tránsito libre (45 corridas de control)

El `slm` no aporta ventaja sobre el `fsm` ni sobre el `reactive` en términos de tasa de éxito o seguridad: los tres brazos completan todas las rutas sin colisiones. El VLM introduce un overhead de tiempo que se diluye con la longitud de ruta (**H2 confirmada**):

| Escenario | Ruta aprox. | Ratio `slm`/`reactive` |
|---|---|---|
| `minisim_clear` (Tier 0, ~185 m) | 2.20× |
| `townsim_clear` (Tier 1, ~626 m) | 1.14× |
| `citysim_clear` (Tier 2, ~427 m) | 1.06× |

El ratio decrece monótonamente (Cliff's δ = 1.0 en comparaciones por pares). La convergencia hacia 1.0× a medida que la ruta se alarga confirma que el overhead del VLM —fijo por invocación, ~850–1400 ms— es absorbido por el presupuesto total de vuelo: en rutas largas, pocas invocaciones son necesarias y su peso relativo decrece. Esta predicción se sostenía teóricamente (cap. 8, §8.6)
y los datos la verifican.

### En entornos con obstrucción (30 corridas de prueba extendida)

La evidencia es heterogénea y revela tres regímenes cualitativamente distintos:

**Régimen 1 — Deadlock crónico por límite de percepción (`townsim_ini`):** El corredor arbolado a z=−10 m produce 0/5 éxitos en los tres brazos. El flujo óptico traslacional se anula precisamente en los obstáculos centrados en la trayectoria (cerca del Foco de Expansión), que son los de mayor riesgo frontal. Ningún mecanismo de decisión puede compensar la ausencia de señal geométrica confiable: ni el `deep_vlm`, ni la FSM, ni el control reactivo. Este es un
límite del sensor, no del algoritmo.

**Régimen 2 — Trampa geométrica por ausencia de razonamiento global (`citymap_pilot`):** Los brazos deliberativos (`slm`, `fsm`) cubren **6.3× más distancia** que el `reactive` (170 m vs. 27 m). El `reactive` queda paralizado bajo una autopista elevada: el flujo óptico detecta superficies en todas las direcciones y el controlador oscila sin escape posible — sin razonamiento global, ninguna evasión local desbloquea la situación. El `deep_vlm`, aunque no logra completar la misión en 600 s, permite que los brazos deliberativos progresen por la grilla urbana eligiendo corredores que el flujo óptico no puede discriminar. Esta es la evidencia más directa a favor de **H1** disponible en el lote.

**Régimen 3 — Obstrucción frontal con escape lateral accesible
(`townsim_calib_cruce_frontal`):** El `reactive` supera a los brazos deliberativos (2/5 vs. 1/5 vs. 0/5). Cuando existe una ruta de escape geométricamente accesible desde la posición actual, el flujo óptico la encuentra más rápido porque no detiene el vuelo para deliberar; el `deep_vlm` introduce latencia de reposicionamiento que, en el momento de la oportunidad de evasión, ya pasó. El VLM no aporta ventaja —y en la mayoría de semillas introduce una desventaja neta.

### Síntesis

El VLM aporta valor en exactamente el régimen para el que fue diseñado: ambigüedad semántica entre corredores de textura uniforme donde el flujo óptico no puede discriminar la dirección correcta.

No aporta valor en ruta libre ni en obstrucciones con escape local. No puede compensar el límite físico del sensor monocular en textura auto-similar densa. Con K=5 semillas y la corrección de Bonferroni aplicada a 18 comparaciones (α_corr ≈ 0.0028), ningún resultado individual alcanza significancia estadística formal. El patrón H2, no obstante, es consistente con δ = 1.0 en todos los pares, y el patrón H1 en `citymap_pilot` es cuantitativamente sustancial (6.3×) aunque no completable en el presupuesto temporal disponible. La validación estadística requeriría K ≥ 10–15 semillas por condición.

---

## 12.3 Limitaciones

- **Validación exclusivamente en simulación (AirSim):** sin validación en hardware físico (Jetson Nano + dron real), que el plan de trabajo aprobado (`plan_tesis/plan-tesis.md`, §"Transferencia de los resultados obtenidos") sitúa como siguiente etapa fuera del alcance de este trabajo.

- **Tamaño de muestra:** K=5 semillas por condición (75 corridas en total). La corrección de Bonferroni para 18 comparaciones fija α_corr ≈ 0.0028, un umbral que el p-valor mínimo alcanzable con K=5 (p ≈ 7.9×10⁻³) no puede superar. Los resultados son indicativos y cuantitativamente consistentes, pero no formalmente significativos.

- **Sensor monocular (parcialmente mitigado):** el canal de flujo óptico depende del movimiento del vehículo entre frames, lo que lo hace estructuralmente ciego a obstáculos centrados en la trayectoria (Foco de Expansión). El límite observado en `townsim_ini` no se resuelve por ajuste de parámetros. Se incorporó un segundo canal de profundidad inferida (Depth Anything V2 Metric, §5.6 V4 / §6.10b) que opera solo sobre RGB y cubre parcialmente ese punto ciego; sus falsos positivos en renders sintéticos están mitigados por la guarda V4b pero no eliminados. El límite del sensor en texturas auto-similares densas (`townsim_ini`) sigue siendo estructural y requiere validación en corridas reales (cap. 11, §11.5.3; Anexo 7).

- **Calibración del canal de ocupación de `ObstacleField` pendiente:** el canal de TTC está formalmente validado contra profundidad ground truth (cap. 7); el umbral de ocupación(`OBSTACLE_OCCUPANCY_BLOCKED = 0.35`) es provisorio (cap. 6, §6.9; cap. 7, §7.5).

- **Un único mapa por escenario:** cada escenario de obstrucción se corrió en un solo mapa urbano (TownSim o CitySim). La generalización de los resultados a otras geometrías urbanas no está garantizada con los datos disponibles.

- **VLM fijo (Qwen2.5-VL-3B-Instruct, zero-shot):** el modelo opera en régimen zero-shot sin sintonización al dominio de vuelo. Los resultados de deliberación están acotados por la distribución de preentrenamiento del modelo y el diseño del prompt, no por la capacidad máxima de la arquitectura.

---

## 12.4 Trabajo futuro y mejoras

Las líneas de continuidad y optimización derivadas de este trabajo se estructuran en cinco ejes prioritarios, integrando la transferencia física, la arquitectura del nodo deliberativo y la infraestructura perceptual:

- **Especialización y adaptación ligera del modelo deliberativo vía LoRA/QLoRA (Anexo 3):** En la implementación evaluada, el modelo multimodal (**Qwen2.5-VL-3B-Instruct**) opera en régimen *zero-shot / in-context learning*, lo cual exige verbalizar en cada ciclo la telemetría, el resumen del `ObstacleField`, el historial y las restricciones sintácticas (~500 tokens de prompt), empujando la latencia de inferencia (850–1400 ms) hacia el límite del perro guardián (`SLM_WATCHDOG_MS = 1500 ms`). Como se fundamenta en el capítulo 8 (§8.7) y se desarrolla en detalle en el [Anexo 3](anexos/A3-OPTIMIZACION-LORA.md), la sintonización fina de bajo rango (*Low-Rank Adaptation*, LoRA / QLoRA / DoRA) quedó excluida del alcance inmediato por escasez de diversidad en el dataset de maniobras inicial y para evitar riesgos de sobreajuste a geometrías urbanas particulares. Como trabajo futuro, se proyecta entrenar adaptadores sobre las   matrices de atención ($W_q, W_v$) y proyecciones MLP del LLM (manteniendo congelado el codificador visual ViT) utilizando la telemetría de vuelos exitosos. Esto permitirá internalizar el espacio cinemático y el formato estructurado en los pesos de la red, reduciendo el prompt a <100 tokens y la latencia a <500 ms sin incurrir en degradaciones por timeout.

- **Decodificación restringida con gramáticas reducidas y dinámicas condicionadas por el grafo (Anexo 4):** La versión actual del lazo táctico emplea un esquema estático global (`DroneTacticalDecision`) con el abanico completo de 5 macro-acciones acoplado a un analizador tolerante (§8.2). En el [Anexo 4](anexos/A4-DECODIFICACION-RESTRINGIDA.md), §A4.4.2, se documenta la especificación técnica de una optimización no implementada en el ciclo actual: la **inyección dinámica de gramáticas acotadas según el estado de vuelo y el motivo de consulta (`reason_note`)**. Como línea de mejora, se propone parametrizar el autómata de decodificación (GBNF / JSON Schema) en tiempo real:
  - Ante colisiones inminentes (`"TTC_CRITICO"`), restringir la gramática estrictamente a `["evasive", "girar_90"]`, podando sintácticamente cualquier token asociado a acciones pasivas.
  - Ante atascos cinemáticos (`"DEADLOCK_ESCAPE"`), forzar alternativas de escape `["girar_90", "fsm", "degraded"]`, impidiendo bucles de evasión redundantes.
  - Esta poda semántica *a priori* concentrará la distribución de probabilidad en alternativas físicamente coherentes, reducirá la entropía de muestreo y acelerará la decodificación aprovechando el salto de tokens (*token fast-forwarding*).

- **Perfeccionamiento del lazo perceptual monocular (Anexo 5):**
  - Calibración formal del canal de ocupación de `ObstacleField` contra el mapa de profundidad de ground truth (cap. 6, §6.3; [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md)), completando el protocolo de curva ROC y derivación del umbral óptimo por índice de Youden.
  - Validación y robustecimiento de la compensación de flujo óptico por derotación angular frente a maniobras de guiñada (*yaw*) agresivas (> 0.3 rad/s), superando el rango acotado del dataset preliminar (cap. 7, §7.4, §7.6).

- **Mitigación de la "maldición monocular" en pasajes densamente obstruidos (Anexo 7):** El fracaso uniforme de los tres brazos en `townsim_ini` (cap. 11, §11.4.2b) expuso un límite estructural del sensor monocular: el flujo óptico traslacional se anula exactamente en los obstáculos centrados en la trayectoria de avance (Foco de Expansión), que son los de mayor riesgo de colisión frontal ([Anexo 7](anexos/A7-MALDICION-MONOCULAR-ESTEREO.md), §A7.1–§A7.2). Como trabajo futuro de menor costo que un LiDAR emulado, se propone incorporar un segundo canal de profundidad instantánea mediante un **par estéreo** (baseline fija y conocida), que resuelve la ambigüedad de escala y elimina la dependencia del movimiento entre frames al recuperar profundidad métrica en un único instante ([Anexo 7](anexos/A7-MALDICION-MONOCULAR-ESTEREO.md), §A7.3–§A7.6). El SLAM monocular disperso o semi-denso queda como línea posterior y complementaria, con limitaciones propias frente a follaje en movimiento y geometría subpíxel.

- **Política de navegación por aprendizaje por refuerzo visual como cuarto brazo (`rl`) ([Anexo 8](anexos/A8-NAVEGACION-RL.md)):** Los tres brazos evaluados (`reactive`, `fsm`, `slm`) cubren el espacio de estrategias reactiva, basada en lógica explícita y basada en VLM pre-entrenado. Un cuarto brazo ortogonal a los tres anteriores es una **política neuronal entrenada por RL** que ocupa la misma capa táctica que `fsm_node` y `evasive_node`, manteniendo activa la capa deliberativa VLM en modo jerárquico. La hipótesis central es que una política especializada en el espacio de macro-acciones de este sistema (`MANTENER_RUMBO`, `EVADIR_*`, `GANAR_ALTURA`, `PERDER_ALTURA`, `FRENAR`) puede superar al brazo `reactive` en obstrucción densa —donde el flujo óptico colapsa— sin el overhead de latencia del brazo `slm` (~850–1400 ms vs. < 5 ms de inferencia neuronal). El [Anexo 8](anexos/A8-NAVEGACION-RL.md) desarrolla en detalle la jerarquía VLM → RL → PX4, el espacio de observación mixto `{rgb, ttc_field, nav}`, la función de recompensa con currículo, la justificación de PPO sobre SAC/DQN, la arquitectura CNN+FC propuesta y el protocolo de evaluación comparativa de los 4 brazos (K=5, 3 escenarios, 60 corridas). Su prerequisito es que el brazo `slm` tenga resultados estables.

- **Transferencia a hardware embebido y navegación en enjambre:**
  - Validación en plataforma física real: integración en una *companion computer* de bajo consumo (NVIDIA Jetson Nano / Orin) conectada vía MAVLink/ROS a un cuadrirrotor físico con sensor monocular, evaluando el lazo reactivo-táctico en entornos reales según las fases delineadas en el plan de trabajo aprobado.
  - Extensión a navegación cooperativa en enjambre y fusión sensorial con sensores
    complementarios (flujo óptico diferencial con sensores acústicos o ToF ultraligeros).
