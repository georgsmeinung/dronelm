# 9. Metodología experimental

## 9.1 Diseño experimental

La evaluación compara tres brazos de decisión sobre el mismo `ObstacleField` (cap. 5), el mismo
espacio de macro-acciones y el mismo traductor a comandos cinemáticos (`action_to_command`, cap. 7):

- **`slm`** — el modelo de lenguaje pequeño como capa de decisión táctica (cap. 7), con freno previo,
  deliberación asíncrona con watchdog, y respaldo determinista ante timeout o respuesta no adherente.
- **`fsm`** — una máquina de estados finitos explícita (`CRUISE → AVOID_LEFT | AVOID_RIGHT | CLIMB |
  BRAKE → CRUISE`), con transiciones por umbrales sobre el mismo `ObstacleField`. Es la línea de base
  contra la que el objetivo específico de la tesis exige comparar al SLM: predictibilidad y bajo costo
  computacional, sin capacidad de interpretar contexto más allá de sus umbrales.
- **`reactive`** — navegación guiada al waypoint sin evasión de obstáculos: una cota inferior explícita,
  útil para separar cuánto del desempeño de los otros dos brazos proviene de la evasión en sí y cuánto
  del guiado de base.

El diseño experimental prevé dos escenarios existentes (`manhattan_a`, `manhattan_b`, trazado urbano
tipo cuadrícula) más un tercer escenario, aún por definir, con un bloqueo frontal masivo genuino —
necesario para ejercitar la rama de decisión que justifica, en primer lugar, la existencia de una capa
deliberativa: sin un escenario que fuerce esa rama, la comparación mide sobre todo crucero sin
incidentes. Se prevén al menos cinco semillas por combinación de brazo y escenario, dado que la
comparación estadística (§9.3) requiere varianza entre semillas para ser significativa. El presupuesto
de tiempo/ciclos por misión debe estimarse a partir de la longitud de la ruta y la velocidad de
crucero medida, con margen suficiente: un primer batch de validación de punta a punta usó un
presupuesto de 60 segundos que resultó insuficiente incluso sin incidentes de bloqueo, y un segundo
batch con 300 segundos, aunque expuso comportamiento real del sistema, tampoco llegó a completar
ninguna misión por la cadena de fallas descrita en el capítulo 8 (ya corregida en la arquitectura
actual). El criterio de arranque para el batch completo es que una corrida piloto de una sola
combinación complete la misión (`success = True`); si ninguna combinación puede tener éxito, no tiene
sentido ejecutar el resto de las combinaciones.

## 9.2 Métricas reportadas

- Tasa de éxito de misión.
- Colisiones por misión y por kilómetro recorrido.
- Distancia mínima a obstáculo, percentil 5 (`min_obstacle_dist_m`), obtenida del canal de profundidad
  a cadencia reducida — usada exclusivamente para métricas, nunca realimentada al control, para no
  contaminar el experimento que se está midiendo.
- SPL (*Success weighted by Path Length*): éxito ponderado por la razón entre la longitud de la
  trayectoria recorrida y la óptima.
- Tiempo a destino.
- Latencia total por ciclo, p50/p95, desagregada por brazo **y por ruta de decisión** (`keep_going`,
  `evasive`, `deliberative`, `girar_90`, `fsm`, `degraded`) — no solo el agregado, porque el costo de
  latencia de cada ruta es cualitativamente distinto.
- `deliberation_rate` (fracción de ciclos que efectivamente invocan al modelo de lenguaje) y el
  histograma completo de rutas por corrida: es la evidencia directa de si la deliberación por
  excepción (cap. 4) se sostiene en la práctica o si, por el contrario, el modelo termina siendo
  consultado en la mayoría de los ciclos.
- Invocaciones del SLM por misión, tasa de *fallback* al respaldo determinista, tasa de *timeout* del
  watchdog.
- `adherence_rate`, con y sin decodificación restringida (§7.2).

## 9.3 Protocolo estadístico

La comparación entre brazos se realiza con la prueba U de Mann-Whitney sobre las semillas de cada
combinación (no sobre promedios agregados sin varianza), junto con el tamaño de efecto
correspondiente. El análisis se diseña para poder responder la pregunta de investigación —¿aporta el
SLM sobre la FSM?— desagregada **por tipo de escenario**, no solo en agregado: un resultado del tipo
"no aporta en el bloqueo frontal masivo, donde la FSM decide igual y en una fracción del tiempo; sí
aporta en la elección de una calle transversal" es un hallazgo honesto y publicable, y sostiene mejor
una defensa que un resultado agregado ambiguo.

## 9.4 Reproducibilidad

El registro por ciclo (`src/logging/flight_logger.py`) produce un JSONL estructurado por corrida más
un `summary.json` con los agregados de la misión; el análisis batch (`experiments/runner.py`,
`experiments/analyze.py`) ejecuta N misiones × M escenarios × K semillas de forma headless y
reproducible, con escenarios y semillas fijos. El conjunto de datos de validación de TTC (cap. 6) y
los JSONL/`summary.json` de la corrida final quedan pendientes de versionar en un repositorio con
identificador estable (por ejemplo Zenodo, por tamaño y citabilidad), de modo que cada tabla de
resultados de la tesis pueda referenciar una fuente de datos citable y reproducible.
