# 4. Planificación de misiones y estación de control en tierra (WebDCS)

## 4.1 Arquitectura desacoplada: dos cerebros (tierra vs. vuelo)

La arquitectura general del sistema responde a un principio de diseño fundamental: la separación estricta entre la **planificación deliberativa global previa al vuelo** (ejecutada en tierra) y la **navegación táctica reactiva** (ejecutada a bordo durante el vuelo). Esta división, conceptualizada como una arquitectura de *dos cerebros*, resuelve la asimetría intrínseca de recursos computacionales y tolerancias de latencia entre ambas fases operativas:

1. **El planificador de estación terrena (`airsim-plan` / WebDCS):** opera de manera previa al despegue del vehículo. En esta etapa, el sistema puede tolerar presupuestos de tiempo del orden de 5 a 10 segundos para interpretar instrucciones en lenguaje natural, consultar información contextual del entorno, aplicar reglas de seguridad operacional y generar un plan de vuelo global validado.
2. **El lazo táctico a bordo (`airsim-loop`):** opera en tiempo real estricto una vez que el vehículo está en el aire (capítulo 5). Bajo una frecuencia objetivo de 5 a 10 Hz, su función no es diseñar la ruta global sino mantener la estabilidad cinemática, seguir los objetivos asignados y ejecutar maniobras reactivas inmediatas de evasión de obstáculos a partir de visión monocular ligera.

![Planificación de Misión UAV y Arquitectura de Control](informe-03-planificacion-del-vuelo.jpg)

El desacoplamiento permite que la misión sea validada, persistida y versionada de forma determinista antes de iniciar los motores. Asimismo, garantiza que el lazo táctico a bordo no dependa de una conexión de red permanente con la estación terrena: una vez transmitido el manifiesto de vuelo, el dron opera de forma enteramente autónoma, protegiendo la seguridad del vuelo ante eventuales pérdidas de enlace de radio o telemetría.

## 4.2 Compilación de misiones desde lenguaje natural
El módulo de planificación en tierra integra un modelo de lenguaje (LLM) que actúa como compilador semántico. Su objetivo es transformar directivas operativas de alto nivel expresadas en lenguaje natural por un operador humano (por ejemplo, *"recorrer el perímetro norte a 10 metros de altura evitando zonas de alta densidad vehicular"*) en un artefacto estructurado y ejecutable por el piloto automático.

Para garantizar la fiabilidad del proceso de compilación sin incurrir en alucinaciones o errores de sintaxis:

- Se utiliza un cliente local compatible con la API de OpenAI (conectado a instancias locales de LM Studio u Ollama), ejecutando modelos orientados a seguimiento de instrucciones (tales como Llama-3-8B, Qwen-7B o Phi-4).
- Se define un *System Prompt* formalizado (`compiler_system.md`) que instruye al modelo sobre las dimensiones del entorno de simulación, las restricciones del espacio aéreo urbano y el formato de salida requerido.
- Se implementa una capa de coerción y extracción de JSON (`json_extract.py`) respaldada por esquemas de validación estricta en **Pydantic** (`manifest.py`). Si la salida generada por el LLM no cumple con los tipos de datos o las restricciones cinemáticas impuestas, el compilador rechaza el plan y solicita una reevaluación antes de comprometer el vuelo.

Cabe una aclaración sobre el alcance actual de la interfaz: si bien el compilador semántico descripto en esta sección está completamente implementado y expuesto como endpoint del backend, la interfaz de WebDCS en su estado presente no ofrece ningún control para invocarlo. La superficie de interacción del operador quedó acotada, por decisión de alcance del proyecto, a la edición manual de waypoints sobre la carta de navegación (§4.4.1) — priorizando el desarrollo del control de vuelo por sobre la interfaz de planificación asistida. La compilación desde lenguaje natural queda documentada aquí como una capacidad ya construida y validada, disponible para reincorporarse a la interfaz sin cambios en el backend.

## 4.3 El contrato del Manifiesto de Misión (`MissionManifest`)

El producto final del planificador terrestre es un archivo JSON denominado **`MissionManifest`**. Este documento actúa como un contrato formal e inmutable entre la estación terrena y el lazo táctico de vuelo. Su schema canónico está definido en Pydantic (`manifest.py`) y validado contra un JSON Schema (`manifest_schema.json`).

```json
{
  "mission_id": "CITYSIM_CLEAR_01",
  "summary": "Patrón de patrullaje urbano sobre cuadrícula con 7 waypoints.",
  "waypoints": [
    {"x": 26.1,  "y": -78.2,  "z": -10.0, "label": "WP_1"},
    {"x": 68.9,  "y": -78.6,  "z": -10.0, "label": "WP_2"},
    {"x": 67.7,  "y": -145.0, "z": -10.0, "label": "WP_3"},
    {"x": 26.5,  "y": -145.0, "z": -10.0, "label": "WP_4"},
    {"x": -16.3, "y": -145.0, "z": -10.0, "label": "WP_5"},
    {"x": -17.9, "y": -78.6,  "z": -10.0, "label": "WP_6"},
    {"x": 12.5,  "y": -78.6,  "z": -10.0, "label": "WP_7"}
  ],
  "map": "citysim_calib.png"
}
```

### Componentes del contrato:
- **`mission_id`:** identificador único en formato `^[A-Z0-9_]{3,32}$`, validado por el schema. Identifica el escenario experimental y aparece en los nombres de carpeta de telemetría.
- **`summary`:** descripción textual de la intención operativa (campo opcional, no consumido por el lazo táctico).
- **`waypoints`:** lista ordenada de puntos de paso tridimensionales en el marco **NED** (*North-East-Down*): $z < 0$ representa altitud sobre el punto de despegue. Cada waypoint lleva una etiqueta opcional (`label`) para identificación en la traza.
- **`map`:** nombre del archivo de imagen de carta de territorio empleado por WebDCS para la visualización de la trayectoria (por defecto `map.png`).

**Separación entre manifiesto y prompt táctico.** El manifiesto entrega únicamente metas geométricas; el prompt del nodo deliberativo no forma parte de él porque no puede ser un texto estático: se construye dinámicamente en cada ciclo de vuelo a partir del estado percibido en ese instante. Su estructura es la siguiente:

**System prompt (estático, fijo en `deliberative.py`):** define el rol del modelo, las reglas de navegación urbana y el conjunto cerrado de macro-acciones posibles. Existen dos variantes — `SYSTEM_PROMPT_TEXT` (solo texto, para SLMs sin capacidad visual) y `SYSTEM_PROMPT_VISION` (texto + imágenes, para VLMs multimodales) — seleccionadas en tiempo de ejecución por la variable de entorno `VLM_VISION_ENABLED`.

**User prompt (dinámico, construido por `_build_user_prompt()` en cada ciclo):** combina cinco componentes:

1. **Resumen del ObstacleField:** estado de los tres sectores de percepción (centro, izquierda, derecha), con TTC estimado y nivel de ocupación por sector.
2. **Objetivo y altitud:** waypoint activo (etiqueta, distancia horizontal, error de rumbo en grados y dirección relativa), altitud actual y cota segura de operación.
3. **Estado cinemático:** velocidad horizontal y actitud (pitch, roll) en el ciclo actual. Si el dron está prácticamente detenido (`< 0.3 m/s`), se indica explícitamente — porque un frame estático sin traslación no aporta evidencia de flujo óptico, y sin ese contexto el modelo tiende a sobre-interpretar la imagen.
4. **Motivo de consulta:** distingue si se consulta al VLM porque el sector central registra un obstáculo real (con TTC medido) o porque la percepción no tiene evidencia suficiente en este ciclo (confianza baja por falta de traslación o rotación reciente) — dos causas con implicaciones muy distintas para la decisión.
5. **Historial reciente:** las últimas tres deliberaciones con su macro-acción y sus resultados medidos (variación de distancia al waypoint, variación del TTC mínimo), para que el modelo pueda evaluar si una estrategia previa funcionó antes de repetirla.

La respuesta del modelo se fuerza mediante decodificación restringida (`json_schema`, si el servidor lo soporta) al formato `{"macro_action": "<ACCION>", "rationale": "<texto>"}`, con temperatura 0.2 y límite de 200 tokens. Si el servidor no soporta `json_schema`, un parser tolerante (`_parse_decision()`) extrae la decisión del texto libre como red de seguridad. Ante timeout del watchdog o respuesta no parseable, se activa una heurística determinista sobre el ObstacleField (`_fallback_decision()`).

Este nivel de dinamismo hace inviable delegar el prompt al manifiesto: el contenido útil depende de percepciones que solo existen en vuelo.

En el marco de la metodología experimental de esta tesis (capítulo 10), el uso de manifiestos estructurados garantiza la **reproducibilidad experimental**: los escenarios de benchmark por Tiers (`minisim_clear`, `townsim_ini`, `citysim_clear`) se definen a través de manifiestos fijos e inmutables, asegurando que las comparaciones de rendimiento entre brazos de control (SLM, FSM y reactivo) se inicien exactamente con las mismas metas cinemáticas y espaciales.

## 4.4 Estación Terrena WebDCS: planificación y auditoría post-vuelo

**WebDCS** (*Web-based Drone Control Station*) es la interfaz de control en tierra, construida sobre **FastAPI** con frontend en HTML5, CSS y JavaScript. Expone su API REST en `http://localhost:8000` y sirve el panel de operación como aplicación web estática.

![Interfaz de la Estación Terrena WebDCS](2026-0903%20Nueva%20UX%20WebDCS.png)

### Funcionalidades de WebDCS:

1. **Gestión interactiva de cartas y waypoints:**
   El panel incorpora un visor Canvas 2D que superpone la trayectoria del manifiesto sobre la carta del entorno urbano (`CitySim`). El operador puede cargar manifiestos existentes desde `airsim-plan/missions/flightplans/`, visualizar la ruta proyectada y editar waypoints interactivamente sobre la carta — agregar, reordenar, eliminar y ajustar altitud — antes de guardar o lanzar.

2. **Lanzamiento y detención de misión:**
   El botón *Lanzar* invoca `POST /api/launch`, que persiste el manifiesto y arranca `airsim-loop` en un hilo de fondo sin bloquear la interfaz. `POST /api/stop` detiene todos los runners activos. `POST /api/reset` reinicia el simulador AirSim y libera el control de la API.

### Dataset de corridas: estructura de `airsim-runs/`

Cada ejecución de una misión escribe una carpeta autocontenida en `airsim-runs/`. El nombre de la carpeta — y el prefijo común (`<stem>`) de todos los archivos dentro de ella — se construye concatenando el `mission_id` del manifiesto con la marca de tiempo de inicio de la ejecución en UTC, en formato ISO 8601 compacto sin separadores: `<MISSION_ID>-<YYYYMMDDTHHMMSSZ>`. Por ejemplo, lanzar la misión `CITYSIM_CLEAR` el 7 de septiembre de 2026 a las 19:12:26 UTC produce la carpeta y el stem `CITYSIM_CLEAR-20260907T191226Z`. Si la misma misión se lanza dos veces, cada ejecución queda en su propia carpeta gracias al timestamp — nunca se sobreescriben corridas anteriores. La tabla siguiente describe los archivos que produce cada ejecución:

| Archivo | Descripción |
|---|---|
| `<stem>.jsonl` | Traza completa: un objeto JSON por ciclo de control |
| `<stem>.csv` | Mismas columnas en formato plano, para inspección directa en Excel / pandas |
| `<stem>.summary.json` | Métricas agregadas de la corrida (éxito, colisiones, latencias, tasas del VLM) |
| `<stem>.summary_by_wp.csv` | Stats por waypoint: ciclos, deliberaciones y eventos de atasco por tramo |
| `<stem>.viewer.html` | Visor de auditoría HTML autocontenido, sincronizado con el video |
| `<stem>.webm` | Video anotado del vuelo (un fotograma por ciclo, con overlay de acción y estado) |
| `photo-<ISO_UTC>.png` | Fotogramas enviados al VLM, uno por deliberación, nombrados por timestamp UTC |

**Traza por ciclo (`.jsonl` / `.csv`):** cada entrada registra el instante, el ciclo, el brazo de control (`arm`: slm/fsm/reactive), el escenario, la ruta, la macro-acción, el waypoint activo y la distancia al mismo, la posición y velocidad 3D, la actitud, el estado de colisión y la distancia mínima al obstáculo. En los ciclos deliberativos se agregan el prompt enviado (`slm_prompt`), la respuesta cruda del modelo (`slm_raw_response`), la latencia de inferencia, indicadores de fallback y timeout, y las rutas a los fotogramas enviados (`slm_frame_paths`). El estado del `ObstacleField` se registra por sector (ocupación, TTC, confianza, bloqueado).

**Resumen de corrida (`.summary.json`):** es el archivo que consume `analyze.py` para el análisis comparativo entre brazos. Incluye éxito de misión, colisiones, distancia mínima al obstáculo, longitud de trayectoria, tasa de deliberación, y tasas de fallback y timeout del VLM.

**Resumen por waypoint (`.summary_by_wp.csv`):** permite identificar en qué tramo de la misión se concentra la dificultad sin necesidad de analizar el CSV completo — muestra ciclos consumidos, proporción de ciclos deliberativos y eventos de escalación de atasco por waypoint.

**Fotogramas del VLM (`photo-<ISO>.png`):** cada imagen enviada al modelo se guarda con su timestamp real de captura en UTC (precisión de milisegundos), que sirve como clave para cruzar con la columna `slm_frame_paths` de la traza. La carpeta es autocontenida: toda la evidencia de una corrida reside en un único directorio.

### Visor de auditoría (`.viewer.html`)

<img src="informe-03-auditoria-de-vuelo.png"/>

El archivo `<stem>.viewer.html` es un documento HTML autocontenido generado al cierre de cada corrida. Sincroniza en ambos sentidos la reproducción del video con la traza:

- Avanzar el video actualiza automáticamente el panel de detalle del ciclo correspondiente, mostrando el prompt enviado, la respuesta del modelo, la macro-acción resultante y el fotograma capturado en ese instante.
- Seleccionar una fila de la tabla salta el video al instante correspondiente.

Para consultarlo: abrir el archivo directamente en Chrome desde `airsim-runs/<carpeta>/<stem>.viewer.html` — no requiere servidor.

#### Anotaciones del video

El video (`.webm`) registra un fotograma por ciclo del lazo, a la misma cadencia de `LOOP_HZ`. Cada fotograma lleva un overlay de cuatro líneas superpuesto **sobre una copia del fotograma**; el original enviado al VLM y guardado como `.png` de auditoría queda sin modificar para no contaminar la evidencia perceptual.

**Línea 1 — nodo activo y macro-acción** (texto grande, color codificado):

```
[KEEP_GOING] ACT: MANTENER_RUMBO  WP 3/7 (42m)
```

- El tag entre corchetes es el **nodo del grafo de decisión** que resolvió el ciclo (§5.1): `KEEP_GOING` (crucero sin novedad), `EVASIVE` (evasión reactiva), `GIRAR_90` (bypass de bloqueo severo), `FSM` (máquina de estados, brazo FSM), `DELIBERATIVE` (consulta al VLM, §5.2) o `DEGRADED_HOVER` (modo degradado, §5.4).
- `ACT:` es la **macro-acción** traducida a comando cinemático por el nodo `motor`.
- `WP X/N (Ym)` indica el waypoint activo y la distancia horizontal restante según `WaypointTracker` (§5.3).
- **Color:** verde para `MANTENER_RUMBO` (avance sin novedad), naranja para maniobras de evasión o giro, rosa/magenta para decisiones del VLM, `PARADA` o `FRENAR`.

**Línea 2 — TTC frontal y estado de vuelo** (derecha del fotograma):

```
TTC: 3.2s | vuelo
```

- `TTC` es el tiempo estimado a colisión del sector frontal según el `ObstacleField` del ciclo (cap. 6); `inf` significa sector despejado.
- El campo de texto refleja el estado general de la misión (`vuelo`, `completada`, `colisión`).

**Línea 3 — telemetría del ciclo:**

```
t= 18.4s cy=92 | pos=(+26.1,-78.2,-10.0) | v=2.31m/s pitch=-3.2deg roll=+0.8deg
```

- `t` y `cy` permiten cruzar el fotograma con la fila exacta del CSV por número de ciclo (la sincronización por tiempo es aproximada, la de ciclo es exacta; ver `flight_video.py`).
- `pos` es la posición 3D en el marco NED del simulador.
- `v`, `pitch`, `roll` son la velocidad horizontal y la actitud del vehículo en ese instante.

**Línea 4 — estado del ObstacleField por sector** (cap. 6):

```
C occ=0.62 ttc=3.2s! | I occ=0.11 ttc=inf | D occ=0.08 ttc=inf
```

- Los tres sectores son `C` (centro / frente), `I` (izquierda) y `D` (derecha).
- `occ` es la fracción de ocupación estimada por flujo óptico monocular; `ttc` es el tiempo a colisión estimado del sector; `!` marca el sector como bloqueado según el umbral de `is_blocked()`.
- Estos valores son los mismos que alimentan `_build_user_prompt()` (§4.3) y el enrutador de política (§5.1): el overlay permite ver, ciclo a ciclo, qué evidencia perceptual motivó la decisión visible en la línea 1.

La combinación de estas cuatro líneas permite reconstruir, para cualquier instante del vuelo, exactamente qué percibió el sistema, por qué derivó al nodo de grafo que aparece en el tag, y qué orden cinemática emitió — sin necesidad de cruzar a mano el video con el CSV.
