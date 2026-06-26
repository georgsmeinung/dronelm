Implementar una aplicacion Langgraph que:

Paso 1: Captura Sensorial: El inicio del ciclo donde la API de AirSim proporciona imágenes RGB y telemetría crítica.

Paso 2: Traducción Píxeles-a-Palabras: El primer filtro de IA local. YOLOv8 o un modelo similar toma la imagen y genera coordenadas matemáticas. Nuestro código traduce instantáneamente estas coordenadas en conceptos textuales estructurados: el tipo de objeto, su ubicación en el encuadre (Izquierda, Centro, Derecha) y una estimación de proximidad.

Paso 3: El "Gatekeeper" de LangGraph: El nodo condicional decisivo. Aquí se aplica la lógica para ahorrar cómputo: si no hay un obstáculo inminente detectado al frente en el sector central, el flujo se desvía directamente al control reactivo. Si el camino está bloqueado, se dispara el nodo del cerebro.

Paso 4A: Reflejo Rápido (Control Reactivo): Una ruta de cómputo casi nulo. Al no haber peligro inmediato, el planificador reactivo decide mantener el rumbo por defecto, ahorrando valiosos ciclos de CPU del LLM.

Paso 4B: Cerebro Deliberativo (SLM Local): La ruta deliberativa. El SLM local (Llama-3 en Ollama) recibe el resumen textual detallado de la escena. Analiza, razona y genera un plan de evasión específico, como "esquivar por la derecha para evitar el árbol detectado al frente".

Paso 5: Ejecución Motriz: El nodo final del ciclo. Traduce la decisión de macro-acción (ya sea "mantener rumbo" o "esquivar por la derecha") en comandos directos de velocidad para la API de AirSim, moviendo físicamente el dron.

Paso 6: Bucle Continuo: El ciclo se cierra y comienza inmediatamente de nuevo, permitiendo una navegación autónoma y sensible al entorno en tiempo real. 

Esta estructura de proyecto en Python está lista para desarrollar e incluye toda la arquitectura modular para implementar un bucle híbrido de decisión, con plantillas de código base que configuran el estado del grafo (DroneState), el enrutamiento condicional del Gatekeeper y el bucle principal (main.py).

Implementar el proyecto de modo que:

main.py: El script principal que arranca el sistema y ejecuta de manera infinita (Paso 6) el flujo de control, inyectando la telemetría y actuando tras la decisión.

src/agents/graph.py: Contiene la definición del grafo de LangGraph. Incluye una estructura base DroneState y la función condicional gatekeeper_router (Paso 3) que analiza los sectores (Centro, Izquierda, Derecha) y la proximidad para desviar el flujo al nodo reactivo o deliberativo.

Módulos de Percepción (src/perception/): Archivos vacíos preparados para albergar la lógica de YOLOv8 (detector.py) y la conversión de cajas de delimitación matemáticas a conceptos de texto estructurado (translator.py).

Módulo de Hardware (src/hardware/airsim_client.py): Clase base para encapsular las llamadas de la API nativa de AirSim tanto para adquirir imágenes RGB/telemetría (Paso 1) como para enviar los vectores de velocidad calculados (Paso 5).

Archivos de entorno (requirements.txt y .env): Con las dependencias esenciales preparadas (langgraph, airsim, ultralytics, openai para la compatibilidad con el servidor local de LM Studio).
