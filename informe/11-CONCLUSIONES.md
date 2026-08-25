# 11. Conclusiones

> **Estado:** pendiente del capítulo de resultados (cap. 10), que a su vez depende de la corrida
> experimental comparativa descrita en el capítulo 9.

## 11.1 Retomar el hilo conductor

Cerrar aquí el argumento declarado en la introducción (§1.4) y desarrollado con evidencia medida en el
capítulo 8: en un sistema de control donde un modelo de lenguaje consume descripciones de escena, el
error más caro está en la interfaz que lo alimenta, no en el razonamiento del modelo, y las tres
instancias documentadas de ese patrón —percepción que afirmaba "despejado" sin señal, historial de
fotogramas inventado, y un canal de ocupación saturado por un error de escala— se detectaron leyendo
contratos de datos, nunca observando el comportamiento del vuelo.

## 11.2 Respuesta a la pregunta de investigación

¿Aporta el SLM sobre la FSM? Síntesis de §10.4, con los matices por tipo de escenario que surjan de la
corrida experimental — evitar una respuesta única y agregada si los datos sostienen una respuesta más
matizada por escenario.

## 11.3 Limitaciones

- Validación exclusivamente en simulación (AirSim); sin validación en hardware físico (Jetson Nano +
  dron real), que el plan de trabajo aprobado (`plan_tesis/plan-tesis.md`, §"Transferencia de los
  resultados obtenidos") sitúa como siguiente etapa fuera del alcance de este trabajo.
- Calibración del canal de ocupación de `ObstacleField` pendiente al cierre de este escrito (cap. 5,
  §5.3), con el canal de TTC como el único de los dos formalmente validado contra profundidad (cap. 6).
- Tamaño de muestra y generalización: a determinar según el número final de semillas y escenarios de
  la corrida de tesis (cap. 9).

## 11.4 Trabajo futuro

- Validación en hardware real: companion computer de bajo costo (Jetson Nano) conectada a un dron
  físico con cámara monocular a bordo, siguiendo el pipeline descrito en el plan de trabajo aprobado.
- Calibración del canal de ocupación contra profundidad, con el mismo protocolo de curva ROC aplicado
  al TTC (cap. 6), y validación de la derotación con giros de guiñada más agresivos (cap. 6, §6.4).
- Navegación en enjambre, sensores adicionales, y las demás líneas de extensión discutidas en el plan
  de trabajo aprobado (`plan_tesis/plan-tesis.md`, §"Transferencia de los resultados obtenidos").
