# Revisión del informe contra el código y los datos v4 (2026-10-27)

Alcance: código de `airsim-loop/src` y `experiments/` en HEAD `4cb48b0d`; caps. 0, 1, 5, 7, 10, 11 y 12 leídos completos; cap. 9 en §9.1, §9.7–§9.9; caps. 6 y 8 por búsqueda puntual; caps. 2–4 y anexos no revisados.
Qué se verificó: `analisis_lotes.md` y CSV de `airsim-runs/produccion/v4`, manifiestos, `plan.json` del plan de ruta, dataset TTC (`airsim-runs/test/ttc`), suite de tests.

## Lo que está bien

- **Integridad de la corrida.** Entre `b0332e1a` y HEAD no cambió nada en `airsim-loop/src`, salvo `runner.py` (+24/−4). Coincide con lo que dice §11.1.
- **Cifras del cap. 11.** Las tablas §11.2–§11.4 coinciden con `analisis_lotes.md`: éxito, IC de Wilson, SPL, tiempos, δ de Cliff y p con Bonferroni. Las razones t_slm/t_reactive (1.95, 1.49, 1.39) y las diferencias (80, 94, 107 s) cierran.
- **Cap. 5 frente a `graph.py`, `stall_detector.py`, `fsm.py`, `deep_scan.py` y `depth_client.py`.** El orden de reglas, los umbrales, las duraciones y la supresión del contador durante el despegue coinciden con el código. §11.5 también: la FSM cuenta el atasco con `evasion_stuck_cycles` y `slm` con su `StallDetector`, que no cuenta durante el despegue.
- **Validación de TTC.** `analyze_ttc.py` sobre los tres archivos reproduce los valores informados: r = −0.034, error 65.9 %, AUC 0.968 / 0.972 / 0.960 y umbrales 1.93 / 3.18 / 4.58 s.
- **Suite de tests:** 321 pasan (`airsimenv`, 20 s).
- **Honestidad de las conclusiones.** El cap. 12 ya declara los defectos de la FSM, que la capa estratégica no se midió y que el VLM no discrimina.

## A. Problemas que afectan a las conclusiones

### A1. «La evasión con profundidad estimada es lo que permite completar la misión»: los propios datos lo contradicen

Dónde aparece: §11.7, §12.2 (título «la evasión con profundidad decide» y la síntesis) y §12.4 («los brazos que lo atraviesan con profundidad estimada…»).

Qué hace cada celda según el código:

- `fsm:blind` no usa profundidad en ninguna decisión. `fsm_node` retorna antes del `_strategic_tick`, y con `blind` no hay barrido.
- `reactive` no evade: `reactive_node` solo sigue el guiado, sin evasión ni resolución de atascos.

Qué dicen los datos:

- `fsm:blind` completa 9/10 en el lote 3 y 9/10 en el lote 4. En el lote 4 es la mejor celda.
- El barrido con profundidad no mejora a la FSM: (ii) da δ = −0.49 en el lote 3 y −0.40 en el lote 4, ambos en contra de la profundidad.

Lectura que sostienen los datos: frente a `reactive`, la diferencia la hace tener una evasión por flujo óptico y algún escape de atascos, aunque sea ciego. La profundidad no explica esa diferencia.

Corregir también:

- §12.2: «Los brazos con evasión y barrido completan entre 5 y 9 de cada 10». `fsm:blind` no tiene barrido.
- §12.3: «Componentes del lazo rápido… comunes a los tres brazos». No lo son. `reactive` no tiene evasión, `GIRAR_90` ni reacción a contacto. La FSM tampoco tiene `GIRAR_90` ni las reglas 4–6. Lo común a los tres es el gobernador, el tracker con su detección de techo y el motor.

### A2. H3 se evaluó con un criterio distinto del preregistrado

- §10.8.3 fija el criterio antes de ver los datos: H3 se sostiene si el efecto `slm`−`fsm` cambia de signo entre los controles y los lotes con obstrucción.
- §11.7 admite que «frente a la FSM no hay cambio de signo». Con el criterio declarado, H3 no se sostiene.
- El informe la da por «sostenida frente a `reactive`». Es un cambio de comparador hecho después de ver los datos, y contra un brazo que no tiene evasión. Por A1, ese cambio de signo mide la evasión, no la deliberación.
- Esto choca con la regla que el mismo cap. 10 fija en §10.7.4: lo sugerido por los datos se reporta como exploratorio.

Propuesta: «H3 no se sostiene con el criterio preregistrado; exploratoriamente, frente a `reactive` el signo cambia, atribuible a la evasión».

### A3. El mecanismo que postula H2 queda refutado, aunque su condición de falsación se cumpla

- §10.1 postula un costo aditivo de la forma N_inv × ℓ̄, es decir, causado por la inferencia.
- El cap. 11 muestra que la inferencia no bloquea y que el costo lo ponen las sub-metas y el gobernador.
- La capa consulta en forma periódica (cada 1 s), así que N_inv crece con la duración de la misión: 90, 151 y 235 consultas. Con la fórmula de H2, el costo escalaría con la ruta.
- Que la razón decrezca en tres escenarios que difieren en altitud, geometría y tasa de sub-metas (27 %, 37 % y 8 %) no aísla un término aditivo.
- Las tres rutas no difieren solo en longitud: `townsim_clear` vuela sobre los techos y casi no recibe sub-metas. La forma aditiva del costo queda confundida con el escenario.

Propuesta: «La predicción de H2 (razón decreciente) se cumple, pero el mecanismo postulado (latencia × consultas) no».

### A4. La tesis central (§1.4, §9.1, §12.1 y el resumen) contradice el resultado decisivo

- La tesis afirma que «el fallo más severo no radica en la capacidad del modelo, sino en el contrato de datos».
- El resultado que define la arquitectura final dice lo contrario: el VLM no discrimina (AUC 0.53, respuestas constantes) y por eso sale del lazo. El propio §9.9 lo registra como «Riesgo D materializado».
- El resumen dice «demostrando… predominantemente». El cap. 9 es una colección de casos sin conteo de frecuencia ni de costo, así que no demuestra «predominantemente».
- §9.1 dice que la salida del modelo «es un comando que se ejecuta directamente». En la arquitectura vigente el modelo no comanda nada.

Reformulación que sí se sostiene: las fallas de interfaz fueron las más caras de diagnosticar, y además ocultaron que el modelo no discriminaba. Solo el banco contra etiquetas de referencia lo reveló.

### A5. Objetivo 3 y el nombre del brazo `slm`

- El objetivo 3 y el resumen prometen evaluar «un SLM como capa de decisión táctica frente a FSM y reactivo».
- En los lotes no hay ningún SLM en vuelo. El objetivo 3 lo responde el banco (§11.0), con resultado negativo, no la corrida v4.
- §10.2.1 lo aclara, pero el título del cap. 11 («SLM vs. FSM»), el resumen («brazo SLM») y §12.2 leen como si el SLM decidiera.

Propuesta: decir explícitamente «el objetivo 3 se responde en §11.0: no». Además, rebautizar la celda en el texto (por ejemplo «estratégico») o recordarlo en cada tabla.

### A6. El plan de ruta del VLM también modificó los lotes 3 y 4, no solo el 6

Según `route_plan` en `summary.json` y `plan.json`:

| Lote | Escenario | Puntos de paso | Tramos desviados |
|---|---|---|---|
| 3 | `townsim_ini` | 6 | 3 (`WP_0b` izq 25, `WP_3` izq 50, `WP_4` der 25) |
| 4 | `townsim_calib_cruce_frontal` | 4 | 2 (`WP_1` der 25, `WP_3` izq 25) |
| 6 | `citysim_pilot` | 7 | 4 (de esos, la recta estaba bloqueada solo en `WP_2`→`WP_3`) |

Consecuencias:

- **SPL.** La nota de §11.1, que dice que el SPL queda por debajo de 1 por los puntos de paso, vale también para los lotes 3 y 4.
- **Lote 4.** El tramo del cruce frontal (`WP_3`) se voló desviado por el VLM, y `reactive` queda trabado justo en `VIA_WP_3_2`, un punto de paso del plan. No se analiza si el desvío empeoró el escenario.
- **Lote 3.** El «retorno a cielo abierto», donde `slm` gana 20 s contra 56–63 s, son tramos desviados.
- **Cap. 12.** La limitación «Plan de ruta común en `citysim_pilot`» y la frase «su único aporte medible está en el plan» deberían cubrir los tres lotes. El efecto del plan en los lotes 3 y 4 no se midió.

### A7. «Sin colisiones» no es una métrica de seguridad confiable, y el informe no dice por qué

- La seguridad se mide con `has_collided` de AirSim (`runner.py:426`).
- El CHANGELOG documenta, en varias entradas, que esa bandera no se dispara en contacto con follaje ni con la cámara dentro de la geometría (líneas ~730, 1660, 3836, 4230).
- Las 21 fallas `physics_locked` son drones «incrustados en la malla», con DistMin de 0.10 m, y aun así registran 0 colisiones.
- §10.6.1, §11.2 y §12.3 deberían declarar que el detector de colisión no ve esos contactos. La afirmación «sin colisión física» de §11.1 no está verificada. Es probable que `physics_locked` sea, en buena parte, colisión no detectada.

## B. Inconsistencias con el código o los datos

| # | Dónde | Dice | Lo verificado |
|---|---|---|---|
| B1 | §10.2.1, tabla §10.2.3 | `reactive` = «guiado con flujo óptico y TTC» | Solo usa el TTC para limitar la guiñada (`safe_yaw_rate`); no evade |
| B2 | §10.3.4, §10.8.1, §11.3, §12.2 | `townsim_clear` ~640 m; §10.3.2 dice 656 m; DESCARTE.md, 578 m | Manifiesto: 598 m en 3D desde el spawn, 578 m en planta, ℓ_opt = 588 m. La «ruta ×3.5» es ×3.3 (como dice §10.6.1) |
| B3 | Tabla §10.3.4 «Long. óptima» | 180 / 420 / 336 m | ℓ_opt de `analyze.py`: 120 / 345 / 339 m. La columna mezcla definiciones |
| B4 | §7.2 | «3735 registros de 9 celdas cada uno» | 3735 registros de celda, es decir, 415 fotogramas × 9 |
| B5 | §7.2 | «tres escenarios» | `yaw_only` aporta 0 positivos: el AUC sale solo de `approach` y `canyon` |
| B6 | §7.3, resumen | AUC 0.96–0.97 | Por escenario: `canyon` 0.97–0.98, `approach` (frontal) 0.93 / 0.90 / 0.85 para τ = 1 / 2 / 3. El caso frontal, el más crítico, rinde menos que lo que dice el resumen. Además, el vuelo usa 640 px y el dataset se tomó a 320 px (lo dice §7.2, no el resumen) |
| B7 | §7.3 | La correlación es baja pero «el ordenamiento es correcto» | Para sostenerlo hace falta Spearman: ρ = 0.57 (0.53 con conf > 0.15). La explicación del r de Pearson es confusa: r ≈ 0 se debe a las colas de TTC_gt (hasta ~570 s en hover) |
| B8 | §7.7 | «falsos negativos (11 %)» | Con sensibilidad 0.93, los falsos negativos son 7 %. El 11 % es 1 − especificidad, es decir, falsos positivos |
| B9 | §7.2 | «queda aún pendiente (§7.5)» | La sección correcta es §7.6 |
| B10 | Objetivo 3, resumen | Métrica «tiempo de reacción» | No se define en el cap. 10 ni se informa en el cap. 11 (solo período del lazo y latencias) |
| B11 | §12.4, viñeta Anexo 4 | Gramáticas `["evasive", "girar_90"]`, `["girar_90", "fsm", "degraded"]` | Son nombres de ruta del grafo, no macro-acciones, y el modelo ya no elige acciones. Desactualizado |
| B12 | §12.4, viñeta LoRA | «latencia local ~0.8 s (§8.6)» | El banco da 0.34–0.88 s por pregunta. Conviene citar el rango |

## C. Trazabilidad

- Varias cifras de §11.3–§11.5 no salen de ningún artefacto guardado en `produccion/v4`: el % de sub-metas, el gobernador activo 27–43 %, la velocidad media, las consultas por misión, la tasa de resolución del barrido, los 281 escapes por techo y los deadlocks falsos al despegar. `analyze_lotes.py` solo escribe éxito, SPL, tiempo y DistMin. Conviene versionar el script (o el notebook) que las produce y guardar su salida junto a `analisis_lotes.md`.
- `summary_by_wp.csv` (§11.4) existe por corrida (`<stem>.summary_by_wp.csv`). No hay un agregado guardado.
- Memoria de proyecto frente a §11.5: la memoria anotó «lote 4 fsm:depth 0/10» con deadlock falso al despegar; el informe dice 1. Verificar.

## D. Código: comentarios desactualizados (no afectan al vuelo)

- `vlm_strategic.py:3`: el encabezado todavía habla de «qwen2.5-vl-3b remoto, ~3–6 s».
- `obstacle_field.py`:
  - `merge_depth_estimate` dice «se llama desde perception_node (V4)». Solo lo llama `legacy/graph_v1.py`: es código muerto.
  - `summary_text` dice «única fuente… para el prompt del SLM». Hoy solo sirve para logging.
- `flow_ttc.py:289`: el comentario «factor 0.450 da AUC 0.767 a 10 m» no coincide con la calibración D2 del informe (AUC 0.87, 5 m). Aclarar a qué experimento corresponde.
- `fsm.py`: las esquinas de la FSM se inyectan con la etiqueta por defecto `VLM_SUBGOAL` (`runner.py`). Un análisis que cuente sub-metas por etiqueta podría atribuírselas al VLM.

## E. Comprensibilidad

- El cap. 9 contradice la regla «el informe describe solo la versión actual». Narra configuraciones previas (historial de fotogramas, prompts con ejemplo, interfaz por ángulos) y usa datos de corridas de diagnóstico, no de v4. Como es el objetivo 4, conviene presentarlo explícitamente como «casos de diagnóstico durante el desarrollo», separado de la arquitectura vigente.
- El brazo `slm` sin SLM, la «capa deliberativa» que es una red de profundidad y el «VLM» con la sigla SLM del título hacen que el lector deba recordar tres equivalencias. Una tabla de nombres al comienzo del cap. 10 y del cap. 11 ayudaría.
- La síntesis «en ruta libre la capa deliberativa solo cuesta» atribuye a la capa estratégica un costo que incluye la evasión del lazo rápido y las rampas del gobernador. No hay una celda `slm` con `STRATEGIC_SOURCE=off` que lo aísle. Decir «el brazo `slm`», no «la capa».
