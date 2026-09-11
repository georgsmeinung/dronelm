# PLAN-VLM-REFINEMENT — Refinamiento Estratégico del Nivel VLM

> Iniciado: 2026-09-11  
> Estado: Borrador — pendiente de aprobación antes de implementar  
> Contexto: Tras completar PLAN-MEJORAS-4 (brazo `slm` funcional, datos post-fix  
> validados), el problema central que persiste es que el VLM no está haciendo lo  
> que puede hacer mejor: razonar semánticamente sobre el espacio. Hoy es un árbitro  
> reactivo de emergencia. Este plan lo convierte en un planificador proactivo de  
> metas intermedias.

---

## 0. Diagnóstico: por qué falla el VLM actual

### 0.1 Síntomas observados

| Síntoma | Causa raíz |
|---|---|
| El VLM se llama solo cuando ya hay un bloqueo confirmado | Es reactivo, no proactivo; no puede anticipar |
| Alternancia EVADIR_IZQ / EVADIR_DER sin salida | Vocabulario binario: no puede expresar "dobla 30m, luego sube" |
| El VLM no sabe que lleva 8 ciclos haciendo lo mismo | Sin memoria semántica entre consultas |
| Frame casi estático cuando se le consulta (drone frenado) | Se llama justo cuando el estimador de flujo tiene menos información |
| El VLM no distingue "pared de concreto" de "rama de árbol" en el mismo sector | La acción GANAR_ALTURA / PERDER_ALTURA es correcta solo si el VLM vio bien |

### 0.2 El problema de fondo

El VLM hoy opera como un **interruptor de seguridad**: se activa cuando el grafo táctico ya fracasó. Para ese momento el drone está detenido o casi, el campo óptico tiene baja confianza y el frame es el menos informativo de la secuencia.  

La propuesta es invertir la causalidad: el VLM corre continuamente a frecuencia baja y le dice al nivel táctico **a dónde ir** (una sub-meta), no **qué hacer** (una acción). El nivel táctico y el reactivo se encargan del **cómo** de forma autónoma.

---

## 1. Arquitectura propuesta: tres capas verdaderas

```
┌─────────────────────────────────────────────────────────┐
│  CAPA ESTRATÉGICA (VLM, 0.5–1 Hz)                       │
│  Entrada: video (frames recientes), telemetría semántica │
│           contexto de misión, historial de metas         │
│  Salida : VlmGoal { waypoint_offset: (dx,dy,dz),        │
│                     semantic_label, confidence,          │
│                     mode: "navegar"|"inspeccionar"|... } │
└────────────────────┬────────────────────────────────────┘
                     │ inyecta VlmGoal en DroneState
┌────────────────────▼────────────────────────────────────┐
│  CAPA TÁCTICA (grafo LangGraph, 5 Hz — actual)           │
│  Interpreta VlmGoal como waypoint dinámico               │
│  Activa reactive/evasive cuando TTC < umbral             │
│  VlmGoal nunca llega al motor si hay obst. inminente     │
└────────────────────┬────────────────────────────────────┘
                     │ velocity_command
┌────────────────────▼────────────────────────────────────┐
│  CAPA DE EJECUCIÓN (motor_node + AirSim, 5 Hz — actual) │
│  Aplica corrección de altitud hover, llama execute_vel   │
└─────────────────────────────────────────────────────────┘
```

**Regla de invariante de seguridad**: El nivel reactivo/evasivo puede siempre preemptar un `VlmGoal`. El VLM no emite comandos de velocidad directos — solo metas. Si el VLM está caído o en timeout, el grafo táctico actual toma control total (degradación suave, sin cambio de comportamiento visible).

---

## 2. Cambios al esquema de salida del VLM

### 2.1 Schema actual (a reemplazar)

```json
{ "macro_action": "EVADIR_IZQUIERDA", "rationale": "..." }
```

Problemas: acoplado a la cinemática, binario izq/der, sin magnitud, sin confianza.

### 2.2 Schema propuesto: `VlmGoal`

```json
{
  "goal_type": "waypoint_offset",
  "dx_m": 12.0,
  "dy_m": -5.0,
  "dz_m": 0.0,
  "confidence": 0.85,
  "semantic_label": "rodear_edificio_izquierda",
  "rationale": "Fachada de edificio bloquea frente; calle libre a la izquierda a ~12m",
  "mode": "navegar"
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `goal_type` | enum | `waypoint_offset` \| `direction_vector` \| `hover_inspect` |
| `dx_m`, `dy_m`, `dz_m` | float | Offset en el frame del drone (body frame NED) |
| `confidence` | 0–1 | Confianza semántica; bajo 0.5 → el táctico ignora la meta |
| `semantic_label` | str | Etiqueta legible; va al FlightLogger para análisis |
| `mode` | enum | `navegar` \| `inspeccionar` \| `buscar` \| `esperar` |
| `rationale` | str | Texto de explicación (auditoría) |

**Por qué offset y no posición absoluta**: el VLM no tiene GPS ni mapa en tiempo real. Un offset relativo al frame actual del drone es lo que el VLM puede estimar con alta confianza a partir de video; el `WaypointTracker` puede convertirlo a coordenadas AirSim.

**Compatibilidad hacia atrás**: mientras se desarrolla el nuevo schema, el VLM puede emitir en paralelo el campo `macro_action` legacy. El táctico usa `VlmGoal` si está disponible, o cae al `macro_action` si el confidence < 0.5.

---

## 3. Cambios operacionales: VLM proactivo

### 3.1 Frecuencia de consulta

| Configuración actual | Configuración propuesta |
|---|---|
| Solo cuando hay bloqueo o deadlock | Cada 1.5s siempre (configurable: `VLM_PROACTIVE_INTERVAL_S`) |
| Watchdog: 1500ms | Watchdog proactivo: 2000ms (el grafo táctico sigue sin bloquear) |
| 2 frames (t y t-1) | 3–4 frames (ring buffer ampliado: t, t-1, t-2, ...) |

El `DeliberationService` ya está diseñado para esto: es un hilo worker con cola. Solo hay que separar el trigger de "bloqueo detectado" del trigger de "intervalo de tiempo transcurrido".

### 3.2 Contenido enriquecido del prompt

Agregar al user prompt actual:
1. **Historial de metas recientes**: las últimas 3 `VlmGoal` y si se ejecutaron con éxito (campo `_vlm_goal_history` en DroneState)
2. **Contexto de misión**: etiqueta del waypoint de misión activo (e.g., "WP_3: zona de inspección norte")
3. **Estado del nivel táctico**: si hubo escapes verticales en los últimos N ciclos, número de evasiones recientes
4. **Nota IMU** (ver §4): si el IMU detectó contacto o vibración anormal en el último segundo

### 3.3 Dónde se inyecta `VlmGoal` en el grafo

En `DroneState`, nuevo campo `vlm_goal: Optional[VlmGoal]`.

En `policy_router`: si `vlm_goal` está presente y `confidence > 0.5` y no hay obst. inminente (TTC > TTC_SAFE_THRESHOLD), el router pasa el goal al `WaypointTracker` como `inject_corner` dinámico antes de decidir `keep_going`.

En `deliberative_node` (modo reactivo de emergencia): si hay un deadlock, el VLM se consulta con el schema expandido pero la prioridad es salir del deadlock. El `VlmGoal` de emergencia tiene `mode="navegar"` y confidence forzada a 1.0.

---

## 4. Integración de IMU

### 4.1 Qué aporta el IMU que la visión no tiene

| Señal IMU | Caso de uso |
|---|---|
| Aceleración lineal transversal (ax, ay) | Detección de contacto con rama/malla antes de que el flujo óptico lo confirme |
| Jitter en yaw rate (gyro Z) | El drone está girando forzado por un objeto (e.g., atrapado en follaje) |
| Diferencia velocidad esperada vs real | Stall físico: el drone recibe comando vx=2 m/s pero ax ≈ 0 → obstáculo real |
| Spike en az | Techo o suelo detectado por golpe (fallback de seguridad extrema) |

### 4.2 IMU en AirSim: lo que ya tenemos

La telemetría de `airsim_client.capture()` ya incluye velocidad y orientación. La posición se deriva de GPS simulado. Lo que **no** se usa hoy:
- Acelerómetro lineal crudo (`linear_acceleration` en la API de AirSim)
- Giroscopio crudo (`angular_velocity`)

Ambos están disponibles en `airsim.ImuData`.

### 4.3 Cambio propuesto en `airsim_client.py`

Agregar a `capture()` la lectura de `getImuData()` de AirSim:
```python
imu = client.getImuData()
telemetry["imu"] = {
    "linear_acceleration": {"ax": ..., "ay": ..., "az": ...},
    "angular_velocity":    {"wx": ..., "wy": ..., "wz": ...},
}
```

### 4.4 Uso del IMU por capa

**Capa reactiva** (directo, no pasa por VLM):
- Si `|ax| > IMU_CONTACT_THRESHOLD_G` por 2+ ciclos consecutivos y la velocidad comandada > 0.3 m/s → activar `FRENAR` de emergencia + loggear `imu_contact_event`
- Esta señal **no espera al VLM**: latencia ≤ 1 ciclo (200ms a 5Hz)

**Capa VLM** (informativa):
- Agregar al user prompt: `"- Vibración IMU: {jitter_level} (normal/elevado/crítico)"`
- El VLM puede razonar "el drone está vibrando fuerte → probablemente dentro de follaje → sugiero PERDER_ALTURA con dz=-3m"

**Capa de logging** (diagnóstico):
- Agregar `imu_jitter_level` a cada entrada de `deliberations[]` en FlightLogger
- Permite correlacionar offline: ¿cuántas deliberaciones coinciden con jitter IMU alto?

### 4.5 Stall confirmation mejorado

Reemplazar el contador de ciclos `evasion_stuck_cycles` (proxy heurístico) por una **señal dual**:
- Opción A: contador actual (seguir como está — simple, funciona)
- Opción B: `cmd_vs_actual_stall = (|v_commanded| > 0.5 m/s) AND (|v_actual_from_imu| < 0.1 m/s)` por 3+ ciclos → stall confirmado físicamente

La opción B reduce falsos positivos (el contador puede dispararse por lag del simulador) y acelera la detección en obstrucciones físicas reales.

---

## 4b. Relación con el SLAM de trayectorias (PLAN-SLAM)

El `FlightTrajectory` / `frente_stall_rate` / `slam_assess` son **complementarios**, no reemplazados por este plan. Operan en capas distintas:

- **SLAM (5 Hz, determinista)**: detecta stall geométrico y escala a `deliberative` en ~2s sin costo de inferencia. Sigue siendo el trigger más rápido y confiable.
- **VLM proactivo (0.5–1 Hz, semántico)**: evita que el drone llegue al stall sugiriendo sub-metas antes de que el SLAM tenga que escalar.

Si el VLM proactivo funciona bien, `slam_assess` debería dispararse **menos**. Si sigue disparando igual, es una señal de que el VlmGoal no está siendo efectivo — métrica de diagnóstico útil.

**Integración pendiente (agregar a V2)**: incluir `frente_stall_rate` y `frente_attempts` del `FlightTrajectory` en el user prompt del VLM proactivo. El modelo debe saber "llevas 8 intentos frontales con 75% de stall" antes de sugerir su sub-meta — es exactamente el contexto que le falta hoy.

---

## 4c. Profundidad métrica al VLM en stall (Depth Anything V2 Metric)

### Motivación

El peor momento para consultar al VLM es cuando el drone está quieto: el frame RGB es casi estático, el FlowTTC colapsa a cero evidencia, y el modelo recibe la imagen más pobre de toda la misión. Paradójicamente es exactamente entonces cuando más se le consulta.

La solución no es mejorar el flujo óptico — es complementar el RGB con un canal que **no dependa de movimiento**: un mapa de profundidad estimado desde un único frame.

### Qué se envía al VLM en modo stall

```
[Frame RGB  t]        [Depth map  t  — colormap Plasma]
[Frame RGB  t-1]      [Depth map  t-1 — colormap Plasma]
```

El depth map se codifica como imagen JPEG (pseudocolor Plasma o Inferno: rojo=cerca, violeta=lejos) y se incluye en la lista `images_b64` junto al RGB correspondiente, con etiqueta explícita:

```
[Fotograma t — RGB]
[Fotograma t — Profundidad estimada (rojo=cerca, violeta=lejos)]
[Fotograma t-1 — RGB]
[Fotograma t-1 — Profundidad estimada]
```

El VLM puede entonces razonar: *"hay una región roja densa en el centro-izquierda (objeto próximo) con un corredor violeta a la derecha (espacio abierto) → EVADIR_DERECHA"*, con información geométrica que el RGB solo no le da cuando el drone está frenado.

### Modelo recomendado

**Depth Anything V2 Metric** (variante `outdoor`, backbone `vits` o `vitb`):
- Da metros reales (con incertidumbre) sin referencia externa
- Variante `vits` (~25M parámetros): 3–6 FPS en CPU a 256×144px — suficiente para 5 Hz si se corre en hilo separado
- No toca la GPU que AirSim está usando
- ZoeDepth es alternativa si Depth Anything V2 Metric no está disponible en el entorno conda

### Cuándo se activa

Solo en stall confirmado, no en vuelo normal. El trigger es la misma condición que hoy usa `_query_reason_note()` para emitir "percepción sin evidencia suficiente":

```python
VLM_DEPTH_ON_STALL = os.getenv("VLM_DEPTH_ON_STALL", "true") == "true"

stall_mode = not field.has_evidence()  # FlowTTC sin confianza → drone quieto
if VLM_DEPTH_ON_STALL and stall_mode:
    depth_frames = _estimate_depth_frames(frame_history)  # lista de arrays
    # intercalar: [rgb_0, depth_0, rgb_1, depth_1, ...]
    images_b64 = _interleave_rgb_depth(frame_history, depth_frames)
    image_labels = _interleave_labels(len(frame_history))
```

En vuelo normal (FlowTTC con evidencia) la inferencia de profundidad no se ejecuta — costo cero.

### Restricción de arquitectura: depth NO entra al grafo de control

El mapa de profundidad va **únicamente** al payload del VLM (campo `images_b64` en `DeliberationService`). No se almacena en `DroneState`, no toca `ObstacleField`, no influye en `policy_router` ni en `motor_node`. La restricción `NUNCA depth en DroneState` del §5 se mantiene intacta.

La inferencia ocurre dentro de `_build_vlm_payload()` (nuevo helper en `deliberative.py`), en el hilo worker del `DeliberationService` — nunca en el hilo del grafo.

### Escala: ¿es necesaria?

Para el VLM, la escala métrica es un bonus pero no un requisito. Incluso un depth relativo (MiDaS) le permite razonar sobre qué sector tiene objetos más próximos. La variante métrica mejora la calidad del `rationale` ("hay un objeto a ~3m al centro") pero no cambia el tipo de sub-meta que puede sugerir.

Si Depth Anything V2 Metric presenta problemas de instalación en el entorno `airsimenv`, se puede empezar con MiDaS-Small (relativo) como fallback — el código del VLM no necesita saber si la escala es métrica o relativa; solo ve una imagen colorizada.

### Implementación (fase V2.5 — entre V2 y V3)

1. Agregar `depth_estimator.py` en `src/perception/`: wrapper lazy (el modelo carga solo en el primer stall, no al iniciar el grafo)
2. En `deliberative.py`: `_build_vlm_payload()` detecta stall, llama al wrapper, intercala imágenes con etiquetas
3. Variable de entorno: `VLM_DEPTH_ON_STALL` (default `true`), `VLM_DEPTH_MODEL` (default `"depth-anything-v2-metric-outdoor-vits"`)
4. Test: `test_depth_stall_payload.py` — verifica que en stall el payload tiene el doble de imágenes con etiquetas correctas, y que en vuelo normal no se ejecuta la inferencia
5. Log: agregar `depth_used: bool` a cada entrada de `deliberations[]`

---

## 5. Qué NO cambiar

| Item | Razón |
|---|---|
| `policy_router` y grafo LangGraph | La arquitectura de grafo es sólida; el VLM solo añade un canal más |
| `reactive_node` y `evasive_node` | Son la capa de seguridad; deben ser completamente ciegos al VLM |
| `motor_node` | No toca semántica; aplica comandos cinemáticos |
| Restricción `NUNCA depth en DroneState` | Se mantiene; el IMU no es profundidad |
| Arquitectura de 3 brazos (slm/fsm/reactive) | Solo `slm` cambia internamente; fsm y reactive no se tocan |
| `DeliberationService` (hilo worker, cola) | Se reutiliza sin cambios para el VLM proactivo |

---

## 6. Fases de implementación

### V1 — Schema expandido sin cambiar la frecuencia (1–2 días)

1. Extender `RESPONSE_JSON_SCHEMA` para incluir `dx_m`, `dy_m`, `dz_m`, `confidence`, `semantic_label`, `mode`
2. Actualizar `SYSTEM_PROMPT_VISION` con instrucciones para el nuevo schema
3. Agregar `vlm_goal` a `DroneState`
4. En `_finalize()`: si el response tiene campos del nuevo schema, poblar `state["vlm_goal"]`
5. En `policy_router`: si `vlm_goal.confidence > 0.5` y camino libre, inyectar como `inject_corner`
6. Tests: `test_vlm_goal_schema.py` valida parsing; `test_vlm_goal_injection.py` valida inyección en el router

### V2 — VLM proactivo (1–2 días)

1. Agregar trigger temporal en `capture_node` o en `policy_router`: si han pasado `VLM_PROACTIVE_INTERVAL_S` desde la última consulta, encolar aunque no haya obst.
2. Separar "consulta proactiva" de "consulta de emergencia" en el log (campo `trigger_type`)
3. Ring buffer ampliado: `VLM_FRAME_HISTORY_SIZE=4` por defecto
4. Agregar `_vlm_goal_history` (últimas 3 metas + resultado) al estado y al prompt

### V3 — IMU básico (1 día)

1. `airsim_client.py`: añadir `getImuData()` a `capture()`
2. `perception_node`: calcular `imu_jitter_level` (RMS de aceleración transversal)
3. `policy_router`: si `imu_contact_event` → forzar `evasive` inmediatamente (preempta cualquier ruta)
4. `_build_user_prompt()`: incluir nota de vibración IMU
5. `FlightLogger`: loggear `imu_jitter_level` y `imu_contact_event` por ciclo

### V4 — Stall confirmation por IMU (opcional, depende de datos V3)

1. Analizar logs V3: ¿correlaciona `cmd_vs_actual_stall` con los eventos problemáticos?
2. Si sí: reemplazar o complementar `evasion_stuck_cycles` con señal dual
3. Si no: mantener el contador actual y documentar por qué

---

## 7. Métricas de éxito

| Métrica | Baseline actual | Meta |
|---|---|---|
| Tasa de deadlock en Tier 1 (MiniSim) | TBD (datos post-fix) | -30% |
| Tasa de deadlock en Tier 2 (CitySim) | TBD | -40% |
| % deliberaciones con `adherent=True` | Datos de PLAN-MEJORAS-4 | +10pp |
| Ciclos promedio hasta resolución de deadlock | TBD | -25% |
| Falsos positivos IMU contact | N/A (nuevo) | < 5% de ciclos en vuelo libre |

---

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| VLM proactivo incrementa latencia promedio | El VLM ya corre en hilo aparte; el grafo no bloquea. Ajustar `VLM_PROACTIVE_INTERVAL_S` ≥ 2s |
| Nuevo schema rompe parseo en modelos pequeños | Mantener `macro_action` como campo legacy en el schema; fallback transparente |
| IMU ruidoso en AirSim (sim ≠ real) | Usar filtro EMA con α=0.3; umbral conservador inicial |
| `inject_corner` conflicto con `WaypointTracker` | `VlmGoal` solo se inyecta como hint, nunca reemplaza el WP de misión |
| Regresión en brazo `fsm` y `reactive` | No se tocan; los tests de no-regresión existentes cubren esto |

---

## 9. Preguntas abiertas (a responder antes de V1)

1. **Coordenadas del offset**: ¿body frame (relativo al heading actual) o NED world frame? Body frame es más natural para el VLM (la cámara mira hacia adelante), pero NED es lo que usa el `WaypointTracker`. Hay que decidir la convención y documentarla en el prompt.

2. **Confianza mínima**: ¿0.5 es el umbral correcto? Con un modelo pequeño (phi3, llama3.2-vision) la calibración de confianza puede ser mala. Puede convenir usar 0.7 como default y calibrar con datos reales.

3. **¿Modo "inspeccionar" en esta fase?**: `mode="inspeccionar"` implica que el drone se detiene frente a un objeto y lo rodea. Eso requiere un controlador de misión más sofisticado que el `WaypointTracker` actual. Posiblemente quedarlo como stub en V1 y activarlo en V3.

4. **IMU en AirSim: `getImuData()` ¿está disponible en la versión de la sim?**: verificar antes de implementar V3. Si no está, se puede derivar la aceleración de la diferencia de velocidad entre ciclos (aproximación aceptable a 5Hz).
