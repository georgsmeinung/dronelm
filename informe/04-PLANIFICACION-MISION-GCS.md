# 4. Planificación de misiones y estación de control en tierra (WebDCS)

## 4.1 Arquitectura desacoplada: dos cerebros (tierra vs. vuelo)

La arquitectura general del sistema responde a un principio de diseño fundamental: la separación estricta entre la **planificación deliberativa global previa al vuelo** (ejecutada en tierra) y la **navegación táctica reactiva** (ejecutada a bordo durante el vuelo). Esta división, conceptualizada como una arquitectura de *dos cerebros*, resuelve la asimetría intrínseca de recursos computacionales y tolerancias de latencia entre ambas fases operativas:

1. **El planificador de estación terrena (`airsim-plan` / WebDCS):** opera de manera previa al despegue del vehículo. En esta etapa, el sistema puede tolerar presupuestos de tiempo del orden de 5 a 10 segundos para interpretar instrucciones en lenguaje natural, consultar información contextual del entorno, aplicar reglas de seguridad operacional y generar un plan de vuelo global validado.
2. **El lazo táctico a bordo (`airsim-loop`):** opera en tiempo real estricto una vez que el vehículo está en el aire (capítulo 5). Bajo una frecuencia objetivo de 5 a 10 Hz, su función no es diseñar la ruta global sino mantener la estabilidad cinemática, seguir los objetivos asignados y ejecutar maniobras reactivas inmediatas de evasión de obstáculos a partir de visión monocular ligera.

![Planificación de Misión UAV y Arquitectura de Control](2026-0625%20Planificacion%20de%20Mision%20UAV.png)

El desacoplamiento permite que la misión sea validada, persistida y versionada de forma determinista antes de iniciar los motores. Asimismo, garantiza que el lazo táctico a bordo no dependa de una conexión de red permanente con la estación terrena: una vez transmitido el manifiesto de vuelo, el dron opera de forma enteramente autónoma, protegiendo la seguridad del vuelo ante eventuales pérdidas de enlace de radio o telemetría.

## 4.2 Compilación de misiones desde lenguaje natural

El módulo de planificación en tierra integra un modelo de lenguaje (LLM) que actúa como compilador semántico. Su objetivo es transformar directivas operativas de alto nivel expresadas en lenguaje natural por un operador humano (por ejemplo, *"recorrer el perímetro norte a 10 metros de altura evitando zonas de alta densidad vehicular"*) en un artefacto estructurado y ejecutable por el piloto automático.

Para garantizar la fiabilidad del proceso de compilación sin incurrir en alucinaciones o errores de sintaxis:
- Se utiliza un cliente local compatible con la API de OpenAI (conectado a instancias locales de LM Studio u Ollama), ejecutando modelos orientados a seguimiento de instrucciones (tales como Llama-3-8B, Qwen-7B o Phi-4).
- Se define un *System Prompt* formalizado (`compiler_system.md`) que instruye al modelo sobre las dimensiones del entorno de simulación, las restricciones del espacio aéreo urbano y el formato de salida requerido.
- Se implementa una capa de coerción y extracción de JSON (`json_extract.py`) respaldada por esquemas de validación estricta en **Pydantic** (`manifest.py`). Si la salida generada por el LLM no cumple con los tipos de datos o las restricciones cinemáticas impuestas, el compilador rechaza el plan y solicita una reevaluación antes de comprometer el vuelo.

Cabe una aclaración sobre el alcance actual de la interfaz: si bien el compilador semántico descripto en esta sección está completamente implementado y expuesto como endpoint del backend, la interfaz de WebDCS en su estado presente no ofrece ningún control para invocarlo. La superficie de interacción del operador quedó acotada, por decisión de alcance del proyecto, a la edición manual de waypoints sobre la carta de navegación (§4.4.1) — priorizando el desarrollo del control de vuelo por sobre la interfaz de planificación asistida. La compilación desde lenguaje natural queda documentada aquí como una capacidad ya construida y validada, disponible para reincorporarse a la interfaz sin cambios en el backend.

## 4.3 El contrato del Manifiesto de Misión (`MissionManifest`)

El producto final del planificador terrestre es un archivo JSON denominado **`MissionManifest`**. Este documento actúa como un contrato formal e inmutable entre la estación terrena y el lazo táctico de vuelo.

```json
{
  "mission_id": "MANHATTAN_URBAN_01",
  "summary": "Patrón de patrullaje urbano sobre cuadrícula con 7 waypoints y retorno seguro.",
  "waypoints": [
    {"x": 0.0,   "y": 50.0,  "z": -10.0, "label": "wp_start"},
    {"x": 60.0,  "y": 50.0,  "z": -10.0, "label": "wp_turn_1"},
    {"x": 60.0,  "y": 120.0, "z": -10.0, "label": "wp_turn_2"},
    {"x": -40.0, "y": 120.0, "z": -10.0, "label": "wp_target"}
  ],
  "rules_of_engagement": {
    "ignore_objects": ["person", "car"],
    "return_to_launch_battery_threshold": 20.0,
    "max_speed_mps": 5.0,
    "safe_altitude_range_m": [5.0, 30.0]
  }
}
```

### Componentes clave del contrato:
- **`mission_id` y metadatos:** identificador único y descripción textual de la intención operativa.
- **`waypoints`:** lista ordenada de puntos de paso tridimensionales expresados en el marco de coordenadas estándar aeronáutico **NED** (*North-East-Down*, donde $z < 0$ representa altitud sobre el punto de despegue).
- **`rules_of_engagement`:** parámetros operacionales y límites cinemáticos globales, tales como velocidad máxima de crucero (`max_speed_mps`), rangos de altitud permitidos y umbrales de seguridad para retorno automático al punto de lanzamiento (*Return-to-Launch*).

En el marco de la metodología experimental de esta tesis (capítulo 10), el uso de manifiestos estructurados garantiza la **reproducibilidad experimental**: los escenarios de benchmark (`manhattan_a` y `manhattan_b`) se definen a través de manifiestos fijos, asegurando que las comparaciones de rendimiento entre brazos de control (SLM, FSM y reactivo) se inicien exactamente con las mismas metas cinemáticas y espaciales.

## 4.4 Estación Terrena WebDCS: planificación y auditoría post-vuelo

Para facilitar la interacción operativa y el análisis experimental posterior, se desarrolló **WebDCS** (*Web-based Drone Control Station*), una estación de control en tierra construida sobre **FastAPI** y tecnologías web estándar (HTML5, Vanilla CSS y JavaScript).

![Interfaz de la Estación Terrena WebDCS](2026-0805%20New%20WebDCS.png)

### Funcionalidades de WebDCS:

1. **Gestión interactiva de cartas de territorio y waypoints:**
   La interfaz incorpora un visor basado en Canvas 2D que mapea la geometría del entorno urbano (`CitySim`) a cartas de navegación satelital. Permite a los operadores cargar manifiestos existentes, visualizar las trayectorias proyectadas y editar waypoints interactivamente sobre la carta (agregar, reordenar, eliminar y ajustar la altitud de cada punto).

2. **Auditoría de vuelo post-misión, sincronizada por video:**
   Cada corrida del lazo táctico registra su propia carpeta autocontenida (identificador de misión y marca de tiempo ISO de inicio) con la traza completa en formato CSV/JSONL, los fotogramas enviados al modelo de lenguaje en cada consulta deliberativa y un video anotado del vuelo completo (un fotograma por ciclo, con overlay de la acción tomada, el nodo del grafo de decisión activo y el estado de los sectores de percepción). Un visor HTML autocontenido, generado automáticamente al cierre de cada corrida, sincroniza en ambos sentidos la reproducción del video con la fila correspondiente de la traza: reproducir el video mueve un cursor sobre la tabla de ciclos, y seleccionar una fila salta el video al instante correspondiente — permitiendo reconstruir exactamente qué fotograma vio el modelo y qué decisión tomó en cualquier punto del vuelo, sin depender de que el operador haya observado la sesión en vivo.

   (Una etapa temprana del desarrollo exploró un mecanismo alternativo de transmisión en vivo de video y telemetría hacia la interfaz web, basado en WebSockets y *Server-Sent Events*. El canal quedó sin ningún consumidor tras un rediseño posterior del frontend y fue retirado por completo — tanto el backend como la interfaz — en favor del mecanismo de auditoría post-vuelo aquí descripto, que resultó suficiente para las necesidades de análisis experimental de este trabajo y más simple de mantener.)

3. **Registro íntegro de cada consulta al modelo de lenguaje:**
   Independientemente del mecanismo de auditoría visual del punto anterior, cada entrada de la traza CSV/JSONL conserva el prompt exacto enviado al modelo, la respuesta cruda emitida, el tiempo de inferencia en milisegundos, la macro-acción resultante y su justificación semántica, además de indicadores de activación de los mecanismos de respaldo deterministas (timeout del watchdog, salida no parseable). Esta traza es la fuente primaria de evidencia para el análisis de modos de falla del capítulo 9 y la metodología experimental del capítulo 10.

4. **Secuencia de fin de misión y aterrizaje autónomo:**
   Al alcanzar el último waypoint del manifiesto o al solicitarse la detención de emergencia desde la interfaz web, el sistema coordina una secuencia controlada de finalización: ejecución de descenso autónomo (`landAsync`), corte de motores, liberación segura de los recursos de API del simulador y retorno ordenado a la pantalla de espera de la estación terrena.
