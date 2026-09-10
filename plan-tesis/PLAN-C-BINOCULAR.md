# Plan binocular — de la configuración de AirSim a un backend de percepción estéreo

**Fecha:** 2026-09-09
**Estado:** exploratorio, no comprometido. Este documento existe para poder decidir con costo/beneficio
concreto si vale la pena ejecutarlo, no como compromiso de implementación.
**Origen:** [`PLAN-FUTURAS-MEJORAS.md`](PLAN-FUTURAS-MEJORAS.md) (discusión de la "maldición monocular")
y [`informe/anexos/A7-MALDICION-MONOCULAR-ESTEREO.md`](../informe/anexos/A7-MALDICION-MONOCULAR-ESTEREO.md)
(formalización teórica), que a su vez explica el fracaso 0/5 de los tres brazos en `townsim_ini`
(`informe/11-RESULTADOS.md`, §11.4.2b). Este plan es el paso siguiente si se decidiera **medir** esa
propuesta en vez de dejarla solo como trabajo futuro razonado.

**Objetivo del experimento (si se ejecuta):** demostrar, con el mismo protocolo estadístico ya usado
en el cap. 11 (K=5 semillas, Mann-Whitney + Cliff's δ, §11.3.2), que sustituir o complementar el canal
de percepción monocular por un canal estéreo mejora la tasa de éxito o la distancia recorrida en
`townsim_ini` (y opcionalmente en `townsim_calib_cruce_frontal`), sin degradar el comportamiento ya
validado en los escenarios `*_clear`.

**Aclaración de alcance importante:** a pesar de que el pedido original habla de "un grafo de control
binocular", la arquitectura actual (`src/agents/graph.py`) ya separa percepción de decisión mediante un
contrato único, `ObstacleField` (`src/perception/obstacle_field.py`, F1.1 del plan de mejoras original).
Todo lo que consume el campo de obstáculos — `policy_router`, `evasive_node`, `deliberative_node`,
`fsm_node`, el resumen textual que ve el SLM — lo hace exclusivamente a través de esa API (`is_blocked()`,
`sector_ttc()`, `min_ttc()`, `summary_text()`, etc.), nunca leyendo flujo óptico crudo. Esto significa que
**no hace falta rediseñar el grafo de LangGraph**: hace falta un nuevo *productor* de `ObstacleField` (un
segundo `perception_node`, o una fusión de dos) que use disparidad estéreo en vez de flujo óptico
derotado. El resto del grafo — routers, nodos tácticos, motor — queda intacto. Esto reduce
significativamente el riesgo y el costo de la prueba: es un cambio acotado a la capa de percepción, no
una reescritura del lazo de control.

---

## 0. Criterio de orden y tabla de fases

Ordenado por dependencia, igual que los planes de mejora anteriores (`PLAN-MEJORAS-*.md`). Cada fase
es indispensable para la siguiente; no hay atajos razonables.

| Fase | Qué desbloquea | Entregable |
|---|---|---|
| **B1** Segunda cámara en AirSim | Que exista un par estéreo capturable | `settings.json` con dos cámaras y baseline conocida, verificado con una captura manual |
| **B2** Captura sincronizada | Que el par de imágenes corresponda al mismo instante | `AirSimClient.capture_stereo()`, timing medido |
| **B3** Rectificación y calibración | Que la disparidad sea geométricamente válida | Matrices de calibración estéreo derivadas de `settings.json`, sin necesidad de checkerboard (cámaras sintéticas sin distorsión) |
| **B4** Motor de disparidad → profundidad métrica | El observable físico nuevo (profundidad en metros, no flujo) | Módulo `stereo_depth.py` con StereoSGBM como línea de base |
| **B5** Adaptador `ObstacleField` | Que el resto del sistema pueda consumir estéreo sin cambios | `StereoObstacleEstimator` con la misma interfaz que `FlowTTCEstimator` |
| **B6** Integración en el grafo | Poder elegir/combinar el backend sin tocar routers ni nodos tácticos | `PERCEPTION_BACKEND=flow\|stereo\|fusion` en `graph.py` |
| **B7** Validación offline contra ground truth | Saber si el estéreo mide bien *antes* de volar con él | Curva ROC + índice de Youden, análogo a cap. 7 §7.5 |
| **B8** Protocolo experimental comparativo | El dato que iría al cap. 11 si se decide escribirlo | Re-corrida de `townsim_ini` (K=5, 3 brazos) con `PERCEPTION_BACKEND=stereo`, comparado contra la línea base monocular ya existente |
| **B9** Riesgos y criterios de aborto | Saber cuándo el experimento no vale la pena seguir | Lista de señales de que el estéreo no está aportando lo esperado (Anexo 7, §A7.5) |

---

## Fase B1 — Segunda cámara en AirSim

**Archivo:** `airsim-settings/settings.json`. Actualmente no declara ninguna sección `Vehicles` ni
`Cameras` explícita (usa los defaults de Cosys-AirSim con una sola cámara frontal, `CameraDefaults` +
`SubWindows` apuntando a `"Front Camera"`). Para un par estéreo hace falta declarar el vehículo y dos
cámaras con un offset relativo fijo y conocido en el eje $Y$ (lateral, baseline horizontal clásica):

```json
{
  "Vehicles": {
    "Drone1": {
      "VehicleType": "SimpleFlight",
      "Cameras": {
        "front_left": {
          "CaptureSettings": [{ "ImageType": 0, "Width": 1080, "Height": 720, "FOV_Degrees": 90 }],
          "X": 0.25, "Y": -0.06, "Z": 0.0,
          "Pitch": 0.0, "Roll": 0.0, "Yaw": 0.0
        },
        "front_right": {
          "CaptureSettings": [{ "ImageType": 0, "Width": 1080, "Height": 720, "FOV_Degrees": 90 }],
          "X": 0.25, "Y": 0.06, "Z": 0.0,
          "Pitch": 0.0, "Roll": 0.0, "Yaw": 0.0
        }
      }
    }
  }
}
```

Puntos a decidir/verificar en esta fase:

- **Baseline ($B$) realista.** 0.12 m (12 cm) es un valor plausible para un dron pequeño tipo el que
  motiva este trabajo (§1.2); documentar la elección con una justificación de plataforma física
  objetivo, porque de este valor depende directamente el error de profundidad con la distancia
  (Anexo 7, §A7.5.1: $\sigma_Z \propto Z^2/(fB)$). Exponerlo como `STEREO_BASELINE_M` (env var) para
  no hardcodearlo en dos lugares (settings de AirSim y cálculo de profundidad en Python).
- **FOV y resolución idénticos entre ambas cámaras**, mismo criterio que la cámara frontal actual
  (Anexo 5, §A5.1.2: $f_x = 554.0$ px calibrados para $\text{FOV}_h=90°$, $W=1080$). Si difieren, la
  rectificación (B3) se complica sin necesidad.
- **Orientación estrictamente paralela** (mismo Pitch/Roll/Yaw en ambas cámaras): en simulación esto es
  gratis (a diferencia de un par físico real, que requeriría calibración extrínseca por checkerboard),
  y es lo que permite saltar la rectificación completa en B3.
- Verificación manual: un script chico que llame `simGetImages` pidiendo `front_left` y `front_right`
  con el dron en hover frente a un obstáculo de distancia conocida en el mapa (p. ej. una pared de
  TownSim), y confirme visualmente el desplazamiento horizontal esperado entre ambas vistas.

---

## Fase B2 — Captura sincronizada

**Archivo:** `airsim-loop/src/hardware/airsim_client.py`, método `capture()` (línea 242 en adelante).
Hoy arma una lista `requests` con un único `airsim.ImageRequest(camera_id, airsim.ImageType.Scene,
False, False)` y opcionalmente agrega una segunda request de profundidad (`return_depth=True`, usada
para debugging/ground truth, no para el lazo de vuelo real — ver la guardia de no-profundidad citada en
`graph.py` línea 152).

Agregar `capture_stereo()` (o extender `capture()` con un flag `stereo: bool = False`) que arme **una
sola llamada a `simGetImages`** con las dos cámaras (`front_left`, `front_right`) en el mismo
`requests`, igual que ya se hace para RGB+profundidad. Esto es importante: batchear ambas requests en
una única llamada RPC es lo que garantiza que las dos imágenes correspondan al mismo instante de
simulación (mismo mecanismo por el que ya se usa `response.time_stamp` — línea 289 — para el flujo
óptico, en vez de `time.time()` del lado cliente).

```python
requests = [
    airsim.ImageRequest("front_left", airsim.ImageType.Scene, False, False),
    airsim.ImageRequest("front_right", airsim.ImageType.Scene, False, False),
]
responses = self._client.simGetImages(requests, vehicle_name=self.vehicle_name)
```

Puntos a resolver:

- Reusar el mismo patrón de conversión RGB→BGR ya presente (línea 308) para ambas imágenes — el bug de
  canales invertidos documentado en `CHANGELOG.md` (2026-09-03) aplica igual a la cámara nueva.
- Medir el costo de latencia extra de pedir dos imágenes en vez de una (el log de timing ya existe,
  línea 348: `dt_images`). Si duplica el tiempo de `simGetImages` de forma significativa, evaluar bajar
  la resolución de captura estéreo por debajo de la resolución RGB principal usada por el VLM (no hace
  falta que el canal estéreo tenga 1080×720 para producir un `ObstacleField` de sectores gruesos).
- Decidir si el canal estéreo captura en **todos** los ciclos (5 Hz, mismo período que flujo óptico) o
  solo quiere probarse a una frecuencia menor si el costo de B4 resulta alto — ver B9 (criterios de
  aborto por presupuesto de cómputo, ecoando la tensión ya señalada en el Anexo 7 §A7.2.1 para SLAM
  denso).

---

## Fase B3 — Rectificación y calibración

Con cámaras sintéticas perfectamente paralelas y sin distorsión de lente (caso de AirSim, a diferencia
de un par físico real), la rectificación estéreo completa (`cv2.stereoRectify`) es opcional: si las
dos cámaras están exactamente co-planares y sin rotación relativa (B1), las líneas epipolares ya son
horizontales por construcción y el *matching* de disparidad puede aplicarse directamente sobre las
imágenes crudas.

Aun así, conviene dejar el paso de rectificación implementado (aunque termine siendo una identidad en
simulación), por dos razones:

1. **Transferencia a hardware real** (cap. 12, §12.4, bullet "Transferencia a hardware embebido"): un
   par físico de cámaras baratas nunca está perfectamente alineado, y ahí la rectificación deja de ser
   opcional. Implementarla ahora evita un rediseño cuando se llegue a esa etapa.
2. **Detección de regresiones de configuración**: si alguien cambia el `Pitch`/`Roll`/`Yaw` de una sola
   cámara en `settings.json` sin darse cuenta, un paso de rectificación con matrices identidad seguiría
   funcionando pero un chequeo de consistencia (ver abajo) lo detectaría.

Matrices de calibración a derivar (reusando exactamente el modelo pin-hole del Anexo 5, §A5.1):
$f_x, f_y, c_x, c_y$ iguales a los ya calibrados para la cámara frontal (`CAMERA_FX`/`CAMERA_FY` en
`flow_ttc.py`, línea 32), y la matriz de traslación estéreo $T = (B, 0, 0)^T$ con $B$ =
`STEREO_BASELINE_M` de B1.

Chequeo de consistencia sugerido: sobre una escena estática de calibración (p. ej. una pared plana a
distancia conocida en MiniSim), verificar que la disparidad medida $d$ reproduce la distancia esperada
vía $Z = f_x B / d$ dentro de una tolerancia razonable (análogo al protocolo de validación TTC del
cap. 7, §7.5, pero aplicado a distancia estéreo en vez de tiempo-a-colisión).

---

## Fase B4 — Motor de disparidad y profundidad métrica

**Archivo nuevo:** `airsim-loop/src/perception/stereo_depth.py`, hermano de `flow_ttc.py`.

Línea de base (barata, determinista, sin dependencias nuevas más allá de OpenCV, que ya es dependencia
del proyecto vía `cv2` en `flow_ttc.py`):

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
depth = (CAMERA_FX * STEREO_BASELINE_M) / np.maximum(disparity, STEREO_MIN_DISPARITY_PX)
```

Opción de mayor precisión, mencionada en el Anexo 7 (§A7.4) pero fuera del alcance de una primera
prueba: un método de *matching* denso basado en aprendizaje (familia RAFT-Stereo). Dejarlo como
extensión de segunda iteración — StereoSGBM alcanza para validar la hipótesis central (que eliminar la
dependencia del FOE mejora `townsim_ini`) sin el costo de integrar un modelo adicional al presupuesto
de cómputo ya compartido con el SLM (cap. 6, §6.1, punto 1).

**Nota metodológica que ya quedó fijada en el Anexo 7 (§A7.4) y hay que respetar en la implementación:**
la profundidad debe salir de este *matching* real, con su ruido de correspondencia incluido — nunca
leerse directamente del `DepthPlanar` de AirSim (que sigue existiendo en el cliente solo para
depuración/validación offline, B7). Si el canal de decisión terminara usando el ground truth, se estaría
comparando el sistema contra un LiDAR ideal, invalidando la comparación de costo/beneficio que motiva
todo el plan.

Variables de entorno a introducir, siguiendo el patrón ya usado por `flow_ttc.py`:
`STEREO_BASELINE_M`, `STEREO_NUM_DISPARITIES`, `STEREO_BLOCK_SIZE`, `STEREO_MIN_DISPARITY_PX`,
`STEREO_MAX_RANGE_M` (más allá de este rango, tratar la celda como "sin evidencia" en vez de extrapolar
una profundidad ruidosa — mismo principio que `FLOW_NOISE_FLOOR_PX` en el estimador de flujo).

---

## Fase B5 — Adaptador hacia `ObstacleField`

**Archivo nuevo:** `StereoObstacleEstimator` en `stereo_depth.py`, con la misma forma de interfaz que
`FlowTTCEstimator.estimate(curr_image, prev_image, telemetry, prev_telemetry) -> ObstacleField`
(`graph.py`, línea 215), para que sea un reemplazo *drop-in* en `perception_node`.

Diferencias clave de implementación respecto del estimador de flujo:

- **No necesita `prev_image` ni `prev_telemetry`.** La profundidad estéreo es un observable de un
  único instante (§A7.3 del Anexo 7) — a diferencia de flujo óptico, que requiere el par de frames
  $t-1, t$. Esto es, en rigor, la ventaja central que motiva todo el plan: el estimador puede producir
  evidencia útil incluso en el primer ciclo de vuelo o durante un hover prolongado.
- **Mapeo a celdas sector×banda:** dividir el mapa de profundidad (mismo *grid* 3×3 que usa
  `obstacle_field.py`, `SECTORS`/`BANDS`) y calcular, por celda, `occupancy` como fracción de píxeles
  con profundidad por debajo de un umbral de bloqueo en metros (`STEREO_OCCUPANCY_RANGE_M`, análogo
  conceptual al umbral de TTC pero en distancia en vez de tiempo), y `confidence` como fracción de
  píxeles con disparidad válida (no en el piso de ruido ni saturados en `STEREO_MAX_RANGE_M`).
- **`ttc_s` derivado, no medido directamente.** El estéreo da distancia, no tiempo-a-colisión; para
  poblar el mismo campo `ttc_s` que consume `policy_router` (`TTC_EVASION_THRESHOLD`,
  `TTC_SAFE_THRESHOLD`, `graph.py` líneas 298–299), estimarlo como $TTC \approx Z / V_{\text{cierre}}$
  usando la componente de velocidad hacia adelante de la telemetría actual (`telemetry["velocity"]`),
  con el mismo cuidado de devolver `inf` si la velocidad de cierre es ~0 (evita dividir por cero y es
  coherente con la semántica ya usada en `Cell` — TTC infinito = "no hay evidencia de aproximación").
- **`source` nuevo en `ObstacleField`:** agregar `"stereo"` (y `"fusion"` si se implementa B6-fusión)
  a los valores ya documentados en el dataclass (`"flow" | "degraded" | "none"`, `obstacle_field.py`
  línea 63), y decidir si `has_evidence()` (línea 109-110, hoy hardcodeada a `source == "flow"`) debe
  generalizarse a cualquier fuente con `foe_confidence`-equivalente > 0, o si el estéreo necesita su
  propio campo de confianza global análogo (`stereo_confidence`) en vez de forzar la semántica de FOE,
  que no aplica a un sensor sin foco de expansión.

Este último punto (`has_evidence()`) es el único lugar del contrato existente que asume implícitamente
flujo óptico monocular por nombre de campo (`foe_confidence`) en vez de por semántica genérica
("¿hay evidencia global confiable?"); vale la pena revisarlo con cuidado antes de tocarlo, porque lo
usa también `has_open_corridor()` (línea 174), consumido por el escape de deadlock en `policy_router`.

---

## Fase B6 — Integración en el grafo de control

**No se agregan nodos nuevos al `StateGraph`** (`graph.py`, líneas 383-420): el cambio vive
enteramente dentro de la función `perception_node` (línea 210), que hoy llama a
`flow_ttc_estimator.estimate(...)`. Tres variantes posibles, de menor a mayor esfuerzo:

1. **Sustitución simple (`PERCEPTION_BACKEND=stereo`).** `perception_node` instancia
   `StereoObstacleEstimator` en vez de `FlowTTCEstimator` según una env var, siguiendo exactamente el
   mismo patrón que `AGENT_ARM` (línea 38). Es el mínimo viable para el experimento de B8: compara
   monocular puro contra estéreo puro, arma por arma.
2. **Fusión (`PERCEPTION_BACKEND=fusion`).** `perception_node` corre ambos estimadores y combina las
   dos `ObstacleField` celda a celda (p. ej. `occupancy = max(flow.occupancy, stereo.occupancy)`,
   `confidence` tomando la fuente de mayor confianza por celda, `ttc_s = min(...)` conservador). Esto es
   arquitectónicamente más fiel a lo que se haría en un sistema real (no se descarta flujo óptico, que
   sigue siendo más barato y sigue funcionando bien en los escenarios `*_clear` del cap. 11, secciones
   11.1–11.3): se usa estéreo específicamente para cubrir el punto ciego cerca del FOE que describe el
   Anexo 7 (§A7.1.2), no para reemplazar todo el pipeline de percepción.
3. **Especialización por sector.** Variante más fina de (2): usar estéreo solo para el sector `centro`
   (donde vive el punto ciego del FOE) y dejar flujo óptico para `izquierda`/`derecha` (donde el flujo
   ya es la fuente de mayor confianza). Reduce el costo de cómputo de correr StereoSGBM sobre el frame
   completo si el presupuesto de B2/B9 resulta ajustado.

Para una primera prueba que busque **una respuesta clara a la pregunta de investigación de este plan**
(¿el estéreo saca al sistema del modo de falla de `townsim_ini`?), la variante (1) es la más limpia
estadísticamente: aísla la variable de interés sin mezclar dos fuentes de evidencia, al costo de perder
el beneficio de robustez lateral que ya aporta el flujo óptico. La variante (2) es la que efectivamente
se recomendaría para producción si el experimento (1) resulta positivo.

`policy_router`, `evasive_node`, `deliberative_node`, `fsm_node`, `girar_90_node` y el `summary_text()`
que arma el prompt del SLM **no requieren ningún cambio** en ninguna de las tres variantes: todos leen
`ObstacleField` por su API pública, no por su origen.

---

## Fase B7 — Validación offline contra ground truth

Antes de volar con el canal estéreo dentro del lazo de decisión, replicar el protocolo de validación
que el cap. 7 ya aplicó al TTC de flujo óptico (§7.5: curva ROC, umbral óptimo por índice de Youden)
contra el mapa de profundidad de referencia (`DepthPlanar`, obtenido vía `capture(return_depth=True)`,
ya soportado por `AirSimClient` — línea 243). Aquí sí es correcto usar el ground truth, porque el
objetivo es *evaluar el error del estéreo*, no alimentar una decisión de vuelo con él (la distinción
que ya establece el Anexo 7, §A7.4, nota metodológica).

Métricas a reportar, análogas a las de calibración pendientes del canal de flujo (cap. 6, §6.3,
mencionadas también como trabajo futuro en cap. 12, §12.4):

- Error absoluto y relativo de profundidad estéreo vs. `DepthPlanar`, en función de la distancia real
  (para verificar empíricamente la relación $\sigma_Z \propto Z^2/(fB)$ del Anexo 7, §A7.5.1, no solo
  asumirla).
- Curva ROC de `is_blocked()` (adaptado a estéreo) contra un umbral de distancia de referencia,
  siguiendo el mismo protocolo Youden que TTC.
- Un corte específico sobre escenas de follaje denso (frames de `townsim_ini`) vs. escenas urbanas
  limpias (`townsim_clear`), para verificar si la degradación de matching por textura repetitiva
  (Anexo 7, §A7.5.1) es medible y de qué magnitud, antes de invertir en la corrida completa de B8.

Si esta fase muestra que el error estéreo en follaje denso es comparable o peor que la falta de
evidencia del monocular en el mismo punto, es una señal de aborto temprano (ver B9) — más barata que
descubrirlo después de correr 15 misiones completas en B8.

---

## Fase B8 — Protocolo experimental comparativo

Reutilizar exactamente el protocolo estadístico ya validado en el cap. 11 (§11.3.2): K=5 semillas,
prueba U de Mann-Whitney bilateral, Cliff's δ, corrección de Bonferroni. Diseño sugerido:

| Comparación | Escenario | Métrica primaria | Métrica secundaria |
|---|---|---|---|
| `slm` monocular vs. `slm` estéreo | `townsim_ini` | tasa de éxito (5/5 vs. 0/5 actual) | distancia recorrida, deadlocks/corrida |
| `fsm` monocular vs. `fsm` estéreo | `townsim_ini` | ídem | ídem |
| `reactive` monocular vs. `reactive` estéreo | `townsim_ini` | ídem | ídem |
| `slm` estéreo vs. `slm` monocular | `townsim_clear` / `citysim_clear` | tiempo de misión (¿el estéreo introduce overhead o regresión en el caso ya resuelto?) | invocaciones VLM, distancia mínima al obstáculo |

La última fila es la más importante para no reportar un resultado sesgado: si el estéreo resuelve
`townsim_ini` pero degrada el rendimiento ya sólido en los tres tiers de control (cap. 11, §11.1–11.3),
la conclusión correcta no es "usar siempre estéreo" sino "usar fusión selectiva" (variante B6.2/B6.3).

Reutilizar la infraestructura de corrida ya existente (`runs/tesis/`, `summary.json` con hash de código,
mismo criterio de cuarentena de datos que `PLAN-MEJORAS-4.md` §I0) en vez de crear un pipeline de
corrida paralelo.

---

## Fase B9 — Riesgos y criterios de aborto temprano

Señales de que el experimento no está aportando lo esperado, y que conviene revisar antes de invertir
en la corrida completa de B8 (coherente con las limitaciones ya declaradas en el Anexo 7, §A7.5):

- **Latencia de `simGetImages` duplicada** (B2) empuja el ciclo por debajo de los 5 Hz nominales del
  lazo (`LOOP_HZ`), o el cómputo de StereoSGBM (B4) no entra en el presupuesto de 20-50 ms por ciclo ya
  compartido con el SLM (cap. 6, §6.1, punto 1) → considerar bajar resolución del canal estéreo o
  correrlo a frecuencia reducida antes de descartar la propuesta.
- **Error de profundidad en follaje denso comparable a la falta de evidencia monocular** (B7) → el
  matching estéreo está sufriendo el mismo problema de textura repetitiva que el Anexo 7 (§A7.5.1) ya
  anticipa; evaluar si vale la pena escalar a un matcher basado en aprendizaje antes de declarar la
  hipótesis refutada.
- **Baseline de 0.12 m insuficiente para el rango de detección necesario** a la velocidad de crucero
  usada en `townsim_ini` → recalcular el horizonte de detección confiable ($\sigma_Z$ vs. distancia de
  frenado necesaria a esa velocidad) antes de correr B8; puede ser necesario ajustar la velocidad de
  aproximación del brazo `reactive`/`fsm` en este escenario específico, no solo el sensor.
- **Mejora medible en `townsim_ini` pero regresión en `*_clear`** (última fila de B8) → no es un
  resultado negativo del experimento, es la señal de que la variante correcta para producción es
  fusión (B6.2/B6.3), no sustitución total (B6.1).

---

## Si se ejecuta: qué actualizar en el informe

- **Cap. 11 (`11-RESULTADOS.md`):** nueva subsección §11.4.2c (o extensión de §11.4.2b) con los
  resultados de B8, siguiendo el mismo formato de tabla y análisis estadístico que el resto del
  capítulo.
- **Anexo 7:** pasaría de propuesta razonada a resultado validado — actualizar la síntesis de §A7.6 con
  los datos reales de B7/B8 en vez de la argumentación puramente teórica actual.
- **Cap. 12 (`12-CONCLUSIONES.md`), §12.4:** el bullet que hoy referencia el Anexo 7 como trabajo futuro
  se reescribiría como resultado logrado (o como línea futura ajustada, si B9 detecta que la mitigación
  correcta es fusión selectiva y no sustitución completa).
