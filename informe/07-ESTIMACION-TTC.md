# 7. Validación del estimador de TTC y calibración del campo de obstáculos

El capítulo 6 describe el modelo algorítmico del estimador de flujo óptico y su salida, el `ObstacleField`. Este capítulo responde una pregunta diferente: **¿cómo sabemos que el estimador funciona?** El enfoque adoptado es experimental — se recolectó un conjunto de datos con ground truth de profundidad del simulador y se aplicó análisis de curva ROC para calibrar y evaluar ambos canales (TTC y ocupación) con datos reales de vuelo.

## 7.1 Ground truth de profundidad en AirSim: ventaja metodológica

AirSim expone un canal de profundidad planar (`DepthPlanar`, en metros por píxel) sin costo computacional adicional: es un buffer de renderizado que el motor ya produce como subproducto de la rasterización. Esto elimina la necesidad de instrumentación externa (LiDAR, cámaras estéreo calibradas, marcadores en escena) y permite construir ground truth denso y de alta frecuencia en condiciones de vuelo idénticas a las de la misión real — la misma geometría, los mismos patrones de movimiento, el mismo ciclo de control (Shah et al., 2017; Jansen et al., 2023).

El TTC de referencia por celda se define como:

$$TTC_{\text{gt}}(\text{celda}) = \frac{\text{percentil}_{20}(Z_{\text{celda}})}{\max(v_{\text{cierre}},\, \varepsilon)}$$

donde $Z_{\text{celda}}$ es la distribución de profundidades de los píxeles de la celda (el percentil 20 actúa como estimado conservador resistente a píxeles de fondo), y $v_{\text{cierre}}$ es la componente de la velocidad del vehículo proyectada sobre el eje óptico (velocidad de cierre frontal positiva = aproximación), extraída de la telemetría del simulador. El término $\varepsilon = 0.01$ m/s evita la división por cero durante hover. Esta definición produce un TTC de referencia que es una función *observable y auditable* del estado físico del sistema en cada ciclo.

**Una limitación de diseño del ground truth:** la profundidad planar mide la distancia perpendicular al plano focal, no la distancia euclidiana al obstáculo más cercano en cada dirección de la cámara. Para obstáculos cercanos y cámaras con ángulo de campo amplio, esta diferencia no es negligible, pero dentro del rango de interés práctico (< 15 m) y con la óptica de 60° de FoV de AirSim, la discrepancia es inferior al 8% para el sector central. Se acepta como buena aproximación para la validación.

*(Para el desarrollo formal del TTC como observable óptico directo $\tau$, la formulación de divergencia y el cálculo por percentil 20 en la grilla $3 \times 3$, véase el [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md), §A5.5–A5.6).*

## 7.2 Diseño del conjunto de datos de validación

`experiments/collect_ttc_dataset.py` recolecta, por ciclo y por celda, el conjunto de variables listado en la tabla siguiente, generando registros JSONL en `runs/ttc/`:

| Campo | Descripción |
|---|---|
| `ttc_est` | TTC estimado por `FlowTTCEstimator` (segundos) |
| `ttc_gt` | TTC de referencia por profundidad (segundos) |
| `occupancy` | Ocupación estimada por celda |
| `divergence_raw` | Divergencia bruta antes de escalar |
| `confidence` | Confianza de celda (fracción de píxeles válidos × `foe_confidence`) |
| `sector`, `band` | Identificación de celda en la grilla 3×3 |
| `speed_mps` | Velocidad de traslación horizontal del vehículo (m/s) |
| `yaw_rate_rps` | Tasa de guiñada instantánea (rad/s) |
| `flow_algorithm` | Backend usado (`dis` o `farneback`) |
| `foe_confidence` | Confianza del FOE estimado (antes de multiplicar por fracción válida) |

El conjunto recolectado totaliza **3735 registros** de 9 celdas cada uno, cubriendo tres escenarios de vuelo scripteados diseñados para ejercitar aspectos específicos del estimador:

1. **Aproximación frontal a un edificio**: vuelo recto hacia una fachada a distintas velocidades (1–6 m/s); maximiza la señal de expansión en el sector central y verifica la correlación TTC estimado vs. TTC de referencia en condiciones ideales.

2. **Vuelo por un cañón urbano**: desplazamiento lateral entre dos edificios; activa los sectores izquierdo y derecho mientras el central permanece mayormente libre; verifica que la grilla detecta amenazas laterales sin generar falsos positivos en el centro.

3. **Giros de guiñada sin traslación**: rotación pura sobre el eje vertical, diseñada para ejercitar el guard de rotación (`FLOW_MAX_ROTATION_DEG`) y la derotación de guiñada. La expectativa correcta es que, durante el giro, el estimador declare incertidumbre (`foe_confidence = 0`) en lugar de reportar obstáculos espurios.

**Limitación documentada del conjunto de datos:** el escenario de giros de guiñada quedó concentrado en el rango $|\dot{\psi}| \in [0.0,\ 0.05)$ rad/s — velocidades de guiñada muy bajas, más próximas al crucero suave que a las maniobras activas de evasión (0.3–0.5 rad/s). Este rango no ejerce presión real sobre la derotación, y la validación de la derotación en giros agresivos queda aún pendiente (§7.5).

## 7.3 Resultados del canal de TTC: dos métricas, una interpretación correcta

El análisis en `experiments/analyze_ttc.py` produce dos números que, leídos de forma independiente, parecen contradictorios:

**Métrica 1 — Correlación puntual:** $r \approx -0.034$, error relativo mediano del 66%.

**Métrica 2 — AUC ROC para detección binaria:** 0.96–0.97 para el evento "colisión dentro de $\tau$ segundos" con $\tau \in \{1, 2, 3\}$.

La reconciliación entre estos dos números es el resultado estadístico central de este capítulo. Procede así:

**¿Por qué la correlación puntual es baja?** La correlación de Pearson mide si existe una relación *lineal* entre dos variables. Un TTC estimado de 4.8 s cuando el TTC real es 3.1 s (error puntual de 55%) contribuye igual a la correlación que si ese par estuviera perfectamente alineado *o no*. El estimador de flujo tiene errores de escala sistemáticos (el modelo de cámara pinhole asume movimiento rígido puro; los residuos de derotación, la profundidad desigual de objetos en la misma celda, y el efecto de la perspectiva en celdas no centrales introducen sesgos). Esos errores de escala no son aleatorios: son sistemáticos y predecibles. En consecuencia, la correlación puntual es baja, pero el *ordenamiento relativo* de los TTC estimados sigue siendo correcto: una celda con TTC estimado de 2.0 s es consistentemente más peligrosa que una con 5.0 s.

**¿Por qué el AUC es alto?** El AUC ROC mide exactamente la propiedad que la correlación no mide: la capacidad del estimador de *ordenar* los casos por riesgo. Un AUC de 0.96 significa que, si se escoge al azar una celda "peligrosa" (TTC real < $\tau$) y una celda "segura" (TTC real ≥ $\tau$), el estimador le asigna un TTC menor a la peligrosa con probabilidad 0.96 — la interpretación probabilística estándar del área bajo la curva ROC como estimador de la probabilidad de ordenamiento correcto entre un caso positivo y uno negativo elegidos al azar (Fawcett, 2006). Ese es el predicado exacto que el sistema de control necesita: no necesita saber que faltan 3.2 s para la colisión; necesita saber que *esta celda* es más peligrosa que *aquella*.

**Formulación defendible del estimador:** "El TTC estimado es un *puntaje de riesgo de cierre calibrado por curva ROC*, cuyo valor numérico tiene unidades de segundos por construcción matemática del modelo (§6.7) pero no interpretación métrica directa. Los umbrales operativos (`TTC_EVASION_THRESHOLD`, `TTC_SAFE_THRESHOLD`) son umbrales en esa escala de puntaje, derivados por criterio de Youden, no parámetros físicos independientes."

Esta distinción entre *clasificador de riesgo* y *cronómetro* se alinea con la literatura sobre sistemas de advertencia de colisión en visión monocular: Al-Kaff et al. (2017) y Vera-Yanez et al. (2024) reportan resultados similares — correlación puntual pobre pero detección binaria confiable — y argumentan que la métrica relevante para evasión es la tasa de verdaderos positivos antes de la zona de peligro, no la precisión de la estimación en segundos.

## 7.4 Derivación de umbrales operativos por índice de Youden

El índice de Youden ($J = \text{sensibilidad} + \text{especificidad} - 1$; Youden, 1950) es el criterio de selección de umbral óptimo que maximiza simultáneamente la tasa de detección de peligro real y la de descarte de falsos peligros — geométricamente, el punto de la curva ROC más alejado de la diagonal de clasificación aleatoria. Para cada $\tau$ se barrió el espacio de umbrales sobre la curva ROC y se encontró:

| Tiempo de horizonte $\tau$ | Umbral de TTC (Youden) | Sensibilidad | Especificidad |
|---|---|---|---|
| 1 s | ~2.1 s | 0.91 | 0.88 |
| 2 s | ~3.18 s | 0.93 | 0.89 |
| 3 s | ~4.58 s | 0.90 | 0.91 |

El umbral para $\tau = 2$ s (3.18 s) fue adoptado como `TTC_EVASION_THRESHOLD` (redondeado a 3.2 s), reemplazando el valor provisorio de 3.0 s que se usaba antes de la validación. El umbral para $\tau = 3$ s (4.58 s) fue adoptado como `TTC_SAFE_THRESHOLD` (redondeado a 4.6 s), reemplazando 6.0 s. Ambos umbrales son datos de validación — no fueron elegidos a mano ni ajustados empíricamente por comportamiento de vuelo. La elección de $\tau = 2$ s como umbral de evasión y $\tau = 3$ s como umbral de zona segura refleja el tiempo de reacción del lazo (5 Hz → 200 ms por ciclo) más el tiempo de ejecución de la maniobra de evasión (1–2 ciclos); a esa velocidad de crucero el margen de 2 s es suficiente para iniciar evasión antes del impacto en los escenarios ensayados.

**Interpretación de la banda entre umbrales.** La zona $TTC \in (3.2,\ 4.6)$ s corresponde al estado "advertencia" en el `policy_router` (cap. 5): no hay bloqueo activo pero el riesgo es elevado; el sistema emite una solicitud al deliberativo y reduce la agresividad lateral de `evasive_node`. La banda de histéresis entre evasión (3.2 s) y zona segura (4.6 s) previene el *chattering* — oscilación rápida entre maniobra de evasión y crucero normal cuando el TTC estimado flota alrededor del umbral de evasión.

## 7.5 Calibración del canal de ocupación (estado y pendientes)

A diferencia del canal de TTC, el canal de ocupación (divergencia escalada → `occupancy`) no pasó todavía por el mismo protocolo de validación contra profundidad. La calibración actual del factor $0.450/8.0$ (descrita en §6.8 del capítulo 6) se realizó con un subconjunto reducido de los datos de `runs/ttc/` y no produjo una curva ROC completa; el factor fue ajustado manualmente hasta que el comportamiento de vuelo en los escenarios de prueba fue satisfactorio. No es un proceso de calibración estadísticamente controlado.

La validación pendiente consiste en:

1. Ejecutar `experiments/analyze_occupancy.py` sobre el conjunto completo (3735 registros), usando como referencia binaria la profundidad de celda < 10 m.
2. Construir la curva ROC del predicado `occupancy ≥ OBSTACLE_OCCUPANCY_BLOCKED`.
3. Calcular el umbral óptimo por Youden, análogamente a §7.4.
4. Verificar que el umbral derivado estadísticamente coincida con el valor operativo actual (0.35), o actualizarlo.

El `OBSTACLE_OCCUPANCY_BLOCKED = 0.35` es por tanto un valor provisorio que funciona en la práctica pero no tiene respaldo estadístico equivalente al del canal de TTC. Esta asimetría en la validación de los dos canales es una limitación documentada del estado actual del sistema.

| Métrica de validación | Canal TTC | Canal Ocupación |
|---|---|---|
| Protocolo de validación ROC | ✓ Completo | ✗ Pendiente |
| Umbral derivado por Youden | ✓ (`TTC_EVASION_THRESHOLD = 3.2 s`) | ✗ (valor provisorio = 0.35) |
| AUC reportada | 0.96–0.97 | No disponible |
| Conjunto de datos | 3735 registros | Subconjunto no documentado |

## 7.6 Validación de la derotación en giros agresivos (pendiente)

El guard `FLOW_MAX_ROTATION_DEG = 2°` descarta todos los ciclos donde la rotación entre frames supera ese umbral (cap. 6). El conjunto de datos de validación actual no ejercita este guard de forma significativa: el 97% de los registros del escenario de guiñada cae en $|\dot{\psi}| < 0.05$ rad/s.

Para completar la validación, es necesario un escenario específico con guiñada de $\pm 0.3$–$0.5$ rad/s sin traslación, que ejercite tanto la correcta inhibición del estimador (el guard debe activarse y retornar `empty_field`) como la eventual reanudación correcta de la estimación una vez que la rotación decrece. También sería informativo estratificar el error relativo de TTC por bins de tasa de guiñada con los datos existentes: si el error en $|\dot{\psi}| \in [0.03, 0.05)$ rad/s es significativamente mayor que en bins más bajos, sugeriría un error de escala o de sincronización entre la telemetría de actitud y el timestamp del frame que debería corregirse antes de considerar cerrada la validación del canal de TTC.

Esta ampliación queda como trabajo pendiente para la versión final del sistema antes de pruebas en hardware real (cap. 9).

## 7.7 Implicaciones para el diseño del sistema

Los resultados de validación tienen consecuencias directas sobre el diseño del lazo de control:

**El AUC de 0.96–0.97 justifica usar TTC como señal primaria de evasión.** Una tasa de verdaderos positivos del 93% con especificidad del 89% (a $\tau = 2$ s) es suficiente para evasión reactiva en entorno simulado; los falsos negativos (11%) son la fracción de situaciones peligrosas que el estimador no detecta a tiempo, justificando la capa deliberativa como red de seguridad.

**La baja correlación puntual justifica la banda de histéresis y el rol del VLM.** Si el TTC fuera un cronómetro confiable, bastaría un solo umbral. La incertidumbre de escala hace necesaria la zona de advertencia (3.2–4.6 s) y la consulta al VLM antes de comprometer una maniobra definitiva: el modelo de lenguaje provee contexto semántico que el estimador de flujo no puede dar.

**La validación pendiente del canal de ocupación es deuda técnica controlada.** El sistema funciona con el umbral provisorio de ocupación porque en los escenarios ensayados, el TTC es el canal primario de decisión y la ocupación actúa como corroboración secundaria. Sin embargo, antes de despliegue en entornos más exigentes (o en hardware real), el protocolo de validación del canal de ocupación debería completarse.
