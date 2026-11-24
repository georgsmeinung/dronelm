# 12. Conclusiones

## 12.1 Retomar el hilo conductor

Este trabajo partió de una constatación práctica: en un sistema de control donde un modelo de lenguaje visual juzga la escena, las fallas más caras de diagnosticar no estuvieron en las respuestas del modelo sino en la interfaz que lo alimenta y que ejecuta lo que responde, y ninguna emergió observando el vuelo: emergieron auditando los contratos de datos entre capas (cap. 9). Tuvieron además una consecuencia más importante: mientras la interfaz distorsionaba las respuestas, no se podía saber si el modelo discriminaba. Una vez corregida, el banco de prueba contra etiquetas de referencia mostró que no lo hace (AUC 0.53). El límite final resultó ser la capacidad del modelo; la interfaz fue lo que impidió verlo antes.

El banco de prueba a bordo (cap. 11, IT.11.0) fijó la configuración que vuela —la capa estratégica y el barrido responden con profundidad estimada, y el VLM queda en el plan de ruta previo al despegue—, y la corrida v4 la evaluó en seis escenarios y 210 corridas. En ella ningún modelo de lenguaje decide en vuelo: el brazo `depth2loop` —`slm` en el código y en los datos— es la arquitectura de dos lazos con la capa estratégica respondida por la red de profundidad.

**Alcance de la evidencia.** La comparación entre brazos tiene un sesgo conocido: el brazo FSM tiene dos defectos de implementación —un deadlock falso al terminar el despegue y un techo de altitud que convierte sus escapes verticales en giros por encima de 30 m— que lo hacen más lento y lo exponen a más fallas (cap. 11, IT.11.5). Las conclusiones frente a `reactive` no están afectadas; las conclusiones frente a la FSM favorecen a `depth2loop` en una medida que estos datos no permiten estimar.

---

## 12.2 Respuesta a la pregunta de investigación

**¿Aporta el brazo deliberativo (`depth2loop`) sobre la máquina de estados (`fsm`) y sobre el control puramente reactivo (`reactive`) en navegación autónoma de dron en entornos urbanos simulados?**

La pregunta tiene dos partes. Si un modelo de visión-lenguaje pequeño sirve como capa de decisión a bordo (objetivo 3a) lo responde el banco de prueba, y la respuesta es no. Si una arquitectura con capa deliberativa —con la profundidad estimada como fuente— aporta frente a una FSM y al control reactivo lo responde la corrida v4 (objetivo 3b), y la respuesta depende del escenario y del brazo de comparación.

### En ruta libre: solo costo (predicción de H2 cumplida)

En los tres escenarios de control `depth2loop` completa 29 de 30 misiones y `reactive` las 30 (la FSM, 25), sin colisiones registradas y con la misma distancia a las estructuras. La bandera de colisión de AirSim no ve el follaje ni los apoyos: las 6 corridas de los controles que terminan por `physics_locked` son contactos que no registra; en los seis lotes son 21, y en los lotes con obstrucción la distancia mínima cae a ~0.1 m (IT.12.3). `depth2loop` no gana seguridad ni éxito; cuesta tiempo. Las nueve comparaciones de tiempo son significativas tras Bonferroni, y el orden es el mismo en los tres tiers: `reactive` < `depth2loop` < `fsm`.

| Escenario | Ruta | $t_{\text{depth2loop}}/t_{\text{reactive}}$ | $t_{\text{depth2loop}} - t_{\text{reactive}}$ |
|---|---|---|---|
| `minisim_clear` (Tier 0) | ~180 m | 1.95 | 80 s |
| `citysim_clear` (Tier 2) | ~420 m | 1.49 | 94 s |
| `townsim_clear` (Tier 1) | ~600 m | 1.39 | 107 s |

La razón decrece con la longitud de la ruta: el costo se comporta como un término aproximadamente aditivo, lo que predice H2, aunque con un solo escenario por tier la forma es descriptiva. El mecanismo que H2 postulaba no se confirma: el costo no lo pone la inferencia, que corre en su propio hilo, sino las sub-metas en ruta libre y el gobernador de velocidad (cap. 11, IT.11.3). Reducirlo es un problema de cuándo desviar y cuándo frenar, no de acelerar el modelo.

### Con obstrucción: la evasión y la salida de bloqueos deciden; la capa estratégica, sin demostrar

**Frente al control reactivo, la diferencia es binaria.** En el corredor arbolado de `townsim_ini` y en el bloqueo frontal de `townsim_calib_cruce_frontal`, `reactive` no completa ninguna de sus 20 corridas, y las otras tres celdas completan entre 5 y 9 de cada 10. Es el resultado más firme del trabajo, pero no es un efecto de la deliberación ni de la profundidad: `fsm:blind`, que evade y tiene una salida de bloqueos pero no usa la profundidad ni tiene capa estratégica, completa 9 de 10 en los dos lotes. Lo que separa a `reactive` del resto es la evasión por flujo óptico y alguna forma de salir de un bloqueo, aunque sea un escape vertical ciego.

**H3 no se sostiene con el criterio declarado.** El diseño fijó de antemano que H3 se sostiene si el efecto `depth2loop` − `fsm` cambia de signo entre los controles y los escenarios con obstrucción (cap. 10, IT.10.7.4), y no cambia: `depth2loop` gana o empata frente a la FSM en los seis lotes. El cambio de signo frente a `reactive` es exploratorio y mide la evasión, no la deliberación.

**Frente a la FSM, la ventaja de `depth2loop` existe pero no se puede atribuir.** `depth2loop` supera en SPL a `fsm:depth` en `townsim_ini` (δ = +0.81) y a las dos FSM en `citysim_pilot` (δ = +1.00), las tres comparaciones significativas tras Bonferroni; en el bloqueo frontal no hay diferencia y `depth2loop` pierde la mitad de sus corridas. Tres razones impiden leer esas ventajas como un aporte de la capa estratégica: los defectos de la FSM la hacen más lenta en toda la ruta, y en `townsim_ini` la ventaja está repartida a lo largo del recorrido; el plan de ruta en `citysim_pilot` resuelve el bloqueo antes del vuelo, al punto de que hasta `reactive` completa las 10 corridas; y el bloqueo frontal, donde se esperaba el beneficio más claro, es justamente donde `depth2loop` no muestra ventaja. La capa estratégica sí discrimina —declara libre el camino directo en dos tercios a tres cuartos de las consultas y propone sub-metas en el resto—, pero a los 20 s esas sub-metas acercan al waypoint tanto como el camino directo, y más solo en el corredor arbolado; en el bloqueo frontal, menos (cap. 11, IT.11.4). La capa no estorba, pero su aporte no se distingue del de volar directo.

### El VLM

Medido contra etiquetas de referencia, el VLM de 1.6 B no separa sectores volables de bloqueados (AUC 0.53) ni rumbos abiertos de cerrados; una red de profundidad monocular de ~25 M de parámetros sí lo hace (AUC 0.83–0.87), en ~110 ms (cap. 11, IT.11.0). Por eso el VLM no vuela, y esa es la respuesta al objetivo 3a: un modelo de visión-lenguaje de 1.6 B, a bordo y *zero-shot*, no sirve como capa de decisión táctica. Su único aporte medible está fuera del lazo: el plan de ruta sobre el mapa cenital (AUC 0.81), una pregunta de reconocimiento y no de distancia, que en `citysim_pilot` basta para que el control reactivo complete la misión.

### Síntesis

**En ruta libre el brazo `depth2loop` solo cuesta**: entre 1.4 y 2 veces el tiempo del control reactivo, sin ganar éxito ni seguridad. **Donde la ruta directa se tranca, evadir con el flujo óptico y tener una salida de los bloqueos es lo que permite completar la misión**; la profundidad estimada no es necesaria para eso. **La ventaja de la capa estratégica sobre una máquina de estados no está demostrada**: las diferencias a favor de `depth2loop` existen, pero los defectos de la FSM evaluada las inflan, y H3 no se sostiene con el criterio declarado. **Un VLM pequeño no aporta en el lazo de vuelo; aporta como planificador de ruta sobre un mapa registrado.** Y, transversal a todo lo anterior, el hilo conductor: en un lazo híbrido, auditar los contratos de datos es condición para poder medir el modelo.

---

## 12.3 Limitaciones

- **Defectos del brazo FSM** (cap. 11, IT.11.5): afectan todas las comparaciones `depth2loop`–`fsm`, que son por eso cotas favorables a `depth2loop`.
- **Plan de ruta común en los escenarios con obstrucción:** desvía entre 2 y 4 tramos por escenario, igual para las cuatro celdas; en `citysim_pilot` rodea el único tramo bloqueado antes del vuelo, de modo que el lote más difícil no ejerce la resolución en vuelo, y en los otros dos su efecto no se midió.
- **Un escenario por tipo y tamaño de muestra:** cada nivel de dificultad tiene una ruta concreta, y con K = 10 una separación parcial no supera Bonferroni: `depth2loop`–`fsm:blind` en `townsim_ini` (δ = +0.73, p = 0.0039) es un efecto grande no detectado con esta potencia, no un efecto ausente.
- **Réplicas, no muestras independientes:** las 10 semillas de una celda son réplicas de la misma sesión de simulador y de la misma pose de partida; su variación viene de la estocasticidad del sistema (cap. 10, IT.10.5.1). Los intervalos y los *p*-valores miden la variabilidad entre réplicas de esa sesión, no entre sesiones, poses ni rutas.
- **Tiempos condicionados al éxito:** en los controles la métrica primaria es el tiempo de las misiones exitosas, de modo que las celdas se comparan sobre subconjuntos distintos de semillas —en el lote 5, 9 corridas de `depth2loop` frente a 6 de la FSM—, y el tiempo no penaliza las fallas, que solo registra la tasa de éxito.
- **AUC del plan de ruta sobre muestras dependientes:** el 0.81 sale de 59 candidatas en 11 tramos (cap. 11, IT.11.0); las candidatas de un mismo tramo comparten mapa y extremos, de modo que la muestra efectiva se acerca más a 11 que a 59 y el valor no tiene un intervalo confiable.
- **Contribución de la capa estratégica no atribuible:** el avance tras cada sub-meta se midió a 20 s (cap. 11, IT.11.4), pero ninguna celda vuela `depth2loop` sin la capa y las sub-metas aparecen justo donde el camino directo no está libre; el lote piloto de fuentes tampoco mostró ventaja frente a volar sin ella (IT.10.2). Sus umbrales son decisiones de diseño, no valores calibrados.
- **Componentes del lazo rápido sin aislar:** la reacción a contacto, el giro ante un frente bloqueado y el descenso bajo un techo los tiene solo `depth2loop`, y ninguna celda los aísla, de modo que las diferencias entre brazos mezclan la capa estratégica con esas reglas y con el gobernador de velocidad.
- **Seguridad sin un detector de contacto confiable:** la bandera de colisión de AirSim no ve el follaje ni el dron apoyado sobre una cornisa (cap. 10, IT.10.6.1); la distancia mínima cae a ~0.1–0.25 m con vegetación y fachadas, y las 21 terminaciones `physics_locked` son contactos no registrados. «Cero colisiones» no es evidencia de vuelo seguro: la seguridad de este trabajo no está medida.
- **Percepción:** el flujo óptico es ciego a obstáculos centrados en el foco de expansión y a superficies horizontales a la altura de vuelo (Anexo 11, IT.A11.4.3); la implementación evaluada tiene invertida la prueba de inliers del FOE (cap. 6, IT.6.6) y usa a 640 px umbrales calibrados con el flujo a 320 px; en vuelo el campo distingue obstáculos cercanos poco más que al azar, y la evasión la disparan sobre todo la ocupación y el contacto (cap. 7, IT.7.7). La ocupación está calibrada con una sola escena (cap. 7, IT.7.5), y la profundidad estimada se evaluó sobre el mismo render del que salen sus etiquetas, sin calibrar su escala a la altura de vuelo (cap. 6, IT.6.12.4).
- **Modelo y entorno fijos:** las conclusiones sobre el VLM son sobre LFM2.5-VL-1.6B *zero-shot* en el render de CitySim; las de la arquitectura, sobre dos mapas urbanos y en simulación, con una dinámica de vuelo más ágil que la real y no reajustada a ella (cap. 3, IT.3.4), sin validación en hardware físico, que el plan de trabajo aprobado sitúa como etapa siguiente.

---

## 12.4 Trabajo futuro

- **Validación del sistema**, la continuación más directa porque condiciona la comparación con la FSM: corregir los dos defectos de la FSM y repetir las comparaciones; agregar celdas que aíslen el gobernador de velocidad, la capa estratégica (`depth2loop` sin capa) y las reglas de contacto y giro del brazo `depth2loop`; correr los escenarios con obstrucción con y sin plan de ruta; medir el contacto con un detector que vea el follaje; e incorporar un test de contrato que falle ante cualquier clave de estado no declarada. El resto del plan extendido de pruebas —curva de degradación por ancho de corredor, barrido de velocidad, repetición entre sesiones, banco en TownSim y con otros modelos— está en el Anexo 12 (IT.A12.11).
- **Percepción monocular:** corregir la prueba de inliers del FOE y recalibrar el TTC y la ocupación en las escenas de los lotes, con la auditoría de distancia mínima como etiqueta; validar la derotación entre 0 y 0.3 rad/s y con IMU real; y, para los obstáculos centrados en la trayectoria, un par estéreo que recupere profundidad métrica sin depender del movimiento ([Anexo 7](anexos/A7-MALDICION-MONOCULAR-ESTEREO.md)).
- **El modelo de lenguaje:** un ajuste fino ligero vía LoRA (Anexo 16, IT.A16.8; [Anexo 3](anexos/A3-OPTIMIZACION-LORA.md)) apuntaría a que el modelo distinga sectores libres de bloqueados, con un conjunto de entrenamiento natural: las más de 7500 consultas de la capa estratégica de la v4, etiquetadas fuera de línea con la profundidad del simulador.
- **Otros brazos de decisión:** una política entrenada por aprendizaje por refuerzo como cuarto brazo ([Anexo 8](anexos/A8-NAVEGACION-RL.md)) y los modelos de mundo latentes como LeWorldModel ([Maes et al., 2026](13-REFERENCIAS.md#ref-maes-2026); [Anexo 9](anexos/A9-MODELOS-DE-MUNDO-LATENTES-EDGE.md)), como verificador de consecuencias o simulador latente; ambos requieren antes una comparación entre brazos limpia.
- **Transferencia a hardware:** integración en una *companion computer* de bajo consumo (Jetson Nano / Orin) conectada a un cuadrirrotor real con cámara monocular, según las fases del plan de trabajo aprobado, y extensión a navegación cooperativa en enjambre.
