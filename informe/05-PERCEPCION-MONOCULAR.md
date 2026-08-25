# 5. Percepción monocular sin redes neuronales

## 5.1 Decisión de diseño: por qué se retiran YOLO, el segmentador IPM y el gate por bordes

El plan de trabajo aprobado (`plan_tesis/plan-tesis.md`) preveía una arquitectura de percepción con
tres redes neuronales: YOLOv8n para detección de obstáculos, MobileNetV3 + U-Net para segmentación de
zonas de aterrizaje, y ORB-SLAM2 para SLAM visual. La arquitectura finalmente implementada prescinde
de redes neuronales de detección. El motivo no fue una preferencia estética por métodos clásicos sino
el diagnóstico de una cadena de fallas concretas, documentada en `legacy/README.md` y en el historial
del proyecto (`CHANGELOG.md`):

- **El detector YOLO fue retirado por costo computacional**, y ese retiro dejó el campo
  `detected_obstacles` de `DroneState` permanentemente vacío (`[]`). El problema no fue el retiro en
  sí, sino que sus consumidores —el enrutador de decisiones, el mecanismo de respaldo determinista, el
  resumen que alimenta el prompt del modelo de lenguaje— siguieron leyendo ese campo como si llevara
  información real. Es la primera de las tres instancias del patrón de falla documentado en el
  capítulo 8.
- **El estimador de TTC original** (`optical_flow_estimator.py`, hoy en `legacy/`) calculaba
  `TTC = 1 / mean(|flujo|)` sin dividir por el intervalo real entre fotogramas: el resultado estaba en
  unidades de fotograma, no de segundos, pero se comparaba contra umbrales expresados en segundos.
  Además, promediar la magnitud del flujo sin separar la componente rotacional confundía magnitud con
  divergencia: cada giro de guiñada del dron hacía caer el TTC de forma espuria y disparaba el freno
  de seguridad sin peligro real — la causa, según el propio historial del proyecto, de un patrón de
  "vuelo cortado y errático" observado en pruebas tempranas. El estimador de foco de expansión (FOE)
  de ese módulo, además, era un valor fijo en el centro geométrico de la imagen, no una estimación.
- **El segmentador por mapeo de perspectiva inversa (IPM)** fue evaluado como reemplazo de la
  segmentación semántica y descartado, no por costo sino por incumplir su propia hipótesis geométrica:
  asume un plano de suelo dominante en el campo de visión, y con una cámara frontal a ~10 m de altura
  en un cañón urbano el suelo ocupa una fracción marginal de la imagen. La implementación evaluada,
  además, aplicaba la misma homografía a ambos fotogramas consecutivos, lo que convertía la diferencia
  entre ellos en, matemáticamente, una diferencia de fotogramas bajo movimiento propio: cualquier
  borde con textura quedaba marcado como obstáculo. Se consideró y descartó implementar un IPM
  correcto (con homografía derivada de actitud y altura reales, compensación de movimiento propio y
  agrupamiento geodésico): es una solución correcta en abstracto para un problema geométrico que este
  caso de uso —cuadricóptero urbano con cámara frontal— no tiene.
- **Un filtro por bordes de Canny** (`canny_xor_gate`), pensado para saltear percepción cuando la
  escena no cambia visualmente entre fotogramas, fue retirado con evidencia medida en vuelo real (446
  ciclos): el ratio de cambio de bordes nunca bajó de 0.071 en crucero activo, muy por encima del
  umbral histórico (0.02–0.03), de modo que el filtro casi nunca se activaba durante el vuelo activo.
  Peor aún, su único patrón de activación frecuente (~1 % de los ciclos) coincidía con momentos de
  hover posteriores a un frenado de seguridad — exactamente el momento en que releer el campo de
  obstáculos importa más, no menos. El filtro se eliminó del grafo en lugar de recalibrarse.

## 5.2 Flujo óptico, derotación y divergencia como señal de ocupación

El reemplazo de estos componentes es un único contrato de percepción, `ObstacleField`
(`src/perception/obstacle_field.py`), producido en cada ciclo por un estimador de flujo óptico y TTC
(`FlowTTCEstimator`, `src/perception/flow_ttc.py`) y consumido exclusivamente a través de su API
pública (`is_blocked`, `blocked_fraction`, `sector_ttc`, `summary_text`, `to_dict`) — ningún nodo del
grafo lee campos crudos de flujo óptico.

El campo se organiza en una grilla de 3×3 celdas (tres sectores horizontales — izquierda, centro,
derecha — por tres bandas verticales — superior, medio, inferior), cada una con cuatro magnitudes:
ocupación (`occupancy`, en [0,1]), tiempo-a-colisión (`ttc_s`, en segundos, `inf` si no hay evidencia
de aproximación), divergencia del campo traslacional (`divergence`, en 1/s) y confianza (`confidence`,
fracción de píxeles válidos en la celda). El cálculo, por ciclo, sigue estos pasos:

1. **Flujo óptico denso** entre el fotograma actual y el anterior (`cv2.DISOpticalFlow`, con
   Farnebäck como alternativa), sobre la imagen reducida a `FLOW_DOWNSCALE_WIDTH` píxeles de ancho.
2. **Derotación.** El flujo inducido por la rotación propia del dron entre fotogramas —estimado a
   partir de los deltas de *pitch*, *yaw* y *roll* de la telemetría de actitud— se resta del flujo
   medido, de modo que lo que queda (`flow_trans`) sea, en la medida de lo posible, únicamente el
   componente traslacional. Esta corrección es la que resuelve el problema de fondo del estimador
   anterior: un giro puro de guiñada, correctamente derotado, no debería producir evidencia de
   aproximación.
3. **Estimación del foco de expansión (FOE)** por mínimos cuadrados ponderados sobre el flujo
   traslacional, con un paso de recorte de valores atípicos (los vectores cuyo ángulo respecto de la
   recta al FOE estimado supera un umbral se excluyen y se resuelve una segunda vez). Sin evidencia
   traslacional suficiente (dron en *hover* o en giro puro derotado), el FOE queda indefinido, la
   confianza es 0 y el TTC de todas las celdas es `inf` — deliberadamente, sin ningún recorte
   cosmético que sustituya la ausencia de evidencia por un valor plausible.
4. **TTC por píxel**, en segundos reales: `TTC = |p − FOE| · dt / |v_traslacional|`, con `dt` tomado
   de las marcas de tiempo de telemetría (nunca del período nominal del lazo). La agregación por
   celda usa el percentil 20 de los valores válidos, de modo que un puñado de píxeles ruidosos no
   domine la estimación.

## 5.3 El canal de ocupación: un hallazgo abierto sobre su escala

La divergencia del campo traslacional (`∇·v`) se calcula, en el código actual
(`src/perception/flow_ttc.py`), con un operador de Sobel de 3×3 sin normalizar la escala del kernel
(`cv2.Sobel(..., ksize=3)`), y esa divergencia se usa directamente para derivar la ocupación de cada
celda (`occupancy = clip(divergencia × 0.5, 0, 1)`). El kernel de Sobel de 3×3 es, por construcción,
equivalente a ocho veces la derivada central real; una divergencia calculada con esa escala sin
corregir sobreestima sistemáticamente la ocupación de una celda frente a lo que la física del campo
de flujo predice.

La consecuencia no es cosmética: `Cell.is_blocked()` combina el canal de ocupación y el canal de TTC
con un operador lógico OR (`ocupación ≥ umbral OR TTC ≤ umbral`). En un OR, un canal saturado **anula**
al otro — si la ocupación satura con facilidad, el TTC, aun siendo el canal validado contra
profundidad (cap. 6), deja de tener ninguna influencia práctica en la decisión, porque la ocupación ya
resolvió `is_blocked()` en `True` antes de que el valor de TTC importe. A la fecha de este escrito, la
corrección de esta escala y la recalibración del umbral `OBSTACLE_OCCUPANCY_BLOCKED` contra el canal
de profundidad —con el mismo protocolo de curva ROC ya aplicado al TTC en el capítulo 6— quedan como
trabajo pendiente; el propio código marca ese umbral como provisorio (`obstacle_field.py`, comentario
junto a `OCCUPANCY_BLOCKED_THRESHOLD`). Se documenta aquí como hallazgo abierto, no como resultado
cerrado, porque de eso depende directamente la sección 5.4 y buena parte del capítulo 8: es la tercera
instancia del patrón de falla que atraviesa este trabajo.

## 5.4 `blocked_fraction()` como reemplazo de `occlusion_ratio`

`ObstacleField.blocked_fraction()` —la fracción de las nueve celdas marcadas como bloqueadas— sustituye
al `occlusion_ratio` que producía el segmentador IPM retirado, y conserva su función original: seguir
siendo la señal que dispara el bypass determinista `girar_90` ante bloqueo severo. Su semántica
depende, igual que `is_blocked()`, de que ambos canales de entrada estén correctamente calibrados; la
sección 5.3 aplica también aquí.
