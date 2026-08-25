# Informe de tesis — índice y estado

Estructura de capítulos para la tesis *"Navegación Autónoma de Drones Urbanos con Visión
Monocular y Small Language Model (SLM)"*. Un archivo Markdown por capítulo, para poder
compilar a PDF o HTML por separado o concatenados (por ejemplo con Pandoc) sin tener que
reescribir la estructura cada vez.

## Orden de lectura / compilación

| # | Archivo | Estado | Depende de |
|---|---|---|---|
| 0 | `00-COVER.md` | Redactado — Carátula, resumen ejecutivo y palabras clave | — |
| 1 | `01-INTRODUCCION.md` | Redactado — Introducción, motivación, objetivos y desvíos | — |
| 2 | `02-ESTADO-DEL-ARTE.md` | Redactado — Estado del arte y trabajos relacionados | — |
| 3 | `03-ENTORNO-SIMULACION.md` | Redactado — Unreal Engine 5.5 + Cosys-AirSim, CitySim y telemetría Zenodo | — |
| 4 | `04-PLANIFICACION-MISION-GCS.md` | Redactado — Planificación en tierra antes del vuelo y GCS WebDCS | — |
| 5 | `05-ARQUITECTURA-LAZO-TACTICO.md` | Redactado — Grafo de decisión por tick (`airsim-loop`) | — |
| 6 | `06-PERCEPCION-MONOCULAR.md` | Redactado — Percepción monocular sin redes neuronales (flujo óptico y TTC) | — |
| 7 | `07-ESTIMACION-TTC.md` | Redactado (parcial: §7.3–7.4 pendientes de datos) | validación de calibración de ocupación, giros agresivos |
| 8 | `08-DECISIONES-SLM.md` | Redactado — Ingeniería de decisiones del SLM, `json_schema` y macro-acciones | — |
| 9 | `09-MODOS-DE-FALLA-LLM.md` | Redactado — Modos de falla de lazos de control híbridos con LLM | — |
| 10 | `10-METODOLOGIA-EXPERIMENTAL.md` | Redactado — Metodología experimental (SLM vs FSM vs Reactivo) | — |
| 11 | `11-RESULTADOS.md` | ⏳ Pendiente — corrida experimental completa | corrida con servidor LLM activo |
| 12 | `12-CONCLUSIONES.md` | ⏳ Pendiente | capítulo 11 |
| 13 | `13-REFERENCIAS.md` | Compilado — pendiente de depuración manual (duplicados, entradas no citadas en el texto final) | — |
| — | `anexos/A1-EXPLORACION-SLM-GGUF.md` | Material de referencia (no es capítulo) | — |
| — | `anexos/A2-SLM-CONCEPTO-Y-VENTAJAS.md` | Material de referencia (no es capítulo) | — |
| — | `anexos/A3-SLM-OPTIMIZACION-Y-DESAFIOS.md` | Material de referencia (no es capítulo) | — |
| — | `anexos/A4-OPTIMIZACION-LORA.md` | Material de referencia — alternativa no adoptada | — |
| — | `anexos/A5-DECODIFICACION-RESTRINGIDA.md` | Material de referencia (no es capítulo) | — |

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

- Completar §7.3 (calibración del canal de ocupación) y §7.4 (validación de derotación
  con giros agresivos) una vez disponibles esos datos.
- Escribir los capítulos 11 (Resultados) y 12 (Conclusiones) con la corrida experimental
  completa (actualmente solo hay corridas preliminares sin servidor LLM activo).
- Depurar `13-REFERENCIAS.md`: es una compilación exhaustiva de la bibliografía del plan
  de tesis aprobado (`plan_tesis/plan-tesis.md` y `plan_tesis/bibliografia/`) más la
  encontrada en `informe/bibliografia/`; falta eliminar lo no citado en el texto final y
  resolver los pocos casos con metadata incompleta (marcados en la sección 13.3).
- El capítulo 3 (§3.2) documenta como desvío de hecho la sustitución del pipeline de fotogrametría de Buenos Aires
  (RealityCapture + OpenStreetMap + Blender) del plan aprobado por entornos urbanos
  genéricos de Unreal Engine (`CitySim`).
