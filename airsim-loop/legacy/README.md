# Codigo retirado

Modulos movidos aca durante la implementacion de `PLAN-MEJORAS.md`. Se conservan
por referencia historica y para la seccion de la tesis que documenta el retiro
de YOLO/IPM como decision de diseno, no se importan desde `src/`.

## `perception/detector.py`, `perception/translator.py`, `perception/roi_cropper.py`

Wrapper de inferencia YOLOv8/YOLO26 y su traductor de bboxes a sectores/etiquetas.
Retirado en el CHANGELOG 2026-0822/0823. El productor de `detected_obstacles` que
estos modulos alimentaban dejo de existir, pero (antes de esta implementacion)
sus consumidores (`ttc_router`, `_summarize_sectors`, `_fallback_decision`,
`evasive_node`) seguian leyendo el campo, que quedaba siempre en `[]`. Ver
`PLAN-MEJORAS.md` seccion 2 del analisis original para la cadena de consumidores
rotos. Reemplazado por `ObstacleField` (`src/perception/obstacle_field.py`),
poblado por flujo optico + TTC (`src/perception/flow_ttc.py`).

## `perception/ttc_estimator.py`

Estimador de TTC alternativo que se instanciaba en `_build_nodes()` pero nunca
se invocaba (`TTCEstimator()` sin uso). Reemplazado por `FlowTTCEstimator`
(`src/perception/flow_ttc.py`), que si esta cableado en el grafo.

## `perception/optical_flow_estimator.py`

TTC calculado como `1.0 / mean(|flow|)`, clampeado a `[0.1, 10.0]`. Problemas
identificados (ver `PLAN-MEJORAS.md` F1.2):
- El resultado esta en unidades de frame, no de segundos (nunca se divide por
  `dt` real), pero se comparaba contra umbrales en segundos.
- Magnitud de flujo no es divergencia: el promedio esta dominado por la
  rotacion propia de yaw, asi que cada giro del dron desplomaba el TTC
  espuriamente y disparaba el freno de seguridad sin peligro real.
- `_calc_foe()` era un stub que devolvia el centro geometrico de la imagen
  (`# Simplificacion` en el comentario original) en lugar de estimar el FOE.
- El clamp `[0.1, 10.0]` escondia estos tres problemas devolviendo siempre un
  numero plausible.

Reemplazado por `FlowTTCEstimator` (`src/perception/flow_ttc.py`), que deroto
el flujo con la telemetria de actitud, estima el FOE por minimos cuadrados
ponderados y calcula TTC en segundos reales con `dt` de telemetria.

## `perception/ipm_segmentator.py`

Retirado, no reparado (decision documentada en `PLAN-MEJORAS.md` F1.4):

- El IPM asume un plano de suelo dominante en el FOV. Con camara frontal a
  ~10 m de altura en canon urbano el suelo ocupa una fraccion marginal de la
  imagen: la hipotesis de base no se cumple para este caso de uso.
- La implementacion no era un IPM real: con `R = I` la homografia se reducia
  a `diag(fx/(1+h), fy/(1+h), 1)` — un escalado dependiente de la altitud sin
  pitch, roll ni altura de camara respecto al plano.
- Se aplicaba la misma homografia a ambos frames, asi que
  `absdiff(ipm_cur, ipm_prev)` era matematicamente un frame-difference bajo
  ego-movimiento: todo borde texturado se marcaba como obstaculo. Ese
  `occlusion_ratio` era el que disparaba `GIRAR_90`.
- Costo no competitivo: bucle Python sobre `np.unique(segments)`
  (~200 iteraciones/frame) y un fallback k-means con k=200 sobre la imagen
  completa cuando faltaba scikit-image.

Reemplazado por `ObstacleField.blocked_fraction()`, derivado del mismo campo
de flujo/TTC (sin homografia, sin SLIC).

### Alternativa considerada y rechazada

Implementar el IPM de verdad (homografia del plano de suelo con pitch/roll/
altura de telemetria, K real de la camara de AirSim, compensacion de
ego-movimiento warpeando t-1 hacia t, SLIC sobre la imagen original y grafo
geodesico de distancias). Es correcto en abstracto pero resuelve un problema
que este caso de uso (cuadricoptero urbano, camara frontal) no tiene, y
agrega el costo del grafo geodesico. Se documenta como decision, no como
trabajo pendiente.
