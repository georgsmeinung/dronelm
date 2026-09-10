# Plan slam_assess — memoria de trayectoria + mitigaciones de percepción

**Fecha:** 2026-09-10  
**Actualizado:** 2026-09-10 (sesión 2) — incorporadas mitigaciones P1–P3 de percepción monocular.  
**Estado:** comprometido para re-test de `townsim_ini`.  
**Pregunta experimental:** ¿Un VLM con memoria de trayectoria acumulada supera al VLM con
panorama instantáneo (`deep_vlm`) en los escenarios bloqueantes (`townsim_ini`)?

**Por qué reemplaza y no complementa:** `deep_vlm` y `blind` son dos estrategias de escape
ante un deadlock duro. Si ninguna resuelve `townsim_ini` (resultado actual: 0/5 en los tres
brazos), agregar una tercera opción no responde la pregunta — la diluye. `slam_assess` reemplaza
a ambas: es el único mecanismo de escape, con una lógica interna de degradación (ver S4).
La variable de interés queda aislada: memoria de trayectoria acumulada vs. panorama del instante.

---

## Distinción de diseño crítica: eventos de trayectoria, no ObstacleFields

El `FlowTTCEstimator` falla exactamente en los escenarios donde se activa el escape por deadlock
(`townsim_ini`, vegetación densa). Si el mapa acumula `ObstacleField` de esos ciclos, acumula
entradas con `foe_confidence ≈ 0` y `source="none"` — el sensor es ciego justo donde más se
necesita el mapa.

Lo que sí es confiable en todos los ciclos, incluso cuando FlowTTC es ciego:
- Posición y heading de telemetría (AirSim no tiene deriva)
- Si el dron avanzó o se quedó en esa posición (`Δ distancia al waypoint`)
- Qué acción se ejecutó y qué pasó después

`slam_assess` acumula **eventos de trayectoria** (posición + acción + resultado), no campos de
obstáculos. Un stall repetido en posición `(x,y,z)` después de `MANTENER_RUMBO` es evidencia de
bloqueo aunque el sensor óptico haya dado `foe_confidence=0`.

Esta distinción de diseño hace que el mapa sea útil en los escenarios exactos donde el sistema
falla, y debe quedar explícita en el informe (§12.3, nota metodológica).

---

## 0. Tabla de fases

Las fases P1–P3 son mitigaciones de percepción monocular independientes del SLAM; se implementan primero porque son pre-requisito para que el sensor óptico sea más confiable durante las corridas de validación SLAM. Las fases S1–S6 son el plan SLAM original. S2b, S3b y MDE son opcionales.

| Fase | Qué desbloquea | Entregable |
|---|---|---|
| **P1** Pre-integración IMU | Derotación más precisa → extiende límite de yaw operativo | `flow_ttc.py`: integración del giroscopio entre frames en lugar de tasa instantánea |
| **P2** Holdover temporal TTC | TTC válido durante giros cortos sin corromper el canal | `flow_ttc.py` / `obstacle_field.py`: último TTC válido con decaimiento temporal, máx. N frames |
| **P3** Supresión de yaw durante percepción | Elimina la degradación de derotación en aproximación a obstáculos | `graph.py` / `action_map.py`: inhibir yaw_rate > umbral cuando TTC < TTC_SAFE_THRESHOLD |
| **S1** Buffer de trayectoria | Memoria de eventos de vuelo independiente del sensor óptico | `FlightTrajectory` en `spatial_history.py` — ring buffer de (posición, heading, acción, Δwp, stall) |
| **S2** Resumen textual para el VLM | Que el VLM reciba historia de intentos, no solo vista actual | `trajectory_context_text()` — qué direcciones se intentaron, cuáles produjeron progreso, cuáles stall |
| **S2b** *(opcional)* Nube SfM por sectores | Añadir evidencia estructural 3D al bloque textual cuando el matching es confiable | Estadístico de puntos triangulados por sector (no render); se degrada silenciosamente si la confianza SfM < umbral |
| **S3** Prompt de slam_assess | Consulta al VLM con contexto de trayectoria + frame actual | `SYSTEM_PROMPT_SLAM_ASSESS` — sin rotación panorámica, solo frame frontal + historia |
| **S3b** *(sub-opción condicional de S3)* Anotación YOLO en stalls | Añadir clase semántica del obstáculo a eventos de stall pasados | `obstacle_class` en `TrajectoryEvent`; solo si `SLAM_YOLO_ENABLED=true` y `conf ≥ 0.45` |
| **S4** Reemplazo de `deep_vlm` y `blind` | Que `DEADLOCK_STRATEGY` tenga un único valor útil | `deep_scan.py` con solo `slam_assess`; `blind` y `deep_vlm` quedan como legado no activo |
| **S5** Validación offline | Saber si la historia hubiera sido útil antes de volar | Reconstrucción sobre logs de `townsim_ini` ya existentes |
| **S6** Corrida experimental | El dato que va al cap. 11 | `townsim_ini` K=5 × 3 brazos con `slam_assess` vs. línea base (`deep_vlm`) del cap. 11 |
| **MDE** *(opcional / trabajo futuro)* Depth Anything v2 Small | Reemplazo del canal TTC por profundidad monocular sin dependencia de movimiento ni yaw | Si P1–P3 no alcanzan y el VRAM lo permite; no bloquea S6 |

---

## Mitigaciones de percepción monocular (P1–P3)

**Contexto.** El análisis de D3 (2026-09-10) confirmó que la derotación analítica falla a partir de 0.3 rad/s de yaw — la primera tasa ensayada por encima del límite teórico de `FLOW_MAX_ROTATION_DEG = 2°/frame` a 5 Hz. Cuando falla, `foe_confidence` cae a cero y el canal de TTC se silencia. Esto ocurre durante maniobras de guiado con yaw, durante `girar_90`, y potencialmente en cualquier ciclo donde el dron corrija su rumbo. Las mitigaciones P1–P3 atacan el problema en tres capas: mejorar la derotación, preservar la información cuando falla, e inhibir el yaw cuando más importa.

Estas tres mitigaciones son independientes entre sí y del SLAM; se implementan antes que S1–S6 porque mejoran la calidad del sensor óptico que el buffer de trayectoria usa para decidir si un ciclo tuvo `flow_had_evidence=True`.

---

### Fase P1 — Pre-integración de IMU para derotación más precisa

**Problema actual.** `FlowTTCEstimator.estimate()` usa `telemetry_curr["orientation"]["yaw_rate"]` (un único valor escalar tomado en el instante del frame actual) para estimar el flujo rotacional acumulado entre `prev_frame` y `curr_frame`. Si la tasa de yaw varió durante el intervalo entre frames (p. ej. el guiado empezó a girar a mitad del intervalo), la estimación es incorrecta.

**Solución.** AirSim expone `client.getImuData()` con velocidad angular cruda del giroscopio a alta frecuencia. En lugar de tomar el valor instantáneo, integrar las muestras de giroscopio acumuladas entre los dos timestamps de captura:

```python
# En AirSimClient, nuevo método:
def get_imu_angular_velocity(self) -> dict:
    imu = self.client.getImuData()
    return {"wx": imu.angular_velocity.x_val,
            "wy": imu.angular_velocity.y_val,
            "wz": imu.angular_velocity.z_val}
```

La integración se hace acumulando `wz × Δt` entre cada par de lecturas de IMU dentro del intervalo de un ciclo. En AirSim la IMU no tiene ruido real (simulación perfecta), por lo que no hay drift de integración — el beneficio es máximo y el riesgo es mínimo. En hardware real habría que modelar el drift, lo que se documenta como limitación de generalización en §12.4.

**Impacto esperado.** Extiende el límite operativo de ~0.175 rad/s (teórico) a un valor determinado por la varianza de la tasa de yaw durante el intervalo, no por la tasa puntual. En guiado normal (≤15°/s = 0.26 rad/s, cerca del límite actual), pequeñas ráfagas de yaw que hoy corrompen la derotación quedarían compensadas.

**Alcance.** Cambios en `src/hardware/airsim_client.py` (método `get_imu_angular_velocity`) y en `src/perception/flow_ttc.py` (pasar velocidad angular integrada en lugar de tomar de `telemetry_curr`). No cambia la firma pública de `FlowTTCEstimator.estimate()` — la integración queda encapsulada en el cliente o se pasa como parámetro adicional opcional.

**Variables de entorno nuevas:** ninguna. El comportamiento es siempre activo si se llama al método IMU.

---

### Fase P2 — Holdover temporal del TTC

**Problema actual.** Cuando `foe_confidence = 0` (yaw activo, textura baja, etc.), `ObstacleField` devuelve `ttc_s = inf` para todos los sectores y el canal de TTC queda mudo. Si el dron está en un giro de 2–3 frames y la última estimación válida era `ttc_centro = 3.5 s`, esa información sigue siendo relevante — el obstáculo no desapareció por el hecho de que el sensor giró.

**Solución.** Mantener en `FlowTTCEstimator` (estado del estimador, no del grafo) el último `ObstacleField` con `foe_confidence > 0`. Cuando el frame actual devuelve `foe_confidence = 0`, devolver ese campo "congelado" con el TTC decrementado por el tiempo transcurrido (`ttc_s -= dt`) hasta un mínimo de 0, y con un flag `source = "holdover"`. El holdover expira después de `FLOW_HOLDOVER_MAX_FRAMES` frames (default 3, = 0.6 s a 5 Hz).

```python
# En FlowTTCEstimator:
FLOW_HOLDOVER_MAX_FRAMES = int(os.getenv("FLOW_HOLDOVER_MAX_FRAMES", "3"))

def estimate(self, curr_frame, prev_frame, telem_curr, telem_prev):
    field = self._compute(curr_frame, prev_frame, telem_curr, telem_prev)
    if field.foe_confidence > 0:
        self._last_valid = field
        self._holdover_count = 0
        return field
    if self._last_valid is not None and self._holdover_count < FLOW_HOLDOVER_MAX_FRAMES:
        self._holdover_count += 1
        dt = (telem_curr["timestamp"] - telem_prev["timestamp"])
        return self._last_valid.decay_ttc(dt, source="holdover")
    return field  # foe_confidence=0, sin holdover disponible
```

`ObstacleField.decay_ttc(dt)` reduce `ttc_s` de cada celda en `dt` segundos, clampea a 0, cambia `source` a `"holdover"`. El `policy_router` y los logs ya leen `field.source`, por lo que la distinción es auditable sin cambios adicionales.

**Condición de seguridad.** Si el holdover expira (`_holdover_count >= FLOW_HOLDOVER_MAX_FRAMES`), se devuelve el campo con `foe_confidence = 0` original — el sistema vuelve al comportamiento actual. El holdover no puede mantenerse indefinidamente porque el entorno puede haber cambiado.

**Variables de entorno nuevas:** `FLOW_HOLDOVER_MAX_FRAMES` (int, default 3).

---

### Fase P3 — Supresión activa de yaw durante percepción

**Problema actual.** Cuando el dron se acerca a un obstáculo (TTC < `TTC_SAFE_THRESHOLD`), el guiado puede estar aplicando yaw para realinearse con el waypoint mientras simultáneamente intenta estimar si hay obstáculo. Si ese yaw supera el límite de derotación, el sensor queda ciego justo cuando más necesita ver.

**Solución.** En `action_map.py` (donde se convierte la macro-acción en comandos de velocidad), limitar el `yaw_rate` a `FLOW_MAX_YAW_DPS_NEAR_OBSTACLE` (default 5°/s = 0.087 rad/s, bien por debajo del límite de 0.175 rad/s) cuando el `policy_router` devuelve `"evasive"` o cuando el TTC del centro es menor que `TTC_SAFE_THRESHOLD`. Fuera de esas condiciones, el yaw del guiado opera con su límite normal (`GUIDANCE_YAW_RATE_MAX_DPS = 15°/s`).

La supresión NO aplica a `girar_90`: ese modo ya sabe que la percepción es inválida durante el giro (la lógica de `policy_router` no toma decisiones de TTC durante `girar_90`) y necesita yaw agresivo para completar la maniobra. Solo afecta al guiado continuo (keep_going + evasive).

```python
# En action_map.py, en la función que arma el comando de velocidad:
FLOW_MAX_YAW_DPS_NEAR_OBSTACLE = float(os.getenv("FLOW_MAX_YAW_DPS_NEAR_OBSTACLE", "5.0"))

def _safe_yaw_rate(yaw_rate_dps, near_obstacle: bool) -> float:
    if near_obstacle:
        return max(-FLOW_MAX_YAW_DPS_NEAR_OBSTACLE,
                   min(FLOW_MAX_YAW_DPS_NEAR_OBSTACLE, yaw_rate_dps))
    return yaw_rate_dps
```

**Trade-off.** El dron realinea su rumbo más lento cuando está cerca de un obstáculo. Para el guiado esto es aceptable: el waypoint no se mueve, y un yaw más lento pero con percepción válida es mejor que un yaw rápido con sensor ciego. El tiempo extra de alineación es del orden de 1–2 ciclos adicionales.

**Variables de entorno nuevas:** `FLOW_MAX_YAW_DPS_NEAR_OBSTACLE` (float, default 5.0).

---

## Opcional / trabajo futuro: MDE (Depth Anything v2 Small)

Si P1–P3 implementadas y validadas no reducen suficientemente la degradación del sensor óptico (medida como fracción de ciclos con `foe_confidence = 0` en el dataset D3 re-corrido), la siguiente opción es reemplazar o complementar el canal de TTC con un estimador de profundidad monocular basado en red neuronal.

**Modelo candidato:** Depth Anything v2 Small (~25 MB, ~50 ms por frame en GPU moderna). Estimación de profundidad densa por frame sin dependencia de movimiento entre frames → sin sensibilidad al yaw.

**Condición de activación:** solo si el VRAM disponible (2–3 GB libres con UE5.5 corriendo) permite cargar VLM + MDE simultáneamente sin thrashing. Medir con `nvidia-smi` en condición de vuelo antes de comprometer implementación.

**Por qué se deja para después:** P1–P3 son cambios algorítmicos puros (sin modelos nuevos, sin VRAM adicional, sin nuevas dependencias). Si resuelven el problema de degradación en el rango operativo de guiado (≤15°/s), MDE no agrega valor para la tesis. Si no alcanzan y el VRAM lo permite, MDE entra como mejora documentada en §12.4.

---

## Fase S1 — Buffer de trayectoria (`FlightTrajectory`)

**Archivo nuevo:** `airsim-loop/src/agents/spatial_history.py`

```python
@dataclass
class TrajectoryEvent:
    timestamp: float
    position: tuple[float, float, float]  # NED, metros, mundo
    heading_deg: float
    action_taken: str                      # macro_action del ciclo anterior
    delta_wp_m: float                      # Δ distancia al waypoint (neg = progresó)
    stall: bool                            # True si delta_wp_m > SLAM_STALL_THRESHOLD_M
    flow_had_evidence: bool                # foe_confidence > 0 ese ciclo
```

El evento se registra al inicio de cada ciclo (con los datos del ciclo anterior), no al final, para
que el buffer tenga el resultado de la acción antes de que se tome la siguiente decisión. Se
instancia una vez en `_build_nodes()` y se pasa por clausura, igual que `FlowTTCEstimator` — no
circula en `DroneState` (estado del proceso, no del grafo).

Variables de entorno:
- `SLAM_HISTORY_SIZE` (int, default 80): 80 ciclos ≈ 16 s a 5 Hz. Suficiente para cubrir la
  aproximación al obstáculo + los primeros intentos de escape.
- `SLAM_STALL_THRESHOLD_M` (float, default 0.3): Δwp por encima del cual el ciclo se clasifica
  como stall (el dron no avanzó hacia el waypoint).

---

## Fase S2 — Resumen textual de trayectoria

**En `spatial_history.py`**, método `trajectory_context_text(current_pos, current_heading_deg)`:

El método agrupa los eventos recientes por zona angular (cuadrantes relativos al heading actual)
y cuenta: cuántos intentos en esa dirección, cuántos produjeron avance, cuántos produjeron stall.
No proyecta en un mapa 2D — clasifica por dirección relativa (frente, izquierda, derecha, atrás).

Ejemplo de salida:
```
HISTORIAL DE TRAYECTORIA (últimos 80 ciclos):
- FRENTE (±30°): 12 intentos de avance → 11 stalls, 1 ciclo con progreso. Zona probable de bloqueo.
- IZQUIERDA (30°–90°): 3 intentos de evasión → 2 stalls. Sin progreso claro.
- DERECHA (30°–90°): 0 intentos. No explorado.
- ATRÁS (>150°): zona de origen; en los últimos 5 m recorridos, sin stalls registrados.
Ciclos en deadlock acumulados: 18. Progreso total hacia el waypoint: -2.4 m (retroceso neto).
```

El VLM recibe esto junto con el frame frontal actual, sin rotación panorámica.
El vocabulario (`FRENTE`, `IZQUIERDA`, `DERECHA`, `ATRÁS`) está alineado con las macro-acciones
disponibles (`MANTENER_RUMBO`, `EVADIR_IZQUIERDA`, `EVADIR_DERECHA`, `FRENAR`).

---

## Fase S2b — Nube de puntos SfM por sectores *(opcional, depende de S2)*

**Condición de activación:** `SLAM_SFM_ENABLED=true` (default `false`). Si la variable no está
activa, S2b se omite completamente y el bloque textual de S2 se usa solo. Esta es la fase más
costosa de implementar y la que tiene mayor riesgo de no aportar en vegetación densa, por eso es
opcional y se evalúa después de validar S1–S2 offline (S5).

### Qué resuelve respecto a S2

`trajectory_context_text()` de S2 describe *intentos y resultados* (stalls, progreso hacia el
waypoint), pero no tiene información sobre *dónde están los obstáculos* en el espacio — solo sabe
que el dron no pudo avanzar. S2b añade evidencia estructural: puntos 3D triangulados de las
superficies que el dron vio mientras se movía, proyectados en el marco del mundo.

### Implementación: SfM con poses conocidas (sin librería externa)

En AirSim la telemetría da la pose de la cámara en cada ciclo sin deriva, lo que elimina la parte
más costosa del SLAM clásico (optimización del grafo de poses, cierre de bucle). Solo se necesita:

1. **Extracción de keyframes:** cada `SLAM_KF_DIST_M` metros de desplazamiento (default 1.0 m),
   guardar el frame + pose de telemetría + descriptores ORB en un buffer de tamaño
   `SLAM_KF_MAX_KEYFRAMES` (default 40). Activar solo cuando `was_moving=True` en el
   `TrajectoryEvent` del ciclo.

2. **Triangulación entre pares de keyframes:** para cada par consecutivo con baseline
   `SLAM_MIN_BASELINE_M` (default 0.5 m), aplicar:
   ```python
   kp1, desc1 = orb.detectAndCompute(kf1.gray, None)
   kp2, desc2 = orb.detectAndCompute(kf2.gray, None)
   matches = bf_matcher.match(desc1, desc2)
   # Filtrar por ratio test (Lowe, 0.75)
   pts_3d = cv2.triangulatePoints(P1, P2, pts1_norm, pts2_norm)
   # P1, P2 de telemetría: K @ [R|t] para cada keyframe
   ```
   Descartar puntos con coordenada Z (profundidad en cámara) negativa o mayor que
   `SLAM_MAX_RANGE_M` (default 20 m).

3. **Acumulación en coordenadas mundo:** los puntos triangulados se proyectan a coordenadas NED
   del mundo y se añaden a un buffer de puntos (`SLAM_MAX_POINTS`, default 5000 puntos, FIFO).

### Conversión a estadístico por sector (no render)

El output de S2b NO es una imagen renderizada para el VLM. Es un bloque de texto que complementa
el de S2, derivado de proyectar la nube en los mismos tres sectores (izquierda/centro/derecha)
del `ObstacleField`, usando la pose actual como referencia:

```
ESTRUCTURA 3D ACUMULADA (nube de puntos SfM, últimos 40 keyframes):
- FRENTE (sector centro, ±30°): 340 puntos, distancia media 6.2 m, densidad ALTA → superficie detectada.
- IZQUIERDA (sector izquierda): 18 puntos, distancia media 14.1 m, densidad BAJA → estructura lejana o matching pobre.
- DERECHA (sector derecha): 3 puntos → sin estructura detectable (no visitado o matching fallido).
Confianza de reconstrucción: 0.62 (fracción de matches que superaron el ratio test).
```

La confianza es importante: si es baja (< `SLAM_MIN_SFM_CONFIDENCE`, default 0.3), el bloque no
se incluye en el prompt para no introducir ruido. En vegetación densa (textura auto-similar,
matches pobres) la confianza caerá por debajo del umbral y S2b se degrada silenciosamente a S2
solo — sin cambios en el parser ni en el esquema JSON de respuesta del VLM.

### Limitación honesta para townsim_ini

La vegetación densa es el caso más difícil para matching de features: ORB/SIFT tienen dificultades
con texturas auto-similares (hojas repetidas, ramas sin corners estables). Las superficies de
edificios que bordean el corredor arbolado se reconstruirán mejor que los árboles mismos que
bloquean el paso. El estadístico de S2b puede ser útil para identificar las paredes laterales del
corredor (y confirmar que izquierda/derecha no son salidas) aunque no capture bien la pared de
vegetación frontal. Este comportamiento debe documentarse en la nota metodológica (§12.3) si S2b
se activa en el experimento final.

### Variables de entorno nuevas

| Variable | Default | Rol |
|---|---|---|
| `SLAM_SFM_ENABLED` | `false` | Activa/desactiva S2b completo |
| `SLAM_KF_DIST_M` | `1.0` | Distancia mínima de desplazamiento para registrar keyframe |
| `SLAM_KF_MAX_KEYFRAMES` | `40` | Tamaño del buffer de keyframes |
| `SLAM_MIN_BASELINE_M` | `0.5` | Baseline mínima entre pares para triangular |
| `SLAM_MAX_RANGE_M` | `20.0` | Profundidad máxima de punto aceptado |
| `SLAM_MAX_POINTS` | `5000` | Tamaño del buffer de puntos 3D (FIFO) |
| `SLAM_MIN_SFM_CONFIDENCE` | `0.3` | Umbral de confianza; si no se alcanza, S2b no se incluye en el prompt |

---

## Fase S3 — Prompt de slam_assess (sin rotación panorámica)

La diferencia arquitectónica clave con `deep_vlm`:

| Aspecto | `deep_vlm` | `slam_assess` |
|---|---|---|
| Frames enviados al VLM | 4 (uno por rumbo tras rotación) | 1 (frame frontal del ciclo actual) |
| Rotación del dron | Sí, 4 × 45° (varios ciclos) | No — sin maniobra extra |
| Contexto temporal | Ninguno (solo el panorama del instante) | Historia de 80 ciclos de trayectoria |
| Latencia de activación | Alta (varios ciclos de giro + asentamiento) | Baja (activa en el mismo ciclo que se detecta el deadlock) |

El prompt nuevo (`SYSTEM_PROMPT_SLAM_ASSESS`) reemplaza a `SYSTEM_PROMPT_DEEP_SCAN`. Estructura:
1. Rol del VLM: árbitro de escape en un deadlock documentado.
2. Bloque de historial: `{trajectory_context}` — generado por `trajectory_context_text()`.
3. Frame actual: el frame frontal del ciclo corriente (sin rotación).
4. Instrucción: "basándote en el historial de intentos y en lo que ves ahora, elige UNA
   macro-acción. Prioriza direcciones no exploradas o la vuelta al origen si el frente está
   cronicamente bloqueado."
5. Vocabulario y esquema JSON: idénticos a los del prompt actual — el parser de respuesta no cambia.

### Fase S3b — Anotación semántica YOLO en eventos de stall *(sub-opción condicional de S3)*

**Activación:** `SLAM_YOLO_ENABLED=true` (default `false`). Sub-opción de S3, no una fase
independiente. Solo se evalúa si S3 ya funciona correctamente y el experimento de S6 muestra que
el historial textual no alcanza para resolver `townsim_ini`.

**Qué añade:** en lugar de correr YOLO en cada ciclo del lazo (innecesario: el VLM ya ve la
imagen con mayor capacidad semántica que YOLO), se corre una única inferencia en el momento en
que se registra un `stall=True` en el `FlightTrajectory`. El resultado anota el evento:

```python
@dataclass
class TrajectoryEvent:
    ...
    stall: bool
    obstacle_class: Optional[str] = None  # "tree" | "building" | "wall" | None
    obstacle_conf: float = 0.0            # confianza de la detección; 0.0 si YOLO desactivado
```

Esto permite que `trajectory_context_text()` enriquezca el bloque con la clase del obstáculo:

```
- FRENTE: 12 stalls consecutivos. Obstáculo identificado: vegetación (árbol, conf=0.71).
  → Considerar PERDER_ALTURA si hay espacio libre debajo.
- IZQUIERDA: 3 stalls. Obstáculo: estructura rígida (edificio, conf=0.84).
  → GANAR_ALTURA o cambio de ruta.
```

Sin S3b, el bloque solo dice "12 stalls, sin progreso" — la clase del obstáculo da al VLM
contexto semántico para razonar sobre la dirección de escape (vertical vs. lateral).

**Por qué no en cada ciclo:** el VLM ya recibe el frame frontal en S3 y puede inferir "árbol"
o "edificio" directamente. Duplicar esa capacidad con YOLO en tiempo real es redundante y añade
latencia al lazo de 5 Hz. La anotación en eventos de stall es el único uso donde YOLO añade
información que el contexto textual no tiene: la clase del obstáculo *en el momento del stall
pasado*, que el VLM del ciclo actual no puede recuperar desde el frame presente.

**Limitación principal:** modelos YOLO con pesos COCO no tienen categorías específicas para
obstáculos de dron en entornos arbóreos. "tree" es una clase COCO pero la confianza en vegetación
densa (`townsim_ini`) puede ser baja o errática. Si `obstacle_conf < SLAM_YOLO_MIN_CONF`
(default `0.45`), el campo `obstacle_class` queda en `None` y el texto del evento no incluye la
anotación — igual que si YOLO estuviera desactivado. El umbral alto (0.45 en vez del típico 0.25)
es deliberado: es mejor no anotar que anotar con clase incorrecta y sesgar al VLM.

**YOLO fue retirado del lazo de vuelo principal** (`graph.py:13`, `detected_obstacles` quedaba
siempre en `[]`). S3b no lo reintegra al lazo — solo lo usa fuera del camino crítico, en el
momento puntual del registro de un stall.

**Variables de entorno:**

| Variable | Default | Rol |
|---|---|---|
| `SLAM_YOLO_ENABLED` | `false` | Activa la anotación semántica en eventos de stall |
| `SLAM_YOLO_MODEL` | `yolov8n.pt` | Peso YOLO a usar (nano = mínimo overhead) |
| `SLAM_YOLO_MIN_CONF` | `0.45` | Umbral de confianza; debajo de este, el campo queda en None |

---

## Fase S4 — Reemplazo en `deep_scan.py`

`DEADLOCK_STRATEGY` deja de ser un selector de tres opciones y pasa a ser un flag binario implícito:
`slam_assess` es el comportamiento por defecto y único. `"blind"` y `"deep_vlm"` quedan en el código
como ramas no activas (bajo un comentario `# legado, no seleccionable en producción`) para que el
historial de commits sea legible, pero el env var ya no los expone.

La degradación interna del modo `slam_assess` (equivalente funcional del `blind` anterior):
- Si `FlightTrajectory` tiene menos de `SLAM_MIN_EVENTS_FOR_CONTEXT` eventos (default 5), no hay
  suficiente historia; el VLM recibe solo el frame actual + "no hay historial disponible aún" y
  el prompt le pide que elija el escape menos arriesgado visible. Esta rama cubre el deadlock en el
  primer ciclo de vuelo, cuando el buffer aún está vacío.
- No hay escape por altitud automático — si el VLM elige `GANAR_ALTURA` o `PERDER_ALTURA` lo hace
  porque el historial o el frame lo justifican, no como fallback ciego.

Impacto en `DroneState`: ningún campo nuevo. `FlightTrajectory` es estado del proceso.
La guardia de no-profundidad (`graph.py` línea 152-156) no se toca.

---

## Fase S5 — Validación offline sobre logs existentes

Sin AirSim corriendo: reconstruir `FlightTrajectory` a partir de los logs de `townsim_ini` ya
archivados en `runs/tesis/` (15 corridas, 5 semillas × 3 brazos).

Verificar, para cada evento de deadlock registrado en esos logs:
1. ¿La `trajectory_context_text()` reconstruida identifica correctamente que el frente estaba
   cronicamente bloqueado?
2. ¿El texto apunta hacia alguna dirección menos intentada (que en los logs resultó ser el escape)?
3. ¿El texto evita marcar como "bloqueada" una zona que en los logs era la salida?

Si la reconstrucción muestra que el contexto hubiera sido correcto en ≥ 2/3 de los deadlocks: la
hipótesis es plausible y vale correr S6. Si el contexto reconstruido es mayormente incorrecto
(p. ej. porque todos los intentos fallaron en todas las direcciones y el VLM no tiene información
útil), el problema de townsim_ini está en el escenario en sí (sin salida local), no en la falta de
memoria — y eso también es un resultado de tesis.

---

## Fase S6 — Protocolo experimental

Línea base ya existente: resultados del cap. 11 con `deep_vlm` (0/5 en `townsim_ini` para los 3
brazos). Tratamiento: mismas condiciones con `slam_assess` activo.

| Comparación | Escenario | Métrica primaria | Secundaria |
|---|---|---|---|
| `slm` `deep_vlm` (cap.11) vs. `slm` `slam_assess` | `townsim_ini` | tasa de éxito | deadlocks resueltos, distancia recorrida |
| `fsm` `deep_vlm` (cap.11) vs. `fsm` `slam_assess` | `townsim_ini` | tasa de éxito | ídem |
| `reactive` `deep_vlm` (cap.11) vs. `reactive` `slam_assess` | `townsim_ini` | tasa de éxito | ídem |
| `slm` `slam_assess` vs. `slm` `deep_vlm` | `townsim_clear` | tiempo de misión | regresión por contexto extra |

La última fila verifica que el contexto de trayectoria no introduzca latencia de generación
que degrade los escenarios ya resueltos (el contexto añade ~300 tokens al prompt).

Protocolo estadístico: K=5 semillas, Mann-Whitney bilateral, Cliff's δ, corrección de Bonferroni —
idéntico al cap. 11 §11.3.2.

---

## Riesgos y criterios de aborto

- **El VLM no usa el contexto textual:** si las decisiones elegidas en `townsim_ini` no guardan
  coherencia con el historial recibido (verificable en `deliberations[]`), la hipótesis de que
  Qwen2.5-VL-3B-Instruct puede razonar sobre historia de trayectoria en texto es incorrecta para
  este modelo/prompt. Señal de aborto: en los logs de S6, el VLM elige `MANTENER_RUMBO` aunque el
  historial señala "FRENTE: 20 stalls consecutivos".

- **Latencia de generación supera el watchdog (`SLM_DEEP_WATCHDOG_MS=12000`):** medir en un run
  corto de calibración antes de S6. Mitigación: truncar `trajectory_context_text()` a los N eventos
  más recientes (`SLAM_CONTEXT_MAX_EVENTS`, default 30).

- **S5 muestra que todos los escenarios de deadlock en townsim_ini no tienen salida local:**
  si el historial confirma que el dron intentó todas las direcciones disponibles y ninguna avanzó,
  la solución no es más memoria — es que la geometría del escenario no tiene salida accesible
  en el rango de percepción monocular. Ese resultado también va al informe: no es un fallo del
  experimento, es la confirmación de que townsim_ini requiere un sensor con mayor alcance (Anexo 7).

---

## Qué actualizar en el informe si se ejecuta

- **Cap. 11 §11.4.2c:** resultados de S6, formato idéntico al resto del capítulo.
- **Cap. 12 §12.3:** nota metodológica que distingue `slam_assess` (memoria de trayectoria sobre
  telemetría) de SLAM visual completo (triangulación 3D, cierre de bucle). Sin esa nota, el lector
  podría interpretar que se implementó SLAM completo.
- **Cap. 12 §12.4:** reescribir el bullet de "maldición monocular" según el resultado: si S6 es
  positivo → `slam_assess` es la mitigación de bajo costo confirmada; si S6 es negativo → la
  mitigación requiere sensor adicional (estéreo, Anexo 7), y la memoria de trayectoria sola no
  basta.
