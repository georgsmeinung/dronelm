Dos preguntas bien encadenadas, así que las separo pero dejando el hilo común (el "monocular curse").

## 1) SLAM vs. flujo óptico en pasajes arbolados

Tiene sentido como línea de trabajo futuro, pero conviene matizarlo en el informe para que no suene a "bala de plata" — porque el follaje denso es un caso adversarial también para SLAM, aunque por razones distintas a las del flujo óptico.

**Por qué SLAM ayudaría:**
- El flujo óptico es una medida *instantánea* (par de frames consecutivos): en una escena con textura repetitiva y auto-similar como ramas y hojas, la correspondencia punto-a-punto es ambigua por diseño (aperture problem agravado por textura periódica).
- SLAM, en cambio, integra evidencia geométrica a lo largo de múltiples vistas (bundle adjustment / filtrado), construyendo una estructura 3D persistente. Eso te permite razonar sobre "espacio libre acumulado" en vez de depender de la ambigüedad de un par de frames puntual — es esencialmente pasar de flujo instantáneo a *structure-from-motion* con memoria.
- Con un mapa (aunque sea disperso u ocupacional) podés aplicar detección de gaps/pasajes viables (frontier-based o gap-detection) en vez de solo "esquivar reactivamente".

**Por qué no es gratis:**
- El follaje denso también rompe supuestos centrales de SLAM: (a) las ramas se mueven con el viento, violando la hipótesis de escena estática que necesita casi todo SLAM basado en features; (b) la textura repetitiva de las hojas genera *false loop closures* y matches erróneos entre ramas distintas; (c) las ramas finas son geometría subpíxel/subvóxel — un SLAM disperso (ORB-SLAM3-style) directamente no las va a registrar como landmarks, y uno denso las va a "promediar" y perder precisión justo donde más importa (obstáculos delgados = el caso típico donde hasta LiDAR falla por retornos escasos).
- Costo computacional: SLAM denso monocular (tipo DROID-SLAM) es bastante más pesado que optical flow clásico, lo cual entra en tensión con el objetivo de tu tesis de comparar contra un FSM liviano en costo de cómputo — es un trade-off que vale la pena nombrar explícitamente como limitación de la propuesta de mejora.

Yo lo plantearía en el trabajo futuro como: "SLAM monocular disperso o semi-denso podría mitigar la ambigüedad de correspondencia frame-a-frame integrando evidencia temporal, aunque el follaje dinámico y las estructuras subpíxel siguen siendo un caso límite conocido en la literatura de SLAM visual, no exclusivo del enfoque de flujo óptico actual."

## 2) Estéreo como salida de la "maldición monocular"

Acá sí hay una salida más directa y barata, y creo que tu intuición es correcta.

**La maldición monocular en rigor** tiene dos componentes distintos que vale la pena separar en el texto:
1. **Ambigüedad de escala**: SLAM/SfM monocular reconstruye *hasta un factor de escala* — necesitás IMU, tamaño de objeto conocido, o alguna referencia externa para fijarla.
2. **Dependencia del movimiento**: sin traslación no hay paralaje, y aun con traslación, los puntos cercanos al foco de expansión (FOE) — justo los que están *adelante tuyo*, que es donde más importa detectar obstáculos — tienen flujo casi nulo. Es un problema estructural, no de calidad de sensor.

Un par estéreo resuelve ambos de un saque: la disparidad te da profundidad métrica (con baseline conocida, no hay ambigüedad de escala) a partir de **un solo instante**, sin necesitar que el dron se mueva ni depender de dónde está el FOE. Esto es justamente lo que lo hace más robusto que el flujo óptico en escenas densas: la correspondencia es espacial y simultánea (misma toma, dos cámaras) en vez de temporal, así que no depende de que el mundo permanezca estático entre frames — lo cual es una ventaja extra en escenas con ramas moviéndose.

**Costo/beneficio frente a LiDAR (PlanarDepth):**
- Estéreo es la opción "segundo mejor" razonable que decís: mucho más barato que LiDAR real, y en AirSim se emula sin drama — agregás una segunda cámara RGB en `settings.json` con un offset fijo en X/Y (baseline conocida) y corrés rectificación + matching de disparidad (OpenCV StereoSGBM como baseline clásico, o algo tipo RAFT-Stereo si querés más precisión y no te importa el costo). Importante para la tesis: si usás esto, conviene generar la profundidad *vía matching real* y no tomar el ground-truth de DepthPlanar directamente, para que el error de estéreo (ruido de matching, textura ambigua) quede reflejado — si no, estarías comparando peras con LiDAR ideal.

**Limitaciones que sí hay que declarar:**
- El rango útil depende linealmente de la baseline: en un dron pequeño la baseline física es corta, así que la precisión de profundidad decae con el cuadrado de la distancia — a las velocidades de crucero típicas el "horizonte de detección confiable" puede ser corto.
- La textura repetitiva del follaje también complica el matching estéreo (ambigüedad de correspondencia lateral, no solo temporal), aunque en general es menos frágil que el flujo óptico porque no depende de que haya movimiento suficiente para generar paralaje utilizable.
- Ramas muy finas pueden caer entre los dos puntos de vista y generar oclusiones diferenciales (visible en una cámara, no en la otra), lo cual mete otro tipo de error de matching.

En síntesis: sí, estéreo te saca eficientemente de la maldición monocular (resuelve escala y dependencia de movimiento con cómputo bajo, factible en tiempo real), y es más fácil de justificar como "próximo paso" que LiDAR emulado, porque emula una limitación de hardware real (dos cámaras baratas) en vez de saltar directo a un sensor que la mayoría de los drones urbanos pequeños no llevan. Yo lo pondría en el trabajo futuro como el paso intermedio natural, con SLAM como paso posterior si quisieran robustez ante escena dinámica además de profundidad instantánea.