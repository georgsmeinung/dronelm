# 7. Estimación de TTC y su validación

## 7.1 Protocolo de validación

El canal de profundidad de AirSim (`DepthPlanar`, en metros) permite construir una referencia (*ground truth*) del tiempo-a-colisión sin necesidad de instrumentación adicional, y sin costo de vuelo extra. `experiments/collect_ttc_dataset.py` recolecta, por ciclo y por celda, el TTC estimado, el TTC de referencia, la divergencia, la ocupación, la confianza, y variables de contexto (velocidad, tasa de guiñada, algoritmo de flujo usado). El TTC de referencia por celda se calcula como

$$ TTC_{\text{gt}}(\text{celda}) = percentil20(Z_{\text{celda}}) / max(v_{\text{closing}}, ε) $$

donde $`Z_{\text{celda}}`$ es la profundidad de la celda (percentil 20, para ser robusto a ruido puntual) y `v_closing` es la componente de la velocidad del cuerpo del dron (de telemetría) proyectada sobre el eje óptico de la cámara.

El conjunto de datos recolectado (3735 registros, `runs/ttc/*.jsonl`) cubre tres escenarios scripteados: aproximación frontal a un edificio, vuelo recto por un cañón urbano, y giros de guiñada sin componente de aproximación — diseñado específicamente para ejercitar la derotación de guiñada descrita en el capítulo 6, desacoplando el giro propio de la señal de aproximación frontal.

## 7.2 Resultado y su interpretación correcta

El análisis (`experiments/analyze_ttc.py`) reporta dos resultados que, leídos por separado, parecen contradictorios: la correlación puntual entre el TTC estimado y el TTC de referencia es floja (r ≈ −0.034, error relativo mediano del 66 %), pero el área bajo la curva ROC (AUC) para el evento binario "colisión dentro de τ segundos" (con τ ∈ {1, 2, 3}) es de 0.96–0.97, y los umbrales elegidos por el índice de Youden son τ=2 s → TTC=3.18 s y τ=3 s → TTC=4.58 s.

La lectura correcta de estos dos números en conjunto es que el estimador **no es un cronómetro**: no hay que interpretar "TTC = 3.2 s" como una medición física precisa de cuánto tiempo falta para una colisión. Lo que sí es, con una AUC de 0.96–0.97, es un **ordenador de riesgo monótono confiable**: un valor de TTC más bajo corresponde, de forma consistente, a mayor riesgo de colisión próxima, aunque el valor puntual en segundos no deba tomarse como magnitud física exacta. Presentarlo como *"un puntaje de riesgo calibrado por curva ROC, cuyo umbral tiene unidades de segundos por construcción pero no interpretación métrica directa"* es la formulación defendible; presentarlo como "TTC = 3.2 s" sin ese matiz sería sobre-especificar la precisión del estimador. Con esos umbrales, `TTC_EVASION_THRESHOLD` se fijó en 3.2 s (antes, un valor provisorio de 3.0) y `TTC_SAFE_THRESHOLD` en 4.6 s (antes, 6.0), ambos derivados de los valores de Youden y no elegidos a mano.

Una limitación queda explícitamente documentada: la validación proviene de una única sesión de vuelo en simulador, y el escenario de giros de guiñada quedó, en la práctica, casi enteramente concentrado en el rango `|yaw_rate| ∈ [0, 0.05)` rad/s. Eso valida bien la detección frontal, pero **no** valida todavía la derotación en giros agresivos con datos reales — es precisamente el caso de uso para el que se diseñó la derotación (cap. 6), y su validación con un rango más amplio de tasas de guiñada queda como trabajo pendiente.

## 7.3 Calibración del canal de ocupación (pendiente)

A diferencia del TTC, el canal de ocupación de `ObstacleField` no pasó todavía por este mismo protocolo de validación contra profundidad. Como se documenta en el capítulo 6 (sección 6.3), el cálculo actual de la divergencia tiene un error de escala conocido (kernel de Sobel sin normalizar), lo que hace que calibrar el umbral de ocupación contra el canal de profundidad —con el mismo enfoque de curva ROC ya aplicado al TTC— sea un paso pendiente y no meramente un refinamiento opcional: el umbral actual (`OBSTACLE_OCCUPANCY_BLOCKED`) sigue siendo un valor provisorio, tal como lo señala el propio código.

| TTC real | Divergencia reportada | Occupancy media | % de celdas ≥ umbral |
|---|---|---|---|
| _pendiente de recalibración_ | _pendiente_ | _pendiente_ | _pendiente_ |

## 7.4 Validación de la derotación con giros agresivos (pendiente)

Ampliar el escenario de giros de guiñada del conjunto de datos de validación (sección 7.1) para cubrir tasas de guiñada más agresivas (del orden de ±0.3 a ±0.5 rad/s, sin componente de traslación), y re-correr la estratificación del error de TTC por `|yaw_rate|`, permitiría confirmar si el error relativo en los bins de guiñada alta es comparable al de guiñada baja. Si no lo es, indicaría un error de signo o una desincronización entre la telemetría de actitud y el fotograma que debería corregirse antes de dar por cerrada la validación del canal de TTC. Esta ampliación queda como trabajo pendiente.
