# Informe de tesis — índice y estado

Estructura de capítulos para la tesis *"Navegación Autónoma de Drones Urbanos con Visión
Monocular y Small Language Model (SLM)"*. Un archivo Markdown por capítulo, para poder
compilar a PDF o HTML por separado o concatenados (por ejemplo con Pandoc) sin tener que
reescribir la estructura cada vez.

## Orden de lectura / compilación

| # | Archivo | Estado | Depende de |
|---|---|---|---|
| 0 | `00-COVER.md` | Existente — resumen requiere revisión (arquitectura desactualizada); es lo último que se actualiza | — |
| 1 | `01-INTRODUCCION.md` | Redactado | — |
| 2 | `02-ESTADO-DEL-ARTE.md` | Redactado | — |
| 3 | `03-ENTORNO-SIMULACION.md` | Redactado — Unreal Engine 5.5 + Cosys-AirSim, entornos urbanos y validación contra telemetría real | — |
| 4 | `04-ARQUITECTURA-LAZO-TACTICO.md` | Redactado — muestra únicamente el grafo de control vigente | — |
| 5 | `05-PERCEPCION-MONOCULAR.md` | Redactado | — |
| 6 | `06-ESTIMACION-TTC.md` | Redactado (parcial: §6.3–6.4 pendientes de datos) | validación de calibración de ocupación, giros agresivos |
| 7 | `07-DECISIONES-SLM.md` | Redactado | — |
| 8 | `08-MODOS-DE-FALLA-LLM.md` | Redactado | — |
| 9 | `09-METODOLOGIA-EXPERIMENTAL.md` | Redactado | — |
| 10 | `10-RESULTADOS.md` | ⏳ Pendiente — corrida experimental completa | corrida con servidor LLM activo |
| 11 | `11-CONCLUSIONES.md` | ⏳ Pendiente | capítulo 10 |
| 12 | `12-REFERENCIAS.md` | Compilado — pendiente de depuración manual (duplicados, entradas no citadas en el texto final) | — |
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
  junto a los capítulos que los referencian; no se movieron.
- El capítulo 4 embebe únicamente el grafo de control vigente
  (`2006-0823 Nuevo  Grafo de Control.mmd`). El grafo previo al refactor (con los nodos
  `canny_xor_gate` y detección YOLO ya retirados) se sacó de `anexos/` — ver más abajo.
- El capítulo 3 embebe algunas de las imágenes de calibración de telemetría ya generadas
  en `informe/` (trayectorias y perfiles de velocidad reales vs. simulados).

## Fuentes citables

El contenido de los capítulos cita `CHANGELOG.md`, `airsim-loop/legacy/README.md`,
el código fuente (`src/perception/flow_ttc.py`, `src/perception/obstacle_field.py`, etc.)
y `plan_tesis/plan-tesis.md`. Los documentos de planificación interna del refactor
(`PLAN-MEJORAS.md`, `PLAN-MEJORAS-2.md`) se usaron como fuente de investigación para
ubicar evidencia, pero no se citan en el texto: son documentos de trabajo, no material
publicable.

## Pendiente

- Completar §6.3 (calibración del canal de ocupación) y §6.4 (validación de derotación
  con giros agresivos) una vez disponibles esos datos.
- Escribir los capítulos 10 (Resultados) y 11 (Conclusiones) con la corrida experimental
  completa (actualmente solo hay corridas preliminares sin servidor LLM activo).
- Depurar `12-REFERENCIAS.md`: es una compilación exhaustiva de la bibliografía del plan
  de tesis aprobado (`plan_tesis/plan-tesis.md` y `plan_tesis/bibliografia/`) más la
  encontrada en `informe/bibliografia/`; falta eliminar lo no citado en el texto final y
  resolver los pocos casos con metadata incompleta (marcados en la sección 12.3).
- El capítulo 3 (§3.2) documenta como desvío de hecho, no como decisión justificada en el
  registro del proyecto, la sustitución del pipeline de fotogrametría de Buenos Aires
  (RealityCapture + OpenStreetMap + Blender) del plan aprobado por entornos urbanos
  genéricos de Unreal Engine. Si en algún momento aparece una justificación documentada
  de ese cambio (actas de reunión, otra fuente), conviene incorporarla ahí.
- Revisar el resumen de `00-COVER.md` cuando se decida actualizarlo (es lo último que se
  toca del informe).
