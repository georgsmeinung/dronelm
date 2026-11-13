# 6. Percepción monocular: flujo óptico, TTC, campo de obstáculos y profundidad estimada

La percepción usa una sola cámara RGB y tiene dos canales, uno por lazo de control (cap. 5, IT.5.1.2): el **flujo óptico** (IT.6.1–IT.6.11), que alimenta al lazo rápido cada 0.2 s, y la **profundidad monocular estimada** con Depth Anything V2 (IT.6.12), que alimenta al lazo lento y al barrido de resolución de bloqueos. IT.6.13 explica cómo se complementan. El desarrollo matemático, la interfaz completa del campo de obstáculos y los parámetros del estimador están en el [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md).

## 6.1 Fundamentos de diseño: percepción geométrica sin redes neuronales en el lazo rápido

El lazo rápido prescinde de redes neuronales de detección —detectores de cajas tipo YOLO ([Redmon et al., 2015](13-REFERENCIAS.md#ref-redmon-2015)) o segmentadores densos— y estima los obstáculos con visión por computadora clásica: **flujo óptico denso derotado y divergencia del campo traslacional**, por tres razones.

**1. Determinismo y presupuesto de cómputo compartido.** Con el cómputo compartido con la simulación y con las redes del lazo lento, un estimador de flujo clásico garantiza una latencia determinista y acotada, del orden de 20–50 ms por ciclo, sin los picos de inferencia de una red densa ([Shi et al., 2024](13-REFERENCIAS.md#ref-shi-s-2024); [Goel et al., 2021](13-REFERENCIAS.md#ref-goel-2021)).

**2. Robustez fuera de distribución.** Un detector supervisado se limita a las clases de su entrenamiento, y en una ciudad los obstáculos incluyen cables, salientes o andamios sin etiqueta previa. El flujo óptico modela el fenómeno **físico** de aproximación —la expansión de textura en el plano focal— y reacciona ante cualquier objeto que genere paralaje, sin importar su clase ([Badrloo & Varshosaz, 2017](13-REFERENCIAS.md#ref-badrloo-2017); [Vera-Yanez et al., 2024](13-REFERENCIAS.md#ref-vera-yanez-2024)).

**3. Tiempo-a-Colisión (TTC) físico.** Una caja delimitadora no da información de cierre. La divergencia del flujo traslacional permite derivar el TTC ($TTC \approx d / v_{\text{cierre}}$) en todo el plano de la imagen: es la teoría del *tau* ($\tau$) de [Lee (1976)](13-REFERENCIAS.md#ref-lee-1976), según la cual el tiempo-a-colisión se lee de la tasa de expansión óptica sin recuperar distancia ni velocidad por separado, aplicada a UAVs por [Al-Kaff et al. (2017)](13-REFERENCIAS.md#ref-al-kaff-2017).

**Limitación estructural.** El flujo óptico necesita **traslación entre frames**: en hover, giro puro o crucero muy lento la señal colapsa, y lo mismo ocurre con un obstáculo centrado en el foco de expansión. El lazo lento, que mira un único fotograma, cubre esa limitación con la profundidad estimada (IT.6.12).

## 6.2 Pipeline de percepción: cinco etapas

`FlowTTCEstimator.estimate()` ejecuta cada ciclo cinco etapas en secuencia y produce un `ObstacleField`:

<img src="2026-1113 pipeline_cinco_etapas.png"/>

*Figura 6.1. Las cinco etapas del estimador de flujo óptico. Cada ciclo recibe el par de fotogramas y la telemetría de ambos, y produce el `ObstacleField` que consume el lazo rápido; si alguna etapa no tiene evidencia suficiente, la salida es un campo vacío con confianza nula.*

Si en cualquier etapa no hay evidencia suficiente (primer ciclo, modo degradado, rotación grande entre frames, flujo bajo el piso de ruido), la función retorna un campo vacío con confianza nula, marcando explícitamente la ausencia de evidencia sin ningún clamp cosmético que la enmascare.

## 6.3 Etapa 1: escala y parámetros intrínsecos

Los fotogramas se convierten a escala de grises y se escalan a un ancho de trabajo de 640 px, con la distancia focal escalada en proporción; a 320 px, el valor usado en la validación del capítulo 7, los objetos finos como las ramas quedan bajo el piso de ruido.

**Guard de rotación.** Antes de computar el flujo, el estimador verifica que la rotación entre frames no exceda 2°. Durante maniobras activas (`GIRAR_90`, `EVADIR_*`) el yaw cambia 4–9° por ciclo; en esas condiciones el modelo de derotación de primer orden (IT.6.5) introduce errores de linealización y las regiones de baja textura generan flujo esencialmente aleatorio. Sin este guard, cada giro produce «nubes» de falsos obstáculos. La solución conservadora es descartar el ciclo y declarar el campo degradado: es mejor declarar incertidumbre que producir un falso positivo que cancele una maniobra en ejecución.

## 6.4 Etapa 2: flujo óptico denso (DIS)

El backend de flujo es **DIS** (*Dense Inverse Search*, `cv2.DISOpticalFlow`), con Farneback como alternativa. DIS produce un campo vectorial $\mathbf{v}(x,y) = (u, v)$ de desplazamientos en píxeles para cada posición del frame actual respecto del anterior, y su búsqueda inversa por parches es entre 5 y 10 veces más rápida que Farneback a resoluciones comparables, con la suavidad que necesita la estimación del FOE (comparación en el Anexo 5, IT.A5.7; [Vera-Yanez et al., 2024](13-REFERENCIAS.md#ref-vera-yanez-2024); [Molineros et al., 2012](13-REFERENCIAS.md#ref-molineros-2012)). El campo resultante mezcla el componente traslacional (paralaje de objetos en escena) con el rotacional inducido por los cambios de actitud del vehículo; separarlos es el objetivo de la etapa siguiente.

## 6.5 Etapa 3: derotación analítica por telemetría IMU

La rotación propia del vehículo entre frames genera un flujo angular parásito que enmascara la expansión traslacional real. Para una cámara *pinhole* con rotación pequeña entre frames, ese flujo rotacional es una función analítica de la posición del píxel y de los incrementos de pitch, yaw y roll que reporta la IMU, y se resta del flujo medido para obtener el campo traslacional (las ecuaciones están en el Anexo 5, IT.A5.3). Cuando la telemetría trae la velocidad angular del giroscopio, el estimador la integra en el intervalo entre frames; en AirSim, cuyo IMU es ideal, es equivalente a restar los ángulos de dos ciclos, pero el diseño queda preparado para hardware real.

Esta corrección es crítica: sin ella, cada corrección de guiado de unos pocos grados genera un flujo rotacional en el sector central que se interpreta como un obstáculo frontal y dispara evasiones espurias en cada ciclo de crucero. El mismo principio se usa en sistemas de visión activa para vehículos terrestres ([Dickmanns, 2024](13-REFERENCIAS.md#ref-dickmanns-2024)) y SLAM monocular ([Chen et al., 2022](13-REFERENCIAS.md#ref-chen-w-2022)).

## 6.6 Etapa 4: estimación del Foco de Expansión (FOE) con RANSAC-lite

Bajo traslación pura, todos los vectores del campo traslacional apuntan radialmente desde un único punto, el **Foco de Expansión** (FOE). Su posición en la imagen codifica la dirección de traslación del vehículo, y la magnitud del flujo en cada píxel es inversamente proporcional a la distancia del obstáculo que generó ese paralaje.

Los píxeles con flujo por debajo de un piso de ruido (0.35 px) se descartan; si queda menos del 1 % de píxeles válidos, el campo entero se declara sin evidencia. Con los válidos, el FOE se estima por **mínimos cuadrados ponderados** —cada vector debe estar alineado con la recta que une su píxel al FOE, y los vectores más largos pesan más— y una segunda pasada tipo **RANSAC-lite** descarta los vectores desalineados más de ~20° y repite el ajuste ([Kaneko et al., 2017](13-REFERENCIAS.md#ref-kaneko-2017); [Molineros et al., 2012](13-REFERENCIAS.md#ref-molineros-2012)). Con menos de 30 inliers la confianza del FOE se fija en 0.3 como señal de evidencia degradada; con más, crece con la fracción de inliers; un FOE fuera de la imagen anula la confianza (deducción en el Anexo 5, IT.A5.4).

**Limitación de la implementación evaluada** (se reproduce en NB3.4). La prueba de inliers del código evaluado compara cada vector con la dirección $p \to \text{FOE}$. En el avance, en cambio, el flujo traslacional diverge del FOE (dirección $\text{FOE} \to p$), con un ángulo de ~180° respecto de la recta usada. En una aproximación pura no queda ningún inlier, la confianza del FOE queda en 0.3 y, con ella, la de las celdas: por debajo del umbral con el que el TTC puede bloquear por sí solo (0.35, IT.6.9). Una celda la bloquea entonces la ocupación (divergencia) y casi nunca el TTC. En la corrida de referencia de `citysim_pilot` (`slm`, semilla 233), la confianza del FOE supera 0.3 en el 7.6 % de los ciclos con flujo. El efecto de corregirlo se midió fuera de vuelo y no se aplicó (cap. 7, IT.7.7): todos los resultados de este trabajo corresponden al código tal como está descrito.

## 6.7 Etapa 5: TTC por píxel y divergencia

Con el FOE estimado y el intervalo temporal real $\Delta t$ entre frames —la diferencia de timestamps del simulador, nunca el período nominal del lazo—, se calcula para cada píxel válido:

$$TTC(x,y) = \frac{\|p - \text{FOE}\| \cdot \Delta t}{\|\mathbf{v}_{\text{trans}}(x,y)\|}$$

la forma discreta de $TTC = Z / v_{\text{cierre}}$, válida con traslación dominante. Cerca del FOE o con flujo muy pequeño, el TTC tiende a infinito: sin evidencia de aproximación.

**Canal de divergencia.** En paralelo, el estimador computa la divergencia del campo traslacional, $\text{div}(x,y) = \partial u / \partial x + \partial v / \partial y$, con diferencias centradas normalizadas por $\Delta t$. La divergencia positiva indica expansión local: el objeto en ese punto se acerca. Es un indicador complementario que no requiere estimar el FOE: aun si el ajuste del FOE falla, una celda con divergencia positiva elevada sigue siendo evidencia de aproximación.

## 6.8 Grilla de celdas 3×3 y agregación por sector

El campo traslacional se divide en una grilla de 3 columnas (sectores *izquierda*, *centro*, *derecha*) × 3 filas. Para cada celda $c$, sea $N_c$ su número de píxeles y $V_c$ el conjunto de los válidos (flujo por encima del piso de ruido). Se calculan tres valores:

$$
\begin{aligned}
\kappa_c &= \frac{|V_c|}{N_c}\,\kappa_{\text{FOE}} \\
\hat{\tau}_c &= P_{20}\big\{\,\tau(p) : p \in V_c,\ \tau(p) < \infty\,\big\} \\
o_c &= \min\!\big(1,\ \max(0,\ k\,\bar{d}_c)\big)
\end{aligned}
$$

- **Confianza** $\kappa_c$: la fracción de píxeles válidos de la celda por la confianza del FOE, $\kappa_{\text{FOE}}$ (IT.6.6). Combina la densidad local de flujo con la calidad global del FOE.
- **TTC de celda** $\hat{\tau}_c$: el percentil 20 de los TTC finitos de la celda, conservador y resistente a TTC espuriamente bajos en píxeles aislados. Con menos de 5 píxeles válidos, $\hat{\tau}_c = \infty$.
- **Ocupación** $o_c$: la divergencia media de la celda, $\bar{d}_c = \frac{1}{|V_c|}\sum_{p \in V_c} \text{div}(p)$ (en s⁻¹, IT.6.7), multiplicada por una constante $k \approx 0.056$ s y acotada a $[0, 1]$. Una celda que en promedio se contrae ($\bar{d}_c \le 0$) tiene ocupación nula; una que se expande la tiene proporcional a la tasa de expansión.

La constante $k$ (en el código, $0.450/8$) se determinó empíricamente contra la profundidad de referencia del simulador: no es un valor físicamente derivado sino un factor de escala. Como $o_c$ es lineal en $\bar{d}_c$ por debajo de 1, el umbral de bloqueo de 0.011 (IT.6.9) equivale a pedir una divergencia media de al menos ~0.2 s⁻¹ en la celda. El protocolo de validación se describe en el capítulo 7.

## 6.9 El predicado de bloqueo: fusión de dos canales

La decisión de si una celda está **bloqueada** fusiona los dos canales con una compuerta disyuntiva condicionada a la confianza:

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

Una celda está bloqueada si tiene evidencia mínima de percepción **y** la ocupación es alta, **o** el TTC es bajo con suficiente confianza.

**Calibración del umbral de ocupación (D2).** La ocupación no toma valores comparables a los del TTC: frente a una pared sólida nunca supera 0.082, de modo que un umbral fijado a ojo (0.35) dejaría ese canal **desactivado**. La curva ROC contra la profundidad de referencia dio AUC = 0.87 y un umbral óptimo por [índice de Youden](13-REFERENCIAS.md#ref-youden-1950) de **0.011** (cap. 7, IT.7.5). `main.py` incorpora además un calibrador que ajusta el umbral al ruido de ocupación del entorno en los primeros ciclos; **el ejecutor de experimentos no lo usa**, de modo que las corridas en lote operan con el valor fijo.

**Umbrales diferenciados de confianza.** La ocupación puede votar bloqueo con confianza 0.15, pero el TTC solo, sin apoyo de la ocupación, necesita 0.35. La razón es que el camino de «pocos inliers» del FOE produce una confianza de 0.3 como señal de evidencia degradada, que supera el piso general: con un único umbral, el TTC degradado votaría con la misma autoridad que un FOE robusto y produciría falsos positivos. Por la limitación descrita en IT.6.6, la confianza casi nunca llega a 0.35 en el avance, y en el código evaluado el bloqueo lo decide sobre todo la ocupación.

## 6.10 El contrato `ObstacleField` y la ausencia de evidencia

Todos los consumidores de la percepción —lazo rápido, evasión, FSM, gobernador de velocidad y registro— acceden al campo de obstáculos **solo** a través de su interfaz pública, un objeto inmutable que ninguno puede modificar; la capa estratégica no lo recibe, porque mira el fotograma (cap. 5, IT.5.5). El campo distingue el origen de su evidencia —flujo, degradado, retenido o sin datos—, y `has_evidence()` solo es verdadero con flujo y confianza positiva. Ese es el contrato que evita la Falla 1 del capítulo 9: **la falta de evidencia no es espacio libre**. Un hover produce un campo sin evidencia, y tratarlo como camino despejado desactivaría el escape de bloqueo justo cuando el dron está atrapado; por eso la consulta de corredor libre de la FSM devuelve falso sin evidencia y el gobernador limita el avance (cap. 5, IT.5.4). La interfaz completa está en el Anexo 5 (IT.A5.8).

## 6.11 Comportamiento bajo condiciones extremas

- **Hover o vuelo muy lento:** el campo queda sin evidencia —«sin información», no «despejado»—; el gobernador limita el avance y la capa estratégica sigue juzgando la escena con la profundidad estimada.
- **Giro puro:** el guard de rotación declara el ciclo degradado y el lazo continúa la maniobra comprometida; la inhibición se verificó con guiñadas de 0.3 a 1.0 rad/s (cap. 7, IT.7.6).
- **Frames aislados sin evidencia:** el estimador retiene el último campo válido, con el TTC descontado, durante hasta 0.6 s, y cerca de un obstáculo el guiado limita su guiñada a 5 °/s, dentro del rango de la derotación (IT.A5.9).
- **Textura baja o cambios bruscos de iluminación:** sin gradiente la confianza de la celda es casi nula; un cambio de exposición produce flujo sistemático que el recorte de outliers mitiga en parte.

Los parámetros del estimador están en el Anexo 5 (IT.A5.10).

## 6.12 Profundidad monocular estimada: Depth Anything V2

### 6.12.1 Qué es y por qué se usa

**Depth Anything V2** ([Yang et al., 2024](13-REFERENCIAS.md#ref-yang-2024)) es una familia de modelos fundacionales de estimación de profundidad monocular: a partir de **una sola imagen RGB** predicen la profundidad de cada píxel. Un modelo maestro entrenado con imágenes sintéticas, de profundidad exacta, etiqueta imágenes reales, y con esas pseudo-etiquetas se entrenan los modelos chicos; las variantes **métricas** devuelven la profundidad **en metros**. Este trabajo usa `Depth-Anything-V2-Metric-Outdoor-Small`: la variante para exteriores con el codificador más chico, de ~25 M de parámetros.

La elección responde a una medición. El lazo lento hace una pregunta de **distancia** —si se puede volar 15 m en la dirección de cada sector—, y el banco de prueba (cap. 10, IT.10.2; cap. 11, IT.11.0) midió tres formas de responderla con el mismo fotograma, contra la misma etiqueta de referencia (625 muestras × 9 sectores):

| Señal | Exactitud balanceada [IC 95 %] | AUC | Latencia |
|---|---|---:|---:|
| **Depth Anything V2 Metric Outdoor Small: p5 estimado por sector** | **75 % [72–77 %]** | **0.83** | 82 ms |
| Segmentación semántica (`yolo26n-sem`): 1 − fracción de obstáculo | 45 % [42–47 %] | 0.50 | 32 ms |
| VLM de vuelo (LFM2.5-VL-1.6B), grilla 3×3 | 53 % [50–55 %] | 0.53 | 880 ms |

Solo la profundidad estimada supera el criterio del banco. La segmentación no sirve porque una clase no dice la distancia —«edificio» incluye uno a 100 m—, y en los barridos reales la profundidad separa rumbos abiertos de cerrados con AUC 0.87, mientras el VLM declaró transitables todos los rumbos. Sus errores son conservadores: el 2 % de los sectores que marca libres tienen un obstáculo a menos de 5 m. El espacio libre es una pregunta de geometría, que resuelve una red chica entrenada para estimar distancia y no un modelo de lenguaje generalista (cap. 12, IT.12.2).

### 6.12.2 Del fotograma a la decisión

La red procesa el fotograma crudo del ciclo, el mismo que usa el flujo óptico, y produce una matriz de profundidades en metros. Sobre el recorte cuadrado central del fotograma —el mismo que recibiría el VLM—, dividido en una grilla de 3×3, se toma el **percentil 5** de la profundidad de cada sector: lo más cercano, sin que lo decidan píxeles sueltos. Un sector es libre si ese valor es ≥ 15 m, la misma distancia a la que se fija la sub-meta. Es exactamente el estadístico con el que se construyen las etiquetas de referencia del banco (cap. 7, IT.7.1), de modo que la exactitud medida allí es la del juicio que usa el vuelo.

El servicio devuelve **la misma estructura que el VLM** —el estado de los nueve sectores para la capa estratégica, y si cada rumbo es transitable para el barrido (cap. 5, IT.5.5.3, IT.5.6)—, de modo que el resto del sistema no distingue la fuente. La auditoría guarda el p5 de cada sector en metros, para revisar cada decisión contra la distancia que la produjo.

### 6.12.3 Dónde corre y qué no es

La red **nunca corre dentro del lazo de 5 Hz**: corre en un hilo de servicio (Anexo 10, IT.A10.6.2), tarda ~110 ms en vuelo con la GPU compartida —la mitad de un ciclo, frente a ~0.8 s del VLM— y ocupa ~440 MiB de VRAM. Por eso no reemplaza al flujo en el lazo rápido: el flujo detecta un cierre en milisegundos, y la profundidad decide, cada segundo, hacia dónde está el espacio libre. La red **no lee el canal de profundidad del simulador**: recibe el mismo fotograma RGB que el flujo, como una red a bordo de un dron que solo tiene una cámara. Ese canal sigue fuera del lazo (cap. 5, IT.5.8), porque de él salen las etiquetas de referencia, y una guardia automatizada lo verifica.

### 6.12.4 Limitaciones

- **Dominio.** Depth Anything V2 se entrenó en parte con imágenes sintéticas, y la etiqueta del banco sale del mismo render que la red ve. En una cámara real el desempeño puede ser menor; la validación en imágenes reales está pendiente.
- **Escala métrica.** La variante para exteriores se ajustó con datos de conducción, a la altura de un auto. Las distancias absolutas a 10–30 m de altura no están calibradas: el umbral de 15 m funciona como corte de clasificación validado en el banco, no como una medición en metros.
- **Objetos finos y follaje.** Ramas, cables y copas semitransparentes son el caso más difícil para cualquier estimador denso; el lote del corredor arbolado de TownSim (Anexo 12, IT.A12.3.2) lo pone a prueba.
- **Sin memoria.** Cada consulta juzga un fotograma aislado, sin fusión temporal ni mapa.
- **Campo de visión.** Solo se analiza el recorte central; lo que queda a los costados del fotograma no participa del juicio.

## 6.13 Complementariedad entre flujo óptico y profundidad estimada

El **flujo óptico** detecta un cierre en milisegundos cuando el dron se traslada con textura suficiente, pero es ciego en hover, en giro puro, ante obstáculos centrados en el foco de expansión y ante superficies horizontales. La **profundidad estimada** no necesita traslación y ve esos casos, pero tarda demasiado para lo inminente: sirve para decidir el rodeo cada segundo. La interfaz entre ambos es **geométrica, no textual** —bloqueos por sector para el lazo rápido, sub-metas en coordenadas del mundo para el guiado—, y ninguno recibe la salida del otro, de modo que no hay que reconciliar dos descripciones de la escena con latencias distintas.

---

*La evaluación cuantitativa del estimador de flujo (curvas ROC, AUC, comparación con profundidad de referencia) se desarrolla en el capítulo 7; la de la profundidad estimada, en el capítulo 11 (IT.11.0). El análisis de los modos de falla de la percepción y su impacto en el comportamiento del lazo se presenta en el capítulo 9.*
