# 6. Percepción monocular: flujo óptico, TTC, campo de obstáculos y profundidad estimada

La percepción usa una sola cámara RGB y tiene dos canales, uno por lazo de control (cap. 5, §5.1.2): el **flujo óptico** (§6.1–§6.13), que alimenta al lazo rápido cada 0.2 s, y la **profundidad monocular estimada** con Depth Anything V2 (§6.14), que alimenta al lazo lento y al barrido de resolución de atascos. §6.15 explica cómo se complementan.

## 6.1 Fundamentos de diseño: percepción geométrica sin redes neuronales en el lazo rápido

La percepción del lazo rápido prescinde deliberadamente de redes neuronales profundas de detección (detectores de cajas delimitadoras tipo YOLO — [Redmon et al., 2015](13-REFERENCIAS.md#ref-redmon-2015) — o segmentadores semánticos densos) y fundamenta la estimación de obstáculos en visión por computadora clásica: **flujo óptico denso derotado y divergencia del campo traslacional**. Esta decisión no es de conveniencia sino de principio, y se sustenta en tres argumentos de ingeniería robótica:

**1. Determinismo y presupuesto de cómputo compartido.** En una plataforma donde el cómputo se comparte con la simulación y con las redes del lazo lento, un estimador de flujo clásico (DIS en OpenCV) garantiza una latencia determinista y acotada por ciclo (5–10 Hz), sin los picos de inferencia asociados a redes convolucionales o transformadores visuales densos. [Shi et al. (2024)](13-REFERENCIAS.md#ref-shi-s-2024) y [Goel et al. (2021)](13-REFERENCIAS.md#ref-goel-2021) documentan este problema de presupuesto en sistemas embebidos de visión con requisitos de tiempo real; en este sistema el presupuesto disponible para percepción es del orden de 20–50 ms por ciclo.

**2. Generalización universal y robustez fuera de distribución.** Los detectores supervisados están limitados a las clases presentes en su conjunto de entrenamiento (automóviles, personas, señales). En un entorno urbano tridimensional, los obstáculos potenciales incluyen cables, salientes arquitectónicas, andamios o geometrías irregulares sin etiqueta semántica previa. El flujo óptico modela directamente el fenómeno **físico** de aproximación espacial mediante la expansión de textura en el plano focal: reacciona ante cualquier objeto que genere paralaje, sin importar su clase ni su apariencia ([Badrloo & Varshosaz, 2017](13-REFERENCIAS.md#ref-badrloo-2017); [Vera-Yanez et al., 2024](13-REFERENCIAS.md#ref-vera-yanez-2024)). Esta propiedad es especialmente valiosa en entornos de simulación que aún no reproducen fielmente la distribución fotométrica del mundo real (cap. 9).

**3. Modelado físico del Tiempo-a-Colisión (TTC).** Una caja delimitadora 2D no provee información cinemática de cierre ni distancia métrica directa. La divergencia del campo de flujo traslacional permite derivar matemáticamente el TTC ($TTC \approx d / v_{\text{cierre}}$) de forma continua a lo largo del plano de la imagen, entregando una señal temporal interpretable y calibrable para las decisiones de maniobra reactiva. El principio no es una invención de la robótica aérea: es la teoría del *tau* ($\tau$) de [Lee (1976)](13-REFERENCIAS.md#ref-lee-1976), que demostró que el tiempo-a-colisión puede leerse directamente de la tasa de expansión óptica de una superficie en el plano de la imagen, sin necesidad de recuperar distancia ni velocidad absolutas por separado. Esta derivación es una consecuencia directa de la ecuación del flujo óptico bajo traslación pura, instanciada en visión artificial aplicada a UAVs por [Al-Kaff et al. (2017)](13-REFERENCIAS.md#ref-al-kaff-2017) y [Vera-Yanez et al. (2024)](13-REFERENCIAS.md#ref-vera-yanez-2024).

**Limitación estructural y rol del lazo lento.** La elección de percepción clásica tiene un costo explícito: el flujo óptico requiere **traslación entre frames** para generar evidencia válida. En hover puro, giro puro o crucero muy lento, la señal traslacional colapsa a cero y el campo de obstáculos pierde toda confianza; lo mismo ocurre con un obstáculo centrado en el foco de expansión. El lazo lento mira un único fotograma y no necesita traslación. Se diseñó para un VLM; en la configuración final lo resuelve una red de profundidad monocular (§6.14), porque el VLM no distinguió sectores libres de bloqueados en el banco de prueba (cap. 11, §11.0). La arquitectura de dos canales —flujo rápido para lo inminente, profundidad estimada de un fotograma para decidir el rodeo— es el mecanismo con el que este trabajo aborda esa limitación.

*(Para el desarrollo matemático riguroso de la cámara pin-hole, las ecuaciones continuas de Longuet-Higgins, la deducción del FOE por mínimos cuadrados y la teoría de $\tau$ de Lee, véase el [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md)).*

## 6.2 Pipeline de percepción: cinco etapas

`FlowTTCEstimator.estimate()` (`src/perception/flow_ttc.py`) ejecuta cada ciclo cinco etapas en secuencia, produciendo un `ObstacleField` (`src/perception/obstacle_field.py`) listo para el router de política:

```
Frame(t-1) + Frame(t) + Telemetría(t-1, t)
    ↓
[1] Escala y conversión a escala de grises
    ↓
[2] Flujo óptico denso (DIS / Farneback)
    ↓
[3] Derotación por telemetría de actitud (IMU)
    ↓
[4] Estimación del FOE + RANSAC-lite de outliers
    ↓
[5] TTC por píxel + divergencia → agregación por celdas → ObstacleField
```

Si en cualquier etapa no hay evidencia suficiente (primer ciclo, modo degradado, rotación grande entre frames, flujo bajo el piso de ruido), la función retorna un `empty_field()` con `source="degraded"` o `"flow"` y `foe_confidence=0.0`, marcando explícitamente la ausencia de evidencia sin ningún clamp cosmético que la enmascare.

## 6.3 Etapa 1: escala y parámetros intrínsecos

Los fotogramas BGR de AirSim se convierten a escala de grises y se escalan a un ancho normalizado `FLOW_DOWNSCALE_WIDTH`: 640 px en `config/.env` (320 px es el valor por defecto del código y el que se usó en la validación de TTC del capítulo 7). El ancho se subió a 640 px el 28 de agosto de 2026 porque a 320 px los objetos finos, como las ramas, quedaban bajo el piso de ruido y el estimador devolvía confianza cercana a cero frente a un acercamiento real. Esta reducción sirve dos propósitos: reducir el costo de cómputo del estimador de flujo y suavizar el ruido de alta frecuencia que genera falsos vectores de flujo. La distancia focal se escala proporcionalmente:

$$f_x' = f_x \cdot \frac{W'}{W}, \quad f_y' = f_y \cdot \frac{W'}{W}$$

con `CAMERA_FX = CAMERA_FY = 554.0` px (cámara simétrica a la resolución de captura de AirSim) y el centro óptico $(c_x, c_y) = (W'/2, H'/2)$.

**Guard de rotación.** Antes de computar el flujo, el estimador verifica que la rotación máxima entre frames (pitch, yaw, roll) no exceda `FLOW_MAX_ROTATION_DEG` (default 2°). Durante maniobras activas (GIRAR_90, EVADIR) el yaw cambia 4–9°/ciclo a `LOOP_HZ=5` Hz. En esas condiciones, el modelo de derotación lineal de primer orden que se describe en §6.4 introduce errores de linealización que el estimador no puede compensar, y regiones de baja textura (cielo, fachadas uniformes) generan flujo esencialmente aleatorio. Sin este guard, cada giro produce «nubes» de falsos obstáculos. La solución conservadora es descartar el ciclo y retornar `empty_field(source="degraded")`: es mejor declarar incertidumbre que producir un falso positivo que cancele una maniobra en ejecución.

## 6.4 Etapa 2: flujo óptico denso (DIS)

El backend de flujo óptico es **DIS** (*Dense Inverse Search*, `cv2.DISOpticalFlow_create(PRESET_MEDIUM)`), con fallback a Farneback si DIS no está disponible. DIS produce un campo vectorial $\mathbf{v}(x,y) = (u, v)$ de desplazamientos en píxeles para cada posición del frame actual respecto al anterior.

**Por qué DIS y no Farneback.** DIS (*Dense Inverse Search*, Kroeger et al., 2016) ofrece una relación velocidad/calidad superior para flujo denso en imágenes de tamaño pequeño (≤ 320 px): su esquema de búsqueda inversa por parches es entre 5 y 10 veces más rápido que Farneback para resoluciones comparables, manteniendo la suavidad necesaria para la estimación del FOE. La propia implementación de OpenCV (`cv2.DISOpticalFlow`) usada en este trabajo es directamente la del algoritmo original de Kroeger et al. [Vera-Yanez et al. (2024)](13-REFERENCIAS.md#ref-vera-yanez-2024) y [Molineros et al. (2012)](13-REFERENCIAS.md#ref-molineros-2012) usan variantes de flujo óptico denso con esquemas de pirámide similares —Farneback en el primer caso—; la elección de DIS en este trabajo está motivada por el mismo compromiso latencia/densidad que documentan esos trabajos, resuelto a favor de la variante más rápida disponible en OpenCV.

El campo resultante $\mathbf{v}(x,y)$ mezcla el componente traslacional (paralaje de objetos en escena) con el componente rotacional inducido por los cambios de actitud del vehículo. Separar ambos componentes es el objetivo de la etapa siguiente.

## 6.5 Etapa 3: derotación analítica por telemetría IMU

La rotación propia del vehículo entre frames consecutivos genera un flujo óptico angular parásito $\mathbf{v}_{\text{rot}}$ que enmascara la expansión traslacional real. Para un modelo de cámara *pinhole* con rotación pequeña entre frames, la contribución rotacional al flujo óptico en el plano normalizado es:

$$u_{\text{rot}}(x,y) = \frac{\theta_x \cdot x \cdot y}{f_x} - \theta_y \left(f_x + \frac{x^2}{f_x}\right) + \theta_z \cdot y$$

$$v_{\text{rot}}(x,y) = \theta_x \left(f_y + \frac{y^2}{f_y}\right) - \frac{\theta_y \cdot x \cdot y}{f_y} - \theta_z \cdot x$$

donde $(x, y)$ son coordenadas en el plano de la imagen centradas en $(c_x, c_y)$, y $(\theta_x, \theta_y, \theta_z)$ son los incrementos de actitud (pitch, yaw, roll) entre frames, extraídos de la telemetría del IMU del simulador. El mapeo cámara-cuerpo asume alineación frontal: $\theta_x \approx \Delta\text{pitch}$, $\theta_y \approx \Delta\text{yaw}$, $\theta_z \approx \Delta\text{roll}$.

El campo traslacional derotado es:

$$\mathbf{v}_{\text{trans}} = \mathbf{v}_{\text{medido}} - \mathbf{v}_{\text{rot}}$$

La implementación (`_derotate()`) vectoriza esta operación sobre el array completo usando `np.mgrid` para construir los mapas de coordenadas $(x, y)$ en una sola operación, sin bucles por píxel. El salto de wrap-around del yaw ($\pm\pi$) se corrige con el módulo estándar antes de usar $\Delta\text{yaw}$ como $\theta_y$.

**Pre-integración de la velocidad angular del IMU (P1).** La telemetría incluye `imu_angular_velocity = {wx, wy, wz}` (rad/s, `getImuData()`), y cuando está presente el estimador usa `wz · Δt` como $\Delta\text{yaw}$ en lugar de la diferencia entre los ángulos de orientación de dos ciclos. La diferencia importa si la tasa de guiñada varía dentro del intervalo entre frames. En AirSim, cuyo IMU es ideal, ambos métodos son numéricamente equivalentes; el cambio deja el diseño preparado para hardware real, donde la velocidad angular medida por el giroscopio es la señal disponible.

Esta corrección es crítica para el sistema: sin ella, cada corrección de guiado (giro de unos pocos grados hacia el waypoint) genera un flujo rotacional en el sector central que se interpreta como un obstáculo frontal, disparando deliberaciones espurias en cada ciclo de crucero. El mismo principio de derotación por IMU se usa en sistemas de visión activa para vehículos terrestres ([Dickmanns, 2024](13-REFERENCIAS.md#ref-dickmanns-2024)) y SLAM monocular ([Chen et al., 2022](13-REFERENCIAS.md#ref-chen-w-2022)).

## 6.6 Etapa 4: estimación del Foco de Expansión (FOE) con RANSAC-lite

Bajo traslación pura (sin rotación residual), todos los vectores del campo traslacional apuntan radialmente desde un único punto llamado **Foco de Expansión** (FOE, también llamado punto de fuga traslacional). La posición del FOE en el plano de la imagen codifica la dirección de traslación del vehículo, y la magnitud del flujo en cada píxel es inversamente proporcional a la distancia al obstáculo que generó ese paralaje.

**Descarte de ruido de baja magnitud.** Los píxeles con $\|\mathbf{v}_{\text{trans}}\| \leq \text{FLOW\_NOISE\_FLOOR\_PX}$ (default 0.35 px) se descartan antes de cualquier ajuste. Por debajo de este umbral, los vectores de flujo son artefactos de cuantización del estimador, no señal real. Si la fracción de píxeles válidos resultante es menor que `MIN_VALID_FRACTION_FOR_FOE` (default 1%), el campo entero se declara sin evidencia.

**Ajuste por mínimos cuadrados ponderados (primera pasada).** Para los píxeles válidos, la condición geométrica de consistencia con el FOE es que cada vector de flujo $\mathbf{v}(p)$ esté **alineado** con la línea que une $p$ al FOE. La componente normal al vector $\mathbf{v}$ debe ser cero en el FOE: para el píxel $(p_x, p_y)$ con vector $(v_x, v_y)$, la normal normalizada es $\mathbf{n} = (-v_y, v_x) / |\mathbf{v}|$, y la condición es $\mathbf{n}^T (\text{FOE} - p) = 0$. El sistema lineal resultante es:

$$\left(\sum_i w_i \mathbf{n}_i \mathbf{n}_i^T\right) \text{FOE} = \sum_i w_i \mathbf{n}_i (\mathbf{n}_i^T p_i)$$

donde $w_i = |\mathbf{v}_i|$ pondera cada ecuación por la magnitud del flujo (vectores más largos son más confiables). Este sistema $2 \times 2$ se resuelve con `np.linalg.solve()`.

**Recorte de outliers tipo RANSAC-lite (segunda pasada).** El FOE de primera pasada puede estar contaminado por píxeles de fondo, regiones de baja textura, o residuos de la derotación. El refinamiento evalúa, para cada píxel, el ángulo entre su vector de flujo y la línea $p \to \text{FOE}$: si el ángulo supera `FOE_OUTLIER_ANGLE_RAD` (default 0.35 rad ≈ 20°), el píxel se descarta como outlier. Con los inliers restantes se repite el ajuste por mínimos cuadrados. Este esquema es una versión simplificada del RANSAC estocástico de [Kaneko et al. (2017)](13-REFERENCIAS.md#ref-kaneko-2017) y de la estimación robusta de FOE en flujo de egomotion documentada en la literatura de detección de obstáculos por flujo residual ([Molineros et al., 2012](13-REFERENCIAS.md#ref-molineros-2012)).

**Confianza del FOE.** Se distinguen dos casos:
- Pocos inliers (< 30): FOE poco confiable; `foe_confidence` se clipea a 0.3 como señal de evidencia degradada.
- Suficientes inliers (≥ 30): `foe_confidence = min(n_inliers / (H × W) × 3.0, 1.0)`. El factor 3.0 compensa que la fracción de inliers esperada en una escena real es aproximadamente 1/3 del total de píxeles válidos (fondo vs. objetos en aproximación); el boost normaliza la confianza a un rango comparable al de la fracción bruta.

**Sanity check de límites.** Un FOE fuera del rectángulo de la imagen (`0 ≤ foe_x ≤ W`, `0 ≤ foe_y ≤ H`) no es un punto de fuga físicamente plausible para esa imagen; indica que el ajuste convergió a una solución artefactual (ruido dominante o residuo de derotación mal compensada). En ese caso, `foe_confidence` se fuerza a 0.0 y el campo se retorna sin celdas bloqueadas.

## 6.7 Etapa 5: TTC por píxel y divergencia

Con el FOE estimado y el intervalo temporal real $\Delta t$ (diferencia de timestamps del simulador entre frames consecutivos — nunca el período nominal del lazo), se calcula para cada píxel válido:

$$TTC(x,y) = \frac{\|p - \text{FOE}\| \cdot \Delta t}{\|\mathbf{v}_{\text{trans}}(x,y)\|}$$

Esta fórmula es la forma discreta de la ecuación continua $TTC = Z / v_{\text{cierre}}$, válida bajo la aproximación de cámara *pinhole* con traslación dominante. Para píxeles cerca del FOE o con flujo muy pequeño, el denominador puede producir TTC extremadamente alto (sin evidencia de aproximación), lo que se traduce en $TTC \to \infty$.

**Canal de divergencia.** En paralelo al TTC, el estimador computa la divergencia del campo traslacional como verificación independiente:

$$\text{div}(x,y) = \frac{\partial u}{\partial x} + \frac{\partial v}{\partial y}$$

implementada con `np.gradient()` (diferencias de segundo orden centradas, normalizadas por el intervalo temporal $\Delta t$). La divergencia positiva indica expansión local del flujo — el objeto en ese punto del plano focal está acercándose al vehículo. Es un indicador complementario al TTC que no requiere estimar el FOE: incluso si el ajuste del FOE falla, una celda con divergencia positiva elevada sigue siendo evidencia de aproximación.

## 6.8 Grilla de celdas 3×3 y agregación por sector

El campo traslacional se divide en una grilla de 3 columnas (sectores: *izquierda*, *centro*, *derecha*) × 3 filas (bandas: *superior*, *medio*, *inferior*), totalizando 9 celdas. Las columnas dividen la imagen en tercios iguales de ancho; las filas, en tercios iguales de alto. Para cada celda se calcula:

**Confianza** (`confidence`): fracción de píxeles válidos (magnitud > piso de ruido) sobre el total de la celda, multiplicada por `foe_confidence`. Esta confianza combinada refleja tanto la densidad local de flujo válido como la calidad global del FOE estimado.

**TTC de celda** (`ttc_s`): percentil `TTC_AGGREGATION_PERCENTILE` (default 20) de la distribución de TTC finitos de la celda. El percentil 20 es conservador: estima el TTC del 20% más rápido de los objetos que se aproximan en la celda, resistente al ruido espurio que produce TTC extremadamente bajos en píxeles aislados. Celdas con menos de 5 píxeles válidos reciben `ttc_s = ∞` (sin evidencia).

**Ocupación** (`occupancy`): media de la divergencia positiva en la celda, escalada por el factor de calibración:

$$\text{occupancy} = \text{clip}\!\left(\bar{\text{div}}^+ \times \frac{0.450}{8.0},\ 0,\ 1\right)$$

El factor $0.450 / 8.0$ fue determinado empíricamente comparando las salidas del estimador con profundidad de referencia del simulador; no es un valor físicamente derivado sino el mejor punto de operación encontrado en las condiciones de vuelo de los escenarios de esta tesis. El protocolo de validación completo —conjunto de datos, curva ROC y la interpretación correcta de las métricas resultantes— se describe en el capítulo 7.

## 6.9 El predicado de bloqueo: fusión de dos canales

La decisión de si una celda está **bloqueada** fusiona los dos canales (ocupación y TTC) con una compuerta disyuntiva, condicionada a la confianza:

```python
def is_blocked(self) -> bool:
    if self.confidence < MIN_CONFIDENCE_FOR_BLOCKED:   # 0.15
        return False
    if self.occupancy >= OCCUPANCY_BLOCKED_THRESHOLD:  # 0.011 (calibrado, D2)
        return True
    return (
        self.confidence >= MIN_CONFIDENCE_FOR_TTC_BLOCKED  # 0.35
        and self.ttc_s <= TTC_BLOCKED_THRESHOLD_S          # 2.5 s
    )
```

La lógica es: una celda está bloqueada si tiene evidencia mínima de percepción **y** (la ocupación es alta, **o** el TTC es bajo con suficiente confianza).

**Calibración del umbral de ocupación (D2).** Un valor de umbral fijado a ojo (0.35) supone que la ocupación toma valores comparables a los del canal de TTC, y no es así. Un dataset de calibración (196 frames capturados en TownSim frente a una pared sólida, a cuatro velocidades de aproximación de 0.5 a 3 m/s; etiqueta de referencia binaria `gt_depth_centro < 5 m`, cap. 7 §7.1) muestra que la ocupación central nunca supera 0.082 en ese conjunto, de modo que con 0.35 la tasa de verdaderos positivos sería 0: el canal de ocupación quedaría, en la práctica, **desactivado** y el TTC cargaría solo con la detección. La curva ROC sobre `occ_centro` dio AUC = 0.87 y un umbral óptimo por [índice de Youden](13-REFERENCIAS.md#ref-youden-1950) de **0.011** (TPR = 0.93, FPR = 0.22), valor que adoptan `config/.env` y el default del código. Los números se recalcularon a partir del archivo del dataset; el detalle metodológico y sus límites se discuten en §7.5. Para atenuar la dependencia de la escena, `main.py` incorpora un `OccupancyCalibrator` que mide el ruido de ocupación del entorno actual en los primeros 25 ciclos válidos (`mean + 3σ`, acotado a [0.005, 0.05]) y reemplaza el umbral global; **el ejecutor de experimentos no lo usa**, de modo que las corridas en lote operan con el valor fijo de `config/.env`.

**Umbrales diferenciados de confianza.** La confianza mínima para que la ocupación vote bloqueo es `MIN_CONFIDENCE_FOR_BLOCKED = 0.15`, pero para que el TTC vote bloqueo por sí solo (sin apoyo de ocupación) se requiere `MIN_CONFIDENCE_FOR_TTC_BLOCKED = 0.35`. La razón es que el camino de "pocos inliers" en la estimación del FOE (§6.6) produce `foe_confidence = 0.3` como señal de evidencia degradada. Sin el umbral diferenciado, ese 0.3 superaba el piso general (0.15) y el TTC degradado votaba bloqueo con la misma autoridad que un FOE robusto. Con un único umbral, el TTC degradado votaría bloqueo con la misma autoridad que un FOE robusto y produciría falsos positivos.

## 6.10 La API pública de `ObstacleField`

Todos los consumidores del sistema de percepción — `navigate_node` (lazo rápido), `evasive_node`, `fsm_node`, el gobernador de velocidad de `motor_node` y `FlightLogger` — acceden al campo de obstáculos **únicamente** a través de esta interfaz. La capa estratégica **no** recibe el `ObstacleField`: mira el fotograma directamente (cap. 5, §5.10). Ningún módulo de control lee campos crudos de flujo ni coordenadas del FOE.

| Método | Descripción |
|---|---|
| `is_blocked(sector)` | `True` si alguna celda del sector está bloqueada según §6.9 |
| `sector_ttc(sector)` | Mínimo TTC del sector, sobre celdas con confianza ≥ 0.15 |
| `sector_occupancy(sector)` | Máxima ocupación del sector, sobre celdas con confianza ≥ 0.15 |
| `sector_confidence(sector)` | Máxima confianza del sector |
| `blocked_fraction()` | Fracción de celdas bloqueadas sobre el total de la grilla 3×3 |
| `min_ttc()` | TTC mínimo global, sobre todas las celdas con confianza suficiente |
| `has_evidence()` | `True` si `source == "flow"` y `foe_confidence > 0.0` |
| `summary_text()` | Texto compacto por sector para el overlay y el logging (`scene_summary`), p. ej. "CENTRO: BLOQUEADO (TTC=3.2s, fuente: flujo óptico)" |
| `to_dict()` | Representación serializable para el JSONL de auditoría |

El campo `source` del `ObstacleField` indica el origen de la evidencia: `"flow"` (solo flujo óptico), `"degraded"` (ciclo con rotación alta o sin flujo), `"holdover"` (campo del ciclo anterior por degradación temporal), `"none"` (sin datos). El gobernador de velocidad usa `source` para limitar el avance cuando no hay evidencia (cap. 5, §5.13).

El diseño como objeto inmutable (`@dataclass(frozen=True)`) garantiza que ningún consumidor pueda modificar el estado de percepción: los nodos solo pueden leer el campo, no escribirlo.

## 6.11 Consultas de nivel superior: `has_open_corridor` y `sector_towards_waypoint`

Dos funciones de módulo sirven como interfaz de alto nivel. Solo la FSM las usa (`has_open_corridor`, para decidir si un atasco tiene un corredor visible); el brazo `slm` detecta el atasco con el `StallDetector` (cap. 5, §5.3.1).

**`sector_towards_waypoint(bearing_err_deg)`** mapea el error de rumbo al waypoint activo a uno de los tres sectores visuales:
- Si `bearing_err_deg < -BEARING_SECTOR_DEG` (default 15°) → `"izquierda"`
- Si `bearing_err_deg > +15°` → `"derecha"`
- Caso contrario → `"centro"`

Esta función conecta el espacio de guiado de `WaypointTracker` con el espacio de percepción del `ObstacleField`, permitiendo que el escape de atasco priorice el sector hacia el waypoint.

**`has_open_corridor(field, guidance)`** determina si la percepción tiene evidencia real de al menos un sector transitable, evaluado en el contexto del waypoint activo:

```python
if not field.has_evidence():
    return False          # sin flujo ≠ "despejado"
for sector in (target, otros_sectores):
    if confidence(sector) >= MIN_CONFIDENCE y not is_blocked(sector):
        return True
return False
```

La condición `has_evidence()` es crítica: un hover puro produce un `ObstacleField` con `foe_confidence = 0`, y tratar esa situación como "camino despejado" desactivaría el escape de atasco precisamente cuando el dron está parado y atrapado. Esta función fue introducida después de documentar un vuelo donde el dron subió 12 m consecutivos mientras el `ObstacleField` reportaba `DERECHA: DESPEJADO` ciclo tras ciclo: tratar la falta de evidencia como corredor libre lleva a decisiones de escape sin fundamento perceptual.

## 6.12 Comportamiento bajo condiciones extremas

**Hover / velocidad < 0.25 m/s.** Sin traslación entre frames, el flujo traslacional es indistinguible del ruido del estimador. La fracción de píxeles válidos cae por debajo de `MIN_VALID_FRACTION_FOR_FOE = 1%` y el campo retorna vacío (`foe_confidence = 0`). `has_evidence()` devuelve `False`, marcando la situación como "sin información" — no como "despejado". La consecuencia es doble: el gobernador de velocidad limita el avance tras varios ciclos sin evidencia (cap. 5, §5.13), y la capa estratégica, que mira el fotograma con la profundidad estimada y no el campo, sigue juzgando la escena (§6.14).

**Giro puro (yaw_rate alto).** La rotación excede `FLOW_MAX_ROTATION_DEG = 2°` y el ciclo retorna `empty_field(source="degraded")`. El lazo continúa con la maniobra comprometida (continuación de la maniobra comprometida en `navigate`) sin recurrir a nueva evidencia perceptual. La inhibición se verificó empíricamente (D3, §7.6): con guiñadas comandadas de 0.3 a 1.0 rad/s (18.7–63.9 °/s reales) el 100 % de los 200 frames ensayados quedó en `source = "degraded"` con `foe_confidence = 0`.

**Holdover temporal del TTC (P2).** Cuando un frame aislado devuelve `foe_confidence = 0` (guiñada, textura baja), `FlowTTCEstimator` no vacía el campo de inmediato: devuelve el último campo válido con el TTC decrementado en el tiempo transcurrido (`ObstacleField.decay_ttc()`, copia inmutable con `source = "holdover"`) durante hasta `FLOW_HOLDOVER_MAX_FRAMES = 3` frames (0.6 s a 5 Hz). Superado ese límite el estimador vuelve al campo vacío, de modo que la memoria del obstáculo nunca se prolonga indefinidamente y el origen queda auditable en los logs.

**Supresión activa de guiñada cerca de obstáculos (P3).** En lugar de solo inhibir el estimador cuando el giro ya ocurrió, el nodo reactivo limita la guiñada del guiado a `FLOW_MAX_YAW_DPS_NEAR_OBSTACLE = 5 °/s` mientras el TTC del sector central esté por debajo del umbral de bloqueo (`safe_yaw_rate()`), un valor dentro del rango en que la derotación opera (≈ 10 °/s a 5 Hz). No aplica a `GIRAR_90` ni a `EVADIR_*`, cuya guiñada es intencional.

**Textura baja o uniformidad fotométrica.** En regiones sin gradiente (cielo, fachadas, superficies sin textura), `np.gradient` produce valores de flujo cercanos a cero que no contribuyen a la estimación del FOE ni al cómputo de TTC. La confianza de esas celdas es cercana a cero y el predicado `is_blocked()` las descarta.

**Transiciones de iluminación brusca.** Cambios rápidos de exposición entre frames (que pueden ocurrir en el simulador al cruzar una sombra) producen flujo sistemático en toda la imagen que puede contaminar el FOE. El recorte de outliers (§6.6) mitiga esto parcialmente; la calibración de `FLOW_MAX_ROTATION_DEG` y el piso de ruido `FLOW_NOISE_FLOOR_PX` son los otros mecanismos de contención.

## 6.13 Variables de entorno calibrables

El estimador expone todos sus parámetros clave a través de variables de entorno (versionadas en `config/.env`):

| Variable | Default | Descripción |
|---|---|---|
| `FLOW_ALGORITHM` | `"dis"` | Backend de flujo: `"dis"` o `"farneback"` |
| `FLOW_DOWNSCALE_WIDTH` | 320 (código) · **640** (`config/.env`) | Ancho de trabajo para flujo óptico (px) |
| `CAMERA_FX` / `CAMERA_FY` | 554.0 | Distancia focal a resolución de captura (px) |
| `FLOW_NOISE_FLOOR_PX` | 0.35 | Piso de ruido: vectores más pequeños se descartan |
| `MIN_VALID_FRACTION_FOR_FOE` | 0.01 | Fracción mínima de píxeles válidos para estimar FOE |
| `FOE_OUTLIER_ANGLE_RAD` | 0.35 | Umbral de ángulo para RANSAC-lite (rad, ≈ 20°) |
| `TTC_AGGREGATION_PERCENTILE` | 20 | Percentil de TTC usado como estimado por celda |
| `FLOW_MAX_ROTATION_DEG` | 2.0 | Rotación máxima (°) para la que la derotación es confiable |
| `OBSTACLE_OCCUPANCY_BLOCKED` | 0.011 | Umbral de ocupación para declarar celda bloqueada (calibrado por ROC/Youden, §6.9 y §7.5) |
| `FLOW_HOLDOVER_MAX_FRAMES` | 3 | Frames máximos de holdover del TTC ante un frame sin evidencia (P2) |
| `FLOW_MAX_YAW_DPS_NEAR_OBSTACLE` | 5.0 | Tope de guiñada (°/s) del guiado cerca de un obstáculo (P3) |
| `OBSTACLE_TTC_BLOCKED_S` | 2.5 | Umbral de TTC para declarar celda bloqueada (s) |
| `OBSTACLE_MIN_CONFIDENCE` | 0.15 | Confianza mínima para que ocupación vote bloqueo |
| `OBSTACLE_MIN_CONFIDENCE_TTC` | 0.35 | Confianza mínima para que TTC vote bloqueo solo |

## 6.14 Profundidad monocular estimada: Depth Anything V2

### 6.14.1 Qué es y por qué se incorporó

**Depth Anything V2** ([Yang et al., 2024](13-REFERENCIAS.md#ref-yang-2024); artículo: <https://arxiv.org/abs/2406.09414>; código y modelos: <https://github.com/DepthAnything/Depth-Anything-V2>) es una familia de modelos fundacionales de estimación de profundidad monocular: a partir de **una sola imagen RGB** predicen la profundidad de cada píxel. Su receta de entrenamiento tiene tres pasos: un modelo maestro grande se entrena solo con imágenes sintéticas, cuya profundidad es exacta; ese maestro etiqueta un conjunto grande de imágenes reales sin anotar (pseudo-etiquetas), y los modelos de producción, más chicos, se entrenan sobre esas pseudo-etiquetas. El codificador de todas las variantes es un Vision Transformer de DINOv2 con una cabeza de predicción densa (DPT). Las variantes **métricas** se ajustan sobre datos sintéticos con escala conocida y devuelven la profundidad **en metros**, no en una escala relativa. Este trabajo usa `Depth-Anything-V2-Metric-Outdoor-Small` (`DEPTH_MODEL`): la variante para exteriores con el codificador más chico, de ~25 M de parámetros, distribuida en Hugging Face y cargada con la biblioteca `transformers`.

La incorporación respondió a una medición, no a una preferencia. El lazo lento hace una pregunta de **distancia**: si se puede volar 15 m en la dirección de cada sector. En el banco de prueba a bordo (cap. 11, §11.0) se midieron, contra la misma etiqueta de referencia, tres formas de responderla con el mismo fotograma (`experiments/vlm_bench/seg_depth_probe.py`; 625 muestras × 9 sectores, 61 % de sectores abiertos):

| Señal | Exactitud balanceada [IC 95 %] | AUC | Latencia |
|---|---|---:|---:|
| **Depth Anything V2 Metric Outdoor Small: p5 estimado por sector** | **75 % [72–77 %]** | **0.83** | 82 ms |
| Segmentación semántica (`yolo26n-sem`): 1 − fracción de obstáculo | 45 % [42–47 %] | 0.50 | 32 ms |
| VLM de vuelo (LFM2.5-VL-1.6B), grilla 3×3 | 53 % [50–55 %] | 0.53 | 880 ms |

La profundidad estimada es la única que supera el criterio del banco (exactitud ≥ 65 % con el intervalo por encima del azar). Separa sin error los casos obvios (AUC 1.00) y, por fila de la grilla, logra AUC 0.97 arriba, 0.80 a la altura del dron y 0.78 abajo. La segmentación no sirve para esta pregunta porque una clase no dice la distancia: «edificio» incluye uno a 100 m. En los barridos reales (290 imágenes, sector central) la profundidad separa rumbos abiertos de cerrados con AUC 0.87 y exactitud balanceada del 75 % [68–82 %], mientras que el VLM declaró transitables todos los rumbos de los 14 barridos del banco. Sus errores son conservadores: solo el 2 % de los sectores que marca libres tienen un obstáculo a menos de 5 m.

La lectura es que el espacio libre es una pregunta de geometría, que resuelve una red chica entrenada para estimar distancia y no un modelo de lenguaje generalista (cap. 12, §12.2).

### 6.14.2 Del fotograma a la decisión

`DepthEstimator` (`src/perception/depth_estimator.py`) procesa el fotograma crudo del ciclo, el mismo que usa el flujo óptico:

1. **Estimación.** Convierte el fotograma de BGR a RGB, lo pasa por el procesador de la red (que lo reescala a su resolución de trabajo), corre la red en la GPU sin gradientes e interpola la salida al tamaño original: una matriz de profundidades en metros, una por píxel.
2. **Recorte y grilla.** Toma el recorte cuadrado central —el mismo que recibía el VLM, ±33.7° en un fotograma de 3:2 con 90° de campo horizontal— y lo divide en una grilla de 3×3 por tercios: columnas A, B, C y filas 1 (arriba), 2 (altura del dron) y 3 (abajo).
3. **Resumen por sector.** Calcula el **percentil 5** de la profundidad de cada sector (`sector_p5`): lo más cercano del sector sin que lo decidan píxeles sueltos. Es exactamente el estadístico con el que se construyen las etiquetas de referencia del banco (cap. 7, §7.1), de modo que la exactitud medida allí es la del juicio que usa el vuelo.
4. **Umbral.** Un sector es `libre` si su p5 es ≥ `DEPTH_FREE_M` (15 m, la misma distancia a la que se fija la sub-meta) y `bloqueado` si no.

El servicio (`src/agents/depth_client.py`) devuelve **la misma estructura que devolvía el VLM**, de modo que el resto del sistema no distingue la fuente:

- **Capa estratégica:** `{"sectores": {"A1": "libre", …, "C3": "bloqueado"}}`. La traducción a una sub-meta en coordenadas del mundo, anclada a la pose del fotograma, es la de cap. 5 §5.10.3.
- **Barrido de resolución de atascos:** por cada uno de los cuatro rumbos, `{"img": i, "view": "open" | "wall", "free": …}`, transitable si el p5 del sector central `B2` —hacia donde volaría el dron en línea recta— es ≥ 15 m (cap. 5 §5.12).

La respuesta cruda que queda en la auditoría es el p5 de cada sector en metros (`{"p5_m": [...]}`), de modo que cada decisión se puede revisar contra la distancia que la produjo (cap. 4 §4.4).

### 6.14.3 Dónde corre y cuánto cuesta

La red **nunca corre dentro del lazo de 5 Hz**: corre en el hilo de un `DeliberationService` (cap. 5, §5.10.5) y el lazo solo deposita pedidos y recoge resultados. Costo medido con la GPU compartida con Unreal Engine:

| Recurso | Valor |
|---|---|
| Latencia por fotograma | 82–94 ms en el banco; mediana 108–114 ms en vuelo (cap. 11 §11.6) |
| VRAM adicional | ~440 MiB |
| Carga inicial | ~19 s al compilar el grafo; el servicio precarga la red con un fotograma vacío para que la primera consulta en vuelo no la pague |
| Período de consulta | `DEPTH_STRATEGIC_PERIOD_S` = 1 s en la capa estratégica (con el VLM era 3 s); un pedido con cuatro imágenes por barrido |

Una consulta de profundidad tarda la mitad de un ciclo del lazo, y el VLM local, ~0.8 s. Por eso la profundidad no reemplaza al flujo en el lazo rápido: el flujo detecta un cierre en milisegundos y en CPU, y la profundidad decide, cada segundo, hacia dónde está el espacio libre.

### 6.14.4 Qué no es: la exclusión del sensor de profundidad

La red **no lee el canal de profundidad del simulador**: recibe el mismo fotograma RGB que el flujo óptico, como lo haría una red a bordo de un dron que solo tiene una cámara. El canal de profundidad de AirSim sigue fuera del lazo (cap. 5, §5.16): de él salen las etiquetas de referencia, y si alimentara al sistema evaluado, las mediciones dejarían de ser independientes. La guardia `tests/test_no_depth_in_flight_path.py` declara los dos módulos de la red como consumidores legítimos del RGB y verifica que ningún módulo de vuelo acceda al canal del simulador.

### 6.14.5 Limitaciones

- **Dominio.** Depth Anything V2 se entrenó en parte con imágenes sintéticas, y la etiqueta del banco sale del mismo render que la red ve. En una cámara real el desempeño puede ser menor; la validación en imágenes reales está pendiente.
- **Escala métrica.** La variante para exteriores se ajustó con datos de conducción, a la altura de un auto. Las distancias absolutas a 10–30 m de altura no están calibradas: el umbral de 15 m funciona como corte de clasificación validado en el banco, no como una medición en metros.
- **Objetos finos y follaje.** Ramas, cables y copas semitransparentes son el caso más difícil para cualquier estimador denso. En el corredor arbolado de TownSim la capa con profundidad mantuvo al dron más lejos del follaje (cap. 11, §11.6.2), pero no eliminó los acercamientos.
- **Sin memoria.** Cada consulta juzga un fotograma aislado, sin fusión temporal ni mapa.
- **Campo de visión.** Solo se analiza el recorte central; lo que queda a los costados del fotograma no participa del juicio.
- **Un primer intento descartado.** En septiembre una integración anterior de la misma red se usó como freno del lazo rápido, con otro estadístico; quedó desactivada (`legacy/depth_estimator_v2.py`). La versión actual se adoptó recién cuando la pregunta, el estadístico y el umbral se validaron contra etiquetas de referencia.

## 6.15 Complementariedad entre flujo óptico y profundidad estimada

El diseño asume que ningún canal de percepción es completo por sí solo. Hay dos canales, uno por lazo de control (cap. 5, §5.1.2):

**Flujo óptico (lazo rápido).** Fuerte cuando el dron se traslada a velocidad moderada (> 0.5 m/s), con textura suficiente e iluminación estable: produce bloqueos en < 5 ms, a tiempo para evadir. Es ciego en hover y giro puro, ante texturas uniformes y, por construcción, ante obstáculos centrados en el FOE y superficies horizontales que no se expanden en el sector frontal.

**Profundidad estimada (lazo lento).** Mira un único fotograma y no necesita traslación: ve el obstáculo centrado en el FOE, la escena en hover y, gracias a las filas de la grilla, una estructura horizontal a la altura del dron. Tarda ~0.1 s, demasiado para lo inminente pero suficiente para decidir el rodeo de un edificio cada segundo, que es lo que el flujo no puede decidir. Con `STRATEGIC_SOURCE = vlm`, el mismo lugar lo ocupa el VLM, con una pregunta igual y la misma salida, pero sin capacidad medida de responderla (cap. 11, §11.0).

**La interfaz entre canales es geométrica, no textual.** Cada canal produce su salida en su propio dominio: el flujo, bloqueos por sector para el lazo rápido; la profundidad, sub-metas en coordenadas del mundo que el guiado persigue. Ninguno recibe la salida del otro, de modo que no hay que reconciliar dos descripciones de la misma escena con latencias distintas.

---

*Las referencias bibliográficas citadas en este capítulo corresponden a las entradas del §13 del presente informe. La evaluación cuantitativa del estimador de flujo (curvas ROC, AUC, comparación con profundidad de referencia) se desarrolla en el capítulo 7; la de la profundidad estimada, en el capítulo 11 (§11.0). El análisis de los modos de falla de la percepción y su impacto en el comportamiento del lazo se presenta en el capítulo 9.*
