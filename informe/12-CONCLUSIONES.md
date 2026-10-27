# 12. Conclusiones

## 12.1 Retomar el hilo conductor

Este trabajo partió de una constatación práctica: en un sistema de control donde un modelo de lenguaje visivo consume descripciones de escena para deliberar sobre maniobras de evasión, el error más caro no está en la política de decisión del modelo sino en la interfaz que lo alimenta.

La evidencia de esa afirmación —desincronización de esquemas de percepción, campos nulos por calibración de escala diferencial, descarte silencioso en grafos de estado— nunca emergió observando el comportamiento superficial del vuelo; emergió auditando formalmente los contratos de datos y la propagación de estado entre capas (cap. 9).

El sistema que resulta de ese proceso se evaluó con dos instrumentos. El banco de prueba a bordo (cap. 11, §11.0) midió, contra etiquetas de referencia, qué preguntas sabe responder cada fuente del lazo lento, y fijó la configuración que vuela: la capa estratégica y el barrido de atascos responden con profundidad monocular estimada, y el VLM queda fuera del lazo de vuelo, en el plan de ruta previo al despegue. La corrida productiva v4 (cap. 11, §11.1–§11.7) evaluó esa configuración en seis escenarios, con 10 semillas por celda y 210 corridas, y permite responder con datos a la pregunta de investigación.

**Alcance de la evidencia.** La comparación entre brazos tiene un sesgo conocido: el análisis de las corridas encontró dos defectos de implementación del brazo FSM —un deadlock falso al terminar el despegue y un techo de altitud que convierte sus escapes verticales en giros por encima de 30 m— que lo hacen más lento y lo exponen a más fallas (cap. 11, §11.5). Las conclusiones frente a `reactive` no están afectadas; las conclusiones frente a la FSM favorecen a `slm` en una medida que estos datos no permiten estimar.

---

## 12.2 Respuesta a la pregunta de investigación

**¿Aporta el brazo deliberativo (`slm`) sobre la máquina de estados (`fsm`) y sobre el control puramente reactivo (`reactive`) en navegación autónoma de dron en entornos urbanos simulados?**

La respuesta depende del escenario y del brazo contra el que se compara.

### En ruta libre: solo costo (H2 sostenida)

En los tres escenarios de control `slm` completa 29 de 30 misiones y `reactive` las 30, sin colisiones (la FSM, 25), y `slm` mantiene la misma distancia a las estructuras que `reactive`. No gana seguridad ni éxito; cuesta tiempo. Las nueve comparaciones de tiempo son significativas tras Bonferroni, con separación completa o casi, y el orden es el mismo en los tres tiers: `reactive` < `slm` < `fsm`.

| Escenario | Ruta | $t_{\text{slm}}/t_{\text{reactive}}$ | $t_{\text{slm}} - t_{\text{reactive}}$ |
|---|---|---|---|
| `minisim_clear` (Tier 0) | ~180 m | 1.95 | 80 s |
| `citysim_clear` (Tier 2) | ~420 m | 1.49 | 94 s |
| `townsim_clear` (Tier 1) | ~640 m | 1.39 | 107 s |

La razón decrece con la longitud de la ruta y la diferencia absoluta crece mucho menos que la ruta: el costo de la arquitectura se comporta como un término aproximadamente aditivo, que es lo que predice H2. El costo no lo pone la inferencia: la capa estratégica corre en su propio hilo, responde en ~110 ms y el dron no frena a esperarla. Lo ponen lo que la capa hace con la respuesta y el gobernador de velocidad: en el plano vacío de MiniSim, el 27 % de las consultas proponen una sub-meta que desvía al dron, y el gobernador limita el avance en el 27–43 % de los ciclos de `slm`, frente al 7–18 % de `reactive`. Reducir el costo de la arquitectura en ruta libre es, por tanto, un problema de cuándo desviar y cuándo frenar, no de acelerar el modelo.

### Con obstrucción: la evasión con profundidad decide; la capa estratégica, sin demostrar

**Frente al control reactivo, la diferencia es binaria.** En el corredor arbolado de `townsim_ini` y en el bloqueo frontal de `townsim_calib_cruce_frontal`, `reactive` no completa ninguna de sus 20 corridas: queda trabado frente al follaje o la fachada hasta el tope de tiempo. Los brazos con evasión y barrido completan entre 5 y 9 de cada 10. Ese es el resultado más firme del trabajo, y es el que sostiene H3: el signo del efecto de la deliberación cambia con el escenario, de costo puro en ruta libre a condición necesaria donde la ruta directa se tranca.

**Frente a la FSM, la ventaja de `slm` existe pero no se puede atribuir.** `slm:depth` supera en SPL a `fsm:depth` en `townsim_ini` (δ = +0.81) y a las dos FSM en `citysim_pilot` (δ = +1.00), las tres comparaciones significativas tras Bonferroni; en el bloqueo frontal no hay diferencia y `slm` pierde la mitad de sus corridas, contra 1 de 10 de la FSM sin barrido. Tres razones impiden leer esas ventajas como un aporte de la capa estratégica:

- **Los defectos de la FSM** (§12.1) la hacen más lenta en toda la ruta, y en `townsim_ini` la ventaja de `slm` está repartida a lo largo del recorrido, incluido el retorno a cielo abierto, en lugar de concentrarse en el follaje como se esperaba.
- **En `citysim_pilot` el plan de ruta resuelve el bloqueo antes del vuelo**, para las cuatro celdas: hasta `reactive` completa las 10 corridas. La comparación mide qué tan bien cada brazo sigue una ruta que ya evita el obstáculo.
- **El bloqueo frontal**, el escenario donde se esperaba el beneficio más claro de rodear en lugar de subir, es justamente donde `slm` no muestra ventaja.

La capa estratégica sí discrimina: declara el camino directo libre en dos tercios a tres cuartos de las consultas y propone sub-metas en el resto. Pero no se midió si esas sub-metas acercan al waypoint real, de modo que su contribución al avance queda sin establecer.

### El VLM

Medido contra etiquetas de referencia, el VLM de 1.6 B no separa sectores volables de bloqueados (AUC 0.53) ni rumbos abiertos de cerrados en el barrido; una red de profundidad monocular de ~25 M de parámetros sí lo hace (AUC 0.83–0.87), en 82 ms en el banco y ~110–135 ms en vuelo (cap. 11, §11.0 y §11.4). Por eso el VLM no vuela. Su único aporte medible está fuera del lazo: el plan de ruta sobre el mapa cenital (AUC 0.81), donde la pregunta es de reconocimiento de calles y techos, no de distancia. En `citysim_pilot` ese plan basta para que el control reactivo complete una misión de rodeo de manzanas; en `citysim_clear`, sobre una ruta ya libre, elige un desvío bloqueado, y por eso los escenarios de control vuelan sin plan.

### Síntesis

**En ruta libre la capa deliberativa solo cuesta**: entre 1.4 y 2 veces el tiempo del control reactivo, sin ganar éxito ni seguridad. **Donde la ruta directa se tranca, evadir con profundidad estimada y resolver los atascos con un barrido es lo que permite completar la misión**, cosa que el control reactivo no logra. **La ventaja de la capa estratégica sobre una máquina de estados no está demostrada**: las diferencias a favor de `slm` existen, pero la implementación de la FSM evaluada tiene defectos que las inflan. Un VLM pequeño no aporta en el lazo de vuelo; aporta como planificador de ruta sobre un mapa registrado.

---

## 12.3 Limitaciones

- **Defectos del brazo FSM:** el deadlock falso al despegar y el escape agotado por el techo de 30 m (cap. 11, §11.5) afectan las seis comparaciones `slm`–`fsm` y las comparaciones entre las dos FSM. Las conclusiones frente a la FSM son, por eso, cotas favorables a `slm`.

- **Plan de ruta común en `citysim_pilot`:** el plan rodea el único tramo bloqueado antes del vuelo, de modo que el lote más difícil no ejerce la resolución de la obstrucción en vuelo. Los puntos de paso del plan toman la altitud del waypoint de destino, por lo que un desvío en un tramo que desciende baja al comienzo y no a lo largo del tramo (cap. 4, §4.3.1).

- **Un escenario por tipo:** cada nivel de dificultad está representado por una ruta concreta. Un efecto observado es una propiedad de esa geometría hasta que se replique en otra ruta del mismo tipo, y la progresión de H2 entre tiers es descriptiva.

- **Tamaño de muestra:** con K = 10 una separación completa supera la corrección de Bonferroni para 18 comparaciones (α ≈ 0.0028), pero una separación parcial no: la comparación `slm:depth`–`fsm:blind` en `townsim_ini` (δ = +0.73, p = 0.0039) es un efecto grande no detectado con esta potencia, no un efecto ausente.

- **Contribución de la capa estratégica sin medir:** no se midió el avance hacia el waypoint real tras cada sub-meta (cap. 10, §10.6.3). Sus umbrales (período, edad máxima de 10 s, sub-meta a 15 m como máximo, cambio de altitud de 4 m como máximo, deduplicación de 10 m, radio sin consultas alrededor del waypoint, grilla de 3×3) son decisiones de diseño, no valores calibrados.

- **Seguridad medida sin contacto:** no hubo colisiones registradas en ninguna corrida, pero DistMin cae a ~0.1–0.25 m en todos los brazos con evasión de los escenarios con vegetación y fachadas, y las fallas son abortos por quedar apoyado en la geometría. El valor de ~0.10 m que se repite probablemente es el plano cercano de la cámara de auditoría, sin verificación en video; la seguridad informada es la ausencia de colisión, no un margen medido.

- **Capacidad de discriminación del VLM no demostrada:** el banco de prueba con el modelo a bordo (cap. 11, §11.0) muestra que LFM2.5-VL-1.6B no distingue sectores volables de bloqueados en el render de CitySim: ninguna de las ocho preguntas evaluadas supera el criterio, la grilla de vuelo queda en 53 % de exactitud balanceada y el barrido declara transitables todos los rumbos. Por eso la configuración final responde la misma pregunta con la profundidad estimada (cap. 5, §5.10.7), y el VLM queda en la planificación de ruta.

- **Componentes del lazo rápido sin evaluar por separado:** la evasión por flujo, `GIRAR_90`, el gobernador de velocidad, la detección de techo y la reacción a contacto forman parte del sistema por ser comunes a los tres brazos, no por evidencia de beneficio. El gobernador, en particular, explica buena parte del costo de `slm` en ruta libre y no tiene una celda que lo aísle.

- **Latencia del VLM solo fuera de vuelo:** con la configuración final el VLM no corre en vuelo; su latencia (0.34–0.88 s por pregunta y 2.6–3.1 s por barrido en el banco, en la misma GPU que Unreal) solo importa para la ablación con `STRATEGIC_SOURCE = vlm`.

- **Validación exclusivamente en simulación (AirSim):** sin validación en hardware físico (Jetson Nano + dron real), que el plan de trabajo aprobado (`plan_tesis/plan-tesis.md`, §"Transferencia de los resultados obtenidos") sitúa como siguiente etapa fuera del alcance de este trabajo.

- **Sensor monocular (parcialmente mitigado):** el canal de flujo óptico depende del movimiento del vehículo entre frames, lo que lo hace estructuralmente ciego a obstáculos centrados en la trayectoria (Foco de Expansión) y a las superficies horizontales a la altura de vuelo (cap. 9, §9.8.7). En el lazo lento lo complementa la profundidad monocular estimada (Depth Anything V2, [Yang et al., 2024](13-REFERENCIAS.md#ref-yang-2024); cap. 6, §6.14), que juzga un fotograma aislado y no necesita traslación. Sus límites: se entrenó en parte con datos sintéticos y se evaluó sobre el mismo render (en cámara real puede rendir menos), su escala métrica no está calibrada a la altura de vuelo y el follaje sigue siendo el caso difícil: en `townsim_ini` el dron completa la misión pero pasa a ~0.1 m de las copas. La validación en imágenes reales queda pendiente (Anexo 7).

- **Calibración del canal de ocupación de `ObstacleField` parcial:** el canal de TTC está formalmente validado contra etiquetas de referencia tomadas de la profundidad del simulador (cap. 7). El umbral de ocupación se calibró por ROC/Youden (`OBSTACLE_OCCUPANCY_BLOCKED = 0.011`, AUC = 0.87) con 196 frames, una sola escena y 29 positivos (cap. 7, §7.5). La validación cruzada en otras escenas y el efecto del `OccupancyCalibrator` adaptativo siguen sin evaluarse.

- **Un único mapa por escenario:** cada escenario de obstrucción se corrió en un solo mapa urbano (TownSim o CitySim). La generalización de los resultados a otras geometrías urbanas no está garantizada con los datos disponibles.

- **VLM fijo (LFM2.5-VL-1.6B, `lfm2.5-vl-1.6b:q4km-ctx8k`, zero-shot):** el modelo opera en régimen zero-shot sin sintonización al dominio de vuelo. Los resultados de deliberación están acotados por la distribución de preentrenamiento del modelo y el diseño del prompt, no por la capacidad máxima de la arquitectura.

---

## 12.4 Trabajo futuro y mejoras

Las líneas de continuidad y optimización derivadas de este trabajo se estructuran en los ejes siguientes, integrando la validación del sistema, la arquitectura de la capa deliberativa, la infraestructura perceptual y la transferencia física:

- **Validación del sistema:** la continuación más directa de este trabajo, porque condiciona la lectura de la comparación con la FSM. (i) Corregir los dos defectos del brazo FSM —no contar progreso durante el despegue y revisar el techo de escape en rutas que vuelan por encima de 30 m— y repetir las comparaciones `slm`–`fsm`. (ii) Medir el avance hacia el waypoint real tras cada sub-meta de la capa estratégica en los tres escenarios con obstrucción (cap. 10, §10.6.3). (iii) Agregar una celda que aísle el gobernador de velocidad, que explica buena parte del costo de `slm` en ruta libre. (iv) Correr un escenario de rodeo sin plan de ruta, para que la obstrucción se resuelva en vuelo. (v) Que los puntos de paso del plan de ruta conserven la altitud más alta del tramo hasta llegar al destino. (vi) Incorporar un test de contrato que recorra `src/agents/` y falle ante cualquier clave de estado no declarada en `DroneState`.

- **Especialización y adaptación ligera del modelo deliberativo vía LoRA/QLoRA (Anexo 3):** En la implementación evaluada, el modelo multimodal (**LFM2.5-VL-1.6B**, `lfm2.5-vl-1.6b:q4km-ctx8k`) opera en régimen *zero-shot*. El prompt ya es mínimo (una imagen con la grilla y una respuesta de nueve valores sin texto libre) y la latencia local es de ~0.8 s (cap. 8, §8.6), de modo que el margen de LoRA está en la **calidad** de la respuesta: que el modelo distinga sectores libres de bloqueados, lo que hoy no hace (AUC 0.53, cap. 11 §11.0). Como se fundamenta en el capítulo 8 (§8.8) y se desarrolla en detalle en el [Anexo 3](anexos/A3-OPTIMIZACION-LORA.md), la sintonización fina de bajo rango (*Low-Rank Adaptation*, LoRA / QLoRA / DoRA) quedó excluida del alcance inmediato por escasez de diversidad en el dataset de maniobras y para evitar riesgos de sobreajuste a geometrías urbanas particulares. Como trabajo futuro, se proyecta entrenar adaptadores sobre las matrices de atención ($W_q, W_v$) y proyecciones MLP del LLM (manteniendo congelado el codificador visual ViT). Un conjunto de entrenamiento natural son los fotogramas que la propia capa estratégica registra (cap. 5, §5.10.4), etiquetados con la profundidad del simulador en forma offline —sin que esa señal entre nunca al lazo de vuelo—; la corrida v4 deja más de 7500 consultas de los escenarios con obstrucción.

- **Decodificación restringida con gramáticas reducidas y dinámicas condicionadas por el grafo (Anexo 4):** El [Anexo 4](anexos/A4-DECODIFICACION-RESTRINGIDA.md), §A4.4.2, especifica una optimización pensada para un modelo que elige macro-acciones: la **inyección dinámica de gramáticas acotadas según el estado de vuelo y el motivo de consulta**. En el sistema descrito el modelo no emite acciones (sus esquemas describen sectores o imágenes, §8.2), por lo que la idea se traslada a restringir **qué describe** según el contexto (por ejemplo, omitir los sectores que el lazo rápido ya sabe bloqueados). La propuesta, como referencia:
  - Ante colisiones inminentes (`"TTC_CRITICO"`), restringir la gramática estrictamente a `["evasive", "girar_90"]`, podando sintácticamente cualquier token asociado a acciones pasivas.
  - Ante atascos cinemáticos (`"DEADLOCK_ESCAPE"`), forzar alternativas de escape `["girar_90", "fsm", "degraded"]`, impidiendo bucles de evasión redundantes.
  - Esta poda semántica *a priori* concentrará la distribución de probabilidad en alternativas físicamente coherentes, reducirá la entropía de muestreo y acelerará la decodificación aprovechando el salto de tokens (*token fast-forwarding*).

- **Perfeccionamiento del lazo perceptual monocular (Anexo 5):**
  - Validación cruzada del umbral de ocupación (ya calibrado por ROC/Youden sobre una escena, cap. 7, §7.5) en CitySim y en escenas con vegetación, con un dataset mayor que 29 positivos y evaluación del `OccupancyCalibrator` adaptativo, hoy ausente del runner de lotes ([Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md)).
  - Completar la validación de la derotación angular: la *inhibición* del estimador ante guiñadas de 0.3–1.0 rad/s está verificada (cap. 7, §7.6), pero falta caracterizar el error de TTC en el rango previo al guard (0–0.3 rad/s), la reanudación de la estimación al cesar el giro y el comportamiento con IMU real.

- **Mitigación de la "maldición monocular" en pasajes densamente obstruidos (Anexo 7):** El control reactivo, que depende solo del flujo óptico, no atraviesa el corredor arbolado de `townsim_ini` en ninguna corrida, y los brazos que sí lo atraviesan con profundidad estimada pasan a ~0.1 m de las copas (cap. 11, §11.4). El flujo óptico traslacional se anula exactamente en los obstáculos centrados en la trayectoria de avance (Foco de Expansión), que son los de mayor riesgo de colisión frontal ([Anexo 7](anexos/A7-MALDICION-MONOCULAR-ESTEREO.md), §A7.1–§A7.2). Como trabajo futuro de menor costo que un LiDAR emulado, se propone incorporar un segundo canal de profundidad instantánea mediante un **par estéreo** (baseline fija y conocida), que resuelve la ambigüedad de escala y elimina la dependencia del movimiento entre frames al recuperar profundidad métrica en un único instante ([Anexo 7](anexos/A7-MALDICION-MONOCULAR-ESTEREO.md), §A7.3–§A7.6). El SLAM monocular disperso o semi-denso queda como línea posterior y complementaria, con limitaciones propias frente a follaje en movimiento y geometría subpíxel.

- **Política de navegación por aprendizaje por refuerzo visual como cuarto brazo (`rl`) ([Anexo 8](anexos/A8-NAVEGACION-RL.md)):** Los tres brazos evaluados (`reactive`, `fsm`, `slm`) cubren el espacio de estrategias reactiva, basada en lógica explícita y basada en una capa estratégica sobre profundidad estimada. Un cuarto brazo ortogonal a los tres anteriores es una **política neuronal entrenada por RL** que ocupa la misma capa táctica que `fsm_node` y `evasive_node`. La hipótesis central es que una política especializada en el espacio de macro-acciones de este sistema (`MANTENER_RUMBO`, `EVADIR_*`, `GANAR_ALTURA`, `PERDER_ALTURA`, `FRENAR`) puede superar al brazo `reactive` en obstrucción densa —donde el flujo óptico colapsa— con una inferencia de < 5 ms (estimado). El [Anexo 8](anexos/A8-NAVEGACION-RL.md) desarrolla en detalle la jerarquía planificador → RL → PX4, el espacio de observación mixto `{rgb, ttc_field, nav}`, la función de recompensa con currículo, la justificación de PPO sobre SAC/DQN, la arquitectura CNN+FC propuesta y el protocolo de evaluación comparativa de los 4 brazos. Su prerequisito es corregir los defectos de la FSM, para que la comparación entre brazos sea limpia.

- **Modelos de mundo latentes (LeWorldModel) como complemento o alternativa parcial al SLM ([Anexo 9](anexos/A9-MODELOS-DE-MUNDO-LATENTES-EDGE.md)):** En marzo de 2026 se presentó LeWorldModel ([Maes et al., 2026](13-REFERENCIAS.md#ref-maes-2026)), un modelo de mundo de tipo JEPA de ~15 M de parámetros que aprende la dinámica del entorno de extremo a extremo desde píxeles y planifica en su espacio latente con tiempos del orden de un segundo, frente a los 1.6 B parámetros del VLM empleado en esta tesis. El Anexo 9 analiza qué aportaría y qué perdería el sistema con este tipo de modelo (predicción de consecuencias de acciones continuas frente a la semántica y el razonamiento global del VLM), estima analíticamente su viabilidad en una *companion computer* Jetson Nano / Orin Nano —memoria holgada, latencia condicionada al presupuesto de muestreo de la planificación— y concluye que, con la evidencia actual (resultados en tareas 2D/3D simples, sin validación en visión monocular urbana aérea), no corresponde reemplazar al brazo `slm` sino **complementarlo** como verificador de consecuencias y detector de sorpresa, o usarlo como simulador latente para entrenar el brazo `rl` del Anexo 8. Las cifras de latencia del anexo son estimaciones; su reemplazo por mediciones en hardware edge y el protocolo de evaluación en lazo cerrado (§A9.7) constituyen el trabajo futuro concreto.

- **Transferencia a hardware embebido y navegación en enjambre:**
  - Validación en plataforma física real: integración en una *companion computer* de bajo consumo (NVIDIA Jetson Nano / Orin) conectada vía MAVLink/ROS a un cuadrirrotor físico con sensor monocular, evaluando el lazo reactivo-táctico en entornos reales según las fases delineadas en el plan de trabajo aprobado.
  - Extensión a navegación cooperativa en enjambre y fusión sensorial con sensores complementarios (flujo óptico diferencial con sensores acústicos o ToF ultraligeros).
