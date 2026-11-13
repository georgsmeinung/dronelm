# 7. Validación del estimador de TTC y calibración del campo de obstáculos

El capítulo 6 describe el estimador de flujo óptico y su salida, el `ObstacleField`. Este capítulo responde otra pregunta: **¿cómo sabemos que el estimador funciona?** Se recolectó un conjunto de datos etiquetado con la profundidad del simulador y se aplicó análisis de curva ROC para calibrar y evaluar los dos canales, TTC y ocupación.

## 7.1 Etiquetas de referencia a partir de la profundidad de AirSim: ventaja metodológica

**Etiqueta de referencia.** En este trabajo se llama *etiqueta de referencia* (en la bibliografía, *ground truth*) al valor correcto contra el que se compara, en el mismo instante, lo que estimó o respondió el sistema: por ejemplo, si el sector central está bloqueado a menos de 5 m, cuál es el TTC real o si un sector de la imagen está libre a 15 m. La etiqueta no la produce el sistema evaluado sino un instrumento independiente y más preciso, la profundidad planar del simulador, que el lazo de vuelo nunca lee (cap. 10, IT.10.4.1). Se calcula siempre en tres pasos: (1) se toma la profundidad del mismo cuadro que vio el sistema, con la misma cámara y el mismo campo de visión; (2) se resume la profundidad de cada región de interés con un percentil bajo, que representa lo más cercano de la región sin que lo arrastren píxeles sueltos; (3) una regla fija y explícita (un umbral de distancia o una fórmula, como la del TTC más abajo) convierte ese resumen en la etiqueta. Como la regla es fija y se puede auditar, la etiqueta no depende del juicio de una persona ni del sistema que se evalúa.

El canal de profundidad planar de AirSim es un subproducto de la rasterización sin costo adicional, de modo que permite etiquetas densas en las mismas condiciones de vuelo que la misión, sin instrumentación externa ([Shah et al., 2017](13-REFERENCIAS.md#ref-shah-2017); [Jansen et al., 2023](13-REFERENCIAS.md#ref-jansen-2023)). El TTC de referencia por celda es

$$TTC_{\text{gt}}(\text{celda}) = \frac{\text{percentil}_{20}(Z_{\text{celda}})}{\max(v_{\text{cierre}},\, \varepsilon)}$$

con $Z_{\text{celda}}$ las profundidades de la celda, $v_{\text{cierre}}$ la velocidad del vehículo proyectada sobre el eje óptico y $\varepsilon = 0.01$ m/s para evitar la división por cero en hover. La profundidad planar mide la distancia al plano focal y no la euclidiana; en el tercio central de la imagen la diferencia es inferior al 6 %, y se acepta como aproximación (desarrollo formal en el [Anexo 5](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md), IT.A5.5–A5.6).

## 7.2 Diseño del conjunto de datos de validación

`experiments/collect_ttc_dataset.py` registra, por ciclo y por celda de la grilla 3×3, el TTC estimado y el de referencia, la ocupación, la divergencia, la confianza de la celda y del FOE, la velocidad de traslación y la tasa de guiñada. El conjunto totaliza **3735 registros de celda** (415 fotogramas × 9 celdas) de tres escenarios de vuelo guiados: una **aproximación frontal** a una fachada a 1–6 m/s, que maximiza la expansión en el sector central; un **vuelo por un cañón urbano**, que activa los sectores laterales con el central mayormente libre; y **giros de guiñada sin traslación**, en los que el estimador debería declarar incertidumbre en lugar de obstáculos espurios.

Dos limitaciones condicionan su lectura. El conjunto se recolectó con el flujo a 320 px, y el vuelo usa 640 px (cap. 6, IT.6.3): los umbrales no están recalibrados a ese ancho. Y el escenario de giros quedó concentrado en guiñadas muy bajas (< 0.05 rad/s), sin presión real sobre la derotación —la validación en giros agresivos es el experimento D3 (IT.7.6)—; sin traslación, además, solo aporta negativos.

## 7.3 Resultados del canal de TTC: dos métricas, una interpretación correcta

El análisis produce dos números que parecen contradictorios:

**Métrica 1 — Correlación puntual:** Pearson $r \approx -0.034$ y error relativo mediano del 66 % (2359 celdas con confianza > 0.15); correlación de rangos de Spearman $\rho = 0.53$ sobre las mismas celdas.

**Métrica 2 — AUC ROC para detección binaria:** 0.97, 0.97 y 0.96 para el evento "colisión dentro de $\tau$ segundos" con $\tau = 1, 2, 3$ s (3139 celdas con TTC estimado finito; 61, 171 y 252 positivos).

**La correlación puntual es baja** porque el TTC de referencia tiene una cola muy larga —en vuelo lento la velocidad de cierre es casi nula y el TTC llega a cientos de segundos (mediana 119 s), mientras el estimado se mueve en otra escala (mediana 14 s)— y esos pares extremos llevan el $r$ de Pearson a cero; a eso se suman errores de escala sistemáticos del modelo de cámara. La correlación de rangos, que no depende de la escala, es moderada: el *ordenamiento* de los TTC se conserva en buena medida, aunque el valor en segundos no sea confiable.

**El AUC es alto** porque mide justamente esa propiedad: con probabilidad 0.96, el estimador le asigna un TTC menor a una celda peligrosa que a una segura elegidas al azar ([Fawcett, 2006](13-REFERENCIAS.md#ref-fawcett-2006)). Es el predicado que el control necesita: no saber que faltan 3.2 s, sino que *esta celda* es más peligrosa que *aquella*.

**El AUC no es uniforme.** El valor conjunto lo empuja el cañón urbano, con el obstáculo a los costados (0.97–0.98). En la aproximación frontal —el obstáculo cerca del Foco de Expansión, el caso más crítico para evadir— baja a 0.93, 0.90 y 0.85. Restringido a celdas con el dron en movimiento, el AUC conjunto se mantiene (0.985 para $\tau = 2$ s). Los registros no son independientes y no se estimó un intervalo de confianza del AUC.

**Formulación defendible del estimador:** "El TTC estimado es un *puntaje de riesgo de cierre calibrado por curva ROC*, cuyo valor numérico tiene unidades de segundos por construcción matemática del modelo (IT.6.7) pero no interpretación métrica directa. Los umbrales operativos son umbrales en esa escala de puntaje, derivados por criterio de Youden, no parámetros físicos independientes." La distinción entre *clasificador de riesgo* y *cronómetro* coincide con la literatura de advertencia de colisión monocular, que reporta correlación puntual pobre y detección binaria confiable ([Al-Kaff et al., 2017](13-REFERENCIAS.md#ref-al-kaff-2017); [Vera-Yanez et al., 2024](13-REFERENCIAS.md#ref-vera-yanez-2024)).

## 7.4 Derivación de umbrales operativos por índice de Youden

El índice de Youden ($J = \text{sensibilidad} + \text{especificidad} - 1$; [Youden, 1950](13-REFERENCIAS.md#ref-youden-1950)) elige el punto de la curva ROC más alejado de la diagonal. Para cada $\tau$:

| Tiempo de horizonte $\tau$ | Umbral de TTC (Youden) | Sensibilidad | Especificidad |
|---|---|---|---|
| 1 s | ~1.93 s | 0.90 | 0.94 |
| 2 s | ~3.18 s | 0.95 | 0.93 |
| 3 s | ~4.58 s | 0.96 | 0.89 |

El umbral para $\tau = 2$ s es el de evasión (redondeado a 3.2 s) y el de $\tau = 3$ s, el de zona segura (4.6 s); NB5.10 reproduce el cálculo. Ambos salen de la validación, no de un ajuste por comportamiento de vuelo, y el margen de 2 s cubre el tiempo de reacción del lazo (200 ms por ciclo) más la ejecución de la maniobra. La banda entre los dos umbrales es la ventana de advertencia de `navigate` (cap. 5, IT.5.3), en la que el lazo rápido corrige lateralmente sin esperar al lazo lento; además, la histéresis evita la oscilación entre evasión y crucero cuando el TTC flota alrededor del umbral.

## 7.5 Calibración del canal de ocupación (D2)

**Protocolo.** El experimento D2 capturó 196 frames en TownSim frente a una pared sólida, a cuatro velocidades de aproximación (0.5 a 3 m/s), con la etiqueta de referencia «profundidad central < 5 m» (29 positivos, 167 negativos), y barrió el umbral de ocupación sobre la curva ROC con el mismo criterio de Youden.

**Resultado.** AUC = 0.87; umbral óptimo de 0.011, con sensibilidad 0.93 y tasa de falsos positivos 0.22. La ocupación central nunca supera 0.082 en el dataset, de modo que un umbral fijado a ojo como 0.35 **no se dispararía en ningún frame** y la detección recaería íntegramente en el TTC. NB5.11 reproduce ambas cifras, y el umbral calibrado es el de la configuración y del código.

**Límites de la calibración.** Una sola escena y una sola geometría (una pared lisa), y solo 29 positivos, sin intervalo de confianza del umbral; uno de cada cinco frames sin obstáculo cercano vota bloqueo, un costo aceptado a cambio de la sensibilidad; la ocupación depende de la textura, y un umbral calibrado en TownSim puede no servir en CitySim (el calibrador por misión de `main.py` no se validó ni lo usa el ejecutor de lotes); y, por la limitación de la prueba de inliers del FOE (cap. 6, IT.6.6), el umbral se calibró con la confianza topada en 0.3.

| Métrica de validación | Canal TTC | Canal Ocupación |
|---|---|---|
| Protocolo de validación ROC | ✓ Completo | ✓ Realizado (dataset reducido) |
| Umbral derivado por Youden | ✓ (evasión: 3.2 s) | ✓ (0.011) |
| AUC reportada | 0.96–0.97 (frontal: 0.85–0.93) | 0.87 |
| Conjunto de datos | 415 fotogramas (3735 celdas) | 196 frames, una escena |

## 7.6 Validación de la derotación en giros agresivos (D3)

El experimento D3 capturó 250 frames frente a una pared a 5 m, a cinco tasas de guiñada comandadas (0 a 1.0 rad/s). En las cuatro tasas no nulas (18.7 a 63.9 °/s reales) el 100 % de los frames quedó degradado y con confianza del FOE nula: el estimador **se inhibe por sí mismo** y no entrega un TTC contaminado con confianza alta, como predice el umbral teórico del guard de rotación (~10 °/s a 5 Hz). Se validó la *inhibición*, no la *exactitud* de la derotación: no se ensayaron tasas entre 0 y 0.3 rad/s, de modo que no se midió el error de TTC en el tramo previo al guard, ni se ejercitó la reanudación de la estimación al cesar el giro. Ambas preguntas, junto con la validación en hardware real, quedan pendientes.

## 7.7 Implicaciones para el diseño del sistema

**El AUC de 0.96–0.97 justifica usar el TTC como señal primaria de evasión** en los escenarios guiados: a $\tau = 2$ s, el 95 % de las situaciones peligrosas se detecta a tiempo, con un 7 % de falsos positivos que disparan evasiones innecesarias. Los falsos negativos son más frecuentes de frente, y los cubren en parte la detección de contacto y la capa estratégica con profundidad estimada, que no depende de la traslación (cap. 6, IT.6.13).

**La baja correlación puntual justifica la banda de histéresis.** Si el TTC fuera un cronómetro confiable, bastaría un umbral; la incertidumbre de escala hace necesaria la ventana de advertencia, y la distancia en metros, que el TTC no da, la aporta en el lazo lento la profundidad estimada (cap. 6, IT.6.12).

**La discriminación medida en los escenarios guiados no se reproduce en vuelo.** La auditoría de distancia mínima de la corrida v4 (cap. 10, IT.10.6.1) permite comparar el campo de obstáculos registrado en vuelo con una etiqueta de referencia. En las 11 642 muestras de las corridas `slm` (NB1.11), con «obstáculo a menos de 5 m» como positivo (1003 positivos, casi todos de los lotes de TownSim con obstrucción), el sector central figura bloqueado en el 23 % de los positivos y en el 17 % de los negativos: en vuelo, el campo distingue poco más que al azar. La etiqueta no es la de IT.7.2 y el follaje domina los positivos, pero la diferencia con el AUC de los escenarios guiados es grande: esa validación no describe el comportamiento del estimador en las escenas de los lotes. Que el lazo complete las misiones con obstrucción se explica entonces menos por la percepción del flujo que por la salida de atascos y, en el brazo `slm`, por la reacción a contacto, que la FSM no tiene (cap. 11, IT.11.7).

**Corregir la prueba de inliers del FOE no mejora la discriminación.** La corrección (cap. 6, IT.6.6) se evaluó fuera de vuelo en NB1.12, sobre el video frontal de una corrida `slm` de cada lote con obstrucción; el video es un sustituto parcial de lo que vio el estimador, válido para comparar los dos estimadores sobre los mismos pares. Con la corrección, la confianza del FOE deja de estar topada y el sector central sale bloqueado en más ciclos (del 20–28 % al 31–47 %), y la regla de evasión o giro se dispara en el 33–37 % de los ciclos, frente al 19–28 %. Contra la etiqueta de distancia mínima menor a 5 m (808 muestras, 111 positivos), la sensibilidad sube de 0.20 a 0.37, pero la tasa de falsos positivos sube con ella, de 0.27 a 0.38: la corrección mueve el punto de operación sobre una curva casi diagonal —más evasiones, sin mejor separación— e invalida las calibraciones de este capítulo. Por eso no se aplicó a la configuración evaluada.

**La validación del canal de ocupación es parcial.** Está calibrado con una escena y 29 positivos (IT.7.5); antes de llevarlo a entornos más exigentes o a hardware real, la validación cruzada del umbral en escenas distintas debería completarse.
