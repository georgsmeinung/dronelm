# Plan de implementación 2 — De lazo reconstruido a demo medible

**Fecha:** 2026-08-25
**Origen:** revisión crítica del estado del repo tras la implementación de `PLAN-MEJORAS.md`
(commits del 2026-08-24, `origin/main` = `3c31ecb`).
**Estado de partida:** F0–F4 del plan anterior implementadas; suite de tests en verde
(94 passed); lazo desbloqueado, `ObstacleField` en producción, IPM y Canny retirados con
evidencia, brazos SLM/FSM/reactivo seleccionables, runner y logging operativos.
**Objetivo:** llevar el piloto de *"arquitectura correcta sobre percepción medida pero mal
escalada"* a *"demo completable + corrida de tesis con datos comparables"*.

---

## 0. Criterio de orden

Igual que el plan anterior: ordenado **por dependencia, no por importancia**. La diferencia
es que ahora hay un solo bloqueante duro (G0) y todo lo demás cuelga de él.

| Fase | Qué desbloquea | Estado final |
|---|---|---|
| **G0** Escala de la divergencia | Todo. Hoy `occupancy` satura y anula al canal de TTC calibrado. | `is_blocked()` responde a evidencia real; deliberación vuelve a ser excepción. |
| **G1** Presupuesto temporal | La comparación entre brazos y el realismo del demo. | `LOOP_HZ` con evidencia local; tasa de deliberación medida y acotada. |
| **G2** Validación de la derotación | La confianza en el TTC durante maniobras. | Test no tautológico + dataset con yaw agresivo. |
| **G3** Instrumentación faltante | La tabla de resultados completa. | `min_obstacle_dist_m` poblado, tope de misión, datos versionados. |
| **G4** Corrida de tesis | El capítulo de resultados. | 3 brazos × 3 escenarios × ≥5 semillas, misiones completables, SLM vivo. |
| **G5** Deuda menor | Nada crítico; higiene. | Cinemática única de verdad, WebDCS y `.env.copy` al día. |
| **G6** Escritura | La defensa. | Esqueleto de capítulos con secciones ya escribibles cerradas. |

**Reglas transversales (heredadas y ampliadas):**

1. Ningún umbral nuevo se elige a mano. Todo umbral que llegue a `main` sale de una curva
   ROC o de una medición registrada en el `CHANGELOG.md`.
2. **Toda magnitud física que el código calcule debe tener un test que la ate a su
   relación teórica conocida.** Esta regla es nueva y sale directamente del hallazgo de G0:
   la suite tenía 94 tests en verde y ninguno verificaba que la divergencia calculada
   valiera lo que la física dice que vale.

---

## Fase G0 — Corregir la escala de la divergencia y calibrar la ocupación

Duración estimada: 2–3 días (la mayor parte es análisis offline, no vuelo).
Rama sugerida: `fix/divergence-scale`.
**Es el único bloqueante duro del plan.**

### G0.1 — El hallazgo

`src/perception/flow_ttc.py:253-255` calcula la divergencia del campo traslacional con
`cv2.Sobel(..., ksize=3)` **sin normalizar**. El kernel de Sobel 3×3 equivale a 8× la
derivada central. Acto seguido, la línea 280 deriva la ocupación de ese valor:

```python
cell_occ = float(np.clip(cell_div * 0.5, 0.0, 1.0)) if cell_div > 0 else 0.0
```

Verificación numérica sobre campo traslacional sintético (`dt = 0.2 s`), contra la relación
teórica `∇·v = 2 / TTC` para un plano fronto-paralelo:

| TTC real | `divergence` reportada | Valor correcto | `occupancy` media | % píxeles ≥ 0.35 (umbral de bloqueo) |
|---|---|---|---|---|
| 20.0 s | 0.79 s⁻¹ | 0.10 s⁻¹ | 0.40 | **99 %** |
| 6.7 s | 2.38 s⁻¹ | 0.30 s⁻¹ | 0.99 | 100 % |
| 4.0 s | 3.97 s⁻¹ | 0.50 s⁻¹ | 1.00 | 100 % |

Con un obstáculo a **20 segundos** —inofensivo— el 99 % de los píxeles cruza el umbral de
`Cell.is_blocked()`.

### G0.2 — Por qué es un bloqueante y no un bug menor

`Cell.is_blocked()` (`src/perception/obstacle_field.py:32-35`) es un **OR**:

```python
return self.occupancy >= OCCUPANCY_BLOCKED_THRESHOLD or self.ttc_s <= TTC_BLOCKED_THRESHOLD_S
```

Un canal saturado en un OR **anula al otro**. Es decir: el canal de TTC —el único validado
contra depth en F1.3, con AUC 0.96–0.97— no llega nunca a decidir nada, porque el canal de
ocupación ya devolvió `True`. Consecuencias en cadena, todas verificables leyendo los
consumidores:

| Consumidor | Comportamiento con `occupancy` saturada |
|---|---|
| `is_blocked(sector)` | `True` en todo sector con flujo válido. |
| `blocked_fraction()` | Alto casi siempre → `girar_90` se dispara de más. |
| `has_open_corridor()` | Casi siempre `False` → **el escape por altura vuelve a ser ciego**, justo el mecanismo que se arregló el 2026-0824. |
| `summary_text()` → prompt del SLM | `BLOQUEADO` en los tres sectores casi siempre. |
| `fsm.py::_decide_state()` | Nunca alcanza `STATE_CRUISE`. |
| `policy_router` | Rutea a `deliberative`/`evasive` casi siempre. |

Esto explica el número más anómalo de la corrida de verificación del 2026-0824:
**555 invocaciones al SLM en 593 ciclos (94 %)**. La deliberación por excepción —la tesis
central de la arquitectura— hoy no es excepción: es el caso normal, y no por decisión de
diseño sino por un factor 8 en un operador de derivada.

Es, estructuralmente, el mismo modo de falla que `detected_obstacles = []` con el signo
invertido: antes la percepción mentía *"despejado"*, ahora miente *"bloqueado"*.

### G0.3 — Corrección

- **Archivo:** `src/perception/flow_ttc.py:253-255`.
- Reemplazar el Sobel sin normalizar por una derivada con escala física correcta:

```python
# np.gradient devuelve la derivada por unidad de índice (px), sin factor de kernel.
du_dx = np.gradient(flow_trans[..., 0], axis=1)
dv_dy = np.gradient(flow_trans[..., 1], axis=0)
divergence_map = (du_dx + dv_dy) / dt   # 1/s
```

  (Alternativa mínima si se quiere conservar Sobel por velocidad: dividir por `8.0`.
  `np.gradient` es preferible porque la constante deja de estar implícita.)

- **Escala de la divergencia al espacio de la imagen completa.** `flow_ttc.py` trabaja sobre
  la imagen reducida a `FLOW_DOWNSCALE_WIDTH`. La divergencia (derivada del flujo respecto
  de la posición) es **invariante a la escala isotrópica** —numerador y denominador escalan
  igual— así que no requiere corrección adicional. **Verificarlo con un test**, no asumirlo:
  el mismo campo sintético a 320 px y a 640 px debe dar la misma divergencia.

- **Test de anclaje físico (regla transversal 2):** nuevo
  `tests/test_flow_ttc.py::test_divergence_matches_two_over_ttc`. Campo traslacional
  sintético con TTC conocido (varios valores: 2, 5, 10, 20 s), `dt` conocido; verificar
  `|∇·v − 2/TTC| / (2/TTC) < 0.15`. Este test es el que hubiera atrapado el bug.

### G0.4 — Recalibrar `OBSTACLE_OCCUPANCY_BLOCKED` contra depth

Corregir la escala **no alcanza**: `OBSTACLE_OCCUPANCY_BLOCKED = 0.35`
(`obstacle_field.py:16`) sigue siendo el default provisorio que nunca pasó por F1.3. F1.3
calibró el canal de TTC y **no calibró el canal de ocupación**.

**No hace falta volar de nuevo.** El dataset de F1.3 (`runs/ttc/*.jsonl`, 3735 registros)
ya graba por celda `divergence`, `occupancy`, `confidence`, `ttc_gt_s` y `speed_mps`
(`experiments/collect_ttc_dataset.py:186-193`). Con eso:

1. Recomputar la ocupación offline con la escala corregida:
   `occ_corregida = clip((divergence / 8) * k, 0, 1)`.
2. Reconstruir la profundidad de la celda: `z = ttc_gt_s × speed_mps` (el percentil 20 de
   depth que se usó como ground truth).
3. Definir el evento binario *"celda ocupada"* como `z ≤ θ_z` para `θ_z ∈ {5, 10, 15} m`.
4. Curva ROC de `occ_corregida` contra ese evento; elegir umbral por índice de Youden o por
   una tasa de falsos positivos objetivo; reportar AUC.
5. Fijar `k` y `OBSTACLE_OCCUPANCY_BLOCKED` con esos valores, versionados en `.env` con el
   razonamiento inline (mismo patrón que se usó para `TTC_EVASION_THRESHOLD`).

- **Nuevo:** `experiments/analyze_occupancy.py` (o una sección nueva en `analyze_ttc.py`).
- **Criterio de aceptación:** existe una tabla en el `CHANGELOG.md` con AUC y umbral elegido
  para el canal de ocupación, análoga a la que ya existe para TTC. `.env` deja de tener
  ningún umbral marcado como "provisorio".

### G0.5 — Revisar la semántica del OR

Con ambos canales calibrados, decidir explícitamente si `is_blocked()` debe seguir siendo un
OR o pasar a una regla ponderada por confianza. El OR es defendible (dos evidencias
independientes de peligro), pero **debe documentarse como decisión**, con la tasa de falsos
positivos conjunta medida — no heredarse del código provisorio.

- **Criterio:** la tasa de falsos positivos del `is_blocked()` compuesto está medida sobre el
  dataset de F1.3 y reportada.

---

## Fase G1 — Presupuesto temporal real

Duración estimada: 2–3 días. Depende de G0.

### G1.1 — Re-medir el techo de captura en loopback

`scripts/bench_capture_results.csv` sólo tiene filas de la **topología remota abandonada**
(todas en timeout de 8–9 s, sin importar la resolución). Tras la migración a `127.0.0.1`
no se volvió a medir; `LOOP_HZ = 5.0` sigue sin evidencia y el propio `.env` lo admite.

- Re-correr `scripts/bench_capture.py --samples 200` en la máquina Windows con AirSim local:
  1080×720 / 640×480 / 320×240, con y sin `DepthPlanar`.
- Elegir `LOOP_HZ` por el p95 y **re-escalar los umbrales expresados en ciclos**
  (`EVASION_STUCK_THRESHOLD`, `MIN_PROGRESS_SPEED_MPS`, `MANEUVER_DURATION_S`,
  `ESCAPE_MANEUVER_DURATION_S`, `GIRAR90_DURATION_S`, `FSM_MANEUVER_DURATION_S`).
- **Criterio:** tabla p50/p95 en el `CHANGELOG.md`, `LOOP_HZ` versionado con referencia a esa
  tabla, y período p95 del ciclo ≤ 1.2 × (1/`LOOP_HZ`) en una misión completa.

### G1.2 — La deliberación tiene que volver a ser excepción

Métrica hoy derivable pero no reportada como tal
(`slm_invocations / cycles` en `summary.json`).

- **Elevar `deliberation_rate` a columna de primera clase** en
  `src/logging/flight_logger.py` (`summary.json`) y en la tabla de
  `experiments/analyze.py`. Agregar también el histograma de `route` por corrida
  (`keep_going` / `evasive` / `deliberative` / `girar_90` / `fsm` / `degraded`): es la
  radiografía del comportamiento del router y hoy no se reporta.
- **Objetivo explícito de diseño: `deliberation_rate ≤ 0.10`.** Si tras G0 sigue por encima,
  el ajuste sale de datos (subir `TTC_EVASION_THRESHOLD`, exigir `MIN_CONFIDENCE` más alta,
  o requerir persistencia temporal del bloqueo antes de deliberar), no de tanteo.
- **Justificación cuantitativa:** latencia medida del SLM en régimen 1.9–3.4 s
  (4 muestras, `.env`). A 5 Hz eso son **10 a 17 ciclos de `FRENAR` por deliberación**. Con
  `deliberation_rate = 0.94` el vuelo es literalmente stop-and-go; con 0.10 el costo
  amortizado vuelve a ser tolerable.
- **Criterio:** un vuelo instrumentado de ≥ 120 s con el SLM vivo reporta
  `deliberation_rate` y el histograma de rutas, y el valor está dentro del objetivo o hay una
  decisión documentada de por qué no.

### G1.3 — Primer vuelo con el SLM realmente respondiendo

En las 18 corridas de `runs/f33_batch_v2` el servidor de LM Studio no estaba levantado:
`fallback = 100 %`, `timeout = 100 %`. La tabla actual **no compara un SLM contra una FSM**:
compara la FSM contra la política de fallback determinista del brazo SLM.

- Verificar `LOCAL_LLM_URL` accesible desde la máquina Windows antes de cada batch.
- **Guarda de sanidad:** que `experiments/runner.py` haga un ping al endpoint del SLM al
  arrancar cuando `AGENT_ARM=slm`, y **aborte con error explícito** si no responde. Una
  corrida de 90 minutos que produce 100 % de fallback silencioso es tiempo perdido.
- **Criterio:** una corrida con `slm_fallback_rate < 0.2` y al menos una decisión no-fallback
  auditable en `deliberations[]`.

---

## Fase G2 — Validar la derotación de verdad

Duración estimada: 2 días (1 de vuelo + 1 de análisis). Puede correr en paralelo con G1.

### G2.1 — El test actual es tautológico

`tests/test_flow_ttc.py::test_derotation_cancels_pure_yaw_rotation` construye el campo de
rotación **con la misma fórmula** que usa `_derotate` para restarlo. Verifica que la resta
funciona; no verifica el modelo físico ni la convención de signos entre el yaw NED de la
telemetría y el eje de la cámara. **Un signo invertido pasaría el test.**

- **Nuevo test:** generar el par de frames rotando una imagen sintética texturada con una
  homografía de rotación construida **independientemente** (`cv2.warpPerspective` con
  `K · R(Δθ) · K⁻¹`), correr `estimate()` completo, y exigir que el campo resultante tenga
  `foe_confidence ≈ 0` y TTC `inf` en todas las celdas.
- Cubrir los tres ejes por separado (yaw, pitch, roll) y con ambos signos.

### G2.2 — Dataset con yaw agresivo

El escenario `yaw_only` de F1.3 quedó casi todo en el bin `|yaw_rate| ∈ [0, 0.05)` rad/s
—como el propio `.env` documenta—, así que valida detección frontal pero **no valida la
derotación**, que es precisamente el mecanismo que debía resolver el "vuelo cortado y
errático" del 2026-0820.

- Agregar a `ScriptedPilot` (`experiments/collect_ttc_dataset.py`) un escenario `yaw_sweep`
  con giros comandados de ±0.3 a ±0.5 rad/s, sin traslación, frente a una pared y en
  espacio abierto.
- Re-correr la estratificación por `|yaw_rate|` de `analyze_ttc.py` con bins poblados.
- **Criterio:** el error relativo de TTC en los bins de `|yaw_rate| > 0.2` rad/s no es
  significativamente peor que en el bin `[0, 0.05)`. Si lo es, hay un error de signo o de
  sincronización telemetría↔frame que hay que corregir antes de G4.

### G2.3 — Validación cruzada del modelo de rotación (pendiente de F1.2)

El plan original pedía estimar además la afín global entre frames
(`cv2.estimateAffinePartial2D` sobre features ralos) y comparar con la predicción de
telemetría; divergencia sostenida entre ambas indica actitud desincronizada del frame por
latencia RPC. No se implementó.

- Implementarlo **como diagnóstico offline** en `collect_ttc_dataset.py` (grabar ambos
  valores por ciclo), no en el hot path del lazo.
- **Criterio:** el desfase medido entre rotación por telemetría y rotación por imagen está
  cuantificado y documentado. Si es grande, es un resultado de tesis por derecho propio
  (la telemetría de actitud no está sincronizada con la cámara en AirSim).

---

## Fase G3 — Completar la instrumentación

Duración estimada: 2–3 días. Depende de G0; independiente de G1/G2.

### G3.1 — `min_obstacle_dist_m` deja de salir `null`

`experiments/runner.py:128` lo omite a propósito ("requiere canal depth, omitido para no
duplicar `simGetImages` en el hot path"). Es la métrica de seguridad más informativa de toda
la tabla y hoy sale `null` en el 100 % de las filas.

- Pedir el canal depth a **cadencia baja** (1 de cada N ciclos, `DEPTH_METRIC_EVERY_N`,
  default 5) y registrar el percentil 5 de la profundidad del sector central.
- Sigue siendo **sólo para métricas**: no se realimenta al control, para no contaminar el
  experimento. Dejarlo explícito en el código y en la tesis.
- **Criterio:** `DistMin p5 (m)` deja de ser `N/D` en la tabla de `analyze.py`.

### G3.2 — Tope de misión en `main.py`

`main.py:213` es un `while True` sin presupuesto (el runner sí tiene `max_cycles` /
`max_seconds`). Un atasco genuinamente irresoluble no termina la corrida por sí solo.

- Agregar `MISSION_MAX_SECONDS` y `MISSION_MAX_CYCLES` con el mismo criterio que el runner,
  y cerrar el `FlightLogger` con `success=False` y una razón de terminación explícita
  (`completed` / `timeout` / `stopped` / `collision`).
- **Criterio:** toda corrida termina con una razón registrada en `summary.json`.

### G3.3 — Versionar los datos

`runs/` está en `.gitignore:18`. Los JSONL que sustentan la calibración de los umbrales y
las tablas de resultados **no están versionados**: la tesis no sería reproducible.

- Archivar como mínimo: el dataset de F1.3 (más el de G2.2) y los JSONL + `summary.json` de
  la corrida final de G4.
- Opciones: `data/` con Git LFS, o un depósito con DOI (Zenodo) referenciado desde el
  `README.md` y desde la tesis. Preferible Zenodo por tamaño y por citabilidad.
- **Criterio:** la tesis puede citar un identificador estable para cada tabla de resultados.

---

## Fase G4 — Corrida de tesis

Duración estimada: 1 día de cómputo + 1 de análisis. **Depende de G0, G1, G3.**

Sólo se ejecuta cuando estén cerrados: la escala de la divergencia (G0.3), la calibración de
ocupación (G0.4), `LOOP_HZ` con evidencia (G1.1), el SLM respondiendo (G1.3) y el tope de
misión (G3.2).

### G4.1 — Diseño

- **Brazos:** `slm`, `fsm`, `reactive` (cota inferior).
- **Escenarios:** los dos existentes (`manhattan_a`, `manhattan_b`) **más un tercero** con
  un bloqueo frontal masivo genuino, para ejercitar la rama que justifica la existencia del
  SLM. Sin ese escenario, la comparación mide sobre todo crucero.
- **Semillas:** ≥ 5 por combinación (hoy 2–3). Mann-Whitney necesita varianza.
- **Presupuesto:** suficiente para completar la misión con navegación sana. Los 300 s del
  batch anterior no alcanzaron ni siquiera sin el deadlock; estimar desde la longitud de
  ruta y la velocidad de crucero medida, con margen ×2.
- **Criterio de arranque:** una corrida piloto de una sola combinación completa la misión
  (`success=True`). Si ninguna corrida puede tener éxito, no tiene sentido gastar las 45.

### G4.2 — Métricas a reportar

Ya implementadas salvo donde se indica:

- tasa de éxito de misión;
- colisiones por misión y por km;
- `min_obstacle_dist_m` p5 (**G3.1**);
- SPL (implementado);
- tiempo a destino;
- latencia p50/p95 por brazo **y por ruta** (implementado);
- `deliberation_rate` e histograma de rutas (**G1.2**);
- invocaciones de SLM por misión, tasa de fallback, tasa de timeout del watchdog;
- `adherence_rate` con y sin `json_schema`;
- Mann-Whitney U sobre semillas + tamaño de efecto.

### G4.3 — El resultado puede ser negativo, y está bien

Se mantiene la pregunta abierta de F2.6, ahora con instrumentación para responderla: **¿el
SLM aporta sobre la FSM?** Diseñar el análisis para poder responder **por tipo de
escenario**, no en agregado. Un resultado del tipo *"no aporta en el bloqueo frontal masivo,
donde la FSM decide igual y en 90 ms; sí aporta en la elección de calle transversal"* es un
hallazgo publicable y honesto — y es el tipo de conclusión que sostiene una defensa mejor
que un empate ambiguo.

---

## Fase G5 — Deuda menor

Duración estimada: 1 día. Sin dependencias.

- **`evasive.py:73-74` rompe F2.4.** Vuelve a pisar `vx = 1.2` y `yaw_rate = ±15.0` después
  de llamar a `action_to_command()` — exactamente el patrón de doble definición cinemática
  que F2.4 vino a eliminar. Mover esos valores a `action_map.py` (p. ej. un parámetro
  `aggressive=True` en la evasión rápida) y agregar el test que verifique que ningún nodo
  modifica el comando devuelto.
- **Tile "XOR %" muerto en WebDCS** (`airsim-plan/webdcs/.../app.js`): decidir si se remueve
  o se reemplaza por `deliberation_rate` / `blocked_fraction`, que sí tienen contenido ahora.
- **`airsim-loop/.env.copy`** desactualizado (aún con config de YOLO, sin las variables
  nuevas): actualizar o eliminar. Si se elimina, documentar que `.env` versionado es la
  plantilla.
- **`_estimate_foe`: constantes mágicas.** `min(confidence * 3.0, 1.0)` y
  `min(confidence, 0.3)` (`flow_ttc.py`) son factores sin justificación. Documentarlos o
  derivarlos de la fracción de inliers esperada; hoy afectan directamente a
  `MIN_CONFIDENCE_FOR_BLOCKED`, que sí es un umbral de decisión.
- **`degraded_hover` y colisión:** verificar que una colisión detectada
  (`telemetry.collision.has_collided`) termine la corrida o al menos quede marcada como
  evento en el JSONL, no sólo contada.

---

## Fase G6 — Escritura del informe

Se puede arrancar **ya**, en paralelo con G0–G3. No esperar a G4.

### G6.1 — Armar el esqueleto numerado

`informe/` hoy tiene notas sueltas (`01-INTRO.md` es un compendio de modelos GGUF, no un
capítulo). Crear el esqueleto de capítulos y asignar el material existente, con las tablas
de resultados ya diseñadas como placeholders vacíos — así el batch de G4 llena celdas en vez
de definir estructura.

### G6.2 — Secciones escribibles hoy, con material completo

| Sección | Material disponible |
|---|---|
| Arquitectura del lazo táctico | Grafo estable, `.mmd` generado desde el código compilado, `PLAN-MEJORAS.md` + `CHANGELOG.md` con la justificación de cada decisión. Núcleo: deliberación por excepción (gatekeeper, freno previo, watchdog, fallback determinista, persistencia anti-flip-flop). |
| Percepción monocular sin redes neuronales | Retiro de YOLO y retiro del IPM como decisiones de diseño con argumento técnico. `legacy/README.md`. |
| Estimación de TTC y su validación | F1.3 completa. **Enmarcar con precisión:** AUC 0.96–0.97 con r = −0.034 y error relativo mediano 66 % significa que es un **ordenador de riesgo monótono, no un tiempo de colisión en segundos**. Escribirlo como *"puntaje de riesgo calibrado por ROC, cuyo umbral tiene unidades de segundos por construcción pero no interpretación métrica"* es más defendible que presentar "TTC = 3.2 s" como magnitud física. |
| Ingeniería de decisiones del SLM | Decodificación restringida vs. parser tolerante, `adherence_rate`, espacio de acción discreto, `action_to_command` como frontera entre lenguaje y cinemática. |
| **Modos de falla de lazos de control híbridos con LLM** | Capítulo (o anexo extenso) por derecho propio. Los cuatro bugs del 2026-0824: claves descartadas por el esquema de LangGraph, ciclo límite de la red de seguridad que se reseteaba a sí misma, métrica de atasco autoincoherente, escape ciego a la percepción. Más el hallazgo de G0. La tabla de altitudes por corrida (356 m de ascenso) es una figura sola. Casi nadie publica esto. |
| Metodología experimental | Diseño de los tres brazos, métricas, protocolo estadístico. Se escribe sin datos: es el "cómo". |

### G6.3 — No escribible todavía

Capítulo de resultados comparativos SLM vs FSM, y conclusiones. Dependen de G4.

### G6.4 — Tesis transversal a sostener

El hilo conductor que atraviesa los dos planes de mejora y que conviene declarar
explícitamente en la introducción y retomar en las conclusiones:

> En un sistema de control donde un modelo de lenguaje consume descripciones de escena, el
> error más caro no está en el modelo sino en la interfaz que lo alimenta — y no se detecta
> observando el comportamiento, porque el modelo siempre produce una respuesta plausible.

Hay tres instancias documentadas del mismo patrón, con distinta forma:

1. `detected_obstacles = []` tras el retiro de YOLO → la percepción afirmaba *"despejado"*.
2. `frame_history` vacío con etiquetas `[Fotograma t-3]` → se le afirmaba al modelo una
   historia temporal inexistente.
3. `occupancy` saturada por un factor 8 (G0) → la percepción afirma *"bloqueado"*.

En los tres casos el sistema **volaba** y el modelo **respondía**. Ninguno se detectó
mirando la salida; los tres se detectaron leyendo el contrato entre productor y consumidor.
Eso es un resultado, no una anécdota de desarrollo.

---

## Dependencias y camino crítico

```
G0.3 (escala de divergencia) ──> G0.4 (calibrar ocupación) ──> G0.5 (semántica del OR)
                                        │
        ┌───────────────────────────────┼───────────────────────────┐
        v                               v                           v
  G1.1 (LOOP_HZ local)           G3.1 (min_obstacle_dist)     G2 (derotación)
        │                               │                           │
        v                               v                           │
  G1.2 (deliberation_rate)       G3.2 (tope de misión)              │
        │                               │                           │
        v                               │                           │
  G1.3 (SLM vivo) ─────────────────────┴───────────────────────────┘
        │
        v
  G4 (corrida de tesis) ──> G6.3 (resultados y conclusiones)

  G5 y G6.1/G6.2 corren en paralelo desde el día 1.
```

**Camino crítico:** G0.3 → G0.4 → G1.1 → G1.3 → G4.

---

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Corregida la escala, `occupancy` queda tan baja que nunca dispara y el sistema se vuelve kamikaze | Se pasa del falso positivo total al falso negativo total | G0.4 calibra el umbral con ROC en vez de elegirlo; el canal de TTC (ya validado, AUC 0.96) queda como red independiente en el OR |
| `deliberation_rate` sigue alto tras G0 | El demo es stop-and-go y la comparación SLM vs FSM mide latencia, no navegación | G1.2 lo mide explícitamente; el ajuste sale de subir umbrales con datos, o de exigir persistencia temporal del bloqueo antes de deliberar |
| La derotación tiene un error de signo (G2) | Girar dispara frenos espurios: regresión del modo de falla del 2026-0820 | G2.1 con homografía independiente lo detecta sin volar; G2.2 lo confirma con datos |
| El SLM no responde dentro del watchdog en régimen | La corrida de tesis vuelve a ser FSM vs fallback | G1.3 agrega ping de sanidad que aborta la corrida; `SLM_WATCHDOG_MS` ya calibrado en 6000 ms sobre latencias medidas de 1.9–3.4 s |
| Ninguna misión se completa aun con todo corregido | No hay `success` con varianza y G4 no produce estadística | Corrida piloto obligatoria (G4.1) antes del batch completo; si falla, el problema es de diseño de escenario/presupuesto, no de política |
| El análisis offline de G0.4 no es posible porque `runs/ttc/*.jsonl` se perdió | Hay que volver a volar el dataset de F1.3 | Verificar la existencia de esos archivos **antes** de arrancar G0.4; si no están, re-correr `collect_ttc_dataset.py` (30 min) y aprovechar para incluir el escenario `yaw_sweep` de G2.2 en la misma sesión |

---

## Lo que no se toca

Fortalezas ya construidas que este plan debe **preservar**:

1. **La arquitectura de deliberación por excepción** y todas sus salvaguardas: freno previo,
   watchdog, whitelist de acciones, parser tolerante como red del `json_schema`, persistencia
   de maniobra, enclavamiento del escape agotado.
2. **`deliberations[]` como contrato congelado**: sólo se le agregan campos, nunca se le
   quitan. Es la evidencia primaria de cada decisión del modelo.
3. **`ObstacleField` como contrato único de percepción.** G0 corrige *cómo se calcula* una de
   sus celdas; no toca la superficie de la API ni reintroduce accesos crudos al flujo óptico
   desde los consumidores.
4. **La disciplina de "todo umbral sale de una medición"** establecida en el plan anterior y
   sostenida en `.env` con el razonamiento inline. Es, probablemente, la mejor práctica
   metodológica del proyecto y hay que mantenerla incluso cuando cueste una sesión de vuelo.
5. **`WaypointTracker`**, con la histéresis y el EMA agregados el 2026-0824.
6. **`callibration_flight` y `local-llm-eval`**: contribuciones independientes del estado del
   lazo.
