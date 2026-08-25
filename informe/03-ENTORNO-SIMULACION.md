# 3. Construcción y validación del entorno de simulación

## 3.1 Arquitectura de simulación: Unreal Engine 5.5 y Cosys-AirSim

El desarrollo y la validación de este trabajo se realizan, tal como preveía el plan de trabajo
aprobado (`plan_tesis/plan-tesis.md`), sobre AirSim, un simulador basado en Unreal Engine que ofrece
física y renderizado de alta fidelidad (Shah et al., 2017). La implementación efectiva, sin embargo,
no usa la distribución original de AirSim de Microsoft: desde el inicio del proyecto se adoptó
**Cosys-AirSim**, un fork mantenido por el Cosys-Lab (Laboratorio de Co-Diseño para Sistemas
Ciber-Físicos de la Universidad de Amberes, Bélgica). El propio historial del proyecto documenta la
decisión: *"Abandonado el proyecto original AirSim por Microsoft, se utiliza la actual versión a
partir de un fork mantenido por el Cosys-Lab"* (`CHANGELOG.md`, 2025-12-03), compilado e integrado
sobre un primer proyecto de Unreal Engine 5.5 (`CityParkSim`) que sirvió de entorno inicial de
desarrollo y pruebas.

Cosys-AirSim, a diferencia del AirSim clásico de Microsoft —enfocado principalmente en cámaras RGB y
visión por computadora—, agrega sensores adicionales basados en GPU y CPU (LiDAR, sonar, radar),
documentados en el paper oficial de la plataforma (Jansen et al., 2023). Este trabajo no usa esos
sensores adicionales: la percepción descrita en el capítulo 5 depende exclusivamente de la cámara RGB
monocular y de la telemetría de actitud, consistente con la restricción de hardware de bajo costo que
motiva todo el proyecto (§1.2). La elección de Cosys-AirSim sobre el AirSim original responde, de
todos modos, a la actividad de mantenimiento del fork más que a una necesidad de esos sensores
adicionales: hacia 2025-2026 el proyecto de Microsoft dejó de recibir actualizaciones activas, y la
documentación, configuración y versiones del fork de Cosys-Lab fueron revisadas explícitamente antes
de adoptarlo (`CHANGELOG.md`, 2026-0624).

## 3.2 Desvío respecto del plan aprobado: de la fotogrametría de Buenos Aires a activos urbanos genéricos

El plan de trabajo aprobado describía un pipeline de digitalización de entornos urbanos específico:
extraer fotogramas de videos públicos de drones en Buenos Aires (YouTube), filtrarlos para asegurar
diversidad visual, anotar obstáculos y zonas de aterrizaje con LabelImg/LabelMe, y reconstruir modelos
3D hiperrealistas con RealityCapture (fotogrametría) a partir de esos videos y de OpenStreetMap,
optimizados en Blender para reducir su complejidad computacional antes de importarlos a AirSim
(`plan_tesis/plan-tesis.md`, §"Metodología"). El objetivo declarado era un entorno virtual 3D
*personalizado* de Buenos Aires, con las particularidades geométricas de su infraestructura densa.

La implementación efectivamente construida sustituyó ese pipeline de fotogrametría por activos
urbanos genéricos ya disponibles para Unreal Engine (marketplace de Fab/Epic Games y paquetes de
terceros), configurados con el plugin de Cosys-AirSim en lugar de reconstruidos a partir de video real
de Buenos Aires:

- **`CityParkSim`** (2025-12-03): el proyecto inicial sobre el que se integró y probó el plugin de
  Cosys-AirSim, usado como entorno de desarrollo durante buena parte del proyecto (incluye los
  manifiestos de misión reutilizados para los escenarios `manhattan_a`/`manhattan_b` del capítulo 9).
- **"City Sample"** (Epic Games, vía Fab): entorno dedicadamente urbano denso, con peatones y tráfico
  gestionado por IA autónoma de Unreal Engine, confirmado funcionando con Cosys-AirSim el 2026-0522 y
  optimizado el 2026-0622 (escena `Small_City_LVL`) siguiendo las recomendaciones oficiales de Epic
  para sistemas de especificación más baja.
- **"Downtown West Modular Pack"**: entorno semi-urbano con mayor nivel de detalle arquitectónico,
  configurado el 2026-0521 como alternativa de mayor realismo visual al `CityParkSim` inicial.
- **"Dynamic City Creator"** (2026-0509): un intento de generar un entorno urbano paramétricamente en
  lugar de usar un activo fijo, **abandonado**: el plugin de Cosys-AirSim no detectaba correctamente
  la malla de colisión de la ciudad generada de esta forma (`CHANGELOG.md`, 2026-0509), lo que la
  hacía inutilizable para vuelo con evasión de obstáculos.

El historial del proyecto no deja registrada una justificación explícita, en el momento del cambio,
de por qué se sustituyó el pipeline de fotogrametría de Buenos Aires por estos entornos genéricos; se
documenta aquí como un desvío de hecho respecto del plan aprobado, en el mismo sentido en que el
capítulo 1 (§1.3) documenta el desvío en percepción: verificable contra el registro del proyecto, sin
inventar una razón que ese registro no sostiene. Una lectura razonable, aunque no confirmada
explícitamente en el `CHANGELOG.md`, es que los entornos ya disponibles con tráfico y peatones
gestionados por IA (como "City Sample") resolvían una necesidad —escenas urbanas dinámicas para
ejercitar evasión de obstáculos— sin el costo del pipeline de reconstrucción fotogramétrica completo;
esa lectura queda señalada como interpretación, no como hecho documentado.

## 3.3 Configuración de rendimiento: gráficos frente a física

La documentación oficial de Cosys-Lab, revisada explícitamente durante el proyecto (`CHANGELOG.md`,
2026-0622, 2026-0624), sostiene que priorizar la tasa de actualización de la física y los sensores
activos por sobre la fidelidad gráfica es una práctica recomendada cuando el objetivo principal no es
la fotografía de la escena. Siguiendo esas recomendaciones, se aplicaron los siguientes ajustes:

- Desactivar el ahorro de CPU en segundo plano del editor de Unreal Engine (`Use Less CPU when in
  Background`), que de otro modo degrada drásticamente la tasa de refresco de la física apenas la
  ventana pierde el foco.
- Ajustar `ClockSpeed` en `settings.json` para desacelerar el tiempo de simulación cuando la carga
  gráfica hace caer los cuadros por segundo, dando margen a que la física se calcule de forma
  sincronizada.
- Preferir binarios empaquetados (*standalone*) sobre la ejecución directa desde el editor de Unreal
  Engine, que consume recursos adicionales de memoria y GPU para la propia interfaz de desarrollo.

El modo `NoDisplay` (que anula por completo el renderizado de pantalla cuando solo se necesitan
telemetría y datos de sensores) no se utilizó: la captura de imágenes RGB es central a la percepción
monocular de este trabajo (capítulo 5), por lo que el renderizado de la cámara no puede desactivarse.
Por el mismo motivo, no se redujo la calidad de texturas del entorno, aunque sí se redujo el
posprocesamiento de renderizado cinemático en escenas con mayor exigencia gráfica (como "City
Sample"), como concesión intermedia entre realismo visual y presupuesto de cómputo compartido con la
inferencia del modelo de lenguaje local (§7.1).

## 3.4 Validación frente a telemetría de vuelos reales

La dinámica de vuelo simulada —no la geometría de la escena urbana, cuya fidelidad fotográfica es el
desvío documentado en §3.2— se validó de forma independiente contra telemetría de drones reales, con
el objetivo explícito de que la comparación experimental entre brazos (capítulo 9) se apoyara en
vuelos simulados cuya cinemática fuera comparable a la de un cuadricóptero real y no solo
físicamente plausible en abstracto.

**Fuente de datos reales.** Se descargó un conjunto de datos de telemetría real de drones
cuadricópteros comerciales (DJI) desde el repositorio público de Zenodo
(<https://zenodo.org/records/15912415>, `CHANGELOG.md`, 2026-0413).

**Protocolo de calibración.** Sobre esa telemetría real se identificaron dos trayectorias de vuelo
distintas —un patrón rectangular simple (Drone 1) y un patrón de cruz combinado con rectángulo (Drone
2)— y se reprodujeron en simulación con `moveOnPath`/`move` de la API de AirSim, ajustando la
simulación a la misma altura y la misma velocidad que los vuelos reales correspondientes. El proceso
se iteró varias veces a lo largo del proyecto: una primera generación automatizada de telemetría de
100 vuelos simulados (2026-0413) para poner a punto el script de iteración; una serie de 10 vuelos de
calibración con telemetría registrada en archivos CSV individuales (2026-0409); una repetición con
trayectorias explícitamente ajustadas a la altura y velocidad de los vuelos reales (2026-0610); y una
iteración final (2026-0627/2026-0628) que reemplazó los comandos de movimiento discretos por
`moveOnPath` con la trayectoria completa como un único comando, para acercar el perfil de aceleración
simulado al de un vuelo real continuo en lugar de una secuencia de tramos independientes.

![Trayectorias de vuelos reales usadas como referencia](2026-0610%20Trayectoria%20vuelos%20Reales.png)

**Metodología estadística.** El análisis se implementó en notebooks de Jupyter del repositorio
complementario del proyecto (`consolidate_telemetry.ipynb` y `telemetry_analysis_*.ipynb`,
[georgsmeinung/lm-drone](https://github.com/georgsmeinung/lm-drone)), con estadística descriptiva y
pruebas de significancia —en particular la prueba de Levene para diferencia de varianzas— aplicadas al
cambio de velocidad en los tres ejes, para determinar si la distribución de la telemetría simulada
difiere de forma significativa de la real.

**Resultado.** Las corridas de análisis (2026-0604 a 2026-0628) documentan tres hallazgos
consistentes:

1. **La varianza de actitud difiere de forma significativa** (prueba de Levene, p ≪ 0,05): en
   simulación, el dron ejecuta inclinaciones de *roll*/*pitch* extremas durante los giros rápidos para
   alcanzar instantáneamente el punto de trayectoria siguiente. Los drones reales, en cambio, están
   limitados electrónicamente por su controlador PID de estabilización (típicamente a ±30°), y
   muestran una varianza mucho menor y acotada durante las mismas maniobras.
2. **La segregación por trayectoria es significativa y consistente.** El Drone 1 (patrón rectangular,
   giros menos frecuentes) concentra la aceleración en las esquinas; el Drone 2 (patrón de cruz y
   rectángulo continuo) presenta una dinámica transicional más exigente y oscilaciones de *roll*/
   *pitch* más ruidosas, tanto en el vuelo real como en el simulado.
3. **El vuelo simulado en tramos rectos es idealizado.** Durante las fases rectas, la telemetría
   simulada muestra varianza de actitud cercana a cero, sin fuerzas externas de viento ni ruido de
   sensores; el dron real, en cambio, mantiene una variabilidad permanente de ±2°–3° en *roll* y
   *pitch* incluso en tramos rectos estables, producto del viento real y de las correcciones continuas
   del piloto automático.

![Comparación de trayectorias y perfil de velocidad — Drone 1](2026-0627%20Comparaci%C3%B3n%20de%20Pefiles%20de%20velocidad%20-%20Drone%201.png)

![Comparación de trayectorias y perfil de velocidad — Drone 2](2026-0627%20Comparaci%C3%B3n%20de%20Pefiles%20de%20velocidad%20-%20Drone%202.png)

**Alcance de esta validación.** Confirma que la dinámica de vuelo simulada —cómo se mueve el dron dado
un comando— es más ágil y menos amortiguada que la de un dron real equivalente, con una brecha de
idealización conocida y cuantificada (varianza de actitud, ausencia de viento simulado). No valida, en
cambio, la fidelidad fotográfica de la escena urbana frente a Buenos Aires real: esa es una validación
distinta, no realizada, y coincide con el desvío documentado en §3.2. Un ejercicio de validación
relacionado pero diferente —si el suavizado por histéresis y media móvil exponencial introducido en
`WaypointTracker` (capítulo 4, §4.3) mejora medible la telemetría real de vuelo— arrojó un resultado
honestamente ambiguo (`std(Δvx)` prácticamente plano antes/después) y se documenta como tal en el
propio `CHANGELOG.md`, no como una mejora confirmada.
