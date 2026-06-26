Preparar la estructura de un proyecto de app python modualar que permita la planificación de la misión.
La Arquitectura de Dos Cerebros (100% Local)
Para optimizar recursos, no le pides al SLM de vuelo que diseñe la misión mientras vuela. Se utiliza un enfoque asíncrono, para esto:
1. El Planificador de Misión (Estación de Tierra): Puedes usar el mismo modelo local en LM Studio (ej. Llama-3-8B), pero sin restricciones de tiempo. Como el dron está en el suelo, este modelo puede tomarse 5 o 10 segundos para "pensar" y traducir instrucciones humanas complejas en un plan de vuelo estructurado. Esta es la aplicacion a implementar dentro de /airsim-plan
2. El Navegador Táctico (SLM en LangGraph): Una vez que despega, su único trabajo es ejecutar el plan de la Estación de Tierra y sobrevivir al entorno. El sistema ya está implementado en /airsim-loop y a este sistema hay que pasarle el manifiesto y pedirle que inicie el vuelo

El Pipeline de Preparación Pre-Vuelo
Antes de que las hélices giren, ocurre este flujo de trabajo de preparación:
Paso 1: Interfaz de Lenguaje Natural (Intención del Usuario)
El operador (tú o un cliente agrícola/industrial) le da una instrucción en lenguaje natural al Planificador de Misión en la Estación de Tierra.
"Revisa el perímetro de la zona industrial norte (coordenadas X:50, Y:100). Si ves personas, ignóralas. Si el nivel de batería cae por debajo del 20%, regresa inmediatamente a la base."
Paso 2: Compilación de la Misión (El LLM de Tierra)
El modelo de tierra procesa esa instrucción y genera un Manifiesto de Misión en JSON. Esto convierte la intención humana en variables frías y matemáticas que el sistema de control puede entender.
{
  "mission_id": "PERIMETER_NORTH_01",
  "waypoints": [
    {"x": 0, "y": 50, "z": -10},
    {"x": 50, "y": 100, "z": -10}
  ],
  "rules of engagement": {
    "ignore_objects": ["person", "car"],
    "return_to_launch_battery_threshold": 20.0
  }
}

Paso 3: Inyección del Contexto en LangGraph (El "Pre-Prompt")
Aquí es donde ambos sistemas se conectan. Antes de compilar tu grafo de LangGraph, inyectas el Manifiesto de Misión en el estado inicial (MonocularDroneState) y configuras el System Prompt del SLM táctico para que conozca las reglas del juego.
El nodo del SLM (el cerebro de vuelo) ahora tendrá un prompt base que lucirá así:
"Eres el navegador táctico. Tu objetivo final es llegar al Waypoint [50, 100].
Reglas de la misión: Ignora las 'personas'. Si la batería es <20%, tu única acción permitida es RETURN_TO_LAUNCH.
Estado actual: [Aquí va el output de YOLO y la telemetría]"
Paso 4: Despegue y Traspaso de Autoridad (Hand-off)
1. La Estación de Tierra envía el comando client.takeoffAsync().join() a AirSim.
2. Se inicializa el bucle de LangGraph con el estado pre-cargado.
3. El dron comienza a moverse hacia el primer Waypoint. El SLM de vuelo ahora solo evalúa el entorno inmediato para evadir obstáculos mientras el dron intenta seguir la ruta global trazada por el Planificador.
