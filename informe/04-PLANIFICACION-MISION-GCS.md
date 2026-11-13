# 4. Planificación de misiones y estación de control en tierra (WebDCS)

## 4.1 Arquitectura desacoplada: dos cerebros (tierra vs. vuelo)

El sistema separa estrictamente la **planificación global previa al vuelo**, en tierra, de la **navegación táctica reactiva**, a bordo. Esta arquitectura de *dos cerebros* resuelve la asimetría de cómputo y de tolerancia a la latencia entre ambas fases: el planificador de la estación terrena (`airsim-plan` / WebDCS) puede tomarse segundos para interpretar instrucciones, consultar el mapa y validar un plan; el lazo táctico a bordo (`airsim-loop`, capítulo 5) opera en tiempo real a 5 Hz y no diseña la ruta, sino que la sigue y evade lo inminente.

![Arquitectura en tres fases: planificación en tierra, lazo táctico a bordo y auditoría](2026-1028%20dos_cerebros.png)

*La arquitectura en tres fases. En tierra se compila la misión y el VLM planifica la ruta sobre el mapa cenital; el manifiesto se transmite una vez. A bordo, el lazo rápido es el único que comanda velocidades y el lazo lento propone sub-metas con la profundidad estimada (capítulo 5). Después, la traza por ciclo alimenta el visor y el análisis por lote. Abajo, qué modelo trabaja en cada fase.*

El desacoplamiento permite validar, persistir y versionar la misión antes de encender los motores, y hace que el lazo a bordo no dependa de una conexión permanente con tierra: transmitido el manifiesto, el dron opera de forma autónoma ante una pérdida de enlace.

## 4.2 Compilación de misiones desde lenguaje natural
El planificador en tierra integra un modelo de lenguaje local como compilador semántico, que transforma una directiva en lenguaje natural (*"recorrer el perímetro norte a 10 metros de altura evitando zonas de alta densidad vehicular"*) en un plan estructurado. Un prompt de sistema describe el entorno, las restricciones del espacio aéreo y el formato de salida, y la salida se valida contra un esquema estricto en Pydantic: un plan que no cumple los tipos o las restricciones cinemáticas se rechaza antes de comprometer el vuelo. El compilador está implementado y expuesto en el backend, pero la interfaz de WebDCS no ofrece todavía un control para invocarlo: por decisión de alcance, el operador edita los waypoints a mano sobre la carta (IT.4.4), y el desarrollo se concentró en el control de vuelo.

## 4.3 El contrato del Manifiesto de Misión (`MissionManifest`)

El producto del planificador es un archivo JSON, el **`MissionManifest`**: un contrato inmutable entre la estación terrena y el lazo táctico, definido en Pydantic y validado contra un JSON Schema.

```json
{
  "mission_id": "CITYMAP_PILOT",
  "summary": "Tier 2: circuito tipo grilla urbana sobre citysim_ortho.png ...",
  "start_pose": { "x": 0.0, "y": 0.0, "z": -10.0, "yaw_deg": 90.0 },
  "waypoints": [
    {"x": 3.0,   "y": -51.0,  "z": -10.0, "label": "WP_0_SUR"},
    {"x": 26.1,  "y": -78.2,  "z": -10.0, "label": "WP_1"},
    {"x": 68.9,  "y": -78.6,  "z": -10.0, "label": "WP_2"},
    {"x": 67.7,  "y": -156.5, "z": -10.0, "label": "WP_3"},
    {"x": 26.5,  "y": -145.0, "z": -10.0, "label": "WP_4"},
    {"x": -16.3, "y": -145.0, "z": -10.0, "label": "WP_5"},
    {"x": -17.9, "y": -78.6,  "z": -10.0, "label": "WP_6"},
    {"x": 12.5,  "y": -78.6,  "z": -10.0, "label": "WP_7"}
  ],
  "map": "citysim_ortho.png"
}
```

*Manifiesto vigente `citysim_pilot.json` (Anexo 12, IT.A12.3.3 explica `WP_0_SUR`; el mapa se describe en IT.4.3.2).*

El contrato tiene pocos campos: un identificador de misión, validado por el esquema, que aparece en los nombres de las carpetas de telemetría; la lista ordenada de **waypoints** tridimensionales en el marco **NED** (*North-East-Down*: $z < 0$ es altitud sobre el punto de despegue), cada uno con una etiqueta para identificarlo en la traza; el nombre de la **imagen cenital** del escenario, que WebDCS usa para mostrar la ruta y el planificador de ruta para decidir por dónde va cada tramo; y, opcionalmente, una pose de partida que solo se usa con la perturbación de la pose inicial (Anexo 12, IT.A12.4.3).

**Separación entre manifiesto y consultas en vuelo.** El manifiesto entrega únicamente metas geométricas. Las consultas del lazo lento —la capa estratégica y el barrido de atascos (cap. 5, IT.5.5, IT.5.6)— no forman parte de él, porque dependen del fotograma, la pose y el waypoint activo de ese instante. En los dos casos el código convierte la respuesta en una sub-meta en coordenadas del mundo, que el `WaypointTracker` inserta delante del waypoint del manifiesto como un waypoint temporal.

### 4.3.1 Plan de ruta con el VLM sobre el mapa cenital

NB4.1–NB4.8 reproducen el plan que voló el lote 6 a partir de las respuestas guardadas del modelo.

El manifiesto une los waypoints en línea recta, y en una ciudad la recta suele cruzar una manzana. En vuelo, la cámara ve solo lo que tiene delante a 10 m de altura y el sistema debe inferir por dónde rodear un edificio cuyo final no ve; desde arriba, la misma pregunta se vuelve de reconocimiento: si una línea dibujada sobre el mapa va por la calle o por encima de los edificios. Es el tipo de juicio que un VLM pequeño resuelve mejor, porque no exige estimar distancias en primera persona. Por eso la estación terrena agrega un paso de planificación con el VLM **antes del despegue** (`src/planning/route_planner.py`): corre una sola vez por misión, la misión espera su resultado y nada de esto ocurre dentro del lazo táctico.

1. **Candidatas geométricas.** Para cada tramo A → B (incluido el tramo desde el *spawn* al primer waypoint) se generan rutas sin mirar el mapa: la recta, las dos rutas en L (primero norte-sur o primero este-oeste) y desvíos paralelos a ±25 y ±50 m a cada lado.
2. **Juicio del VLM por parches.** El modelo no juzga la ruta entera, sino lo que hay debajo de ella: cada 8 m de la candidata se recorta un parche del mapa, con contexto alrededor, y el modelo lo clasifica en una de cinco clases (calle, edificio, árboles, estacionamiento, autopista elevada) con decodificación restringida. La puntuación de la candidata es la probabilidad media de «calle», leída de los *logprobs*. El modelo es el mismo de vuelo.
3. **Elección.** Gana la candidata de mayor puntuación; a menos de 0.05 de la mejor, la más corta. Si no aprobó ninguna, queda la recta. Los vértices intermedios de la elegida se insertan en el manifiesto como waypoints, con la altura del waypoint de destino.

El modelo evalúa; el código solo genera las opciones y toma la mejor según el propio modelo. El plan se calcula una vez por escenario, antes de la primera corrida, y se guarda completo —cada candidata con su respuesta y probabilidad—, de modo que todas las semillas y brazos de un lote vuelan el mismo plan.

**Por qué parches.** Juzgar la ruta entera, dibujada sobre el mapa, no funciona con los modelos pequeños (Anexo 13, IT.A13.1.1). En el banco sobre `citysim_pilot`, ninguno de los dos modelos candidatos (cap. 8, IT.8.1) distinguió una candidata por la calle de una que cruza el techo de un edificio: con la ruta dibujada como línea, uno rechazó las 37 candidatas y el otro aprobó todas; dibujada como pasillo, ambos aprobaron todas; con la pregunta invertida («¿el pasillo cruza algún techo?»), ambos respondieron «sí» a todas. La respuesta depende de la forma de la pregunta y no de la imagen. Los parches le piden al modelo lo que sí hace bien, reconocer qué hay en una imagen, en lugar de juzgar una ruta entera.

**Uso en los experimentos.** El plan está activado en los escenarios con obstrucción de TownSim y CitySim (lotes 3, 4 y 6), sobre sus mapas registrados (IT.4.3.2); los escenarios de control vuelan el manifiesto tal cual, porque son la ruta fija de base de cada tier (cap. 10, IT.10.4.1, punto 5). En el banco de prueba la puntuación separa las rutas libres de las bloqueadas con AUC 0.81, y en el único tramo de `citysim_pilot` con la recta bloqueada el plan elige un desvío libre (cap. 11 IT.11.0). Es la única tarea del sistema en la que el VLM aporta una señal medible.

### 4.3.2 Mapa cenital registrado

El plan de ruta solo tiene sentido si el mapa coincide con el mundo de vuelo. Los mapas de CitySim y TownSim se construyen con el propio simulador: el dron se reubica sobre una grilla de puntos a 1000 m de altura con la cámara apuntando hacia abajo y un campo visual estrecho, de modo que la vista es casi ortográfica, y las tomas se pegan en un lienzo con el origen NED en el centro, el norte arriba y el este a la derecha. La orientación y la escala se verifican en el arranque desplazando el dron y midiendo el corrimiento de la imagen. El resultado, `citysim_ortho.png`, cubre la ciudad completa (1920 × 1640 m) y es el mapa de todas las misiones de CitySim; `townsim_ortho.png` cubre 500 × 500 m alrededor del origen de TownSim. Las demás imágenes de esos niveles no están registradas con el mundo y la configuración las marca así. El procedimiento de captura, incluida la carga por zonas de Unreal Engine, está en el Anexo 13 (IT.A13.1.2).

Los manifiestos fijos garantizan la **reproducibilidad experimental**: los escenarios de cada tier (capítulo 10) se definen con manifiestos inmutables, de modo que los tres brazos de control parten de las mismas metas cinemáticas y espaciales.

## 4.4 Estación terrena WebDCS y auditoría post-vuelo

**WebDCS** (*Web-based Drone Control Station*) es la interfaz de control en tierra, construida sobre FastAPI con un frontend web. Permite cargar manifiestos, ver la ruta sobre la carta del entorno, editar waypoints y lanzar o detener una misión sin bloquear la interfaz.

Su segunda función es la auditoría. Cada ejecución escribe una carpeta autocontenida en `airsim-runs/` que ninguna corrida sobrescribe: la **traza completa ciclo a ciclo** en JSONL y CSV —posición, actitud, ruta y macro-acción del ciclo, `ObstacleField` por sector, latencias y el `DroneState` completo—, el **resumen de la corrida** que consumen los análisis (éxito, colisiones, distancia mínima a obstáculo, recorrido, consultas, deadlocks, plan de ruta y versión del código), un resumen por objetivo, las muestras de la auditoría de distancia mínima, los **fotogramas exactos** de cada consulta del lazo lento y dos videos, el de la cámara frontal con la telemetría superpuesta y el de una cámara de seguimiento externa. Guardar todo el estado, y no una selección de campos, hace que la traza no dependa de haber previsto qué registrar.

<img src="2026-1028 visor_auditoria.png"/>

*Visor de una corrida `slm:depth` de `townsim_ini` (corrida v4, lote 3, semilla 89) en el ciclo 398: un muro cubre el campo, el lazo rápido gira 90° y adelanta la consulta estratégica #40.*

Un **visor HTML** autocontenido, generado al cerrar cada corrida, sincroniza por número de ciclo los dos videos con la traza, y muestra para cada ciclo el campo de obstáculos, la consulta del lazo lento con sus imágenes y el árbol del `DroneState`. El uso típico es partir de un evento del resumen —un deadlock, una colisión, la distancia mínima más baja— y llevar el visor a ese ciclo: el video muestra la escena, el panel muestra qué percibió el sistema y qué decidió, y el árbol del estado muestra por qué. Así se auditaron los modos de falla del capítulo 9. NB2 es su equivalente en Python. La estructura completa del dataset —cada archivo, cada campo de la traza y del resumen— y las anotaciones del video están en el Anexo 13 (IT.A13.3, IT.A13.4).
