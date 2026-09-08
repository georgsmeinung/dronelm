# 10. Metodología experimental

Este capítulo especifica el protocolo experimental completo con el que se evalúa la hipótesis central de la tesis: si la deliberación contextual de un modelo de lenguaje multimodal pequeño (VLM/SLM) aporta un beneficio medible sobre una heurística rígida en la capa táctica de un dron autónomo con percepción monocular, y a qué costo. Se describen las preguntas experimentales, el diseño factorial, el contenido y la dificultad específica de cada escenario, el rol de las semillas, la organización de las corridas en tres *batches*, el protocolo estadístico, la disposición física de los resultados y un plan extendido de pruebas.

La estructura de este capítulo responde a un orden deliberado: primero *qué se quiere probar* (§10.1), luego *con qué factores* (§10.2), *sobre qué escenarios* (§10.3), *con cuántas repeticiones y por qué* (§10.4), *ejecutado cómo* (§10.5), *midiendo qué* (§10.6), *analizado cómo* (§10.7–§10.8), *dejando qué evidencia* (§10.9) y *qué falta por hacer* (§10.10). El capítulo 11 consume directamente esta especificación: las tablas de resultados están definidas aquí antes de existir los datos, para evitar el sesgo de elegir las métricas después de verlas.

---

## 10.1 Preguntas experimentales e hipótesis operativas

El diseño no persigue una única comparación global "SLM vs. FSM", sino cuatro preguntas separables, cada una con su propia condición de falsación:

**H1 — Beneficio de la deliberación contextual.**
En escenarios donde la trayectoria directa está obstruida por geometría que exige una decisión *semántica* (elegir entre dos corredores de ancho similar, anticipar que una fachada continua no tiene salida lateral), el brazo `slm` alcanza una tasa de éxito y/o un SPL superiores a los del brazo `fsm` con significancia estadística.
*Condición de falsación:* si en los escenarios con bloqueo real el `fsm` iguala o supera al `slm` en éxito y SPL, la deliberación contextual no aporta y el resultado negativo es igualmente publicable — es, de hecho, un hallazgo de diseño relevante para el capítulo 9.

**H2 — Costo del razonamiento.**
El sobrecosto temporal del brazo `slm` no escala con la distancia recorrida sino con la **frecuencia de deliberación** (`deliberation_rate`). Es decir: el costo del VLM es aproximadamente un término aditivo $N_{\text{inv}} \times \bar{\ell}_{\text{VLM}}$ (número de invocaciones por latencia media de inferencia), no un factor multiplicativo sobre el tiempo de misión.
*Condición de falsación:* si el ratio $t_{\text{slm}} / t_{\text{reactive}}$ es aproximadamente constante entre tiers en lugar de decrecer con la longitud de la ruta, la hipótesis es incorrecta y el costo sí es multiplicativo.

**H3 — Estratificación del beneficio por dificultad ambiental.**
El signo del efecto de H1 depende del tier: en ambientes despejados el VLM sólo agrega costo; el beneficio, de existir, aparece únicamente donde la geometría exige una decisión que la heurística no puede tomar. La hipótesis operativa es que **existe una interacción significativa entre el factor "brazo" y el factor "tier"**, no un efecto principal uniforme del brazo.

Esta última hipótesis es la que dicta la arquitectura de escenarios en tres niveles: sin escenarios de control despejados no hay forma de separar el costo fijo del brazo `slm` de su beneficio condicional, y sin escenarios con bloqueo genuino no hay forma de que el beneficio se manifieste. El diseño es, en este sentido, deudor directo de la práctica establecida en los *benchmarks* de conducción autónoma y navegación encarnada, donde la dificultad se estratifica explícitamente en niveles y cada nivel se corre un número fijo de episodios: CARLA organiza sus tareas en cuatro niveles crecientes (recta, un giro, navegación, navegación con tráfico dinámico) sobre el mismo simulador (Dosovitskiy et al., 2017), y su sucesor *NoCrash* define tres niveles de densidad de agentes dinámicos (`Empty`, `Regular`, `Dense`) con 25 episodios por tarea y condición (Codevilla et al., 2019). La estratificación por densidad de obstáculos es también la forma canónica de reportar navegación aérea de alta velocidad en bosque simulado (Loquercio et al., 2021), donde la métrica se informa en función de la densidad de árboles por metro cuadrado en lugar de agregarse en un único número.

---

## 10.2 Diseño factorial

### 10.2.1 Factor principal: brazo de decisión (`AGENT_ARM`)

La evaluación compara tres brazos de decisión sobre **el mismo `ObstacleField`** (cap. 6), **el mismo espacio de macro-acciones** y **el mismo traductor a comandos cinemáticos** (`action_to_command`, cap. 8). Esta invariancia es lo que hace legítima la comparación: la única diferencia entre brazos es *quién elige la macro-acción*, no qué percibe el sistema ni cómo ejecuta la decisión.

- **`slm`** — el modelo de lenguaje multimodal (Qwen2.5-VL-3B cuantizado) como capa táctica y deliberativa (cap. 8). Durante la espera de respuesta del modelo, el sistema aplica un **avance cauto** a velocidad reducida (`DELIB_WAIT_CREEP_SPEED_MPS = 0.5 m/s`) en lugar de un frenado total, preservando la traslación necesaria para que el estimador de flujo óptico mantenga confianza; sólo se comanda detención total incondicional ante un bloqueo frontal inminente y confirmado (`close_structural`). El modelo delibera de forma **asíncrona** bajo un watchdog de seguridad (`SLM_WATCHDOG_MS`, 6000 ms en la configuración de producción; 12000 ms para el barrido profundo, `SLM_DEEP_WATCHDOG_MS`) con respaldo determinista ante timeout o respuestas no conformes, recibiendo un historial temporal de fotogramas ($t$ y $t-1$), notas cinemáticas (`pitch`, `roll`, velocidad) y el motivo explícito de la consulta (`reason_note`).
- **`fsm`** — una máquina de estados finitos explícita (`CRUISE → AVOID_LEFT | AVOID_RIGHT | CLIMB | BRAKE → CRUISE`), con transiciones gobernadas por umbrales fijos sobre el mismo `ObstacleField`. Es la línea de base directa contra la que se evalúa la hipótesis: alta predictibilidad y costo computacional mínimo, sin capacidad de razonamiento contextual ni interpretación semántica del entorno.
- **`reactive`** — navegación guiada al waypoint sin evasión de obstáculos: **cota inferior de rendimiento** que permite desacoplar qué porción del desempeño proviene del lazo táctico de evasión y cuánto del seguimiento cinemático de base. Sin este brazo, cualquier diferencia entre `slm` y `fsm` sería inseparable del ruido introducido por el guiado.

El brazo se selecciona por variable de entorno `AGENT_ARM`, leída **a nivel de módulo** en `src/agents/graph.py`. Esta decisión de implementación tiene una consecuencia metodológica directa: **cada combinación debe correr en un intérprete propio**, porque reutilizar el proceso arrastraría el primer valor leído. El runner lanza por eso un subproceso por corrida (§10.5), lo que además aísla el fallo de una corrida del resto del batch.

### 10.2.2 Mecanismo de resolución de atascos

Los brazos `slm` y `fsm` utilizan el mecanismo **`deep_vlm`** como procedimiento de resolución de atascos duros: ante un `deadlock` declarado, ejecuta un barrido panorámico espacial multifotograma **dentro del lazo de control** (`SCAN_HEADING_COUNT_DEEP = 4` rumbos, `SCAN_SETTLE_CYCLES_DEEP = 2` ciclos de asentamiento por rumbo, hasta `MAX_DEEP_SCAN_IMAGES = 5` imágenes) seguido de una única consulta deliberativa al VLM con el panorama completo, para identificar visualmente un corredor despejado antes de forzar el escape cinemático como último recurso.

El brazo `reactive` nunca declara atasco ni ejecuta escape: el concepto de "objetivo pendiente bloqueado" no existe en un control reactivo puro.

`deep_vlm` **no introduce macro-acciones nuevas**: elige entre las mismas del vocabulario `PROMPT_ACTIONS` que usa el nodo deliberativo ordinario. El procedimiento aporta evidencia visual multiángulo que el nodo deliberativo ordinario, que opera con un único fotograma frontal, no tiene disponible en condiciones de bloqueo.

### 10.2.3 Estructura de celdas

La celda elemental es la tupla

$$\text{celda} = (\text{Escenario} \times \text{Brazo})$$

y cada celda se replica con $K \geq 5$ semillas. La estructura es uniforme en todos los escenarios:

| Brazo | Semillas | Corridas por escenario |
|---|---|---|
| `slm` | 5 | 5 |
| `fsm` | 5 | 5 |
| `reactive` | 5 | 5 |
| **Total** | | **15** |

---

## 10.3 Escenarios: contenido, particularidad y dificultad

Superando las formulaciones exploratorias preliminares (los borradores `manhattan_a` y `manhattan_b`, descartados por inconsistencias topográficas y de mapas en el simulador), el protocolo define una jerarquía formal en tres niveles crecientes de dificultad ambiental, cada uno sobre un **proyecto de Unreal Engine distinto** (cap. 3).

### 10.3.0 Principios de diseño comunes a todos los escenarios

Cuatro principios metodológicos gobiernan la construcción de cualquier escenario de esta batería, y explican por qué los manifiestos tienen la forma que tienen:

1. **Prohibición de teletransporte cinemático.** El campo `start_pose` está inhabilitado en la ruta de producción: todas las misiones despegan desde el *PlayerStart* nativo del nivel de Unreal Engine y ejecutan un ascenso vertical controlado previo a la navegación horizontal. La razón es que `simSetVehiclePose(ignore_collision=True)` es un reposicionamiento instantáneo que **no verifica colisión**, con lo que un escenario podría materializar el dron dentro de un edificio o a centímetros de un tronco, generando variación entre corridas que nada tiene que ver con la política de control evaluada. La consecuencia de diseño es que un escenario que necesita empezar lejos del *spawn* se arma como **misión de varios tramos**: un tramo de tránsito a altitud validada hasta el punto de interés, y recién allí el tramo de prueba a nivel de calle.
2. **Ninguna coordenada se inventa sobre el PNG del mapa.** Los mapas no tienen archivo de calibración píxel↔metro confiable. Toda coordenada nueva se deriva **por interpolación de coordenadas ya voladas y confirmadas**; la imagen se usa sólo cualitativamente (disposición relativa de plaza, bloques, corredor, avenida). Las coordenadas obtenidas por subdivisión geométrica —no por vuelo— se marcan explícitamente como **PROVISORIAS** y no entran a un batch sin pasar el protocolo de validación del punto 4.
3. **Exclusión de profundidad del lazo de control.** Ningún escenario reintroduce el canal de profundidad como entrada de control. El canal *depth* se captura únicamente cada `DEPTH_METRIC_EVERY_N = 5` ciclos y **sólo para observabilidad** (`min_obstacle_dist_m`), con una guardia arquitectónica automatizada (`tests/test_no_depth_in_flight_path.py`) que impide que reingrese al camino de vuelo. Sin esta guardia, la métrica de seguridad estaría contaminada por la propia señal que pretende auditar.
4. **Protocolo de validación previo obligatorio.** Antes de que un escenario entre a un batch estadístico: (a) se redacta el manifiesto en `airsim-plan/missions/flightplans/`; (b) se dibuja la ruta con `scripts/plot_mission_route.py` y se confirma en el *viewport* de UE que la línea cruza donde el escenario pretende (fachada para los de bloqueo, calle abierta para los de control); (c) se corre una **misión piloto de una sola combinación** (`slm`, una semilla) y se exige `success = True` con 0 colisiones —o, si no completa, que el motivo sea instructivo (atasco genuino) y no un error de geometría; (d) recién entonces se lanza el batch completo. El criterio es explícito: *si ninguna combinación puede tener éxito en el escenario, no tiene sentido gastar el presupuesto del batch*.

Una consecuencia práctica del punto 4 es la limpieza obligatoria de estado antes de cada corrida: el runner invoca `client.reset()` (que devuelve el vehículo a la pose de *spawn* de `settings.json` y limpia colisión/velocidad del controlador interno) y `client.clear_debug_markers()` (que descarta las primitivas persistentes dibujadas por `plot_mission_route.py`, las cuales de otro modo aparecen en el fotograma que recibe el VLM y son interpretadas como obstáculos reales).

---

### 10.3.1 Tier 0 — MiniSim (`crater.png`): línea de base y control

**Entorno.** Proyecto base de Unreal Engine 5.5, terreno abierto tipo cráter, sin edificaciones ni vegetación densa. Iluminación uniforme, textura de suelo con relieve suficiente para que el estimador de flujo óptico produzca campo denso, pero sin ninguna estructura vertical en la trayectoria.

**Escenario `minisim_clear` (`MINISIM_CLEAR`).**

| WP | x (m) | y (m) | z (m, NED) | Rol del tramo |
|---|---|---|---|---|
| WP_1 | 60.0 | 0.0 | −10.0 | Crucero recto de 60 m |
| WP_2 | 60.0 | 60.0 | −10.0 | Quiebre de rumbo de 90° |
| WP_3 | 0.0 | 60.0 | −10.0 | Segundo tramo recto de 60 m |

Recorrido nominal en "L": 120 m entre waypoints declarados, ~180 m contando el tramo desde el *spawn* hasta WP_1, y 191.7 m efectivamente recorridos en la corrida piloto del brazo `slm`. Altitud constante de −10 m.

**Qué se quiere probar.** Este escenario **no busca ejercitar la evasión** — busca medir lo que un escenario con obstáculos no permite medir limpiamente:

1. **Cota inferior de latencia de ciclo** y consumo cinemático ideal del sistema, sin ninguna contribución del lazo de evasión.
2. **Costo puro del brazo `slm` sin beneficio compensatorio.** Es el escenario donde H2 se mide en su forma más cruda: cualquier segundo de diferencia entre `slm` y `reactive` es sobrecosto neto de deliberación, porque no hay nada que deliberar. En la corrida piloto, 80 invocaciones sobre 1151 ciclos (6.95 %) produjeron 235 s frente a 84 s del `reactive`: un ratio de 2.8×, el mayor de los tres tiers.
3. **Tasa de falsos positivos de percepción.** En un campo sin obstáculos, *toda* invocación al VLM y *todo* evento de evasión son, por construcción, falsos positivos del canal de percepción. `deliberation_rate` en Tier 0 es por tanto una medida directa de la especificidad del predicado `is_blocked()` (cap. 6, §6.9) en condiciones benignas — una métrica que ningún escenario con obstáculos puede aislar.
4. **Fidelidad del quiebre de rumbo de 90°.** El giro entre WP_1 y WP_2 ejercita la guardia de rotación del estimador de flujo (`FLOW_MAX_ROTATION_DEG = 2°`) y la derotación analítica por IMU (cap. 6, §6.5). Un pico espurio de deliberación concentrado en ese tramo —visible en `summary_by_wp.csv`— indicaría que la derotación no está compensando el giro, que es exactamente el modo de falla histórico documentado en el capítulo 9.

**Particularidad y dificultad.** Es el único escenario donde el resultado esperado es *desfavorable* a la hipótesis principal: se espera que `reactive` gane por amplio margen y que `slm` sea el más lento. Su dificultad no es de navegación sino de **interpretación**: sirve para calibrar cuánto del desempeño observado en Tier 1 y 2 es atribuible al escenario y cuánto al costo estructural del brazo. Sin Tier 0, una victoria del `slm` en Tier 2 no podría separarse de un simple sesgo de medición.

---

### 10.3.2 Tier 1 — TownSim (`townsim_calib.png`): vegetación y morfología orgánica

**Entorno.** Entorno semiurbano construido sobre el *Downtown West Modular Pack* (PurePolygons). De norte a sur: una plaza con rotonda y jardín circular, y luego **tres bloques rectangulares de edificios en fila**, cada uno separado del siguiente por una calle transversal. Cada bloque tiene dos filas de edificios (oeste y este) con un **pasaje peatonal central** entre ambas. Una avenida ancha sale hacia el este, aproximadamente a la altura del límite entre la plaza y el primer bloque. Todo el complejo está rodeado de bosque denso; hay un cuerpo de agua al sur, fuera del complejo.

La geometría métrica del complejo se derivó exclusivamente de una misión ya volada y confirmada (`TOWNSIM_CALIB_0`, 656 m, `success = True`, 0 colisiones):

- El complejo mide **≈156 m de norte a sur** ($y \in [-71, +84]$) y **≈146 m de ancho** desde el eje del corredor central ($x \approx 0$) hasta el borde oeste exterior ($x \approx -146$).
- Centroide del complejo: $x \approx -73$, $y \approx 6.5$.
- Con tres bloques repartidos en tercios sobre el rango norte-sur (≈52 m por bloque), los límites entre bloques quedan aproximadamente en $y \approx -19$ e $y \approx 32$ — **subdivisión PROVISORIA**, sujeta a confirmación visual.

**La particularidad que define a este tier** es que sus obstáculos son de **morfología orgánica y semitransparente**: follaje, arboledas densas, mobiliario urbano. A diferencia de una fachada plana, una copa de árbol produce un campo de flujo óptico de alta frecuencia y baja coherencia — el estimador de FOE pierde inliers, la confianza cae, y el sistema entra en el régimen donde la evidencia geométrica es ambigua. Ese es precisamente el régimen donde la interpretación semántica del VLM debería aportar: distinguir "follaje atravesable / rodeable" de "estructura sólida" es una decisión que el canal de TTC, por diseño, no puede tomar. Es también el modo de falla que ya se observó en vuelo real: el primer intento de `townsim_ini` se enganchó en el follaje cercano a la plaza porque el guiado combinaba ascenso y traslación lateral simultáneos, cruzando la copa de los árboles todavía bajo.

#### Escenario 1.A — `townsim_clear` (control de crucero largo)

Perímetro completo del complejo, 6 waypoints, ~640 m, altitud de tránsito −30 m (por encima de la línea de tejados). Derivado directamente de `TOWNSIM_CALIB_0`: mismos 6 waypoints, misma geometría verificada por vuelo real.

**Qué se quiere probar.** Rol análogo al de `minisim_clear` en Tier 0, pero con una diferencia crítica: **la ruta es 3.3× más larga**. Es el escenario que permite testear H2 de forma directa — si el costo del VLM es aditivo en el número de invocaciones y no multiplicativo en la distancia, el ratio $t_{\text{slm}}/t_{\text{reactive}}$ debe caer sustancialmente respecto de Tier 0. El dato piloto lo confirma provisionalmente: 1.17× frente a 2.8×, con `deliberation_rate` de 0.82 % (11 invocaciones sobre 1337 ciclos).

**Dificultad.** Baja en términos de navegación (a −30 m el dron sobrevuela los tres bloques en lugar de negociarlos; el histograma de rutas de la corrida original fue 77 % `reactive`), pero **alta en términos de duración**: es la corrida más larga del batch de Tier 1 y la que más expone al sistema a la deriva acumulada del estimador y a la degradación por saturación de GPU compartida entre UE y el servidor del VLM.

#### Escenario 1.B — `townsim_ini` (recorrido con vegetación en ruta)

Vuelta a la manzana arrancando en el *PlayerStart* real (0,0), con una particularidad estructural: **WP_0_ASCENSO sube en el lugar** (mismo $x,y$ del *spawn*) antes de trasladarse, para no cruzar la copa de los árboles de la plaza durante el ascenso. Recién después sale por el lado este a altitud de tránsito, se une al perímetro ya validado (WP_2…WP_5) y vuelve a ~5 m del punto de partida descendiendo a −10 m.

**Qué se quiere probar.** Es el escenario de **interés real** de Tier 1: cruza el interior del complejo con corredores vegetados, e incorpora los dos tramos de mayor dificultad de todo el batch — el ascenso inicial entre follaje y el descenso final de retorno. El desglose `summary_by_wp.csv` es aquí la herramienta central: permite aislar el comportamiento del tramo `WP_0_ASCENSO` (que ya concentró la dificultad en corridas previas) de la fase de crucero.

**Dificultad.** Media-alta. La obstrucción no es un muro sino un dosel: el sistema debe decidir con evidencia geométrica degradada. Es el escenario donde se espera la primera manifestación de H1.

#### Escenario 1.C — `townsim_calib_cruce_frontal` / T-CALIB-2 (bloqueo frontal masivo)

| WP | x (m) | y (m) | z (m) | Rol |
|---|---|---|---|---|
| WP_1 | −150.0 | 0.4 | −30.0 | Tránsito de ida a altitud validada |
| WP_2 | −150.0 | 0.4 | −10.0 | Descenso **fuera** del complejo, en bosque abierto |
| WP_3 | 0.0 | 0.4 | −10.0 | **Cruce real a nivel de calle** contra la fila de edificios oeste |

**Qué se quiere probar.** Este es el escenario diseñado explícitamente para **forzar la activación de las ramas deliberativas y de resolución de atascos**. El tramo WP_2→WP_3 pone al dron a nivel de calle frente a una fachada continua, obligándolo a elegir entre `GANAR_ALTURA` (sobrevolar) y un corredor lateral. La estructura de tres tramos no es arbitraria: los dos primeros son **tránsito a geometría ya verificada**, necesarios sólo porque el teletransporte está prohibido; el único tramo sin verificar —y el único que efectivamente prueba algo— es el tercero.

**Particularidad.** Es el escenario donde H1 se manifiesta más claramente: si el `fsm` resuelve el bloqueo escalando por encima del edificio y el `slm` lo resuelve encontrando la calle transversal, ambos tendrán `success = True` pero con SPL muy distintos. **Por eso la métrica primaria de este escenario no es el éxito sino el SPL y la distancia recorrida** — la diferencia de calidad entre soluciones aparece en la longitud de la trayectoria, no en el binario de llegada.

**Dificultad.** Alta y deliberada: es el escenario donde se espera una tasa de atascos apreciable en los brazos deliberativos, lo que ejercita el mecanismo `deep_vlm` de resolución de bloqueos.

---

### 10.3.3 Tier 2 — CitySim (`citysim_calib.png`): cañones urbanos

**Entorno.** Proyecto de Unreal Engine 5.5 basado en el *Sample City* de Epic Games: tejido edilicio masivo en cuadrícula ortogonal regular, con edificios de **50 a 100 m de altura**, pasos restringidos y cañones urbanos angostos.

**La particularidad que define a este tier** es doble. Primero, la **altura de los obstáculos convierte a la altitud en variable de diseño de primer orden**: a diferencia de TownSim, donde −30 m basta para sobrevolar todo, en CitySim la maniobra `GANAR_ALTURA` deja de ser una salida universal — un escape por altura desde −20 m no despeja un edificio de 80 m. Segundo, la **regularidad y uniformidad de la textura urbana** es adversa para la percepción monocular: dos calles paralelas de ancho idéntico producen campos de flujo casi indistinguibles, y las fachadas repetitivas degradan el emparejamiento denso de DIS. Es el entorno donde la ventaja teórica del VLM (información semántica sobre la escena) enfrenta su prueba más exigente, porque también es el entorno donde una imagen aérea de dos corredores idénticos aporta poca información discriminativa.

#### Escenario 2.A — `citysim_clear` (control con arquitectura *climb-first*)

Perímetro de una manzana del grid regular, 7 waypoints, ~430 m, altitud de tránsito **−70 m AGL**. La estructura es *climb-first*: WP_1→WP_2 mantiene $x,y$ constantes y sube de −10 m a −70 m en **vertical puro**, y WP_6→WP_7 desciende en vertical puro desde la esquina noroeste. El patrón sólo es posible gracias al *fix* `near_vertical` del `WaypointTracker` (2026-09-07), que fuerza $v_x = 0$ cuando el siguiente waypoint está casi directamente arriba o abajo (`dist_xy < 1 m` y `|dz| > 0.3 m`), evitando la rampa diagonal.

**Qué se quiere probar.** Rol de control del tier, análogo a `minisim_clear` y `townsim_clear`. Pero su valor metodológico específico es **haber establecido la altitud de tránsito como parámetro crítico documentado**: la primera corrida a −50 m falló con colisión porque la ruta de ascenso atravesaba edificios. Ese fallo es un dato del diseño experimental, no un accidente descartable — establece la cota inferior de altitud segura para todo Tier 2 y explica por qué cualquier atasco observado en escenarios de corredor será atribuible a la geometría del corredor y no a un artefacto de altitud insuficiente.

> **Nota de estado (verificación de manifiesto, 2026-09-08).** El archivo `citysim_clear.json` en el árbol de trabajo contiene actualmente una variante de 4 waypoints con altitud máxima de −50 m, distinta de la geometría de 7 waypoints a −70 m con la que se obtuvieron los resultados piloto reportados en el capítulo 11 y descrita en el CHANGELOG del 2026-09-07. La discrepancia es compatible con una sobrescritura del manifiesto desde el editor de misiones de WebDCS. **El manifiesto debe restaurarse a la versión de 7 waypoints a −70 m antes de lanzar el batch de Tier 2**; correrlo en su estado actual reproduciría la condición de −50 m que ya falló por colisión.

#### Escenario 2.B — `citymap_pilot` (circuito de corredores)

Circuito de 7 waypoints en grilla urbana a −10 m de altitud constante, atravesando corredores entre edificios altos en lugar de sobrevolarlos.

**Qué se quiere probar.** Es el escenario terminal de la batería: **elección de corredor sin información discriminativa geométrica**. Ni el `reactive` ni el `fsm` tienen información semántica para elegir entre dos calles de ancho similar; su decisión se reduce a distancia pura o a la asimetría accidental del flujo óptico. La hipótesis es que el brazo `slm`, al consultar al VLM con la imagen del corredor, elegirá la ruta más despejada con mayor consistencia.

**El resultado negativo es igualmente válido y está previsto por diseño**: si el VLM no aporta información útil en un entorno de textura urbana uniforme, ése es un hallazgo relevante sobre los límites de la percepción semántica en entornos repetitivos, y se reporta como tal en el capítulo 9.

**Dificultad.** Máxima del batch. A −10 m entre edificios de 50–100 m, el escape por altura está efectivamente vetado (`MAX_ESCAPE_ALT_M = 30 m` no despeja la línea de tejados), lo que **elimina la salida universal del brazo `fsm`** y obliga a una decisión lateral genuina. Es, en consecuencia, el escenario donde H1 tiene la mayor potencia discriminativa y donde se espera la mayor tasa de fallo absoluto en los tres brazos.

---

### 10.3.4 Síntesis de la batería base

| Tier | Entorno (proyecto UE) | Escenario | Rol | Long. óptima | Altitud | Dificultad esperada | Hipótesis que ejercita |
|---|---|---|---|---|---|---|---|
| 0 | MiniSim (`crater.png`) | `minisim_clear` | Control / cota inferior | ~180 m | −10 m | Nula | H2, H3 (costo puro) |
| 1 | TownSim (`townsim_calib.png`) | `townsim_clear` | Control de crucero largo | ~640 m | −30 m | Baja | H2 (dilución del costo) |
| 1 | TownSim | `townsim_ini` | Vegetación en ruta | ~640 m | −30/−10 m | Media-alta | H1 |
| 1 | TownSim | `townsim_calib_cruce_frontal` | Bloqueo frontal masivo | ~320 m | −30/−10 m | Alta | **H1** |
| 2 | CitySim (`citysim_calib.png`) | `citysim_clear` | Control a altitud franca | ~430 m | −70 m | Baja | H2, H3 |
| 2 | CitySim | `citymap_pilot` | Elección de corredor | ~290 m | −10 m | **Máxima** | **H1, H3** |

---

## 10.4 Semillas: por qué varias y qué cambia cada una

### 10.4.1 Por qué se requieren múltiples semillas

Una corrida única no permite ninguna inferencia. La razón no es formal sino sustantiva: **el sistema bajo prueba es estocástico en al menos cinco puntos independientes** (§10.4.2), y una diferencia observada entre dos corridas únicas es indistinguible de la varianza intrínseca del entorno. La práctica de reportar resultados de agentes secuenciales a partir de pocas corridas está bien documentada como fuente sistemática de conclusiones no reproducibles (Henderson et al., 2018; Colas et al., 2018), y el problema se agrava exactamente en el régimen de este trabajo: **pocas corridas por celda, porque cada corrida cuesta minutos de tiempo real de simulación** (Agarwal et al., 2021).

Hay tres funciones distintas que cumplen las semillas en este diseño, y conviene no confundirlas:

1. **Función inferencial.** Sin réplicas no hay distribución muestral, y sin distribución muestral no hay prueba de hipótesis. Las pruebas no paramétricas del §10.7 operan sobre las distribuciones de las $K$ semillas de cada celda; con $K = 1$ el estadístico U de Mann-Whitney no está definido de forma útil.
2. **Función de robustez.** Un brazo que tiene éxito en 5 de 5 semillas es cualitativamente distinto de uno que tiene éxito en 3 de 5, aun con el mismo tiempo medio. La **tasa de éxito sobre semillas** es en sí misma la métrica primaria de fiabilidad, análoga al `success rate` sobre episodios de los *benchmarks* de conducción (Codevilla et al., 2019).
3. **Función de detección de acoplamiento.** Si dos semillas del brazo determinista `reactive` producen trayectorias idénticas al milímetro, ello indica que el entorno no está aportando la variación que se supone que aporta, y por tanto que las semillas no son réplicas independientes. La varianza del brazo `reactive` funciona así como **control negativo del propio diseño experimental**: es la medida de cuánta variabilidad introduce el entorno sin intervención de ninguna política estocástica.

### 10.4.2 Qué cambia realmente una semilla

Este punto exige precisión, porque la implementación tiene un matiz que es fácil de reportar mal. En la configuración de producción del batch (**sin** `--seed-jitter`), la variable `AIRSIM_SEED` **no perturba deliberadamente ningún parámetro del sistema**: se propaga al `FlightLogger` como etiqueta de identificación de la corrida. El runner llama `client.reset()`, que devuelve el vehículo a su pose de *spawn* original definida en `settings.json`, y no vuelve a reposicionarlo.

En consecuencia, en el batch base **una semilla identifica una réplica independiente, no una condición distinta**. La variación entre semillas proviene íntegramente de la estocasticidad intrínseca del sistema, que tiene cinco fuentes identificadas:

1. **Jitter temporal del lazo de control.** El lazo corre a `LOOP_HZ = 5.0` con temporización de reloj de pared (`time.sleep(max(0, 1/f - t_ciclo))`). El tiempo de cada ciclo depende de la latencia RPC a AirSim, de la carga de GPU y del planificador del sistema operativo. Un ciclo que se pasa del presupuesto desplaza todos los siguientes: dos corridas idénticas divergen en **qué instante exacto de la trayectoria** se toma cada decisión. Con `REACTIVE_FORWARD_SPEED = 3.0 m/s`, 20 ms de desfase equivalen a 6 cm de desplazamiento por ciclo, que se acumulan.
2. **Renderizado y física no reproducibles cuadro a cuadro.** Unreal Engine no garantiza determinismo cuadro a cuadro bajo carga variable de GPU; la física de AirSim avanza en tiempo real, no en pasos fijos sincronizados con el cliente. El fotograma capturado en el ciclo $n$ no es bit a bit el mismo entre corridas, y el estimador de flujo óptico —que opera sobre diferencias de intensidad a nivel de píxel— amplifica esas diferencias.
3. **Sensibilidad del estimador de flujo a condiciones iniciales.** El cálculo de FOE por mínimos cuadrados ponderados con rechazo de *outliers* (RANSAC-lite, `FOE_OUTLIER_ANGLE_RAD = 0.35`) es una función no lineal del campo de flujo. Pequeñas diferencias en el conteo de inliers cruzan el umbral de confianza diferenciada (< 30 vs. ≥ 30 inliers), lo que cambia el estado epistémico reportado por `ObstacleField` y, con él, la decisión de enrutamiento del `policy_router`. Es un sistema con **realimentación**: una decisión distinta cambia la pose, que cambia el fotograma siguiente, que cambia la decisión siguiente.
4. **Muestreo estocástico del VLM.** La inferencia se realiza con `temperature = 0.2` y **sin semilla de muestreo fijada** en el servidor de inferencia. Dos consultas con el mismo prompt pueden producir macro-acciones distintas. A esto se suma que la determinación de la inferencia en servidores de LLM no está garantizada aun con temperatura cero: la composición de kernels no invariantes al tamaño de lote con un tamaño de lote que varía según la carga del servidor produce variación de corrida a corrida a nivel de punto flotante (He, 2025). Esta fuente **afecta únicamente al brazo `slm`**, lo que es metodológicamente relevante: el brazo deliberativo tiene una fuente de varianza adicional que los otros dos no tienen, y por eso se espera —y se debe reportar— una dispersión mayor en sus métricas.
5. **Deriva temporal del watchdog asíncrono.** El servicio de deliberación corre en hilo separado bajo `SLM_WATCHDOG_MS`. Que una respuesta llegue **antes o después** del vencimiento del watchdog depende de la latencia de red y de la carga del servidor de inferencia en ese instante; el mismo prompt puede resolverse como decisión del modelo en una corrida y como *fallback* determinista en otra. Ésta es la fuente de varianza más consecuente para el análisis, porque cambia cualitativamente qué política gobierna ese ciclo.

Estas cinco fuentes se acumulan multiplicativamente sobre una misión de 1000–2000 ciclos. La divergencia entre dos semillas de la misma celda es, por tanto, real y sustancial — pero es **estocasticidad no controlada**, no un factor manipulado.

### 10.4.3 El modo de perturbación controlada y por qué no es el modo por defecto

El runner ofrece un modo alternativo (`--seed-jitter`) en el que la semilla **sí** determina una condición distinta y reproducible: siembra un `random.Random(seed)` que genera un desplazamiento de la pose inicial de $\pm 1.5$ m en $x$ e $y$ y $\pm 10°$ en guiñada (`SEED_JITTER_XY_M`, `SEED_JITTER_YAW_DEG`). Es el análogo directo de las *sticky actions* introducidas en la revisión del Arcade Learning Environment para inyectar estocasticidad controlada y evaluar la robustez de una política en lugar de su capacidad de memorizar una trayectoria (Machado et al., 2018).

**Este modo está deshabilitado por defecto, y la razón es una decisión metodológica explícita.** El jitter se aplica vía `simSetVehiclePose(ignore_collision=True)`, un teletransporte que no verifica colisión: con $\pm 1.5$ m de desplazamiento, el dron puede materializarse más cerca de un poste o un tronco que en el *spawn* limpio de AirSim, introduciendo variación entre corridas que **no proviene de la política de control sino de la posición del obstáculo más cercano al punto de partida**. Eso viola el principio de no teletransporte del §10.3.0 y contamina la comparación entre brazos: la corrida "difícil" le tocaría a un brazo por sorteo, no por diseño.

La consecuencia se asume y se declara: **en el batch base, la variación entre semillas es la variación intrínseca del entorno, y la comparación entre brazos es una comparación de réplicas independientes bajo condiciones iniciales nominalmente idénticas.** El modo con jitter se reserva para el plan extendido (§10.10), donde se lo trata como un factor experimental propio y se lo valida antes de usarlo — verificando en el *viewport* que ninguna de las poses sorteadas cae dentro de un obstáculo.

### 10.4.4 Número de semillas

Se ejecutan **$K \geq 5$ semillas por celda factorial**. Este número es una solución de compromiso explícita, no un valor arbitrario:

- El **límite inferior** lo impone la potencia estadística. Con $K = 5$ por grupo, el estadístico U de Mann-Whitney tiene un $p$-valor mínimo alcanzable (bilateral, sin empates) de $2/\binom{10}{5} = 0.0079$. Es decir: con 5 semillas por brazo, **sólo una separación perfecta entre las dos muestras puede ser significativa al 5 %**, y ninguna comparación puede sobrevivir la corrección de Bonferroni del §10.7 ($\alpha_{\text{ajustado}} \approx 0.0028$). Este es un límite duro del diseño y debe reportarse como tal.
- El **límite superior** lo impone el presupuesto de tiempo real: cada corrida consume entre 3 y 15 minutos de simulación en tiempo real, y el batch completo con $K = 5$ ya supera las 14 horas de máquina (§10.5.4).

La respuesta operativa a esta tensión es doble. Primero, **$K = 5$ es el mínimo del batch base y $K = 10$ el objetivo de las celdas donde la comparación es central para la tesis** (las de `townsim_calib_cruce_frontal` y `citymap_pilot`); con $K = 10$ por grupo, el $p$ mínimo alcanzable baja a $2/\binom{20}{10} \approx 1.1\times10^{-5}$, holgadamente por debajo del umbral corregido. Segundo, **el reporte no se apoya sólo en el $p$-valor**: se informan tamaños de efecto con intervalo de confianza *bootstrap* y las distribuciones completas, que es la práctica recomendada precisamente para el régimen de pocas corridas (Agarwal et al., 2021). Un tamaño de efecto grande con un intervalo de confianza ancho es información útil y honestamente reportable; un $p$-valor no significativo con $K = 5$ **no es evidencia de ausencia de efecto**, y así se lo declara en el capítulo 11.

---

## 10.5 Organización en tres batches

### 10.5.1 Por qué exactamente tres batches, y no uno

La ejecución **no puede organizarse como un único batch monolítico**, por una restricción dura del entorno de simulación: los tres tiers corresponden a **tres proyectos de Unreal Engine distintos** (MiniSim, TownSim y CitySim, §10.3), cada uno con su propio nivel, su propio *PlayerStart* y su propio `settings.json` de AirSim. El cliente de AirSim se conecta por RPC a la instancia de UE que esté corriendo en ese momento; **no existe forma programática de cambiar de proyecto desde el runner**. Un escenario de Tier 1 lanzado contra el nivel de Tier 0 no falla con un error legible: vuela sobre el terreno equivocado y produce una corrida silenciosamente inválida.

En consecuencia, la unidad de ejecución del protocolo es el **batch = conjunto de todas las corridas que comparten un mismo nivel de Unreal Engine cargado**. La organización en tres batches no es una preferencia de conveniencia sino la traducción directa de esa restricción, y tiene dos consecuencias metodológicas favorables:

1. **Aísla la fuente de contaminación cruzada más peligrosa.** Todas las corridas de un batch comparten exactamente el mismo estado del simulador, la misma configuración de escalabilidad gráfica y la misma sesión de UE. Comparar entre brazos *dentro* de un batch es por tanto una comparación limpia.
2. **Obliga a declarar explícitamente el análisis entre batches como comparación de segundo orden** (§10.8.4): los tiers no comparten sesión de simulador, de modo que las diferencias absolutas entre tiers arrastran un efecto de sesión no controlado, y sólo las **razones normalizadas dentro de cada tier** (p. ej. $t_{\text{slm}}/t_{\text{reactive}}$) son comparables entre tiers.

### 10.5.2 Procedimiento por batch

Cada batch se ejecuta según la siguiente secuencia, en este orden estricto:

1. **Preparación del entorno.** Lanzar el proyecto de UE correspondiente al tier; aplicar el perfil de escalabilidad mínima documentado en el capítulo 3 (`Config/DefaultScalability.ini` con `sg.ShadowQuality` forzado, necesario para que la estimación de TTC disponga de las sombras que usa el flujo); verificar que el servidor de inferencia responde (`GET {LOCAL_LLM_URL}/models`, chequeo que el propio runner ejecuta antes de cada corrida del brazo `slm` y que aborta la corrida si falla).
2. **Higiene de estado.** El runner ejecuta `client.reset()` y `client.clear_debug_markers()` al inicio de cada corrida. No se depende de que el operador recuerde limpiar los marcadores de `plot_mission_route.py`.
3. **Piloto de validación.** Una corrida `slm`, una semilla, por cada escenario nuevo del batch (§10.3.0, punto 4).
4. **Batch completo.** Un subproceso por combinación (escenario × brazo × estrategia × semilla).
5. **Verificación de integridad.** Confirmar que el número de archivos `*.summary.json` coincide con el número de combinaciones planificadas y que todos comparten el mismo `code_version`. Una discrepancia de `code_version` dentro de un batch invalida la comparación: significa que se redeployó código a mitad de la corrida.
6. **Análisis.** `experiments/analyze.py` para la tabla agregada y las latencias por rama; `experiments/analyze_tesis_results.py` para el desglose por brazo y escenario.

### 10.5.3 Comandos de ejecución

**Batch A — Tier 0 (MiniSim / `crater.png`).**

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/minisim_clear.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier0 \
  --max-cycles 2400 \
  --max-seconds 480
```

**Batch B — Tier 1 (TownSim / `townsim_calib.png`).** Los tres escenarios corren sobre el mismo nivel UE:

```bash
# B.1 — control de crucero largo
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_clear.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier1 \
  --max-cycles 4500 --max-seconds 900

# B.2 — escenarios con obstrucción real
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_ini.json \
               ../airsim-plan/missions/flightplans/townsim_calib_cruce_frontal.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier1 \
  --max-cycles 4500 --max-seconds 900
```

**Batch C — Tier 2 (CitySim / `citysim_calib.png`).** Requiere haber restaurado previamente el manifiesto `citysim_clear.json` a la geometría de 7 waypoints a −70 m (nota de §10.3.3):

```bash
# C.1 — control a altitud franca
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/citysim_clear.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier2 \
  --max-cycles 3000 --max-seconds 600

# C.2 — corredores urbanos angostos
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/citymap_pilot.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier2 \
  --max-cycles 3000 --max-seconds 600
```

### 10.5.4 Presupuestos y volumen del batch

Los presupuestos temporales **no se dimensionan sobre la velocidad nominal** (`REACTIVE_FORWARD_SPEED = 3.0 m/s`) sino sobre la **velocidad de crucero efectivamente medida en vuelo**, que descuenta frenadas, deliberación y maniobras: ≈1.9 m/s en `TOWNSIM_CALIB_0` (656 m en 349.6 s de vuelo). Sobre esa base se aplica un margen ≥2.5×, con margen adicional en los escenarios con `deep_vlm` por el freno propio del barrido panorámico.

| Batch | Escenario | Corridas | `--max-seconds` | `--max-cycles` | Tiempo estimado |
|---|---|---|---|---|---|
| A (Tier 0) | `minisim_clear` | 15 | 480 | 2400 | ~1.2 h |
| B (Tier 1) | `townsim_clear` | 15 | 900 | 4500 | ~1.5 h |
| B (Tier 1) | `townsim_ini` | 15 | 900 | 4500 | ~2.0 h |
| B (Tier 1) | `townsim_calib_cruce_frontal` | 15 | 900 | 4500 | ~2.0 h |
| C (Tier 2) | `citysim_clear` | 15 | 600 | 3000 | ~1.0 h |
| C (Tier 2) | `citymap_pilot` | 15 | 600 | 3000 | ~1.5 h |
| **Total** | | **90** | | | **~9.2 h** |

Cada escenario aporta 15 corridas: tres brazos × 5 semillas, todas con el mecanismo `deep_vlm`.

El límite `--max-cycles` es una salvaguarda secundaria: a `LOOP_HZ = 5` y con el lazo cumpliendo su presupuesto (≈4.9 Hz medidos en los pilotos), `--max-seconds` se agota primero. El límite de ciclos protege el caso patológico opuesto — un lazo que se acelera porque las capturas fallan silenciosamente.

---

## 10.6 Métricas reportadas

Todas las métricas se derivan del registro por ciclo del `FlightLogger` y se consolidan en el `summary.json` de cada corrida. La distinción entre **métricas de control** (las que realimentan el vuelo) y **métricas de observabilidad** (las que sólo se registran) es arquitectónicamente estricta: `min_obstacle_dist_m` proviene del canal de profundidad y **nunca realimenta el control**, lo que la convierte en un auditor independiente de la percepción monocular.

### 10.6.1 Eficacia y seguridad de vuelo

- **Tasa de éxito de misión** (`success`): arribo a todos los waypoints dentro del presupuesto de ciclos y segundos. Es un binario por corrida; sobre $K$ semillas se convierte en una proporción, que es la métrica primaria de fiabilidad.
- **Colisiones** por misión y **normalizadas por kilómetro** recorrido. La normalización es necesaria porque los escenarios difieren en longitud por un factor de 3.3×.
- **Distancia mínima a obstáculo, percentil 5** (`min_obstacle_dist_m`), medida por el canal de profundidad cada `DEPTH_METRIC_EVERY_N = 5` ciclos sobre el tercio central de la imagen. Se reporta el percentil 5 sobre la agregación de semillas, no el mínimo absoluto, para no dejar que un único artefacto domine la métrica de seguridad.
- **SPL** (*Success weighted by Path Length*), en su definición estándar para agentes de navegación (Anderson et al., 2018): $\text{SPL} = S \cdot \ell_{\text{opt}} / \max(\ell_{\text{real}}, \ell_{\text{opt}})$, con $S$ el indicador de éxito. La longitud óptima $\ell_{\text{opt}}$ se computa como la suma de distancias euclídeas entre waypoints consecutivos del manifiesto: no es un camino volable en presencia de obstáculos, pero es la referencia estándar y, sobre todo, es **idéntica para los tres brazos**, que es lo que la comparación requiere. El SPL es la única métrica que penaliza simultáneamente no llegar y llegar dando vueltas, y es por eso la métrica principal para los escenarios de bloqueo (§10.3.2, escenario 1.C).

  > **Sesgo conocido en el cálculo actual.** `experiments/analyze.py` computa $\ell_{\text{opt}}$ sumando únicamente las distancias entre waypoints **declarados en el manifiesto**, sin incluir el tramo desde el *spawn* hasta el primer waypoint, que sí queda contabilizado en $\ell_{\text{real}}$. En `minisim_clear` ese tramo son 60 m sobre 120 m declarados: el SPL queda subestimado en aproximadamente un tercio. El sesgo es **constante por escenario e idéntico para los tres brazos**, de modo que no invalida ninguna comparación entre brazos dentro de un escenario, pero sí impide interpretar el valor absoluto del SPL y compararlo entre escenarios. Se reporta en consecuencia el SPL como métrica **relativa dentro de cada escenario**; la corrección del cálculo (incorporar la pose de *spawn* como origen de la polilínea óptima) queda registrada como deuda técnica del pipeline de análisis.
- **Tiempo y ciclos totales** a destino.

### 10.6.2 Dinámica del lazo táctico y latencias

- **Latencia total por ciclo** ($p_{50}$ y $p_{95}$), desagregada por brazo y por **nodo activo del grafo de control** (`reactive`, `evasive`, `deliberative`, `girar_90`, `fsm`, `deep_scan`). El $p_{95}$ es la métrica relevante para la viabilidad en tiempo real: un $p_{50}$ aceptable con un $p_{95}$ que excede el presupuesto de ciclo describe un sistema que cumple "en promedio" y falla justo cuando importa.
- **Histograma de rutas** por corrida: la distribución de ciclos entre nodos del grafo. Es la caracterización más informativa del comportamiento cualitativo de un brazo — una corrida 77 % `reactive` describe un vuelo que sobrevoló los obstáculos en lugar de negociarlos, independientemente de lo que digan sus métricas de éxito.
- **`deliberation_rate`**: fracción de ciclos que invocan efectivamente al modelo. Se contabiliza por **transición de identificador único de deliberación**, no por ciclo con ruta `deliberative`; sin esa distinción, una deliberación que abarca varios ciclos de espera se contaría múltiples veces e inflaría la tasa muy por encima de la real.
- La latencia del **escaneo espacial pre-vuelo** (`spatial_scan`, cap. 5) es un costo de inicialización de única vez y se registra por separado del presupuesto por ciclo.

### 10.6.3 Comportamiento del modelo de lenguaje

- **Invocaciones efectivas por misión** (`slm_invocations`).
- **Tasa de *fallback* determinista** (`slm_fallback_rate`) ante respuestas inválidas o fuera de esquema.
- **Tasa de *timeout*** del watchdog asíncrono (`slm_timeout_rate`).
- **Tasa de adherencia sintáctica** (`adherence_rate`), con y sin decodificación gramatical estructurada (cap. 8, §8.2).

### 10.6.4 Resolución de atascos

- **`deadlock_events`**: número de atascos declarados.
- **`deep_scan_resolution_rate`**: fracción de atascos resueltos por el barrido profundo.
- **`deep_scan_avg_cycles_to_resolve`**: costo medio en ciclos de una resolución exitosa.
- **`deep_scan_fallback_rate`**: fracción de atascos donde el barrido no resolvió y se cayó al escape ciego de respaldo.

Estas cuatro métricas sólo tienen valor conjunto: una tasa de resolución alta con un costo de ciclos desmesurado no describe un mecanismo exitoso sino uno caro.

### 10.6.5 Desglose espacial por waypoint

Cada corrida emite `<stem>.summary_by_wp.csv` con ciclos consumidos, duración, ciclos deliberativos, tasa de deliberación y eventos de escaneo profundo **por tramo de misión**. Es la herramienta que permite aislar los tramos de ascenso vertical de las fases de crucero y maniobra horizontal, y la que ya identificó en corridas previas que un único waypoint (`WP_0_ASCENSO` de `townsim_ini`) concentraba la dificultad de toda la misión. Sin este desglose, una métrica agregada de misión atribuye a "el escenario" una dificultad que pertenece a un solo tramo de 20 segundos.

---

## 10.7 Protocolo estadístico

### 10.7.1 Pruebas de hipótesis

La comparación entre brazos y configuraciones se realiza mediante **pruebas no paramétricas**, calculadas sobre las distribuciones de las semillas de cada celda:

- **Prueba U de Mann-Whitney** (bilateral) para comparaciones pareadas entre dos brazos en el mismo escenario y estrategia (Mann & Whitney, 1947). Hipótesis nula: la distribución de la métrica no difiere entre brazos.
- **Prueba de Kruskal-Wallis** para el contraste conjunto de los tres brazos antes de descender a comparaciones pareadas (Kruskal & Wallis, 1952).

La elección de pruebas no paramétricas no es una precaución de rutina: es una necesidad del tipo de dato. Las distribuciones de tiempo de misión están **truncadas por la derecha** por el presupuesto `--max-seconds` (una corrida que se agota registra el presupuesto, no su tiempo real), lo que produce distribuciones asimétricas con masa concentrada en el límite. Ninguna prueba que asuma normalidad es defendible sobre ese dato.

**Métrica primaria:** tiempo de misión sobre corridas con `success = True` en los escenarios de control (H2); **SPL** en los escenarios con bloqueo (H1). **Métrica secundaria de seguridad:** `min_obstacle_dist_m`. La declaración anticipada de la métrica primaria por escenario —antes de ver los datos— es lo que impide elegir *a posteriori* la métrica que favorece la hipótesis.

### 10.7.2 Tamaños de efecto

Se reporta **Cliff's Delta** ($\delta$) para toda comparación pareada (Cliff, 1993), definido como la proporción de pares en que una muestra domina a la otra: $\delta = 2U/(n_A n_B) - 1$. Se adopta la escala de interpretación de Romano et al. (2006): $|\delta| < 0.147$ despreciable, $0.147$–$0.330$ pequeño, $0.330$–$0.474$ mediano, $\geq 0.474$ grande. Para el contraste conjunto se reporta $\eta^2_H$ o la correlación de rango biserial según corresponda.

El tamaño de efecto no es un complemento decorativo del $p$-valor: **es el resultado principal cuando $K$ es pequeño**. Un $p$ significativo con $\delta$ despreciable describe una diferencia real de magnitud práctica nula; un $\delta$ grande con $p$ no significativo describe un efecto que el diseño no tuvo potencia para detectar, no un efecto ausente. Ambos casos se reportan explícitamente como tales.

### 10.7.3 Comparaciones múltiples

Se aplica **corrección de Bonferroni** sobre la familia de comparaciones planificadas: 3 pares de brazos × 6 escenarios = 18 pruebas. El umbral ajustado es $\alpha = 0.05/18 \approx 0.0028$.

La corrección se aplica **sólo a las comparaciones declaradas antes de ver los datos**. Cualquier comparación adicional sugerida por la inspección de los resultados se reporta como **exploratoria**, sin pretensión de significancia — la alternativa (corregir sobre una familia que crece a medida que se exploran los datos) sería a la vez estadísticamente incorrecta y prácticamente inútil.

### 10.7.4 Análisis desagregado

El análisis **no se limita a valores agregados globales**. Se evalúa el rendimiento desagregado por tipo de escenario y morfología de obstáculo, porque es la única forma de contrastar H4: la pregunta no es "¿es mejor el `slm`?" sino "¿en qué condiciones lo es, y a qué costo?". Un promedio sobre los seis escenarios de la batería mezclaría escenarios donde el brazo `slm` sólo puede perder (los de control) con escenarios donde sólo puede ganar, produciendo un número sin interpretación posible. Es la misma razón por la que los *benchmarks* de conducción reportan por nivel de dificultad en lugar de agregarlos (Codevilla et al., 2019).

---

## 10.8 Análisis esperado por batch y análisis comparativo conjunto

Esta sección declara, **antes de tener los datos**, qué resultado se espera de cada batch y cómo se leerá. La finalidad es explícita: un resultado que contradiga estas expectativas es informativo precisamente porque las expectativas estaban escritas de antemano.

### 10.8.1 Batch A (Tier 0) — qué se espera

El resultado esperado es **desfavorable al brazo `slm` y favorable a la hipótesis H2**:

- Orden esperado de tiempo de misión: `reactive` < `fsm` < `slm`, con $\delta$ grande (cercano a 1.0) en la comparación `reactive` vs. `slm`. Es la comparación con mayor probabilidad de superar el umbral corregido, porque el efecto piloto (84 s vs. 235 s) es enorme respecto de la dispersión plausible.
- Sin diferencias significativas en seguridad: en un campo despejado, ningún brazo puede ser más seguro que otro, y las distancias mínimas al obstáculo del piloto (9.74 / 9.06 / 6.38 m) son consistentes con esa lectura.
- `deliberation_rate` del orden de unos pocos puntos porcentuales, interpretable directamente como **tasa de falso positivo de percepción** en condiciones benignas.
- La comparación `slm` vs. `fsm` se espera más variable, porque depende de cuántos atascos acumule la FSM por corrida — y en Tier 0 un atasco es, por definición, espurio.

**Qué invalidaría la lectura:** una tasa de éxito inferior a 5/5 en cualquier brazo. En un escenario sin obstáculos, un fallo indica un problema del sistema (percepción, guiado o infraestructura), no del escenario, y obliga a detener el batch antes de continuar con Tier 1.

### 10.8.2 Batch B (Tier 1) — qué se espera

Es el batch con mayor contenido informativo, porque contiene los tres roles: control, obstrucción orgánica y bloqueo frontal.

- **`townsim_clear`**: se espera que el ratio $t_{\text{slm}}/t_{\text{reactive}}$ caiga marcadamente respecto de Tier 0 (piloto: 1.17× vs. 2.8×). **Ésta es la prueba directa de H2**, y su forma es una comparación de razones, no de valores absolutos.
- **`townsim_ini`**: se espera la primera aparición de una ventaja del `slm` en SPL, concentrada según `summary_by_wp.csv` en el tramo de ascenso inicial entre follaje. Si la ventaja aparece pero está distribuida uniformemente entre tramos, la explicación no es la deliberación sino un sesgo sistemático del guiado, y debe investigarse como tal.
- **`townsim_calib_cruce_frontal`**: se espera una tasa de atascos apreciable en `slm` y `fsm`. La lectura esperada es que el `slm` produzca el mejor SPL del escenario al resolver el bloqueo lateralmente, mientras el `fsm` recurre al escape por altura.

**Qué invalidaría la lectura:** cero atascos en `townsim_calib_cruce_frontal`. Significaría que el tramo de cruce no está encontrando la fachada —error de geometría, no de política— y obligaría a re-validar el manifiesto con `plot_mission_route.py`.

### 10.8.3 Batch C (Tier 2) — qué se espera

- **`citysim_clear`**: comportamiento análogo al de los otros controles, con el ratio $t_{\text{slm}}/t_{\text{reactive}}$ más bajo de los tres tiers (piloto: 1.09×), consistente con H2. Cero atascos en los tres brazos confirma que la ruta de crucero a −70 m no presenta obstrucciones y que la altitud es adecuada.
- **`citymap_pilot`**: es el escenario terminal y el de mayor incertidumbre. Se esperan **tasas de éxito inferiores a 1.0 en los tres brazos** —es el único escenario del batch donde el fracaso es un resultado esperado y no un síntoma— y una mayor dispersión entre semillas. Es también el escenario donde la hipótesis puede fallar de la forma más informativa: si el VLM no discrimina entre corredores de textura uniforme, `slm` y `fsm` empatarán, y ese empate es un resultado sustantivo sobre los límites de la percepción semántica en tejido urbano repetitivo.

### 10.8.4 Análisis comparativo conjunto

El cruce entre los tres batches es donde se contrasta **H4**, y exige una precaución declarada en §10.5.1: los tres batches corren en sesiones de simulador distintas y sobre proyectos de UE distintos, de modo que **las diferencias absolutas entre tiers arrastran un efecto de sesión no controlado**. La comparación entre tiers se realiza en consecuencia sobre tres tipos de cantidad, todas normalizadas dentro de su propio tier:

1. **Razones normalizadas por brazo.** $t_{\text{arm}}/t_{\text{reactive}}$ dentro de cada escenario. Al dividir por el brazo de referencia del mismo escenario y la misma sesión, el efecto de sesión se cancela en primer orden. La progresión esperada de $t_{\text{slm}}/t_{\text{reactive}}$ (2.8× → 1.17× → 1.09×) es la evidencia central de H2.
2. **Perfil de deliberación por dificultad.** `deliberation_rate` en función del tier. La predicción de H4 es un perfil **no monótono**: alto en Tier 0 (falsos positivos sobre campo despejado), bajo en los escenarios de control de crucero franco, y nuevamente alto en los escenarios con obstrucción real — pero esta vez con invocaciones *justificadas*. La distinción entre "alto por ruido" y "alto por necesidad" se hace cruzando `deliberation_rate` con el SPL resultante y con `summary_by_wp.csv`.
3. **Interacción brazo × tier.** El resultado que sostiene H4 es un **cambio de signo** del efecto `slm` − `fsm` entre los escenarios de control y los de bloqueo. Con la potencia disponible ($K = 5$), esta interacción se reporta como patrón de tamaños de efecto con sus intervalos de confianza, no como una prueba formal de interacción: un ANOVA de dos factores sobre datos truncados y con 5 réplicas no sería defendible.

El producto final del análisis conjunto es una tabla de doble entrada **brazo × escenario** con éxito, SPL, tiempo normalizado, seguridad y tasa de deliberación —la estructura ya definida en el capítulo 11, §11.2— más el conjunto de comparaciones pareadas con su $\delta$ e intervalo de confianza. La conclusión de la tesis no es un único número sino ese mapa: **dónde el razonamiento contextual paga y dónde no**.

---

## 10.9 Organización de los resultados, auditoría y reproducibilidad

### 10.9.1 Disposición física de los artefactos

El runner escribe de forma determinista bajo la siguiente estructura, derivada de los propios factores del diseño:

```
airsim-runs/produccion/<tier>/
└── <escenario>/                    # stem del manifiesto: townsim_ini, citymap_pilot, …
    └── <brazo>/                    # slm | fsm | reactive
        ├── seed_1.jsonl               # telemetría granular ciclo a ciclo
        ├── seed_1.csv                 # misma corrida, tabular
        ├── seed_1.summary.json        # indicadores agregados de la corrida
        ├── seed_1.summary_by_wp.csv   # desglose por tramo de misión
        ├── seed_2.jsonl
        │   …
        └── photo-<timestamp_ISO>.png  # fotogramas exactos enviados al VLM
```

La ruta **es** el registro del punto del diseño factorial al que pertenece la corrida: escenario, brazo, estrategia y semilla son directorios y nombre de archivo, no metadatos que haya que parsear. Los fotogramas de auditoría conviven en el directorio de la celda y se nombran por *timestamp* de captura con precisión de milisegundos (varios fotogramas de una misma deliberación —el barrido panorámico, por ejemplo— comparten segundo), de modo que se cruzan con la telemetría por el campo `slm_frame_paths` del CSV.

El CSV plano por corrida contiene, además de la cinemática y las lecturas sectoriales del `ObstacleField`, el **prompt completo y la respuesta cruda del VLM** en cada deliberación, junto al identificador de la entrada correspondiente del JSONL. La decisión de duplicar esa información en el CSV es deliberada: permite analizar el comportamiento del modelo sin cruzar archivos.

Cuando se usa `batch_runner.py`, se agrega en la raíz del directorio de salida un `RESULTS_SUMMARY.json` consolidado con una fila por combinación, y un `RESULTS_SUMMARY.batch_version.txt` con el hash del código que orquestó el batch (que puede diferir del `code_version` de las corridas si se redeployó a mitad de camino).

### 10.9.2 Artefactos de auditoría de corridas interactivas

Las corridas **interactivas** (`main.py`, usadas para pilotos y diagnóstico) generan adicionalmente un directorio autónomo de auditoría `airsim-runs/<mission_id>-<timestamp>/` que incluye dos artefactos que **el runner headless no produce**, por diseño, para no gastar ciclos de CPU en un batch de 130 corridas:

- **Grabación de video continua sincronizada**: `.webm` con códec VP8 (sin dependencias de licencias propietarias), grabado a la tasa nominal `LOOP_HZ`, con superposición de telemetría cinemática, lecturas sectoriales de TTC y nodo activo del grafo.
- **Visor interactivo offline (`viewer.html`)**: aplicación web autocontenida —el CSV se embebe *inline*, no se carga por `fetch()`, de modo que el archivo funciona abierto directamente desde el disco— que vincula un deslizador temporal con el video y la tabla de telemetría, permitiendo inspeccionar sincronizadamente el prompt, los fotogramas y la respuesta del modelo en cada decisión.

Esta asimetría entre corridas interactivas y batch es intencional y debe declararse: **la evidencia audiovisual del comportamiento cualitativo proviene de las corridas piloto, la evidencia estadística proviene del batch.** Si se desea video de una celda específica del batch, se re-corre esa combinación en modo interactivo con `FLIGHT_RECORD_VIDEO=true`.

### 10.9.3 Trazabilidad y cuarentena experimental

Cada corrida incorpora automáticamente el hash de commit de Git (`code_version`) en su `summary.json`, obtenido en el momento de cierre del logger. La verificación de que todas las corridas de un batch comparten `code_version` es un paso obligatorio del procedimiento (§10.5.2, paso 5).

Se establece además una **política estricta de cuarentena de datos**: ningún vuelo anterior al **2026-09-03** se incluye en el análisis estadístico formal del capítulo 11. Los registros previos estuvieron expuestos a tres artefactos instrumentales ya corregidos que afectaban directamente **lo que el modelo veía**:

1. **Inversión de canales de color R/B** en toda captura de AirSim: el modelo tomó decisiones sobre imágenes con los canales rojo y azul intercambiados durante toda la vida previa del proyecto.
2. **Persistencia de líneas de depuración** dibujadas por `plot_mission_route.py` en el fotograma enviado al VLM, interpretadas por el modelo como estructuras físicas.
3. **Supresión espuria de los ángulos de *pitch* y *roll*** en las notas cinemáticas del prompt.

Las corridas en cuarentena **no se descartan como evidencia**: siguen siendo válidas para establecer que una geometría es volable y que un corredor es transitable. Pero sus métricas de `slm_invocations`, `deliberation_rate` e histograma de rutas **no son comparables** con corridas posteriores al fix, y por tanto no entran a ninguna prueba estadística. La magnitud del efecto de los fixes justifica la severidad de la política: la `deliberation_rate` de `townsim_clear` cayó de 15.4 % (pre-fix) a 0.82 % (post-fix), una reducción de ×19 que ninguna diferencia entre brazos podría igualar.

### 10.9.4 Publicación

El conjunto de validación de TTC (cap. 7, 3735 registros), los archivos de telemetría del batch definitivo, los manifiestos de misión y la configuración completa (`config/.env`) serán archivados y publicados con un identificador digital persistente (DOI vía Zenodo), acompañados del hash de commit correspondiente, garantizando la auditabilidad y reproducibilidad de los resultados.

*(Para la especificación formal del archivo `settings.json`, el perfil de escalabilidad, la estructura detallada de los manifiestos de misión JSON y el protocolo de ejecución paso a paso, véase el [Anexo 6](anexos/A6-CONFIGURACION-ENTORNO-REPRODUCIBILIDAD.md)).*

---

## 10.10 Plan extendido de pruebas

La batería base de §10.3 es el mínimo necesario para responder H1–H3. Esta sección esboza los experimentos adicionales que el diseño admite sin cambios estructurales, ordenados por relación aporte/costo.

### 10.10.1 Extensiones de Tier 0 (MiniSim)

| Diseño | Qué aporta |
|---|---|
| `minisim_clear` × `REACTIVE_FORWARD_SPEED ∈ {2, 5, 7}` m/s × 5 semillas | Establece la **frontera de viabilidad temporal** del brazo `slm`: a qué velocidad la latencia de deliberación deja de ser absorbible por el avance cauto. Los umbrales de TTC son de tiempo, no de distancia, por lo que en teoría el margen de reacción no se degrada con la velocidad; este experimento verifica o refuta esa afirmación empíricamente. Es el experimento de mayor valor por costo de toda la lista. |
| `minisim_clear` × `--seed-jitter` × 10 semillas, tres brazos | Convierte la semilla en factor manipulado (§10.4.3). En un entorno **sin obstáculos**, la objeción del teletransporte no aplica, de modo que Tier 0 es el único tier donde el jitter es metodológicamente seguro. Permite estimar la **varianza atribuible a condiciones iniciales** y separarla de la varianza intrínseca del §10.4.2. |

### 10.10.2 Extensiones de Tier 1 (TownSim)

| Diseño | Qué aporta |
|---|---|
| Patrón de tránsito T-CALIB-2 alineado con el límite entre bloques ($y \approx 32$, PROVISORIO) | Complementa T-CALIB-2: escenario donde **la solución correcta es lateral** en lugar de escalar. Permite medir si el `slm` elige la lateral correcta con mayor frecuencia que el azar — la forma más directa de contrastar H1 sin confundirla con la capacidad de ganancia de altura. Requiere validación previa de la coordenada $y$. |
| Tramo largo sin obstáculos hacia el este, ~370 m × 5 semillas | Segunda medición del costo fijo por brazo en el mismo tier, con geometría distinta a `townsim_clear`. Permite verificar que la razón $t_{\text{slm}}/t_{\text{reactive}}$ de Tier 1 es una propiedad del tier y no del recorrido perimetral particular. |
| `townsim_calib_cruce_frontal` × $z \in \{-10, -15, -20, -25\}$ m × 5 semillas | Convierte la altitud en factor experimental. Traza la **curva de transición** entre el régimen donde el escape por altura resuelve el bloqueo y el régimen donde no, e identifica la altitud a la que la diferencia entre brazos es máxima. |
| `townsim_ini` × {mediodía, atardecer, nublado} vía `simSetTimeOfDay` × 5 semillas | Ataca la vulnerabilidad de la percepción monocular a cambios de iluminación (cap. 6). El flujo óptico degrada con iluminación baja mientras el reconocimiento semántico del VLM es comparativamente robusto — la ventaja del `slm` debería crecer en condiciones adversas. |

### 10.10.3 Extensiones de Tier 2 (CitySim)

| Diseño | Qué aporta |
|---|---|
| Escenario `citymap_a` con tramos de ancho de corredor decreciente sobre el grid regular | Traza la **curva de degradación de la tasa de éxito en función del ancho del corredor** (Loquercio et al., 2021) — la única forma de responder "¿hasta qué angostura funciona el sistema?" en lugar de "¿funciona?". Es el experimento de mayor valor científico de la lista. |
| `citymap_pilot` con tráfico vehicular y agentes de IA activados × 5 semillas | Introduce **obstáculos móviles**, que el diseño actual no cubre. Es la extensión que más acerca el protocolo a la práctica de la literatura de conducción (Codevilla et al., 2019) y la que mayor costo computacional implica por el aumento de varianza ambiental. |
| `citysim_clear` con ruido inyectado en la estimación de posición del guiado | Aproxima el cañón urbano real, donde la degradación de GPS es el modo de falla dominante (cap. 1). Mide cuánto de la fiabilidad observada depende de un guiado con posición exacta. |

### 10.10.4 Extensiones transversales

| Diseño | Qué aporta |
|---|---|
| Los tres escenarios de bloqueo × {Qwen2.5-VL-3B, un VLM alternativo de tamaño comparable} × 5 semillas | Separa lo que es propiedad de **la arquitectura del sistema** de lo que es propiedad del modelo concreto. Sin este experimento, toda conclusión sobre el brazo `slm` está condicionada a un único modelo — la limitación de validez externa más seria del diseño actual. |
| `townsim_calib_cruce_frontal` y `citymap_pilot` × $K = 10$ semillas | **Mayor retorno estadístico por hora de máquina**: eleva el $p$ mínimo alcanzable de $7.9\times10^{-3}$ a $1.1\times10^{-5}$ únicamente en las dos celdas donde la comparación es central (§10.4.4). |
| Repetición completa del batch de Tier 0 en una segunda sesión de simulador, mismo `code_version` | Mide directamente el **efecto de sesión** declarado en §10.5.1. Valida la decisión de comparar tiers sólo mediante razones normalizadas. Costo bajo y pertinencia alta para la validez interna del diseño. |

### 10.10.5 Priorización

Si el presupuesto sólo permite un subconjunto, el orden de prioridad es: (1) elevación de $K$ a 10 en los escenarios decisivos —única vía para obtener significancia con el diseño actual—, (2) curva de degradación `citymap_a` —mayor valor científico—, (3) barrido de velocidad en Tier 0 —frontera de viabilidad temporal, costo mínimo—, (4) reproducibilidad entre sesiones —validez interna—. Las restantes son deseables pero no condicionan las conclusiones de la tesis.

---

## 10.11 Amenazas a la validez

El protocolo tiene cuatro limitaciones conocidas que se declaran explícitamente y se arrastran a las conclusiones del capítulo 12:

1. **Potencia estadística.** Con $K = 5$, ninguna comparación puede superar el umbral de Bonferroni salvo separación perfecta (§10.4.4). Todo resultado no significativo del lote base debe leerse como "no detectado con esta potencia", nunca como "ausente". La mitigación es la elevación de $K$ a 10 en las celdas decisivas (§10.10.4).
2. **Validez externa respecto del modelo.** Todas las conclusiones sobre el brazo `slm` son conclusiones sobre Qwen2.5-VL-3B cuantizado, no sobre "modelos de lenguaje pequeños" en general. La mitigación es la comparación de modelos descrita en §10.10.4.
3. **Efecto de sesión entre tiers.** Los tres batches corren en sesiones y proyectos distintos, de modo que las comparaciones absolutas entre tiers no son limpias (§10.5.1). La mitigación parcial es el uso de razones normalizadas; la mitigación completa es la repetición de un batch en segunda sesión descrita en §10.10.4.
4. **Ausencia de obstáculos dinámicos.** Todo el diseño asume geometría estática. Las conclusiones no se extienden a entornos con agentes móviles, que es precisamente el escalón de dificultad que la literatura de conducción autónoma identifica como decisivo (Codevilla et al., 2019). La mitigación es la extensión con agentes de IA descrita en §10.10.3.

Ninguna de estas limitaciones invalida el diseño para las preguntas que sí responde; todas acotan el alcance de lo que puede afirmarse a partir de él.
