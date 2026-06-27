Un **Modelo de Lenguaje Pequeño (SLM)** es una versión ligera de un modelo de lenguaje tradicional, diseñada para operar de manera eficiente en entornos con recursos limitados, como teléfonos inteligentes, sistemas embebidos o computadoras de bajo consumo energético 1-5.  
Aquí hay una descripción más detallada de lo que son los SLMs:

* **Definición Operativa** 6:  
* Un SLM es un modelo de lenguaje (LM) que **puede instalarse en un dispositivo electrónico de consumo común** 4, 6\.  
* Puede realizar inferencias con una **latencia suficientemente baja** para ser práctico al atender las solicitudes de un solo usuario en sistemas de agentes 5-8.  
* Un LLM se define como un LM que no es un SLM 6\.  
* **Tamaño y Escala** 4, 6, 9:  
* Mientras que los Modelos de Lenguaje Grandes (LLMs) tienen cientos de miles de millones, o incluso billones, de parámetros, los SLMs generalmente varían de **1 millón a 10 mil millones de parámetros** 4\. A partir de 2025, se considerarían SLMs la mayoría de los modelos con menos de 10 mil millones de parámetros 6\.  
* Es importante destacar que el término "pequeño" es relativo y se utiliza en comparación con los LLMs más grandes, ya que incluso un modelo de mil millones de parámetros no es "pequeño" por definición absoluta 9, 10\.  
* **Capacidades y Propósito** 4, 7, 11:  
* Los SLMs son suficientemente potentes para manejar las tareas de modelado de lenguaje de las aplicaciones de agentes 11, 12\.  
* Mantienen capacidades básicas de Procesamiento de Lenguaje Natural (NLP) como generación de texto, resumen, traducción y respuesta a preguntas 4\.  
* Se afirman como el futuro de la IA agéntica porque son inherentemente más adecuados operacionalmente y necesariamente más económicos para la mayoría de los usos de modelos de lenguaje en sistemas de agentes 11, 13\.  
* **Ventajas Clave** 5, 7, 14, 15:  
* **Menores requisitos computacionales**: Pueden ejecutarse en laptops de consumo, dispositivos de borde y teléfonos móviles 5, 8\.  
* **Menor consumo de energía**: Modelos eficientes que reducen el uso de energía, haciéndolos más sostenibles 5, 8, 16\.  
* **Inferencia más rápida**: Generan respuestas rápidamente, ideal para aplicaciones en tiempo real 5, 7, 8\.  
* **IA en el dispositivo (On-Device AI)**: No requieren conexión a internet ni servicios en la nube, lo que mejora la privacidad y la seguridad 5, 17\.  
* **Despliegue más económico**: Menores costos de hardware y nube, lo que hace la IA más accesible 5, 14\.  
* **Mayor flexibilidad y personalización**: Son más fáciles de ajustar para tareas específicas de dominio 5, 15\.  
* **Cómo se logran "pequeños"** 1, 9, 18:  
* **Destilación de conocimiento**: Entrenamiento de un modelo "estudiante" más pequeño utilizando el conocimiento transferido de un modelo "maestro" más grande 9, 18, 19\.  
* **Poda (Pruning)**: Eliminación de parámetros redundantes o menos importantes dentro de la arquitectura de la red neuronal 9, 20\.  
* **Cuantización**: Reducción de la precisión de los valores numéricos utilizados en los cálculos (por ejemplo, convertir números de punto flotante a enteros) 9, 21\.  
* **Aplicaciones Comunes** 22:  
* Chatbots y asistentes virtuales.  
* Generación de código.  
* Traducción de idiomas.  
* Resumen y generación de contenido.  
* Aplicaciones en salud.  
* IoT y computación de borde.  
* Herramientas educativas.

En resumen, los SLMs son modelos eficientes y adaptables que buscan democratizar el acceso a la IA, permitiendo su despliegue en una gama más amplia de dispositivos y situaciones donde los LLMs serían inviables debido a sus altos requisitos de recursos 3, 4, 23, 24\.  
