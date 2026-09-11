# 6. Percepción monocular: flujo óptico, TTC y campo de obstáculos

## 6.1 Fundamentos de diseño: percepción geométrica sin redes neuronales

La arquitectura de percepción a bordo implementada en este trabajo prescinde deliberadamente de redes neuronales profundas de detección (detectores de cajas delimitadoras tipo YOLO — Redmon et al., 2015 — o segmentadores semánticos densos) y fundamenta la estimación de obstáculos en visión por computadora clásica: **flujo óptico denso derotado y divergencia del campo traslacional**. Esta decisión no es de conveniencia sino de principio, y se sustenta en tres argumentos de ingeniería robótica:

**1. Determinismo y presupuesto de cómputo compartido.** En una plataforma donde los recursos de CPU deben compartirse con la inferencia de un modelo de lenguaje local (SLM/VLM), un estimador de flujo clásico (DIS en OpenCV) garantiza una latencia determinista y acotada por ciclo (5–10 Hz), sin los picos de inferencia asociados a redes convolucionales o transformadores visuales densos. [Shi et al. (2024)](13-REFERENCIAS.md#ref-shi-s-2024) y [Goel et al. (2021)](13-REFERENCIAS.md#ref-goel-2021) documentan este problema de presupuesto en sistemas embebidos de visión con requisitos de tiempo real; en este sistema el presupuesto disponible para percepción es del orden de 20–50 ms por ciclo.

**2. Generalización universal y robustez fuera de distribución.** Los detectores supervisados están limitados a las clases presentes en su conjunto de entrenamiento (automóviles, personas, señales). En un entorno urbano tridimensional, los obstáculos potenciales incluyen cables, salientes arquitectónicas, andamios o geometrías irregulares sin etiqueta semántica previa. El flujo óptico modela directamente el fenómeno **físico** de aproximación espacial mediante la expansión de textura en el plano focal: reacciona ante cualquier objeto que genere paralaje, sin importar su clase ni su apariencia ([Badrloo & Varshosaz, 2017](13-REFERENCIAS.md#ref-badrloo-2017); [Vera-Yanez et al., 2024](13-REFERENCIAS.md#ref-vera-yanez-2024)). Esta propiedad es especialmente valiosa en entornos de simulación que aún no reproducen fielmente la distribución fotométrica del mundo real (cap. 9).

**3. Modelado físico del Tiempo-a-Colisión (TTC).** Una caja delimitadora 2D no provee información cinemática de cierre ni distancia métrica directa. La divergencia del campo de flujo traslacional permite derivar matemáticamente el TTC ($TTC \approx d / v_{\text{cierre}}$) de forma continua a lo largo del plano de la imagen, entregando una señal temporal interpretable y calibrable para las decisiones de maniobra reactiva. El principio no es una invención de la robótica aérea: es la teoría del *tau* ($\tau$) de [Lee (1976)](13-REFERENCIAS.md#ref-lee-1976), que demostró que el tiempo-a-colisión puede leerse directamente de la tasa de expansión óptica de una superficie en el plano de la imagen, sin necesidad de recuperar distancia ni velocidad absolutas por separado. Esta derivación es una consecuencia directa de la ecuación del flujo óptico bajo traslación pura, instanciada en visión artificial aplicada a UAVs por [Al-Kaff et al. (2017)](13-REFERENCIAS.md#ref-al-kaff-2017) y [Vera-Yanez et al. (2024)](13-REFERENCIAS.md#ref-vera-yanez-2024).

**Limitación estructural y rol del VLM.** La elección de percepción clásica tiene un costo explícito: el flujo óptico requiere **traslación entre frames** para generar evidencia válida. En hover puro, giro puro o crucero muy lento, la señal traslacional colapsa a cero y el campo de obstáculos pierde toda confianza. Este punto ciego estructural es exactamente el que el VLM deliberativo (cap. 5) está diseñado para cubrir: cuando el `ObstacleField` reporta "sin evidencia", el modelo de lenguaje toma decisiones con contexto visual e histórico que el estimador de flujo no puede proveer. La arquitectura de dos capas — percepción geométrica rápida + deliberación semántica lenta — es el mecanismo central con el que este trabajo aborda esa limitación.

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

Los fotogramas BGR de AirSim se convierten a escala de grises y se escalan a un ancho normalizado `FLOW_DOWNSCALE_WIDTH` (default 320 px). Esta reducción sirve dos propósitos: reducir el costo de cómputo del estimador de flujo y suavizar el ruido de alta frecuencia que genera falsos vectores de flujo. La distancia focal se escala proporcionalmente:

$$f_x' = f_x \cdot \frac{W'}{W}, \quad f_y' = f_y \cdot \frac{W'}{W}$$

con `CAMERA_FX = CAMERA_FY = 554.0` px (cámara simétrica a la resolución de captura de AirSim) y el centro óptico $(c_x, c_y) = (W'/2, H'/2)$.

**Guard de rotación.** Antes de computar el flujo, el estimador verifica que la rotación máxima entre frames (pitch, yaw, roll) no exceda `FLOW_MAX_ROTATION_DEG` (default 2°). Durante maniobras activas (GIRAR_90, EVADIR) el yaw cambia 4–9°/ciclo a `LOOP_HZ=5` Hz. En esas condiciones, el modelo de derotación lineal de primer orden que se describe en §6.4 introduce errores de linealización que el estimador no puede compensar, y regiones de baja textura (cielo, fachadas uniformes) generan flujo esencialmente aleatorio. El resultado documentado antes de implementar este guard fueron "nubes" de falsos obstáculos durante cada giro (CHANGELOG.md 2026-0826). La solución conservadora es descartar el ciclo y retornar `empty_field(source="degraded")`: es mejor declarar incertidumbre que producir un falso positivo que cancele una maniobra en ejecución.

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
    if self.occupancy >= OCCUPANCY_BLOCKED_THRESHOLD:  # 0.35
        return True
    return (
        self.confidence >= MIN_CONFIDENCE_FOR_TTC_BLOCKED  # 0.35
        and self.ttc_s <= TTC_BLOCKED_THRESHOLD_S          # 2.5 s
    )
```

La lógica es: una celda está bloqueada si tiene evidencia mínima de percepción **y** (la ocupación es alta, **o** el TTC es bajo con suficiente confianza).

**Umbrales diferenciados de confianza.** La confianza mínima para que la ocupación vote bloqueo es `MIN_CONFIDENCE_FOR_BLOCKED = 0.15`, pero para que el TTC vote bloqueo por sí solo (sin apoyo de ocupación) se requiere `MIN_CONFIDENCE_FOR_TTC_BLOCKED = 0.35`. La razón es que el camino de "pocos inliers" en la estimación del FOE (§6.6) produce `foe_confidence = 0.3` como señal de evidencia degradada. Sin el umbral diferenciado, ese 0.3 superaba el piso general (0.15) y el TTC degradado votaba bloqueo con la misma autoridad que un FOE robusto. La separación entre ambos umbrales fue el fix directo de una fuente documentada de falsos positivos (CHANGELOG.md 2026-0826).

## 6.10 La API pública de `ObstacleField`

Todos los consumidores del sistema de percepción — `policy_router`, `evasive_node`, `deliberative_node`, `fsm_node`, `FlightLogger` — acceden al campo de obstáculos **únicamente** a través de esta interfaz. Ningún módulo de control lee campos crudos de flujo ni coordenadas del FOE.

| Método | Descripción |
|---|---|
| `is_blocked(sector)` | `True` si alguna celda del sector está bloqueada según §6.9 |
| `sector_ttc(sector)` | Mínimo TTC del sector, sobre celdas con confianza ≥ 0.15 |
| `sector_occupancy(sector)` | Máxima ocupación del sector, sobre celdas con confianza ≥ 0.15 |
| `sector_confidence(sector)` | Máxima confianza del sector |
| `blocked_fraction()` | Fracción de celdas bloqueadas sobre el total de la grilla 3×3 |
| `min_ttc()` | TTC mínimo global, sobre todas las celdas con confianza suficiente |
| `has_evidence()` | `True` si `source == "flow"` y `foe_confidence > 0.0` |
| `summary_text()` | Texto compacto para el prompt del VLM (§4.3): "CENTRO: BLOQUEADO (TTC=3.2s, fuente: flujo óptico + profundidad monocular)" |
| `merge_depth_estimate(depth_m, cmd_vx)` | Inyecta una estimación de profundidad monocular en el sector centro: las tres celdas quedan con `occupancy` sobre el umbral de bloqueo, `ttc_s = depth_m / cmd_vx` y `source = "flow+depth"` (V4/A1) |
| `to_dict()` | Representación serializable para el JSONL de auditoría |

El campo `source` del `ObstacleField` indica el origen de la evidencia: `"flow"` (solo flujo óptico), `"flow+depth"` (flujo + Depth Anything V2 Metric), `"degraded"` (ciclo con rotación alta o sin flujo), `"holdover"` (campo del ciclo anterior por degradación temporal), `"none"` (sin datos). Este campo es visible en `summary_text()` y llega al SLM en el prompt, permitiéndole calibrar su confianza según las fuentes que confirmaron el obstáculo (B1).

El diseño como objeto inmutable (`@dataclass(frozen=True)`) garantiza que ningún consumidor pueda modificar el estado de percepción: los nodos solo pueden leer el campo, no escribirlo. La excepción es `merge_depth_estimate()`, que retorna un **nuevo** `ObstacleField` con el sector centro modificado — el campo original no se altera.

## 6.10b Segundo canal perceptual: Depth Anything V2 Metric (V4)

El estimador de flujo óptico tiene un punto ciego estructural ante obstáculos centrados en la trayectoria (cerca del FOE): la divergencia traslacional de esos píxeles es mínima precisamente porque están en el eje de aproximación. Para cubrir ese punto ciego, el sistema incorpora un segundo canal de profundidad **completamente independiente del sensor de profundidad del simulador**: un estimador de profundidad monocular basado en el modelo **Depth Anything V2 Metric** (`src/perception/depth_estimator.py`).

**Principio.** La entrada es únicamente el frame RGB del ciclo actual — el mismo frame que ya captura `capture_node`, sin ninguna llamada adicional a AirSim. El modelo de red neuronal infiere un mapa de profundidad métrico (en metros) del frame. Esta distinción arquitectural es crucial: no es el canal `DepthPlanar` de AirSim (ground truth del simulador, disponible solo en simulación), sino un estimado inferido de una imagen monocular, idéntico a lo que haría un sistema real con un drone sin LiDAR.

**Hilo background.** `DepthEstimator` corre en un hilo daemon independiente para no bloquear el lazo de control a 5 Hz. `perception_node` llama a `depth_estimator.request(frame)` (no bloqueante) y `depth_estimator.poll()` para obtener el resultado más reciente y su edad en ms. Si el resultado tiene más de `DEPTH_MAX_AGE_MS = 3000 ms`, se descarta.

**Trigger condicional.** La inferencia solo se solicita cuando: (a) el drone avanza (`cmd_vx >= 0.30 m/s`), (b) el flujo óptico reporta corredor libre (`blocked_fraction < 0.25`), y (c) la ruta del ciclo anterior no es `"evasive"` (no relanzar inferencia durante maniobras activas). La condición (b) es la más importante: cuando el flujo óptico ve obstáculos (`blocked_fraction > 0.25`), ya tiene control; Depth Anything V2 solo se activa en el caso específico donde el flujo dice "libre" pero el drone no avanza.

**Guarda V4b — anti-falso-positivo.** El mapa de profundidad de Depth Anything V2 sobre renders sintéticos de Unreal Engine puede generar falsos positivos aislados (el modelo fue entrenado sobre imágenes del mundo real y el dominio simulado introduce artefactos). Para filtrarlos, la señal solo se inyecta en el `ObstacleField` cuando `depth_m < DEPTH_BRAKE_M = 5.0 m` durante ≥ `DEPTH_BELOW_THRESHOLD = 2` ciclos consecutivos (`_depth_below_cycles`). Un solo frame con profundidad baja no activa la señal.

**Clasificación por textura (E2).** `DepthEstimator.poll()` retorna también un tipo de obstáculo estimado por análisis del mapa de profundidad del sector frontal:
- `"follaje"`: CV (std/mean) > 0.55 **o** fracción de píxeles con profundidad > 3× el percentil-5 > 0.30. El follaje tiene huecos que ven objetos lejanos; el CV es alto.
- `"superficie plana"`: CV < 0.55 y low far_fraction. La pared produce un mapa de profundidad uniforme.

Esta clasificación se añade al `scene_summary` como pista táctica para el SLM (`"follaje: evasión diagonal o +1 m"` vs. `"superficie plana: evasión lateral amplia"`), mejorando la especificidad de la decisión sin modificar el routing.

**Integración con el `ObstacleField` (A1).** Cuando la señal V4 está activa, la profundidad no crea un path de routing separado: se inyecta vía `merge_depth_estimate()` en el campo existente. El resultado es que el router, el SLM y todos los consumidores downstream ven un único `ObstacleField` coherente con `source = "flow+depth"`. No hay condiciones `if depth_available` dispersas en el código de navegación.

## 6.11 Consultas de nivel superior: `has_open_corridor` y `sector_towards_waypoint`

Dos funciones de módulo sirven como interfaz de alto nivel compartida entre el router de política, el nodo deliberativo y la FSM:

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

La condición `has_evidence()` es crítica: un hover puro produce un `ObstacleField` con `foe_confidence = 0`, y tratar esa situación como "camino despejado" desactivaría el escape de atasco precisamente cuando el dron está parado y atrapado. Esta función fue introducida después de documentar un vuelo donde el dron subió 12 m consecutivos mientras el `ObstacleField` reportaba `DERECHA: DESPEJADO` ciclo tras ciclo — el router cortocircuitaba hacia `GANAR_ALTURA` antes de leer el campo (CHANGELOG.md 2026-0824).

## 6.12 Comportamiento bajo condiciones extremas

**Hover / velocidad < 0.25 m/s.** Sin traslación entre frames, el flujo traslacional es indistinguible del ruido del estimador. La fracción de píxeles válidos cae por debajo de `MIN_VALID_FRACTION_FOR_FOE = 1%` y el campo retorna vacío (`foe_confidence = 0`). `has_evidence()` devuelve `False`, marcando la situación como "sin información" — no como "despejado". El nodo deliberativo lo detecta vía `_query_reason_note()` y comunica explícitamente al VLM que la consulta se debe a falta de evidencia, no a un bloqueo real (§4.3, §5.10).

**Giro puro (yaw_rate alto).** La rotación excede `FLOW_MAX_ROTATION_DEG = 2°` y el ciclo retorna `empty_field(source="degraded")`. El lazo continúa con la maniobra comprometida (persistencia en `evasive_node`) sin recurrir a nueva evidencia perceptual.

**Textura baja o uniformidad fotométrica.** En regiones sin gradiente (cielo, fachadas, superficies sin textura), `np.gradient` produce valores de flujo cercanos a cero que no contribuyen a la estimación del FOE ni al cómputo de TTC. La confianza de esas celdas es cercana a cero y el predicado `is_blocked()` las descarta.

**Transiciones de iluminación brusca.** Cambios rápidos de exposición entre frames (que pueden ocurrir en el simulador al cruzar una sombra) producen flujo sistemático en toda la imagen que puede contaminar el FOE. El recorte de outliers (§6.6) mitiga esto parcialmente; la calibración de `FLOW_MAX_ROTATION_DEG` y el piso de ruido `FLOW_NOISE_FLOOR_PX` son los otros mecanismos de contención.

## 6.13 Variables de entorno calibrables

El estimador expone todos sus parámetros clave a través de variables de entorno (versionadas en `config/.env`):

| Variable | Default | Descripción |
|---|---|---|
| `FLOW_ALGORITHM` | `"dis"` | Backend de flujo: `"dis"` o `"farneback"` |
| `FLOW_DOWNSCALE_WIDTH` | 320 | Ancho de trabajo para flujo óptico (px) |
| `CAMERA_FX` / `CAMERA_FY` | 554.0 | Distancia focal a resolución de captura (px) |
| `FLOW_NOISE_FLOOR_PX` | 0.35 | Piso de ruido: vectores más pequeños se descartan |
| `MIN_VALID_FRACTION_FOR_FOE` | 0.01 | Fracción mínima de píxeles válidos para estimar FOE |
| `FOE_OUTLIER_ANGLE_RAD` | 0.35 | Umbral de ángulo para RANSAC-lite (rad, ≈ 20°) |
| `TTC_AGGREGATION_PERCENTILE` | 20 | Percentil de TTC usado como estimado por celda |
| `FLOW_MAX_ROTATION_DEG` | 2.0 | Rotación máxima (°) para la que la derotación es confiable |
| `OBSTACLE_OCCUPANCY_BLOCKED` | 0.35 | Umbral de ocupación para declarar celda bloqueada |
| `OBSTACLE_TTC_BLOCKED_S` | 2.5 | Umbral de TTC para declarar celda bloqueada (s) |
| `OBSTACLE_MIN_CONFIDENCE` | 0.15 | Confianza mínima para que ocupación vote bloqueo |
| `OBSTACLE_MIN_CONFIDENCE_TTC` | 0.35 | Confianza mínima para que TTC vote bloqueo solo |

## 6.14 Complementariedad entre los tres canales de percepción

El diseño del sistema asume explícitamente que ningún canal de percepción es completo por sí solo. La arquitectura emplea tres capas con dominios de confiabilidad complementarios:

**Flujo óptico (canal primario)** es fuerte cuando el dron se traslada a velocidad moderada (> 0.5 m/s), la textura es suficiente y la iluminación es estable. Produce `ObstacleField` con `foe_confidence > 0.35` y bloqueos confiables en < 5 ms sin consultar el VLM ni el estimador de profundidad.

**Depth Anything V2 Metric (canal secundario, V4)** actúa en el punto ciego estructural del flujo óptico: obstáculos centrados en la trayectoria (cerca del FOE) que generan divergencia nula o muy baja. Solo se activa cuando el flujo dice "libre" pero el drone no avanza — exactamente el escenario donde el flujo óptico más falla. Agrega información de profundidad sin costo de sensor adicional (entrada solo RGB). Sus limitaciones: latencia de inferencia (↑ algunas decenas de ms, cubierta por el hilo background), posibles falsos positivos en renders sintéticos (mitigados por la guarda V4b de N ciclos consecutivos), y dependencia de la distribución del modelo preentrenado.

**VLM (capa deliberativa)** cubre los casos donde ambos canales geométricos fallan: hover puro, giro puro, atasco crónico donde el flujo y la profundidad han colapsado, o cuando se necesita razonamiento semántico global (distinguir una calle libre de una fachada con ventanas, elegir el corredor en una intersección). Recibe el fotograma directamente junto con el resumen del `ObstacleField` (que puede llevar `source = "flow+depth"` si el canal V4 aportó evidencia) y la historia de trayectoria acumulada.

**La interfaz entre capas** es el `scene_summary` del `ObstacleField` y el motivo de consulta del prompt: cuando hay evidencia geométrica, el VLM la recibe como contexto cuantitativo con su fuente indicada (`"CENTRO: BLOQUEADO, TTC=3.2s, fuente: flujo óptico + profundidad monocular"`); cuando no la hay, el prompt lo dice explícitamente. Esta transparencia sobre fuente y calidad de la evidencia es el mecanismo que permite al modelo calibrar su respuesta según el nivel de confianza del canal perceptual.

---

*Las referencias bibliográficas citadas en este capítulo corresponden a las entradas del §13 del presente informe. La evaluación cuantitativa del estimador (curvas ROC, AUC, comparación con profundidad de referencia) se desarrolla en el capítulo 7. El análisis de los modos de falla de la percepción y su impacto en el comportamiento del lazo se presenta en el capítulo 9.*
