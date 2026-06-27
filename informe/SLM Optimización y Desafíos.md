Un **Modelo de Lenguaje Pequeño (SLM)** busca ser una versión eficiente y de bajo consumo de un modelo de lenguaje, diseñada para operar en entornos con recursos limitados 1, 2\. La meta es mantener la precisión y/o adaptabilidad de los modelos de lenguaje grandes (LLMs) bajo ciertas restricciones, como hardware de entrenamiento o inferencia, disponibilidad de datos, ancho de banda o tiempo de generación 3\.  
Para reducir la cantidad de parámetros de un SLM sin perder la precisión de un LLM, se emplean varias técnicas clave:

* **Destilación de Conocimiento (Knowledge Distillation)**:  
* Esta técnica implica entrenar un modelo "estudiante" más pequeño para replicar el comportamiento de un modelo "maestro" más grande y complejo 4, 5\.  
* La destilación de conocimiento puede transferir las capacidades matizadas del LLM al SLM, permitiendo que el modelo pequeño imite las salidas del LLM en conjuntos de datos específicos de la tarea 5, 6\.  
* Por ejemplo, Babyllama, un modelo compacto de 58 millones de parámetros, fue desarrollado utilizando un modelo Llama como "maestro", demostrando que la destilación puede superar el rendimiento de los modelos "maestros", especialmente en condiciones de datos limitados 5, 7, 8\.  
* Se puede mejorar la calidad de las respuestas de los modelos "estudiantes" mediante modificaciones en la función de pérdida de destilación 5\. También es posible fusionar múltiples modelos de lenguaje como un solo "maestro" para destilar conocimiento en SLMs 9\.  
* Incluso se pueden destilar cadenas de razonamiento de un LLM más grande a un SLM, lo que ha demostrado mejorar las habilidades de razonamiento aritmético, matemático de varios pasos, simbólico y de sentido común en los modelos pequeños 10\.  
* La utilización de "razones" como supervisión adicional durante la destilación puede hacerla más eficiente en el uso de muestras, e incluso permitir que el modelo destilado supere a los LLMs en benchmarks comunes 10\.  
* **Poda (Pruning)**:  
* La poda es una técnica que reduce el número de parámetros del modelo para mejorar la eficiencia computacional y disminuir el uso de memoria, manteniendo al mismo tiempo los niveles de rendimiento 4, 11\.  
* Existen dos enfoques principales:  
* **Poda no estructurada**: Elimina pesos individuales menos significativos, ofreciendo un control más granular para reducir el tamaño del modelo 11\. Técnicas como SparseGPT pueden manejar modelos a gran escala, y la estrategia de poda n:m (eliminar exactamente n pesos de cada m) busca equilibrar la flexibilidad de la poda con la eficiencia computacional para lograr aceleraciones significativas 11-13.  
* **Poda estructurada**: Comprime los LLMs eliminando grupos de parámetros de manera estructurada, lo que facilita una implementación de hardware más eficiente 14\. Esto incluye abordar la redundancia en la arquitectura Transformer y la escasez de neuronas, o la poda de capas 14, 15\.  
* **Cuantización (Quantization)**:  
* La cuantización reduce la precisión de los valores numéricos utilizados en los cálculos (por ejemplo, convertir números de punto flotante a enteros) para comprimir los LLMs con vastos recuentos de parámetros 4, 16\.  
* Métodos como GPTQ se centran en la cuantización de solo pesos por capa, minimizando el error de reconstrucción 16\. Otros métodos cuantifican tanto los pesos como las activaciones 16\.  
* Técnicas como AWQ y ZeroQuant tienen en cuenta las activaciones para evaluar la importancia de los pesos, optimizando la cuantización de manera más efectiva 16\.  
* La Cuantización del Caché K/V (Key-Value Cache) se aplica específicamente para la inferencia eficiente de secuencias largas 16\.  
* SmoothQuant y SpinQuant abordan los valores atípicos en la distribución de activaciones, migrando la dificultad de cuantificación de las activaciones a los pesos o transformando los valores atípicos en un nuevo espacio 17\.  
* Los métodos de entrenamiento conscientes de la cuantización (QAT), como LLM-QAT y Edge-QAT, utilizan la destilación con modelos float16 para recuperar el error de cuantificación, demostrando un rendimiento sólido 17\.

**Otras técnicas y avances que contribuyen a la eficiencia y el mantenimiento de la precisión:**

* **Arquitecturas Ligeras**: Diseños como MobileBERT (reducción de tamaño 4.3x y aceleración 5.5x sobre BERT), DistilBERT y TinyBERT 18 son optimizaciones de modelos encoder-only. Las arquitecturas decoder-only ligeras como BabyLLaMA, TinyLLaMA, MobilLLaMA y MobileLLM utilizan destilación de conocimiento, optimización de la sobrecarga de memoria, y esquemas de compartición de parámetros y embeddings 7\.  
* **Aproximaciones Eficientes de Autoatención**: Métodos como Reformer, mecanismos de atención lineal, Mamba y RWKV reducen la complejidad computacional de la autoatención de O(N^2) a O(N log N) o O(N) 19\.  
* **Búsqueda de Arquitectura Neural (NAS)**: Métodos automatizados descubren las arquitecturas de modelos más eficientes para tareas y hardware específicos 20\.  
* **Entrenamiento de Precisión Mixta**: Técnicas como Automatic Mixed Precision (AMP), BFLOAT16 y FP8 mejoran la eficiencia del preentrenamiento al usar representaciones de baja precisión para la propagación hacia adelante y hacia atrás 21\.  
* **Ajuste Fino Eficiente en Parámetros (PEFT)**: Técnicas como LoRA y Prompt Tuning actualizan solo un pequeño subconjunto de parámetros o añaden módulos ligeros, reduciendo los costos computacionales y preservando el conocimiento del modelo preentrenado 22-24.  
* **Aumento de Datos**: El aumento de datos, a través de técnicas como AugGPT, Evol-Instruct y Reflection-tuning, incrementa la complejidad, diversidad y calidad de los datos de entrenamiento para SLMs, mejorando la generalización y el rendimiento en tareas específicas, especialmente cuando los datos son limitados 25, 26\.  
* **Potencia de Razonamiento**: Los SLMs ya poseen suficiente poder de razonamiento para una porción sustancial de las invocaciones de agentes. La capacidad, no el recuento de parámetros, es la restricción. Con el entrenamiento, el prompting y las técnicas de aumento agéntico modernos, los SLMs son viables y, comparativamente, más adecuados que los LLMs para sistemas agénticos modulares y escalables 27\. Por ejemplo, el modelo Phi-2 (2.7 mil millones de parámetros) de Microsoft logra puntuaciones de razonamiento de sentido común y generación de código a la par de modelos de 30 mil millones de parámetros, mientras que funciona aproximadamente 15 veces más rápido 28\. DeepSeek-R1-Distill-Qwen-7B supera a modelos propietarios grandes como Claude-3.5-Sonnet-1022 y GPT-4o-0513 29\.

En resumen, los SLMs logran un equilibrio entre tamaño y rendimiento, empleando una combinación de técnicas de compresión y optimización, junto con arquitecturas de diseño inteligente y entrenamiento específico, para ofrecer capacidades similares a las de los LLMs en tareas especializadas 4, 27, 30\.

### SLMs y la Propensión a Alucinaciones

En cuanto a la propensión a alucinaciones, los Modelos de Lenguaje Grandes (LLMs) son conocidos por el problema de la "alucinación", que se define como la generación de contenido sin sentido o falso en relación con ciertas fuentes 31\.  
En el contexto de los SLMs:

* Un estudio utilizando **HallusionBench**, un benchmark para el razonamiento en modelos de visión-lenguaje, encontró que **los tamaños de modelo más grandes reducían las alucinaciones** 32\. Esto sugiere que, en general, los modelos más pequeños podrían ser más propensos a generar contenido alucinatorio.  
* El análisis del benchmark de alucinaciones AMBER también indicó que el tipo de alucinación varía a medida que cambia el recuento de parámetros en Minigpt-4 32\.  
* Las alucinaciones son un riesgo y una limitación que los SLMs comparten con los LLMs 33\.  
* La investigación futura necesita considerar no solo cómo cambia el total de alucinaciones en los SLMs, sino también cómo el tipo y la gravedad pueden verse influenciados por el tamaño del modelo 32\.

Por lo tanto, existe evidencia que sugiere que los SLMs podrían ser más susceptibles a las alucinaciones debido a su menor tamaño, aunque este es un campo de investigación activo para comprender completamente la relación entre el tamaño del modelo y la naturaleza de las alucinaciones 32\.  
