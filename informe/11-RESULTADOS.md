# 11. Resultados: el VLM a bordo y la comparación entre brazos

Este capítulo reporta dos instrumentos. El banco de prueba a bordo (§11.0) mide, fuera de vuelo, qué preguntas sabe responder cada fuente del lazo lento, y es el que fija la configuración que vuela. La corrida productiva v4 (§11.1–§11.7) evalúa esa configuración en vuelo: seis lotes, uno por escenario, con 10 semillas por celda y 210 corridas en total, analizadas con el protocolo del capítulo 10 (§10.7).

**Qué responde cada instrumento.** El objetivo específico 3 (cap. 1, §1.2) —evaluar un modelo de lenguaje pequeño como capa de decisión a bordo— lo responde el banco (§11.0), y la respuesta es negativa: el modelo no distingue sectores volables de bloqueados. Por eso en la corrida v4 **ningún modelo de lenguaje decide en vuelo**. El brazo que conserva el nombre `slm` es la arquitectura de dos lazos con la capa estratégica respondida por la red de profundidad estimada (cap. 10, §10.2.1); el VLM solo interviene antes del despegue, en el plan de ruta de los lotes 3, 4 y 6, común a todas las celdas. Las comparaciones de §11.3–§11.7 miden esa arquitectura, no al VLM.

## 11.0 Banco de prueba del VLM: línea base a bordo

El banco (`airsim-loop/experiments/vlm_bench/`; qué es, cómo se construyó y cómo se usó para decidir, en cap. 10 §10.13) mide, fuera de vuelo, qué preguntas sabe responder el modelo, contra una etiqueta de referencia tomada de la profundidad del simulador en la misma pose. La **línea base** de todas las comparaciones es la corrida `airsim-runs/vlm_bench/v2/` con la configuración de vuelo vigente: LFM2.5-VL-1.6B Q4_K_M en Ollama, contexto de 8192 tokens, **en la misma GPU que Unreal Engine y el grafo de control** (cap. 8 §8.1.2). Se toma esa condición porque un VLM a bordo comparte el cómputo con el resto del sistema de vuelo.

**Datos.** Muestras de las 21 corridas de `citysim_pilot` que tienen telemetría y los dos videos (frontal y FollowCam). De 6926 poses se reprodujeron en AirSim 1908 (todas las consultas estratégicas, 429, y los barridos, 579, más 900 de trayectoria al azar). Válidas para evaluar: 915; se excluyen 190 con la cámara dentro de la geometría, 384 con captura inestable y 589 con la pose mal reproducida (correlación con lo registrado en vuelo < 0.5). El centro está libre en el 51 % de las válidas. Cada pregunta se hace con decodificación restringida y temperatura 0, a 384 px (los barridos a 256 px, como en vuelo), sobre hasta 60 muestras por clase.

**Criterio de pase:** exactitud balanceada de la respuesta tal como sale ≥ 0.65 y límite inferior del IC 95 % (*bootstrap* por corrida) por encima del azar. El AUC, calculado con la probabilidad de la opción leída de los *logprobs*, es diagnóstico: indica si hay señal que el modelo no expresa en la respuesta, no configura el vuelo.

| Pregunta | n | Exactitud bal. [IC 95 %] | Azar | Pasa | Respuesta más frecuente | AUC (diag.) | Latencia mediana |
|---|---:|---|---:|:---:|---|---:|---:|
| `grid_prod` (pregunta de vuelo, grilla 3×3) | 120 | 53 % [50–55 %] | 50 % | no | libre (82 %) | 0.53 | 0.88 s |
| `grid_perm` (ídem, etiquetas permutadas) | 120 | 51 % [49–53 %] | 50 % | no | libre (85 %) | 0.51 | 0.88 s |
| `centro_libre` (¿recto 15 m?) | 120 | 50 % [50–50 %] | 50 % | no | sí (100 %, constante) | 0.52 | 0.34 s |
| `borde_lateral` | 180 | 33 % [33–33 %] | 33 % | no | izquierda (100 %, constante) | — | 0.35 s |
| `borde_superior` | 120 | 53 % [50–58 %] | 50 % | no | sí (95 %) | 0.69 | 0.36 s |
| `direccion_abierta` | 208 | 32 % [28–36 %] | 25 % | no | izquierda (62 %) | — | 0.36 s |
| `scan_prod` (barrido de vuelo) | 14 | 50 % | 50 % | no | todo transitable (100 %) | 0.04* | 2.6 s |
| `scan_perm` (ídem, orden permutado) | 22 | 50 % | 50 % | no | todo transitable (100 %) | 0.92* | 3.1 s |

\* Con 14 y 22 barridos el AUC se calcula sobre muy pocos pares y cambia de extremo a extremo con el orden de las imágenes: no es interpretable.

**Ninguna pregunta pasa.** Tres son constantes y el resto queda a pocos puntos del azar. En la pregunta de vuelo, las filas 1 y 3 de la grilla salen «libre» en el 100 % de las muestras (realmente libres: 72–78 % arriba, 38–47 % abajo), y en la fila del medio la respuesta depende de la posición del sector más que de la escena (A2 libre 14 %, B2 70 %, C2 52 %, con ~50–57 % reales). Con las etiquetas permutadas la respuesta coincide con la del orden normal en el 75 % de los sectores: el modelo responde sobre todo a la posición en la imagen. Los *logprobs* no rescatan la grilla (AUC 0.53); la única señal latente apreciable está en `borde_superior` (AUC 0.69, frente a una respuesta casi constante).

**Consecuencia para el vuelo.** Con el VLM como fuente de la capa estratégica, la sub-meta saldría de la posición de las celdas y no de la escena: la fila de abajo, siempre «libre», haría descender al dron hacia las estructuras horizontales. Y el barrido declararía transitables todos los rumbos, de modo que la salida del atasco la decidiría la exclusión de rumbos ya probados (cap. 5 §5.12), no el modelo. Por eso el VLM no vuela, y esta es la respuesta al objetivo 3: LFM2.5-VL-1.6B, a bordo y en régimen *zero-shot*, no sirve como fuente de decisión táctica.

**Plan de ruta sobre el mapa** (juicio por parches, cap. 4 §4.3.1; 59 candidatas en 11 tramos de `citysim_pilot` y `citysim_clear`, 28 realmente libres). La probabilidad media de «calle» separa las rutas libres de las bloqueadas con AUC 0.81. La ruta elegida es libre en 10 de 11 tramos, igual que la recta: en el único tramo con la recta bloqueada (`citysim_pilot` WP_2 → WP_3, la recta cruza un edificio) el plan elige un desvío libre, y en un tramo de `citysim_clear` elige un desvío bloqueado con la recta libre. En la prueba de parches del mapa (60 parches etiquetados, cinco clases) el modelo local obtiene exactitud balanceada 0.65 y AUC 0.79; el planificador usa la probabilidad, no la respuesta.

**La misma pregunta con profundidad estimada** (`experiments/vlm_bench/seg_depth_probe.py`; detalle en cap. 6 §6.14.1). Con el mismo fotograma, la misma geometría y la misma etiqueta, el p5 de la profundidad estimada por Depth Anything V2 Metric Outdoor Small separa sectores libres de bloqueados con exactitud balanceada del 75 % [72–77 %] y AUC 0.83 (625 muestras × 9 sectores; 76 % y 0.84 en las 120 muestras de las preguntas del VLM), en 82 ms. Es la única señal que pasa el criterio. En los barridos (290 imágenes, sector central) logra 75 % [68–82 %] y AUC 0.87. Una red de segmentación semántica chica (`yolo26n-sem`) queda en el azar (AUC 0.50): la clase de un píxel no dice a qué distancia está.

## 11.1 Corrida productiva v4: datos y validez

**Configuración.** La del capítulo 10: capa estratégica y barrido con profundidad estimada (`STRATEGIC_SOURCE = depth`, `DEADLOCK_STRATEGY = depth`), el VLM fuera del lazo de vuelo, plan de ruta con el VLM solo en los lotes con obstrucción (§10.3.0, punto 5), techo de 1200 s / 6000 ciclos por corrida y spawn limpio de AirSim. Resultados en `airsim-runs/produccion/v4/` y análisis con `analyze_lotes.py --family 18`, que escribe `analisis_lotes.md` y dos CSV.

**Integridad.** Cada lote se corrió de una vez, con un solo `code_version` y sin cambios sin confirmar: lote 1 `b0332e1a`, lote 2 `12e90aab`, lotes 3 y 4 `835ae75f`, lote 5 `7053f405` y lote 6 `55583639`. El código de vuelo es idéntico en todas esas versiones: entre ellas solo cambian las líneas de avance del runner y la configuración del lanzador. El análisis toma la versión de referencia de cada lote y no descarta ninguna corrida: 210 válidas, ninguna con menos de 50 ciclos, ninguna colisión registrada por la bandera de AirSim (que no detecta todos los contactos, §10.6.1). Los tres pilotos y las corridas apartadas por un error de armado del escenario (registradas en `DESCARTE.md`) no entran.

**Distancia mínima.** DistMin se calcula sin la primera muestra de la auditoría, que es un artefacto del arranque: en una corrida de `townsim_clear` marca 0.003 m y la siguiente, 18.3 m. El valor de ~0.10 m que se repite en los escenarios con obstrucción es, probablemente, el plano cercano de la cámara de auditoría dentro del follaje o contra una fachada: indica contacto o casi contacto con la geometría, que la bandera de colisión de AirSim no registra.

**SPL.** La longitud óptima es la del manifiesto entre waypoints declarados, sin el tramo desde el *spawn* (§10.6.1). En los lotes 3, 4 y 6 los cuatro brazos vuelan además los puntos de paso del plan de ruta (§10.3.0, punto 5), de modo que su SPL queda por debajo de 1 aun en la ruta perfecta; el sesgo es igual para todas las celdas de un lote y el SPL se lee solo dentro de cada lote.

## 11.2 Resultados por celda

Éxito con su IC de Wilson al 95 %; SPL, tiempo de las misiones exitosas y DistMin como mediana [p25, p75]; terminación de las corridas fallidas.

| Lote | Escenario | Celda | Éxito [IC 95 %] | SPL | Tiempo de éxito (s) | DistMin (m) | Fallas |
|---|---|---|---|---|---|---|---|
| 1 | `minisim_clear` | `slm:depth` | 10/10 [0.72, 1.00] | 0.54 [0.51, 0.56] | 165.1 [159.8, 171.4] | 15.51 [15.47, 15.64] | — |
| 1 | | `fsm:depth` | 10/10 [0.72, 1.00] | 0.38 [0.35, 0.43] | 306.4 [252.9, 369.5] | 15.49 [15.44, 15.63] | — |
| 1 | | `reactive` | 10/10 [0.72, 1.00] | 0.63 [0.63, 0.63] | 84.9 [84.7, 85.3] | 15.47 [15.46, 15.50] | — |
| 2 | `townsim_clear` | `slm:depth` | 10/10 [0.72, 1.00] | 0.89 [0.87, 0.90] | 379.8 [366.4, 399.1] | 16.41 [12.43, 16.48] | — |
| 2 | | `fsm:depth` | 9/10 [0.60, 0.98] | 0.76 [0.72, 0.80] | 488.6 [434.1, 516.2] | 1.55 [0.24, 3.63] | 1 `physics_locked` |
| 2 | | `reactive` | 10/10 [0.72, 1.00] | 0.93 [0.91, 0.93] | 272.6 [272.4, 280.8] | 14.77 [7.89, 16.68] | — |
| 5 | `citysim_clear` | `slm:depth` | 9/10 [0.60, 0.98] | 0.70 [0.68, 0.72] | 286.2 [277.1, 288.9] | 11.45 [10.38, 12.50] | 1 `physics_locked` |
| 5 | | `fsm:depth` | 6/10 [0.31, 0.83] | 0.42 [0.00, 0.43] | 705.9 [664.8, 748.9] | 0.10 [0.10, 0.11] | 4 `physics_locked` |
| 5 | | `reactive` | 10/10 [0.72, 1.00] | 0.79 [0.79, 0.79] | 192.3 [190.6, 194.1] | 10.85 [10.70, 10.97] | — |
| 3 | `townsim_ini` | `slm:depth` | 9/10 [0.60, 0.98] | 0.48 [0.43, 0.48] | 519.9 [517.9, 524.3] | 0.13 [0.11, 0.37] | 1 `physics_locked` |
| 3 | | `fsm:depth` | 9/10 [0.60, 0.98] | 0.32 [0.31, 0.37] | 805.8 [704.9, 822.1] | 0.23 [0.12, 0.38] | 1 `physics_locked` |
| 3 | | `fsm:blind` | 9/10 [0.60, 0.98] | 0.38 [0.35, 0.40] | 625.1 [594.7, 684.6] | 0.24 [0.11, 0.38] | 1 `physics_locked` |
| 3 | | `reactive` | 0/10 [0.00, 0.28] | 0.00 | — | 1.94 [1.35, 2.36] | 10 tope de tiempo |
| 4 | `townsim_calib_cruce_frontal` | `slm:depth` | 5/10 [0.24, 0.76] | 0.28 [0.00, 0.58] | 479.0 [401.7, 497.0] | 0.14 [0.12, 0.36] | 5 `physics_locked` |
| 4 | | `fsm:depth` | 8/10 [0.49, 0.94] | 0.41 [0.33, 0.43] | 608.3 [558.9, 687.1] | 0.25 [0.16, 0.34] | 2 `physics_locked` |
| 4 | | `fsm:blind` | 9/10 [0.60, 0.98] | 0.46 [0.40, 0.49] | 492.4 [469.3, 572.7] | 0.14 [0.12, 0.26] | 1 `physics_locked` |
| 4 | | `reactive` | 0/10 [0.00, 0.28] | 0.00 | — | 0.11 [0.10, 0.18] | 10 tope de tiempo |
| 6 | `citysim_pilot` | `slm:depth` | 10/10 [0.72, 1.00] | 0.48 [0.46, 0.51] | 483.1 [452.7, 513.0] | 4.14 [2.32, 4.14] | — |
| 6 | | `fsm:depth` | 9/10 [0.60, 0.98] | 0.34 [0.33, 0.37] | 805.6 [688.1, 834.7] | 1.16 [0.20, 2.63] | 1 `physics_locked` |
| 6 | | `fsm:blind` | 5/10 [0.24, 0.76] | 0.14 [0.00, 0.34] | 712.5 [625.4, 870.8] | 0.11 [0.10, 1.28] | 3 `physics_locked`, 2 tope de tiempo |
| 6 | | `reactive` | 10/10 [0.72, 1.00] | 0.53 [0.53, 0.53] | 313.2 [309.6, 319.4] | 4.14 [4.14, 4.14] | — |

**Cómo terminan las corridas que fallan.** La bandera de colisión de AirSim no se activa en ninguna de las 210. De las 23 fallas de los brazos con evasión, 21 son abortos por `physics_locked`: el dron queda apoyado o incrustado en la malla y el vigilante corta la corrida (cap. 5 §5.19). Son, en la práctica, contactos con la geometría que la bandera no detecta (§10.6.1). Las otras 2, de `fsm:blind` en el lote 6, y las 20 de `reactive` en los lotes 3 y 4 llegan al tope de 1200 s sin completar. `reactive` es casi determinista: en los controles y en el lote 6 sus 10 corridas difieren en pocos segundos, y su varianza entre semillas confirma que el entorno aporta poca variación por sí solo (§10.4.1).

## 11.3 Escenarios de control (lotes 1, 2 y 5): costo de la arquitectura (H2)

**Comparaciones planificadas** (tiempo de las misiones exitosas; δ > 0 indica que la primera celda tarda más):

| Lote | Comparación | n | δ de Cliff [IC 95 %] | p (permutación exacta) | p Bonferroni |
|---|---|---|---|---|---|
| 1 | `slm` vs. `fsm` | 10 / 10 | −1.00 [−1.00, −1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 1 | `slm` vs. `reactive` | 10 / 10 | +1.00 [+1.00, +1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 1 | `fsm` vs. `reactive` | 10 / 10 | +1.00 [+1.00, +1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 2 | `slm` vs. `fsm` | 10 / 9 | −0.98 [−1.00, −0.87] | 4.3 × 10⁻⁵ | 7.8 × 10⁻⁴ |
| 2 | `slm` vs. `reactive` | 10 / 10 | +1.00 [+1.00, +1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 2 | `fsm` vs. `reactive` | 9 / 10 | +1.00 [+1.00, +1.00] | 2.2 × 10⁻⁵ | 3.9 × 10⁻⁴ |
| 5 | `slm` vs. `fsm` | 9 / 6 | −1.00 [−1.00, −1.00] | 4.0 × 10⁻⁴ | 0.0072 |
| 5 | `slm` vs. `reactive` | 9 / 10 | +1.00 [+1.00, +1.00] | 2.2 × 10⁻⁵ | 3.9 × 10⁻⁴ |
| 5 | `fsm` vs. `reactive` | 6 / 10 | +1.00 [+1.00, +1.00] | 2.5 × 10⁻⁴ | 0.0045 |

Las nueve son significativas tras Bonferroni (α = 0.0028), con separación completa o casi: en los tres tiers el orden es **`reactive` < `slm` < `fsm`**. El orden esperado en §10.8.1 era `reactive` < `fsm` < `slm`: la FSM resulta la más lenta, por las razones de §11.5.

**Razón de tiempos y su dependencia de la ruta.**

| Lote | Ruta | $t_{\text{slm}}/t_{\text{reactive}}$ | $t_{\text{slm}} - t_{\text{reactive}}$ | Consultas por misión (`slm`) | Sub-metas | $t_{\text{fsm}}/t_{\text{reactive}}$ |
|---|---|---|---|---|---|---|
| 1 `minisim_clear` | ~180 m | 1.95 | 80 s | 90 | 27 % | 3.61 |
| 5 `citysim_clear` | ~420 m | 1.49 | 94 s | 151 | 37 % | 3.67 |
| 2 `townsim_clear` | ~600 m | 1.39 | 107 s | 235 | 8 % | 1.79 |

Ordenados por longitud de ruta, la razón $t_{\text{slm}}/t_{\text{reactive}}$ decrece: 1.95, 1.49, 1.39. La diferencia absoluta crece mucho menos que la ruta: la ruta se multiplica por 3.3 y la diferencia por 1.3. Es la forma que predice H2: la razón decrece con la ruta, como un costo aproximadamente aditivo y no un factor multiplicativo (§10.1). La lectura tiene dos límites. Primero, con un solo escenario por tier la progresión es descriptiva, y los tres controles difieren en más que la longitud: `townsim_clear` vuela sobre los techos y recibe muchas menos sub-metas (8 % frente a 27–37 %). Segundo, **el mecanismo que postula H2 no se confirma**: H2 atribuía el costo al número de consultas por su latencia, pero las consultas son periódicas —su número crece con la duración de la misión: 90, 151 y 235— y, sobre todo, no bloquean al dron.

**De dónde sale el costo.** No sale de esperar al modelo: la capa estratégica corre en su propio hilo, con latencia mediana de 104–125 ms por consulta en los controles, y el dron no frena a esperarla. Sale de lo que el brazo `slm` hace con las respuestas y con su evasión, y del gobernador de velocidad. No hay una celda que separe la capa estratégica del resto del brazo (por ejemplo, `slm` con `STRATEGIC_SOURCE = off`), de modo que el reparto entre las dos fuentes siguientes es descriptivo:

- **Sub-metas en ruta libre.** En el plano sin obstáculos de MiniSim, el 27 % de las 912 consultas proponen una sub-meta; en `citysim_clear`, el 37 %, con otro 12 % sin sector libre. En `townsim_clear`, a −30 m sobre la línea de tejados, solo el 8 %. Cada sub-meta inserta un desvío: `slm` recorre 17 % más que `reactive` en el lote 1 (223 frente a 191 m), 4 % en el 2 y 11 % en el 5.
- **Gobernador de velocidad.** Limita el avance cuando falta evidencia perceptual y, tras cada maniobra, rampa la velocidad desde 1 m/s (cap. 5 §5.13): está activo en el 27–43 % de los ciclos de `slm`, frente al 7–18 % de `reactive`, que no hace maniobras. La velocidad horizontal media de `slm` es 1.35–1.79 m/s; la de `reactive`, 2.42–2.48 m/s.

**Seguridad.** Sin colisiones registradas en ningún brazo. DistMin de `slm` y `reactive` es la misma en los tres controles (δ de 0.07 a 0.31, sin diferencia). La FSM pasa mucho más cerca en los dos controles con estructuras: 1.55 m en `townsim_clear` y 0.10 m en `citysim_clear` (δ = +0.90 y +0.94 a favor de `slm`, secundarias).

**Validez del control.** El lote 1 no tiene fallas, de modo que el sistema no muestra problemas de percepción, guiado ni infraestructura en el plano libre (§10.8.1). `citysim_clear` no cumple la expectativa de cero atascos: 31 en `slm` y 83 en `fsm`. Sus cinco fallas ocurren en el mismo tramo, WP_2 (−30 m) → WP_3 (−50 m): el dron queda incrustado a ~50 m de altura entre 15 y 25 m al oeste de la recta del manifiesto, que `reactive` sigue sin desviarse. La ruta es libre; lo que la vuelve peligrosa es salir de ella.

## 11.4 Escenarios con obstrucción (lotes 3, 4 y 6): beneficio de la capa deliberativa (H1)

**Comparaciones planificadas** (SPL; δ > 0 indica mejor SPL de la primera celda):

| Lote | Comparación | δ de Cliff [IC 95 %] | p | p Bonferroni | Éxito A / B |
|---|---|---|---|---|---|
| 3 | (i) `slm:depth` vs. `fsm:blind` | +0.73 [+0.28, +1.00] | 0.0039 | 0.071 | 9/10 / 9/10 |
| 3 | (ii) `fsm:depth` vs. `fsm:blind` | −0.49 [−0.90, 0.00] | 0.065 | 1.00 | 9/10 / 9/10 |
| 3 | (iii) `slm:depth` vs. `fsm:depth` | **+0.81 [+0.40, +1.00]** | 0.0011 | **0.019** | 9/10 / 9/10 |
| 4 | (i) `slm:depth` vs. `fsm:blind` | +0.05 [−0.52, +0.62] | 0.87 | 1.00 | 5/10 / 9/10 |
| 4 | (ii) `fsm:depth` vs. `fsm:blind` | −0.40 [−0.82, +0.12] | 0.14 | 1.00 | 8/10 / 9/10 |
| 4 | (iii) `slm:depth` vs. `fsm:depth` | +0.10 [−0.52, +0.66] | 0.73 | 1.00 | 5/10 / 8/10 |
| 6 | (i) `slm:depth` vs. `fsm:blind` | **+1.00 [+1.00, +1.00]** | 1.1 × 10⁻⁵ | **2.0 × 10⁻⁴** | 10/10 / 5/10 |
| 6 | (ii) `fsm:depth` vs. `fsm:blind` | +0.39 [−0.15, +0.84] | 0.14 | 1.00 | 9/10 / 5/10 |
| 6 | (iii) `slm:depth` vs. `fsm:depth` | **+1.00 [+1.00, +1.00]** | 1.1 × 10⁻⁵ | **2.0 × 10⁻⁴** | 10/10 / 9/10 |

Tres de las nueve son significativas tras Bonferroni, las tres a favor de `slm:depth`. Ninguna favorece a una FSM. Las tasas de éxito no difieren significativamente en ningún par (Fisher, secundaria), salvo (i) en el lote 6 sin corrección (p = 0.033).

**Qué separa a las celdas que completan de `reactive`.** `fsm:blind` no usa la profundidad estimada en ninguna decisión (no tiene capa estratégica ni barrido) y completa 9 de 10 en los lotes 3 y 4, tantas o más que las celdas con profundidad. El barrido con profundidad tampoco mejora a la FSM en esos lotes: la comparación (ii) da δ = −0.49 y −0.40, en contra de la profundidad, aunque sin significancia. Lo que comparten las tres celdas que completan, y le falta a `reactive`, es la evasión por flujo óptico y alguna forma de salir de un atasco, aunque sea ciega. La profundidad estimada solo se asocia a más éxitos en el lote 6 (`fsm:depth` 9/10 frente a 5/10 de `fsm:blind`, no significativo).

**El plan de ruta cambia los tres escenarios.** El plan del VLM, común a las cuatro celdas, desvía 3 de 7 tramos en `townsim_ini`, 2 de 3 en `townsim_calib_cruce_frontal` y 4 de 8 en `citysim_pilot` (§10.3.0, punto 5). Las celdas no enfrentan, por lo tanto, la obstrucción de la recta del manifiesto sino la de la ruta planificada, y no se midió si el plan facilita o dificulta cada escenario.

**Lote 3, `townsim_ini` (corredor arbolado).** `slm:depth` supera a `fsm:depth` en SPL con un efecto grande; frente a `fsm:blind` el efecto también es grande (δ = +0.73) pero no supera la corrección. Las tres celdas con evasión completan 9 de 10. `reactive` no completa ninguna: las 10 corridas quedan trabadas en el corredor antes de WP_2_CENTRO_CORREDOR hasta el tope de tiempo. El desglose por tramo (`summary_by_wp.csv`) muestra que `slm` es más rápido en casi todos los tramos, incluido el retorno a cielo abierto (20 s frente a 56–63 s de las FSM), y más lento en uno solo, la salida del corredor (71 s frente a 46–49 s), que se vuela por el desvío de 50 m a la izquierda que eligió el plan. La ventaja no se concentra en el follaje, como esperaba §10.8.2: está repartida a lo largo de la ruta y la explica sobre todo la lentitud general de la FSM (§11.5), no una mejor decisión en el corredor.

**Lote 4, `townsim_calib_cruce_frontal` (bloqueo frontal).** Ninguna diferencia significativa. `slm:depth` completa 5 de 10 —las cinco fallas son `physics_locked`— y es la celda más rápida cuando completa (479 s); `fsm:blind` completa 9 de 10 y tiene el mejor SPL. El lote es válido según el criterio de §10.8.2, porque el tramo de cruce sí produce atascos: 42 en `slm` y 134 en `fsm:depth`. `reactive` no completa ninguna: 8 de 10 quedan frente al edificio, camino al punto de paso VIA_WP_3_2. El tramo de cruce (WP_2 → WP_3), el que el escenario diseñó para enfrentar la fachada de frente, no se vuela por la recta: el plan lo reemplaza por un desvío de 25 m a la izquierda, y es en ese desvío donde `reactive` queda trabado. El lote mide, por lo tanto, la resolución de un bloqueo frontal sobre la ruta del plan, no sobre la recta del manifiesto.

**Lote 6, `citysim_pilot` (rodeo de manzanas).** `slm:depth` completa las 10 y supera a las dos FSM con separación completa. El barrido no mejora significativamente a la FSM (ii), aunque `fsm:depth` completa 9 frente a 5 de `fsm:blind`, cuyo escape ciego termina incrustado a −30 m en la misma zona en tres corridas. `reactive` también completa las 10 —el resultado que §10.8.2 no esperaba—, porque el plan de ruta, común a las cuatro celdas, ya rodea el único tramo con la recta bloqueada (WP_2 → WP_3). En este lote la obstrucción la resuelve el plan en tierra, no la política en vuelo: la comparación entre celdas mide cómo cada una sigue una ruta que ya evita el bloqueo.

**Capa estratégica.** Las tres celdas `slm:depth` consultan la capa unas 240–270 veces por misión, con latencia mediana de 114–135 ms.

| Lote | Consultas | `directo_libre` | Sub-meta | Sin sector libre |
|---|---|---|---|---|
| 3 | 2362 | 66 % | 29 % | 5 % |
| 4 | 2450 | 75 % | 21 % | 4 % |
| 6 | 2734 | 74 % | 24 % | 2 % |

La capa discrimina: declara el camino directo libre en dos tercios a tres cuartos de las consultas y propone sub-metas en el resto, más que en `townsim_clear` (8 %). No se midió el avance hacia el waypoint real tras cada sub-meta (§10.6.3), de modo que no se puede afirmar que cada sub-meta acerque a la meta.

**Barrido de atascos.** Con `slm:depth` la tasa mediana de resolución es 0.33 en el lote 3, 0.25 en el 4 y 0.75 en el 6; con `fsm:depth`, 0.45, 0.38 y 0.33. «Resuelto» significa que el barrido encontró un rumbo transitable, no que el dron haya salido del atasco (§10.6.4). `slm` declara muchos menos atascos que la FSM: 23, 42 y 7 frente a 180, 134 y 176.

**Seguridad.** Sin colisiones registradas, pero DistMin cae a ~0.1–0.25 m en todas las celdas con evasión de los lotes 3 y 4: el dron roza el follaje y las fachadas sin que la bandera de colisión lo registre, y las fallas son de ese tipo, abortos por quedar apoyado en la geometría.

## 11.5 Dos defectos del brazo FSM que afectan las comparaciones

El análisis de las corridas encontró dos defectos de implementación del brazo FSM, presentes en los seis lotes. No afectan a `slm` ni a `reactive`. Ambos hacen a la FSM más lenta y la exponen a más fallas, de modo que **todas las comparaciones contra la FSM están sesgadas a favor de `slm`**, con un sesgo que no se puede estimar con estos datos.

**Deadlock falso al despegar.** El runner cuenta el progreso hacia el waypoint también durante el ascenso vertical inicial. La distancia horizontal no cambia mientras el dron sube, el contador de atasco llega a ~30–37 ciclos y la FSM, que usa ese contador, declara un deadlock apenas termina el ascenso, sin haberse movido. El barrido descarta entonces el rumbo hacia el waypoint como rumbo fallido y manda al dron en otra dirección. `slm` decide sus atascos con su propio detector (cap. 5 §5.3.1) y no lo sufre. Ocurre en las 10 corridas `fsm:depth` de los lotes 1, 2, 3, 5 y 6, en las 10 `fsm:blind` de los lotes 3 y 6, y en pocas del lote 4 (1 de `fsm:depth`, 3 de `fsm:blind`), cuyo primer waypoint es un ascenso en el lugar. Su costo depende del escenario: en `townsim_clear`, con WP_1 sobre el spawn, la FSM igual llega en ~7 s; en `citysim_clear` tarda 112 s de mediana en alcanzar WP_1, contra 47 s de `slm`. Contradice la condición del diseño de que el despegue no es un atasco (§10.12.2).

**Escape agotado por el techo de altitud.** La FSM no sube por encima de `MAX_ESCAPE_ALT_M` = 30 m, el mismo techo que usa el escape del brazo `slm`. Por encima, cada escape vertical se convierte en un giro de 90° con un desvío lateral inyectado. En las rutas a −30 m o más arriba eso ocurre con frecuencia: 281 veces en las 10 corridas `fsm:depth` de `citysim_clear` (entre 17 y 53 por corrida), con las cuatro fallas en el tramo a −50 m; 42 en `townsim_clear`, cuyo crucero va justo a −30 m; y 98 en `fsm:blind` del lote 6, cuyo escape ciego sube hasta el techo. Los desvíos sacan a la FSM de la ruta libre hacia las estructuras.

Los dos defectos explican buena parte de lo que separa a la FSM de las otras celdas: el orden inesperado `slm` < `fsm` en los controles (§11.3), la proximidad de la FSM a las estructuras, el gobernador de velocidad activo en el 48–79 % de sus ciclos y sus fallas en `citysim_clear`. También afectan la comparación (ii) de los lotes con obstrucción, porque las dos celdas FSM los comparten.

## 11.6 Ritmo del lazo y latencias

El período mediano del lazo es de 0.20–0.24 s en todas las celdas salvo `reactive` en los lotes 3, 4 y 6 (0.26–0.31 s): el lazo cumple aproximadamente su objetivo de 5 Hz. La latencia del grafo por ciclo —el tiempo de reacción del sistema, desde el fotograma hasta el comando (§10.6.2)— tiene mediana de 110–303 ms y p95 de 231–364 ms, sin diferencias sistemáticas entre brazos; depende sobre todo del escenario (MiniSim es el más rápido). La capa estratégica no suma latencia al ciclo: corre en su propio hilo y responde en 104–135 ms de mediana.

## 11.7 Síntesis por hipótesis

| Hipótesis | Evidencia | Lectura |
|---|---|---|
| **H1** — beneficio en obstrucción | `slm:depth` > `fsm:depth` en SPL en los lotes 3 y 6 (δ = +0.81 y +1.00, significativas); > `fsm:blind` en el lote 6 (δ = +1.00); sin diferencia en el lote 4 | Parcial. Ninguna FSM supera a `slm` en ningún lote, pero las ventajas están sesgadas por los defectos de la FSM (§11.5): en el lote 3 se reparten a lo largo de la ruta y en el lote 6 la obstrucción la resuelve el plan común. En el bloqueo frontal, el escenario donde se esperaba el beneficio más claro, `slm` pierde la mitad de las corridas |
| **H2** — costo aditivo | $t_{\text{slm}}/t_{\text{reactive}}$ = 1.95, 1.49 y 1.39 con rutas de ~180, ~420 y ~600 m; las nueve comparaciones de los controles, significativas | La predicción se cumple: la razón decrece con la ruta. El mecanismo postulado no: el costo no lo pone la inferencia (consultas × latencia), que no bloquea, sino lo que el brazo hace con las respuestas —sub-metas en ruta libre, maniobras— y el gobernador de velocidad. Con un escenario por tier y controles que difieren en más que la longitud, la forma aditiva es descriptiva |
| **H3** — interacción brazo × escenario | Criterio declarado (§10.8.3): cambio de signo del efecto `slm` − `fsm` entre controles y obstrucción. `slm` gana o empata frente a la FSM en los seis lotes | **No se sostiene con el criterio declarado**: frente a la FSM no hay cambio de signo, y los defectos de la FSM impiden separar la política de la implementación. *Exploratorio:* frente a `reactive` el signo sí cambia (`slm` pierde en tiempo en los controles y gana en los lotes 3 y 4, donde `reactive` no completa ninguna corrida), pero `fsm:blind`, sin capa estratégica ni profundidad, logra lo mismo: ese cambio lo produce la evasión del lazo rápido y el escape de atascos, no la deliberación |

El mapa que resume la corrida: **en ruta libre el brazo `slm` solo cuesta** (entre 1.4 y 2 veces el tiempo del control reactivo, sin ganar seguridad); **donde la ruta directa se tranca, tener evasión por flujo óptico y una salida de los atascos es lo que permite completar la misión**, cosa que el control reactivo, que no tiene ninguna de las dos, no logra; la profundidad estimada no es necesaria para eso, porque la FSM sin barrido completa tanto como las celdas que la usan; y **la ventaja de la capa estratégica frente a una FSM no está demostrada** con esta implementación de la FSM. El VLM no interviene en vuelo; su único aporte medible está en el plan de ruta en tierra (§11.0), que en `citysim_pilot` alcanza para que hasta el control reactivo complete la misión, y cuyo efecto en los lotes 3 y 4, donde también desvía la ruta, no se midió.
