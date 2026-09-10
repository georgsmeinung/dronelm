# Plan slam_assess — reemplazo del modo de escape por deadlock

**Fecha:** 2026-09-10
**Estado:** exploratorio, no comprometido.
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

| Fase | Qué desbloquea | Entregable |
|---|---|---|
| **S1** Buffer de trayectoria | Memoria de eventos de vuelo independiente del sensor óptico | `FlightTrajectory` en `spatial_history.py` — ring buffer de (posición, heading, acción, Δwp, stall) |
| **S2** Resumen textual para el VLM | Que el VLM reciba historia de intentos, no solo vista actual | `trajectory_context_text()` — qué direcciones se intentaron, cuáles produjeron progreso, cuáles stall |
| **S3** Prompt de slam_assess | Consulta al VLM con contexto de trayectoria + frame actual | `SYSTEM_PROMPT_SLAM_ASSESS` — sin rotación panorámica, solo frame frontal + historia |
| **S4** Reemplazo de `deep_vlm` y `blind` | Que `DEADLOCK_STRATEGY` tenga un único valor útil | `deep_scan.py` con solo `slam_assess`; `blind` y `deep_vlm` quedan como legado no activo |
| **S5** Validación offline | Saber si la historia hubiera sido útil antes de volar | Reconstrucción sobre logs de `townsim_ini` ya existentes |
| **S6** Corrida experimental | El dato que va al cap. 11 | `townsim_ini` K=5 × 3 brazos con `slam_assess` vs. línea base (`deep_vlm`) del cap. 11 |

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
