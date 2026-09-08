# Informe de tesis — índice y estado

Estructura de capítulos para la tesis *"Navegación Autónoma de Drones Urbanos con Visión
Monocular y Small Language Model (SLM)"*. Un archivo Markdown por capítulo, para poder
compilar a PDF o HTML por separado o concatenados (por ejemplo con Pandoc) sin tener que
reescribir la estructura cada vez.

## Orden de lectura / compilación

| # | Archivo | Estado | Depende de |
|---|---|---|---|
| 0 | [`00-COVER.md`](00-COVER.md) | Redactado — Carátula, resumen ejecutivo y palabras clave | — |
| 1 | [`01-INTRODUCCION.md`](01-INTRODUCCION.md) | Redactado — Introducción, motivación, objetivos y desvíos | — |
| 2 | [`02-ESTADO-DEL-ARTE.md`](02-ESTADO-DEL-ARTE.md) | Redactado — Estado del arte y trabajos relacionados | — |
| 3 | [`03-ENTORNO-SIMULACION.md`](03-ENTORNO-SIMULACION.md) | Redactado — Unreal Engine 5.5 + Cosys-AirSim, jerarquía de 3 Tiers (MiniSim, TownSim, CitySim) y telemetría Zenodo | — |
| 4 | [`04-PLANIFICACION-MISION-GCS.md`](04-PLANIFICACION-MISION-GCS.md) | Redactado — Planificación en tierra, GCS WebDCS, estructura de corridas `airsim-runs/` y viewer | — |
| 5 | [`05-ARQUITECTURA-LAZO-TACTICO.md`](05-ARQUITECTURA-LAZO-TACTICO.md) | Redactado — Grafo LangGraph completo: todos los nodos, routers, DroneState, macro-acciones, WaypointTracker y DeiberationService | — |
| 6 | [`06-PERCEPCION-MONOCULAR.md`](06-PERCEPCION-MONOCULAR.md) | Redactado — Pipeline completo DIS→derotación→FOE→TTC→ObstacleField; lógica `is_blocked()`; API pública; complementariedad VLM | — |
| 7 | [`07-ESTIMACION-TTC.md`](07-ESTIMACION-TTC.md) | Redactado — Validación experimental: ground truth de profundidad, dataset 3735 registros, AUC ROC 0.96–0.97, derivación de umbrales por Youden. **Pendiente:** §7.5 calibración ROC del canal de ocupación; §7.6 validación derotación con giros agresivos | datos de giros agresivos y dataset ocupación |
| 8 | [`08-DECISIONES-SLM.md`](08-DECISIONES-SLM.md) | Redactado — Selección de modelo (Qwen2.5-VL-3B), decodificación restringida + parser tolerante, espacio de acción discreto, 5 componentes del prompt, gestión de latencia, LoRA no adoptado | — |
| 9 | [`09-MODOS-DE-FALLA-LLM.md`](09-MODOS-DE-FALLA-LLM.md) | Redactado — 5 modos de falla documentados (schema drift, desalineación temporal, divergencia descalibrada, state clipping en LangGraph, degradaciones sensoriales); metodología de diagnóstico; riesgos residuales | — |
| 10 | [`10-METODOLOGIA-EXPERIMENTAL.md`](10-METODOLOGIA-EXPERIMENTAL.md) | Redactado — Metodología experimental (SLM vs FSM vs Reactivo en 3 Tiers) | — |
| 11 | [`11-RESULTADOS.md`](11-RESULTADOS.md) | ⏳ Parcial — corridas piloto seed=1 completas (3 brazos × 3 Tiers). **Pendiente:** semillas 2–5, escenarios con obstáculos (`townsim_ini`, `citymap_a`), batch G4 completo | corrida batch G4 |
| 12 | [`12-CONCLUSIONES.md`](12-CONCLUSIONES.md) | ⏳ Pendiente | capítulo 11 |
| 13 | [`13-REFERENCIAS.md`](13-REFERENCIAS.md) | Compilado — pendiente de depuración final (eliminar entradas no citadas en texto, resolver metadata incompleta §13.3) | — |
| — | [`anexos/A1-EXPLORACION-SLM-GGUF.md`](anexos/A1-EXPLORACION-SLM-GGUF.md) | Material de referencia — selección de modelos GGUF y evaluación de nivel de innovación | — |
| — | [`anexos/A2-SLM-CONCEPTO-Y-VENTAJAS.md`](anexos/A2-SLM-CONCEPTO-Y-VENTAJAS.md) | Material de referencia (no es capítulo) | — |
| — | [`anexos/A3-SLM-OPTIMIZACION-Y-DESAFIOS.md`](anexos/A3-SLM-OPTIMIZACION-Y-DESAFIOS.md) | Material de referencia (no es capítulo) | — |
| — | [`anexos/A4-OPTIMIZACION-LORA.md`](anexos/A4-OPTIMIZACION-LORA.md) | Material de referencia — alternativa LoRA explorada y no adoptada | — |
| — | [`anexos/A5-DECODIFICACION-RESTRINGIDA.md`](anexos/A5-DECODIFICACION-RESTRINGIDA.md) | Material de referencia — decodificación restringida, GBNF, `json_schema` | — |

## Convenciones

- Un único `#` (H1) por archivo, con el número y título del capítulo, para que la
  concatenación produzca una jerarquía de encabezados consistente.
- Las tablas de resultados que dependen de la corrida experimental final quedan como
  placeholders con las columnas ya definidas, para que la corrida de tesis llene celdas
  en vez de definir estructura.
- Las imágenes y diagramas ya generados (`.png`, `.jpg`, `.mmd`) quedan en `informe/`
  junto a los capítulos que los referencian.
- El capítulo 5 embebe únicamente el grafo de control vigente exportado directamente desde el código compilado (`scripts/export_graph_mmd.py`).
- El capítulo 3 embebe las imágenes de calibración de telemetría en `informe/` (trayectorias y perfiles de velocidad reales vs. simulados).
- El capítulo 4 detalla la planificación previa al vuelo en tierra mediante la estación GCS WebDCS y el compilador de misiones a `MissionManifest` JSON inmutable.

## Fuentes citables

El contenido de los capítulos cita el código fuente (`src/perception/flow_ttc.py`,
`src/perception/obstacle_field.py`, `src/mission/manifest.py`, etc.) y el plan de tesis aprobado (`plan_tesis/plan-tesis.md`).
Las notas y registros de desarrollo interno se utilizaron únicamente como referencia técnica para
ubicar evidencia experimental y métricas, pero no forman parte del texto citado del informe.

## Pendiente

### Datos experimentales faltantes
- **§7.5** — Calibración ROC completa del canal de ocupación: ejecutar `experiments/analyze_occupancy.py`
  sobre el dataset completo (3735 registros), construir curva ROC, derivar umbral por Youden.
  El umbral actual `OBSTACLE_OCCUPANCY_BLOCKED = 0.35` es provisorio.
- **§7.6** — Validación de la derotación con giros agresivos (±0.3–0.5 rad/s). El dataset
  actual solo cubre `|yaw_rate| < 0.05` rad/s.

### Capítulos pendientes de redactar
- **Cap. 11 (Resultados)**: corridas piloto seed=1 completas para los tres brazos en 3 Tiers.
  Falta: semillas 2–5 y escenarios con obstáculos (`townsim_ini`, `citymap_a`). El batch G4
  completo (Brazo × Atasco × Tier × Semillas ≥ 5) es el prerequisito para las conclusiones.
- **Cap. 12 (Conclusiones)**: bloquea en cap. 11.

### Revisión final
- Depurar `13-REFERENCIAS.md`: eliminar entradas no citadas en el texto final y resolver
  los pocos casos con metadata incompleta (marcados en §13.3). Las referencias de los
  capítulos 6–9 reescritos (Vera-Yanez 2024, Al-Kaff 2017, Badrloo 2017, Kaneko 2017,
  Molineros 2012, Raspanti 2025, Geng 2025, Jansen 2023, Wahba 1965) ya están en §13.4
  y deben verificarse como citadas en el texto.

### Nota estructural
- El capítulo 3 (§3.2) documenta como desvío de hecho la sustitución del pipeline de
  fotogrametría de Buenos Aires (RealityCapture + OpenStreetMap + Blender) del plan
  aprobado por la jerarquía de tres Tiers en Unreal Engine (`MiniSim`, `TownSim`, `CitySim`).
