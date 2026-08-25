# 6. Percepción monocular sin redes neuronales

## 6.1 Fundamentos de diseño: percepción geométrica y física de aproximación

La arquitectura de percepción a bordo implementada en este trabajo prescinde deliberadamente de redes neuronales profundas de detección (como detectores de cajas delimitadoras o segmentadores semánticos) y fundamenta la estimación de obstáculos en visión por computadora clásica: **flujo óptico denso derotado y divergencia del campo traslacional**. Esta decisión se sustenta en tres principios de ingeniería robótica:

1. **Determinismo y presupuesto de cómputo en tiempo real:** En una plataforma de navegación autónoma donde los recursos de cómputo (GPU/CPU) deben compartirse con la inferencia de un modelo de lenguaje local (SLM), los algoritmos de visión clásica optimizados (`cv2.DISOpticalFlow`) garantizan una latencia determinista y acotada por ciclo (5–10 Hz), eliminando los cuellos de botella de inferencia asociados a redes convolucionales o transformadores visuales densos.
2. **Generalización universal y robustez fuera de distribución (OOD):** Los detectores de objetos supervisados están limitados a las clases semánticas presentes en sus conjuntos de entrenamiento (automóviles, personas, señales). En un entorno urbano tridimensional complejo, los obstáculos potenciales incluyen cables, salientes arquitectónicas, andamios o geometrías irregulares sin etiqueta previa. El flujo óptico modela directamente el fenómeno físico de aproximación espacial mediante la expansión de textura en el plano focal, reaccionando ante cualquier objeto que represente un riesgo de colisión sin importar su clase semántica ni su apariencia.
3. **Modelado físico de Tiempo-a-Colisión (TTC):** Una caja delimitadora 2D no provee información cinemática de cierre ni distancia métrica directa. En contraste, la divergencia del campo de flujo traslacional permite derivar matemáticamente el Tiempo-a-Colisión ($TTC \approx Z / v_z$) de forma continua a lo largo del plano de la imagen, entregando una señal temporal interpretable y calibrable para las decisiones de maniobra reactiva.

## 6.2 Flujo óptico, derotación y divergencia como señal de ocupación

La percepción del sistema produce en cada ciclo un objeto de estado unificado denominado `ObstacleField` (`src/perception/obstacle_field.py`), generado por el estimador de flujo y TTC (`FlowTTCEstimator`, `src/perception/flow_ttc.py`). Los componentes del grafo de control consumen este estado exclusivamente a través de su API pública (`is_blocked`, `blocked_fraction`, `sector_ttc`, `summary_text`, `to_dict`), aislando la lógica de control de los cálculos numéricos de bajo nivel.

El campo espacial se organiza en una grilla de 3×3 celdas (tres sectores horizontales: *izquierda*, *centro*, *derecha*; por tres bandas verticales: *superior*, *medio*, *inferior*). Para cada celda se computan cuatro magnitudes principales:
- **Ocupación (`occupancy` $\in [0, 1]$):** Nivel de actividad de divergencia positiva en la celda.
- **Tiempo-a-Colisión (`ttc_s` en segundos):** Estimación de tiempo para el impacto ($+\infty$ si no hay aproximación).
- **Divergencia traslacional (`divergence` en $1/s$):** Tasa de expansión del flujo traslacional.
- **Confianza (`confidence` $\in [0, 1]$):** Proporción de píxeles válidos con gradiente suficiente en la celda.

El procesamiento por ciclo ejecuta las siguientes etapas:

1. **Flujo óptico denso:** Cálculo del vector de desplazamiento entre fotogramas consecutivos escalados a una resolución normalizada (`FLOW_DOWNSCALE_WIDTH`), empleando el algoritmo variacional DIS (*Dense Inverse Search*).
2. **Derotación analítica por telemetría de actitud:** La rotación propia del vehículo (cambios de *roll*, *pitch* y *yaw* registrados por la IMU entre fotogramas) genera un flujo óptico angular parásito que enmascara la aproximación real. El estimador proyecta analíticamente la velocidad angular sobre el plano focal y resta este componente del flujo total medido:
   $$\mathbf{v}_{\text{trans}} = \mathbf{v}_{\text{medido}} - \mathbf{v}_{\text{rot}}(\Delta\phi, \Delta\theta, \Delta\psi)$$
   Esta corrección garantiza que giros puros de guiñada o cabeceos de estabilización no generen falsas alarmas de colisión frontal.
3. **Estimación del Foco de Expansión (FOE):** Localización del punto de fuga del vector de traslación mediante mínimos cuadrados ponderados con eliminación recursiva de valores atípicos (*outliers*). Si el dron se encuentra en estacionario (*hover*) o movimiento lateral puro, el FOE se marca como indefinido y el TTC se asigna a $+\infty$.
4. **Cálculo de TTC por celda:** Para cada píxel válido $p$, se calcula $TTC(p) = \frac{\|p - \mathbf{FOE}\| \cdot \Delta t}{\|\mathbf{v}_{\text{trans}}(p)\|}$. La agregación a nivel de celda toma el percentil 20 de la distribución interna, proporcionando una estimación conservadora y resistente al ruido espurio.

## 6.3 El canal de ocupación y calibración de escala

La divergencia del campo traslacional ($\nabla \cdot \mathbf{v}_{\text{trans}}$) se evalúa en `src/perception/flow_ttc.py` mediante operadores diferenciales sobre las componentes horizontal y vertical del flujo. En la implementación de referencia, la ocupación se deriva escalando la divergencia positiva (`occupancy = clip(divergencia × 0.5, 0, 1)`).

El predicado de bloqueo por celda `Cell.is_blocked()` integra de forma complementaria ambos canales de percepción mediante una compuerta lógica disyuntiva:
$$\text{is\_blocked} = (\text{occupancy} \ge \tau_{\text{occ}}) \lor (\text{ttc\_s} \le \tau_{\text{ttc}})$$
donde $\tau_{\text{ttc}} = 3.2\,\text{s}$ corresponde al umbral óptimo calibrado frente a profundidad de referencia (capítulo 7) y $\tau_{\text{occ}}$ es el umbral de ocupación (`OBSTACLE_OCCUPANCY_BLOCKED`). La calibración formal de este operador y su escala frente a datos de profundidad constituye un punto de análisis metodológico relevante (capítulo 7 y 9).

## 6.4 Métrica de bloqueo global: `blocked_fraction()`

Para la toma de decisiones a nivel macro en el grafo de navegación, `ObstacleField.blocked_fraction()` computa la proporción de celdas bloqueadas sobre el total de la grilla 3×3. 

Cuando esta fracción supera el umbral crítico de bloqueo generalizado, el sistema determina que la trayectoria frontal se encuentra completamente comprometida en todos sus sectores, transfiriendo el control al nodo determinista `girar_90` para efectuar una maniobra de escape ortogonal inmediata sin incurrir en latencias de deliberación innecesarias.
