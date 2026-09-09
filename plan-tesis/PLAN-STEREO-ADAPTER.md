# Plan stereo-adapter — escenario intermedio de bajo costo entre monocular y binocular

**Fecha:** 2026-09-09
**Estado:** exploratorio, no comprometido.
**Posición en la escalera de costo de hardware:** este plan es un escalón propio, **más barato que
montar una segunda cámara** (`PLAN-BINOCULAR.md`) y estrictamente superior al monocular actual frente
a la maldición monocular (`informe/anexos/A7-MALDICION-MONOCULAR-ESTEREO.md`). No depende de que
`PLAN-BINOCULAR.md` se ejecute antes ni después: es una alternativa autocontenida a evaluar en su
propio mérito, no una variante o extensión de aquel plan.

| Opción | Sensores físicos | Costo/peso/integración | ¿Resuelve la maldición monocular (Anexo 7, §A7.1)? |
|---|---|---|---|
| Monocular (actual) | 1 | mínimo (ya implementado) | no |
| **Adaptador estéreo de un sensor (este plan)** | **1** | **bajo** — una sola cámara, una sola interfaz eléctrica, óptica pasiva (espejos/prismas) añadida | **sí**, con pérdida de resolución por ojo |
| Dos cámaras separadas (`PLAN-BINOCULAR.md`) | 2 | medio — dos módulos completos, dos interfaces, posible necesidad de sync de hardware | sí, a resolución completa por ojo |
| LiDAR (fuera de alcance, Anexo 7 §A7.4) | 1 (activo) | alto — peso, consumo, costo | parcialmente (con limitaciones propias en follaje, Anexo 7 §A7.5.2) |

**Origen:** discusión sobre si, en vez de montar dos cámaras físicas separadas, tiene sentido resolver
la maldición monocular con un **adaptador estereográfico de una sola cámara** (*single-camera stereo
rig* / *stereo adapter* / *biprism stereo*) — el mismo principio óptico de los adaptadores estéreo
comerciales usados en endoscopía y macrofotografía: un juego de espejos o prismas redirige dos vistas
con ángulos distintos hacia dos mitades del mismo sensor, de modo que la salida nativa del hardware ya
es **una sola imagen compuesta**, con las dos vistas lado a lado (el mismo principio que el formato
*side-by-side* de cámaras VR/360 estéreo). Vale la pena anclarlo a ese antecedente real en la tesis: es
hardware existente y barato, no una idea ad hoc.

**Objetivo del experimento (si se ejecuta):** verificar si esta variante de un solo sensor alcanza para
sacar al sistema del modo de falla documentado en `townsim_ini` (`informe/11-RESULTADOS.md`, §11.4.2b)
sin pagar el costo de hardware de una segunda cámara — y, si no alcanza, cuantificar cuánto le falta
para decidir con datos si conviene escalar directamente a `PLAN-BINOCULAR.md`.

---

## 0. Por qué es la opción a evaluar primero

Para la plataforma objetivo de este trabajo (UAV urbano pequeño, §1.2), un solo sensor con óptica
plegada es la reducción de costo, peso y complejidad de integración eléctrica más agresiva que sigue
resolviendo el problema estructural identificado en el Anexo 7 (§A7.1.2: flujo/evidencia nula cerca
del Foco de Expansión). Antes de justificar el gasto de una segunda cámara completa, tiene sentido
preguntar si la mitad de esa inversión de hardware ya alcanza:

- **Sincronización perfecta gratis.** Un único sensor con un único obturador: no hay desfase temporal
  entre "ojo" izquierdo y derecho. Dos cámaras separadas necesitan trigger compartido o toleran un
  desfase — crítico si el dron se mueve rápido cerca de ramas, que es exactamente el régimen de
  `townsim_ini`.
- **Consistencia fotométrica perfecta.** Mismo sensor, mismo exposure, mismo balance de blancos: los
  dos canales son fotométricamente idénticos, lo cual ayuda al matching de disparidad (menos falsos
  negativos por diferencias de brillo/color entre cámaras, un ruido que un par de cámaras separadas sí
  tiene).
- **Baseline flexible más allá del chasis.** Con espejos/prismas se puede lograr una baseline efectiva
  mayor que el ancho físico del dron — relevante porque la precisión de profundidad depende de la
  baseline ($\sigma_Z \propto Z^2/(fB)$, Anexo 7 §A7.5.1), y un dron chico limita físicamente cuánto se
  pueden separar dos cámaras montadas directamente en el chasis.

El costo que hay que pagar por esto es conocido y acotado: pérdida de resolución efectiva por ojo
(cada mitad del sensor cubre aproximadamente la mitad del ancho útil), calibración algo más compleja
(viñeteo/aberración de la óptica plegada), y menor tolerancia mecánica en hardware real. Ninguno de los
tres invalida la propuesta de entrada — son trade-offs a medir, no descartar a priori.

---

## 1. Trade-offs a declarar explícitamente

### 1.1 Ventajas frente a monocular puro (actual)

Resuelve directamente el mecanismo identificado como causa del fracaso en `townsim_ini` (Anexo 7,
§A7.1–§A7.2): la disparidad de un obstáculo centrado en la trayectoria de vuelo no depende de su
posición respecto de ningún FOE, y no requiere que el vehículo se mueva para generar paralaje —
profundidad métrica a partir de un único instante.

### 1.2 Ventajas frente a dos cámaras separadas

- Sincronización y consistencia fotométrica perfectas "gratis" (§0).
- Baseline potencialmente mayor que el ancho del chasis.
- Un solo módulo de cámara, una sola interfaz eléctrica: menor huella de integración en una
  *companion computer* de bajo consumo (Jetson Nano/Orin, cap. 12 §12.4), relevante para la fase de
  transferencia a hardware físico.

### 1.3 Costos a declarar frente a ambas alternativas

- **Pérdida de resolución efectiva.** Cada "ojo" recibe aproximadamente la mitad del ancho (o del
  área) del sensor comparado con usar un sensor completo por cámara — afecta la densidad de puntos
  válidos disponibles para el matching de disparidad en zonas de textura fina (ramas), agravando el
  problema de ambigüedad de correspondencia sobre follaje ya señalado en el Anexo 7 (§A7.5.1).
- **Calibración no trivial.** Aunque sea un solo sensor, sigue haciendo falta calibración estéreo
  completa (intrínsecos + extrínsecos de cada "cámara virtual"), porque la geometría de espejos/prismas
  casi nunca da una relación perfectamente simétrica ni libre de distorsión: viñeteo en los bordes de
  cada mitad, y posible aberración cromática si se usan prismas en vez de solo espejos.
- **Menor tolerancia mecánica en hardware real.** Cualquier desalineación de los espejos rompe la
  geometría epipolar asumida — un tema de validación de hardware (impresión 3D, montaje), fuera del
  alcance del pipeline de software, pero a declarar como riesgo de la vía de transferencia física.

### 1.4 El cambio de pipeline es de captura, no de algoritmo

En vez de recibir dos streams de dos cámaras, se recibe **un solo frame** que se recorta en mitad
izquierda / mitad derecha, se le aplica rectificación estéreo con los parámetros calibrados del rig, y
de ahí en más el pipeline (matching de disparidad → profundidad → `ObstacleField`) es el mismo que el
de cualquier sistema estéreo de dos cámaras. Es un cambio de *front-end* de captura, no del algoritmo
de percepción — lo cual acota el riesgo de implementación de esta variante.

---

## 2. Emulación en AirSim: por qué el atajo ingenuo es incorrecto

La tentación obvia sería: "en simulación no hace falta emular la óptica del adaptador, porque lo que el
adaptador logra en hardware real (dos vistas con baseline conocida) se obtiene gratis poniendo dos
cámaras AirSim con el offset deseado en `settings.json`, sin las limitaciones ópticas reales" — y eso es
cierto **si el objetivo es solo validar el algoritmo de percepción estéreo en abstracto**.

Pero el objetivo específico de este plan es que **los resultados de simulación reflejen fielmente la
pérdida de resolución** de la versión de bajo costo, para poder comparar en la tesis "estéreo real de
un solo sensor" contra la línea base monocular sin sobreestimar lo que lograría el hardware real. Para
eso hay que simular explícitamente el efecto que el adaptador tiene sobre la imagen, no solo el
paralaje.

### 2.1 Cómo funciona el hardware real que se está emulando

La óptica del adaptador separa dos vistas y proyecta cada una sobre una porción del mismo sensor: la
salida nativa del hardware ya es **una sola imagen compuesta**, con las dos vistas lado a lado (formato
*side-by-side*, igual que las cámaras VR/360 estéreo). El paso de "separar en dos ojos" ocurre
**después**, en software, no en el sensor.

### 2.2 Pipeline de emulación (fase SA1)

**Archivos involucrados:** `airsim-settings/settings.json` y un módulo nuevo,
`airsim-loop/src/hardware/stereo_adapter.py`, que se intercala entre la captura cruda de AirSim y el
resto del pipeline de percepción.

1. **Dos cámaras virtuales en `settings.json`**, con el offset de baseline real del adaptador que se
   quiera modelar (sección `Vehicles.Drone1.Cameras`, dos entradas `front_left`/`front_right` con
   offset relativo en $Y$). Esto da el paralaje correcto — es la única pieza de configuración que
   coincide con lo que también usaría un par de dos cámaras completas, pero aquí es solo un medio para
   generar el frame compuesto (paso 3), no la fuente final de percepción.
2. **Redimensionar cada render** a la fracción de resolución que le correspondería a su mitad del
   sensor real que se quiere emular. Si el sensor objetivo tiene, p. ej., 1920 px de ancho total y cada
   mitad se lleva la mitad, cada render de AirSim (que sale a resolución completa) se downsamplea a
   960 px de ancho antes de componerlo. El factor de downsample es un parámetro nuevo,
   `STEREO_ADAPTER_HALF_WIDTH_PX`, derivado del sensor físico que se quiera modelar.
3. **Componer un único frame** pegando las dos mitades redimensionadas lado a lado (izquierda +
   derecha concatenadas horizontalmente). Este frame compuesto es la "captura cruda" simulada: lo que
   saldría directamente del sensor del adaptador real.
4. **Recién en el pipeline de procesamiento**, volver a partir ese frame compuesto en sus dos mitades,
   aplicar rectificación estéreo calibrada (fase SA3) y seguir con el matching de disparidad (fase SA4).

### 2.3 Ventaja metodológica de armar el pipeline en dos etapas (compone → separa)

Si se implementa así — un bloque que **genera** el frame combinado (exclusivo de simulación, porque
AirSim no tiene un sensor de adaptador real) y un segundo bloque que lo **separa y procesa** (fases
SA3–SA4, sin distinción de si el frame vino de simulación o de hardware real) — el bloque de
procesamiento de ahí en más es **literalmente el mismo código** que se usaría con el adaptador físico:
solo cambia de dónde viene el frame compuesto. El trabajo de simulación queda directamente transferible
a la fase de hardware real (cap. 12, §12.4), no como un atajo específico de AirSim.

```
[AirSim front_left]  →  downsample a mitad de ancho  ┐
                                                        ├→ concat horizontal → frame compuesto (SA1)
[AirSim front_right] →  downsample a mitad de ancho  ┘
                                                              │
                                    (único bloque exclusivo de simulación)
                                                              │
                                                              ▼
                     split en mitad izq/der → rectificación → StereoSGBM → profundidad
                     (idéntico en simulación y en el adaptador físico real)
```

---

## 3. Detalles de fidelidad opcionales (fase SA2)

Dos efectos que tienen los adaptadores reales y que conviene decidir explícitamente si entran en el
alcance de la tesis o se declaran como supuesto simplificador:

- **Banda muerta / gap entre las dos mitades.** Por el grosor físico de los espejos o el soporte
  central del adaptador, suele haber una franja sin información óptica útil entre ambas vistas. Se
  emula con un relleno negro (o recorte) de `STEREO_ADAPTER_GAP_PX` columnas entre las dos mitades del
  frame compuesto en el paso 3 de §2.2.
- **Inversión de una de las vistas.** Según la configuración óptica del adaptador (número de
  reflexiones), una de las dos vistas puede llegar espejada al sensor y requerir un flip horizontal en
  software antes de la rectificación. Se emula con un flag `STEREO_ADAPTER_RIGHT_MIRRORED` que aplica
  `cv2.flip(..., 1)` a la mitad derecha antes de componerla.

Ninguno de los dos es difícil de implementar; la decisión pendiente es si aportan a la validez del
experimento (¿el matching de disparidad es sensible al gap o solo estético?) lo suficiente como para
justificar el parámetro extra, o si conviene dejarlos fuera del alcance y declararlos como limitación
simplificadora del modelo de adaptador usado en la tesis.

---

## Fase SA3 — Rectificación y calibración

A diferencia de dos cámaras AirSim perfectamente paralelas (donde la rectificación completa es
opcional, porque las líneas epipolares ya son horizontales por construcción), el frame compuesto de
este plan simula deliberadamente el degradado de una óptica real: si se activan los detalles de
fidelidad de la fase SA2 (banda muerta, inversión), o si se decide inyectar viñeteo/distorsión
asimétrica sintética para modelar la óptica plegada con mayor fidelidad (§1.3), la rectificación deja de
ser una identidad y debe resolverse con matrices de calibración reales, no asumidas.

Matrices de calibración a derivar (reusando el modelo pin-hole del Anexo 5, §A5.1): $f_x, f_y, c_x, c_y$
para cada mitad del frame compuesto (ajustados al `STEREO_ADAPTER_HALF_WIDTH_PX` de la fase SA1, no a la
resolución completa de la cámara frontal actual), y la matriz de traslación estéreo $T = (B, 0, 0)^T$
con $B$ = `STEREO_ADAPTER_BASELINE_M`.

Chequeo de consistencia sugerido: sobre una escena estática de calibración (p. ej. una pared plana a
distancia conocida en MiniSim), verificar que la disparidad medida $d$ reproduce la distancia esperada
vía $Z = f_x B / d$ dentro de una tolerancia razonable — mismo protocolo que la validación TTC del
cap. 7, §7.5, adaptado a distancia estéreo.

---

## Fase SA4 — Motor de disparidad y profundidad métrica

**Archivo nuevo:** `airsim-loop/src/perception/stereo_depth.py`, hermano de `flow_ttc.py`.

Línea de base (barata, determinista, sin dependencias nuevas más allá de OpenCV, ya dependencia del
proyecto vía `cv2` en `flow_ttc.py`):

```python
stereo = cv2.StereoSGBM_create(
    minDisparity=0,
    numDisparities=STEREO_NUM_DISPARITIES,   # múltiplo de 16
    blockSize=STEREO_BLOCK_SIZE,
    P1=8 * 3 * STEREO_BLOCK_SIZE ** 2,
    P2=32 * 3 * STEREO_BLOCK_SIZE ** 2,
    disp12MaxDiff=1,
    uniquenessRatio=10,
    speckleWindowSize=100,
    speckleRange=32,
)
disparity = stereo.compute(left_gray, right_gray).astype(np.float32) / 16.0
depth = (CAMERA_FX_HALF * STEREO_ADAPTER_BASELINE_M) / np.maximum(disparity, STEREO_MIN_DISPARITY_PX)
```

`CAMERA_FX_HALF` es la distancia focal recalibrada para el ancho reducido de cada mitad (fase SA3), no
la $f_x=554.0$ px de la cámara frontal a resolución completa (Anexo 5, §A5.1.2) — usar la focal
equivocada aquí introduciría un sesgo sistemático de escala en toda la profundidad estimada.

**Nota metodológica a respetar en la implementación:** la profundidad debe salir de este *matching*
real, con su ruido de correspondencia incluido — nunca leerse directamente del `DepthPlanar` de AirSim
(que sigue existiendo en el cliente solo para depuración/validación offline, fase SA7). Si el canal de
decisión terminara usando el ground truth, se estaría comparando el sistema contra un sensor ideal en
vez del adaptador de bajo costo real que se busca evaluar.

Variables de entorno a introducir: `STEREO_ADAPTER_BASELINE_M`, `STEREO_ADAPTER_HALF_WIDTH_PX`,
`STEREO_NUM_DISPARITIES`, `STEREO_BLOCK_SIZE`, `STEREO_MIN_DISPARITY_PX`, `STEREO_MAX_RANGE_M`.

---

## Fase SA5 — Adaptador hacia `ObstacleField`

**Archivo nuevo:** `StereoObstacleEstimator` en `stereo_depth.py`, con la misma forma de interfaz que
`FlowTTCEstimator.estimate(curr_image, prev_image, telemetry, prev_telemetry) -> ObstacleField`
(`src/agents/graph.py`, función `perception_node`), para que sea un reemplazo *drop-in*.

Diferencias clave respecto del estimador de flujo:

- **No necesita `prev_image` ni `prev_telemetry`.** La profundidad estéreo es un observable de un
  único instante (Anexo 7, §A7.3) — a diferencia de flujo óptico, que requiere el par de frames
  $t-1, t$. Esta es la ventaja central que motiva el plan: el estimador produce evidencia útil incluso
  en el primer ciclo de vuelo o durante un hover prolongado.
- **Mapeo a celdas sector×banda:** dividir el mapa de profundidad (mismo *grid* 3×3 que usa
  `obstacle_field.py`, `SECTORS`/`BANDS`) y calcular, por celda, `occupancy` como fracción de píxeles con
  profundidad por debajo de un umbral de bloqueo en metros (`STEREO_OCCUPANCY_RANGE_M`), y `confidence`
  como fracción de píxeles con disparidad válida (no en el piso de ruido ni saturados en
  `STEREO_MAX_RANGE_M`) — con el descuento adicional de que, a la mitad de resolución de este plan, la
  cantidad absoluta de píxeles disponibles por celda es menor que en un par de dos cámaras completas,
  lo cual reduce la confianza estadística de cada celda de forma medible (fase SA7).
- **`ttc_s` derivado, no medido directamente.** El estéreo da distancia, no tiempo-a-colisión; para
  poblar el mismo campo `ttc_s` que consume `policy_router`, estimarlo como $TTC \approx
  Z / V_{\text{cierre}}$ usando la componente de velocidad hacia adelante de la telemetría actual, con
  el mismo cuidado de devolver `inf` si la velocidad de cierre es ~0.
- **`source` nuevo en `ObstacleField`:** agregar `"stereo_adapter"` a los valores documentados en el
  dataclass (`"flow" | "degraded" | "none"`, `obstacle_field.py`), distinto de un eventual `"stereo"` de
  dos cámaras completas — para poder diferenciar en los logs/`summary.json` de qué variante de hardware
  provino cada `ObstacleField`, dato relevante para la fase SA8.

---

## Fase SA6 — Integración en el grafo de control

**No se agregan nodos nuevos al `StateGraph`** (`src/agents/graph.py`): el cambio vive enteramente
dentro de `perception_node`, que hoy llama a `flow_ttc_estimator.estimate(...)`. Mismas tres variantes
de integración que cualquier backend estéreo (sustitución simple, fusión con flujo óptico, o
especialización por sector — solo estéreo en el sector `centro`, donde vive el punto ciego del FOE,
dejando flujo óptico para `izquierda`/`derecha`), seleccionables vía `PERCEPTION_BACKEND=flow|
stereo_adapter|fusion`, siguiendo el mismo patrón ya usado por `AGENT_ARM`.

`policy_router`, `evasive_node`, `deliberative_node`, `fsm_node`, `girar_90_node` y el `summary_text()`
que arma el prompt del SLM **no requieren ningún cambio**: todos leen `ObstacleField` por su API
pública, sin importar si el origen es flujo óptico, un adaptador de un sensor o dos cámaras completas.

---

## Fase SA7 — Validación offline contra ground truth

Antes de volar con este canal dentro del lazo de decisión, replicar el protocolo de validación que el
cap. 7 aplicó al TTC de flujo óptico (§7.5: curva ROC, umbral óptimo por índice de Youden) contra el
mapa de profundidad de referencia (`DepthPlanar`). Aquí es correcto usar el ground truth porque el
objetivo es *evaluar el error del adaptador*, no alimentar una decisión de vuelo con él.

Métrica específica de esta variante, no compartida con un par de dos cámaras completas: cuantificar el
**costo real de la pérdida de resolución** — error de profundidad del adaptador (media resolución por
ojo) a distintas distancias, comparado contra lo que se obtendría con dos sensores completos a la misma
baseline. Esta comparación es la que en definitiva permite decidir, con datos y no por intuición, si el
ahorro de hardware de un solo sensor justifica la pérdida de precisión frente a montar dos cámaras.

Corte adicional recomendado: escenas de follaje denso (`townsim_ini`) vs. escenas urbanas limpias
(`townsim_clear`), para verificar si la pérdida de resolución agrava específicamente la ambigüedad de
correspondencia sobre textura repetitiva (Anexo 7, §A7.5.1) más de lo que lo haría un par de dos
cámaras completas en la misma escena.

---

## Fase SA8 — Protocolo experimental comparativo

Mismo protocolo estadístico ya validado en el cap. 11 (§11.3.2): K=5 semillas, prueba U de
Mann-Whitney bilateral, Cliff's δ, corrección de Bonferroni. Diseño de tres puntas (no solo dos, porque
la pregunta relevante de este plan es de costo/beneficio relativo, no solo "¿ayuda o no?"):

| Comparación | Escenario | Pregunta que responde |
|---|---|---|
| Monocular vs. adaptador de un sensor | `townsim_ini` | ¿el escalón de menor costo ya saca al sistema del modo de falla documentado en §11.4.2b? |
| Adaptador de un sensor vs. dos cámaras completas (si `PLAN-BINOCULAR.md` también se ejecuta) | `townsim_ini` | ¿cuánto rendimiento se pierde por la mitad de resolución, en términos de tasa de éxito/distancia recorrida? |
| Adaptador de un sensor vs. monocular | `townsim_clear` / `citysim_clear` | ¿el canal nuevo introduce overhead o regresión en los escenarios de control ya resueltos (cap. 11, §11.1–11.3)? |

Si la primera fila ya muestra una mejora estadísticamente significativa comparable a la que se esperaría
de dos cámaras completas, el resultado natural es recomendar esta variante como la de mejor
costo/beneficio y no ejecutar `PLAN-BINOCULAR.md` en absoluto. Si la mejora es parcial (progresa más
pero no completa la ruta, o reduce deadlocks sin llegar a 5/5), la segunda fila cuantifica si vale la
pena escalar al par de dos cámaras completas.

---

## Fase SA9 — Riesgos y criterios de aborto temprano

- **Latencia de `simGetImages` duplicada** (dos cámaras virtuales en la fase SA1) empuja el ciclo por
  debajo de los 5 Hz nominales del lazo, o el cómputo de StereoSGBM no entra en el presupuesto de
  20–50 ms por ciclo compartido con el SLM (cap. 6, §6.1) → considerar bajar aún más
  `STEREO_ADAPTER_HALF_WIDTH_PX` antes de descartar la propuesta.
- **Error de profundidad en follaje denso, ya degradado por la mitad de resolución, comparable a la
  falta de evidencia monocular** (fase SA7) → la pérdida de resolución de este escalón económico anula
  la ventaja de eliminar el punto ciego del FOE; es la señal concreta de que conviene escalar
  directamente a `PLAN-BINOCULAR.md` en vez de seguir ajustando esta variante.
- **Baseline insuficiente para el rango de detección necesario** a la velocidad de crucero usada en
  `townsim_ini` → recalcular el horizonte de detección confiable antes de correr la fase SA8; puede ser
  necesario ajustar la velocidad de aproximación del brazo evaluado en este escenario específico, no
  solo el hardware.
- **Mejora medible en `townsim_ini` pero regresión en `*_clear`** → no es un resultado negativo del
  experimento, es la señal de que la variante correcta para producción es fusión selectiva
  (fase SA6, variante 2 o 3), no sustitución total del canal de percepción.

---

## 4. Camino de decisión frente a `PLAN-BINOCULAR.md`

Este plan y `PLAN-BINOCULAR.md` no son mutuamente excluyentes ni secuenciales por obligación — son dos
puntos de la misma escalera de costo de hardware (tabla de §0), y cada uno se sostiene solo. La
recomendación de orden de ejecución, si se decidiera avanzar con alguno:

1. **Ejecutar primero este plan** (adaptador de un sensor): es la inversión de hardware más barata que
   sigue atacando la causa raíz identificada en el Anexo 7 (§A7.1.2), y la fase SA8 ya da una respuesta
   directa a si alcanza o no.
2. **Escalar a `PLAN-BINOCULAR.md` (dos cámaras completas) solo si la fase SA9 detecta que la pérdida de
   resolución de este escalón anula el beneficio** — es decir, solo si los datos muestran que hace falta
   la resolución completa por ojo para que el matching de disparidad sea confiable en follaje denso.
3. **No ejecutar ninguno de los dos y quedarse con la propuesta teórica del Anexo 7** si la fase SA7
   (validación offline, antes de volar) ya muestra que ni siquiera a resolución completa el estéreo
   supera significativamente al vacío de evidencia monocular en el punto adversarial de `townsim_ini`.

---

## 5. Antecedentes a buscar para la bibliografía (si se ejecuta)

Términos de búsqueda para anclar esta variante a literatura real, sin fabricar citas antes de
verificarlas: *stereo adapter*, *biprism stereo camera*, *single-lens stereo rig*, *beam-splitter stereo
imaging*, adaptadores estéreo de endoscopía/macrofotografía, y el formato *side-by-side* de cámaras
VR/360 estéreo como antecedente del frame compuesto descrito en §2. Agregar las referencias que resulten
relevantes a `informe/13-REFERENCIAS.md` siguiendo el formato ya usado (entradas alfabéticas con anclas
`ref-<autor>-<año>`) antes de citarlas en el cuerpo del informe.

---

## 6. Si se ejecuta: qué actualizar en el informe

- **Cap. 11 (`11-RESULTADOS.md`):** nueva subsección junto a §11.4.2b con los resultados de la fase SA8,
  siguiendo el mismo formato de tabla y análisis estadístico que el resto del capítulo.
- **Anexo 7:** la síntesis de §A7.6 pasaría de argumentación teórica a resultado medido, incorporando el
  escalón intermedio de costo (adaptador de un sensor) junto al de dos cámaras completas ya contemplado.
- **Cap. 12 (`12-CONCLUSIONES.md`), §12.4:** el bullet que hoy referencia el Anexo 7 como trabajo futuro
  se ajustaría para reflejar la recomendación de costo/beneficio real que surja de §4 de este documento.
