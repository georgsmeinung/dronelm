# 10. Metodología experimental

Este capítulo especifica el protocolo experimental con el que se evalúa la hipótesis central de la tesis: si una capa deliberativa sobre percepción monocular aporta un beneficio medible sobre una heurística rígida en la capa táctica de un dron autónomo, y a qué costo. La pregunta se responde con dos instrumentos. El **banco de prueba a bordo** (§10.13) mide, fuera de vuelo y contra etiquetas de referencia, si una fuente —el VLM o la red de profundidad estimada— sabe responder la pregunta que el lazo lento le hace. Los **lotes de vuelo** (§10.5) miden si el sistema completo, con la fuente que pasa el banco, vuela mejor que una máquina de estados y que un controlador reactivo.

La estructura del capítulo responde a un orden deliberado: primero *qué se quiere probar* (§10.1), luego *con qué factores* (§10.2), *sobre qué escenarios* (§10.3), *con cuántas repeticiones y por qué* (§10.4), *organizado en qué lotes* (§10.5), *midiendo qué* (§10.6), *analizado cómo* (§10.7–§10.8), *dejando qué evidencia* (§10.9) y *qué queda fuera* (§10.10–§10.11). §10.12 detalla lo propio de los lotes con obstrucción y §10.13 describe el banco de prueba. El capítulo 11 consume directamente esta especificación: las métricas primarias y las comparaciones están fijadas aquí antes de existir los datos, para evitar el sesgo de elegirlas después de verlos.

---

## 10.1 Preguntas experimentales e hipótesis operativas

El diseño no persigue una única comparación global "SLM vs. FSM", sino tres preguntas separables, cada una con su propia condición de falsación:

**H1 — Beneficio de la capa deliberativa.**
En escenarios donde la trayectoria directa está obstruida por geometría que exige decidir un rodeo (elegir entre dos corredores, anticipar que una fachada continua no tiene salida lateral), el brazo `slm` alcanza un SPL superior al de una FSM con significancia estadística.
*Condición de falsación:* si en los escenarios con obstrucción la FSM iguala o supera al `slm` en SPL, la capa deliberativa no aporta, y el resultado negativo es igualmente publicable.

**H2 — Costo de la arquitectura.**
El sobrecosto temporal del brazo `slm` no escala con la distancia recorrida sino con la **frecuencia de consulta del lazo lento** (`deliberation_rate`): es aproximadamente un término aditivo $N_{\text{inv}} \times \bar{\ell}$ (número de consultas por su costo medio en la misión), no un factor multiplicativo sobre el tiempo de misión.
*Condición de falsación:* si el ratio $t_{\text{slm}} / t_{\text{reactive}}$ es aproximadamente constante entre escenarios de control en lugar de decrecer con la longitud de la ruta, la hipótesis es incorrecta y el costo sí es multiplicativo.

**H3 — Estratificación del beneficio por dificultad ambiental.**
El signo del efecto de H1 depende del escenario: en ambientes despejados la capa deliberativa solo agrega costo; el beneficio, de existir, aparece únicamente donde la geometría exige una decisión que la heurística no puede tomar. La hipótesis operativa es que **existe una interacción entre el factor "brazo" y el factor "escenario"**, no un efecto principal uniforme del brazo.

Esta última hipótesis es la que dicta la arquitectura de escenarios en tres niveles, cada uno con un escenario de control despejado: sin controles no hay forma de separar el costo fijo del brazo `slm` de su beneficio condicional, y sin escenarios con obstrucción genuina no hay forma de que el beneficio se manifieste. El diseño es, en este sentido, deudor directo de la práctica establecida en los *benchmarks* de conducción autónoma y navegación encarnada, donde la dificultad se estratifica explícitamente en niveles y cada nivel se corre un número fijo de episodios: CARLA organiza sus tareas en cuatro niveles crecientes (recta, un giro, navegación, navegación con tráfico dinámico) sobre el mismo simulador ([Dosovitskiy et al., 2017](13-REFERENCIAS.md#ref-dosovitskiy-2017)), y su sucesor *NoCrash* define tres niveles de densidad de agentes dinámicos (`Empty`, `Regular`, `Dense`) con 25 episodios por tarea y condición ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)). La estratificación por densidad de obstáculos es también la forma canónica de reportar navegación aérea de alta velocidad en bosque simulado ([Loquercio et al., 2021](13-REFERENCIAS.md#ref-loquercio-2021)), donde la métrica se informa en función de la densidad de árboles por metro cuadrado en lugar de agregarse en un único número.

---

## 10.2 Diseño factorial

### 10.2.1 Factor principal: brazo de decisión (`AGENT_ARM`)

La evaluación compara tres brazos de decisión sobre **el mismo `ObstacleField`** (cap. 6), **el mismo espacio de macro-acciones** y **el mismo traductor a comandos cinemáticos** (`action_to_command`, cap. 8). Esta invariancia es lo que hace legítima la comparación: la diferencia entre brazos es *quién elige la macro-acción y quién decide los rodeos*, no qué percibe el sistema ni cómo ejecuta la decisión.

- **`slm`** — el grafo de control con sus dos lazos (cap. 5). El lazo lento, cada ≥ 1 s o de inmediato cuando el lazo rápido ve un muro de frente, juzga qué sectores de una grilla de 3×3 del fotograma frontal son volables; la respuesta se traduce a una sub-meta en coordenadas del mundo anclada a la pose del fotograma, y el dron nunca se detiene a esperarla. En un deadlock, un barrido panorámico de 4 rumbos produce la sub-meta de salida; ante una falla, escape vertical. La fuente del juicio es `STRATEGIC_SOURCE` (§10.2.2): en los lotes, la red de profundidad estimada (cap. 6, §6.14). El nombre del brazo designa la arquitectura con capa deliberativa; con la configuración de los lotes el VLM no interviene en vuelo y solo planifica la ruta antes del despegue en TownSim y CitySim (cap. 4, §4.3.1). No hay reglas deterministas que reescriban la respuesta de la fuente.
- **`fsm`** — una máquina de estados finitos explícita (`CRUISE → AVOID_LEFT | AVOID_RIGHT | CLIMB | BRAKE → CRUISE`), con transiciones gobernadas por umbrales fijos sobre el mismo `ObstacleField`, y su propia lógica de atasco y escape (cap. 5, §5.11). Es la línea de base directa: alta predictibilidad y costo computacional mínimo, sin capa deliberativa.
- **`reactive`** — navegación guiada al waypoint con flujo óptico y TTC, sin deliberación ni resolución de atascos: **cota inferior de rendimiento** que permite desacoplar qué porción del desempeño proviene de la capa táctica y cuánto del seguimiento cinemático de base. Su varianza entre semillas es además el control negativo del diseño (§10.4.1).

El brazo se selecciona por variable de entorno `AGENT_ARM`, leída **a nivel de módulo** en `src/agents/graph.py`. Los tres brazos comparten el mismo bucle externo, el mismo `WaypointTracker` y el mismo nodo `motor` (ancla de altitud y gobernador de velocidad). Esta decisión de implementación tiene una consecuencia metodológica directa: **cada corrida debe correr en un intérprete propio**, porque reutilizar el proceso arrastraría el primer valor leído. El runner lanza por eso un subproceso por corrida, lo que además aísla el fallo de una corrida del resto del lote.

### 10.2.2 Factores secundarios: resolución de atascos (`DEADLOCK_STRATEGY`) y fuente de la capa estratégica (`STRATEGIC_SOURCE`)

**Resolución de atascos.** Ante un deadlock declarado, barrido panorámico **dentro del lazo de control** (`SCAN_HEADING_COUNT_DEEP = 4` rumbos, `SCAN_SETTLE_CYCLES_DEEP = 2` ciclos de asentamiento por rumbo, hasta `MAX_DEEP_SCAN_IMAGES = 5` imágenes) y una única consulta que juzga cada imagen; el código fija una sub-meta en el rumbo transitable elegido (cap. 5, §5.12). Sin respuesta válida, escape vertical. Valores:

- **`depth`** (default): los rumbos los juzga la profundidad estimada (p5 del sector central ≥ 15 m).
- **`deep_vlm`**: los juzga el VLM (alternativa; no se usa en los lotes).
- **`blind`**: sin barrido; escape vertical determinista (`GANAR_ALTURA`) en el brazo `slm` y alternancia `CLIMB`/`DESCEND` propia en el brazo `fsm`.

El brazo `reactive` nunca declara atasco.

**Fuente de la capa estratégica** (solo brazo `slm`): `depth` (default), `vlm` u `off` (sin capa). Se selecciona con `--strategic-sources`; con el argumento, las celdas se nombran `strat_<fuente>__<estrategia>`. Los lotes la fijan en `depth`.

**Advertencia de diseño: el barrido es común a `slm` y `fsm`.** Con `depth`, la FSM delega sus deadlocks en el mismo barrido que el brazo `slm`. La comparación `slm:depth` vs. `fsm:depth` aísla, por lo tanto, la capa estratégica y la política del lazo rápido, no la resolución de atascos. El brazo sin barrido es `fsm:blind`, que solo se corre donde hay atascos que resolver (§10.12.2).

### 10.2.3 Estructura de celdas

La celda elemental es la tupla (escenario × brazo × estrategia de atasco), que el runner recibe como `--cells brazo:estrategia`. Cada celda se replica con $K = 10$ semillas (§10.4.4):

| Celda | Qué aísla | Escenarios despejados | Escenarios con obstrucción |
|---|---|---|---|
| `slm:depth` | El sistema completo: capa estratégica + política del lazo rápido del brazo `slm` + barrido | ✓ | ✓ |
| `fsm:depth` | La misma resolución de atascos con profundidad, sin capa estratégica y con política FSM | ✓ | ✓ |
| `fsm:blind` | La FSM sin barrido (escape determinista) | — | ✓ |
| `reactive` | Flujo óptico + TTC, sin deliberación | ✓ | ✓ |
| **Corridas por escenario** | | **30** | **40** |

---

## 10.3 Escenarios: contenido, particularidad y dificultad

El protocolo define una jerarquía en tres niveles crecientes de dificultad ambiental, cada uno sobre un **proyecto de Unreal Engine distinto** (cap. 3), con un escenario de control despejado por nivel y uno o dos escenarios con obstrucción en los niveles 1 y 2.

### 10.3.0 Principios de diseño comunes a todos los escenarios

Cuatro principios metodológicos gobiernan la construcción de cualquier escenario, y explican por qué los manifiestos tienen la forma que tienen:

1. **Prohibición de teletransporte cinemático.** El campo `start_pose` está inhabilitado en la ruta de producción: todas las misiones despegan desde el *PlayerStart* nativo del nivel de Unreal Engine y ejecutan un ascenso vertical controlado previo a la navegación horizontal. La razón es que `simSetVehiclePose(ignore_collision=True)` es un reposicionamiento instantáneo que **no verifica colisión**, con lo que un escenario podría materializar el dron dentro de un edificio o a centímetros de un tronco, generando variación entre corridas que nada tiene que ver con la política de control evaluada. La consecuencia de diseño es que un escenario que necesita empezar lejos del *spawn* se arma como **misión de varios tramos**: un tramo de tránsito a altitud validada hasta el punto de interés, y recién allí el tramo de prueba a nivel de calle.
2. **Ninguna coordenada se inventa sobre el PNG del mapa.** Los mapas registrados de TownSim y CitySim (cap. 4, §4.3.2) sirven para planificar la ruta y ubicar waypoints candidatos, pero no reemplazan la verificación en vuelo. Toda coordenada nueva se deriva **por interpolación de coordenadas ya voladas y confirmadas**, o se verifica ubicando el dron en ella; la imagen se usa sólo cualitativamente (disposición relativa de plaza, bloques, corredor, avenida). Las coordenadas obtenidas por subdivisión geométrica —no por vuelo— se marcan explícitamente como **PROVISORIAS** y no entran a un lote sin pasar el protocolo de validación del punto 4.
3. **Exclusión total de profundidad del lazo de vuelo.** Ni el grafo, ni `main.py`, ni el runner leen el canal de profundidad del simulador: ni como entrada de control, ni como freno, ni como criterio de aborto. Cualquier uso de esa señal dentro del lazo, aun «solo para observabilidad», abre un canal por el que la profundidad del simulador —de la que salen las etiquetas de referencia— puede terminar alimentando al brazo evaluado (cap. 9, §9.8.5). Una guardia automatizada (`tests/test_no_depth_in_flight_path.py`) cubre el runner, `main.py` y todos los módulos de vuelo. La única lectura de profundidad de una corrida es la **auditoría de la distancia mínima a obstáculo** (§10.6.1): un hilo aislado, con su propia conexión al simulador, que solo escribe un archivo de muestras; la misma guardia verifica que no importe ningún módulo del grafo y que el runner se limite a arrancarlo y detenerlo.
4. **Protocolo de validación previo obligatorio.** Antes de que un escenario entre a un lote: (a) se redacta el manifiesto en `airsim-plan/missions/flightplans/`; (b) se dibuja la ruta con `scripts/plot_mission_route.py` y se confirma en el *viewport* de UE que la línea cruza donde el escenario pretende (fachada para los de obstrucción, calle abierta para los de control); (c) se corre una **misión piloto** (`slm:depth`, una semilla) y se exige el criterio de pase del escenario (§10.12.2) —o, si no completa, que el motivo sea instructivo (atasco genuino) y no un error de geometría; (d) recién entonces se lanza el lote completo. El criterio es explícito: *si ninguna celda puede tener éxito en el escenario, no tiene sentido gastar el presupuesto del lote*.

Una consecuencia práctica del punto 4 es la limpieza obligatoria de estado antes de cada corrida: el runner invoca `client.reset()` (que devuelve el vehículo a la pose de *spawn* de `settings.json` y limpia colisión/velocidad del controlador interno) y `client.clear_debug_markers()` (que descarta las primitivas persistentes dibujadas por `plot_mission_route.py`, las cuales de otro modo aparecen en el fotograma que recibe la capa estratégica, cap. 9 §9.6.2).

---

### 10.3.1 Tier 0 — MiniSim: línea de base y control

**Entorno.** Proyecto base de Unreal Engine 5.5: un plano liso con textura de tablero, sin relieve, edificaciones ni vegetación. Iluminación uniforme y una textura de suelo con contraste suficiente para que el estimador de flujo óptico produzca campo denso, sin ninguna estructura vertical en la trayectoria. Sin obstáculos, la recta entre waypoints es la ruta óptima, de modo que el escenario vuela sin plan de ruta (`--route-plan off`). La distancia mínima a obstáculo que se mide ahí (§10.6.1) es la distancia al suelo.

**Escenario `minisim_clear` (`MINISIM_CLEAR`, lote 1).**

| WP | x (m) | y (m) | z (m, NED) | Rol del tramo |
|---|---|---|---|---|
| WP_1 | 60.0 | 0.0 | −10.0 | Crucero recto de 60 m |
| WP_2 | 60.0 | 60.0 | −10.0 | Quiebre de rumbo de 90° |
| WP_3 | 0.0 | 60.0 | −10.0 | Segundo tramo recto de 60 m |

Recorrido nominal en "L": 120 m entre waypoints declarados, ~180 m contando el tramo desde el *spawn* hasta WP_1. Altitud constante de −10 m.

**Qué se quiere probar.** Este escenario **no busca ejercitar la evasión** — busca medir lo que un escenario con obstáculos no permite medir limpiamente:

1. **Cota inferior de latencia de ciclo** y consumo cinemático ideal del sistema, sin ninguna contribución del lazo de evasión.
2. **Costo puro del brazo `slm` sin beneficio compensatorio.** Es el escenario donde H2 se mide en su forma más cruda: cualquier segundo de diferencia entre `slm` y `reactive` es sobrecosto neto de la arquitectura, porque no hay nada que decidir.
3. **Tasa de falsos positivos de percepción.** En un campo sin obstáculos, *todo* evento de evasión y *todo* deadlock son, por construcción, falsos positivos. Es una medida directa de la especificidad del predicado `is_blocked()` (cap. 6, §6.9) en condiciones benignas — una métrica que ningún escenario con obstáculos puede aislar.
4. **Fidelidad del quiebre de rumbo de 90°.** El giro entre WP_1 y WP_2 ejercita la guardia de rotación del estimador de flujo (`FLOW_MAX_ROTATION_DEG = 2°`) y la derotación analítica por IMU (cap. 6, §6.5). Un pico espurio de evasiones concentrado en ese tramo —visible en `summary_by_wp.csv`— indicaría que la derotación no está compensando el giro.

**Particularidad y dificultad.** Es el único escenario donde el resultado esperado es *desfavorable* a la hipótesis principal: se espera que `reactive` gane por amplio margen y que `slm` sea el más lento. Su dificultad no es de navegación sino de **interpretación**: sirve para calibrar cuánto del desempeño observado en Tier 1 y 2 es atribuible al escenario y cuánto al costo estructural del brazo.

---

### 10.3.2 Tier 1 — TownSim (`townsim_ortho.png`): vegetación y morfología orgánica

**Entorno.** Entorno semiurbano construido sobre el *Downtown West Modular Pack* (PurePolygons). De norte a sur: una plaza con rotonda y jardín circular, y luego **tres bloques rectangulares de edificios en fila**, cada uno separado del siguiente por una calle transversal. Cada bloque tiene dos filas de edificios (oeste y este) con un **pasaje peatonal central** entre ambas. Una avenida ancha sale hacia el este, aproximadamente a la altura del límite entre la plaza y el primer bloque. Todo el complejo está rodeado de bosque denso; hay un cuerpo de agua al sur, fuera del complejo.

La geometría métrica del complejo se deriva exclusivamente de una misión volada y confirmada (`TOWNSIM_CALIB_0`, 656 m, `success = True`, 0 colisiones):

- El complejo mide **≈156 m de norte a sur** ($y \in [-71, +84]$) y **≈146 m de ancho** desde el eje del corredor central ($x \approx 0$) hasta el borde oeste exterior ($x \approx -146$).
- Centroide del complejo: $x \approx -73$, $y \approx 6.5$.
- Con tres bloques repartidos en tercios sobre el rango norte-sur (≈52 m por bloque), los límites entre bloques quedan aproximadamente en $y \approx -19$ e $y \approx 32$ — **subdivisión PROVISORIA**, sujeta a confirmación visual.

**La particularidad que define a este tier** es que sus obstáculos son de **morfología orgánica y semitransparente**: follaje, arboledas densas, mobiliario urbano. A diferencia de una fachada plana, una copa de árbol produce un campo de flujo óptico de alta frecuencia y baja coherencia — el estimador de FOE pierde inliers, la confianza cae, y el sistema entra en el régimen donde la evidencia geométrica es ambigua. Es el régimen donde un juicio sobre el fotograma completo (la capa estratégica) debería aportar sobre la reacción al flujo. Un riesgo específico es el ascenso: si el guiado combina ascenso y traslación lateral, el dron cruza la copa de los árboles todavía bajo y se engancha en el follaje; por eso el despegue es vertical (cap. 5, §5.15).

#### Escenario 1.A — `townsim_clear` (control de crucero largo, lote 2)

Perímetro completo del complejo, 6 waypoints, ~640 m, altitud de tránsito −30 m (por encima de la línea de tejados). Derivado directamente de `TOWNSIM_CALIB_0`: mismos 6 waypoints, misma geometría verificada por vuelo.

**Qué se quiere probar.** Rol análogo al de `minisim_clear` en Tier 0, pero con una diferencia crítica: **la ruta es 3.3× más larga**. Es el escenario que permite testear H2 de forma directa — si el costo del lazo lento es aditivo en el número de consultas y no multiplicativo en la distancia, el ratio $t_{\text{slm}}/t_{\text{reactive}}$ debe caer sustancialmente respecto de Tier 0.

**Dificultad.** Baja en términos de navegación (a −30 m el dron sobrevuela los tres bloques en lugar de negociarlos), pero **alta en términos de duración**: expone al sistema a la deriva acumulada del estimador y a la degradación por GPU compartida entre UE y las redes del lazo lento.

#### Escenario 1.B — `townsim_ini` (recorrido con vegetación en ruta, lote 3)

Travesía norte–sur del corredor peatonal arbolado central de TownSim, arrancando en el *PlayerStart* real (0,0), con dos particularidades estructurales. Primera: **WP_0_ASCENSO sube en el lugar** (mismo $x,y$ del *spawn*, hasta −30 m) antes de trasladarse, para no cruzar la copa de los árboles durante el ascenso. Segunda: **WP_0b_SOBRE_PLAZA** (−60, 5, −22) cruza la plaza central a 22 m de altitud, porque la ruta directa a −10 m atraviesa la copa de los árboles del patio (12–15 m de altura) y el dron entra en la malla de colisión antes de llegar al corredor. Recién entonces desciende a nivel de calle (−10 m): WP_1_ENTRADA_NORTE (−75, 10) entra por el extremo norte, entre los edificios norte y centro; **WP_1b_PASO_MOLDURA** (−70, 0) lo desplaza 8 m al este del saliente de cornisa del edificio oeste (x ≈ −78, y ≈ −14), donde, sin ese desplazamiento, las maniobras de evasión y el sesgo del controlador reactivo lo dejan trabado (960 ciclos sin salir de y ≈ −14 en una corrida piloto); WP_2_CENTRO_CORREDOR (−75, −35) cruza la zona de mayor densidad de árboles y WP_3_SALIDA_SUR (−75, −70) alcanza la avenida sur. WP_4 sale al este subiendo a −30 m y WP_5 regresa al punto de partida. La ruta total es de ~340 m (8 waypoints).

**Qué se quiere probar.** Es el escenario de **interés real** de Tier 1: cruza el interior del complejo por un corredor vegetado e incorpora los tramos de mayor dificultad del tier —el corredor bajo la copa de los árboles y el paso junto a la moldura del edificio oeste—. El desglose `summary_by_wp.csv` es aquí la herramienta central: permite aislar el comportamiento de cada tramo (ascenso, cruce de la plaza, entrada al corredor, paso de la moldura, cruce central) de la fase de crucero.

**Dificultad.** Media-alta. La obstrucción no es un muro sino un dosel: el sistema debe decidir con evidencia geométrica degradada.

#### Escenario 1.C — `townsim_calib_cruce_frontal` (bloqueo frontal masivo, lote 4)

| WP | x (m) | y (m) | z (m) | Rol |
|---|---|---|---|---|
| WP_1 | −150.0 | 0.4 | −30.0 | Tránsito de ida a altitud validada |
| WP_2 | −150.0 | 0.4 | −10.0 | Descenso **fuera** del complejo, en bosque abierto |
| WP_3 | 0.0 | 0.4 | −10.0 | **Cruce real a nivel de calle** contra la fila de edificios oeste |

**Qué se quiere probar.** Este es el escenario diseñado explícitamente para **forzar la activación de la capa estratégica y de la resolución de atascos**. El tramo WP_2→WP_3 pone al dron a nivel de calle frente a una fachada continua, obligándolo a elegir entre `GANAR_ALTURA` (sobrevolar) y un corredor lateral. La estructura de tres tramos no es arbitraria: los dos primeros son **tránsito a geometría ya verificada**, necesarios sólo porque el teletransporte está prohibido; el único tramo sin verificar —y el único que efectivamente prueba algo— es el tercero.

**Particularidad.** Es el escenario donde H1 se manifiesta más claramente: si la FSM resuelve el bloqueo escalando por encima del edificio y el `slm` lo resuelve encontrando la calle transversal, ambos tendrán `success = True` pero con SPL muy distintos. **Por eso la métrica primaria de los escenarios con obstrucción no es el éxito sino el SPL** — la diferencia de calidad entre soluciones aparece en la longitud de la trayectoria, no en el binario de llegada.

**Dificultad.** Alta y deliberada: se espera una tasa de atascos apreciable en `slm` y `fsm`, lo que ejercita el barrido de resolución de bloqueos.

---

### 10.3.3 Tier 2 — CitySim (`citysim_ortho.png`): cañones urbanos

**Entorno.** Proyecto de Unreal Engine 5.5 basado en el *Sample City* de Epic Games: tejido edilicio masivo en cuadrícula ortogonal regular, con edificios de **50 a 100 m de altura**, pasos restringidos y cañones urbanos angostos.

**La particularidad que define a este tier** es doble. Primero, la **altura de los obstáculos convierte a la altitud en variable de diseño de primer orden**: a diferencia de TownSim, donde −30 m basta para sobrevolar todo, en CitySim la maniobra `GANAR_ALTURA` deja de ser una salida universal — un escape por altura desde −20 m no despeja un edificio de 80 m. Segundo, la **regularidad y uniformidad de la textura urbana** es adversa para la percepción monocular: dos calles paralelas de ancho idéntico producen campos de flujo casi indistinguibles, y las fachadas repetitivas degradan el emparejamiento denso de DIS. Como en TownSim, el VLM planifica la ruta sobre el mapa cenital registrado antes del vuelo (`--route-plan vlm`, cap. 4, §4.3.1).

#### Escenario 2.A — `citysim_clear` (control: perímetro de manzana en rampa, lote 5)

Perímetro de una manzana del grid regular, **4 waypoints**, ~420 m. La altitud crece en rampa a lo largo del perímetro —WP_1 a −10 m, WP_2 a −30 m, WP_3 a −50 m— y el último tramo vuelve a −10 m en WP_4, sobre el punto de partida. Los cambios de altitud se hacen en diagonal, combinados con el avance horizontal.

**Qué se quiere probar.** Rol de control del tier, análogo a `minisim_clear` y `townsim_clear`: el costo de la arquitectura en tránsito libre, ahora entre edificios altos y con cambios de altitud en cada tramo. Si los tres brazos lo completan sin colisiones, la ruta no presenta obstrucciones a esas altitudes y cualquier atasco en el escenario de corredores de este tier es atribuible a la geometría del corredor.

#### Escenario 2.B — `citysim_pilot` (circuito de corredores, lote 6)

Circuito en grilla urbana a −10 m de altitud constante, atravesando corredores entre edificios en lugar de sobrevolarlos (manifiesto `citysim_pilot.json`, cap. 4 §4.3). Tres elementos del manifiesto merecen explicación:

- **Mapa `citysim_ortho.png`** (cap. 4 §4.3.2): mosaico cenital construido con el propio simulador, registrado con el marco NED por construcción. Sobre él se planifica la ruta antes del vuelo (cap. 4 §4.3.1).
- **`start_pose`** en el *spawn* real (0, 0, yaw 90°), que solo se usa con `--seed-jitter` (§10.4.3).
- **Waypoints verificados en el simulador.** Cada waypoint se comprueba ubicando el dron en él a −10 m y midiendo la profundidad en las cuatro direcciones y hacia abajo. `WP_0_SUR` (3, −51, −10) está en el centro de la calle este-oeste que sale del *spawn*, con la fachada del edificio sur a 13 m, y evita la autopista elevada; `WP_3` (67.7, −156.5, −10) está en el centro de la calle oeste de la manzana que separa WP_2 de WP_3, con fachadas a unos 7 y 10 m. WP_1, WP_2 y WP_5 quedan a 1.6–2.6 m por encima del tablero de la autopista elevada que cruza la zona a la altura de crucero (cap. 9, §9.8.7). El tramo WP_2 → WP_3 en línea recta atraviesa esa manzana (x ≈ 50–92 m, y ≈ −146 a −112 m): es el rodeo que la misión obliga a resolver.

**Qué se quiere probar.** Es el escenario terminal de la batería: **rodear edificios y elegir corredor**. Ni el `reactive` ni la FSM tienen un juicio sobre el fotograma para elegir entre dos calles de ancho similar; su decisión se reduce a distancia pura o a la asimetría accidental del flujo óptico. La hipótesis es que el brazo `slm`, al juzgar con la profundidad estimada qué sectores del fotograma están libres a 15 m, elegirá el rodeo con mayor consistencia.

**El resultado negativo es igualmente válido y está previsto por diseño**: si la capa estratégica no aporta en un entorno de textura urbana uniforme, ése es un hallazgo relevante sobre los límites de la percepción monocular en entornos repetitivos.

**Dificultad.** Máxima de la batería. A −10 m entre edificios de 50–100 m, el escape por altura está efectivamente vetado (`MAX_ESCAPE_ALT_M = 30 m` no despeja la línea de tejados), lo que **elimina la salida universal de la FSM** y obliga a una decisión lateral genuina. Es, en consecuencia, el escenario donde H1 tiene la mayor potencia discriminativa y donde se espera la mayor tasa de fallo absoluto en todas las celdas.

---

### 10.3.4 Síntesis de la batería

| Lote | Tier | Entorno (proyecto UE) | Escenario | Rol | Long. óptima | Altitud | Dificultad esperada | Hipótesis que ejercita |
|---|---|---|---|---|---|---|---|---|
| 1 | 0 | MiniSim (plano sin obstáculos) | `minisim_clear` | Control / cota inferior | ~180 m | −10 m | Nula | H2, H3 (costo puro) |
| 2 | 1 | TownSim (`townsim_ortho.png`) | `townsim_clear` | Control de crucero largo | ~640 m | −30 m | Baja | H2 (dilución del costo) |
| 3 | 1 | TownSim | `townsim_ini` | Vegetación en ruta | ~340 m | −30/−22/−10 m | Media-alta | H1 |
| 4 | 1 | TownSim | `townsim_calib_cruce_frontal` | Bloqueo frontal masivo | ~320 m | −30/−10 m | Alta | **H1** |
| 5 | 2 | CitySim (`citysim_ortho.png`) | `citysim_clear` | Control en rampa sobre el perímetro de una manzana | ~420 m | −10/−30/−50 m | Baja | H2, H3 |
| 6 | 2 | CitySim | `citysim_pilot` | Rodeo de manzanas y elección de corredor | ~336 m | −10 m | **Máxima** | **H1, H3** |

---

## 10.4 Semillas: por qué varias y qué cambia cada una

### 10.4.1 Por qué se requieren múltiples semillas

Una corrida única no permite ninguna inferencia. La razón no es formal sino sustantiva: **el sistema bajo prueba es estocástico en varios puntos independientes** (§10.4.2), y una diferencia observada entre dos corridas únicas es indistinguible de la varianza intrínseca del entorno. La práctica de reportar resultados de agentes secuenciales a partir de pocas corridas está bien documentada como fuente sistemática de conclusiones no reproducibles ([Henderson et al., 2018](13-REFERENCIAS.md#ref-henderson-2018); [Colas et al., 2018](13-REFERENCIAS.md#ref-colas-2018)), y el problema se agrava exactamente en el régimen de este trabajo: **pocas corridas por celda, porque cada corrida cuesta minutos de tiempo real de simulación** ([Agarwal et al., 2021](13-REFERENCIAS.md#ref-agarwal-2021)).

Hay tres funciones distintas que cumplen las semillas en este diseño, y conviene no confundirlas:

1. **Función inferencial.** Sin réplicas no hay distribución muestral, y sin distribución muestral no hay prueba de hipótesis. Las pruebas no paramétricas del §10.7 operan sobre las distribuciones de las $K$ semillas de cada celda.
2. **Función de robustez.** Un brazo que tiene éxito en 10 de 10 semillas es cualitativamente distinto de uno que tiene éxito en 6 de 10, aun con el mismo tiempo medio. La **tasa de éxito sobre semillas** es en sí misma la métrica primaria de fiabilidad, análoga al `success rate` sobre episodios de los *benchmarks* de conducción ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)).
3. **Función de detección de acoplamiento.** Si dos semillas del brazo `reactive`, sin deliberación, producen trayectorias idénticas al milímetro, el entorno no está aportando la variación que se supone que aporta, y las semillas no son réplicas independientes. La varianza del brazo `reactive` funciona así como **control negativo del propio diseño experimental**: es la medida de cuánta variabilidad introduce el entorno sin intervención de la capa deliberativa.

### 10.4.2 Qué cambia realmente una semilla

Este punto exige precisión, porque la implementación tiene un matiz que es fácil de reportar mal. En la configuración de los lotes (**sin** `--seed-jitter`), la variable `AIRSIM_SEED` **no perturba deliberadamente ningún parámetro del sistema**: se propaga al `FlightLogger` como etiqueta de identificación de la corrida. El runner llama `client.reset()`, que devuelve el vehículo a su pose de *spawn* original definida en `settings.json`, y no vuelve a reposicionarlo.

En consecuencia, **una semilla identifica una réplica independiente, no una condición distinta**. La variación entre semillas proviene íntegramente de la estocasticidad intrínseca del sistema, que tiene cinco fuentes identificadas:

1. **Jitter temporal del lazo de control.** El lazo corre a `LOOP_HZ = 5.0` con temporización de reloj de pared (`time.sleep(max(0, 1/f - t_ciclo))`). El tiempo de cada ciclo depende de la latencia RPC a AirSim, de la carga de GPU y del planificador del sistema operativo. Un ciclo que se pasa del presupuesto desplaza todos los siguientes: dos corridas idénticas divergen en **qué instante exacto de la trayectoria** se toma cada decisión. Con `REACTIVE_FORWARD_SPEED = 3.0 m/s`, 20 ms de desfase equivalen a 6 cm de desplazamiento por ciclo, que se acumulan.
2. **Renderizado y física no reproducibles cuadro a cuadro.** Unreal Engine no garantiza determinismo cuadro a cuadro bajo carga variable de GPU; la física de AirSim avanza en tiempo real, no en pasos fijos sincronizados con el cliente. El fotograma capturado en el ciclo $n$ no es bit a bit el mismo entre corridas, y el estimador de flujo óptico —que opera sobre diferencias de intensidad a nivel de píxel— amplifica esas diferencias.
3. **Sensibilidad del estimador de flujo a condiciones iniciales.** El cálculo de FOE por mínimos cuadrados ponderados con rechazo de *outliers* (RANSAC-lite, `FOE_OUTLIER_ANGLE_RAD = 0.35`) es una función no lineal del campo de flujo. Pequeñas diferencias en el conteo de inliers cruzan el umbral de confianza diferenciada (< 30 vs. ≥ 30 inliers), lo que cambia el estado epistémico reportado por `ObstacleField` y, con él, qué regla de `navigate_node` decide el ciclo. Es un sistema con **realimentación**: una decisión distinta cambia la pose, que cambia el fotograma siguiente, que cambia la decisión siguiente.
4. **Inferencia de las redes del lazo lento.** La red de profundidad es determinista salvo diferencias numéricas mínimas de la GPU, pero recibe fotogramas distintos (fuente 2) en instantes distintos (fuente 1). El VLM no interviene en vuelo; en TownSim y CitySim planifica la ruta una vez por escenario, con temperatura 0 y caché por contenido, de modo que todas las semillas y celdas de un lote vuelan el mismo plan (cap. 4, §4.3.1). Si se usara el VLM en vuelo (`STRATEGIC_SOURCE = vlm`), su muestreo (`temperature = 0.2`, sin semilla fijada en el servidor) sería una fuente adicional exclusiva del brazo `slm`; la determinación de la inferencia en servidores de LLM no está garantizada aun con temperatura cero, porque los kernels no son invariantes al tamaño de lote y este varía con la carga del servidor ([He, 2025](13-REFERENCIAS.md#ref-he-2025)).
5. **Deriva temporal de las respuestas asíncronas.** Que una respuesta estratégica llegue antes o después de su edad máxima (10 s), o de que el dron supere la sub-meta que produciría, y que un barrido se resuelva antes o después de su watchdog (`SLM_DEEP_WATCHDOG_MS`), depende de la latencia de la red en ese instante; el mismo fotograma puede producir un rodeo en una corrida y nada en otra. Cambia cualitativamente qué decide el ciclo.

Estas cinco fuentes se acumulan multiplicativamente sobre una misión de miles de ciclos. La divergencia entre dos semillas de la misma celda es, por tanto, real y sustancial — pero es **estocasticidad no controlada**, no un factor manipulado.

### 10.4.3 El modo de perturbación controlada y por qué no es el modo por defecto

El runner ofrece un modo alternativo (`--seed-jitter`) en el que la semilla **sí** determina una condición distinta y reproducible: siembra un `random.Random(seed)` que genera un desplazamiento de la pose inicial de $\pm 1.5$ m en $x$ e $y$ y $\pm 10°$ en guiñada (`SEED_JITTER_XY_M`, `SEED_JITTER_YAW_DEG`). Es el análogo directo de las *sticky actions* introducidas en la revisión del Arcade Learning Environment para inyectar estocasticidad controlada y evaluar la robustez de una política en lugar de su capacidad de memorizar una trayectoria ([Machado et al., 2018](13-REFERENCIAS.md#ref-machado-2018)).

**Este modo está deshabilitado por defecto, y la razón es una decisión metodológica explícita.** El jitter se aplica vía `simSetVehiclePose(ignore_collision=True)`, un teletransporte que no verifica colisión: con $\pm 1.5$ m de desplazamiento, el dron puede materializarse más cerca de un poste o un tronco que en el *spawn* limpio de AirSim, introduciendo variación entre corridas que **no proviene de la política de control sino de la posición del obstáculo más cercano al punto de partida**. Eso viola el principio de no teletransporte del §10.3.0 y contamina la comparación entre brazos: la corrida "difícil" le tocaría a un brazo por sorteo, no por diseño.

La consecuencia se asume y se declara: **en los lotes, la variación entre semillas es la variación intrínseca del entorno, y la comparación entre brazos es una comparación de réplicas independientes bajo condiciones iniciales nominalmente idénticas.** El modo con jitter se reserva para el plan extendido (§10.10), donde se lo trata como un factor experimental propio y se lo valida antes de usarlo — verificando en el *viewport* que ninguna de las poses sorteadas cae dentro de un obstáculo.

### 10.4.4 Número y asignación de semillas

Se ejecutan **$K = 10$ semillas por celda**. El número lo impone la potencia estadística. Con $K$ semillas por grupo, el $p$-valor mínimo alcanzable de la prueba de rangos (bilateral, sin empates) es $2/\binom{2K}{K}$: con $K = 5$ sería 0.0079, de modo que ninguna comparación podría sobrevivir la corrección de Bonferroni del §10.7 ($\alpha_{\text{ajustado}} \approx 0.0028$) ni siquiera con separación perfecta; con $K = 10$ baja a $1.1 \times 10^{-5}$, holgadamente por debajo del umbral corregido. El límite superior lo impone el presupuesto de tiempo real (§10.5.4).

**Asignación.** Las semillas son los primeros 60 números primos, sin repetir entre lotes (diez por lote, en orden). Dentro de cada semilla, las celdas se alternan, con el orden rotado de una semilla a la siguiente (`runner.py --cells`): la deriva del simulador a lo largo de horas (temperatura de la GPU, fragmentación de memoria de UE) se reparte así entre celdas en lugar de concentrarse en la que corre al final.

**El reporte no se apoya sólo en el $p$-valor**: se informan tamaños de efecto con intervalo de confianza *bootstrap* y las distribuciones completas, que es la práctica recomendada precisamente para el régimen de pocas corridas ([Agarwal et al., 2021](13-REFERENCIAS.md#ref-agarwal-2021)). Un tamaño de efecto grande con un intervalo de confianza ancho es información útil y honestamente reportable; un $p$-valor no significativo **no es evidencia de ausencia de efecto**, y así se lo declara en el capítulo 11.

---

## 10.5 Organización en lotes

### 10.5.1 Por qué un lote por escenario, agrupados por nivel de Unreal Engine

Los tres tiers corresponden a **tres proyectos de Unreal Engine distintos** (MiniSim, TownSim y CitySim, §10.3), cada uno con su propio nivel, su propio *PlayerStart* y su propio `settings.json` de AirSim. El cliente de AirSim se conecta por RPC a la instancia de UE que esté corriendo en ese momento; **no existe forma programática de cambiar de proyecto desde el runner**. Un escenario de Tier 1 lanzado contra el nivel de Tier 0 no falla con un error legible: vuela sobre el terreno equivocado y produce una corrida silenciosamente inválida.

La unidad de ejecución es el **lote**: todas las corridas de un escenario (sus celdas × 10 semillas). Seis escenarios dan seis lotes, y solo se corren juntos los lotes del mismo nivel de UE: 1 | 2, 3, 4 | 5, 6. La organización tiene dos consecuencias metodológicas favorables:

1. **Aísla la fuente de contaminación cruzada más peligrosa.** Todas las corridas de un lote comparten el mismo nivel, la misma configuración de escalabilidad gráfica y la misma sesión de UE. Comparar entre celdas *dentro* de un lote es por tanto una comparación limpia.
2. **Obliga a declarar el análisis entre lotes como comparación de segundo orden** (§10.8.3): los tiers no comparten sesión de simulador, de modo que las diferencias absolutas entre tiers arrastran un efecto de sesión no controlado, y sólo las **razones normalizadas dentro de cada lote** (p. ej. $t_{\text{slm}}/t_{\text{reactive}}$) son comparables entre lotes.

### 10.5.2 Procedimiento por lote

Cada lote se ejecuta según la siguiente secuencia, en este orden estricto:

1. **Árbol confirmado.** El runner no arranca con cambios sin commitear en `airsim-loop/`, `config/`, `airsim-plan/` o `experiments/` (termina con código 2), de modo que todas las corridas de un lote llevan el mismo `code_version` (§10.9.3). Tampoco arranca con otro intérprete de Python que el de `AIRSIM_ENV_DIR` en `config/.env` (Anexo 6).
2. **Preparación del entorno.** Abrir en Unreal el nivel del escenario y aplicar el perfil de escalabilidad documentado en el capítulo 3 (`Config/DefaultScalability.ini`, con las sombras necesarias para que la estimación de TTC disponga de los gradientes que usa el flujo). En los lotes 2 a 6, Ollama debe responder en `127.0.0.1:11434` para el plan de ruta (`startOllama.ps1`; el script del lote lo verifica): el runner calcula el plan una vez por escenario antes de la primera corrida y todas las corridas del lote vuelan ese plan. En el lote 1 (`--route-plan off`) el servidor puede quedar cerrado y su VRAM queda para Unreal (Anexo 6). La red de profundidad la carga el propio grafo al compilarse (~19 s).
3. **Higiene de estado.** El runner ejecuta `client.reset()` y `client.clear_debug_markers()` al inicio de cada corrida. No se depende de que el operador recuerde limpiar los marcadores de `plot_mission_route.py`.
4. **Piloto de validación.** En los lotes con obstrucción (3, 4 y 6), una corrida `slm:depth` con la semilla 99, revisada contra el criterio de pase del escenario antes de lanzar el lote (§10.12.2). Los pilotos se guardan aparte y no entran al análisis.
5. **Lote completo.** Un subproceso por corrida (escenario × celda × semilla), con las celdas alternadas dentro de cada semilla (§10.4.4). Un lote cortado se reanuda con `-Resume`, que saltea las corridas válidas ya hechas.
6. **Análisis.** `airsim-loop/experiments/analyze_lotes.py` sobre la raíz de los seis lotes (§10.7).

### 10.5.3 Celdas, semillas y presupuesto de cada lote

Los scripts de los lotes están versionados en `experiments/` (`run_lotes.ps1` define el diseño; cada `run_loteN_*.ps1` lo llama con su número). El diseño completo es:

| Lote | Escenario | Nivel UE | Celdas | Corridas | Semillas | Plan de ruta | Tiempo estimado |
|---|---|---|---|---|---|---|---|
| 1 | `minisim_clear` | MiniSim | `slm:depth`, `fsm:depth`, `reactive` | 30 | 2 3 5 7 11 13 17 19 23 29 | off | ~1.5 h |
| 2 | `townsim_clear` | TownSim | ídem | 30 | 31 37 41 43 47 53 59 61 67 71 | vlm | ~3 h |
| 3 | `townsim_ini` | TownSim | ídem + `fsm:blind` | 40 | 73 79 83 89 97 101 103 107 109 113 | vlm | ≤ 11.5 h |
| 4 | `townsim_calib_cruce_frontal` | TownSim | ídem + `fsm:blind` | 40 | 127 131 137 139 149 151 157 163 167 173 | vlm | ≤ 14 h |
| 5 | `citysim_clear` | CitySim | `slm:depth`, `fsm:depth`, `reactive` | 30 | 179 181 191 193 197 199 211 223 227 229 | vlm | ~2 h |
| 6 | `citysim_pilot` | CitySim | ídem + `fsm:blind` | 40 | 233 239 241 251 257 263 269 271 277 281 | vlm | ≤ 12 h |
| **Total** | | | | **210** | | | **~44 h** (peor caso) |

En los lotes despejados el tiempo estimado es el típico (las corridas terminan en pocos minutos); en los de obstrucción, el peor caso, con las celdas que se traban agotando el presupuesto.

### 10.5.4 Presupuesto por corrida y ejecución

Todas las corridas tienen el mismo techo: **1200 s / 6000 ciclos**. Es el mismo en todos los escenarios y holgado, para que una celda lenta falle por el obstáculo y no por el tiempo; las corridas exitosas terminan antes, y el techo solo alarga las que se traban. A `LOOP_HZ = 5`, con el lazo cumpliendo su presupuesto, se agota antes el tiempo que los ciclos; el límite de ciclos protege el caso patológico opuesto —un lazo que se acelera porque las capturas fallan silenciosamente—.

Los lotes se lanzan desde `experiments/`, en PowerShell:

```powershell
.\run_lote3_townsim_ini.ps1 -Pilot    # piloto -> airsim-runs\produccion\v4\pilotos\lote3_townsim_ini
.\run_lote3_townsim_ini.ps1           # lote completo
.\run_lote3_townsim_ini.ps1 -Resume   # reanudar un lote cortado
.\run_lotes.ps1 -Lotes 2,3,4          # varios lotes del mismo nivel de UE
```

Cada script llama a `runner.py` con `--scenarios`, `--cells`, `--seeds`, `--out-dir`, `--max-seconds 1200`, `--max-cycles 6000` y `--route-plan`; las opciones `-SeedJitter` y `-NoVideo` agregan `--seed-jitter` y `--no-video`.

---

## 10.6 Métricas reportadas

Todas las métricas se derivan del registro por ciclo del `FlightLogger` y se consolidan en el `summary.json` de cada corrida (cap. 4, §4.4).

### 10.6.1 Eficacia y seguridad de vuelo

- **Tasa de éxito de misión** (`success`): arribo a todos los waypoints dentro del presupuesto de ciclos y segundos. Es un binario por corrida; sobre $K$ semillas se convierte en una proporción, que se informa con su intervalo de Wilson al 95 %.
- **Colisiones** por misión y **normalizadas por kilómetro** recorrido. La normalización es necesaria porque los escenarios difieren en longitud por un factor de 3.3×.
- **Motivo de terminación** (`termination_reason`): éxito, tope de tiempo o de ciclos, colisión, o `physics_locked` (el vigilante de congelamiento detectó el estado físico idéntico durante 25 ciclos: dron incrustado en la malla, cap. 5 §5.19). `physics_locked` cuenta como falla de misión, igual que una colisión.
- **Distancia mínima a obstáculo** (`min_obstacle_dist_m`, DistMin): la mide un **hilo de auditoría aislado** durante el vuelo. Con su propia conexión al simulador, cada `DISTMIN_TRACK_PERIOD_S` (1 s, una muestra cada 5 ciclos) captura la profundidad `DepthPlanar` de la cámara frontal y toma el percentil 5 del tercio central de la imagen; DistMin es el mínimo sobre la corrida. Las muestras se escriben en `<corrida>.distmin.ndjson` y `finalize_run` vuelca el mínimo en el `summary.json` al cerrar la corrida. El hilo no comparte ningún objeto con el grafo, de modo que la medición no puede influir en el control (§10.3.0, punto 3).
- **SPL** (*Success weighted by Path Length*), en su definición estándar para agentes de navegación ([Anderson et al., 2018](13-REFERENCIAS.md#ref-anderson-2018)): $\text{SPL} = S \cdot \ell_{\text{opt}} / \max(\ell_{\text{real}}, \ell_{\text{opt}})$, con $S$ el indicador de éxito. La longitud óptima $\ell_{\text{opt}}$ se computa como la suma de distancias euclídeas entre waypoints consecutivos del manifiesto: no es un camino volable en presencia de obstáculos, pero es la referencia estándar y, sobre todo, es **idéntica para todas las celdas**, que es lo que la comparación requiere. El SPL es la única métrica que penaliza simultáneamente no llegar y llegar dando vueltas, y es por eso la métrica primaria de los escenarios con obstrucción.

  > **Sesgo conocido del cálculo.** `analyze.py` (que usa también `analyze_lotes.py`) computa $\ell_{\text{opt}}$ sumando únicamente las distancias entre waypoints **declarados en el manifiesto**, sin incluir el tramo desde el *spawn* hasta el primer waypoint, que sí queda contabilizado en $\ell_{\text{real}}$. En `minisim_clear` ese tramo son 60 m sobre 120 m declarados: el SPL queda subestimado en aproximadamente un tercio. El sesgo es **constante por escenario e idéntico para todas las celdas**, de modo que no invalida ninguna comparación dentro de un lote, pero sí impide interpretar el valor absoluto del SPL y compararlo entre escenarios. Se reporta en consecuencia el SPL como métrica **relativa dentro de cada lote**.
- **Tiempo y ciclos totales** a destino.

### 10.6.2 Dinámica del lazo táctico y latencias

- **Latencia total por ciclo** ($p_{50}$ y $p_{95}$), desagregada por brazo y por **ruta activa del grafo de control** (`reactive`, `evasive`, `girar_90`, `deliberative` —barrido—, `tactical` —escape vertical—, `fsm`, `degraded`). El $p_{95}$ es la métrica relevante para la viabilidad en tiempo real: un $p_{50}$ aceptable con un $p_{95}$ que excede el presupuesto de ciclo describe un sistema que cumple "en promedio" y falla justo cuando importa.
- **Histograma de rutas** por corrida: la distribución de ciclos entre nodos del grafo. Es la caracterización más informativa del comportamiento cualitativo de un brazo — una corrida mayormente `reactive` describe un vuelo que sobrevoló los obstáculos en lugar de negociarlos, independientemente de lo que digan sus métricas de éxito.
- **`deliberation_rate`**: fracción de ciclos con una consulta nueva del lazo lento. Se contabiliza por **transición de identificador único de deliberación**, cualquiera sea la ruta del ciclo; sin esa distinción, una consulta que abarca varios ciclos de espera se contaría múltiples veces. Incluye las consultas de la capa estratégica, que se resuelven mientras el dron vuela por la ruta reactiva o evasiva.
- El **escaneo espacial pre-vuelo** (`spatial_scan`, cap. 5 §5.0) solo lo ejecuta `main.py`; el runner no lo corre, de modo que no interviene en ninguna corrida experimental.

### 10.6.3 Comportamiento del lazo lento

- **Consultas efectivas por misión** (`slm_invocations`).
- **Tasa de *fallback*** (`slm_fallback_rate`) ante respuestas inválidas o fuera de esquema, y **tasa de *timeout*** (`slm_timeout_rate`).
- **Distribución de resultados de la capa estratégica**, a partir de las entradas `arm = "depth_strategic"` de `deliberations[]`: fracción de respuestas que proponen sub-meta, que declaran el camino directo libre (`directo_libre`), sin sector libre, vencidas, superadas o no parseables. Complementa al banco de prueba (§10.13), que mide si la fuente **discrimina** contra etiquetas de referencia: una capa que declara `directo_libre` en casi todas las consultas, incluso cuando el dron termina en deadlock, no está aportando información.
- **Avance hacia el waypoint real tras cada sub-meta**: distancia al waypoint de misión (no a la sub-meta) en el momento de la inyección y 20 s después. Es la medida directa de si las sub-metas ayudan a completar la misión: una sub-meta que no acerca al waypoint real en ese plazo es un desvío sin beneficio.
- **Avance en waypoints del plan a tiempos de referencia** y **segundos a menos de 1 m de un obstáculo** por tramo (con la posición de cada muestra de DistMin), calculados por `analyze_strategic_batch.py`.

### 10.6.4 Resolución de atascos

- **`deadlock_events`**: número de atascos declarados.
- **`deep_scan_resolution_rate`**: fracción de atascos resueltos por el barrido.
- **`deep_scan_avg_cycles_to_resolve`**: costo medio en ciclos de una resolución exitosa.
- **`deep_scan_fallback_rate`**: fracción de atascos donde el barrido no resolvió y se cayó al escape vertical.

Estas cuatro métricas sólo tienen valor conjunto: una tasa de resolución alta con un costo de ciclos desmesurado no describe un mecanismo exitoso sino uno caro. «Resuelto» significa que la fuente del barrido encontró un rumbo transitable y se fijó una sub-meta, **no** que el dron haya salido del atasco; por eso se reporta además el avance hacia el waypoint real tras cada resolución.

### 10.6.5 Desglose espacial por waypoint

Cada corrida emite `<stem>.summary_by_wp.csv` con ciclos consumidos, duración, ciclos deliberativos, tasa de deliberación y eventos de barrido **por tramo de misión**. Es la herramienta que permite aislar los tramos de ascenso vertical de las fases de crucero y maniobra horizontal: sin este desglose, una métrica agregada de misión atribuye a "el escenario" una dificultad que puede pertenecer a un solo tramo de 20 segundos, como el ascenso inicial entre follaje de `townsim_ini`.

---

## 10.7 Protocolo estadístico

El análisis lo implementa `airsim-loop/experiments/analyze_lotes.py`, que escribe `analisis_lotes.md` y dos CSV en la raíz de los lotes:

```powershell
D:\TesisMCD\airsimenv\python.exe ..\airsim-loop\experiments\analyze_lotes.py ..\airsim-runs\produccion\v4 --family 18
```

### 10.7.1 Métricas primarias y comparaciones planificadas

La métrica primaria se declara por tipo de escenario antes de ver los datos:

- **Lotes despejados (1, 2 y 5):** tiempo de las misiones exitosas (H2). Comparaciones: `slm`–`fsm`, `slm`–`reactive` y `fsm`–`reactive`.
- **Lotes con obstrucción (3, 4 y 6):** SPL (H1). Comparaciones: `slm:depth` vs. `fsm:blind`, `fsm:depth` vs. `fsm:blind` y `slm:depth` vs. `fsm:depth` (§10.12.2).

Tres comparaciones por lote y seis lotes forman la familia de 18 comparaciones primarias.

### 10.7.2 Pruebas de hipótesis

Cada comparación primaria usa una **prueba de permutación exacta sobre rangos** (bilateral), equivalente a la U de Mann-Whitney exacta ([Mann & Whitney, 1947](13-REFERENCIAS.md#ref-mann-1947)) pero válida con empates, frecuentes en SPL porque todas las corridas fallidas tienen SPL = 0. Hipótesis nula: la distribución de la métrica no difiere entre las dos celdas.

La elección de pruebas no paramétricas no es una precaución de rutina: es una necesidad del tipo de dato. Las distribuciones de tiempo de misión están **truncadas por la derecha** por el presupuesto (una corrida que se agota registra el presupuesto, no su tiempo real), y las de SPL tienen una masa en cero; ninguna prueba que asuma normalidad es defendible sobre esos datos.

**Secundarias, sin corrección y rotuladas como tales:** el éxito (prueba exacta de Fisher y diferencia de tasas con intervalo de Newcombe al 95 %) y la distancia mínima al obstáculo (delta de Cliff y la misma prueba de rangos).

### 10.7.3 Tamaños de efecto

Se reporta **Cliff's Delta** ($\delta$) para toda comparación ([Cliff, 1993](13-REFERENCIAS.md#ref-cliff-1993)), definido como la proporción de pares en que una muestra domina a la otra: $\delta = 2U/(n_A n_B) - 1$, con un intervalo de confianza *bootstrap* percentil (5000 remuestreos de corridas dentro de cada celda). Se adopta la escala de interpretación de [Romano et al. (2006)](13-REFERENCIAS.md#ref-romano-2006): $|\delta| < 0.147$ despreciable, $0.147$–$0.330$ pequeño, $0.330$–$0.474$ mediano, $\geq 0.474$ grande.

El tamaño de efecto no es un complemento decorativo del $p$-valor: **es el resultado principal cuando $K$ es pequeño**. Un $p$ significativo con $\delta$ despreciable describe una diferencia real de magnitud práctica nula; un $\delta$ grande con $p$ no significativo describe un efecto que el diseño no tuvo potencia para detectar, no un efecto ausente. Ambos casos se reportan explícitamente como tales.

### 10.7.4 Comparaciones múltiples

Se aplica **corrección de Bonferroni** sobre la familia de 18 comparaciones primarias: $\alpha = 0.05/18 \approx 0.0028$. Con $K = 10$, una separación perfecta da $p = 1.1 \times 10^{-5}$ y pasa la corrección.

La corrección se aplica **sólo a las comparaciones declaradas antes de ver los datos**. Cualquier comparación adicional sugerida por la inspección de los resultados se reporta como **exploratoria**, sin pretensión de significancia — la alternativa (corregir sobre una familia que crece a medida que se exploran los datos) sería a la vez estadísticamente incorrecta y prácticamente inútil.

### 10.7.5 Análisis desagregado

El análisis **no se limita a valores agregados globales**. Se evalúa el rendimiento desagregado por escenario y morfología de obstáculo, porque es la única forma de contrastar H3: la pregunta no es "¿es mejor el `slm`?" sino "¿en qué condiciones lo es, y a qué costo?". Un promedio sobre los seis escenarios mezclaría escenarios donde el brazo `slm` sólo puede perder (los de control) con escenarios donde puede ganar, produciendo un número sin interpretación posible. Es la misma razón por la que los *benchmarks* de conducción reportan por nivel de dificultad en lugar de agregarlos ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)).

---

## 10.8 Análisis esperado y análisis comparativo conjunto

Esta sección declara, **antes de tener los datos**, qué resultado se espera de cada lote y cómo se leerá. Un resultado que contradiga estas expectativas es informativo precisamente porque las expectativas estaban escritas de antemano.

### 10.8.1 Lotes despejados (1, 2 y 5) — qué se espera

El resultado esperado es **desfavorable al brazo `slm` y favorable a la hipótesis H2**:

- Orden esperado de tiempo de misión: `reactive` < `fsm` < `slm`, con $\delta$ grande en la comparación `reactive` vs. `slm` en MiniSim.
- Ratio $t_{\text{slm}}/t_{\text{reactive}}$ decreciente con la longitud de la ruta: mayor en `minisim_clear` (~180 m) que en `townsim_clear` (~640 m). **Ésta es la prueba directa de H2**, y su forma es una comparación de razones, no de valores absolutos.
- Sin diferencias de seguridad: en un campo despejado, ningún brazo puede ser más seguro que otro.
- En `citysim_clear`, cero atascos en las tres celdas confirma que la ruta en rampa (−10 a −50 m) no presenta obstrucciones y que las altitudes son adecuadas.

**Qué invalida la lectura:** cualquier fallo de misión en el lote 1. Sin obstáculos, un fallo indica un problema del sistema (percepción, guiado o infraestructura), no del escenario, y obliga a diagnosticarlo antes de continuar.

### 10.8.2 Lotes con obstrucción (3, 4 y 6) — qué se espera

- **`townsim_ini`**: se espera la primera aparición de una ventaja del `slm` en SPL, concentrada según `summary_by_wp.csv` en los tramos con follaje (corredor y paso de la moldura). Si la ventaja aparece pero está distribuida uniformemente entre tramos, la explicación no es la capa estratégica sino un sesgo sistemático del guiado, y debe investigarse como tal.
- **`townsim_calib_cruce_frontal`**: se espera una tasa de atascos apreciable en `slm` y `fsm`. La lectura esperada es que el `slm` produzca el mejor SPL al resolver el bloqueo lateralmente, mientras la FSM recurre al escape por altura; `fsm:depth` frente a `fsm:blind` mide cuánto aporta el barrido por sí solo.
- **`citysim_pilot`**: es el escenario terminal y el de mayor incertidumbre. Se esperan **tasas de éxito inferiores a 1.0 en todas las celdas** —es el único escenario donde el fracaso es un resultado esperado y no un síntoma— y una mayor dispersión entre semillas. Si la capa estratégica no discrimina entre corredores de textura uniforme, `slm:depth` y `fsm:depth` empatarán, y ese empate es un resultado sustantivo.

**Qué invalida la lectura:** cero atascos en `townsim_calib_cruce_frontal`. Significaría que el tramo de cruce no está encontrando la fachada —error de geometría, no de política— y obligaría a re-validar el manifiesto con `plot_mission_route.py`.

### 10.8.3 Análisis comparativo conjunto

El cruce entre lotes es donde se contrasta **H3**, y exige una precaución declarada en §10.5.1: los lotes de distintos tiers corren en sesiones de simulador distintas y sobre proyectos de UE distintos, de modo que **las diferencias absolutas entre tiers arrastran un efecto de sesión no controlado**. La comparación entre lotes se realiza en consecuencia sobre tres tipos de cantidad, todas normalizadas dentro de su propio lote:

1. **Razones normalizadas por brazo.** $t_{\text{brazo}}/t_{\text{reactive}}$ dentro de cada escenario. Al dividir por el brazo de referencia del mismo escenario y la misma sesión, el efecto de sesión se cancela en primer orden. La progresión de $t_{\text{slm}}/t_{\text{reactive}}$ entre los tres controles es la evidencia central de H2.
2. **Perfil de consulta por dificultad.** `deliberation_rate` y deadlocks en función del escenario. La predicción de H3 es un perfil **no monótono**: bajo en los controles y alto en los escenarios con obstrucción real, con consultas *justificadas*. La distinción entre "alto por ruido" y "alto por necesidad" se hace cruzando `deliberation_rate` con el SPL resultante y con `summary_by_wp.csv`.
3. **Interacción brazo × escenario.** El resultado que sostiene H3 es un **cambio de signo** del efecto `slm` − `fsm` entre los escenarios de control y los de obstrucción. Con la potencia disponible ($K = 10$), esta interacción se reporta como patrón de tamaños de efecto con sus intervalos de confianza, no como una prueba formal de interacción: un ANOVA de dos factores sobre datos truncados y con 10 réplicas no sería defendible.

El producto final del análisis conjunto es una tabla de doble entrada **celda × escenario** con éxito, SPL, tiempo normalizado, seguridad y tasa de consulta, más el conjunto de comparaciones con su $\delta$ e intervalo de confianza. La conclusión de la tesis no es un único número sino ese mapa: **dónde la capa deliberativa paga y dónde no**.

---

## 10.9 Organización de los resultados, auditoría y reproducibilidad

### 10.9.1 Disposición física de los artefactos

Los resultados quedan fuera de git (`airsim-runs/` está en `.gitignore`: los logs, CSV y videos son demasiado pesados), bajo una estructura derivada de los propios factores del diseño:

```
airsim-runs/produccion/v4/
├── loteN_<escenario>/
│   ├── batch_<ts>.log                   # registro del lote
│   └── <escenario>/                     # stem del manifiesto: townsim_ini, citysim_pilot, …
│       ├── route_plan/                  # plan de ruta del escenario (TownSim y CitySim)
│       └── <brazo>/                     # slm | fsm | reactive
│           └── <estrategia>/            # depth | blind
│               └── seed_<N>_<timestamp>/    # una carpeta autocontenida por corrida
│                   ├── seed_<N>_<ts>.jsonl            # DroneState completo ciclo a ciclo
│                   ├── seed_<N>_<ts>.csv              # misma corrida, tabular (columnas state.*)
│                   ├── seed_<N>_<ts>.summary.json     # indicadores agregados
│                   ├── seed_<N>_<ts>.summary_by_wp.csv
│                   ├── seed_<N>_<ts>.distmin.ndjson   # muestras de la auditoría de DistMin (1 Hz)
│                   ├── seed_<N>_<ts>.console.log      # copia de la consola de la corrida
│                   ├── seed_<N>_<ts>.webm / .follow.webm / .viewer.html
│                   └── photo-<timestamp_ISO>.png      # fotogramas de cada consulta del lazo lento
└── pilotos/loteN_<escenario>/           # pilotos de validación, fuera del análisis
```

El contenido de cada archivo —campos de la traza, columnas del CSV, indicadores del resumen— y el uso del visor se describen en el capítulo 4 (§4.4).

La ruta **es** el registro del punto del diseño al que pertenece la corrida: escenario, brazo, estrategia y semilla son directorios, no metadatos que haya que parsear, y ninguna corrida sobrescribe a otra. Los fotogramas de auditoría se nombran por *timestamp* de captura con precisión de milisegundos y se cruzan con la telemetría por el campo `slm_frame_paths` del CSV.

El CSV plano por corrida contiene, además de la cinemática y las lecturas sectoriales del `ObstacleField`, la respuesta cruda de cada consulta del lazo lento (con la profundidad, el p5 por sector), junto al identificador de la entrada correspondiente del JSONL. La decisión de duplicar esa información en el CSV es deliberada: permite analizar el comportamiento de la fuente sin cruzar archivos.

### 10.9.2 Video y visor de auditoría

Tanto las corridas interactivas (`main.py`) como las del runner generan, por defecto, el video anotado de la cámara frontal (`.webm`, VP8, un cuadro por ciclo con superposición de telemetría, TTC por sector y ruta activa), el video de la cámara de seguimiento externa (`.follow.webm`, solo auditoría) y un visor HTML autocontenido que sincroniza ambos videos con la traza por índice de ciclo y muestra el `DroneState` y la consulta del lazo lento de cada ciclo (cap. 4, §4.4). La codificación corre en un hilo aparte para no alterar el período del lazo (cap. 5, §5.18). En lotes largos puede desactivarse con `-NoVideo`.

### 10.9.3 Trazabilidad

Cada corrida incorpora el hash de commit de Git (`code_version`) en su `summary.json`. Si al correr había cambios sin commitear en el código, la configuración, los manifiestos o los scripts de los lotes (`airsim-loop/`, `config/`, `airsim-plan/`, `experiments/`), el valor lleva el sufijo `-dirty`: el hash solo identifica el código si el árbol está limpio. El runner no arranca un lote con el árbol sucio (§10.5.2), y `analyze_lotes.py` toma como referencia el `code_version` del lote y descarta las corridas con otro hash o con sufijo `-dirty` (§10.12.2). Agrupar corridas con software de decisión distinto mezclaría el efecto del software con el de los brazos; por eso solo entran al análisis estadístico las corridas de los seis lotes con el mismo hash. Las corridas piloto de validación y las corridas de diagnóstico del capítulo 9 no entran: son evidencia de diagnóstico.

### 10.9.4 Publicación

El conjunto de validación de TTC (cap. 7, 3735 registros), los archivos de telemetría de los seis lotes, los manifiestos de misión y la configuración completa (`config/.env`) serán archivados y publicados con un identificador digital persistente (DOI vía Zenodo), acompañados del hash de commit correspondiente, garantizando la auditabilidad y reproducibilidad de los resultados.

*(Para la especificación formal del archivo `settings.json`, el perfil de escalabilidad, la estructura detallada de los manifiestos de misión JSON y el protocolo de ejecución paso a paso, véase el [Anexo 6](anexos/A6-CONFIGURACION-ENTORNO-REPRODUCIBILIDAD.md)).*

---

## 10.10 Plan extendido de pruebas

Los seis lotes son el mínimo necesario para responder H1–H3. Esta sección esboza los experimentos adicionales que el diseño admite sin cambios estructurales, ordenados por relación aporte/costo.

### 10.10.1 Extensiones de Tier 0 (MiniSim)

| Diseño | Qué aporta |
|---|---|
| `minisim_clear` × `REACTIVE_FORWARD_SPEED ∈ {2, 5, 7}` m/s × 10 semillas | Establece la **frontera de viabilidad temporal** del brazo `slm`: a qué velocidad la latencia del lazo lento deja de ser absorbible por el avance. Los umbrales de TTC son de tiempo, no de distancia, por lo que en teoría el margen de reacción no se degrada con la velocidad; este experimento verifica o refuta esa afirmación empíricamente. Es el experimento de mayor valor por costo de toda la lista. |
| `minisim_clear` × `--seed-jitter` × 10 semillas, tres brazos | Convierte la semilla en factor manipulado (§10.4.3). En un entorno **sin obstáculos**, la objeción del teletransporte no aplica, de modo que Tier 0 es el único tier donde el jitter es metodológicamente seguro. Permite estimar la **varianza atribuible a condiciones iniciales** y separarla de la varianza intrínseca del §10.4.2. |

### 10.10.2 Extensiones de Tier 1 (TownSim)

| Diseño | Qué aporta |
|---|---|
| Patrón de tránsito de `townsim_calib_cruce_frontal` alineado con el límite entre bloques ($y \approx 32$, PROVISORIO) | Escenario donde **la solución correcta es lateral** en lugar de escalar. Permite medir si el `slm` elige la lateral correcta con mayor frecuencia que el azar — la forma más directa de contrastar H1 sin confundirla con la ganancia de altura. Requiere validación previa de la coordenada $y$. |
| `townsim_calib_cruce_frontal` × $z \in \{-10, -15, -20, -25\}$ m | Convierte la altitud en factor experimental. Traza la **curva de transición** entre el régimen donde el escape por altura resuelve el bloqueo y el régimen donde no, e identifica la altitud a la que la diferencia entre brazos es máxima. |
| `townsim_ini` × {mediodía, atardecer, nublado} vía `simSetTimeOfDay` | Ataca la vulnerabilidad de la percepción monocular a cambios de iluminación (cap. 6): el flujo óptico degrada con iluminación baja, y la profundidad estimada puede degradar de otro modo. |
| Banco de prueba (§10.13) en TownSim | Extiende la validación fuera de vuelo de la profundidad estimada a un segundo entorno (§10.13.5). |

### 10.10.3 Extensiones de Tier 2 (CitySim)

| Diseño | Qué aporta |
|---|---|
| Escenario con tramos de ancho de corredor decreciente sobre el grid regular | Traza la **curva de degradación de la tasa de éxito en función del ancho del corredor** ([Loquercio et al., 2021](13-REFERENCIAS.md#ref-loquercio-2021)) — la única forma de responder "¿hasta qué angostura funciona el sistema?" en lugar de "¿funciona?". Es el experimento de mayor valor científico de la lista. |
| `citysim_pilot` con tráfico vehicular y agentes de IA activados | Introduce **obstáculos móviles**, que el diseño actual no cubre. Es la extensión que más acerca el protocolo a la práctica de la literatura de conducción ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)) y la que mayor costo computacional implica por el aumento de varianza ambiental. |
| `citysim_clear` con ruido inyectado en la estimación de posición del guiado | Aproxima el cañón urbano real, donde la degradación de GPS es el modo de falla dominante (cap. 1). Mide cuánto de la fiabilidad observada depende de un guiado con posición exacta. |

### 10.10.4 Extensiones transversales

| Diseño | Qué aporta |
|---|---|
| Banco de prueba con otros VLM (Qwen2.5-VL-3B y modelos más grandes, fuera del presupuesto de VRAM a bordo) | Separa lo que es propiedad de **la pregunta y la arquitectura** de lo que es propiedad del modelo concreto. Sin este experimento, la conclusión de que el VLM no responde la pregunta del lazo lento está condicionada a un único modelo. |
| Lotes con obstrucción × `STRATEGIC_SOURCE = off` | Aísla la capa estratégica dentro del brazo `slm`, con la misma política de lazo rápido (`slm:depth` con y sin capa). |
| Repetición completa del lote 1 en una segunda sesión de simulador, mismo `code_version` | Mide directamente el **efecto de sesión** declarado en §10.5.1. Valida la decisión de comparar tiers sólo mediante razones normalizadas. Costo bajo y pertinencia alta para la validez interna del diseño. |

### 10.10.5 Priorización

Si el presupuesto sólo permite un subconjunto, el orden de prioridad es: (1) curva de degradación por ancho de corredor —mayor valor científico—, (2) barrido de velocidad en Tier 0 —frontera de viabilidad temporal, costo mínimo—, (3) reproducibilidad entre sesiones —validez interna—, (4) banco de prueba en TownSim y con otros VLM —validez externa de las conclusiones sobre las fuentes—. Las restantes son deseables pero no condicionan las conclusiones de la tesis.

---

## 10.11 Amenazas a la validez

El protocolo tiene cinco limitaciones conocidas que se declaran explícitamente y se arrastran a las conclusiones del capítulo 12:

1. **Potencia estadística.** Con $K = 10$, una separación perfecta supera el umbral de Bonferroni, pero una separación parcial puede no hacerlo. Todo resultado no significativo debe leerse como "no detectado con esta potencia", nunca como "ausente", y se informa con su tamaño de efecto e intervalo.
2. **Validez externa respecto de los modelos.** Las conclusiones sobre el brazo `slm` son conclusiones sobre una red de profundidad concreta (Depth Anything V2 Metric Outdoor Small), y las conclusiones sobre el VLM, sobre LFM2.5-VL-1.6B cuantizado (`lfm2.5-vl-1.6b:q4km-ctx8k`), no sobre "modelos de lenguaje pequeños" en general. La mitigación es la comparación de modelos descrita en §10.10.4.
3. **Efecto de sesión entre tiers.** Los lotes de distintos tiers corren en sesiones y proyectos distintos, de modo que las comparaciones absolutas entre tiers no son limpias (§10.5.1). La mitigación parcial es el uso de razones normalizadas; la mitigación completa es la repetición de un lote en segunda sesión descrita en §10.10.4.
4. **Ausencia de obstáculos dinámicos.** Todo el diseño asume geometría estática. Las conclusiones no se extienden a entornos con agentes móviles, que es precisamente el escalón de dificultad que la literatura de conducción autónoma identifica como decisivo ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)). La mitigación es la extensión con agentes de IA descrita en §10.10.3.
5. **Un escenario por lote.** Cada nivel de dificultad está representado por una o dos rutas concretas. Un efecto observado en un escenario es una propiedad de esa geometría hasta que se replique en otra ruta del mismo tipo; por eso los resultados se informan por escenario (§10.7.5) y la generalización entre escenarios es descriptiva.

Ninguna de estas limitaciones invalida el diseño para las preguntas que sí responde; todas acotan el alcance de lo que puede afirmarse a partir de él.

## 10.12 Lotes con obstrucción

### 10.12.1 Componentes del sistema que ejercen los escenarios con obstrucción

Los escenarios despejados apenas ejercen la capa táctica: el TTC rara vez baja del umbral y los detectores de atasco no disparan. Los escenarios con obstrucción (lotes 3, 4 y 6) sí, y son los que permiten evaluar los componentes del sistema:

| Componente | Comportamiento que se evalúa | Referencia |
|---|---|---|
| Capa estratégica con profundidad estimada | Sub-metas ancladas a la pose del fotograma; si las sub-metas acercan al waypoint real y si alejan al dron de los obstáculos | §5.10, §6.14 |
| Consulta inmediata ante un muro (`GIRAR_90` + `expedite`) | Que el rodeo se decida con el fotograma que ve el muro | §5.9 |
| Barrido en marco mundo (`depth`) | Que la sub-meta de salida apunte a un rumbo transitable y que el dron salga del atasco | §5.12 |
| Detección de atasco de dos señales | Ausencia de deadlocks falsos (despegue, sub-metas nuevas) y presencia de los reales | §5.3.1 |
| Escape vertical cuando el barrido no resuelve | Que libere al dron de estructuras horizontales | §5.3.4 |
| Detección de techo | Altitud limitada bajo estructuras horizontales | §5.15.3 |
| Gobernador de velocidad | Avance limitado sin evidencia perceptual | §5.13 |
| Vigilante de congelamiento | Terminación `physics_locked` | §5.19 |
| Plan de ruta con el VLM sobre el mapa cenital (juicio por parches) | Si el plan elige desvíos libres cuando la recta está bloqueada, en TownSim y CitySim, sobre sus mapas registrados | §4.3.1, §11.0 |
| Manifiestos `townsim_ini` (WP_0b, WP_1b) y `citysim_pilot` (WP_0_SUR) | Evitan la copa de la plaza, la moldura del edificio oeste y la autopista elevada | §10.3.2, §10.3.3 |

Los umbrales de la capa estratégica (período de 1 s con la profundidad, edad máxima de 10 s, sub-meta a 15 m, cambio de altura de 4 m, deduplicación de 10 m) no están calibrados: son decisiones de diseño.

### 10.12.2 Celdas, pilotos, comparaciones y descartes

**Calibración previa.** La fuente del lazo lento pasa por el banco de prueba a bordo (§10.13) antes de llevarse al vuelo: una pregunta se vuela solo si la fuente la responde, contra la etiqueta de referencia, por encima del criterio de pase. Con el resultado del banco (cap. 11, §11.0), las preguntas de la capa estratégica y del barrido las responde la profundidad estimada, y el VLM solo planifica la ruta antes del vuelo (`--route-plan vlm` en TownSim y CitySim).

**Celdas.** Los tres lotes con obstrucción —3 (`townsim_ini`), 4 (`townsim_calib_cruce_frontal`) y 6 (`citysim_pilot`), también llamados D, E y F— agregan a las tres celdas comunes (§10.2.3) la celda `fsm:blind`: la FSM sin barrido, con su escape determinista. Solo se corre donde hay atascos que resolver; en los controles sería idéntica a `fsm:depth`.

**Pilotos y criterios de pase.** Cada lote va precedido por un piloto de validación (`slm:depth`, semilla 99, guardado en `airsim-runs/produccion/v4/pilotos/`). Criterios: en el lote 3, el dron cruza el corredor arbolado; en el 4, rodea el edificio o al menos lo bordea; en el 6, alcanza WP_0_SUR y WP_1 sin quedar trabado sobre la autopista. Un piloto que no cumple su criterio indica una regresión que se diagnostica antes de lanzar el lote.

**Comparaciones planificadas por lote** (métrica primaria: SPL, §10.7.1). (i) `slm:depth` vs. `fsm:blind`: ¿aporta el sistema completo frente a una FSM sin barrido? (ii) `fsm:depth` vs. `fsm:blind`: ¿aporta el barrido con profundidad en la resolución de atascos, con la misma política de lazo rápido? (iii) `slm:depth` vs. `fsm:depth`: ¿aporta la capa estratégica junto con la política del lazo rápido del brazo `slm`? La pregunta «¿aporta el VLM en vuelo?» no es una comparación de estos lotes: la responde el banco (§10.13).

**Métricas adicionales.** Además de las de §10.6: la distribución de resultados de la capa estratégica y el avance hacia el waypoint real tras cada sub-meta (§10.6.3); las señales del `StallDetector` (`_stopped_cycles`, `_wp_no_progress_cycles`, `imu_contact_event`, `blind_wall_event`) y qué señal disparó cada deadlock; los deadlocks en los primeros 30 ciclos (deben ser cero: el despegue no es un atasco, cap. 5 §5.3.1); y la fracción de ciclos con el gobernador de velocidad activo (`_speed_cap`).

**Condiciones de descarte y de invalidación** (para los seis lotes). Se descarta una corrida individual si su `code_version` difiere del de referencia del lote, si termina en `-dirty`, o si tiene menos de 50 ciclos (falla de infraestructura, no del dron); los pilotos no entran al análisis. Se invalida un lote si contiene corridas con hashes distintos que no puedan reemplazarse. Una corrida terminada por `physics_locked` termina con éxito falso y se cuenta como falla de misión, al igual que una colisión.

## 10.13 Banco de prueba a bordo (`vlm_bench`)

### 10.13.1 Qué es y para qué sirve

El banco de prueba es una herramienta de medición **fuera de vuelo**. Responde una pregunta previa a cualquier lote: **¿la fuente del lazo lento sabe responder la pregunta que el lazo le hace?** Por ejemplo, si un sector de la imagen está libre a 15 m, si un rumbo del barrido es transitable o si un tramo de ruta sobre el mapa va por la calle. Para responderla compara, muestra por muestra, la respuesta de la fuente con una **etiqueta de referencia** independiente, calculada con la profundidad del simulador en la misma pose (cap. 7, §7.1).

Un lote de vuelo no puede responder esa pregunta. El resultado de una misión mezcla la percepción con el guiado, el lazo rápido, los atascos y el azar del simulador; con pocas semillas, una fuente que responde al azar puede empatar con una que acierta. El banco aísla el juicio. Si una fuente no lo supera, volarla no puede aportar, y no se lleva al vuelo. Si lo supera, los lotes miden lo que el banco no puede medir: si ese juicio mejora el vuelo (§10.12).

Tres reglas lo mantienen como medición **generalista** y no como ajuste del sistema a un escenario:

1. **Prompts y preguntas fijos**, iguales a los de vuelo e independientes del escenario: no nombran objetos de un entorno.
2. **La respuesta se lee tal como sale.** El criterio de pase usa la etiqueta que la fuente devuelve, sin umbrales calibrados sobre los datos. El AUC, calculado con la probabilidad de cada opción, se informa solo como diagnóstico: indica si hay información que la respuesta no expresa, pero no configura el vuelo.
3. **Pasar en todos los entornos medidos con el mismo prompt.** Por entorno, el criterio es exactitud balanceada ≥ 0.65 y límite inferior del intervalo de confianza del 95 % por encima del azar. El intervalo se calcula por *bootstrap* por corrida: se remuestrean corridas enteras, porque las vistas de una misma corrida no son independientes. Si una pregunta no pasa, se descarta: el modelo no tiene esa capacidad sin entrenamiento, y adaptarla al escenario sería un entrenamiento manual por entorno, lo que el enfoque generalista evita.

### 10.13.2 Cómo está construido

El código está en `airsim-loop/experiments/vlm_bench/` y la tubería completa se ejecuta con `run_all.sh`. Cada etapa es reanudable: si se corta, al relanzarla saltea lo ya hecho.

| Etapa | Módulo | Qué hace |
|---|---|---|
| 1. Muestras | `dataset.py` | Toma las corridas que tienen telemetría y los dos videos (frontal y `FollowCam`) y extrae poses registradas en vuelo (posición, actitud y meta activa). Hay tres clases de muestra: **estratégicas** (cada consulta de la capa estratégica, con la respuesta que dio en vuelo y la foto enviada), **de barrido** (cada rumbo de cada barrido) y **de trayectoria** (ciclos sin consulta, a ≥ 8 m de altura, sin duplicados en celdas de 2 m y 20°: un dron trabado cientos de ciclos cuenta una vez). |
| 2. Etiquetas | `ground_truth.py`, `labels.py` | Ver §10.13.3. Es el único módulo del banco que lee la profundidad del simulador. |
| 3. Preguntas | `questions.py` | Catálogo: para cada pregunta, a qué muestras aplica, cómo arma la imagen y el prompt, su esquema JSON (igual que en vuelo), cuál es la etiqueta verdadera y cómo se lee la respuesta. Las opciones tienen iniciales distintas para leer la probabilidad de cada una en los *logprobs*. |
| 4. Evaluación | `evaluate.py` | Selecciona hasta 60 muestras válidas por clase verdadera (los barridos, todos) y hace cada pregunta con decodificación restringida y temperatura 0. Guarda la respuesta, la probabilidad de cada opción y la latencia. |
| 5. Reporte | `report.py` | Calcula exactitud balanceada con su intervalo, AUC, respuestas constantes, sesgo por posición y acuerdo bajo permutación, y aplica el criterio de pase. Con bancos de varios entornos produce `cross_report.md`. |

Las preguntas del catálogo son:

| Pregunta | Qué pregunta | Para qué está |
|---|---|---|
| `grid_prod` | La pregunta de vuelo de la capa estratégica tal cual: grilla de 3×3, marca de la meta, «libre» o «bloqueado» por sector | Medir la capacidad que usa el vuelo |
| `grid_perm` | La misma, con las etiquetas de los sectores permutadas | Control: si la respuesta no cambia con la permutación, el modelo responde a la posición en la imagen y no a la escena |
| `centro_libre` | ¿Se puede avanzar recto 15 m? (sin grilla) | La forma más simple de la pregunta |
| `borde_lateral` | Con un obstáculo de frente, ¿por qué lado termina? | Información para elegir el rodeo |
| `borde_superior` | Con un obstáculo de frente, ¿hay espacio libre por encima? | Ídem, en vertical |
| `direccion_abierta` | ¿Qué tercio tiene más espacio libre a la altura del dron? | Ídem, como elección |
| `scan_prod` / `scan_perm` | La pregunta de vuelo del barrido con las imágenes de un barrido real, en el orden de vuelo y en otro orden | Medir el barrido y su sesgo por orden |

Cuatro pruebas derivadas usan las mismas muestras o la misma etiqueta para preguntas puntuales:

| Prueba | Módulo | Pregunta |
|---|---|---|
| Mapa | `map_probe.py` | ¿El VLM reconoce qué hay en un parche del mapa cenital (calle o techo)? La etiqueta se obtiene mirando el parche desde 40 m con la profundidad. |
| Rutas | `route_bench.py` | ¿El juicio del planificador de ruta (cap. 4, §4.3.1) separa rutas libres de bloqueadas? La etiqueta recorre la ruta cada 4 m a la altura de vuelo: la ruta es libre si en ningún punto hay un obstáculo a menos de 6 m en la ventana central. |
| Regiones | `region_probe.py` | Si el VLM no juzga distancias en la cámara frontal, ¿reconoce al menos qué hay en cada sector? |
| Profundidad y segmentación | `seg_depth_probe.py` | ¿Dos redes chicas que solo ven el RGB juzgan el espacio libre por sector mejor que el VLM, con la misma geometría y el mismo estadístico que la etiqueta? |

### 10.13.3 Etiquetas de referencia

Cada muestra es una foto o un cuadro de video de una corrida, con la pose del dron registrada en ese instante. Su etiqueta se calcula fuera de vuelo con `ground_truth.py`, una herramienta de laboratorio aislada del lazo, de la misma categoría que la calibración del TTC (cap. 7). El procedimiento tiene cinco pasos:

1. **Reubicar el dron.** Se lleva el dron a la pose exacta (posición y actitud) con la cámara en el campo de visión de vuelo (90°; el cliente rechaza conectarse si el campo de visión fue alterado).
2. **Esperar la carga de la escena.** Unreal carga la escena por zonas y, tras un salto largo, la primera captura puede salir sin edificios. Se repite la captura hasta que la profundidad de cada sector cambia menos de 0.5 m entre dos capturas seguidas.
3. **Capturar y filtrar.** Se capturan la imagen y la profundidad planar. Se descartan las muestras con la cámara dentro de la geometría, con captura inestable o cuya imagen reproducida no coincide con la registrada en vuelo (correlación normalizada < 0.5: la pose no se reprodujo bien, por ejemplo con el dron atravesando una fachada).
4. **Resumir por sector.** Sobre el recorte cuadrado central —el mismo que recibe la fuente en vuelo—, dividido en una grilla de 3×3, se toma el percentil 5 de la profundidad de cada sector: lo más cercano, sin píxeles sueltos.
5. **Etiquetar.** Un sector es **libre** si ese percentil es ≥ 15 m, la misma distancia que se le pide juzgar a la fuente y a la que se fija la sub-meta.

De ahí salen las etiquetas de cada pregunta:
- *Centro libre*: el estado del sector central.
- *Lado por donde termina el obstáculo*: el lado del hueco libre más cercano al centro en la franja a la altura del dron.
- *Espacio libre por encima*: si al menos la mitad del sector superior central está libre.
- *Dirección más abierta*: el tercio de la franja con mayor profundidad mediana, o «ninguna» si ninguno llega a 15 m.

Estas etiquetas solo sirven para medir: nunca entran al lazo de vuelo (§10.3.0, punto 3).

### 10.13.4 Qué decide el banco en la configuración del sistema

Tres componentes del lazo de control salen de lo que el banco mide: la fuente de la capa estratégica, el juicio del barrido y el plan de ruta.

| Medición | Resultado | Consecuencia de diseño |
|---|---|---|
| Juicio de rutas enteras dibujadas sobre el mapa (línea, pasillo, pregunta invertida) | Ningún modelo distingue una ruta por la calle de una sobre un edificio: la respuesta depende de la forma de la pregunta | El planificador no juzga rutas enteras (cap. 4, §4.3.1) |
| `map_probe`: reconocimiento de parches del mapa con cinco clases | LFM2.5-VL-1.6B: AUC 0.80 para «calle»; Qwen2.5-VL-3B: 0.63 | Juicio **por parches** y LFM2.5-VL-1.6B también para el planificador |
| `route_bench`: rutas juzgadas por parches | AUC 0.81 | Plan de ruta activado sobre mapas registrados (`ROUTE_PLAN_MODE=vlm`) |
| `grid_prod` y `scan_prod` con el VLM de vuelo | Ninguna de las ocho preguntas pasa; las filas de arriba y de abajo salen «libres» siempre; el barrido declara todo transitable | El VLM no responde la pregunta del lazo lento; desempate por fila con margen si se usa (`VLM_SUBGOAL_TIE_DEG`, cap. 5 §5.10.3) |
| `region_probe`: reconocimiento por sector en la cámara frontal | No pasa (exactitud 48–49 %; AUC 0.53–0.62) | No se pregunta «qué hay» en lugar de «a qué distancia» |
| `seg_depth_probe`: profundidad monocular y segmentación | Profundidad: 75 % y AUC 0.83 por sector, AUC 0.87 en los barridos; segmentación: AUC 0.50 | La capa estratégica y el barrido usan la profundidad estimada (`STRATEGIC_SOURCE=depth`, `DEADLOCK_STRATEGY=depth`) |

La tabla muestra el uso previsto del instrumento: cada pregunta que no pasa se descarta en lugar de compensarse con reglas, y cada fuente que pasa se lleva al vuelo y se juzga con los lotes. Las cifras completas están en el capítulo 11 (§11.0), y la descripción de la red de profundidad, en el capítulo 6 (§6.14).

### 10.13.5 Alcance y límites

- **Un solo entorno medido.** Las 6926 poses del banco provienen de corridas de `citysim_pilot`; TownSim no tiene banco. El criterio exige pasar en todos los entornos medidos. Para el VLM la conclusión no cambia, porque no pasa ni siquiera en CitySim. Para la profundidad y para el plan de ruta por parches, en TownSim solo los evalúan los lotes de vuelo (lotes 2 a 4). Un banco en TownSim es la extensión pendiente más directa (§10.10.2).
- **Muestras sesgadas hacia los lugares difíciles.** Las muestras estratégicas y de barrido se toman donde el sistema consultó, que suelen ser los tramos con obstáculos; la evaluación equilibra las clases verdaderas para que la exactitud balanceada no dependa de esa proporción.
- **Render sintético.** La etiqueta sale del mismo render que ve la fuente. Una red entrenada en parte con imágenes sintéticas, como la de profundidad, puede rendir menos con una cámara real.
- **Pocos barridos.** 14 y 22 barridos alcanzan para ver que el VLM responde siempre lo mismo, pero no para interpretar su AUC.
