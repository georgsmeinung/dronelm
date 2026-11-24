# 7. Validación del estimador de TTC y calibración del campo de obstáculos

El capítulo 6 describe el estimador de flujo óptico y su salida, el `ObstacleField`. Este capítulo responde otra pregunta: **¿cómo sabemos que el estimador funciona?** Se recolectó un conjunto de datos etiquetado con la profundidad del simulador y se aplicó análisis de curva ROC para calibrar y evaluar los dos canales, TTC y ocupación.

## 7.1 Etiquetas de referencia a partir de la profundidad de AirSim: ventaja metodológica

**Etiqueta de referencia.** En este trabajo se llama *etiqueta de referencia* (en la bibliografía, *ground truth*) al valor correcto contra el que se compara, en el mismo instante, lo que estimó o respondió el sistema: si el sector central está bloqueado a menos de 5 m, cuál es el TTC real o si un sector de la imagen está libre a 15 m. La produce un instrumento independiente y más preciso, la profundidad planar del simulador, que el lazo de vuelo nunca lee (cap. 10, IT.10.4.1): sobre el mismo cuadro que vio el sistema, la profundidad de cada región se resume con un percentil bajo —lo más cercano, sin que lo arrastren píxeles sueltos— y una regla fija y auditable la convierte en la etiqueta.

Ese canal es un subproducto de la rasterización, de modo que permite etiquetas densas en las mismas condiciones de vuelo, sin instrumentación externa ([Shah et al., 2017](13-REFERENCIAS.md#ref-shah-2017)). El TTC de referencia por celda es

$$TTC_{\text{gt}}(\text{celda}) = \frac{\text{percentil}_{20}(Z_{\text{celda}})}{\max(v_{\text{cierre}},\, \varepsilon)}$$

con $Z_{\text{celda}}$ las profundidades de la celda, $v_{\text{cierre}}$ la velocidad proyectada sobre el eje óptico y $\varepsilon = 0.01$ m/s; la profundidad planar difiere de la euclidiana en menos del 6 % en el tercio central de la imagen (Anexo 5, IT.A5.5–A5.6).

## 7.2 Diseño del conjunto de datos de validación

`experiments/collect_ttc_dataset.py` registra, por ciclo y por celda de la grilla 3×3, el TTC estimado y el de referencia, la ocupación, la confianza y la cinemática del vuelo: **3735 registros de celda** (415 fotogramas × 9 celdas) de tres escenarios guiados —una **aproximación frontal** a una fachada a 1–6 m/s, un **vuelo por un cañón urbano** con el obstáculo a los costados y **giros de guiñada sin traslación**—.

Dos limitaciones condicionan su lectura: el conjunto se recolectó con el flujo a 320 px, y el vuelo usa 640 px sin recalibrar (cap. 6, IT.6.3); y los giros quedaron concentrados en guiñadas muy bajas, sin presión real sobre la derotación (la validación en giros agresivos es D3, IT.7.6).

## 7.3 Resultados del canal de TTC: dos métricas, una interpretación correcta

El análisis produce dos números que parecen contradictorios.

**Métrica 1 — Correlación puntual:** Pearson $r \approx -0.034$ y error relativo mediano del 66 % (2359 celdas con confianza > 0.15); correlación de rangos de Spearman $\rho = 0.53$ sobre las mismas celdas.

**Métrica 2 — AUC ROC para detección binaria:** 0.97, 0.97 y 0.96 para el evento "colisión dentro de $\tau$ segundos" con $\tau = 1, 2, 3$ s (3139 celdas con TTC estimado finito; 61, 171 y 252 positivos).

**La correlación puntual es baja** porque el TTC de referencia tiene una cola muy larga —en vuelo lento llega a cientos de segundos (mediana 119 s), mientras el estimado se mueve en otra escala (mediana 14 s)— y a eso se suman errores de escala del modelo de cámara; la correlación de rangos, moderada, muestra que el *ordenamiento* se conserva.

**El AUC es alto** porque mide justamente esa propiedad: con probabilidad 0.96, el estimador le asigna un TTC menor a una celda peligrosa que a una segura elegidas al azar ([Fawcett, 2006](13-REFERENCIAS.md#ref-fawcett-2006)). Es el predicado que el control necesita: no saber que faltan 3.2 s, sino que *esta celda* es más peligrosa que *aquella*.

**El AUC no es uniforme.** Lo empuja el cañón urbano (0.97–0.98); en la aproximación frontal —el obstáculo cerca del Foco de Expansión, el caso más crítico— baja a 0.93, 0.90 y 0.85. Los registros no son independientes y no se estimó un intervalo de confianza del AUC.

**Formulación defendible del estimador.** El TTC estimado es un *puntaje de riesgo de cierre calibrado por curva ROC*, con unidades de segundos por construcción (IT.6.7) pero sin interpretación métrica directa, y sus umbrales son umbrales en esa escala, no parámetros físicos. La distinción entre *clasificador de riesgo* y *cronómetro* coincide con la literatura de advertencia de colisión monocular ([Al-Kaff et al., 2017](13-REFERENCIAS.md#ref-al-kaff-2017); [Vera-Yanez et al., 2024](13-REFERENCIAS.md#ref-vera-yanez-2024)).

## 7.4 Derivación de umbrales operativos por índice de Youden

El índice de Youden ($J = \text{sensibilidad} + \text{especificidad} - 1$; [Youden, 1950](13-REFERENCIAS.md#ref-youden-1950)) elige el punto de la curva ROC más alejado de la diagonal. Para cada $\tau$:

| Tiempo de horizonte $\tau$ | Umbral de TTC (Youden) | Sensibilidad | Especificidad |
|---|---|---|---|
| 1 s | ~1.93 s | 0.90 | 0.94 |
| 2 s | ~3.18 s | 0.95 | 0.93 |
| 3 s | ~4.58 s | 0.96 | 0.89 |

El umbral para $\tau = 2$ s es el de evasión (redondeado a 3.2 s) y el de $\tau = 3$ s, el de zona segura (4.6 s); NB5.10 reproduce el cálculo. El margen de 2 s cubre el tiempo de reacción del lazo más la ejecución de la maniobra, y la banda entre ambos es la ventana de advertencia de `navigate` (cap. 5, IT.5.3), con histéresis que evita la oscilación entre evasión y crucero.

## 7.5 Calibración del canal de ocupación (D2)

**Protocolo.** El experimento D2 capturó 196 frames en TownSim frente a una pared sólida, a cuatro velocidades de aproximación (0.5 a 3 m/s), con la etiqueta de referencia «profundidad central < 5 m» (29 positivos, 167 negativos), y barrió el umbral de ocupación sobre la curva ROC con el mismo criterio de Youden.

**Resultado.** AUC = 0.87; umbral óptimo de 0.011, con sensibilidad 0.93 y tasa de falsos positivos 0.22. La ocupación central nunca supera 0.082 en el dataset, de modo que un umbral fijado a ojo como 0.35 **no se dispararía en ningún frame** y la detección recaería íntegramente en el TTC. NB5.11 reproduce ambas cifras, y el umbral calibrado es el de la configuración y del código.

**Límites de la calibración.** Una sola escena (una pared lisa) y 29 positivos, sin intervalo de confianza del umbral; uno de cada cinco fotogramas sin obstáculo cercano vota bloqueo; la ocupación depende de la textura, de modo que un umbral calibrado en TownSim puede no servir en CitySim; y el umbral se calibró con la confianza del FOE topada en 0.3 (cap. 6, IT.6.6).

| Métrica de validación | Canal TTC | Canal Ocupación |
|---|---|---|
| Protocolo de validación ROC | ✓ Completo | ✓ Realizado (dataset reducido) |
| Umbral derivado por Youden | ✓ (evasión: 3.2 s) | ✓ (0.011) |
| AUC reportada | 0.96–0.97 (frontal: 0.85–0.93) | 0.87 |
| Conjunto de datos | 415 fotogramas (3735 celdas) | 196 frames, una escena |

## 7.6 Validación de la derotación en giros agresivos (D3)

El experimento D3 capturó 250 fotogramas frente a una pared a 5 m, a cinco tasas de guiñada (0 a 1.0 rad/s). En las cuatro tasas no nulas el 100 % de los fotogramas quedó degradado y con confianza del FOE nula: el estimador **se inhibe por sí mismo** y no entrega un TTC contaminado. Se validó la *inhibición*, no la *exactitud* de la derotación: el tramo entre 0 y 0.3 rad/s, la reanudación tras el giro y el hardware real quedan pendientes.

## 7.7 Qué dispara la evasión en vuelo y alcance de la validación

**Qué valida este capítulo.** El AUC de 0.96–0.97 (0.85–0.93 de frente) mide el TTC como puntaje de riesgo en los escenarios guiados de IT.7.2, con el flujo a 320 px: a $\tau = 2$ s, el 95 % de las situaciones peligrosas se detecta a tiempo, con un 7 % de falsos positivos, y de ahí salen los umbrales de 3.2 y 4.6 s. La baja correlación puntual justifica la banda de histéresis: si el TTC fuera un cronómetro confiable bastaría un umbral, y la distancia en metros, que el TTC no da, la aporta en el lazo lento la profundidad estimada (cap. 6, IT.6.12).

**Qué dispara la evasión en vuelo.** Esta es la explicación de referencia del informe; los capítulos 5, 6 y 12 remiten a ella. En el brazo `depth2loop` la evasión tiene tres disparadores (cap. 5, IT.5.3.2):

- **Contacto**: la IMU o el muro ciego (regla 4), que no dependen del flujo.
- **Ocupación**: una celda está bloqueada cuando su ocupación supera 0.011 (IT.7.5), y el sector central bloqueado dispara la evasión con TTC ≤ 4.6 s (regla 7) o sin condición de TTC (regla 7b).
- **TTC**: un TTC central ≤ 3.2 s, o un TTC mínimo ≤ 4.6 s, disparan la evasión por sí solos con una confianza de celda ≥ 0.15 (reglas 7 y 7b).

Tres condiciones del código evaluado alejan ese reparto del que se validó. La prueba de *inliers* del FOE está invertida (cap. 6, IT.6.6): la confianza del FOE queda topada en 0.3 en casi todos los ciclos (la supera en el 7.6 % de los ciclos con flujo de la corrida de referencia), el TTC casi nunca alcanza la confianza de 0.35 con la que podría bloquear una celda por sí solo, y entra en la decisión solo por las reglas 7 y 7b, calculado con un FOE degradado. Los umbrales se calibraron con el flujo a 320 px y el vuelo usa 640 px, sin recalibrar (IT.7.2; cap. 6, IT.6.3). Y durante los giros el estimador no estima (cap. 6, IT.6.11): en los brazos que maniobran, el campo es nuevo solo en el 37–41 % de los ciclos (NB1.11). En vuelo, entonces, el bloqueo del sector central lo decide sobre todo la ocupación, el TTC actúa con una confianza que la validación no cubrió, y el contacto cubre lo que el flujo no ve.

**La discriminación medida en los escenarios guiados no se reproduce en vuelo.** La auditoría de distancia mínima de la corrida v4 (cap. 10, IT.10.6.1) permite comparar el campo de obstáculos registrado en vuelo con una etiqueta de referencia. En las 11 642 muestras de las corridas `depth2loop` (NB1.11), con «obstáculo a menos de 5 m» como positivo (1003 positivos, casi todos de los lotes de TownSim con obstrucción), el sector central figura bloqueado en el 23 % de los positivos y en el 17 % de los negativos: en vuelo, el campo distingue poco más que al azar. La etiqueta no es la de IT.7.2 y el follaje domina los positivos, pero la diferencia con el AUC de los escenarios guiados es grande: esa validación no describe el comportamiento del estimador en las escenas de los lotes. Que el lazo complete las misiones con obstrucción se explica entonces menos por la percepción del flujo que por la salida de bloqueos y, en el brazo `depth2loop`, por la reacción a contacto, que la FSM no tiene (cap. 11, IT.11.7).

**Corregir la prueba de inliers del FOE no mejora la discriminación.** La corrección se evaluó fuera de vuelo en NB1.12, sobre el video frontal de una corrida `depth2loop` de cada lote con obstrucción. Con ella el sector central sale bloqueado en más ciclos (del 20–28 % al 31–47 %), y contra la etiqueta de distancia mínima menor a 5 m (808 muestras, 111 positivos) la sensibilidad sube de 0.20 a 0.37, pero la tasa de falsos positivos sube con ella, de 0.27 a 0.38: más evasiones, sin mejor separación, y con las calibraciones de este capítulo invalidadas. Por eso no se aplicó a la configuración evaluada.

**La validación del canal de ocupación es parcial.** Está calibrado con una escena y 29 positivos (IT.7.5); antes de llevarlo a entornos más exigentes o a hardware real, la validación cruzada del umbral en escenas distintas debería completarse.
