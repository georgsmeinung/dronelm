
# 2026-0804 
* Haciendo pruebas de rendimiento de inferencia de https://ollama.com/LiquidAI/lfm2.5-1.2b-instruct de 1.2b parametros
<img src="https://cdn-uploads.huggingface.co/production/uploads/61b8e2ba285851687028d395/dxnYF2fuLpulismtFSGFi.png"/>
* Haciendo pruebas de rendimiento de inferencia de https://ollama.com/library/qwen3.5 de 0.8b parametros
<img src="https://ollama.com/assets/library/qwen3.5/1c5d9a27-97b2-4d6d-a1b1-d326259acae5"/>
* Evaluando con [llmfit](https://www.llmfit.org/) 

# 2026-0723

* Se agregan las cartas de territorio a los manifiestos para planificar rutas sobre ellas
* Modificado WebDCS para poder mostrar el mapa en el cual se está planificando la misión

# 2026-0716

* Revisión completa del sistema de planificación de misiones.
* Creada nueva aplicación para la planificación de misiones webdcs (web based mission planner).
  - Se agregó la capacidad de cargar y guardar manifiestos.
  - Se agregó la capacidad de eliminar manifiestos.
  - Se agregó la capacidad de editar manifiestos.
  - Se agregó la capacidad de validar manifiestos.
  - Se agregó la capacidad de planificar rutas.
  - Se agregó la capacidad de mostrar rutas.
  - Se agregó la capacidad de mostrar rutas en el mapa.

<img src="informe/2026-0723 New DCS.png"/>

# 2026-0714

## Porqué La segmentación semantica de imágenes es más rápida que la detección de objetos

### Segmentación Semántica vs. Segmentación de Instancias
Cuando se compara la segmentación semántica con YOLO de detección o YOLO de segmentación (YOLOv8-seg), estamos h ablando de Segmentación de Instancias. Este tipo de segmentación tiene que identificar objetos individuales (sabe que hay "Árbol 1", "Árbol 2" y "Árbol 3") y dibujar una máscara para cada uno. Para lograr esto, el modelo primero tiene que detectar el objeto con una caja y luego generar la máscara. Por eso es más pesado y lento que la detección simple.
Sin embargo, lo que tú mencionas es la Segmentación Semántica (modelos como BiSeNet, Fast-SCNN o DDRNet).
En la segmentación semántica:
* No hay cajas de texto ni identidades: Al modelo no le importa si hay uno o diez árboles; solo clasifica los píxeles. Todo lo que parezca árbol se pinta del mismo color en un mapa plano.
* Sin post-procesamiento pesado: No necesita algoritmos como NMS (Non-Maximum Suppression) para eliminar cajas duplicadas.
* Arquitecturas ultra-optimizadas: Al saltarse el paso de "detectar objetos individuales", existen redes de segmentación semántica diseñadas específicamente para hardware embebido que son increíblemente pequeñas (de 1 a 3 MB) y corren a más de 100 FPS.
Si se usa segmentación semántica pura (yolo26n-sem en vez de yolo26-seg), efectivamente se pueden conseguir modelos mucho más rápidos, ligeros y eficientes que un detector de objetos. Por eso se eligió este modelo para "Visual Looming (aproximación visual) o Detección de Obstáculos Basada en la Ocupación de la Imagen"

### El problemad de la detección de objetos con YOLO: Objetos parciales y cortados
Los detectores de cajas de objetos sufren muchísimo con objetos parciales, ocluidos o cortados por el borde de la pantalla.
¿Por qué pasa esto en la detección de objetos?
Para que un detector como YOLO dibuje una caja delimitadora, la red neuronal necesita predecir con alta confianza el centro del objeto, su ancho y su alto (x, y, w, h).
* Si un dron se acerca a un árbol y solo ve una rama aislada que entra por el lateral de la cámara, el modelo no tiene suficientes características visuales para identificar el "concepto completo de árbol".
* Como no puede estimar dónde termina el árbol (porque está fuera de la pantalla), la confianza del modelo cae por debajo de tu umbral (ej. < 0.25) y YOLO simplemente decide no mostrar nada. Para un dron, esto es fatal: una rama invisible en la pantalla se convierte en un choque inminente.
¿Por qué la segmentación es superior aquí?
La segmentación (tanto semántica como de instancias) clasifica la imagen píxel a píxel basándose en texturas, colores y patrones locales.
* A la segmentación no le importa si el árbol está completo o si solo se ve el 5% de una rama en la esquina superior derecha.
* Si esos píxeles tienen textura de hojas o corteza, el modelo los clasificará como "obstáculo" y los pintará.
* El algoritmo de Visual Looming (ocupación de imagen) sumará de inmediato esos píxeles en el área de peligro y detendrá el dron, incluso si el objeto está incompleto o pegado al borde.

### Comparativa para Navegación de Drones

<img src="informe/2026-0714 Segmentantion vs Detection.png"/>

| Característica | Detección de Objetos (YOLO) | Seg. de Instancias (YOLO-seg) | Seg. Semántica Real-Time (BiSeNet/DDRNet) |
| :--- | :--- | :--- | :--- |
| **Velocidad** | Alta | Media | Extremadamente Alta |
| **Consumo de recursos** | Bajo | Alto | Muy Bajo |
| **¿Detecta objetos parciales?** | No (Suele ignorar objetos cortados) | Sí | Excelente (Pinta cualquier píxel reconocido) |
| **Ideal para Evitación de Obstáculos** | Regular (Peligroso para ramas/bordes) | Bueno | Excelente (El estándar en robótica móvil) |

Si el objetivo es la evitación de obstáculos en un dron, es mejor usar segmentación semántica.
Para el caso de uso de detección de obstáculos en un dron, un modelo de segmentación semántica ligera dará lo mejor de ambos mundos: una velocidad y ligereza que superan a la detección de objetos de YOLO, combinada con la capacidad crítica de detectar cualquier obstáculo parcial o rama delgada que se cruce en el camino del dron.

## Visual Looming (aproximación visual) o Detección de Obstáculos Basada en la Ocupación de la Imagen

Este es un enfoque muy común, robusto y elegante en la navegación autónoma de drones llamado Visual Looming (aproximación visual) o Detección de Obstáculos Basada en la Ocupación de la Imagen.
En lugar de estimar la profundidad en metros (lo que requiere una calibración compleja y es propenso a la ambigüedad de escala), se utiliza la relación entre el área del obstáculo segmentado y el área total del fotograma. A medida que el drone se acerca a un objeto, su proyección en el sensor de la cámara crece de forma exponencial.
Aquí se muestra cómo se puede implementar esto en el código, junto con el concepto de una "Zona de Peligro" (Central Region of Interest - ROI) para evitar falsas alarmas con objetos que se encuentran a los lados.

<img src="informe/2026-0714 Image Occupagy Obstacle detection.png"/>

### Lógica matemática fundamental
1. Área total del fotograma: $A_{\text{total}} = W \times H (\text{píxeles totales})$
2. Área del segmento: $A_{\text{obstáculo}}$ es el número de píxeles que pertenecen al segmento.
3. Porcentaje de ocupación:  $P_{\text{ocupación}} = \left(\frac{A_{\text{obstáculo}}}{A_{\text{total}}}\right) \times 100\%$
4. Umbral de colisión: se define un umbral (por ejemplo, el 15%). Si $P_{\text{ocupación}} \ge 15\%$, se activa una advertencia de colisión.

### Implementación en el bucle de segmentación YOLO
Se muestra cómo puedes modificar el bucle de procesamiento en `capture_video_seg.py` para calcular y mostrar el riesgo de colisión en función del porcentaje de ocupación del fotograma.

Fragmento de código para el Caso 1 (Segmentación de instancias):

```python
# --- Dentro del bucle de captura, reemplazando/aumentando el Caso 1 ---
if hasattr(results[0], 'masks') and results[0].masks is not None:
    classes = results[0].boxes.cls.cpu().numpy()
    names = results[0].names
    
    total_pixels = h * w
    # Definir los límites de una "Zona de Peligro" central (p. ej., el 40% central de la pantalla)
    danger_zone_x1 = int(w * 0.3)
    danger_zone_x2 = int(w * 0.7)
    danger_zone_y1 = int(h * 0.3)
    danger_zone_y2 = int(h * 0.7)
    
    # Opcional: Dibujar el cuadro de la Zona de Peligro en pantalla para depuración visual
    cv2.rectangle(annotated, (danger_zone_x1, danger_zone_y1), (danger_zone_x2, danger_zone_y2), (255, 255, 255), 1, cv2.LINE_AA)

    for i, mask_obj in enumerate(results[0].masks.xy):
        class_id = int(classes[i])
        class_name = names[class_id]
        
        # Solo nos interesan las clases de obstáculos (p. ej., árbol, edificio, poste, pared)
        # Omitir clases seguras si aplica
        
        # Crear una máscara binaria vacía
        binary_mask = np.zeros((h, w), dtype=np.uint8)
        pts = np.array(mask_obj, dtype=np.int32)
        cv2.fillPoly(binary_mask, [pts], 255)
        
        # Calcular el área de la máscara en píxeles (usando el momento cero)
        M = cv2.moments(binary_mask)
        obstacle_pixels = M["m00"]
        
        if obstacle_pixels > 0:
            # 1. Calcular el porcentaje de la imagen completa
            occupancy_pct = (obstacle_pixels / total_pixels) * 100
            
            # 2. Obtener el centroide para verificar si está directamente frente al dron
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            is_in_danger_zone = (danger_zone_x1 <= cx <= danger_zone_x2) and (danger_zone_y1 <= cy <= danger_zone_y2)
            
            # Definir los umbrales de ocupación
            WARNING_THRESHOLD = 5.0   # Ocupa el 5% de la pantalla
            CRITICAL_THRESHOLD = 15.0 # Ocupa el 15% de la pantalla
            
            # Decidir el nivel de alerta
            color = (0, 255, 255) # Amarillo por defecto
            alert_text = ""
            
            if occupancy_pct >= CRITICAL_THRESHOLD and is_in_danger_zone:
                color = (0, 0, 255) # Rojo para crítico
                alert_text = " [¡PELIGRO DE COLISIÓN!]"
                # Aquí activarías el bucle de control del dron para DETENER/FRENAR
            elif occupancy_pct >= WARNING_THRESHOLD:
                color = (0, 165, 255) # Naranja para advertencia
                alert_text = " [Advertencia]"
            
            # Dibujar la superposición de texto en la ventana de OpenCV
            text = f"{class_name}: {occupancy_pct:.1f}%{alert_text}"
            
            # Sombra
            cv2.putText(annotated, text, (cx - 50, cy + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
            # Texto
            cv2.putText(annotated, text, (cx - 50, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
```

Por qué esto es sumamente eficaz para el vuelo de drones monoculares:
1. **Seguridad invariable a la escala**: Ya sea que el obstáculo sea un árbol grande a lo lejos o un poste más pequeño de cerca, si bloquea una parte significativa del sensor de la cámara directamente frente al dron, representa un peligro de colisión.
2. **Conexión de control directo**: Si cualquier clase objetivo (p. ej., tree, building, person) tiene un occupancy_pct > 15.0 y su centroide está en la región central del fotograma, el código de tu piloto automático o modelo puede anular inmediatamente los comandos de velocidad: 
```python
# Comando de frenado de emergencia 
client.execute_velocity(vx=0.0, vy=0.0, vz=0.0)
```

3. **Sin dependencia de sensores adicionales**: Funciona con cámaras RGB estándar de bajo costo sin necesidad de usar sensores mas caros como LiDAR activos o cámaras con sensor de profundidad.

## Falsos positivos con la segmentación semántica de YOLO

En la literatura científica, este concepto se conoce como la **Teoría Tau ($\tau$)** o **Detección del Tiempo de Colisión (TTC - Time-to-Collision)** basada en la tasa de expansión divergente: **un objeto lejano y enorme (como una montaña o el suelo a gran altura) tiene una tasa de expansión visual casi nula, mientras que un objeto cercano y peligroso se expande exponencialmente a medida que nos acercamos.**

<img src="informe/2026-0714 False Collition Detection Avoidance.png"/>

### La Matemática del Tiempo de Colisión ($TTC$)

Si se aproxima a un obstáculo a una velocidad constante, el área de su proyección en la cámara ($A$) crece de forma no lineal. La relación entre el área actual y su velocidad de crecimiento nos da directamente el **Tiempo de Colisión** sin necesidad de conocer la distancia real ni la velocidad del dron.

La **Tasa de Expansión Relativa (RER)** se define como:

$$\text{RER} = \frac{1}{A} \frac{dA}{dt}$$

A partir de aquí, el Tiempo de Colisión ($TTC$) se puede aproximar mediante la siguiente fórmula:

$$TTC \approx \frac{2 \cdot A}{\frac{dA}{dt}}$$

* **Caso A (Montaña lejana/Suelo alto):** El área $A$ es grande (ej. 20% del ROI), pero la tasa de cambio $\frac{dA}{dt}$ es prácticamente $0$. El $TTC$ tiende a infinito ($\infty$). **No hay peligro.**
* **Caso B (Rama cercana):** El área $A$ empieza siendo pequeña pero su tasa de cambio $\frac{dA}{dt}$ se dispara de golpe. El $TTC$ cae rápidamente a valores como $1.5\text{ segundos}$. **¡Frenado de emergencia inmediato!**

### Cómo implementarlo en el código (Control Temporal)

Para calcular esto en el bucle de procesamiento, es necesario guardar el estado del fotograma anterior para calcular la diferencia de área ($\Delta A$) y la diferencia de tiempo ($\Delta t$).

Para evitar la complejidad de tener que "rastrear" individualmente cada objeto (lo cual requeriría un algoritmo de tracking como ByteTrack), una solución muy robusta y elegante es **medir la ocupación global sumada dentro del ROI central (la Zona de Peligro).**

A continuación se muestra un fragmento de código que ilustra cómo estructurar esta lógica en Python:

```python
import time

# --- Variables globales para mantener la memoria entre fotogramas ---
prev_roi_area = 0.0
prev_time = None

# Umbral de tiempo al impacto para disparar la alarma (en segundos)
TTC_CRITICAL_THRESHOLD = 1.8  # Si el choque es en menos de 1.8 segundos, frena.

# --- Dentro de tu bucle de captura de video ---
def process_frame(frame, results, h, w):
    global prev_roi_area, prev_time
    
    current_time = time.time()
    
    # 1. Definir la Zona de Peligro central (ROI)
    roi_x1, roi_x2 = int(w * 0.3), int(w * 0.7)
    roi_y1, roi_y2 = int(h * 0.3), int(h * 0.7)
    roi_total_pixels = (roi_x2 - roi_x1) * (roi_y2 - roi_y1)
    
    # Creamos una máscara vacía para acumular todos los obstáculos detectados DENTRO del ROI
    accumulated_roi_mask = np.zeros((h, w), dtype=np.uint8)
    
    # 2. Acumular máscaras de segmentación en el frame
    if hasattr(results[0], 'masks') and results[0].masks is not None:
        for mask_obj in results[0].masks.xy:
            pts = np.array(mask_obj, dtype=np.int32)
            cv2.fillPoly(accumulated_roi_mask, [pts], 255)
            
    # Cortamos la máscara acumulada para quedarnos solo con el ROI central
    roi_mask = accumulated_roi_mask[roi_y1:roi_y2, roi_x1:roi_x2]
    current_roi_area = np.sum(roi_mask == 255) # Número de píxeles ocupados en el ROI
    
    # 3. Calcular la dinámica temporal (TTC)
    if prev_time is not None and prev_roi_area > 0:
        dt = current_time - prev_time
        
        if dt > 0:
            # Diferencia de área (píxeles ganados/perdidos)
            delta_area = current_roi_area - prev_roi_area
            
            # Solo nos importa si el obstáculo se está expandiendo (acercando)
            if delta_area > 0:
                da_dt = delta_area / dt  # Velocidad de crecimiento (píxeles/segundo)
                
                # Calcular el Tiempo de Colisión (TTC)
                ttc = (2.0 * current_roi_area) / da_dt
                
                print(f"Área actual ROI: {current_roi_area}px | Crecimiento: {da_dt:.1f}px/s | TTC: {ttc:.2f}s")
                
                # CONDICIÓN DE COLISIÓN DINÁMICA
                # Solo disparamos si el área es mínimamente significativa Y el impacto es inminente
                min_area_pct = (current_roi_area / roi_total_pixels) * 100
                if ttc < TTC_CRITICAL_THRESHOLD and min_area_pct > 3.0:
                    print("¡¡ALERTA DINÁMICA: EVITACIÓN DE COLISIÓN ACTIVADA!!")
                    # client.execute_velocity(vx=0.0, vy=0.0, vz=0.0) # Frenar dron
            else:
                # El obstáculo se aleja o se mantiene estable (TTC infinito)
                ttc = float('inf')
                
    # Guardar estado actual para el siguiente fotograma
    prev_roi_area = current_roi_area
    prev_time = current_time

```

### Ventajas de este enfoque temporal:

1. **Inmunidad a falsos positivos aéreos:** Volar alto sobre bosques, lagos o ciudades generará un área de ocupación alta pero constante ($\Delta A \approx 0$). El algoritmo ignorará estas lecturas al calcular un $TTC$ seguro.
2. **Independiente de la velocidad del dron:** Si el dron vuela rápido, el $TTC$ se reduce velozmente; si vuela lento, el $TTC$ se mantiene alto. La alarma se adapta dinámicamente a tu velocidad de avance.
3. **Sin necesidad de Tracking individual:** Al unificar todo en el "área total del ROI central", no hay que preocuparse si YOLO pierde el ID del objeto entre fotogramas. Lo único que importa es la masa de píxeles que bloquea el frente.

### ¿Cuánta historia considera?

El algoritmo usa un **EMA (Exponential Moving Average / Media Móvil Exponencial)** — no es ni fotograma-a-fotograma puro, ni un promedio de ventana fija. Así funciona:

La fórmula es:

```python
smoothed = 0.4 * delta_actual + 0.6 * ema_anterior
```

Esto **considera implícitamente todos los fotogramas anteriores**, pero con **pesos exponencialmente decrecientes**:

| Fotograma | Peso | Acumulado |
|-----------|------|-----------|
| Actual (t) | 40% | 40% |
| t−1 | 24% | 64% |
| t−2 | 14.4% | 78% |
| t−3 | 8.6% | 87% |
| t−4 | 5.2% | 92% |
| t−5 | 3.1% | 95% |

**El 95% de la señal viene de los últimos ~6 fotogramas.** A 30-60 fps, eso son ~100-200ms de historia. La ventana efectiva es muy corta, lo cual lo hace reactivo a cambios rápidos.

### ¿Es promedio o fotograma a fotograma?

Es un **híbrido**:
1. El **delta** (`occ_pct - prev_occ`) se calcula **fotograma a fotograma** (solo almacena la ocupación del frame anterior en `prev_class_roi_occupancy`)
2. Pero ese delta se **suaviza con EMA**, lo que actúa como un promedio ponderado que da más peso al presente

Si fuera `EMA_ALPHA = 1.0` sería puramente fotograma-a-fotograma (sin suavizado, ruido). Si fuera `EMA_ALPHA = 0.1` sería casi un promedio de muchos frames (lento, poco reactivo). Con `0.4` es un buen balance: **responde rápido (~3 frames para registrar una amenaza real) pero filtra el ruido de un solo frame**.

## Reconsideración de la trayectoria con ORB-SLAM

Por último, al detectar el peligro queda involucrar la modelo SLM a bordo del dron para que pueda tomar decisiones sobre la trayectoria a seguir. En el mundo de los drones y la robótica terrestre, lo que se necesita es **ORB-SLAM** (un algoritmo famosísimo de SLAM visual que utiliza características llamadas ORB). Así, se separa la **reacción rápida** de la **deliberación inteligente** usando el SLAM como puente es el camino correcto. Así es como funciona esta arquitectura en la práctica.

<img src="informe/2026-0714 ORB-SLAM.png"/>

### La Arquitectura "Reflejo-Deliberación"

En lugar de que un único modelo intente controlarlo todo (lo cual sería lento y consumiría demasiada batería), se divide el sistema de navegación del drone en dos niveles:

#### 1. El Sistema Reflejo (Bajo Nivel / Grafo de Control)

* **Qué hace:** Corre en tiempo real a alta frecuencia (ej. 50Hz - 100Hz).
* **Herramientas:** El algoritmo de **TTC** (Tiempo de Colisión) visto antes, o sensores de proximidad simples.
* **Acción:** Si detecta un peligro inminente, el grafo de control interrumpe inmediatamente el vuelo y **detiene el dron en seco** (vuelo estacionario/hover). Es el equivalente al reflejo de cerrar los ojos cuando algo vuela hacia los ojos.

#### 2. El Sistema Deliberativo (Nivel Alto / El "Cerebro")

Una vez que el drone está detenido y seguro, el grafo de control "despierta" a un modelo de toma de decisiones (que en este caso es un [SLM] probablemente complementado con un Modelo de Lenguaje Visual [VLM] para interpretar la situación ) y le entrega el **contexto del ORB-SLAM**:

* **Nube de puntos 3D:** El SLAM le dice al modelo exactamente dónde están los límites físicos del obstáculo en el espacio tridimensional, no solo en una imagen plana de 2D.
* **Historial de trayectoria (Odometría):** El modelo sabe con precisión milimétrica de dónde venía el dron, lo que evita que intente retroceder hacia un lugar peligroso por el que acaba de pasar.
* **Espacio libre (Free Space):** El SLAM puede proporcionar una estimación de qué zonas del entorno *no* tienen obstáculos, permitiendo al modelo calcular una ruta de escape viable.

### ¿Cómo se le pasa esta información al modelo?

Para que el modelo decida el siguiente comando, no le pasas la nube de puntos gigante y cruda del SLAM (eso lo abrumaría). En su lugar, traduces los datos del SLAM en **información de contexto estructurada**:

> **Ejemplo de contexto enviado al modelo:**
> * *Estado:* Detenido por TTC (Obstáculo al frente).
> * *Distancia al obstáculo:* 1.1 metros.
> * *Mapa de ocupación local:* Obstáculo bloqueando el sector delantero ($[-30^\circ, +30^\circ]$). Sector izquierdo ($[-90^\circ, -30^\circ]$) libre de obstáculos hasta 5 metros. Sector derecho bloqueado por una pared detectada por SLAM.
> * *Meta del viaje:* Norte ($0^\circ$).
> 
> 

Con este contexto digerido, el modelo puede tomar una decisión lógica en milisegundos: *"Girar 45 grados a la izquierda, avanzar 2 metros para rodear el obstáculo, y reanudar la ruta hacia el Norte"*.

Esta combinación evita el procesamiento continuo de algoritmos pesados de IA durante el vuelo normal, activándolos únicamente cuando el dron se topa con una situación compleja que el grafo de control básico no sabe resolver.

# 2026-0713

### Fine tunning de YOLOv8n-seg y optimización de la visualización de máscaras.

#### 1. Cómo funciona la captura y la segmentación en `capture_video.py`
El proceso de captura y segmentación funciona en un bucle (loop) continuo dentro de la función `main()`:

##### A. Inicialización del modelo y del cliente

1. **Inicialización de YOLO**: En `init_yolo`, el script carga el modelo YOLO desde una ruta personalizada que se pasa como argumento de línea de comandos. Si no se proporciona ninguna ruta, carga por defecto `weights/yolo26n.pt`.
2. **Conexión con AirSim**: El script instancia y conecta el `AirSimClient`.
* **Modo simulador real**: Si AirSim se está ejecutando, el cliente se conecta a la API de simulación.
* **Modo de respaldo (fallback) simulado**: Si el simulador no está disponible, el cliente recurre a la generación de fotogramas de ruido sintético que contienen un rectángulo naranja central para simular un obstáculo.

##### B. El bucle principal 

1. **Captura de fotogramas**: `client.capture()` obtiene el fotograma RGB sin procesar de la cámara del simulador (por defecto la cámara `"0"` / vista de escena).

2. **Conversión del espacio de color**: La matriz de la imagen se convierte de RGB a BGR (`cv2.cvtColor(img, cv2.COLOR_RGB2BGR)`) porque tanto OpenCV (`cv2`) como YOLO esperan que los canales estén en orden BGR.

3. **Segmentación YOLO**:
* `results = yolo_model(frame_bgr)` ejecuta la inferencia en el fotograma.
* `annotated = results[0].plot()` dibuja las cajas delimitadoras (bounding boxes) detectadas, las máscaras, las puntuaciones de confianza (confidence scores) y las etiquetas de clase sobre una copia del fotograma.

4. **Mostrar y guardar**: El script muestra el fotograma anotado en una ventana de OpenCV y lo escribe en un archivo `.mp4` si se proporcionó una ruta de guardado.

---

#### 2. Cómo ajustar la segmentación

Se puede ajustar la segmentación de dos formas principales: mediante **parámetros en tiempo de ejecución** (la opción más rápida) y mediante el **entrenamiento del modelo** (la más precisa para objetos personalizados).

##### Opción A: Ajustar los parámetros de inferencia (Ajuste en tiempo de ejecución)

Se puede personalizar el comportamiento de la inferencia pasando parámetros a la llamada del modelo reemplazando la línea `capture_video.py`:

```python
results = yolo_model(frame_bgr)

```

por:

```python
results = yolo_model(
    frame_bgr,
    conf=0.5,      # Umbral de confianza (de 0.0 a 1.0). Valores más altos reducen los falsos positivos.
    iou=0.45,      # Umbral IoU para NMS. Valores más bajos ayudan a evitar detecciones duplicadas superpuestas.
    imgsz=640,     # Tamaño de imagen para inferencia (redimensiona el fotograma). 640 es el estándar; usar el tamaño real de la cámara aumenta la precisión.
    device='cuda', # Fuerza el uso de la GPU ('cuda' o 0) para obtener FPS en tiempo real, o 'cpu' si no hay GPU disponible.
    classes=[0, 2] # (Opcional) Filtra los resultados para mostrar solo IDs de clases específicos (ej. barcos, puertas/gates, etc.).
)

```

También se puede ajustar la **visualización de las anotaciones** (por ejemplo, quitando las etiquetas o las cajas y dejando solo la máscara de segmentación) dentro de la llamada `.plot()`:

```python
# Mostrar solo las máscaras, ocultar las cajas delimitadoras y los nombres de las clases
annotated = results[0].plot(boxes=False, labels=False, conf=False)

```

##### Opción B: Entrenar YOLO para elementos específicos del simulador

Si el modelo por defecto no logra segmentar los objetos personalizados de tu simulación (como puertas específicas, drones o el terreno), hay que entrenar un modelo propio:

1. **Recolectar fotogramas**: Ejecutar `capture_frame.py` bajo distintas posiciones de vuelo para guardar imágenes de ejemplo.
2. **Anotar**: Etiquetar las imágenes con máscaras de polígonos usando una plataforma de anotación (por ejemplo, CVAT o Roboflow) y exportarlas en el formato YOLOv8 de PyTorch.
3. **Reentrenar el modelo**: Ejecutar un script de entrenamiento para ajustar un modelo de segmentación base:
```python
from ultralytics import YOLO
model = YOLO("yolov8n-seg.pt")
model.train(data="your_dataset.yaml", epochs=50, imgsz=640, device=0)

```

4. **Desplegar**: Mover los pesos entrenados (`best.pt`) al directorio `weights/` y pasarlos como argumento cuando ejecutes `capture_video.py`.


### Opciones de inferencia de YOLO (ajuste fino sin reentrenamiento)

Se pueden pasar varios parámetros directamente a `yolo_model()` para cambiar su sensibilidad de detección, velocidad y precisión sobre la marcha:

| Parámetro | Tipo y por defecto | Descripción | Estrategia de uso/ajuste |
| --- | --- | --- | --- |
| **`conf`** | `float` (`0.25`) | Umbral mínimo de puntuación de confianza. | Aumentarlo (por ejemplo, a `0.5` o `0.6`) para eliminar falsos positivos débiles. Reducirlo (por ejemplo, a `0.15`) si YOLO no detecta objetivos debido a una mala iluminación. |
| **`iou`** | `float` (`0.7`) | Umbral de Intersección sobre Unión (IoU) para la Supresión No Máxima (NMS). | Reducirlo (por ejemplo, a `0.45`) para fusionar cajas delimitadoras superpuestas de la misma clase (elimina detecciones dobles de un mismo objeto). |
| **`imgsz`** | `int` o `tuple` (`640`) | Redimensiona los fotogramas antes de procesarlos. | Usa una tupla que coincida con la relación de aspecto de la cámara (por ejemplo, `(720, 1280)`) para evitar que se distorsione la imagen. Mayor tamaño = más detalle/detección de objetos más pequeños, pero menor FPS. |
| **`half`** | `bool` (`False`) | Habilita la inferencia de punto flotante en FP16 (precisión media). | Establécelo en `True` en GPU (`device='cuda'`) para duplicar la velocidad de inferencia casi sin pérdida de precisión. |
| **`max_det`** | `int` (`300`) | Máximo de detecciones permitidas por fotograma. | Configúralo en un número bajo (por ejemplo, `10`) para acelerar la anotación del fotograma si solo buscas unos pocos objetos. |
| **`classes`** | `list[int]` (`None`) | Filtra objetos por IDs de clase. | Pasa IDs de clase específicos (por ejemplo, `classes=[0]` para personas) para ignorar por completo objetos no relacionados. |
| **`retina_masks`** | `bool` (`False`) | Renderiza las máscaras en alta resolución. | Configúralo en `True` para obtener bordes nítidos y de alta precisión en las máscaras de segmentación (disminuye ligeramente los FPS). |

*Ejemplo de llamada para obtener un rendimiento de FPS óptimo en tiempo real:*

```python
results = yolo_model(
    frame_bgr,
    conf=0.45,
    iou=0.45,
    imgsz=640,
    half=True,        # Acelera la inferencia en GPU Nvidia
    device='cuda',
    retina_masks=True # Bordes de máscara limpios y nítidos
)

```

### Personalización de las anotaciones (`results[0].plot()`)

El método `.plot()` dibuja las cajas delimitadoras, etiquetas y máscaras sobre el fotograma. Se puede ajustar su comportamiento con los siguientes argumentos:

* **`boxes`** (`bool`, por defecto `True`): Establecerlo en `False` para ocultar las cajas delimitadoras.
* **`labels`** (`bool`, por defecto `True`): Establecerlo en `False` para ocultar las etiquetas de clase (por ejemplo, "gate").
* **`conf`** (`bool`, por defecto `True`): Establecerlo en `False` para ocultar el porcentaje de confianza.
* **`alpha`** (`float`, por defecto `0.5`): Transparencia de las máscaras de color superpuestas (`0.0` es completamente transparente, `1.0` es color sólido).
* **`line_width`** (`int`, por defecto `None`): Grosor del contorno de las cajas (por defecto se escala según el ancho de la imagen).

*Ejemplo de una salida limpia que muestra solo las máscaras (ideal para visualizar segmentación semántica):*

```python
annotated = results[0].plot(
    boxes=False,    # Sin rectángulos de cajas
    labels=False,   # Sin etiquetas de texto
    conf=False     # Sin números de confianza
)

```

---

* Buscando modelos YOLO mas optimizados para la detección de objetos en tiempo real en entornos urbanos.
* Iniciada gestion de cuenta en [Cityscapes Datasets](https://www.cityscapes-dataset.com/) para la descarga de un modelo preentrenado más genérico en detecciónm de objetos urbanos.
* Iniciado calculo de distancia en captura segmentada con modelo de clasificación semántico.

# 2026-0711

* Corrección de angulo de actitud del drone en base al valor del eje Z en el script de control manual cuando cambia la posición horizontal del drone.
* Eliminación de código muerto en `airsim-kc/main.py`

# 2026-0708

* Modelo de segmentación automática YOLO actualizado a **YOLO26**
* Implementación de controlador de teclado más simple para experimentos de detección de objetos

# 2026-0706

**YOLOv8** (You Only Look Once, versión 8), lanzado por Ultralytics, es uno de los modelos de visión artificial más avanzados, rápidos y eficientes de la actualidad.

A diferencia de las primeras versiones de YOLO que solo detectaban objetos en cajas (bounding boxes), YOLOv8 es una plataforma unificada capaz de realizar múltiples tareas: **detección de objetos, segmentación de instancias, clasificación de imágenes y seguimiento de objetos (tracking)**.

<img src="informe/2026-0706 YOLO infografia.png"/>

### 1. ¿Cómo funciona YOLOv8 para la segmentación?

La **segmentación de instancias** no solo detecta qué objetos hay en una imagen y dónde están, sino que identifica cada píxel exacto que pertenece a ese objeto (creando una "máscara").

YOLOv8 logra esto en tiempo real gracias a su arquitectura:

* **Red de un solo paso (Single-Shot):** Procesa la imagen completa de una sola vez. No necesita proponer regiones primero y luego clasificarlas (como hacían redes más lentas tipo R-CNN).
* **Split-Head (Cabezas divididas):** Separa físicamente las tareas de clasificación (qué es) y regresión (dónde está) en la punta de la red. Para la segmentación, añade una "cabeza" adicional que predice las máscaras de píxeles mediante coeficientes de prototipos.
* **Sin Anclas (Anchor-Free):** Predice directamente el centro de los objetos en lugar de usar cajas de referencia predefinidas. Esto reduce drásticamente el tiempo de cómputo y mejora la precisión en objetos deformes o superpuestos.

### 2. Implementación en Tiempo Casi Real (Video Streams)

Para procesar un stream de video (como una cámara web, un archivo de video o un flujo RTSP de una cámara de seguridad) a alta velocidad, se utiliza Python junto con la librería oficial de `ultralytics` y `opencv`.

#### Requisitos Previos

Primero, instala las dependencias en tu terminal:

```bash
pip install ultralytics opencv-python touch
```

#### Código de Implementación

Este script captura el video frame por frame, le aplica el modelo de segmentación de YOLOv8 y muestra el resultado renderizado en tiempo real.

```python
import cv2
from ultralytics import YOLO

# 1. Cargar el modelo YOLOv8 de segmentación (la 'x' al final indica el tamaño, 'n' es el más rápido)
# Tamaños disponibles: yolov8n-seg (nano), yolov8s-seg (small), yolov8m-seg (medium), yolov8l-seg (large), yolov8x-seg
model = YOLO("yolov8n-seg.pt") 

# 2. Configurar la fuente de video
# Usa '0' para la webcam integrada, o la ruta de un archivo/stream ("video.mp4" o "rtsp://...")
source = 0 
cap = cv2.VideoCapture(source)

if not cap.isOpened():
    print("Error: No se pudo abrir la fuente de video.")
    exit()

print("Presiona 'q' para salir del stream.")

while cap.isOpened():
    success, frame = cap.read()
    
    if not success:
        print("Fin del video o stream interrumpido.")
        break

    # 3. Realizar la inferencia en el frame actual
    # 'stream=True' optimiza el uso de memoria RAM para flujos continuos de video
    results = model(frame, stream=True)

    for r in results:
        # 4. Dibujar las máscaras y cajas de segmentación en el frame
        annotated_frame = r.plot() 
        
    # 5. Mostrar el frame procesado en una ventana
    cv2.imshow("YOLOv8 Real-Time Segmentation", annotated_frame)

    # Romper el bucle si se presiona la tecla 'q'
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# Liberar recursos
cap.release()
cv2.destroyAllWindows()
```

### 3. Claves para lograr "Tiempo Real" (Optimización)

Si se nota retraso (lag) en el stream, se pueden aplicar los siguientes ajustes:

* **Elige el modelo correcto:** Usar `yolov8n-seg.pt` (Nano). Es el más ligero, diseñado específicamente para dispositivos con recursos limitados (como CPUs o Raspberry Pi) y alcanza la mayor tasa de FPS (cuadros por segundo).
* **Aprovecha la GPU (CUDA):** Si se tiene una tarjeta gráfica NVIDIA, asegúrarse de tener instalado PyTorch con soporte CUDA. YOLOv8 la detectará automáticamente, multiplicando la velocidad por 10 o más.
* **Reducción de resolución:** Se puede indicar al modelo que procese las imágenes a un tamaño menor utilizando el parámetro `imgsz`. Por ejemplo: `model(frame, imgsz=320, stream=True)`. Menos píxeles se traducen en un procesamiento mucho más rápido.

### Prueba de Captura y procesamiento YOLO

* Generación de script `capture_video.py` para captura manual de fotogramas con cámara del drone para verificar cuál es la entrada de YOLO.
* Prueba de correcta ejecución del loop de control en ambiente mínimo (`TownSim`)  con el drone Airsim en un entorno con obstáculos en un ambito urbano. Control del dronen en manual
* Subido video ["AirSim Plugin on UE 5.5 video capture and YOLO in real time"](https://youtu.be/BkV4tYFSrrs) con prueba de captura de video y detección de objetos con YOLO en tiempo real. 

<img src="informe/2026-0706 Captura Video YOLO.png"/>

# 2026-0705

### Pruebas y ajustes al loop de control autónomo en `airsim-loop`

* Carga inicial de pesos de YOLOv8.
* Generación de script `capture_frame.py` para captura manual de fotogramas con cámara del drone para verificar cuál es la entrada de YOLO.

<img src="informe/imagen_20260706_003541.jpg"/>

* Ajuste del script `main.py` para la correcta ejecución del loop de control
* Prueba de correcta ejecución del loop de control en ambiente mínimo (`MiniSim`) sólo con el drone Airsim sin obstáculos ni meteorología. Falta forzar la toma decisión con una manifiesto de vuelo mínimo para verificar el cambio del YOLO al SLM Local. Todavía resta probar la generación asistiada y estructurada del manifiesto de misión.
* Ajustes a `requirements.txt` con las dependencias necesarias

# 2026-0702

### Evaluando performance de SLM corriendo localmente con Ollama

* Instalación de [ollama-benchmark](https://github.com/LarHope/ollama-benchmark)
* Evaluando: `gemma2:2b`, `qwen3.5:4b`,`llama3.2:latest`,`LiquidAI/lfm2.5-1.2b-instruct:latest`, `phi4-mini:latest`,`LiquidAI/lfm2.5-350m:latest`
* Generando tablas comparativa con: `ollama-benchmark --verbose --prompts "Write a hello world in Rust" "Explain quantum computing" "How blockchain works" --table_output --models gemma2:2b qwen3.5:4b llama3.2:latest LiquidAI/lfm2.5-1.2b-instruct:latest phi4-mini:latest LiquidAI/lfm2.5-350m:latest`

| Model Name | Prompt Evaluation Rate (T/s) | Evaluation Rate (T/s) | Total Rate (T/s) | Load Time (s) | Prompt Evaluation Count | Prompt Evaluation Time (s) | Evaluation Count | Evaluation Time (s) | Total Time (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gemma2:2b | 240.05 | 54.03 | 55.11 | 0.31 | 39 | 0.16 | 1501 | 27.78 | 28.27 |
| qwen3.5:4b | 153.76 | 28.82 | 29.01 | 0.51 | 43 | 0.28 | 5359 | 185.92 | 186.79 |
| llama3.2:latest | 1133.67 | 44.79 | 47.54 | 0.32 | 88 | 0.08 | 1370 | 30.59 | 31.01 |
| LiquidAI/lfm2.5-1.2b-instruct:latest | 1245.20 | 120.67 | 139.95 | 0.11 | 85 | 0.07 | 472 | 3.91 | 4.10 |
| phi4-mini:latest | 238.22 | 37.19 | 37.98 | 0.34 | 21 | 0.09 | 839 | 22.56 | 23.01 |
| LiquidAI/lfm2.5-350m:latest | 3928.09 | 220.06 | 292.20 | 0.12 | 85 | 0.02 | 240 | 1.09 | 1.24 |

* Considerando tests más completos, por ejemplo [promptFoo](https://dev.to/roobia/como-probar-aplicaciones-llm-guia-completa-de-promptfoo-2026-k4p)
* Instalación de [promptFoo](https://www.promptfoo.dev/docs/getting-started/) 
```
brew install promptfoo
mkdir local-llm-eval
cd local-llm-eval
promptfoo init 
promptfoo eval setup
```
* Configuración de prueba con los mismos modelos y promtps:
#### Providers
<img src="informe/2026-0702 promptFoo Providers.png"/>

#### Prompts
<img src="informe/2026-0702 PrompFoo Prompts.png"/>

#### Configuración completa de la prueba
``` yaml
# yaml-language-server: $schema=https://promptfoo.dev/config-schema.json
description: ''
env: {}
extensions: []
prompts:
  - Write a hello world in Rust
  - Explain quantum computing
  - How blockchain works
providers:
  - id: ollama:chat:llama3.2:latest
  - id: ollama:gemma2:2b
    config: {}
    label: ollama:gemma2:2b
  - id: ollama:qwen3.5:4b
    config: {}
    label: ollama:qwen3.5:4b
  - id: ollama:llama3.2:latest
    config: {}
    label: ollama:llama3.2:latest
  - id: ollama:LiquidAI/lfm2.5-1.2b-instruct:latest
    config: {}
    label: ollama:LiquidAI/lfm2.5-1.2b-instruct:latest
  - id: ollama:phi4-mini:latest
    config: {}
    label: ollama:phi4-mini:latest
  - id: ollama:LiquidAI/lfm2.5-350m:latest
    config: {}
    label: ollama:LiquidAI/lfm2.5-350m:latest
scenarios: []
tests:
  - description: Fun animal adventure story
    vars:
      animal: penguin
      location: tropical island
    assert: []
evaluateOptions:
  delay: 0
defaultTest:
  options:
    provider: ollama:chat:llama3.2:latest
derivedMetrics: []
```

#### Resultados de la prueba
* Visualización con 
```
promptfoo view
```
<img src="informe/2026-0702 prompFoo Results.png"/>


# 2026-0627

### Regeneración de Datos Sintéticos

* Modificados los scripts `airsim_commander.py` y `airsim_iterator.py` para soportar trayectorias completas como comando y para recibirlas por línea de comando.

* Subido video [AirSim Plugin on UE 5.5 synthetic telemetry for Drone 1 trajectory](https://youtu.be/LGso1VYQsPY) con muestra de generación de telemetría sintética del drone 1 (trayectoria en azul)
* Subido video [AirSim Plugin on UE 5.5 synthetic telemetry for Drone 2 trajectory](https://youtu.be/xgItxxe4yRM) con muestra de generación de telemetría sintética del drone 2 (trayectoria en marrón)
* Regeneración de telemetría sintética con trayectorias de vuelos reales.
* Análisis de [Variabilidad de Telmetría de Vuelos Simulados vs Drones Reales](https://github.com/georgsmeinung/lm-drone/blob/main/callibration_flight/telemetry_analysis_20260627.ipynb) con nueva telemetría sintética generada el 2026-0627, generando reporte en notebook de Jupyter con estadísticas descriptivas y pruebas estadísiticas para determinar si existen diferencias significativas entre las distribuciones de los datos de telemetría simulados y reales. 

#### Comparación Drone 1
* Vuelo simulado con la trayectoria del Drone 1. Los puntos de las trayectorias están redondeados a múltiplos de 5.
```
# Trayetoria del drone 1, traza en azul (1E2A56)
takeoff
moveOnPath(0,0,-120,245,-65,-120,30,-45,-120,30,95,-120,-135,95,-120,-135,-45,-120,39,-45,-120,245,-65,-120,0,0,-120,0,0,0,5)
reset
```
<img src="informe/2026-0627 Generación de telemetría sintética del drone 1 - azul.png"/>
<img src="informe/2026-0627 Trayectorias Drone 1.png"/>
<img src="informe/2026-0627 Comparación de Pefiles de velocidad - Drone 1.png"/>

#### Comparación Drone 2
* Vuelo simulado con la trayectoria del Drone 2. Los puntos de las trayectorias están redondeados a múltiplos de 5.
```
# Trayectoria del drone 2, traza en marrón (8B4513)
takeoff
moveOnPath(0,0,-120, 50,-75,-120, -45,-20,-120, 95,-20,-120, 95,-110,-120, -100,-110,-120, -100,110,-120, 125,110,-120, -45,-20,-120, 50,-75,-120,0,0,-120,0,0,0,5)
reset
```
<img src="informe/2026-0627 Generación de telemetría sintética del drone 2 - marrón.png"/>
<img src="informe/2026-0627 Trayectorias Drone 2.png"/>
<img src="informe/2026-0627 Comparación de Pefiles de velocidad - Drone 2.png"/>

* Al contrastar la telemetría real frente a la simulada en las trayectorias específicas del 2026-06-27 para Dron 1 y Dron 2, concluimos lo siguiente:

1. **Variabilidad y Rigidez Física (Giro):**
   - Al igual que en la fecha anterior, las pruebas de Levene confirman una varianza de actitud significativamente diferente ($p \ll 0.05$). En la simulación (AirSim), el dron experimenta inclinaciones laterales y frontales extremas durante los giros rápidos para generar la aceleración requerida y seguir los puntos de la trayectoria instantáneamente.
   - En cambio, los drones reales (DJI) están restringidos electrónicamente por el controlador PID de estabilización (típicamente limitado a $\pm 30^\circ$), mostrando una varianza mucho menor y acotada durante las maniobras.
   
2. **Segregación por Trayectoria:**
   - La segregación por trayectorias ha permitido aislar correctamente el comportamiento inercial y de control en dos perfiles distintos. 
   - El **Dron 1** experimenta giros de rumbo menos frecuentes y más simples (rectángulo), por lo que las aceleraciones se concentran principalmente en las esquinas.
   - El **Dron 2**, con su patrón de cruz y rectángulo continuo, presenta una dinámica transicional mucho más exigente y ruidosa, lo que exacerba las oscilaciones de roll y pitch en la simulación y demanda correcciones más frecuentes en el dron real.

3. **Ruido Ambiental y Estocasticidad:**
   - Durante las fases **rectas**, la telemetría simulada en AirSim es idealizada (varianza de actitud cercana a 0), sin fuerzas externas de viento ni ruido de sensores.
   - El dron real, por otro lado, manifiesta una variabilidad permanente de $\pm 2^\circ - 3^\circ$ en roll y pitch incluso en tramos rectos estables, producto del viento real de la zona y de las correcciones del piloto automático.

### La optimización de Modelos de Lenguaje Pequeños (SLM) con LoRA (Low-Rank Adaptation) 

<img src="informe/2026-0627 Optimización_de_Modelos_Pequeños.png"/>

Para mejorar la navegación y respuesta del SLM corriendo abordo se considera **LoRA (Low-Rank Adaptation)**, que es una estrategia altamente eficiente que forma parte de las técnicas de **Ajuste Fino Eficiente en Parámetros (PEFT)**.  
LoRA optimiza los modelos funcionando mediante una **descomposición de bajo rango**: actualiza solo un subconjunto muy pequeño de parámetros (o afina unas pocas capas específicas) mientras mantiene fijos la mayor parte de los parámetros del modelo preentrenado original.

La aplicación de LoRA en SLMs aporta las siguientes ventajas y características fundamentales:

* **Eficiencia de recursos:** Al actualizar solo una fracción de la red, LoRA **reduce drásticamente los costos computacionales y los requisitos de memoria** asociados con el proceso de ajuste fino (fine-tuning), haciéndolo mucho más ligero y accesible.  

* **Agilidad extrema:** El ajuste de un SLM utilizando LoRA requiere **solo unas pocas horas de procesamiento en GPU**. Esto permite a los desarrolladores un ciclo de iteración muy rápido para agregar nuevos comportamientos, corregir errores o especializar el modelo de la noche a la mañana, en lugar de esperar semanas.  

* **Prevención del sobreajuste (Overfitting):** Dado que la mayor parte del modelo original permanece inalterada, LoRA ayuda a **preservar el conocimiento preentrenado del modelo**, reduce el riesgo de sobreajuste y mejora la flexibilidad.  

* **Especialización de dominio:** Es el método ideal para adaptar un SLM general a **conjuntos de datos de dominios específicos o aplicaciones de nicho**. Por ejemplo, un modelo puede optimizarse de forma rápida con LoRA sobre documentos legales para crear un asistente de análisis de contratos, o sobre manuales técnicos para desarrollar una guía de resolución de problemas 

* **Variantes avanzadas y facilidad de uso:** Su implementación hoy en día es sencilla gracias a bibliotecas como peft de Hugging Face, que permiten configurar rápidamente los parámetros de la adaptación. Además, existen variantes populares empleadas en SLMs como **QLoRA** (que cuantiza el modelo para reducir aún más el consumo de recursos) y **DoRA**, que expanden la capacidad de ajustar modelos bajo restricciones de hardware.

### Optimización de Modelos mediante Decodificación Restringida
Además de LoRA para hacer obtener ordenes de navegación estructuras se considera utilizar gramátias reducidas para formatear las salidas.La generación de salidas estructuradas y la mejora en la eficiencia de la inferencia se logra principalmente a través de una técnica conocida como **decodificación restringida (constrained decoding)**.  

**Generación de salidas estructuradas:**
* La decodificación restringida interviene en el proceso de generación del modelo evaluando las reglas de una gramática o restricción dada y **enmascarando (ocultando) los tokens que son inválidos** en cada paso .  
* Al hacer esto, el modelo es guiado para que tome muestras únicamente de tokens válidos, lo que garantiza que la salida final se ajuste perfectamente a la estructura predefinida, siendo **JSON Schema** el estándar predominante en la industria para definir estos formatos.  
* Para lograr esto, se han desarrollado motores de gramática y marcos de trabajo optimizados como Guidance, Outlines, Llamacpp y XGrammar, los cuales traducen estas reglas para controlar las respuestas del modelo.  
* En el caso específico de los SLM integrados en sistemas de agentes autónomos, mantener formatos estrictos (como JSON, XML o código Python) es vital para comunicarse con otras herramientas. Las fuentes sugieren que los SLM pueden ser ajustados (fine-tuned) de forma económica para forzar una única decisión de formato, evitando así alucinaciones estructurales que rompan el código del sistema.

**Mayor eficiencia en la inferencia:**Aunque aplicar gramáticas o restricciones podría parecer un proceso que añade carga computacional, las implementaciones optimizadas en realidad **pueden acelerar el proceso de generación hasta en un 50%** en comparación con la generación sin restricciones. Esto se logra mediante varias optimizaciones clave:

* **Procesamiento en paralelo:** El cálculo de la máscara de tokens permitidos se ejecuta en paralelo con el paso hacia adelante (forward pass) del modelo de lenguaje.  
* **Compilación simultánea:** La compilación inicial de la gramática requerida se realiza de manera concurrente con los cálculos de pre-llenado (pre-filling) del prompt inicial.  
* **Optimizaciones avanzadas:** Los sistemas emplean técnicas como el almacenamiento en caché de gramáticas y la decodificación especulativa basada en restricciones para reducir los tiempos de respuesta. Además, marcos como *Guidance* alcanzan una eficiencia sobresaliente al ser capaces de acelerar y saltarse directamente ciertos pasos de generación cuando la gramática los hace predecibles.

# 2026-0626

* Explorando usar [Ollama](https://ollama.com/) directamente en vez de [LMStudio](https://lmstudio.ai/)
* LMStudio es muy útil explorar modelos, su rendimiento y configuración de inferencia óptima pero Ollama parece tener más eficiencia para construir soluciones. 
* Posiblemente para una instalación en un dispositivo Edge, con bajo poder de cómputo como una companion computer del drone, probablemente [llama.cpp](https://llama.app/) sea la mejor opción.
* Corrección de infografías generadas por IA con [Nano Banana](https://gemini.google/tm/overview/image-generation/?hl=en-TM) a través de la app de escritorio de [Gemini](https://gemini.google.com/app)
* Instalación de [openai/gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) en Ollama directamenete desde el repositorio de Hugging Face de OpenAI:
``` Bash
# gpt-oss-20b
ollama pull gpt-oss:20b
ollama run gpt-oss:20b
```
* `gpt-oss-20b` is recommeded for lower latency, and local or specialized use cases (21B parameters with 3.6B active parameters)
* Igual tiene tiempo tiempos de respuesta altos para el proposito del prototipo y no es SLM. Prueba simple de conversación:
```
total duration:       50.381895541s
load duration:        228.9805ms
prompt eval count:    75 token(s)
prompt eval duration: 2.533294s
prompt eval rate:     29.61 tokens/s
eval count:           918 token(s)
eval duration:        47.494863s
eval rate:            19.33 tokens/s
```
* Probando con el modelo [LiquidAI/LFM2.5-8B-A1B](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B). Prueba de conversación simple:
```
total duration:       17.997622792s
load duration:        135.492042ms
prompt eval count:    15 token(s)
prompt eval duration: 162.112ms
prompt eval rate:     92.53 tokens/s
eval count:           1399 token(s)
eval duration:        17.698413s
eval rate:            79.05 tokens/s
```
* Primera implementación del loop de control en `airsim-loop`
* Primera implementación del planificador en `airsim-plan`
* Subido video ["AirSim Plugin on UE 5.5 Trajectory Auditory and RGB Video Capture at 720p"](https://youtu.be/BkV4tYFSrrs) para determinar el comportamiento del piloto automático en trayectorias porgramadas 

<img src="informe/2026-0626 Control de Trayectoria.png"/>

* Activada la opción de traza del Airsim (linea violeta flotando destrás del drone en el video). La falta de saltos de una trayectoria conocida de antemano por el piloto automático sugiere que procesa la aceleración más ordenadamente que con comandos separados. Esto puede se la explicación de las desacelearaciones brusas en las pruebas de generación de telemetría sintética. Habría que repetir el experimento con trayectorias en lugar de comandos aislados.
* Aunque el render del editor de Unreal Engine tenga algunos saltos, la captura de video de la cámara de abordo muestra el vuelo correctamente renderizado y sin saltos.
* Configuración en AirSim `settings.json` para subir la resolución de la camára del dron a 1080x720p. El archivo queda así:
``` JSON
{
  "SeeDocsAt": "https://github.com/Cosys-Lab/Cosys-AirSim/blob/main/docs/settings_example.json",
  "SettingsVersion": 2.0,
  "SimMode": "Multirotor",
  "LocalHostIp": "0.0.0.0",
  "ApiServerPort": 41451,
  "RecordUIVisible": false,
  "ClockType": "SteppableClock",
  "OriginGeopoint": {
    "Latitude": 47.641468,
    "Longitude": -122.140165,
    "Altitude": 122
  },
  "CameraDefaults": {
    "CaptureSettings": [
      {
        "ImageType": 0,
        "Width": 1080,
        "Height": 720
      },
      {
        "ImageType": 3,
        "Width": 1080,
        "Height": 720
      },
      {
        "ImageType": 5,
        "Width": 1080,
        "Height": 720
      },
      {
        "ImageType": 1,
        "Width": 1080,
        "Height": 720
      }
    ]
  }
}
```
* Con esta resolución se puede empezar la prueba del procesamiento YOLO y del SLM del loop del control del drone
* También fue necesario ajustar el renderizado del escena a `Epic` para tener una imagen monocular utilizable.

# 2026-0625

### Diseñando solución de Nagevación con SLM y LangGraph para comenzar el prototipado
<img src="informe/2026-0626 Infografia Drone Autónomo.png"/>

* Bucle de Navegación implementado con LangGraph
  - **Paso 1: Captura Sensorial.** El inicio del ciclo donde la API de AirSim proporciona imágenes RGB y telemetría crítica.
  - **Paso 2: Traducción Píxeles-a-Palabras.** El primer filtro de IA local. YOLOv8 o un modelo similar toma la imagen y genera coordenadas matemáticas. Nuestro código traduce instantáneamente estas coordenadas en conceptos textuales estructurados: el tipo de objeto, su ubicación en el encuadre (Izquierda, Centro, Derecha) y una estimación de proximidad.
  - **Paso 3: El "Gatekeeper" de LangGraph.** El nodo condicional decisivo. Aquí se aplica la lógica para ahorrar cómputo: si no hay un obstáculo inminente detectado al frente en el sector central, el flujo se desvía directamente al control reactivo. Si el camino está bloqueado, se dispara el nodo del cerebro.
  - **Paso 4A: Reflejo Rápido (Control Reactivo).** Una ruta de cómputo casi nulo. Al no haber peligro inmediato, el planificador reactivo decide mantener el rumbo por defecto, ahorrando valiosos ciclos de CPU del LLM.
  - **Paso 4B: Cerebro Deliberativo (SLM Local).** La ruta deliberativa. El SLM local (Phi-3 o Llama-3 en LM Studio) recibe el resumen textual detallado de la escena. Analiza, razona y genera un plan de evasión específico, como "esquivar por la derecha para evitar el árbol detectado al frente".
  - **Paso 5: Ejecución Motriz: El nodo final del ciclo.** Traduce la decisión de macro-acción (ya sea "mantener rumbo" o "esquivar por la derecha") en comandos directos de velocidad para la API de AirSim, moviendo físicamente el dron.
  - **Paso 6: Bucle Continuo.** El ciclo se cierra y comienza inmediatamente de nuevo, permitiendo una navegación autónoma y sensible al entorno en tiempo real.

* NOTAS
  - Para capturar el feed de video en tiempo real de AirSim y poder procesarlo YOLO, hay que  hacer capturas de imágenes en un bucle continuo como el presentado.
  - Para procesar una cámara monocular RGB en tiempo real y alimentar un Small Language Model (SLM) local sin colapsar la GPU, debemos aplicar el paradigma "Píxeles a Palabras" (Pixel-to-Text).
  - Dado que el SLM procesa texto a una velocidad menor (latencia de 100-300ms) que la captura de la cámara (30 FPS o ~33ms), el pipeline debe estar desacoplado. El procesamiento de imágenes (YOLO/OpenCV) corre a máxima velocidad, y LangGraph actúa como el orquestador deliberativo que decide cuándo consultar al SLM según el estado del entorno.
  - El flujo de procesamiento transforma los datos ópticos crudos en vectores de estado textuales que el SLM pueda entender perfectamente.
    1. Captura Frecuente (High-Frequency Loop): OpenCV extrae el frame RGB de AirSim.
    2. Compresión Espacial (Local Vision AI): YOLOv8-nano procesa el frame. Transforma las cajas de colisión bidimensionales ($x_1, y_1, x_2, y_2$) en conceptos relativos: Izquierda, Centro, Derecha y Tamaño (el tamaño relativo en una cámara monocular estima la cercanía).
    3. Inyección al Estado de LangGraph: El estado del dron se actualiza con la semántica del entorno.
    4. Evaluación de Disparadores (Gatekeeper): Si el camino está despejado, se ejecuta control directo (rutina estándar). Si se detecta un cambio o un obstáculo, se dispara el nodo del SLM.

### Diseñanando solución de Planificación de Misión para comenzar el prototipado
El complemento necesario para el sistema de navegación autonoma a bordo es la contraparte terrena que genera el manifiesto de vuelo

<img src="informe/2026-0626 Infografia Planificacion Vuelo.png"/>

El operador de vuelo sigue este flujo para la planificación:
  1. **Estación Terrena (Planificación).** El operador interactúa con una interfaz visual local, definiendo la ruta (Waypoints) y las reglas de seguridad sin necesidad de código complejo.
  2. **Manifiesto de Misión (El Contrato JSON).** La estación terrena compila las entradas del usuario en un archivo JSON estricto. Este documento es la fuente de la verdad para el dron, conteniendo coordenadas relativas y umbrales críticos (como el de la batería).
  3. **Inyección en LangGraph.** El archivo JSON se carga directamente en el estado inicial (AutonomousMissionState) del script de Python antes del despegue, pre-cargando la memoria del dron con su objetivo.
  4. **Ejecución a Bordo (El Navegador Estratégico).** Ya en vuelo, el nodo estratégico consulta constantemente este plan para dirigir al dron hacia el siguiente waypoint, delegando el control al SLM táctico (como Phi-3) únicamente si los sensores detectan un obstáculo imprevisto en la ruta.



# 2026-0624

* Revisión de documentación actualizad de [Cosys-AirSim](https://cosys-airsim.com/)
* Revisión de [configuración de Cosys-Airsim](https://cosys-lab.github.io/Cosys-AirSim/settings/)
* Revisión versiones en [repositorio GitHub de Cosys-Airsim](https://github.com/Cosys-Lab/Cosys-AirSim)

# 2026-0623

* Revisión y ordenamiento de CHANGELOG.MD

# 2026-0622

* Optimización de escena `Small_City_LVL` de ["City Sample"](https://www.fab.com/listings/4898e707-7855-404b-af0e-a505ee690e68), según las recomendaciones para ["lower spec systems"](https://dev.epicgames.com/documentation/unreal-engine/city-sample-project-unreal-engine-demonstration). Optmizado para visualización a distancia media con multitud y tráfico controlado con IA.
* Subido video ["AirSim Plugin on UE 5.5 running along AI traffic and crowds"](https://www.youtube.com/watch?v=mAna9kyDVSc) a YouTube mostrando vuelo con trafico y multitudes controlados por IA.

<img src="informe/2026-0623 Airsim con trafico y multitud IA.png"/>

* El laboratorio Cosys-Lab de la Universidad de Amberes aborda la relación entre el rendimiento gráfico y la simulación física. En su paper oficial sobre la plataforma, titulado ["Cosys-AirSim: A Real-Time Simulation Framework Expanded for Complex Industrial Applications"](informe/bibliografia/2303.13381v3.pdf), detallan de forma específica cómo equilibrar la carga computacional. 
* **La postura de Cosys-Lab sobre gráficos vs. física**: El paper original de Cosys-AirSim resalta que, a diferencia del AirSim clásico de Microsoft (enfocado principalmente en cámaras RGB y visión por computadora), Cosys-AirSim añade sensores avanzados como LiDAR, Sonar y Radar basados en GPU y CPU. Por lo tanto, bajar la calidad visual del entorno al mínimo es una práctica recomendada y necesaria si tu objetivo principal es priorizar la tasa de actualización de la física y los sensores activos, evitando que el renderizado de texturas y luces sature los recursos. Por este motivo, no se reducen las texturas, pero si el post procesamiento para renderizado cinmático en "City Sample".
* **Recomendaciones específicas de configuración**: Para lograr este comportamiento y evitar cuellos de botella en la simulación física, la documentación de Cosys-Lab y las configuraciones de su repositorio exigen ajustar los siguientes parámetros:
    - Desactivar el ahorro de CPU en segundo plano: En el editor de Unreal Engine, ir a Edit -> Editor Preferences, buscar el término "CPU" y desmarcar obligatoriamente la casilla "Use Less CPU when in Background". Si no, la tasa de refresco de la física caerá drásticamente en cuanto la ventana pierda el foco. 
    - Ajuste del ClockSpeed: Cosys-AirSim permite modificar la velocidad del reloj de simulación en el archivo settings.json mediante el parámetro "ClockSpeed": 1. Si los fotogramas por segundo (FPS) bajan demasiado debido a la carga gráfica, recomiendan reducir este valor (por ejemplo, a 0.5) para ralentizar el tiempo de simulación y dar margen a que la física se calcule de manera precisa y sincronizada paso a paso. Útil para cálculo de interacción detallada con la meteorología.
    - Modo sin renderizado (NoDisplay Mode): Si no se necesita recolectar imágenes de cámaras visuales (No es el caso de la temática de esta tesis) y solo se requiere la telemetría, la física o los datos de sensores puros, se recomienda activar el "ViewMode": "NoDisplay" en el archivo de configuración. Esto anula por completo el esfuerzo de renderizado de la pantalla de Unreal Engine, multiplicando la velocidad del motor de física interno. 
    - Uso de binarios empaquetados (Packages): Cosys-Lab aconseja ejecutar la simulación a través del proyecto ya compilado y empaquetado (Standalone/Executable Binary) en lugar de correrlo directamente desde el Unreal Editor. La ejecución directa en el editor consume recursos masivos de memoria y procesamiento gráfico dedicados a la interfaz del software de desarrollo.

# 2026-0621

* Análisis de [Variabilidad de Telmetría de Vuelos Simulados vs Drones Reales](https://github.com/georgsmeinung/lm-drone/blob/main/callibration_flight/telemetry_analysis_20260610.ipynb) con nueva telemetría sintética generada el 2026-060, generando reporte en notebook de Jupyter con estadísticas descriptivas y pruebas estadísiticas para determinar si existen diferencias significativas entre las distribuciones de los datos de telemetría simulados y reales. 
* La segregación por trayectorias, imitando la de los drones reales, ha permitido aislar correctamente el comportamiento inercial y de control en dos perfiles distintos. 
* El **Dron 1** experimenta giros de rumbo menos frecuentes y más simples (rectángulo), por lo que las aceleraciones se concentran principalmente en las esquinas.
<img src="informe/2026-0610 Trayectorias Drone 1.png">
<img src="informe/2026-0610 Perfiles de Velocidad Drone 1.png">
* El **Dron 2**, con su patrón de cruz y rectángulo continuo, presenta una dinámica transicional mucho más exigente y ruidosa, lo que exacerba las oscilaciones de roll y pitch en la simulación y demanda correcciones más frecuentes en el dron real.
<img src="informe/2026-0610 Trayectorias Drone 2.png">
<img src="informe/2026-0610 Perfiles de Velocidad Drone 2.png">
* Además durante las fases **rectas**, la telemetría simulada en AirSim es idealizada (varianza de actitud cercana a 0), sin fuerzas externas de viento ni ruido de sensores.
* El dron real, por otro lado, manifiesta una variabilidad permanente de $\pm 2^\circ - 3^\circ$ en roll y pitch incluso en tramos rectos estables, producto del viento real de la zona y de las correcciones del piloto automático.

# 2026-0619

* Prueba de conexión desde server con servicio LLM a server con servicio AirSim y simulación
* Comunicación física mediante cable cruzado Ethernet.
* Entorno de trabajo remoto configurado en VS Code para Windows 11 a server remoto en Mac OS Tahoe
* Prueba de control desde host IA hacia host AirSim remoto OK.

<img src="informe/2026-0619 Control Airsim desde Host IA.png"/>

# 2026-0612

* Depuración de configuración para tener el cliente de AirSime en un servidor separado
* Prepararción de entorno para ARM64
* Modificación de scripts para que tome la información del Host Airsim de un .env

# 2026-0611

* Configuración de servidor de inferencia en Mac mini con LMStudio:

<img src="informe/mac_mini_m4.jpg" width="50%"/>

```
      Model Name: Mac mini
      Model Identifier: Mac16,10
      Model Number: MU9D3LL/A
      Chip: Apple M4
      Total Number of Cores: 10 (4 Performance and 6 Efficiency)
      Memory: 16 GB
```
* Analizando modelos por debajo del 1B parámetros para inferencia razonablemente rápida
* Prueba de red por Ethernet entre los dos sistemas
* Prueba de fluidez de Unreal Engine sobre Remote Desktop Protocol. Funciona razonablemente. EL UE funciona mejor cuando se baja el viewport virtual
* La aceleración de la RTX 5060 no tiene efecto sobre el Remote Desktop. Se determina usar como estación de renderizado PC con la GPU

<img src="informe/RTX-5060-Ti-8Gb-Msi.jpeg" width="50%"/>

```
        Marketing Name: GeForce RTX™ 5060 8G GAMING OC 
        Model Name: G5060-8GC 
        Graphics Processing Unit: NVIDIA® GeForce RTX™ 5060
        Arquitecture: NVIDIA Blackwell (5 nm litography).
        Interface: PCI Express® Gen 5 x16 pin(uses x8) 
        Core Clocks: Extreme Performance: 2640 MHz (MSI Center) Boost: 2625 MHz 
        CUDA® CORES: 3840 Units 
        Memory Speed: 28 Gbps 
        Memory: 8GB GDDR7 
        Memory Bus: 128-bit 
        HDCP Support: Y 
        Power consumption: 155 W 
        Power connectors: 8-pin x 1 
        Recommended PSU: 550 W 
        Card Dimension (mm): 248 x 135 x 41 mm 
        Weight (Card / Package): 649 g / 966 g 
        DirectX Version Support: 12 Ultimate 
        OpenGL Version Support: 4.6 
        Maximum Displays: 4 
        G-SYNC® technology: Y 
        Digital Maximum Resolution: 7680 x 4320
```



# 2026-0610

* Generación de telemetría de los vuelos simulados con las mismas trayectorias que los reales, a la misma altura y la misma velocidad. 

<img src="informe/2026-0610 Trayectoria vuelos Reales.png"/>

* Vuelo simulado con la trayectoria del Drone 1. Los puntos de las trayectorias están redondeados a múltiplos de 5.
```
takeoff
move(0,0,-30,5)
move(245,-65,-30,5)
move(30,-45,-30,5)
move(30,95,-30,5)
move(-135,95,-30,5)
move(-135,-45,-30,5)
move(39,-45,-30,5)
move(245,-65,-30,5)
reset
```

* Vuelo simulado con la trayectoria del Drone 2. Los puntos de las trayectorias están redondeados a múltiplos de 5.
```
takeoff
move(0,0,-30,5)
move(50,-75,-30,5)
move(-45,-20,-30,5)
move(95,-20,-30,5)
move(95,-110,-30,5)
move(-100,-110,-30,5)
move(-100,110,-30,5)
move(125,110,-30,5)
move(-45,-20,-30,5)
move(50,-75,-30,5)
reset
```

* Subido video ["AirSim Plugin on UE 5.5 Calibration Flight with Drone 2 trajectory"](https://www.youtube.com/watch?v=xNnIMdziv5g) a YouTube mostrando uno de los vuelos de calibración.
<img src="informe/2026-0610 AirSim Plugin on UE 5_5 Calibration Flight with Drone 2 trajectory.png"/>


# 2026-0605

* Reunión de Avance de Proyecto con Ezequiel para mostrar avances y analizar los resultados de las pruebas realizadas. Acuerdo para poner foco en los experimentos, el sandbox de Airsim con entornos dinámicos parece ser válido para los experimentos a realizar. Objetivo 1 de pipeline reproducible alcanzado, ahora poner foco en experimentos de los objetivo 2 y 3: procesamiento de datos se sensores en tiempo real para tomar decisiones de navegación con la intervención del un SLM; comparar este mecanismo de operación con el de un piloto automático tradicional basad en un FSM.
* Para mejorar la comparación, acuerdo para generar los vuelos simulados con las mismas trayectorias que los reales. Es necesario ver cuál es la velocidad de los vuelos reales porque no está explícita.
* Modificación del Notebool para [consolidar datos de telemtría de drones reales](https://github.com/georgsmeinung/lm-drone/blob/main/callibration_flight/actual_telemetry/consolidate_telemetry.ipynb) para calcular el cambio de velocidad en los tres ejes.
* Análisis de [Variabilidad de Telmetría de Vuelos Simulados vs Drones Reales](https://github.com/georgsmeinung/lm-drone/blob/main/callibration_flight/telemetry_analysis_20260610.ipynb) modificando reporte en notebook de Jupyter para analizar los cambios de velocidad en los tres ejes.

# 2026-0604

* Generado Notebook para [consolidar datos de telemtría de drones reales](https://github.com/georgsmeinung/lm-drone/blob/main/callibration_flight/actual_telemetry/consolidate_telemetry.ipynb)
* Análisis de [Variabilidad de Telmetría de Vuelos Simulados vs Drones Reales](https://github.com/georgsmeinung/lm-drone/blob/main/callibration_flight/telemetry_analysis_20260413.ipynb) generando reporte en notebook de Jupyter con estadísticas descriptivas y pruebas estadísiticas para determinar si existen diferencias significativas entre las distribuciones de los datos de telemetría simulados y reales. 
<img src="informe/2026-0413 Trayectorias Comparadas.png"/>

# 2026-0522

* AirSim funcionando en [City Sample](https://fab.com/s/5e8f5eda64d8), ambiente desnamente urbano. Con peatones y tráfico gestionado por IA autónoma de Unreal Engine.
* Airsim funcionando junto el modelo [liquid/lfm2.5-1.2b](https://lmstudio.ai/models/liquid/lfm2.5-1.2b) corriendo en lmstudio.
<img src="informe/2026-0522 Drone en Entorno Urbano.png"/>

# 2026-0521

* Generando nuevo ambiente de pruebas con [Downtown West Modular Pack](https://fab.com/s/be5ea9a2cae4) para ambiente semi urbano con más realismo y configurando Cosys Airsim en el nuevo proyecto. Pruebas OK.
<img src="informe/2026-0521 Drone en Entorno Semi Urbano.png"/>
* Generando nuevo ambiente de pruebas con [City Sample](https://fab.com/s/5e8f5eda64d8) para ambiente desnamente urbano. Configurando Small_City_LVL para no consumir toda la VRAM.

# 2026-0509

* Generando nuevo ambiente de pruebas con [Dynamic City Creator](https://alidocs.dingtalk.com/i/nodes/jb9Y4gmKWrx9eo4dCqAq361yJGXn6lpz) y configurando Cosys Airsim en el nuevo proyecto. El Plugin de Airsim no detecta la red de colisiòn de la ciudad generada paramétricamente.

# 2026-0508

* Probando modelos Edge en la misma PC que corre Unreal Engine con GPU RTX 5060. Considerando:
  - [LFM2.5‑VL-450M](https://huggingface.co/LiquidAI/LFM2.5-VL-450M): Modelo edge de LiquiAI que soporta visión para el procesado de imágenes del drone. No tiene sentido usar esto sólo, un preprocesamiento con YOLO puede ayudar con una segmentación previa con una CNN más rápida. Este modelo es para la navegación y decisiones en tiempo real.
  - [LiquidAI/LFM2.5-1.2B-Thinking](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Thinking):  modelo de 1.200 millones de parámetros que integra un proceso de razonamiento nativo (CoT), permitiéndo superar en lógica y programación a modelos siete veces más grandes. Su mayor ventaja es la eficiencia extrema, ya que requiere menos de 1 GB de RAM en su versión optimizada, lo que facilita la ejecución de agentes autónomos y tareas de código complejas directamente en dispositivos personales sin latencia ni dependencia de la nube. Este modelo es para planificación de la misión de vuelo. Un proceso de razonamiento nativo (o Chain-of-Thought - CoT) es una técnica donde el modelo de IA no responde de inmediato, sino que "piensa en voz alta" internamente antes de dar la respuesta final. Respuesta muy fluida: 224 TPS
  - [google/gemma-4-E4B](https://huggingface.co/google/gemma-4-E4B) con cuantizacion Q4. Implementación de KV Cache optimizada para una ventana de contexto de 32k tokens. Respuesta de 268 TPS
  - [liquid/lfm2-700m](https://huggingface.co/LiquidAI/LFM2-700M-GGUF) con cuantizacion Q4 y 64K de contexto. Respuesta de  344 TPS.

* Prueba de concepto con **LiquidAI/LFM2.5-1.2B** de control de drone, todo en memoria.

# 2026-0507

* Implementando servidor de inferencia en `Ubuntu 26.04 LTS`. Tareas implementar el servidor de inferencia ThinkPad T15 Gen 2 con **Kubuntu**.
* Pruebas con [**google/gemma-4-E4B**](https://huggingface.co/google/gemma-4-E4B) no dan buen rendimiento: menos 7 TPS.
* Considerando modelos Edge para trabajo agéntico, pruebas con:
  - [LiquidAI/LFM2-350M-GGUF](https://huggingface.co/LiquidAI/LFM2-350M-GGUF): LFM2 es una nueva generación de modelos híbridos desarrollados por Liquid AI, diseñados específicamente para IA en el borde y despliegue en dispositivos. Establece un nuevo estándar en términos de calidad, velocidad y eficiencia de memoria. Muy buena velocidad: 60 TPS.
  - [LiquidAI/LFM2-1.2B-GGUF](https://huggingface.co/LiquidAI/LFM2-1.2B-GGUF): LFM2-1.2B-Tool: Un modelo de 1.200 millones de parámetros diseñado específicamente para la llamada de funciones (function calling) y flujos de trabajo de agentes. Según los reportes, compite en ejecución de tareas con modelos mucho más grandes, como Qwen-8B y Gemma-12B. Menos velocidad pero todavia aceptable: 45 TPS.
  

# 2026-0506

* Reconsiderando un entorno distribuido entre dos plataformas para descargar trabajo de la RTX 5060 con VRAM limitada a 8GB, dejando la GPU dedicada a Unreal Engine 5.5 con Cosys Airsim.
* Diseño de Infraestructura de Inferencia de IA Local distribuida con este despliegue

#### Arquitectura de Inferencia Distribuida (Gemma 4 / Iris Xe)
##### 1. Nodo de Inferencia (Headless Server)
- Host: Lenovo ThinkPad T15 Gen 2 (Intel Core i5, Iris Xe 80 EUs).
- OS: Kubuntu (Kernel Linux 6.x / Mesa Drivers con soporte Vulkan anv).
- Memoria: 40 GB DDR4. El modelo se carga en el bloque inicial de 16 GB para aprovechar el Dual-Channel (Flex Memory), minimizando cuellos de botella en el ancho de banda.
- Backend: llmster (vía lms CLI). Ejecución optimizada mediante GPU Offloading (NGL) total sobre la iGPU para liberar ciclos de CPU.
- Modelo:  [**google/gemma-4-E4B**](https://huggingface.co/google/gemma-4-E4B) con cuantizacion Q8_0. Implementación de KV Cache optimizada para una ventana de contexto de 32k tokens.

##### 2. Capa de Aplicación y Red
- Protocolo: API REST compatible con OpenAI (v1) expuesta en 0.0.0.0:1234.
- Orquestación: Despliegue de Open WebUI mediante contenedor Docker en el host de Windows 11, vinculado al endpoint remoto por LAN.
- Integración IDE: Conexión vía OpenCode / VS Code para telemetría y generación de código local (Local Code-Reviewer).

##### 3. Implementación Agéntica
- Framework: OpenClaw o CreoAI para ejecución de herramientas locales y Gemini CLI (MCP) como fallback híbrido para contextos extensos (128k+).
- Control de Potencia: Configuración de perfil de energía performance en Linux para evitar el throttling térmico del SoC durante la inferencia sostenida.

# 2026-0504

* Intento de desplegar entorno en Linux con Unreal Engine for Linux
* El entorno es muy inestable

# 2026-0415

* Generado una versión más avanzada de control por teclado
* Cambiando modo de control por teclado a posición relativa a la orientación del drone

# 2026-0413

* Reunión avance de Tesis con Ezequiel y determinación de próximos pasos.
* Decargado datos de  telemetría real de drones cuadricópteros en https://zenodo.org/records/15912415
* Creado script de iteración apara generar telemetría automatizada de al menos 100 vuelos simulados
* Generados telemetria de 100 vuelos simulados

# 2026-0409

* Generado script de vuelo de calibración y archivo de comandos
* Ejecutados los 10 primeros vuelos de calibración. Cada vuelo individual tiene la telmetría registrada en un .CSV separado

# 2026-0402

* En preparación para vuelos de calibración, agregada la condicion de reset para detener el `airsim_logger.py` (escritura de telemetría a archivos)

# 2026-0331

* Los modelos Qwen no están interpretando bien los comandos y el Phi 4 no es eficiente. Probando con modelo: [**nvidia/nemotron-3-nano-4b**](https://lmstudio.ai/models/nvidia/nemotron-3-nano-4b)
* Determinada plataforma para calibración: Drone con nvidia/nemotron-3-nano-4b. Funciona mejor sin el modo thinking, para no llenar la ventana de contexto muy rápidamente.

# 2026-0313

* Probando una versión destilada de Claude 4.6 Opus para evitar consumir muchas VRAM: [**Jackrong/Qwen3.5-2B-Claude-4.6-Opus-Reasoning-Distilled-GGUF**](https://huggingface.co/Jackrong/Qwen3.5-2B-Claude-4.6-Opus-Reasoning-Distilled-GGUF) funciona ocupando sólo 1.69 GB con cuantización de 4 bits  y venta de contexto de 8192 tokens.
* Conectado Claude Code con modelo local `Jackrong/Qwen3.5-2B-Claude-4.6-Opus-Reasoning-Distilled-GGUF` corriendo en LMStudio, pero tuve que subir la ventana de contexto a 32768 por la cantidad de system promps que envia Claude.

# 2026-0312

Buscando opciones para mejorar la capacidad agéntica del despliegue sin consumir muchas VRAM. Dado que se está usando una RTX 5060 (8 GB) y se necesita mantener a Unreal Engine funcionando sin problemas, cada megabyte de VRAM cuenta. 
[**Qwen2.5‑Coder‑1.5B‑Instruct**](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF) es una buena opción en este escenario. Con cuantización **Q4\_K\_M**, tiene una huella de aproximadamente **\~1.1 GB**.

**Cómo ajustarlo para que entre en 2 GB (dejando 6 GB para Unreal)**
Para asegurar que el LLM se mantenga estrictamente dentro de 2 GB y no interfiera con la simulación, se usarán estos ajustes específicos en **LM Studio 0.4.1**:

**1. Ventana de contexto** configurada en **8.192 (8k)**. Es crucial habilitar **4‑bit KV Cache (Flash Attention)** en la configuración de LM Studio.  Esto reduce el costo de VRAM de la “memoria” en un **50 %**. Un contexto de 8k en 4‑bit ocupará solo unos **\~150 MB**, mientras que 32k se comería casi **1 GB**.

**2. Offload a GPU** en **Max (todas las capas)**. Si las capas se desbordan a la RAM del sistema (CPU), la velocidad de generación de tokens caerá significativamente, lo que puede hacer que agentes como **Claude Code** haga *timeout* durante tareas complejas.

**3. Estabilidad entre aplicaciones**. En el **Panel de Control de NVIDIA**, setear **“Background Application Max Frame Rate”** para que esté limitado para LM Studio a **20–30 FPS**. Esto evita que la interfaz del LLM compita con Unreal por los recursos de la GPU. 

**Consideraciones adionales: ¿Por qué no usar BitNet aquí?**
Aunque **BitNet (1.58‑bit)** usa aún menos VRAM (**\~0.4 GB**), requiere **bitnet.cpp** o *kernels* especializados. Dado que **LM Studio 0.4.1** todavía no soporta de forma nativa la arquitectura BitNet, se perdería la conveniencia del nuevo endpoint “compatible con Anthropic”. **Qwen 1.5B** es un buen equilibrio entre compatibilidad nativa con LM Studio y bajo consumo de recursos.

**Configuración (PowerShell)**
Una vez que el servidor esté corriendo en el puerto **1234** en LM Studio:
```powershell
# Windows PowerShell
$env:ANTHROPIC_BASE_URL="http://localhost:1234/v1"
$env:ANTHROPIC_API_KEY="lm-studio"
claude
```
Si Unreal Engine empieza a dar lags en el render, revisar el uso de VRAM en la barra inferior de LM Studio. Si supera **1.8 GB**, bajar la ventana de contexto a **4.096**.

* Modelo Qwen2.5‑Coder‑1.5B‑Instruct funcionando correctamente con MCP server de AirSim

# 2026-0310

* Generada una versión funcional del Airsim Drone MCP server
* Pruebas de conexión y funcionamiento del loop de eventos de Airsim y el MCP


# 2026-0304

* Instalado https://huggingface.co/DevQuasar/HuggingFaceTB.SmolLM2-135M-Instruct-GGUF en lmstudio. 
* `HuggingFaceTB/SmolLM2-135M` no es muy bueno interpretando comandos.
* Probando con:
```
Model: Qwen/Qwen2.5-Coder-0.5B-Instruct
Provider: Alibaba
Parameters: 494M
Best Quant: Q8_0 (for this hardware) 
Context: 32768 tokens
Use Case: Code generation and completion
```
* `Qwen/Qwen2.5-Coder-0.5B-Instruct` funciona bien para procesar comandos simples

# 2026-0303

* Determinando mejor llm local con `llmfit`. 
Seleccionado:
```
Model: HuggingFaceTB/SmolLM2-135M
Provider: huggingfacetb
Parameters: 135M
Quantization: Q4_K_M
Best Quant: Q8_0 (for this hardware)
Context: 8192 tokens
Use Case: General purpose text generation
Category: General
Released: 2024-10-31
Runtime: llama.cpp (baseline est. ~1046.7 tok/s)
Installed: No provider running
```

# 2026-0212

### Small Language Models (SLM)

Un **Modelo de Lenguaje Pequeño (SLM)** es una versión ligera de un modelo de lenguaje tradicional, diseñada para operar de manera eficiente en entornos con recursos limitados, como teléfonos inteligentes, sistemas embebidos o computadoras de bajo consumo energético .  

* **Definición Operativa**:  
* Un SLM es un modelo de lenguaje (LM) que **puede instalarse en un dispositivo electrónico de consumo común** 
* Puede realizar inferencias con una **latencia suficientemente baja** para ser práctico al atender las solicitudes de un solo usuario en sistemas de agentes.  
* Un LLM se define como un LM que no es un SLM.  

* **Tamaño y Escala**:  
* Mientras que los Modelos de Lenguaje Grandes (LLMs) tienen cientos de miles de millones, o incluso billones, de parámetros, los SLMs generalmente varían de **1 millón a 10 mil millones de parámetros**. A partir de 2025, se considerarían SLMs la mayoría de los modelos con menos de 10 mil millones de parámetros.  
* Es importante destacar que el término "pequeño" es relativo y se utiliza en comparación con los LLMs más grandes, ya que incluso un modelo de mil millones de parámetros no es "pequeño" por definición absoluta.  

* **Capacidades y Propósito**:  
* Los SLMs son suficientemente potentes para manejar las tareas de modelado de lenguaje de las aplicaciones de agentes.  
* Mantienen capacidades básicas de Procesamiento de Lenguaje Natural (NLP) como generación de texto, resumen, traducción y respuesta a preguntas
.  
* Se afirman como el futuro de la IA agéntica porque son inherentemente más adecuados operacionalmente y necesariamente más económicos para la mayoría de los usos de modelos de lenguaje en sistemas de agentes.  

* **Ventajas Clave**:  
* **Menores requisitos computacionales**: Pueden ejecutarse en laptops de consumo, dispositivos de borde y teléfonos móviles.  
* **Menor consumo de energía**: Modelos eficientes que reducen el uso de energía, haciéndolos más sostenibles.  
* **Inferencia más rápida**: Generan respuestas rápidamente, ideal para aplicaciones en tiempo real.  
* **IA en el dispositivo (On-Device AI)**: No requieren conexión a internet ni servicios en la nube, lo que mejora la privacidad y la seguridad.  
* **Despliegue más económico**: Menores costos de hardware y nube, lo que hace la IA más accesible.  
* **Mayor flexibilidad y personalización**: Son más fáciles de ajustar para tareas específicas de dominio.  
* **Cómo se logran "pequeños"**:  
* **Destilación de conocimiento**: Entrenamiento de un modelo "estudiante" más pequeño utilizando el conocimiento transferido de un modelo "maestro" más grande.  
* **Poda (Pruning)**: Eliminación de parámetros redundantes o menos importantes dentro de la arquitectura de la red neuronal.  
* **Cuantización**: Reducción de la precisión de los valores numéricos utilizados en los cálculos (por ejemplo, convertir números de punto flotante a enteros).  
* **Aplicaciones Comunes**:  
* Chatbots y asistentes virtuales.  
* Generación de código.  
* Traducción de idiomas.  
* Resumen y generación de contenido.  
* Aplicaciones en salud.  
* IoT y computación de borde.  
* Herramientas educativas.

<img src="informe/Guía_de_modelos_lenguaje_SLM.png"/>

### SLMs y la Propensión a Alucinaciones

En cuanto a la propensión a alucinaciones, los Modelos de Lenguaje Grandes (LLMs) son conocidos por el problema de la "alucinación", que se define como la generación de contenido sin sentido o falso en relación con ciertas fuentes.  
En el contexto de los SLMs:

* Un estudio utilizando **HallusionBench**, un benchmark para el razonamiento en modelos de visión-lenguaje, encontró que **los tamaños de modelo más grandes reducían las alucinaciones**. Esto sugiere que, en general, los modelos más pequeños podrían ser más propensos a generar contenido alucinatorio.  
* El análisis del benchmark de alucinaciones AMBER también indicó que el tipo de alucinación varía a medida que cambia el recuento de parámetros en Minigpt-4.  
* Las alucinaciones son un riesgo y una limitación que los SLMs comparten con los LLMs.  
* La investigación futura necesita considerar no solo cómo cambia el total de alucinaciones en los SLMs, sino también cómo el tipo y la gravedad pueden verse influenciados por el tamaño del modelo.

Por lo tanto, existe evidencia que sugiere que los SLMs podrían ser más susceptibles a las alucinaciones debido a su menor tamaño, aunque este es un campo de investigación activo para comprender completamente la relación entre el tamaño del modelo y la naturaleza de las alucinaciones.  

### Analizando la mejor versión de SLM para ejecutar localmente.

* Buscando variaciones de LLM local que requiera poco poder de cómputo de la GPU. Analizando los siguiente modelos con capacidad agéntica con formato GGUF-quantized para llama.cpp o LM Studio:

| Model                          | Size (quant) | Approx. VRAM (full offload) | Strengths for your use-case                          | Why good for strict/grammar-limited output          | Where to get (Hugging Face)                  |
|--------------------------------|--------------|------------------------------|-----------------------------------------------------|-----------------------------------------------------|----------------------------------------------|
| **Qwen3-4B-Instruct** or **Qwen3-7B-Instruct** | ~3–5 GB     | ~2.5–4 GB                   | Excellent reasoning, instruction adherence, function-calling in recent versions | Very good at following format prompts; many 2026 variants support JSON mode well | Qwen/Qwen3-4B-Instruct-GGUF                 |
| **Phi-4-mini-instruct** (or Phi-4 variants)    | ~3–4 GB     | ~2–3.5 GB                   | Microsoft-tuned for high-quality synthetic data; strong on structured tasks | Among the best small models for schema adherence / low-variance output | microsoft/Phi-4-mini-instruct-GGUF          |
| **SmolLM3-3B-Instruct**                        | ~2–3 GB     | ~1.8–3 GB                   | Hugging Face's compact reasoning champ; beats many 4–7B on benchmarks | Compact + instruct-tuned → easy to force rigid formats via system prompt | HuggingFaceTB/SmolLM3-3B-GGUF               |
| **Gemma-3-4B-IT** or similar Gemma-3 small     | ~3 GB       | ~2.5 GB                     | Google-tuned, multimodal-capable but text-strong; good on-device fit | Solid structured output with clear prompting; supports function calling | google/gemma-3-4b-it-GGUF variants          |
| **Ministral-3-3B-Instruct**                    | ~2.5 GB     | ~2 GB                       | Mistral's edge-optimized tiny instruct model        | Designed for constrained/edge use; reliable format following | mistralai/Ministral-3-3B-Instruct-GGUF      |

* Analizando estraregias para hacer determinística la salida del LLM con estrategias como forzar una "gramática limitada" / Formato de salida estricto.  Así se está la opción de utilizar una o más de estas técnicas en  forma local con backends como llama.cpp (LM Studio, Ollama, etc.):

1. **Prompt de sistema + instrucciones estrictas** (la más fácil, con sobrecarga casi nula)  
   - Ejemplo:  
     "Eres un respondedor estricto para MCP. Genera **SOLO** JSON válido que coincida exactamente con este esquema. Sin explicaciones, sin texto adicional, sin markdown. Esquema: { "tool_call": {"name": str, "args": dict}, "response": str o null }. Si no se necesita herramienta, establece tool_call en null. Siempre escapa correctamente las cadenas."  
   - Funciona sorprendentemente bien en modelos Phi/Qwen/SmolLM con cuantización Q4/Q5.

2. **Gramática / GBNF con muestreo restringido** (nativo en llama.cpp, muy confiable)  
   - Define una gramática libre de contexto pequeña (formato GBNF) → obliga a que la salida coincida exactamente (por ejemplo, solo claves específicas, valores enum, sin prosa libre).  
   - llama.cpp lo soporta de forma nativa (y herramientas como LM Studio lo exponen).  
   - Guías/ejemplos: Busca "llama.cpp grammars README" o "GBNF para esquema JSON".  
   - Impacto: Reduce la velocidad de generación en un 10–30 %, pero garantiza un 100 % de salida válida.

3. **Librerías Outlines / Guidance / llguidance** (avanzado, pero potente)  
   - Integra con el servidor de llama.cpp o el servidor local de LM Studio → impone esquemas JSON / regex / gramática personalizada a nivel de token.  
   - Garantiza salida estructurada válida incluso en modelos pequeños.

Para MCP en particular:  
- Muchas implementaciones locales de MCP (por ejemplo, clientes y servidores open-source en GitHub) esperan que el LLM genere llamadas a herramientas en un formato fijo (a menudo estilo Anthropic con XML o JSON).  
- Usa los métodos de restricción anteriores → tu SLM se convierte en un "cerebro MCP" confiable sin divagaciones.

# 2026-0205

* Restaurado configuración para sólo API Python, no se va a implementar STIL por MAVLink hasta calibrar el escenario:
```json
{
  "SeeDocsAt": "https://github.com/Cosys-Lab/Cosys-AirSim/blob/main/docs/settings_example.json",
  "SettingsVersion": 2.0,
  "SimMode": "Multirotor",
  "LocalHostIp": "127.0.0.1",
  "ApiServerPort": 41451,
  "RecordUIVisible": false
}
```
* Prueba de captura de logs de telemetría (en pantalla) en simultaneo con navegación controlada por API

# 2026-0204

* Instalado Docker Desktop para ejecutar PX4 Autopilot
* Instalado container con Autopilot cloando repositorio:
```bash
git clone https://github.com/PX4/PX4-Autopilot.git --recursive
```
* Generado `docker-compose.yml`:
```yaml
services:
  px4_sitl:
      image: px4io/px4-dev-simulation-focal:latest
      container_name: px4_sitl
      privileged: true
      volumes:
        - ./PX4-Autopilot:/src/PX4-Autopilot
      ports:
        - "4560:4560"
        - "14550:14550/udp"
      stdin_open: true # Equivalent to -i
      tty: true        # Equivalent to -t
      working_dir: /src/PX4-Autopilot
      command: bash -c "make px4_sitl_default none_iris"
```
Iniciando contenedor con volumen referenciado al repositorio clonado:

```bash
docker-compose up
```
* Configurado Airsim para hacer de bridge en entre PX4 y QGroundControl
```json
{
  "SeeDocsAt": "https://cosys-lab.github.io/settings/",
  "SettingsVersion": 2.0,
  "LocalHostIp": "127.0.0.1",
  "ApiServerPort": 41451,
  "SimMode": "Multirotor",
  "Vehicles": {
    "PX4": {
      "VehicleType": "PX4Multirotor",
      "UseSerial": false,
      "LockStep": true,
      "UseTcp": true,
      "TcpPort": 4560,
      "QgcHostIp": "127.0.0.1",
      "QgcPort": 14550,
      "Parameters": {
        "NAV_RCL_ACT": 0,
        "NAV_DLL_ACT": 0,
        "COM_OBL_ACT": 1
      }
    }
  },
  "RecordUIVisible": false
}
```
* Secuencia de inicio: 
1. PX4
2. Unreal Engine + Airsim
3. QGroundControl

# 2026-0131

* Instalado QGroudControl para control de misión. 

# 2026-0130

* Optimizado proyecto Unreal Engine para reducir el footprint de VRAM que va a compartir con LLM local: reducción de hasta 40% de uso de VRAM dedicada para dejar lugar a capas críticas para la inferencia rápida: próximo paso prueba de eficiencia con arquitectura MCP completa en local.
Configuración optimizada en [./CityParkSim/Config/DefaultEngine.ini](./CityParkSim/Config/DefaultEngine.ini).

# 2026-0115

* Generado proyecto auxiliar, a partir de un fork, para control de drone desde el teclado https://github.com/georgsmeinung/airsim-drone-kc utilizando la nueva librería `cosysairsim`

# 2026-0109

* Reunión seguimiento con Ezequiel. Acordado calibrar la simulación con un script de vuelo repetido para determinar la varianza usando datos de [telemetría de AirSim en formato PX4/MavLink Logging](https://microsoft.github.io/AirSim/px4_logging/).

# 2026-0108

* Creado servidor MCP para control del drone via prompts
* Creado este repositorio de proyecto: https://github.com/georgsmeinung/lm-drone 
* Instalado LM Studio con el modelo `qwen/qwen3-vl-4b one` para correr modelos de lenguaje localmente y disponibilizarlos con una [API compatible con OpenAI](https://lmstudio.ai/docs/developer/openai-compat)
* Subido video ["Airsim Plugin on UE 5.5 controlled through MCP Server PoC" video"](https://youtu.be/lNdmPKZekkk) a YouTube  mostrando el control del drone a través de un server MCP muy básico disponible en `./python_poc/drone_mcp_server.py` con comunicación STDIO

<img src="informe/2026-0108  Airsim Plugin on UE 5_5 controlled through MCP Server PoC.png"/>

# 2025-1202

* Instalación de [text-gen-webui-3.19](https://github.com/oobabooga/text-generation-webui/releases/tag/v3.19) para ejecutar modelos de lenguaje localmente.

# 2025-1203

* Compilación del [Plugin Airsim](https://github.com/Cosys-Lab/Cosys-AirSim). Abandonado el proyecto original [AirSim por Microsoft](https://github.com/microsoft/AirSim), se utiliza la actual versión a partir de un fork mantenido por el [Cosys-Lab](https://www.uantwerpen.be/en/research-groups/cosys-lab/): Laboratorio de Co-Diseño para Sistema Ciber-físicos de la Universidad de Ambéres en Bélgica
* Incorporación del Plugin al proyecto [CityParkSim](https://drive.google.com/drive/folders/1ImTngQAt0gAlrXNOfOYs5csRWQt3IhS_?usp=sharing) configurado para utilizar [Unreal Engine 5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-5-documentation?application_version=5.5)
* Subido video ["Airsim Plugin on UE 5.5 controlled by Python PoC video"](https://youtu.be/4ykS1tUelrY) a YouTube mostrando el control del drone desde un script de Phython.
<img src="informe/2025-1203 Airsim Plugin on UE 5_5 controlled by Python PoC video.png"/>

# 2025-0912

* [Reunión de organización con Ezequiel](./follow_up/2025-0912-objetivo_1.md)

# 2025-0829

* Aprobación de [Plan de Tesis](./plan_tesis/nicolau-plan-aprobado.pdf)
