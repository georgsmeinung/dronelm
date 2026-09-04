# 3. Construcción y validación del entorno de simulación

## 3.1 Arquitectura de simulación: Unreal Engine 5.5 y Cosys-AirSim

El desarrollo y la validación de este trabajo se realizan, tal como preveía el plan de trabajo aprobado (`plan_tesis/plan-tesis.md`), sobre AirSim, un simulador basado en Unreal Engine que ofrece física y renderizado de alta fidelidad (Shah et al., 2017). La implementación efectiva, sin embargo, no usa la distribución original de AirSim de Microsoft: desde el inicio del proyecto se adoptó **Cosys-AirSim**, un fork mantenido por el Cosys-Lab (Laboratorio de Co-Diseño para Sistemas Ciber-Físicos de la Universidad de Amberes, Bélgica). Al inicio del desarrollo se adoptó la decisión de utilizar este fork: *"Abandonado el proyecto original AirSim por Microsoft, se utiliza la actual versión a partir de un fork mantenido por el Cosys-Lab"*, compilado e integrado sobre proyectos de Unreal Engine 5.5 que sirvieron como banco de pruebas y validación experimental.

Cosys-AirSim, a diferencia del AirSim clásico de Microsoft —enfocado principalmente en cámaras RGB y visión por computadora—, agrega sensores adicionales basados en GPU y CPU (LiDAR, sonar, radar), documentados en el paper oficial de la plataforma (Jansen et al., 2023). Este trabajo no usa esos sensores adicionales: la percepción descrita en el capítulo 6 depende exclusivamente de la cámara RGB monocular y de la telemetría de actitud, consistente con la restricción de hardware de bajo costo que motiva todo el proyecto (§1.2). La elección de Cosys-AirSim sobre el AirSim original responde, de todos modos, a la actividad de mantenimiento del fork más que a una necesidad de esos sensores adicionales: hacia 2025-2026 el proyecto de Microsoft dejó de recibir actualizaciones activas, y la documentación, configuración y versiones del fork de Cosys-Lab fueron revisadas exhaustivamente antes de adoptarlo.

**Particularidades de la API y telemetría de actitud.** Una diferencia relevante descubierta durante la integración radica en la interfaz en Python: a diferencia del paquete clásico `airsim`, el binding `cosysairsim` no expone la función auxiliar `to_eularian_angles` para la extracción directa de ángulos de actitud. La ausencia de este método provocó que los fallbacks iniciales reportaran *pitch* y *roll* en $0.0^\circ$ de forma permanente. Para subsanar esta omisión sin introducir dependencias externas complejas, se implementó en el cliente de simulación (`AirSimClient._quaternion_to_euler`) la conversión matemática directa de cuaterniones a ángulos de Euler en convención aeroespacial NED (North-East-Down), asegurando que las variaciones de inclinación del cuadricóptero alimenten con fidelidad continua la telemetría del lazo táctico y el contexto del modelo deliberativo.

## 3.2 Desvío respecto del plan aprobado: de la fotogrametría de Buenos Aires a activos urbanos genéricos

El plan de trabajo aprobado describía un pipeline de digitalización de entornos urbanos específico: extraer fotogramas de videos públicos de drones en Buenos Aires (YouTube), filtrarlos para asegurar diversidad visual, anotar obstáculos y zonas de aterrizaje con LabelImg/LabelMe, y reconstruir modelos 3D hiperrealistas con RealityCapture (fotogrametría) a partir de esos videos y de OpenStreetMap, optimizados en Blender para reducir su complejidad computacional antes de importarlos a AirSim (`plan_tesis/plan-tesis.md`, §"Metodología"). El objetivo declarado era un entorno virtual 3D *personalizado* de Buenos Aires, con las particularidades geométricas de su infraestructura densa.

La implementación efectivamente construida sustituyó ese pipeline de fotogrametría por activos urbanos y suburbanos ya disponibles para Unreal Engine (marketplace de Fab/Epic Games y paquetes de terceros), configurados con el plugin de Cosys-AirSim en lugar de reconstruidos a partir de video real de Buenos Aires (disponibles en el repositorio compartido de Google Drive: <https://drive.google.com/drive/folders/1roLmbGFNsHXZyT3NaNzNYMuaBQ8CulX7>).

### Entornos principales estructurados por Tiers de evaluación

Para responder con rigor al protocolo experimental de la tesis (capítulo 10), los entornos de simulación se organizaron en una **jerarquía formal de tres niveles de complejidad (Tiers)**, superando los primeros borradores preliminares de misión (`manhattan_a` y `manhattan_b`, descartados y alineados a esta nueva nomenclatura):

1. **Tier 0 — Base / Control (`MiniSim`):** Entorno abierto basado en el mapa `crater.png` (`Landscape Mountains`). Diseñado para pruebas de calibración cinemática, sintonización de controladores de posición y determinación de la cota inferior de latencia del sistema sin interferencia de obstáculos.

2. **Tier 1 — Intermedio / Morfología orgánica y vegetación (`TownSim`):** Entorno semiurbano desarrollado sobre `townsim.png` y refinado en el mapa calibrado `townsim_calib.png`. Presenta calles de ancho variable, fachadas intermedias, mobiliario y arboledas densas. Constituye el banco de pruebas central para la batería de calibración `T-CALIB-0` a `T-CALIB-5` y la misión de recorrido perimetral `townsim_ini`, albergando el escenario de bloqueo frontal masivo genuino (`T-CALIB-2`).

3. **Tier 2 — Complejo / Cañones urbanos de gran densidad (`CitySim` / `CityParkSim`):** Proyecto de Unreal Engine 5.5 con tejido edilicio masivo (`citymap.png`), rascacielos, pasos restringidos y disposición en cuadrícula ortogonal. Aloja las misiones de estrés en corredores angostos (`citymap_pilot.json` y `citymap_a.json`).

### Entornos adicionales evaluados en fases exploratorias

Junto a los tres Tiers principales, se evaluaron otras alternativas durante el desarrollo:
- **"City Sample"** (Epic Games, vía Fab): entorno dedicadamente urbano denso, con peatones y tráfico gestionado por IA autónoma de Unreal Engine, confirmado funcionando con Cosys-AirSim el 2026-0522 y optimizado el 2026-0622 (escena `Small_City_LVL`) siguiendo las recomendaciones oficiales de Epic para sistemas de especificación más baja.
- **"Downtown West Modular Pack"**: entorno semiurbano con mayor nivel de detalle arquitectónico, configurado el 2026-0521 como alternativa de mayor realismo visual al entorno base.
- **"Dynamic City Creator"** (2026-0509): intento de generar un entorno urbano paramétricamente, **abandonado** debido a que Cosys-AirSim no detectaba adecuadamente la malla de colisión de las geometrías generadas proceduralmente, invalidando la detección física de obstáculos.

El historial del proyecto no deja registrada una justificación explícita de por qué se sustituyó la fotogrametría de Buenos Aires por estos entornos; se documenta aquí como un desvío de hecho respecto del plan aprobado, en el mismo sentido en que el capítulo 1 (§1.3) documenta el desvío en percepción. Una lectura razonable es que los activos preexistentes resolvían de forma inmediata la necesidad de geometrías urbanas complejas con colisiones operativas, ahorrando el enorme costo técnico y temporal del pipeline de reconstrucción fotogramétrica.

## 3.3 Configuración de rendimiento, escalabilidad gráfica e higiene de captura

La documentación técnica de Cosys-Lab sostiene que priorizar la tasa de actualización de la física por sobre la fidelidad gráfica es una práctica recomendada cuando el objetivo principal no es la fotografía cinemática de la escena. Siguiendo esas directrices y considerando que la misma estación de cómputo aloja en simultáneo el renderizado 3D y la inferencia del modelo de lenguaje local (§8.1), se establecieron los siguientes compromisos de arquitectura:

- Desactivar el ahorro de CPU en segundo plano del editor de Unreal Engine (`Use Less CPU when in Background`), evitando caídas drásticas en el refresco de la física cuando la ventana del simulador pierde el foco.
- Ajustar `ClockSpeed` en `settings.json` para sincronizar el tiempo de simulación y garantizar que el lazo físico se calcule sin pérdidas temporales cuando la carga gráfica fluctúa.
- Preferir binarios empaquetados (*standalone*) sobre la ejecución directa desde el editor, reduciendo la sobrecarga de memoria VRAM asociada a la interfaz de desarrollo.
- El modo `NoDisplay` no pudo utilizarse, dado que la captura de imágenes RGB monocular es estrictamente indispensable para la percepción del dron (capítulo 6).

### Escalabilidad gráfica en Unreal Engine 5.5

Para equilibrar la carga de GPU entre Unreal Engine y el servidor SLM/VLM local, se definió un perfil de escalabilidad mínima (*Minimal Scalability Config*) que fija sombras, postprocesamiento e iluminación global en niveles bajos (`Low`/`Medium`), reservando la VRAM necesaria para los pesos del modelo multimodal.

Sin embargo, en Unreal Engine 5.5 la reducción automática de efectos suele degradar la resolución de los render targets de captura de escena. Para evitar que la cámara frontal pierda nitidez o altere el cálculo de flujo óptico, se forzó el nivel de detalle en el archivo `Config/DefaultScalability.ini` del proyecto Unreal:

```ini
[EffectsQuality@0]
r.DetailMode=2
[EffectsQuality@1]
r.DetailMode=2
[EffectsQuality@2]
r.DetailMode=2
[EffectsQuality@3]
r.DetailMode=2
[EffectsQuality@Cine]
r.DetailMode=2
```

![Configuración mínima de escalabilidad en Unreal Engine](2026-0831%20Minimal%20Scalability%20Config%20for%20Airsim.png)

### Higiene y consistencia de la captura monocular

Durante la experimentación continua en simulación se identificaron y resolvieron dos anomalías instrumentales críticas en el canal visual:

1. **Inversión de canales de color (RGB vs. BGR):** El buffer crudo devuelto por `simGetImages(ImageType.Scene)` en Cosys-AirSim es entregado en formato RGB. No obstante, el ecosistema de procesamiento de OpenCV y las rutinas de compresión asumían internamente la convención BGR. Como consecuencia, las capturas enviadas al VLM y guardadas en auditoría mostraban una tonalidad azulada con rojo y azul invertidos. La anomalía se corrigió de forma definitiva en el propio método `AirSimClient.capture()`, asegurando que el modelo de lenguaje razone sobre los colores naturales de la escena (pavimento, vegetación y cielo).
2. **Supresión de marcadores de depuración persistentes:** Primitivas geométricas dibujadas en el mundo virtual por scripts de planificación (mediante `simPlotLineStrip` y `simPlotPoints` de `plot_mission_route.py`) permanecían activas en el nivel y eran capturadas por la cámara a bordo, siendo interpretadas por el VLM como obstáculos físicos reales. Se implementó una rutina de higiene obligatoria (`AirSimClient.clear_debug_markers()`, invocando `simFlushPersistentMarkers()`) al inicio de cada sesión de conexión.

## 3.4 Validación frente a telemetría de vuelos reales

La dinámica de vuelo simulada —no la geometría de la escena urbana, cuya fidelidad fotográfica es el desvío documentado en §3.2— se validó de forma independiente contra telemetría de drones reales, con el objetivo explícito de que la comparación experimental entre brazos (capítulo 10) se apoyara en vuelos simulados cuya cinemática fuera comparable a la de un cuadricóptero real y no solo físicamente plausible en abstracto.

**Fuente de datos reales.** Se descargó un conjunto de datos de telemetría real de drones cuadricópteros comerciales (DJI) desde el repositorio público de Zenodo (<https://zenodo.org/records/15912415>).

**Protocolo de calibración.** Sobre esa telemetría real se identificaron dos trayectorias de vuelo distintas —un patrón rectangular simple (Drone 1) y un patrón de cruz combinado con rectángulo (Drone 2)— y se reprodujeron en simulación con `moveOnPath`/`move` de la API de AirSim, ajustando la simulación a la misma altura y la misma velocidad que los vuelos reales correspondientes. El proceso se iteró varias veces a lo largo del proyecto: una primera generación automatizada de telemetría de 100 vuelos simulados (2026-0413) para poner a punto el script de iteración; una serie de 10 vuelos de calibración con telemetría registrada en archivos CSV individuales (2026-0409); una repetición con trayectorias explícitamente ajustadas a la altura y velocidad de los vuelos reales (2026-0610); y una iteración final (2026-0627/2026-0628) que reemplazó los comandos de movimiento discretos por `moveOnPath` con la trayectoria completa como un único comando, para acercar el perfil de aceleración simulado al de un vuelo real continuo en lugar de una secuencia de tramos independientes.

![Trayectorias de vuelos reales usadas como referencia](2026-0610%20Trayectoria%20vuelos%20Reales.png)

**Metodología estadística.** El análisis se implementó en notebooks de Jupyter del repositorio complementario del proyecto (`consolidate_telemetry.ipynb` y `telemetry_analysis_*.ipynb`, [georgsmeinung/lm-drone](https://github.com/georgsmeinung/lm-drone)), con estadística descriptiva y pruebas de significancia —en particular la prueba de Levene para diferencia de varianzas— aplicadas al cambio de velocidad en los tres ejes, para determinar si la distribución de la telemetría simulada difiere de forma significativa de la real.

**Resultado.** Las corridas de análisis (2026-0604 a 2026-0628) documentan tres hallazgos consistentes:

1. **La varianza de actitud difiere de forma significativa** (prueba de Levene, p ≪ 0,05): en simulación, el dron ejecuta inclinaciones de *roll*/*pitch* extremas durante los giros rápidos para alcanzar instantáneamente el punto de trayectoria siguiente. Los drones reales, en cambio, están limitados electrónicamente por su controlador PID de estabilización (típicamente a ±30°), y muestran una varianza mucho menor y acotada durante las mismas maniobras.
2. **La segregación por trayectoria es significativa y consistente.** El Drone 1 (patrón rectangular, giros menos frecuentes) concentra la aceleración en las esquinas; el Drone 2 (patrón de cruz y rectángulo continuo) presenta una dinámica transicional más exigente y oscilaciones de *roll*/ *pitch* más ruidosas, tanto en el vuelo real como en el simulado.
3. **El vuelo simulado en tramos rectos es idealizado.** Durante las fases rectas, la telemetría simulada muestra varianza de actitud cercana a cero, sin fuerzas externas de viento ni ruido de sensores; el dron real, en cambio, mantiene una variabilidad permanente de ±2°–3° en *roll* y *pitch* incluso en tramos rectos estables, producto del viento real y de las correcciones continuas del piloto automático.

![Comparación de trayectorias y perfil de velocidad — Drone 1](2026-0627%20Comparaci%C3%B3n%20de%20Pefiles%20de%20velocidad%20-%20Drone%201.png)

![Comparación de trayectorias y perfil de velocidad — Drone 2](2026-0627%20Comparaci%C3%B3n%20de%20Pefiles%20de%20velocidad%20-%20Drone%202.png)

**Alcance de esta validación.** Confirma que la dinámica de vuelo simulada —cómo se mueve el dron dado un comando— es más ágil y menos amortiguada que la de un dron real equivalente, con una brecha de idealización conocida y cuantificada (varianza de actitud, ausencia de viento simulado). No valida, en cambio, la fidelidad fotográfica de la escena urbana frente a Buenos Aires real: esa es una validación distinta, no realizada, y coincide con el desvío documentado en §3.2. Un ejercicio de validación relacionado pero diferente —si el suavizado por histéresis y media móvil exponencial introducido en `WaypointTracker` (capítulo 5, §5.3) mejora medible la telemetría real de vuelo— arrojó un resultado honestamente ambiguo (`std(Δvx)` prácticamente plano antes/después) y se documenta como tal en el presente informe, no como una mejora confirmada.
