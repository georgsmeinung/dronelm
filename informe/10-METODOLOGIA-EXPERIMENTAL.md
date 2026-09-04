# 10. Metodología experimental

## 10.1 Diseño experimental

La evaluación compara tres brazos de decisión sobre el mismo `ObstacleField` (cap. 6), el mismo espacio de macro-acciones y el mismo traductor a comandos cinemáticos (`action_to_command`, cap. 8):

- **`slm`** — el modelo de lenguaje multimodal (VLM, típicamente Qwen2.5-VL-3B) como capa táctica y deliberativa (cap. 8). Durante la espera de respuesta del modelo, el sistema aplica un avance cauto a velocidad reducida (`DELIB_WAIT_CREEP_SPEED_MPS = 0.5 m/s`) en lugar de un frenado total, preservando la traslación necesaria para que el estimador de flujo óptico mantenga confianza; solo se comanda detención total incondicional ante un bloqueo frontal inminente y confirmado (`close_structural`). El modelo delibera de forma asíncrona bajo un watchdog de seguridad con respaldo determinista ante timeout o respuestas no conformes, recibiendo un historial temporal de fotogramas ($t$ y $t-1$), notas cinemáticas (`pitch`, `roll`, velocidad) y el motivo explícito de la consulta.
- **`fsm`** — una máquina de estados finitos explícita (`CRUISE → AVOID_LEFT | AVOID_RIGHT | CLIMB | BRAKE → CRUISE`), con transiciones gobernadas por umbrales fijos sobre el mismo `ObstacleField`. Es la línea de base directa contra la que se evalúa la hipótesis de la tesis: alta predictibilidad y costo computacional mínimo, pero sin capacidad de razonamiento contextual ni interpretación semántica del entorno.
- **`reactive`** — navegación guiada al waypoint sin evasión de obstáculos: cota inferior de rendimiento para desacoplar qué porción del desempeño proviene del lazo táctico de evasión y cuánto del seguimiento cinemático de base.

Adicionalmente, el diseño incorpora como factor experimental cruzado la **estrategia de resolución de atascos** (`DEADLOCK_STRATEGY`, cap. 5), compartida por los brazos `slm` y `fsm`:
- **`blind`**: maniobra reactiva de escape cinemático tradicional (ganancia de altura o rotaciones de desenganche en bucle abierto).
- **`deep_vlm`**: barrido panorámico espacial multifotograma ejecutado dentro del lazo y consulta deliberativa al VLM para identificar visualmente un corredor despejado antes de forzar el escape ciego como último recurso.

### Escenarios de prueba y jerarquía de Tiers

Superando las formulaciones exploratorias preliminares (como los borradores `manhattan_a` y `manhattan_b`, descartados por inconsistencias topográficas y de mapas en el simulador), el protocolo define una jerarquía formal en tres niveles crecientes de dificultad ambiental:

- **Tier 0 (Línea de base / Control):** Escenario `minisim_clear` sobre el mapa `crater.png` (MiniSim). Terreno despejado sin obstáculos para cuantificar el guiado puro, la cota inferior de latencia de ciclo y el consumo cinemático ideal.
- **Tier 1 (Entorno intermedio / Vegetación y morfología orgánica):** Escenarios sobre el mapa `townsim_calib.png` (TownSim), abarcando la suite de pruebas `T-CALIB-0` a `T-CALIB-5` y la misión de recorrido perimetral `townsim_ini`. Incluye específicamente el escenario `T-CALIB-2` (`townsim_calib_cruce_frontal.json`), diseñado para imponer un **bloqueo frontal masivo genuino** frente a una fachada continua, forzando la activación de las ramas deliberativas y de resolución de atascos.
- **Tier 2 (Entorno complejo / Cañones urbanos y corredores angostos):** Escenarios sobre `citymap.png` (CitySim, ej. `citymap_pilot.json` y `citymap_a.json`), con edificaciones de gran altura, mobiliario urbano denso y pasos restringidos tipo cuadrícula.

Como principio metodológico estricto, **se descarta el teletransporte cinemático** (`start_pose` inhabilitado): todas las misiones despegan desde el *PlayerStart* nativo del nivel en Unreal Engine y ejecutan un ascenso vertical controlado previo a la navegación horizontal. A partir de las velocidades medidas en vuelo real (~2 a 3 m/s) y la cadencia táctica (5 Hz), el presupuesto temporal por corrida se dimensiona entre **600 y 900 segundos** para permitir la resolución completa de tramos complejos sin truncamiento artificial.

El criterio de arranque para el batch completo exige la validación previa de misiones piloto exitosas (`success = True`, 0 colisiones) en cada nivel. Se ejecutan al menos **cinco semillas por celda factorial** ($\text{Brazo} \times \text{Estrategia de Atasco} \times \text{Tier}$) mediante el runner automatizado headless (`experiments/runner.py`).

## 10.2 Métricas reportadas

El sistema registra y evalúa las siguientes métricas cuantitativas:

- **Eficacia y seguridad de vuelo:**
  - Tasa de éxito de misión (`success_rate`, arribo a todos los waypoints dentro del presupuesto).
  - Tasa de colisiones totales por misión y normalizadas por kilómetro recorrido.
  - Distancia mínima a obstáculo, percentil 5 (`min_obstacle_dist_m`), medida mediante el canal de profundidad a cadencia reducida con guardia arquitectónica de no contaminación sobre el lazo de control (cap. 5).
  - SPL (*Success weighted by Path Length*): éxito ponderado por la razón entre la longitud de la trayectoria óptima y la efectivamente recorrida.
  - Tiempo y ciclos totales a destino.
- **Dinámica del lazo táctico y latencias:**
  - Latencia total por ciclo ($p50$ y $p95$), desagregada por brazo y por nodo activo del grafo de control (`reactive`, `evasive`, `deliberative`, `girar_90`, `fsm`, `spatial_scan`, `deep_scan`).
  - `deliberation_rate` (fracción de ciclos tácticos que invocan activamente al modelo de lenguaje) e histograma integral de rutas por corrida.
- **Comportamiento del modelo de lenguaje (SLM/VLM):**
  - Número de invocaciones efectivas por misión (contabilizadas por transición de identificador único).
  - Tasa de *fallback* determinista ante respuestas inválidas o fuera de esquema.
  - Tasa de *timeout* del watchdog asíncrono.
  - Tasa de adherencia sintáctica (`adherence_rate`), con y sin decodificación gramatical estructurada
    (§8.2).
- **Resolución de atascos (Ablation H2/H3):**
  - Tasa de resolución de atascos mediante escaneo profundo (`deep_scan_resolution_rate`).
  - Promedio de ciclos consumidos para resolver el atasco (`deep_scan_avg_cycles_to_resolve`).
  - Tasa de caída a escape ciego de respaldo (`deep_scan_fallback_rate`).
- **Desglose espacial por Waypoint:**
  - Métricas segmentadas por tramo de misión (`<stem>.summary_by_wp.csv`), permitiendo aislar el comportamiento en tramos de ascenso inicial vertical de las fases de crucero y maniobra horizontal.

## 10.3 Protocolo estadístico

La comparación entre brazos y configuraciones se realiza mediante pruebas no paramétricas (prueba U de Mann-Whitney para comparaciones pareadas y Kruskal-Wallis para factores múltiples) calculadas sobre las distribuciones de las semillas de cada combinación, reportando además el tamaño de efecto (Cliff's Delta o correlación de rango biserial). 

El análisis no se limita a valores agregados globales, sino que evalúa el rendimiento **desagregado por tipo de escenario y morfología de obstáculo**. Esta formulación permite discernir con precisión cuándo la capacidad de interpretación contextual del VLM proporciona ventajas medibles (por ejemplo, al anticipar salidas en pasajes bloqueados o seleccionar corredores abiertos entre vegetación) y en qué situaciones una heurística rígida (FSM) alcanza un rendimiento equivalente a una fracción mínima del costo computacional.

## 10.4 Reproducibilidad, auditoría y cuarentena de datos

El subsistema de registro (`src/logging/flight_logger.py`, `flight_video.py`, `flight_viewer.py`) genera por cada misión un directorio autónomo de auditoría (`airsim-runs/<mission_id>-<timestamp>/`) que comprende:

1. **Telemetría granular:** Archivo `JSONL` estructurado ciclo a ciclo y archivo `CSV` correspondiente para análisis tabular directo.
2. **Resúmenes agregados:** `summary.json` con los indicadores globales de la corrida y `summary_by_wp.csv` con el desglose por waypoint.
3. **Auditoría visual forense del VLM:** Almacenamiento individual en formato `PNG` (`photo-<timestamp_ISO>.png`) de cada fotograma exacto presentado al modelo, preservando el timestamp de captura real y evitando discrepancias de inferencia.
4. **Grabación de video continua sincronizada:** Archivo `.webm` (códec VP8 sin dependencias de licencias propietarias) grabado a la tasa nominal `LOOP_HZ`, con superposición en pantalla de la telemetría cinemática, lecturas sectoriales de TTC y el nodo activo del grafo.
5. **Visor interactivo offline (`viewer.html`):** Aplicación web embebida en la carpeta de la corrida que vincula un deslizador temporal con el video y la tabla de telemetría, permitiendo inspeccionar sincronizadamente el prompt textual, los fotogramas y la respuesta del modelo en cada decisión.

**Trazabilidad y cuarentena experimental:** Cada corrida incorpora automáticamente el hash de commit de Git (`code_version`) en `summary.json`. Para garantizar la validez científica de los resultados, se establece una **política estricta de cuarentena**: ningún vuelo anterior al 2026-09-03 se incluye en el análisis estadístico formal del capítulo 11, dado que los registros previos estuvieron expuestos a artefactos instrumentales ya corregidos (inversión de canales de color R/B en la captura, persistencia de líneas de depuración en el visor 3D y supresión espuria de los ángulos de *pitch* y *roll*).

El conjunto de validación de TTC (cap. 7), junto con los archivos de telemetría y configuración del batch definitivo, serán archivados y publicados con un identificador digital persistente (DOI vía Zenodo), garantizando la completa auditabilidad y reproducibilidad de la tesis.
