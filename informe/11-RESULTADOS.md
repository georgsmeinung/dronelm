# 11. Resultados: el VLM a bordo y la comparación entre brazos

Este capítulo reporta dos instrumentos. El banco de prueba a bordo (IT.11.0) mide, fuera de vuelo, qué preguntas sabe responder cada fuente del lazo lento; su resultado responde la primera parte del objetivo 3 (cap. 1, IT.1.2) y fija la configuración que vuela. La corrida productiva v4 (IT.11.1–IT.11.7) evalúa esa configuración: seis lotes, uno por escenario, con 10 semillas por celda y 210 corridas, analizadas con el protocolo del capítulo 10 (IT.10.7). En ella **ningún modelo de lenguaje decide en vuelo**: el brazo `depth2loop` —`slm` en el código y en los datos— responde la capa estratégica con la red de profundidad estimada (Anexo 12, IT.A12.1), y el VLM solo interviene antes del despegue, en el plan de ruta de los lotes 3, 4 y 6. El detalle por lote está en el Anexo 12 (IT.A12.12), y los datos crudos, en <https://bit.ly/dlm-data>.

## 11.0 Banco de prueba del VLM: línea base a bordo

El banco (cap. 10, IT.10.2) compara las respuestas de LFM2.5-VL-1.6B, cuantizado y **en la misma GPU que Unreal Engine y el grafo de control** (cap. 8, IT.8.1.2), con una etiqueta de referencia tomada de la profundidad del simulador en la misma pose.

**Datos.** 915 poses válidas de las 21 corridas de `citysim_pilot`, con el centro libre en el 51 %; cada pregunta se hace con decodificación restringida, temperatura 0 y hasta 60 muestras por clase (Anexo 12, IT.A12.12.1). El AUC, calculado con los *logprobs*, es solo diagnóstico.

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

**Ninguna pregunta pasa.** Tres son constantes y el resto queda a pocos puntos del azar. En la pregunta de vuelo, las filas de arriba y de abajo salen «libre» en el 100 % de las muestras (realmente libres: 72–78 % y 38–47 %), y en la del medio la respuesta depende de la posición del sector más que de la escena; con las etiquetas permutadas coincide con la del orden normal en el 75 % de los sectores. Los *logprobs* no rescatan la grilla (AUC 0.53).

**Consecuencia para el vuelo.** Con el VLM como fuente, la sub-meta saldría de la posición de las celdas y no de la escena, y el barrido declararía transitables todos los rumbos. Por eso el VLM no vuela, y esta es la respuesta a la primera parte del objetivo 3: LFM2.5-VL-1.6B, a bordo y *zero-shot*, no sirve como fuente de decisión táctica.

**Plan de ruta sobre el mapa** (juicio por parches, cap. 4 IT.4.3.1; 59 candidatas en 11 tramos de `citysim_pilot` y `citysim_clear`, 28 realmente libres). La probabilidad media de «calle» separa las rutas libres de las bloqueadas con AUC 0.81, calculado sobre candidatas dependientes: las de un mismo tramo comparten mapa y extremos (cap. 12, IT.12.3). La ruta elegida es libre en 10 de 11 tramos, igual que la recta: en el único tramo con la recta bloqueada el plan elige un desvío libre, y en un tramo de `citysim_clear` elige un desvío bloqueado con la recta libre.

**La misma pregunta con profundidad estimada.** Con el mismo fotograma y la misma etiqueta, el p5 de la profundidad estimada separa sectores libres de bloqueados con exactitud balanceada del 75 % [72–77 %] y AUC 0.83, en 82 ms, y rumbos abiertos de cerrados en los barridos con AUC 0.87: es la única señal que pasa el criterio (cap. 6, IT.6.12.1).

## 11.1 Corrida productiva v4: datos y validez

**Configuración e integridad.** La del capítulo 10. Cada lote se corrió de una vez, con un solo `code_version` y sin cambios sin confirmar, y ninguna corrida se descarta: 210 válidas, ninguna con menos de 50 ciclos y ninguna colisión registrada por la bandera de AirSim. Esa bandera no ve el contacto con el follaje ni el dron apoyado sobre una cornisa (IT.10.6.1): en los lotes con obstrucción la distancia mínima cae a ~0.1 m, y 21 corridas terminan por `physics_locked`, dron apoyado o incrustado en la geometría (IT.11.2). «Sin colisiones» significa aquí sin colisiones registradas, no sin contactos. NB1 reproduce el análisis y verifica sus tablas contra el reporte (NB1.10).

**Distancia mínima y SPL.** DistMin se calcula sin la primera muestra de la auditoría, un artefacto del arranque. En los lotes 3, 4 y 6 todas las celdas vuelan los puntos de paso del plan de ruta, de modo que su SPL queda por debajo de 1 aun en la ruta perfecta; el sesgo es igual dentro de cada lote (IT.A12.12.2).

## 11.2 Resultados por celda

Éxito con su IC de Wilson al 95 %; SPL, tiempo de las misiones exitosas y DistMin como mediana [p25, p75]; terminación de las corridas fallidas (PL: `physics_locked`; TT: tope de tiempo). El escenario de cada lote está en la tabla de IT.10.4.2.

| Lote | Celda | Éxito [IC 95 %] | SPL | Tiempo de éxito (s) | DistMin (m) | Fallas |
|---|---|---|---|---|---|---|
| 1 | `depth2loop` | 10/10 [0.72, 1.00] | 0.54 [0.51, 0.56] | 165.1 [159.8, 171.4] | 15.51 [15.47, 15.64] | — |
| 1 | `fsm:depth` | 10/10 [0.72, 1.00] | 0.38 [0.35, 0.43] | 306.4 [252.9, 369.5] | 15.49 [15.44, 15.63] | — |
| 1 | `reactive` | 10/10 [0.72, 1.00] | 0.63 [0.63, 0.63] | 84.9 [84.7, 85.3] | 15.47 [15.46, 15.50] | — |
| 2 | `depth2loop` | 10/10 [0.72, 1.00] | 0.89 [0.87, 0.90] | 379.8 [366.4, 399.1] | 16.41 [12.43, 16.48] | — |
| 2 | `fsm:depth` | 9/10 [0.60, 0.98] | 0.76 [0.72, 0.80] | 488.6 [434.1, 516.2] | 1.55 [0.24, 3.63] | 1 PL |
| 2 | `reactive` | 10/10 [0.72, 1.00] | 0.93 [0.91, 0.93] | 272.6 [272.4, 280.8] | 14.77 [7.89, 16.68] | — |
| 5 | `depth2loop` | 9/10 [0.60, 0.98] | 0.70 [0.68, 0.72] | 286.2 [277.1, 288.9] | 11.45 [10.38, 12.50] | 1 PL |
| 5 | `fsm:depth` | 6/10 [0.31, 0.83] | 0.42 [0.00, 0.43] | 705.9 [664.8, 748.9] | 0.10 [0.10, 0.11] | 4 PL |
| 5 | `reactive` | 10/10 [0.72, 1.00] | 0.79 [0.79, 0.79] | 192.3 [190.6, 194.1] | 10.85 [10.70, 10.97] | — |
| 3 | `depth2loop` | 9/10 [0.60, 0.98] | 0.48 [0.43, 0.48] | 519.9 [517.9, 524.3] | 0.13 [0.11, 0.37] | 1 PL |
| 3 | `fsm:depth` | 9/10 [0.60, 0.98] | 0.32 [0.31, 0.37] | 805.8 [704.9, 822.1] | 0.23 [0.12, 0.38] | 1 PL |
| 3 | `fsm:blind` | 9/10 [0.60, 0.98] | 0.38 [0.35, 0.40] | 625.1 [594.7, 684.6] | 0.24 [0.11, 0.38] | 1 PL |
| 3 | `reactive` | 0/10 [0.00, 0.28] | 0.00 | — | 1.94 [1.35, 2.36] | 10 TT |
| 4 | `depth2loop` | 5/10 [0.24, 0.76] | 0.28 [0.00, 0.58] | 479.0 [401.7, 497.0] | 0.14 [0.12, 0.36] | 5 PL |
| 4 | `fsm:depth` | 8/10 [0.49, 0.94] | 0.41 [0.33, 0.43] | 608.3 [558.9, 687.1] | 0.25 [0.16, 0.34] | 2 PL |
| 4 | `fsm:blind` | 9/10 [0.60, 0.98] | 0.46 [0.40, 0.49] | 492.4 [469.3, 572.7] | 0.14 [0.12, 0.26] | 1 PL |
| 4 | `reactive` | 0/10 [0.00, 0.28] | 0.00 | — | 0.11 [0.10, 0.18] | 10 TT |
| 6 | `depth2loop` | 10/10 [0.72, 1.00] | 0.48 [0.46, 0.51] | 483.1 [452.7, 513.0] | 4.14 [2.32, 4.14] | — |
| 6 | `fsm:depth` | 9/10 [0.60, 0.98] | 0.34 [0.33, 0.37] | 805.6 [688.1, 834.7] | 1.16 [0.20, 2.63] | 1 PL |
| 6 | `fsm:blind` | 5/10 [0.24, 0.76] | 0.14 [0.00, 0.34] | 712.5 [625.4, 870.8] | 0.11 [0.10, 1.28] | 3 PL, 2 TT |
| 6 | `reactive` | 10/10 [0.72, 1.00] | 0.53 [0.53, 0.53] | 313.2 [309.6, 319.4] | 4.14 [4.14, 4.14] | — |

**Cómo terminan las corridas que fallan.** La bandera de colisión de AirSim no se activa en ninguna de las 210. De las 23 fallas de los brazos con evasión, 21 son abortos por `physics_locked`: el dron queda apoyado o incrustado en la malla y el vigilante corta la corrida (cap. 5 IT.5.4). Son, en la práctica, contactos con la geometría que la bandera no detecta (IT.10.6.1). Las otras 2 y las 20 de `reactive` en los lotes 3 y 4 llegan al tope de tiempo. `reactive` es casi determinista —sus 10 corridas difieren en pocos segundos—, lo que confirma que el entorno aporta poca variación por sí solo (IT.10.5.1).

## 11.3 Escenarios de control (lotes 1, 2 y 5): costo de la arquitectura (H2)

**Comparaciones planificadas** (tiempo de las misiones exitosas; δ > 0 indica que la primera celda tarda más):

| Lote | Comparación | n | δ de Cliff [IC 95 %] | p (permutación exacta) | p Bonferroni |
|---|---|---|---|---|---|
| 1 | `depth2loop` vs. `fsm` | 10 / 10 | −1.00 [−1.00, −1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 1 | `depth2loop` vs. `reactive` | 10 / 10 | +1.00 [+1.00, +1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 1 | `fsm` vs. `reactive` | 10 / 10 | +1.00 [+1.00, +1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 2 | `depth2loop` vs. `fsm` | 10 / 9 | −0.98 [−1.00, −0.87] | 4.3 × 10⁻⁵ | 7.8 × 10⁻⁴ |
| 2 | `depth2loop` vs. `reactive` | 10 / 10 | +1.00 [+1.00, +1.00] | 1.1 × 10⁻⁵ | 2.0 × 10⁻⁴ |
| 2 | `fsm` vs. `reactive` | 9 / 10 | +1.00 [+1.00, +1.00] | 2.2 × 10⁻⁵ | 3.9 × 10⁻⁴ |
| 5 | `depth2loop` vs. `fsm` | 9 / 6 | −1.00 [−1.00, −1.00] | 4.0 × 10⁻⁴ | 0.0072 |
| 5 | `depth2loop` vs. `reactive` | 9 / 10 | +1.00 [+1.00, +1.00] | 2.2 × 10⁻⁵ | 3.9 × 10⁻⁴ |
| 5 | `fsm` vs. `reactive` | 6 / 10 | +1.00 [+1.00, +1.00] | 2.5 × 10⁻⁴ | 0.0045 |

Las nueve son significativas tras Bonferroni (α = 0.0028), con separación completa o casi: en los tres tiers el orden es **`reactive` < `depth2loop` < `fsm`**. El orden esperado en IT.A12.8.1 era `reactive` < `fsm` < `depth2loop`: la FSM resulta la más lenta, por las razones de IT.11.5.

**Razón de tiempos y su dependencia de la ruta.**

| Lote | Ruta | $t_{\text{depth2loop}}/t_{\text{reactive}}$ | $t_{\text{depth2loop}} - t_{\text{reactive}}$ | Consultas por misión (`depth2loop`) | Sub-metas | $t_{\text{fsm}}/t_{\text{reactive}}$ |
|---|---|---|---|---|---|---|
| 1 `minisim_clear` | ~180 m | 1.95 | 80 s | 90 | 27 % | 3.61 |
| 5 `citysim_clear` | ~420 m | 1.49 | 94 s | 151 | 37 % | 3.67 |
| 2 `townsim_clear` | ~600 m | 1.39 | 107 s | 235 | 8 % | 1.79 |

Ordenada por longitud de ruta, la razón $t_{\text{depth2loop}}/t_{\text{reactive}}$ decrece —1.95, 1.49, 1.39— y la diferencia absoluta crece mucho menos que la ruta (×3.3 la ruta, ×1.3 la diferencia): es la forma que predice H2, un costo aproximadamente aditivo (IT.10.1), aunque con un solo escenario por tier la progresión es descriptiva. **El mecanismo que postula H2 no se confirma**: H2 atribuía el costo al número de consultas por su latencia, pero las consultas son periódicas y no bloquean al dron.

**De dónde sale el costo.** No de esperar a la capa —responde en 104–125 ms y el dron no frena—, sino de lo que el brazo hace con las respuestas y del gobernador de velocidad, que ninguna celda separa: las sub-metas en ruta libre (27 % de las consultas en MiniSim, donde `depth2loop` recorre 17 % más que `reactive`) y un gobernador activo en el 27–43 % de los ciclos de `depth2loop`, frente al 7–18 % de `reactive`, sobre todo durante los giros, cuando el estimador no estima (IT.A12.12.3).

**Seguridad.** Sin colisiones registradas en ningún brazo, con la salvedad de que la bandera no ve el follaje ni los apoyos (IT.10.6.1): 6 corridas de los controles terminan por `physics_locked` —1 de `depth2loop` y 5 de la FSM—, contactos que la bandera no registra. DistMin de `depth2loop` y `reactive` es la misma en los tres controles (δ de 0.07 a 0.31, sin diferencia). La FSM pasa mucho más cerca en los dos controles con estructuras: 1.55 m en `townsim_clear` y 0.10 m en `citysim_clear` (δ = +0.90 y +0.94 a favor de `depth2loop`, secundarias).

**Validez del control.** El lote 1 no tiene fallas; las cinco de `citysim_clear` ocurren en el mismo tramo, con el dron incrustado al salir de una ruta que es libre (IT.A12.12.2).

## 11.4 Escenarios con obstrucción (lotes 3, 4 y 6): beneficio de la capa deliberativa (H1)

**Comparaciones planificadas** (SPL; δ > 0 indica mejor SPL de la primera celda):

| Lote | Comparación | δ de Cliff [IC 95 %] | p | p Bonferroni | Éxito A / B |
|---|---|---|---|---|---|
| 3 | (i) `depth2loop` vs. `fsm:blind` | +0.73 [+0.28, +1.00] | 0.0039 | 0.071 | 9/10 / 9/10 |
| 3 | (ii) `fsm:depth` vs. `fsm:blind` | −0.49 [−0.90, 0.00] | 0.065 | 1.00 | 9/10 / 9/10 |
| 3 | (iii) `depth2loop` vs. `fsm:depth` | **+0.81 [+0.40, +1.00]** | 0.0011 | **0.019** | 9/10 / 9/10 |
| 4 | (i) `depth2loop` vs. `fsm:blind` | +0.05 [−0.52, +0.62] | 0.87 | 1.00 | 5/10 / 9/10 |
| 4 | (ii) `fsm:depth` vs. `fsm:blind` | −0.40 [−0.82, +0.12] | 0.14 | 1.00 | 8/10 / 9/10 |
| 4 | (iii) `depth2loop` vs. `fsm:depth` | +0.10 [−0.52, +0.66] | 0.73 | 1.00 | 5/10 / 8/10 |
| 6 | (i) `depth2loop` vs. `fsm:blind` | **+1.00 [+1.00, +1.00]** | 1.1 × 10⁻⁵ | **2.0 × 10⁻⁴** | 10/10 / 5/10 |
| 6 | (ii) `fsm:depth` vs. `fsm:blind` | +0.39 [−0.15, +0.84] | 0.14 | 1.00 | 9/10 / 5/10 |
| 6 | (iii) `depth2loop` vs. `fsm:depth` | **+1.00 [+1.00, +1.00]** | 1.1 × 10⁻⁵ | **2.0 × 10⁻⁴** | 10/10 / 9/10 |

Tres de las nueve son significativas tras Bonferroni, las tres a favor de `depth2loop`. Ninguna favorece a una FSM. Las tasas de éxito no difieren significativamente en ningún par (Fisher, secundaria), salvo (i) en el lote 6 sin corrección (p = 0.033).

**Qué separa a las celdas que completan de `reactive`.** `fsm:blind` no usa la profundidad estimada en ninguna decisión (no tiene capa estratégica ni barrido) y completa 9 de 10 en los lotes 3 y 4, tantas o más que las celdas con profundidad. El barrido con profundidad tampoco mejora a la FSM en esos lotes: la comparación (ii) da δ = −0.49 y −0.40, en contra de la profundidad, aunque sin significancia. Lo que comparten las tres celdas que completan, y le falta a `reactive`, es la evasión por flujo óptico y alguna forma de salir de un bloqueo, aunque sea ciega. La profundidad estimada solo se asocia a más éxitos en el lote 6 (`fsm:depth` 9/10 frente a 5/10 de `fsm:blind`, no significativo).

**El plan de ruta cambia los tres escenarios.** Común a las cuatro celdas, desvía 3 de 7 tramos en `townsim_ini`, 2 de 3 en `townsim_calib_cruce_frontal` y 4 de 8 en `citysim_pilot`: las celdas enfrentan la obstrucción de la ruta planificada, y no se midió si el plan facilita o dificulta cada escenario.

**Lote 3, `townsim_ini` (corredor arbolado).** `depth2loop` supera a `fsm:depth` en SPL con un efecto grande, y a `fsm:blind` con un efecto grande que no supera la corrección. `reactive` queda trabado en el corredor en las 10 corridas. La ventaja no se concentra en el follaje, como esperaba IT.A12.8.2: está repartida a lo largo de la ruta y la explica sobre todo la lentitud general de la FSM (IT.11.5).

**Lote 4, `townsim_calib_cruce_frontal` (bloqueo frontal).** Ninguna diferencia significativa. `depth2loop` completa 5 de 10 —las cinco fallas son `physics_locked`— y es la celda más rápida cuando completa; `fsm:blind` completa 9 y tiene el mejor SPL. El plan reemplaza el cruce frontal por un desvío de 25 m, de modo que el lote mide la resolución de un bloqueo sobre la ruta del plan, no sobre la del manifiesto.

**Lote 6, `citysim_pilot` (rodeo de manzanas).** `depth2loop` completa las 10 y supera a las dos FSM con separación completa. `reactive` también completa las 10, porque el plan de ruta ya rodea el único tramo con la recta bloqueada: en este lote la obstrucción la resuelve el plan en tierra, no la política en vuelo. El detalle de los tres lotes está en el Anexo 12 (IT.A12.12.4).

**Capa estratégica.** `depth2loop` consulta la capa unas 240–270 veces por misión, en 114–134 ms de mediana.

| Lote | Consultas | `directo_libre` | Sub-meta | Sin sector libre |
|---|---|---|---|---|
| 3 | 2362 | 66 % | 29 % | 5 % |
| 4 | 2450 | 75 % | 21 % | 4 % |
| 6 | 2734 | 74 % | 24 % | 2 % |

La capa discrimina: declara el camino directo libre en dos tercios a tres cuartos de las consultas y propone sub-metas en el resto, más que en `townsim_clear` (8 %).

**Avance tras cada sub-meta** (IT.10.6.3; NB1.13). A los 20 s de cada respuesta, el avance mediano sobre la ruta del manifiesto tras una sub-meta es de 20.3 m [17.5–21.6] en el lote 3, 12.0 m [9.7–14.4] en el 4 y 18.5 m [18.1–18.9] en el 6, frente a 14.1, 15.7 y 19.0 m tras una respuesta `directo_libre`; en los controles difieren en menos de 1.5 m. Las sub-metas no frenan al dron, pero solo en el corredor arbolado avanzan más que el camino directo, y en el bloqueo frontal, donde rodear debía ayudar, avanzan menos. La comparación no es contrafactual —las sub-metas aparecen donde el camino directo no está libre, y ninguna celda vuela `depth2loop` sin la capa—: muestra que la capa no estorba, no que ayude. La comparación por ventanas con los otros brazos está en el Anexo 12 (IT.A12.12.5).

**Barrido de bloqueos.** Con `depth2loop` la tasa mediana de resolución es 0.33 en el lote 3, 0.25 en el 4 y 0.75 en el 6; con `fsm:depth`, 0.45, 0.38 y 0.33. «Resuelto» significa que el barrido encontró un rumbo transitable, no que el dron haya salido del bloqueo (IT.10.6.3). `depth2loop` declara muchos menos bloqueos que la FSM: 23, 42 y 7 frente a 180, 134 y 176.

**Seguridad.** Sin colisiones registradas, pero la bandera de AirSim no ve el follaje ni los apoyos (IT.10.6.1): DistMin cae a ~0.1–0.25 m en todas las celdas con evasión de los lotes 3 y 4 —el dron roza el follaje y las fachadas sin que la bandera lo registre— y 15 corridas de estos lotes terminan por `physics_locked`, abortos por quedar apoyado en la geometría.

## 11.5 Dos defectos del brazo FSM que afectan las comparaciones

El análisis de las corridas encontró dos defectos de implementación del brazo FSM, presentes en los seis lotes, que la hacen más lenta y la exponen a más fallas: **todas las comparaciones contra la FSM están sesgadas a favor de `depth2loop`**, con un sesgo que no se puede estimar con estos datos.

**Deadlock falso al despegar.** El runner cuenta el progreso hacia el waypoint también durante el ascenso inicial, y la FSM, que usa ese contador, declara un deadlock apenas termina el ascenso; el barrido descarta entonces el rumbo hacia el waypoint y manda al dron en otra dirección. `depth2loop` decide sus bloqueos con su propio detector (cap. 5, IT.5.3.1) y no lo sufre. Ocurre en casi todas las corridas FSM de los lotes 1, 2, 3, 5 y 6: en `citysim_clear` la FSM tarda 112 s de mediana en alcanzar el primer waypoint, contra 47 s de `depth2loop`.

**Escape agotado por el techo de altitud.** Por encima de `MAX_ESCAPE_ALT_M` = 30 m, cada escape vertical de la FSM se convierte en un giro de 90° con un desvío lateral —281 veces en las 10 corridas `fsm:depth` de `citysim_clear`—, que la saca de la ruta libre hacia las estructuras.

Los dos defectos explican buena parte de lo que separa a la FSM de las otras celdas: el orden inesperado `depth2loop` < `fsm` en los controles (IT.11.3), la proximidad de la FSM a las estructuras, el gobernador de velocidad activo en el 48–79 % de sus ciclos y sus fallas en `citysim_clear`. También afectan la comparación (ii) de los lotes con obstrucción, porque las dos celdas FSM los comparten.

## 11.6 Ritmo del lazo y latencias

El período mediano del lazo es de 0.20–0.24 s en todas las celdas salvo `reactive` en los lotes 3, 4 y 6 (0.26–0.31 s): el lazo cumple aproximadamente su objetivo de 5 Hz. La latencia del grafo por ciclo —el tiempo de reacción del sistema, desde el fotograma hasta el comando (IT.10.6.2)— tiene mediana de 110–303 ms y p95 de 231–364 ms, sin diferencias sistemáticas entre brazos; depende sobre todo del escenario (MiniSim es el más rápido). La capa estratégica no suma latencia al ciclo: corre en su propio hilo y responde en 104–134 ms de mediana. Los valores por celda están en NB1.9 (`notebooks/output/v4_latencias.csv`).

## 11.7 Síntesis por hipótesis

| Hipótesis | Evidencia | Lectura |
|---|---|---|
| **H1** — beneficio en obstrucción | `depth2loop` > `fsm:depth` en SPL en los lotes 3 y 6 (δ = +0.81 y +1.00, significativas); > `fsm:blind` en el lote 6 (δ = +1.00); sin diferencia en el lote 4 | **No atribuible.** Ninguna FSM supera a `depth2loop` en ningún lote, pero las ventajas están sesgadas por los defectos de la FSM (IT.11.5): en el lote 3 se reparten a lo largo de la ruta y en el lote 6 la obstrucción la resuelve el plan común. En el bloqueo frontal, el escenario donde se esperaba el beneficio más claro, `depth2loop` pierde la mitad de las corridas, y sus sub-metas avanzan hacia el waypoint menos que el camino directo (IT.11.4) |
| **H2** — costo aditivo | $t_{\text{depth2loop}}/t_{\text{reactive}}$ = 1.95, 1.49 y 1.39 con rutas de ~180, ~420 y ~600 m; las nueve comparaciones de los controles, significativas | La predicción se cumple: la razón decrece con la ruta. El mecanismo postulado no: el costo no lo pone la inferencia (consultas × latencia), que no bloquea, sino lo que el brazo hace con las respuestas —sub-metas en ruta libre, maniobras— y el gobernador de velocidad. Con un escenario por tier y controles que difieren en más que la longitud, la forma aditiva es descriptiva |
| **H3** — interacción brazo × escenario | Criterio declarado (IT.10.7.4): cambio de signo del efecto `depth2loop` − `fsm` entre controles y obstrucción. `depth2loop` gana o empata frente a la FSM en los seis lotes | **No se sostiene con el criterio declarado**: frente a la FSM no hay cambio de signo, y los defectos de la FSM impiden separar la política de la implementación. *Exploratorio:* frente a `reactive` el signo sí cambia (`depth2loop` pierde en tiempo en los controles y gana en los lotes 3 y 4, donde `reactive` no completa ninguna corrida), pero `fsm:blind`, sin capa estratégica ni profundidad, logra lo mismo: ese cambio lo produce la evasión del lazo rápido y el escape de bloqueos, no la deliberación |
