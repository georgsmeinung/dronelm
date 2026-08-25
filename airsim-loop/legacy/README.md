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

## `perception/canny_gate.py` (`CannyGate`, nodo `canny_xor_gate`, `xor_router`)

Retirado con evidencia medida (F0.4, CHANGELOG 2026-0824). El gate comparaba
bordes Canny entre frames consecutivos (`xor_change_ratio`) y, si el cambio
era menor al umbral, saltaba directo a `keep_going` sin pasar por
`perception` **ni por `policy_router`** — el bypass no solo evitaba el flujo
optico/TTC, evitaba toda la logica de seguridad de los brazos `slm`/`fsm`.

- **Medido en vuelo real** (446 ciclos a `LOOP_HZ=5.0`,
  `runs/xor_calibration/manhattan_b/reactive/seed_1.jsonl`): en crucero activo
  `xor_change_ratio` nunca bajo de 0.071 (p1=0.158, p50=0.247). El umbral
  historico (0.02-0.03) jamas disparaba. Recalibrarlo al percentil 1 medido
  (0.16) tampoco resolvia el problema de fondo: seguia sin disparar durante
  >99% del vuelo activo, y el ~1% donde si disparaba correspondia a momentos
  de hover (post-`FRENAR`, esperando deliberacion) — no a "ahorro de computo
  en crucero", que era el proposito original del gate.
- **Por que ese ~1% es peor que inutil, no solo inutil:** `reactive_node`
  (destino del bypass) nunca lee `obstacle_field`, asi que el bypass no
  cambiaba nada para el brazo `reactive`. Para `slm`/`fsm`, el bypass ocurria
  justo cuando la escena estaba visualmente estatica — que es exactamente lo
  que pasa durante un hover de seguridad, cuando el dron ya freno porque
  `policy_router` detecto TTC bajo o `center_blocked` en un ciclo anterior.
  En ese momento, "nada cambio visualmente" no significa "es seguro seguir":
  significa que el obstaculo que causo el freno probablemente sigue ahi. El
  gate resumia `MANTENER_RUMBO` sin volver a evaluar el campo de obstaculos,
  justo en el escenario donde mas importaba volver a evaluarlo.
- **Costo pagado sin contrapartida:** Canny + XOR corria en el 100% de los
  ciclos (el gate mismo cuesta computo), mientras que el ahorro que deberia
  justificar ese costo (saltar el flujo optico/TTC) casi nunca se
  materializaba en la fase de vuelo donde mas ciclos se ejecutan.

**Conclusion:** con datos de vuelo real, el gate no cumplia su proposito de
diseno (ahorro de computo en crucero) y su unico modo de disparo frecuente
introducia una regresion de seguridad. Aplica el criterio del propio
`PLAN-MEJORAS.md` F0.4 ("si nunca dispara utilmente, se retira") mas fuerte
de lo previsto: no es que nunca disparara, es que su patron de disparo era
contrario a la seguridad. `degraded_router` ahora rutea directo a
`perception`; el nodo `canny_xor_gate` y `xor_router` se eliminaron del
grafo (`src/agents/graph.py`).
