# Informe de tesis — índice y estado

Estructura de capítulos para la tesis *"Navegación Autónoma de Drones Urbanos con Visión Monocular y Modelos de Lenguaje Visual Pequeños"*. Un archivo Markdown por capítulo, para poder
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
| 5 | [`05-ARQUITECTURA-LAZO-TACTICO.md`](05-ARQUITECTURA-LAZO-TACTICO.md) | Redactado — Grafo LangGraph de cuatro nodos (`capture → perception → navigate → motor`) con dos lazos desacoplados: lazo rápido a 5 Hz (guiado, evasión por flujo óptico, `GIRAR_90`) y capa estratégica asíncrona del VLM que propone sub-metas ancladas a la pose del fotograma; `StallDetector` (dron trabado, sin progreso al waypoint); resolución de deadlock por barrido panorámico `deep_vlm` con rumbos medidos; `WaypointTracker` y sub-metas; detección de techo y `z_path_blocked`; `DroneState`; salvaguardas (sin canal de profundidad); registro de vuelo, vigilancia de congelamiento y `land_smooth` | — |
| 6 | [`06-PERCEPCION-MONOCULAR.md`](06-PERCEPCION-MONOCULAR.md) | Redactado — Pipeline completo DIS→derotación→FOE→TTC→ObstacleField; lógica `is_blocked()`; API pública; complementariedad VLM | — |
| 7 | [`07-ESTIMACION-TTC.md`](07-ESTIMACION-TTC.md) | Redactado — Validación experimental: etiquetas de referencia de profundidad, dataset 3735 registros, AUC ROC 0.96–0.97, umbrales por Youden; IT.7.5 calibración ROC del canal de ocupación (D2, parcial) y IT.7.6 validación de la inhibición ante giros agresivos (D3, parcial) | datos de giros agresivos y dataset ocupación |
| 8 | [`08-DECISIONES-SLM.md`](08-DECISIONES-SLM.md) | Redactado — Selección de modelo (LFM2.5-VL-1.6B Q4_K_M GGUF, tag `lfm2.5-vl-1.6b:q4km-ctx8k` en Ollama local; antes Qwen2.5-VL-3B), decodificación restringida + parser estricto, rol del VLM como perceptor semántico anclado al mundo (grilla de 3×3 con dirección absoluta en la capa estratégica, imágenes numeradas con rumbo medido en el barrido), `action_to_command`, prompts, latencia y consulta asíncrona con caducidad, nombres de campo compactos, LoRA no adoptado | — |
| 9 | [`09-MODOS-DE-FALLA-LLM.md`](09-MODOS-DE-FALLA-LLM.md) | Redactado — 6 modos de falla documentados (schema drift, desalineación temporal, divergencia descalibrada, state clipping en LangGraph, degradaciones sensoriales, integración del VLM), cada uno con su mecanismo de contención; metodología de diagnóstico; riesgos residuales | — |
| 10 | [`10-METODOLOGIA-EXPERIMENTAL.md`](10-METODOLOGIA-EXPERIMENTAL.md) | Redactado — Metodología experimental (SLM vs FSM vs Reactivo en 3 Tiers): hipótesis, banco de prueba a bordo (IT.10.2), diseño factorial y comparaciones (IT.10.3), escenarios, réplicas, métricas, protocolo estadístico y amenazas a la validez; el detalle operativo está en el Anexo 12 | — |
| 11 | [`11-RESULTADOS.md`](11-RESULTADOS.md) | Redactado — banco de prueba a bordo (IT.11.0) y corrida productiva v4: 6 lotes, 210 corridas (IT.11.1–IT.11.7), con los defectos del brazo FSM que sesgan la comparación (IT.11.5) | — |
| 12 | [`12-CONCLUSIONES.md`](12-CONCLUSIONES.md) | Redactado sobre la corrida v4 | — |
| 13 | [`13-REFERENCIAS.md`](13-REFERENCIAS.md) | Compilado y depurado — todas las entradas citadas en el texto; enlaces y metadatos verificados contra arXiv/DataCite/Crossref o la página original (ver nota de verificación) | — |
| — | [`anexos/A1-EXPLORACION-SLM-GGUF.md`](anexos/A1-EXPLORACION-SLM-GGUF.md) | Material de referencia — selección de modelos GGUF, decodificación estructurada y análisis de innovación | — |
| — | [`anexos/A2-SLM-OPTIMIZACION-Y-DESAFIOS.md`](anexos/A2-SLM-OPTIMIZACION-Y-DESAFIOS.md) | Material de referencia — técnicas de optimización, compresión y mitigación de desafíos en SLM | — |
| — | [`anexos/A3-OPTIMIZACION-LORA.md`](anexos/A3-OPTIMIZACION-LORA.md) | Material de referencia — optimización y especialización con LoRA/QLoRA para navegación aérea | — |
| — | [`anexos/A4-DECODIFICACION-RESTRINGIDA.md`](anexos/A4-DECODIFICACION-RESTRINGIDA.md) | Material de referencia — decodificación restringida, gramáticas formales, GBNF, `json_schema` y optimización del grafo de control | — |
| — | [`anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md`](anexos/A5-PERCEPCION-MONOCULAR-FLUJO-OPTICO.md) | Material de referencia — fundamentos matemáticos de percepción monocular, flujo óptico y estimación de TTC | — |
| — | [`anexos/A6-CONFIGURACION-ENTORNO-REPRODUCIBILIDAD.md`](anexos/A6-CONFIGURACION-ENTORNO-REPRODUCIBILIDAD.md) | Material de referencia — configuración del entorno de simulación, variables de sistema y protocolo de reproducibilidad | — |
| — | [`anexos/A7-MALDICION-MONOCULAR-ESTEREO.md`](anexos/A7-MALDICION-MONOCULAR-ESTEREO.md) | Material de referencia — formaliza la "maldición monocular" (ambigüedad de escala + flujo nulo cerca del FOE) como causa raíz del fracaso del control reactivo (0/10) en `townsim_ini` (IT.11.4) y evalúa mitigación estéreo (dos cámaras / adaptador de un sensor) frente a LiDAR, con sus propias limitaciones en follaje denso | IT.11.4, IT.12.4 |
| — | [`anexos/A8-NAVEGACION-RL.md`](anexos/A8-NAVEGACION-RL.md) | Trabajo futuro — diseño técnico del cuarto brazo experimental `rl` (PPO visual): jerarquía VLM → RL → PX4, espacio de observación `{rgb, ttc_field, nav}`, espacio de acciones discretas (6 macro-acciones), función de recompensa con currículo, justificación PPO vs SAC/DQN, arquitectura CNN+FC, advertencia sobre generalización (caso Swift/ETH), protocolo de evaluación 4 brazos (60 corridas) | IT.12.4 |
| — | [`anexos/A9-MODELOS-DE-MUNDO-LATENTES-EDGE.md`](anexos/A9-MODELOS-DE-MUNDO-LATENTES-EDGE.md) | Trabajo futuro — análisis de LeWorldModel (JEPA, ~15 M parámetros) como alternativa/complemento del SLM: trade-offs, brechas de aplicabilidad, tres opciones de integración, estimación de viabilidad en Jetson Nano/Orin Nano y protocolo de evaluación | IT.12.4 |
| — | [`anexos/A10-ESPECIFICACION-LAZO-TACTICO.md`](anexos/A10-ESPECIFICACION-LAZO-TACTICO.md) | Material de referencia — especificación del lazo táctico: escaneo pre-vuelo, campos de `DroneState`, señales y umbrales del `StallDetector`, nodos y comportamientos, mapa de macro-acciones, gobernador de velocidad, `DeliberationService`, máquina de estados del barrido, `WaypointTracker`, registro de vuelo y cierre de misión | IT.5 |
| — | [`anexos/A11-CATALOGO-INCIDENTES-INTEGRACION.md`](anexos/A11-CATALOGO-INCIDENTES-INTEGRACION.md) | Material de referencia — catálogo de incidentes de integración: vulnerabilidades de estado y precedencia en LangGraph, degradaciones sensoriales y siete casos de corridas de diagnóstico y piloto (deadlock falso, profundidad en el brazo evaluado, `physics_locked`, señales que se tapan, sub-metas que ocultan al waypoint, respuestas truncadas, barrido constante) | IT.9 |
| — | [`anexos/A12-OPERACION-EXPERIMENTAL.md`](anexos/A12-OPERACION-EXPERIMENTAL.md) | Material de referencia — operación del experimento: nombres heredados, geometría de los escenarios, semillas, procedimiento de los lotes, métricas secundarias, resultados esperados declarados antes de correr, artefactos y trazabilidad, construcción del banco de prueba y plan extendido de pruebas | IT.10 |
| — | [`anexos/A13-ESTACION-TERRENA-DATASET.md`](anexos/A13-ESTACION-TERRENA-DATASET.md) | Material de referencia — estación terrena WebDCS, juicio por imagen del planificador de ruta, construcción del mapa cenital registrado, estructura completa del dataset de corridas (archivos, traza, resumen) y visor de auditoría con las anotaciones del video | IT.4 |

## Convenciones

- Un único `#` (H1) por archivo, con el número y título del capítulo, para que la
  concatenación produzca una jerarquía de encabezados consistente.
- Las tablas de resultados que dependen de la corrida experimental final quedan como
  placeholders con las columnas ya definidas, para que la corrida de tesis llene celdas
  en vez de definir estructura.
- Las imágenes y diagramas ya generados (`.png`, `.jpg`, `.mmd`) quedan en `informe/`
  junto a los capítulos que los referencian.
