# 10. Metodología experimental

Este capítulo especifica el protocolo con el que se evalúa la hipótesis central: si una capa deliberativa sobre percepción monocular aporta un beneficio medible sobre una heurística rígida en la capa táctica de un dron autónomo, y a qué costo. Hay dos instrumentos. El **banco de prueba a bordo** (IT.10.2) mide, fuera de vuelo y contra etiquetas de referencia, si una fuente —el VLM o la red de profundidad estimada— sabe responder la pregunta que el lazo lento le hace. Los **lotes de vuelo** (IT.10.3–IT.10.5) miden si el sistema completo, con la fuente que pasa el banco, vuela mejor que una máquina de estados y que un controlador reactivo. Las métricas primarias y las comparaciones, y los resultados esperados de cada lote (Anexo 12, IT.A12.8), se fijaron antes de existir los datos. El detalle operativo está en el [Anexo 12](anexos/A12-OPERACION-EXPERIMENTAL.md).

---

## 10.1 Preguntas experimentales e hipótesis operativas

El diseño no persigue una única comparación global "SLM vs. FSM", sino tres preguntas separables, cada una con su propia condición de falsación:

**H1 — Beneficio de la capa deliberativa.**
En escenarios donde la trayectoria directa está obstruida por geometría que exige decidir un rodeo, el brazo `slm` alcanza un SPL superior al de una FSM con significancia estadística.
*Condición de falsación:* si en los escenarios con obstrucción la FSM iguala o supera al `slm` en SPL, la capa deliberativa no aporta, y el resultado negativo es igualmente publicable.

**H2 — Costo de la arquitectura.**
El sobrecosto temporal del brazo `slm` no escala con la distancia recorrida sino con la **frecuencia de consulta del lazo lento**: es aproximadamente un término aditivo $N_{\text{inv}} \times \bar{\ell}$ (número de consultas por su costo medio), no un factor multiplicativo sobre el tiempo de misión.
*Condición de falsación:* si el ratio $t_{\text{slm}} / t_{\text{reactive}}$ es aproximadamente constante entre escenarios de control en lugar de decrecer con la longitud de la ruta, el costo es multiplicativo.

**H3 — Estratificación del beneficio por dificultad ambiental.**
En ambientes despejados la capa deliberativa solo agrega costo; el beneficio, de existir, aparece donde la geometría exige una decisión que la heurística no puede tomar. La hipótesis operativa es que **existe una interacción entre el factor "brazo" y el factor "escenario"**, no un efecto principal uniforme del brazo.

H3 dicta la arquitectura de escenarios en tres niveles, cada uno con un control despejado: sin controles no se puede separar el costo fijo del brazo `slm` de su beneficio condicional, y sin obstrucción genuina el beneficio no puede manifestarse. Es la práctica de los *benchmarks* de conducción y navegación, que estratifican la dificultad en niveles con un número fijo de episodios por nivel ([Dosovitskiy et al., 2017](13-REFERENCIAS.md#ref-dosovitskiy-2017); [Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)) y reportan la navegación aérea en función de la densidad de obstáculos ([Loquercio et al., 2021](13-REFERENCIAS.md#ref-loquercio-2021)).

---

## 10.2 Banco de prueba a bordo (`vlm_bench`)

El banco es una medición **fuera de vuelo** que responde una pregunta previa a cualquier lote: **¿la fuente del lazo lento sabe responder la pregunta que el lazo le hace?** —si un sector de la imagen está libre a 15 m, si un rumbo del barrido es transitable, si un tramo de ruta sobre el mapa va por la calle—. Compara, muestra por muestra, la respuesta de la fuente con una **etiqueta de referencia** calculada con la profundidad del simulador en la misma pose (cap. 7, IT.7.1): un sector es libre si el percentil 5 de su profundidad es ≥ 15 m. Las muestras son poses registradas en corridas reales, y las etiquetas nunca entran al lazo de vuelo (IT.10.4.1, punto 3).

Un lote de vuelo no puede responder esa pregunta: el resultado de una misión mezcla la percepción con el guiado, el lazo rápido, los atascos y el azar del simulador, y con pocas semillas una fuente que responde al azar puede empatar con una que acierta. El banco aísla el juicio. Una fuente que no lo supera no se lleva al vuelo; una que lo supera se juzga después en los lotes. Tres reglas lo mantienen como medición **generalista** y no como ajuste a un escenario: prompts y preguntas fijos, iguales a los de vuelo, que no nombran objetos de un entorno; la respuesta se lee tal como sale, sin umbrales calibrados sobre los datos; y el criterio de pase —exactitud balanceada ≥ 0.65 con el intervalo de confianza del 95 % por encima del azar, con *bootstrap* por corrida— debe cumplirse en todos los entornos medidos. Una pregunta que no pasa se descarta: adaptarla al escenario sería un entrenamiento manual por entorno.

| Medición | Resultado | Consecuencia de diseño |
|---|---|---|
| Juicio de rutas enteras dibujadas sobre el mapa | Ningún modelo distingue una ruta por la calle de una sobre un edificio | El planificador no juzga rutas enteras (cap. 4, IT.4.3.1) |
| Reconocimiento de parches del mapa cenital | LFM2.5-VL-1.6B: AUC 0.80 para «calle»; Qwen2.5-VL-3B: 0.63 | Juicio **por parches** con LFM2.5-VL-1.6B |
| Rutas juzgadas por parches | AUC 0.81 | Plan de ruta activado sobre mapas registrados |
| Pregunta de la capa estratégica y del barrido con el VLM | Ninguna de las ocho preguntas pasa; el barrido declara todo transitable | El VLM no responde la pregunta del lazo lento |
| Reconocimiento por sector en la cámara frontal | No pasa (AUC 0.53–0.62) | No se pregunta «qué hay» en lugar de «a qué distancia» |
| Profundidad monocular y segmentación | Profundidad: 75 % y AUC 0.83 por sector, 0.87 en los barridos; segmentación: AUC 0.50 | La capa estratégica y el barrido usan la profundidad estimada |
| Lote piloto de fuentes: 15 corridas `slm` en `citysim_pilot` con fuentes `depth`, `vlm` y `off`, 5 semillas emparejadas | Avance equivalente en las tres; éxitos 3/5, 4/5 y 5/5 | `depth` sobre `vlm` por latencia (~0.1 s frente a ~0.8 s). Frente a `off`, el lote no muestra ventaja de la capa, pero con 5 pares tampoco puede descartarla; se conserva para juzgarla en la v4 |

Las cifras completas están en el capítulo 11 (IT.11.0) y NB5 recalcula cada fila; la construcción del banco, el etiquetado y sus límites —un solo entorno medido, muestras sesgadas hacia los tramos difíciles, render sintético— están en el Anexo 12 (IT.A12.10).

---

## 10.3 Diseño factorial

### 10.3.1 Factor principal: brazo de decisión

Los tres brazos comparten **el mismo `ObstacleField`** (cap. 6), **el mismo vocabulario de macro-acciones** y **el mismo traductor a cinemática**: la diferencia entre ellos es *quién elige la macro-acción y quién decide los rodeos*. Elegir la macro-acción incluye las reglas del lazo rápido, que no son las mismas en los tres brazos (cap. 5, IT.5.3.3), de modo que cada comparación mide el brazo completo, no la capa deliberativa sola.

- **`slm`** — el grafo con sus dos lazos (cap. 5): el lazo lento juzga, cada ≥ 1 s o de inmediato ante un muro, qué sectores de una grilla de 3×3 son volables y traduce la respuesta a una sub-meta anclada a la pose del fotograma; ante un deadlock, un barrido de 4 rumbos produce la sub-meta de salida. Con el resultado del banco, la fuente es la red de profundidad estimada (cap. 6, IT.6.12): pese al nombre, heredado de versiones anteriores, **ningún modelo de lenguaje decide en vuelo**, y el VLM solo planifica la ruta antes del despegue (cap. 4, IT.4.3.1). Los nombres heredados se explican en el Anexo 12 (IT.A12.1).
- **`fsm`** — una máquina de estados explícita (`CRUISE → AVOID_LEFT | AVOID_RIGHT | CLIMB | BRAKE → CRUISE`) con umbrales fijos sobre el mismo `ObstacleField` y su propia lógica de atasco (cap. 5, IT.5.7): la línea de base directa, predecible y de costo mínimo.
- **`reactive`** — solo guiado al waypoint, **sin evasión**, sin deliberación y sin resolución de atascos: la **cota inferior de rendimiento**. Lo que lo separa de los otros brazos es a la vez la evasión del lazo rápido y la resolución de atascos. Su varianza entre semillas es el control negativo del diseño (IT.10.5.1).

### 10.3.2 Factores secundarios: resolución de atascos y fuente de la capa estratégica

**Resolución de atascos.** Ante un deadlock, un barrido panorámico dentro del lazo y una única consulta que juzga cada rumbo (cap. 5, IT.5.6); sin respuesta válida, escape vertical. Valores: **`depth`** (por defecto; los rumbos los juzga la profundidad estimada), **`deep_vlm`** (los juzga el VLM; evaluado en el banco, no en los lotes) y **`blind`** (sin barrido, escape determinista). **Fuente de la capa estratégica** (solo `slm`): `depth`, `vlm` u `off`; los lotes la fijan en `depth`.

**El barrido es común a `slm` y `fsm`.** Con `depth`, la FSM delega sus deadlocks en el mismo barrido, de modo que `slm:depth` vs. `fsm:depth` aísla la capa estratégica y la política del lazo rápido, no la resolución de atascos. El brazo sin barrido es `fsm:blind`.

### 10.3.3 Celdas y comparaciones planificadas

La celda es la tupla (escenario × brazo × estrategia de atasco), replicada con $K = 10$ semillas (IT.10.5.1):

| Celda | Qué aísla | Escenarios despejados | Escenarios con obstrucción |
|---|---|---|---|
| `slm:depth` | El sistema completo: capa estratégica + política del lazo rápido del brazo `slm` + barrido | ✓ | ✓ |
| `fsm:depth` | La misma resolución de atascos con profundidad, sin capa estratégica y con política FSM | ✓ | ✓ |
| `fsm:blind` | La FSM sin barrido (escape determinista) | — | ✓ |
| `reactive` | Solo guiado: sin evasión, sin deliberación y sin resolución de atascos | ✓ | ✓ |
| **Corridas por escenario** | | **30** | **40** |

`fsm:blind` solo se corre donde hay atascos que resolver. En los lotes con obstrucción, las tres comparaciones planificadas son: (i) `slm:depth` vs. `fsm:blind`: ¿aporta el sistema completo frente a una FSM sin barrido? (ii) `fsm:depth` vs. `fsm:blind`: ¿aporta el barrido con profundidad? (iii) `slm:depth` vs. `fsm:depth`: ¿aporta la capa estratégica junto con la política del lazo rápido del brazo `slm`? La pregunta «¿aporta el VLM en vuelo?» la responde el banco (IT.10.2), no los lotes.

---

## 10.4 Escenarios

Tres niveles crecientes de dificultad ambiental, cada uno sobre un **proyecto de Unreal Engine distinto** (cap. 3), con un escenario de control despejado por nivel y uno o dos con obstrucción en los niveles 1 y 2.

### 10.4.1 Principios de diseño comunes

Cinco principios gobiernan todos los escenarios (justificación en el Anexo 12, IT.A12.2):

1. **Sin teletransporte.** Todas las misiones despegan del punto de inicio nativo del nivel: reposicionar el dron no verifica colisión y podría materializarlo dentro de un obstáculo.
2. **Ninguna coordenada se inventa sobre el mapa.** Toda coordenada se deriva de posiciones ya voladas o se verifica ubicando el dron en ella.
3. **Exclusión total de profundidad del lazo de vuelo.** Ni el grafo ni el runner leen el canal de profundidad del simulador, del que salen las etiquetas de referencia (Anexo 11, IT.A11.4.2); una guardia automatizada lo verifica, y la única lectura es la auditoría de distancia mínima (IT.10.6.1), en un hilo aislado del grafo.
4. **Validación previa obligatoria.** Antes de un lote, la ruta se confirma en el simulador y una misión piloto debe cumplir el criterio de pase del escenario (IT.A12.7.2).
5. **Los controles vuelan una ruta fija.** Los controles (lotes 1, 2 y 5) vuelan el manifiesto sin plan de ruta, porque miden el costo de la arquitectura en tránsito libre. El plan con el VLM se usa solo en los escenarios con obstrucción (lotes 3, 4 y 6), donde cambia la ruta que se vuela —desvía entre 2 y 4 tramos por escenario— igual para las cuatro celdas: el obstáculo que enfrenta cada brazo es el de la ruta planificada.

### 10.4.2 La batería de escenarios

| Lote | Escenario | Entorno | Rol | Ruta / $\ell_{\text{opt}}$ | Altitud | Dificultad · hipótesis |
|:---:|---|---|---|---|---|---|
| 1 | `minisim_clear` | MiniSim (T0) | Control: cota inferior | 181 / 120 m | −10 m | Nula · H2, H3 |
| 2 | `townsim_clear` | TownSim (T1) | Control: crucero largo | 598 / 588 m | −30 m | Baja · H2 |
| 3 | `townsim_ini` | TownSim (T1) | Vegetación en ruta | 343 / 312 m | −30 a −10 m | Media-alta · H1 |
| 4 | `townsim_calib_cruce_frontal` | TownSim (T1) | Bloqueo frontal | 350 / 320 m | −30 a −10 m | Alta · **H1** |
| 5 | `citysim_clear` | CitySim (T2) | Control en rampa | 421 / 345 m | −10 a −50 m | Baja · H2, H3 |
| 6 | `citysim_pilot` | CitySim (T2) | Rodeo de manzanas | 391 / 339 m | −10 m | **Máxima** · **H1, H3** |

*Ruta: longitud desde el punto de partida, con el ascenso; $\ell_{\text{opt}}$: suma de los tramos entre waypoints del manifiesto, la que usa el SPL (IT.10.6.1). T0–T2: nivel de dificultad del entorno. En los lotes 3, 4 y 6 el plan de ruta agrega puntos de paso a la ruta volada (IT.10.4.1, punto 5).*

**Tier 0 — MiniSim.** Un plano sin estructuras verticales: mide el **costo puro del brazo `slm`**, sin nada que decidir, y la **tasa de falsos positivos de percepción**, porque todo evento de evasión o deadlock es, por construcción, falso.

**Tier 1 — TownSim.** Un complejo semiurbano con pasajes arbolados, cuya particularidad son los obstáculos **orgánicos y semitransparentes**: una copa de árbol produce un flujo de baja coherencia y una evidencia geométrica ambigua, el régimen donde un juicio sobre el fotograma completo debería aportar. `townsim_clear` recorre el perímetro sobre los tejados con una ruta 3.3× más larga que la de MiniSim, la prueba directa de H2; `townsim_ini` cruza a nivel de calle el corredor arbolado; `townsim_calib_cruce_frontal` enfrenta al dron con una fachada continua y lo obliga a elegir entre sobrevolar y buscar un corredor lateral. Si la FSM escala el edificio y el `slm` encuentra la calle transversal, ambos llegan con SPL muy distintos: **por eso la métrica primaria con obstrucción es el SPL y no el éxito**.

**Tier 2 — CitySim.** Una cuadrícula regular con edificios de 50 a 100 m, donde un escape por altura ya no despeja el obstáculo y la textura repetitiva hace casi indistinguibles dos calles paralelas. `citysim_clear` es el control en rampa; `citysim_pilot`, a −10 m entre edificios, obliga a **rodear manzanas y elegir corredor**, y es donde H1 tiene mayor potencia y se espera la mayor tasa de fallo. La geometría de cada escenario está en el Anexo 12 (IT.A12.3) y los manifiestos, en el Anexo 6 (IT.A6.5).

---

## 10.5 Réplicas y organización en lotes

### 10.5.1 Semillas

Una corrida única no permite inferencia: el sistema es estocástico, y pocas corridas son una fuente documentada de conclusiones no reproducibles en agentes secuenciales ([Henderson et al., 2018](13-REFERENCIAS.md#ref-henderson-2018); [Colas et al., 2018](13-REFERENCIAS.md#ref-colas-2018)), agravada cuando cada corrida cuesta minutos de simulación ([Agarwal et al., 2021](13-REFERENCIAS.md#ref-agarwal-2021)). **Una semilla identifica una réplica, no una condición distinta**: el dron parte siempre de la misma pose, y la variación entre semillas viene de la estocasticidad del sistema —el desfase temporal del lazo, el render y la física no deterministas, la sensibilidad no lineal del flujo y el momento en que llegan las respuestas asíncronas—, que se realimenta a lo largo de miles de ciclos (análisis en el Anexo 12, IT.A12.4). La varianza del brazo `reactive` mide cuánta variabilidad introduce el entorno por sí solo: es el **control negativo del diseño**.

Se corren **$K = 10$ semillas por celda**, número que impone la potencia: el $p$-valor mínimo de la prueba de rangos es $2/\binom{2K}{K}$, de modo que con $K = 5$ (0.0079) ninguna comparación sobreviviría la corrección de Bonferroni (IT.10.7.3) ni con separación perfecta, y con $K = 10$ baja a $1.1 \times 10^{-5}$. Dentro de cada semilla las celdas se alternan, para repartir la deriva del simulador a lo largo de horas.

### 10.5.2 Lotes

La unidad de ejecución es el **lote**: todas las corridas de un escenario. Seis escenarios dan seis lotes y **210 corridas**. Como los tiers son proyectos de Unreal Engine distintos, solo se corren juntos los lotes del mismo nivel; todas las corridas de un lote comparten nivel, configuración gráfica y sesión de simulador, de modo que **comparar celdas dentro de un lote es limpio**, y comparar entre lotes es de segundo orden (IT.10.7.4). Todas las corridas tienen el mismo techo holgado de **1200 s / 6000 ciclos**, para que una celda lenta falle por el obstáculo y no por el tiempo; las corridas con otra versión del código, con cambios sin confirmar o con menos de 50 ciclos se descartan (IT.A12.7.2). El procedimiento, las semillas de cada lote y la trazabilidad están en el Anexo 12 (IT.A12.5, IT.A12.9).

---

## 10.6 Métricas reportadas

Todas se derivan del registro por ciclo y se consolidan en el resumen de cada corrida (cap. 4, IT.4.4); el detalle de cálculo está en el Anexo 12 (IT.A12.6).

### 10.6.1 Eficacia y seguridad de vuelo

- **Tasa de éxito** sobre las $K$ semillas, con intervalo de Wilson al 95 %, y **motivo de terminación**: éxito, tope de tiempo, colisión o `physics_locked` (dron incrustado en la malla, cap. 5, IT.5.4), que cuenta como falla.
- **Colisiones**, por misión y por kilómetro. La bandera de colisión de AirSim **no detecta todos los contactos** —ni el follaje ni el dron apoyado sobre una cornisa—: cero colisiones no equivale a cero contactos.
- **Distancia mínima a obstáculo** (DistMin): el mínimo, sobre la corrida, del percentil 5 de la profundidad del tercio central de la imagen, muestreado a 1 Hz por un hilo de auditoría que no comparte nada con el grafo.
- **SPL** ([Anderson et al., 2018](13-REFERENCIAS.md#ref-anderson-2018)): $\text{SPL} = S \cdot \ell_{\text{opt}} / \max(\ell_{\text{real}}, \ell_{\text{opt}})$, con $S$ el éxito y $\ell_{\text{opt}}$ la suma de las distancias entre waypoints del manifiesto, idéntica para todas las celdas. Penaliza a la vez no llegar y llegar dando vueltas, y es la métrica primaria con obstrucción. Como $\ell_{\text{opt}}$ omite el tramo desde el punto de partida, el SPL está subestimado en una proporción constante por escenario (IT.A12.6.2) y se interpreta **dentro de cada lote**.
- **Tiempo** a destino.

### 10.6.2 Dinámica del lazo táctico

- **Tiempo de reacción**, medido como la **latencia del grafo por ciclo**, desde el fotograma hasta el comando; la capa estratégica no participa, porque corre en su propio hilo (cap. 5, IT.5.1.2). Se reporta la mediana y el $p_{95}$, que es el que importa para el tiempo real.
- **Histograma de rutas**: la distribución de ciclos entre los comportamientos del grafo, que caracteriza el vuelo mejor que el éxito.
- **Tasa de deliberación**: fracción de ciclos con una consulta nueva del lazo lento.

### 10.6.3 Lazo lento y resolución de atascos

- **Resultados de la capa estratégica**: fracción de consultas que proponen sub-meta, que declaran libre el camino directo o que no encuentran sector libre; una capa que declara libre el camino en casi todas las consultas, incluso cuando el dron termina en deadlock, no aporta información.
- **Avance hacia el waypoint real tras cada sub-meta**, a los 20 s: la medida directa de si las sub-metas ayudan.
- **Atascos**: número de deadlocks, fracción resuelta por el barrido y fracción que cae al escape vertical. «Resuelto» significa que se fijó una sub-meta, **no** que el dron haya salido del atasco.
- **Desglose por waypoint**, para no atribuir a todo el escenario la dificultad de un solo tramo.

---

## 10.7 Protocolo estadístico

El análisis lo implementa `analyze_lotes.py` (IT.A12.5.4) y el cuaderno NB1 abre cada paso.

### 10.7.1 Métricas primarias y comparaciones planificadas

Declaradas antes de ver los datos: en los **lotes despejados**, el tiempo de las misiones exitosas (H2), con las tres comparaciones entre brazos; en los **lotes con obstrucción**, el SPL (H1), con las tres comparaciones de IT.10.3.3. Tres comparaciones por lote y seis lotes forman la familia de **18 comparaciones primarias**.

### 10.7.2 Pruebas de hipótesis y tamaños de efecto

Cada comparación usa una **prueba de permutación exacta sobre rangos**, equivalente a la U de Mann-Whitney exacta ([Mann & Whitney, 1947](13-REFERENCIAS.md#ref-mann-1947)) pero válida con empates, frecuentes en SPL porque toda corrida fallida tiene SPL = 0. Las pruebas no paramétricas son una necesidad del dato: los tiempos están truncados por el presupuesto y el SPL tiene una masa en cero. El éxito y la distancia mínima se informan como métricas secundarias, sin corrección.

Se reporta **Cliff's Delta** ($\delta$; [Cliff, 1993](13-REFERENCIAS.md#ref-cliff-1993)), la proporción de pares en que una muestra domina a la otra, con intervalo *bootstrap* y la escala de [Romano et al. (2006)](13-REFERENCIAS.md#ref-romano-2006): grande por encima de 0.474. Con $K$ pequeño, **el tamaño de efecto es el resultado principal** ([Agarwal et al., 2021](13-REFERENCIAS.md#ref-agarwal-2021)): un $\delta$ grande con $p$ no significativo describe un efecto que el diseño no tuvo potencia para detectar, no un efecto ausente.

### 10.7.3 Comparaciones múltiples

**Corrección de Bonferroni** sobre la familia de 18: $\alpha \approx 0.0028$. Se aplica **solo a las comparaciones declaradas antes de ver los datos**; cualquier otra se reporta como **exploratoria**.

### 10.7.4 Análisis desagregado y comparación entre lotes

El análisis se informa **por escenario**, la única forma de contrastar H3: un promedio sobre los seis mezclaría escenarios donde `slm` solo puede perder con escenarios donde puede ganar ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)). Como los tiers corren en sesiones y proyectos distintos, la comparación entre lotes usa cantidades normalizadas dentro de cada lote: las **razones** $t_{\text{brazo}}/t_{\text{reactive}}$, cuya progresión entre los tres controles es la evidencia central de H2; el **perfil de consulta** por escenario; y la **interacción brazo × escenario**. El resultado que sostiene H3 es un **cambio de signo** del efecto `slm` − `fsm` entre los controles y los escenarios con obstrucción, reportado como patrón de tamaños de efecto con sus intervalos y no como prueba formal de interacción, que con datos truncados y 10 réplicas no sería defendible. La conclusión no es un número sino un mapa: **dónde la capa deliberativa paga y dónde no**.

---

## 10.8 Amenazas a la validez

1. **Potencia estadística.** Con $K = 10$, una separación parcial puede no superar Bonferroni: un resultado no significativo se lee como "no detectado con esta potencia", nunca como "ausente".
2. **Validez externa respecto de los modelos.** Las conclusiones son sobre una red de profundidad concreta y sobre LFM2.5-VL-1.6B cuantizado, no sobre "modelos de lenguaje pequeños" en general; el banco mide además un solo entorno (IT.A12.10.3).
3. **Efecto de sesión entre tiers.** Las comparaciones absolutas entre tiers no son limpias (IT.10.5.2); la mitigación parcial son las razones normalizadas.
4. **Sin obstáculos dinámicos.** El diseño asume geometría estática, y las conclusiones no se extienden a agentes móviles, el escalón que la literatura de conducción identifica como decisivo ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)).
5. **Un escenario por lote.** Un efecto es una propiedad de esa geometría hasta que se replique en otra ruta del mismo tipo; la generalización entre escenarios es descriptiva.

Ninguna invalida el diseño para las preguntas que sí responde; todas acotan lo que puede afirmarse. Las extensiones que las mitigan están en el plan extendido de pruebas (Anexo 12, IT.A12.11).
