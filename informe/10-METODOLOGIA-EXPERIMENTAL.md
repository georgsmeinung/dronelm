# 10. Metodología experimental

Este capítulo especifica el protocolo con el que se evalúa si una capa deliberativa sobre percepción monocular aporta un beneficio medible sobre una heurística rígida en la capa táctica de un dron, y a qué costo. Hay dos instrumentos: el **banco de prueba a bordo** (IT.10.2) mide, fuera de vuelo y contra etiquetas de referencia, si una fuente sabe responder la pregunta del lazo lento; los **lotes de vuelo** (IT.10.3–IT.10.5) miden si el sistema completo, con la fuente que pasa el banco, vuela mejor que una máquina de estados y que un controlador reactivo. Las métricas primarias, las comparaciones y los resultados esperados de cada lote (Anexo 12, IT.A12.8) se fijaron antes de existir los datos. El detalle operativo está en el [Anexo 12](anexos/A12-OPERACION-EXPERIMENTAL.md).

---

## 10.1 Preguntas experimentales e hipótesis operativas

El diseño no persigue una única comparación global "`depth2loop` vs. FSM", sino tres preguntas separables, cada una con su propia condición de falsación:

**H1 — Beneficio de la capa deliberativa.**
En escenarios donde la trayectoria directa está obstruida por geometría que exige decidir un rodeo, el brazo `depth2loop` alcanza un SPL superior al de una FSM con significancia estadística.
*Condición de falsación:* si en los escenarios con obstrucción la FSM iguala o supera al `depth2loop` en SPL, la capa deliberativa no aporta.

**H2 — Costo de la arquitectura.**
El sobrecosto temporal del brazo `depth2loop` no escala con la distancia recorrida sino con la **frecuencia de consulta del lazo lento**: es aproximadamente un término aditivo $N_{\text{inv}} \times \bar{\ell}$ (número de consultas por su costo medio), no un factor multiplicativo sobre el tiempo de misión.
*Condición de falsación:* si el ratio $t_{\text{depth2loop}} / t_{\text{reactive}}$ es aproximadamente constante entre escenarios de control en lugar de decrecer con la longitud de la ruta, el costo es multiplicativo.

**H3 — Estratificación del beneficio por dificultad ambiental.**
En ambientes despejados la capa deliberativa solo agrega costo; el beneficio, de existir, aparece donde la geometría exige una decisión que la heurística no puede tomar. La hipótesis operativa es que **existe una interacción entre el factor "brazo" y el factor "escenario"**, no un efecto principal uniforme del brazo.

H3 dicta la arquitectura de escenarios en tres niveles, cada uno con un control despejado: sin controles no se puede separar el costo fijo del brazo de su beneficio condicional, y sin obstrucción genuina el beneficio no puede manifestarse. Es la práctica de los *benchmarks* de conducción y navegación, que estratifican la dificultad en niveles ([Dosovitskiy et al., 2017](13-REFERENCIAS.md#ref-dosovitskiy-2017); [Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019); [Loquercio et al., 2021](13-REFERENCIAS.md#ref-loquercio-2021)).

---

## 10.2 Banco de prueba a bordo (`vlm_bench`)

El banco es una medición **fuera de vuelo** que responde una pregunta previa a cualquier lote: **¿la fuente del lazo lento sabe responder la pregunta que el lazo le hace?** —si un sector de la imagen está libre a 15 m, si un rumbo del barrido es transitable, si un tramo de ruta sobre el mapa va por la calle—. Compara, muestra por muestra, la respuesta de la fuente con una **etiqueta de referencia** calculada con la profundidad del simulador en la misma pose (cap. 7, IT.7.1): un sector es libre si el percentil 5 de su profundidad es ≥ 15 m. Las muestras son poses de corridas reales, y las etiquetas nunca entran al lazo de vuelo. El criterio de pase —exactitud balanceada ≥ 0.65 con el IC 95 % por encima del azar— debe cumplirse sin adaptar la pregunta al escenario; las reglas y la construcción del banco están en el Anexo 12 (IT.A12.10).

| Medición | Resultado | Consecuencia de diseño |
|---|---|---|
| Juicio de rutas enteras dibujadas sobre el mapa | Ningún modelo distingue una ruta por la calle de una sobre un edificio | El planificador no juzga rutas enteras (cap. 4, IT.4.3.1) |
| Reconocimiento de parches del mapa cenital | LFM2.5-VL-1.6B: AUC 0.80 para «calle»; Qwen2.5-VL-3B: 0.63 | Juicio **por parches** con LFM2.5-VL-1.6B |
| Rutas juzgadas por parches | AUC 0.81 | Plan de ruta activado sobre mapas registrados |
| Pregunta de la capa estratégica y del barrido con el VLM | Ninguna de las ocho preguntas pasa; el barrido declara todo transitable | El VLM no responde la pregunta del lazo lento |
| Reconocimiento por sector en la cámara frontal | No pasa (AUC 0.53–0.62) | No se pregunta «qué hay» en lugar de «a qué distancia» |
| Profundidad monocular y segmentación | Profundidad: 75 % y AUC 0.83 por sector, 0.87 en los barridos; segmentación: AUC 0.50 | La capa estratégica y el barrido usan la profundidad estimada |
| Lote piloto de fuentes: 15 corridas en `citysim_pilot` con fuentes `depth`, `vlm` y `off`, 5 semillas emparejadas | Avance equivalente en las tres; éxitos 3/5, 4/5 y 5/5 | `depth` sobre `vlm` por latencia; frente a `off`, sin ventaja de la capa, aunque con 5 pares no se puede descartar |

Las cifras completas están en el capítulo 11 (IT.11.0) y NB5 recalcula cada fila.

---

## 10.3 Diseño factorial

### 10.3.1 Factor principal: brazo de decisión

Los tres brazos comparten **el mismo `ObstacleField`** (cap. 6), **el mismo vocabulario de macro-acciones** y **el mismo traductor a cinemática**: la diferencia es *quién elige la macro-acción y quién decide los rodeos*. Como las reglas del lazo rápido tampoco son las mismas (cap. 5, IT.5.3.3), cada comparación mide el brazo completo, no la capa deliberativa sola.

- **`depth2loop`** — el grafo con sus dos lazos (cap. 5): la capa estratégica juzga qué sectores de una grilla de 3×3 son volables y propone sub-metas ancladas a la pose del fotograma, y ante un deadlock un barrido de 4 rumbos produce la sub-meta de salida, ambos con la profundidad estimada (cap. 6, IT.6.12). **Ningún modelo de lenguaje decide en vuelo**; el VLM solo planifica la ruta antes del despegue (cap. 4, IT.4.3.1). En el código y en los datos de la v4 el brazo figura como `slm` (celda `slm:depth`), nombre heredado de versiones en que el lazo lento consultaba al VLM (Anexo 12, IT.A12.1).
- **`fsm`** — una máquina de estados con umbrales fijos sobre el mismo `ObstacleField` y su propia lógica de bloqueo (cap. 5, IT.5.7): la línea de base directa, predecible y de costo mínimo.
- **`reactive`** — solo guiado al waypoint, **sin evasión**, sin deliberación y sin resolución de bloqueos: la **cota inferior de rendimiento**, y su varianza entre semillas, el control negativo del diseño (IT.10.5.1).

### 10.3.2 Factores secundarios: resolución de bloqueos y fuente de la capa estratégica

**Resolución de bloqueos:** **`depth`** (barrido panorámico juzgado por la profundidad estimada; por defecto), **`deep_vlm`** (juzgado por el VLM; evaluado en el banco, no en los lotes) y **`blind`** (sin barrido, escape determinista). **Fuente de la capa estratégica** (solo `depth2loop`): `depth`, `vlm` u `off`; los lotes la fijan en `depth`. Con `depth`, la FSM delega sus deadlocks en el mismo barrido, de modo que `depth2loop` vs. `fsm:depth` aísla la capa estratégica y la política del lazo rápido, no la resolución de bloqueos.

### 10.3.3 Celdas y comparaciones planificadas

La celda es la tupla (escenario × brazo × estrategia de bloqueo), replicada con $K = 10$ semillas (IT.10.5.1):

| Celda | Qué aísla | Escenarios despejados | Escenarios con obstrucción |
|---|---|---|---|
| `depth2loop` | El sistema completo: capa estratégica + política del lazo rápido del brazo `depth2loop` + barrido | ✓ | ✓ |
| `fsm:depth` | La misma resolución de bloqueos con profundidad, sin capa estratégica y con política FSM | ✓ | ✓ |
| `fsm:blind` | La FSM sin barrido (escape determinista) | — | ✓ |
| `reactive` | Solo guiado: sin evasión, sin deliberación y sin resolución de bloqueos | ✓ | ✓ |
| **Corridas por escenario** | | **30** | **40** |

En los lotes con obstrucción, las tres comparaciones planificadas son: (i) `depth2loop` vs. `fsm:blind`: ¿aporta el sistema completo frente a una FSM sin barrido? (ii) `fsm:depth` vs. `fsm:blind`: ¿aporta el barrido con profundidad? (iii) `depth2loop` vs. `fsm:depth`: ¿aporta la capa estratégica junto con la política del lazo rápido del brazo `depth2loop`? La pregunta «¿aporta el VLM en vuelo?» la responde el banco (IT.10.2), no los lotes.

---

## 10.4 Escenarios

Tres niveles crecientes de dificultad ambiental, cada uno sobre un **proyecto de Unreal Engine distinto** (cap. 3), con un escenario de control despejado por nivel y uno o dos con obstrucción en los niveles 1 y 2.

### 10.4.1 Principios de diseño comunes

Todos los escenarios despegan del punto de inicio nativo del nivel, sin teletransporte; ninguna coordenada se inventa sobre el mapa; ningún componente del lazo de vuelo lee el canal de profundidad del simulador, salvo la auditoría de distancia mínima en un hilo aislado (IT.10.6.1); y antes de cada lote una misión piloto debe cumplir el criterio de pase del escenario (justificación en el Anexo 12, IT.A12.2). **Los controles vuelan una ruta fija**: los lotes 1, 2 y 5 vuelan el manifiesto sin plan de ruta, porque miden el costo de la arquitectura en tránsito libre, y el plan con el VLM se usa solo en los lotes con obstrucción (3, 4 y 6), donde desvía entre 2 y 4 tramos por escenario, igual para las cuatro celdas.

### 10.4.2 La batería de escenarios

| Lote | Escenario | Entorno | Rol | Ruta / $\ell_{\text{opt}}$ | Altitud | Dificultad · hipótesis |
|:---:|---|---|---|---|---|---|
| 1 | `minisim_clear` | MiniSim (T0) | Control: cota inferior | 181 / 120 m | −10 m | Nula · H2, H3 |
| 2 | `townsim_clear` | TownSim (T1) | Control: crucero largo | 598 / 588 m | −30 m | Baja · H2 |
| 3 | `townsim_ini` | TownSim (T1) | Vegetación en ruta | 343 / 312 m | −30 a −10 m | Media-alta · H1 |
| 4 | `townsim_calib_cruce_frontal` | TownSim (T1) | Bloqueo frontal | 350 / 320 m | −30 a −10 m | Alta · **H1** |
| 5 | `citysim_clear` | CitySim (T2) | Control en rampa | 421 / 345 m | −10 a −50 m | Baja · H2, H3 |
| 6 | `citysim_pilot` | CitySim (T2) | Rodeo de manzanas | 391 / 339 m | −10 m | **Máxima** · **H1, H3** |

*Ruta: longitud desde el punto de partida, con el ascenso; $\ell_{\text{opt}}$: suma de los tramos entre waypoints del manifiesto, la que usa el SPL (IT.10.6.1). T0–T2: nivel de dificultad del entorno.*

**MiniSim** es un plano sin estructuras: mide el **costo puro del brazo**, sin nada que decidir, y la tasa de falsos positivos de percepción. **TownSim** agrega obstáculos **orgánicos y semitransparentes** —copas de árboles con flujo de baja coherencia—: `townsim_clear` recorre los tejados con una ruta 3.3× más larga que la de MiniSim, la prueba directa de H2; `townsim_ini` cruza a nivel de calle un corredor arbolado; y `townsim_calib_cruce_frontal` enfrenta al dron con una fachada continua, donde sobrevolar y rodear producen SPL muy distintos, **por eso la métrica primaria con obstrucción es el SPL y no el éxito**. **CitySim** es una cuadrícula de edificios de 50 a 100 m, donde un escape por altura ya no despeja el obstáculo; `citysim_pilot`, a −10 m, obliga a **rodear manzanas y elegir corredor**. La geometría de cada escenario está en el Anexo 12 (IT.A12.3) y los manifiestos, en el Anexo 6 (IT.A6.5).

---

## 10.5 Réplicas y organización en lotes

### 10.5.1 Semillas

Una corrida única no permite inferencia: el sistema es estocástico, y pocas corridas son una fuente documentada de conclusiones no reproducibles en agentes secuenciales ([Henderson et al., 2018](13-REFERENCIAS.md#ref-henderson-2018); [Colas et al., 2018](13-REFERENCIAS.md#ref-colas-2018); [Agarwal et al., 2021](13-REFERENCIAS.md#ref-agarwal-2021)). **Una semilla identifica una réplica, no una condición distinta**: el dron parte siempre de la misma pose, y la variación entre semillas viene de la estocasticidad del sistema —el desfase temporal del lazo, el render y la física no deterministas y el momento en que llegan las respuestas asíncronas— (Anexo 12, IT.A12.4). La varianza del brazo `reactive` mide cuánta variabilidad introduce el entorno por sí solo: es el **control negativo del diseño**.

Se corren **$K = 10$ semillas por celda**, número que impone la potencia: el $p$-valor mínimo de la prueba de rangos es $2/\binom{2K}{K}$, de modo que con $K = 5$ (0.0079) ninguna comparación sobreviviría la corrección de Bonferroni (IT.10.7.3) ni con separación perfecta, y con $K = 10$ baja a $1.1 \times 10^{-5}$.

### 10.5.2 Lotes

La unidad de ejecución es el **lote**: todas las corridas de un escenario. Seis escenarios dan seis lotes y **210 corridas**. Todas las corridas de un lote comparten nivel, configuración gráfica y sesión de simulador, de modo que **comparar celdas dentro de un lote es limpio**, y comparar entre lotes es de segundo orden (IT.10.7.4). Todas tienen el mismo techo holgado de **1200 s**, para que una celda lenta falle por el obstáculo y no por el tiempo; las corridas con otra versión del código, con cambios sin confirmar o con menos de 50 ciclos se descartan (procedimiento y trazabilidad en el Anexo 12, IT.A12.5, IT.A12.7.2, IT.A12.9).

---

## 10.6 Métricas reportadas

Todas se derivan del registro por ciclo y se consolidan en el resumen de cada corrida (cap. 4, IT.4.4); el detalle de cálculo está en el Anexo 12 (IT.A12.6).

### 10.6.1 Eficacia y seguridad de vuelo

- **Tasa de éxito** sobre las $K$ semillas, con intervalo de Wilson al 95 %, y **motivo de terminación**: éxito, tope de tiempo, colisión o `physics_locked` (dron incrustado en la malla, cap. 5, IT.5.4), que cuenta como falla.
- **Colisiones.** La bandera de colisión de AirSim **no detecta todos los contactos** —ni el follaje ni el dron apoyado sobre una cornisa—: cero colisiones no equivale a cero contactos.
- **Distancia mínima a obstáculo** (DistMin): el mínimo, sobre la corrida, del percentil 5 de la profundidad del tercio central de la imagen, muestreado a 1 Hz por un hilo de auditoría que no comparte nada con el grafo.
- **SPL** ([Anderson et al., 2018](13-REFERENCIAS.md#ref-anderson-2018)): $\text{SPL} = S \cdot \ell_{\text{opt}} / \max(\ell_{\text{real}}, \ell_{\text{opt}})$, con $S$ el éxito y $\ell_{\text{opt}}$ la suma de las distancias entre waypoints del manifiesto. Penaliza a la vez no llegar y llegar dando vueltas, y es la métrica primaria con obstrucción; como $\ell_{\text{opt}}$ omite el tramo desde el punto de partida, se interpreta **dentro de cada lote** (IT.A12.6.2).
- **Tiempo** a destino.

### 10.6.2 Dinámica del lazo táctico

- **Tiempo de reacción**: la **latencia del grafo por ciclo**, desde el fotograma hasta el comando, con su mediana y su $p_{95}$; la capa estratégica no participa, porque corre en su propio hilo (cap. 5, IT.5.1.2).
- **Histograma de rutas** entre los comportamientos del grafo y **tasa de deliberación**, la fracción de ciclos con una consulta nueva del lazo lento.

### 10.6.3 Lazo lento y resolución de bloqueos

- **Resultados de la capa estratégica**: fracción de consultas que proponen sub-meta, que declaran libre el camino directo o que no encuentran sector libre.
- **Avance hacia el waypoint real tras cada sub-meta**, a los 20 s, sobre la ruta restante del manifiesto: la medida directa de si las sub-metas ayudan (cálculo en el Anexo 12, IT.A12.6.4).
- **Bloqueos**: número de deadlocks, fracción resuelta por el barrido y fracción que cae al escape vertical. «Resuelto» significa que se fijó una sub-meta, **no** que el dron haya salido del bloqueo.
- **Desglose por waypoint**, para no atribuir a todo el escenario la dificultad de un solo tramo.

---

## 10.7 Protocolo estadístico

El análisis lo implementa `analyze_lotes.py` (IT.A12.5.4) y el cuaderno NB1 abre cada paso.

### 10.7.1 Métricas primarias y comparaciones planificadas

Declaradas antes de ver los datos: en los **lotes despejados**, el tiempo de las misiones exitosas (H2), con las tres comparaciones entre brazos; en los **lotes con obstrucción**, el SPL (H1), con las tres comparaciones de IT.10.3.3. Tres comparaciones por lote y seis lotes forman la familia de **18 comparaciones primarias**.

### 10.7.2 Pruebas de hipótesis y tamaños de efecto

Cada comparación usa una **prueba de permutación exacta sobre rangos**, equivalente a la U de Mann-Whitney exacta ([Mann & Whitney, 1947](13-REFERENCIAS.md#ref-mann-1947)) pero válida con empates, frecuentes en SPL porque toda corrida fallida tiene SPL = 0. El éxito y la distancia mínima se informan como métricas secundarias, sin corrección. Se reporta **Cliff's Delta** ($\delta$; [Cliff, 1993](13-REFERENCIAS.md#ref-cliff-1993)) con intervalo *bootstrap* y la escala de [Romano et al. (2006)](13-REFERENCIAS.md#ref-romano-2006): grande por encima de 0.474. Con $K$ pequeño, **el tamaño de efecto es el resultado principal** ([Agarwal et al., 2021](13-REFERENCIAS.md#ref-agarwal-2021)): un $\delta$ grande con $p$ no significativo describe un efecto que el diseño no tuvo potencia para detectar, no un efecto ausente.

### 10.7.3 Comparaciones múltiples

**Corrección de Bonferroni** sobre la familia de 18: $\alpha \approx 0.0028$. Se aplica **solo a las comparaciones declaradas antes de ver los datos**; cualquier otra se reporta como **exploratoria**.

### 10.7.4 Análisis desagregado y comparación entre lotes

El análisis se informa **por escenario**, la única forma de contrastar H3: un promedio sobre los seis mezclaría escenarios donde `depth2loop` solo puede perder con escenarios donde puede ganar ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)). Como los tiers corren en sesiones y proyectos distintos, la comparación entre lotes usa cantidades normalizadas dentro de cada lote: las **razones** $t_{\text{brazo}}/t_{\text{reactive}}$, cuya progresión entre los tres controles es la evidencia central de H2, y la **interacción brazo × escenario**. El resultado que sostiene H3 es un **cambio de signo** del efecto `depth2loop` − `fsm` entre los controles y los escenarios con obstrucción, reportado como patrón de tamaños de efecto con sus intervalos y no como prueba formal de interacción, que con datos truncados y 10 réplicas no sería defendible.

---

## 10.8 Amenazas a la validez

1. **Potencia estadística.** Con $K = 10$, una separación parcial puede no superar Bonferroni: un resultado no significativo se lee como "no detectado con esta potencia", nunca como "ausente".
2. **Validez externa respecto de los modelos.** Las conclusiones son sobre una red de profundidad concreta y sobre LFM2.5-VL-1.6B cuantizado, no sobre "modelos de lenguaje pequeños" en general; el banco mide además un solo entorno (IT.A12.10.3).
3. **Efecto de sesión entre tiers.** Las comparaciones absolutas entre tiers no son limpias (IT.10.5.2); la mitigación parcial son las razones normalizadas.
4. **Sin obstáculos dinámicos.** El diseño asume geometría estática, y las conclusiones no se extienden a agentes móviles ([Codevilla et al., 2019](13-REFERENCIAS.md#ref-codevilla-2019)).
5. **Un escenario por lote.** Un efecto es una propiedad de esa geometría hasta que se replique en otra ruta del mismo tipo; la generalización entre escenarios es descriptiva.
6. **Réplicas de una sesión.** Las semillas de un lote comparten sesión de simulador y pose de partida (IT.10.5.1): la inferencia es sobre la variabilidad entre réplicas de esa sesión, no entre sesiones ni poses.
7. **Métrica condicionada al éxito.** En los controles se compara el tiempo de las misiones exitosas: si una celda falla más, su tiempo se calcula sobre menos semillas y no refleja esas fallas, que se leen en la tasa de éxito.

Ninguna invalida el diseño para las preguntas que sí responde; todas acotan lo que puede afirmarse. Las extensiones que las mitigan están en el plan extendido de pruebas (Anexo 12, IT.A12.11).
