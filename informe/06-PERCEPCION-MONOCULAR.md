# 6. Percepción monocular: flujo óptico, TTC, campo de obstáculos y profundidad estimada

La percepción usa una sola cámara RGB y tiene dos canales, uno por lazo de control (cap. 5, IT.5.1.2): el **flujo óptico** (IT.6.1–IT.6.11), que alimenta al lazo rápido cada 0.2 s, y la **profundidad monocular estimada** con Depth Anything V2 (IT.6.12), que alimenta al lazo lento y al barrido de resolución de bloqueos; IT.6.13 explica cómo se complementan. El desarrollo matemático, la interfaz del campo de obstáculos, las decisiones de implementación y los parámetros están en el [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md).

## 6.1 Fundamentos de diseño: percepción geométrica sin redes neuronales en el lazo rápido

El lazo rápido prescinde de redes neuronales de detección —detectores de cajas tipo YOLO ([Redmon et al., 2015](13-REFERENCIAS.md#ref-redmon-2015)) o segmentadores densos— y estima los obstáculos con **flujo óptico denso derotado y divergencia del campo traslacional**, por tres razones:

1. **Determinismo.** Con el cómputo compartido con la simulación y las redes del lazo lento, un estimador clásico garantiza una latencia acotada, de 20–50 ms por ciclo, sin los picos de inferencia de una red densa ([Shi et al., 2024](13-REFERENCIAS.md#ref-shi-s-2024); [Goel et al., 2021](13-REFERENCIAS.md#ref-goel-2021)).
2. **Robustez fuera de distribución.** Un detector supervisado se limita a sus clases de entrenamiento; el flujo modela el fenómeno **físico** de aproximación y reacciona ante cualquier objeto que genere paralaje, sea un cable, un saliente o un andamio ([Badrloo & Varshosaz, 2017](13-REFERENCIAS.md#ref-badrloo-2017); [Vera-Yanez et al., 2024](13-REFERENCIAS.md#ref-vera-yanez-2024)).
3. **Tiempo-a-Colisión físico.** La divergencia del flujo permite derivar el TTC en todo el plano de la imagen sin recuperar distancia ni velocidad por separado: la teoría del *tau* de [Lee (1976)](13-REFERENCIAS.md#ref-lee-1976), aplicada a UAVs por [Al-Kaff et al. (2017)](13-REFERENCIAS.md#ref-al-kaff-2017).

**Limitación estructural.** El flujo necesita **traslación entre fotogramas**: en hover, giro puro o crucero muy lento la señal colapsa, y lo mismo ocurre con un obstáculo centrado en el foco de expansión. El lazo lento cubre esa limitación con la profundidad estimada (IT.6.12).

## 6.2 Pipeline de percepción: cinco etapas

`FlowTTCEstimator.estimate()` ejecuta cada ciclo cinco etapas en secuencia y produce un `ObstacleField`:

<img src="2026-1113 pipeline_cinco_etapas.png"/>

*Figura 6.1. Las cinco etapas del estimador de flujo óptico. Cada ciclo recibe el par de fotogramas y la telemetría de ambos, y produce el `ObstacleField` que consume el lazo rápido; si alguna etapa no tiene evidencia suficiente, la salida es un campo vacío con confianza nula.*

Si en cualquier etapa no hay evidencia suficiente —primer ciclo, modo degradado, rotación grande entre fotogramas o flujo bajo el piso de ruido—, el estimador retorna un campo vacío con confianza nula: la ausencia de evidencia queda explícita.

## 6.3 Etapa 1: escala y parámetros intrínsecos

Los fotogramas se pasan a escala de grises y se escalan a un ancho de trabajo de 640 px, con la distancia focal escalada en proporción; la validación del capítulo 7 usó 320 px. Un **guard de rotación** descarta el ciclo si la rotación entre fotogramas supera 2°: durante las maniobras el yaw cambia 4–9° por ciclo, la derotación de primer orden deja de valer y cada giro produciría falsos obstáculos (IT.A5.11).

## 6.4 Etapa 2: flujo óptico denso (DIS)

El flujo se calcula con **DIS** (*Dense Inverse Search*, `cv2.DISOpticalFlow`), 5 a 10 veces más rápido que Farneback a resoluciones comparables y con la suavidad que necesita la estimación del FOE (Anexo 5, IT.A5.7; [Molineros et al., 2012](13-REFERENCIAS.md#ref-molineros-2012)). El campo mezcla el componente traslacional, el paralaje de la escena, con el rotacional inducido por la actitud del vehículo.

## 6.5 Etapa 3: derotación analítica por telemetría IMU

Para una cámara *pinhole* con rotación pequeña entre fotogramas, el flujo rotacional es una función analítica de la posición del píxel y de los incrementos de actitud que reporta la IMU, y se resta del flujo medido para obtener el campo traslacional (Anexo 5, IT.A5.3). Sin esta corrección, cada ajuste de guiado de unos pocos grados genera un flujo en el sector central que se interpreta como un obstáculo frontal y dispara evasiones espurias.

## 6.6 Etapa 4: estimación del Foco de Expansión (FOE) con RANSAC-lite

Bajo traslación pura, los vectores del campo traslacional apuntan radialmente desde un único punto, el **Foco de Expansión** (FOE), y la magnitud del flujo en cada píxel es inversamente proporcional a la distancia del obstáculo. Descartados los píxeles bajo el piso de ruido (0.35 px), el FOE se estima por **mínimos cuadrados ponderados** y una segunda pasada tipo **RANSAC-lite** descarta los vectores desalineados más de ~20° ([Kaneko et al., 2017](13-REFERENCIAS.md#ref-kaneko-2017)). Con menos de 30 inliers la confianza del FOE se fija en 0.3 como señal de evidencia degradada; con más, crece con la fracción de inliers (Anexo 5, IT.A5.4).

**Limitación de la implementación evaluada** (se reproduce en NB3.4). La prueba de inliers del código evaluado compara cada vector con la dirección $p \to \text{FOE}$, cuando en el avance el flujo diverge del FOE ($\text{FOE} \to p$). En una aproximación pura no queda ningún inlier, y la confianza del FOE queda en 0.3: por debajo del umbral con el que el TTC puede bloquear una celda por sí solo (0.35, IT.6.9). En la corrida de referencia de `citysim_pilot` (`depth2loop`, semilla 233) la supera en el 7.6 % de los ciclos con flujo. Su consecuencia sobre lo que dispara la evasión, y el efecto de corregirla —medido fuera de vuelo y no aplicado—, se analizan en el cap. 7 (IT.7.7): todos los resultados corresponden al código tal como está descrito.

## 6.7 Etapa 5: TTC por píxel y divergencia

Con el FOE y el intervalo real $\Delta t$ entre fotogramas —la diferencia de timestamps del simulador, nunca el período nominal del lazo—, el TTC de cada píxel válido es

$$TTC(x,y) = \frac{\|p - \text{FOE}\| \cdot \Delta t}{\|\mathbf{v}_{\text{trans}}(x,y)\|}$$

la forma discreta de $TTC = Z / v_{\text{cierre}}$. En paralelo se calcula la **divergencia** del campo traslacional, cuyo valor positivo indica expansión local: es evidencia de aproximación que no depende del FOE.

## 6.8 Grilla de celdas 3×3 y agregación por sector

El campo traslacional se divide en una grilla de 3 columnas (sectores *izquierda*, *centro*, *derecha*) × 3 filas, y para cada celda se calculan tres valores (definición formal en el Anexo 5, IT.A5.6.1):

- **Confianza**: la fracción de píxeles válidos de la celda por la confianza del FOE.
- **TTC de celda**: el percentil 20 de los TTC finitos de la celda, conservador ante TTC espuriamente bajos en píxeles aislados.
- **Ocupación**: la divergencia media de la celda multiplicada por una constante de escala empírica ($k \approx 0.056$ s) y acotada a $[0, 1]$.

## 6.9 El predicado de bloqueo: fusión de dos canales

Una celda está **bloqueada** si tiene evidencia mínima (confianza ≥ 0.15) **y** su ocupación supera 0.011, **o** si su TTC es ≤ 2.5 s con confianza ≥ 0.35:

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

El umbral de ocupación sale de la curva ROC contra la profundidad de referencia (AUC = 0.87, índice de [Youden](13-REFERENCIAS.md#ref-youden-1950); cap. 7, IT.7.5): frente a una pared sólida la ocupación nunca supera 0.082, de modo que un umbral fijado a ojo (0.35) dejaría ese canal desactivado. El TTC necesita más confianza que la ocupación para votar solo, porque la confianza degradada del FOE (0.3) supera el piso general (IT.A5.11). Por la limitación de IT.6.6, en el código evaluado el TTC casi nunca alcanza ese umbral en el avance; qué dispara entonces la evasión en vuelo se analiza en el cap. 7 (IT.7.7).

## 6.10 El contrato `ObstacleField` y la ausencia de evidencia

Todos los consumidores de la percepción —lazo rápido, evasión, FSM, gobernador de velocidad y registro— acceden al campo de obstáculos **solo** a través de su interfaz pública, un objeto inmutable (Anexo 5, IT.A5.8). El campo distingue el origen de su evidencia —flujo, degradado, retenido o sin datos—, y `has_evidence()` solo es verdadero con flujo y confianza positiva. Es el contrato que evita la Falla 1 del capítulo 9: **la falta de evidencia no es espacio libre**. Un hover produce un campo sin evidencia, y tratarlo como camino despejado desactivaría el escape de bloqueo justo cuando el dron está atrapado; por eso el gobernador limita el avance sin evidencia (cap. 5, IT.5.4).

## 6.11 Comportamiento bajo condiciones extremas

- **Hover o vuelo muy lento:** el campo queda sin evidencia —«sin información», no «despejado»—; el gobernador limita el avance y la capa estratégica sigue juzgando la escena con la profundidad estimada.
- **Giro puro:** el guard de rotación declara el ciclo degradado y el lazo continúa la maniobra comprometida; la inhibición se verificó con guiñadas de 0.3 a 1.0 rad/s (cap. 7, IT.7.6).
- **Fotogramas aislados sin evidencia:** el estimador retiene el último campo válido, con el TTC descontado, durante hasta 0.6 s, y cerca de un obstáculo el guiado limita su guiñada a 5 °/s (IT.A5.9).
- **Textura baja o cambios bruscos de iluminación:** sin gradiente la confianza de la celda es casi nula; un cambio de exposición produce flujo sistemático que el recorte de outliers mitiga en parte.

## 6.12 Profundidad monocular estimada: Depth Anything V2

### 6.12.1 Qué es y por qué se usa

**Depth Anything V2** ([Yang et al., 2024](13-REFERENCIAS.md#ref-yang-2024)) es una familia de modelos fundacionales que predicen la profundidad de cada píxel a partir de **una sola imagen RGB**; las variantes **métricas** la devuelven en metros. Este trabajo usa `Depth-Anything-V2-Metric-Outdoor-Small`, de ~25 M de parámetros.

La elección responde a una medición. El lazo lento hace una pregunta de **distancia** —si se puede volar 15 m en la dirección de cada sector—, y el banco de prueba (cap. 10, IT.10.2; cap. 11, IT.11.0) midió tres formas de responderla con el mismo fotograma y la misma etiqueta de referencia (625 muestras × 9 sectores):

| Señal | Exactitud balanceada [IC 95 %] | AUC | Latencia |
|---|---|---:|---:|
| **Depth Anything V2 Metric Outdoor Small: p5 estimado por sector** | **75 % [72–77 %]** | **0.83** | 82 ms |
| Segmentación semántica (`yolo26n-sem`): 1 − fracción de obstáculo | 45 % [42–47 %] | 0.50 | 32 ms |
| VLM de vuelo (LFM2.5-VL-1.6B), grilla 3×3 | 53 % [50–55 %] | 0.53 | 880 ms |

Solo la profundidad estimada supera el criterio del banco: una clase semántica no dice la distancia, y en los barridos reales la profundidad separa rumbos abiertos de cerrados con AUC 0.87, mientras el VLM declaró transitables todos los rumbos. Sus errores son conservadores: el 2 % de los sectores que marca libres tienen un obstáculo a menos de 5 m.

### 6.12.2 Del fotograma a la decisión

Sobre el recorte cuadrado central del fotograma, dividido en una grilla de 3×3, se toma el **percentil 5** de la profundidad estimada de cada sector, y el sector es libre si ese valor es ≥ 15 m: el mismo estadístico con que se construyen las etiquetas del banco (cap. 7, IT.7.1). El servicio devuelve la misma estructura que el VLM, de modo que el resto del sistema no distingue la fuente (detalle en el Anexo 5, IT.A5.12).

### 6.12.3 Dónde corre y qué no es

La red **nunca corre dentro del lazo de 5 Hz**: corre en un hilo de servicio, en ~110 ms con la GPU compartida. No reemplaza al flujo en el lazo rápido —el flujo detecta un cierre en milisegundos; la profundidad decide, cada segundo, hacia dónde está el espacio libre— y **no lee el canal de profundidad del simulador**: recibe el mismo fotograma RGB que el flujo, como una red a bordo de un dron con una sola cámara.

### 6.12.4 Limitaciones

La red se evaluó sobre el mismo render sintético del que salen sus etiquetas, y en una cámara real puede rendir menos; su escala métrica no está calibrada a 10–30 m de altura, de modo que el umbral de 15 m funciona como corte de clasificación y no como medición; el follaje y los objetos finos son su caso más difícil; y cada consulta juzga un fotograma aislado, solo en el recorte central (detalle en el Anexo 5, IT.A5.12).

## 6.13 Complementariedad entre flujo óptico y profundidad estimada

El **flujo óptico** detecta un cierre en milisegundos cuando el dron se traslada con textura suficiente, pero es ciego en hover, en giro puro, ante obstáculos centrados en el foco de expansión y ante superficies horizontales. La **profundidad estimada** no necesita traslación y ve esos casos, pero tarda demasiado para lo inminente: sirve para decidir el rodeo cada segundo. La interfaz entre ambos es **geométrica**, no textual —bloqueos por sector para el lazo rápido, sub-metas en coordenadas del mundo para el guiado—, y ninguno recibe la salida del otro. La evaluación del flujo está en el capítulo 7 y la de la profundidad, en el capítulo 11 (IT.11.0).
