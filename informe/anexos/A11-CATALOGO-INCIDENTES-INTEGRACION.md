# Anexo 11: Catálogo de incidentes de integración

El capítulo 9 presenta seis familias de fallas estructurales en la integración de percepción, grafo de control y modelo de lenguaje, con los casos necesarios para sostener su argumento central: las fallas más costosas estuvieron en los contratos de interfaz, no en las respuestas del modelo, y ninguna produjo una excepción. Este anexo reúne el resto de la evidencia: el detalle de las vulnerabilidades de estado y precedencia del grafo (Falla 4), las degradaciones sensoriales (Falla 5) y los incidentes de corridas de diagnóstico y piloto que el capítulo 9 resume en una tabla (Falla 6). Como en el capítulo, los casos provienen de corridas con configuraciones anteriores a la evaluada en el capítulo 11, y se documentan como casos, sin una medición de su frecuencia.

---

## A11.1 Falla 4 en detalle: vulnerabilidades de estado y ciclos límite en LangGraph

### A11.1.1 Cuatro vulnerabilidades

**Vulnerabilidad A — Claves de control no declaradas.**

En corridas de diagnóstico, tres claves de control cruzaban la frontera entre nodo y lazo sin estar declaradas en `DroneState`:

- `_reset_stall_counter`: debía reiniciar el contador de progreso estancado al llegar a un waypoint. No declarada, el contador crece monótonamente desde el inicio de la misión, independientemente del progreso real.
- `_delib_memory`: debía acumular un historial corto de resultados de la consulta al VLM. No declarada, el historial está siempre vacío y el VLM se consulta sin contexto de lo que decidió un ciclo antes.
- `_corner_wp`: debía inyectar un sub-waypoint de esquina para la maniobra `GIRAR_90`. No declarada, el decisor la lee en el ciclo siguiente como el valor inicial (`None`), nunca como el punto calculado.

Ningún log de nivel de aplicación muestra el descarte; diagnosticarlo exige comparar el estado completo antes y después de cada invocación. El mecanismo específico importa: el `TypedDict` de Python es una anotación de tipos, no una estructura de datos con validación en tiempo de ejecución. `state["clave_nueva"] = valor` no falla aunque `clave_nueva` no esté en el `TypedDict`; simplemente el runtime de LangGraph no la persiste en el canal de estado entre invocaciones (cap. 5, IT.5.2).

**Vulnerabilidad B — Ciclo límite de período 3 en la red de seguridad.**

Un mecanismo de escape que se resetea a sí mismo,

```
si stall_count > hard_threshold:
    activar FRENAR (ciclo 1)
    si stall_count > hard_threshold + N:
        resetear stall_count = 0  ← la red de seguridad se resetea a sí misma
```

convierte el estado "atasco severo → acción de escape" en un estado transitorio: al ciclo siguiente, `stall_count = 0 < hard_threshold` y el sistema vuelve a crucero; tres ciclos después, el atasco se re-detecta y el ciclo se repite. El período 3 (crucero → pre-stall → escape → reseteo → crucero) no es observable como un error: en el visor se ve como "el dron frena ocasionalmente sin razón aparente".

**Vulnerabilidad C — Métrica de progreso auto-inconsistente.**

Un predicado de atasco `ciclos_sin_progreso > effective_stall_threshold`, con `effective_stall_threshold = max(10, eps_m / (min_speed / loop_hz))`, combina `eps_m` (distancia mínima de avance por ciclo) y `min_speed` (velocidad mínima de crucero), definidos en unidades y archivos distintos. Con `eps_m = 0.5 m`, `min_speed = 2.0 m/s` y `loop_hz = 5 Hz`, la velocidad de avance implícita es 2.5 m/s, mientras que en un giro de 90° la velocidad de aproximación al waypoint oscila entre 0 y `vx · cos(θ)`, con media ≈ 1.25 m/s. El resultado es un detector de atasco que se dispara prácticamente al inicio de cada waypoint que requiera maniobra.

**Vulnerabilidad D — Escape ciego a la percepción.**

Si el decisor evalúa las condiciones de escape de atasco *antes* de leer el `ObstacleField`,

```python
if state["stall_count"] > hard_threshold:
    return "deadlock_escape"   # ← sin verificar percepción
if field.is_blocked("centro"):
    return "evasive"
```

el dron asciende aunque el estimador de flujo tenga evidencia válida de un sector lateral despejado.

### A11.1.2 El ascenso acumulado como síntoma compuesto

La combinación de las cuatro vulnerabilidades produjo, en una corrida de diagnóstico, un ascenso acumulado de ~356 m en una sola misión:

1. `_reset_stall_counter` no declarada → `stall_count` creció desde el ciclo 1 sin resetearse al llegar a cada waypoint.
2. A los ~8 ciclos de misión, `stall_count > hard_threshold` a pesar de que el dron avanzaba normalmente.
3. El decisor activó el escape (ciego a la percepción), que ejecutaba `GANAR_ALTURA` con deriva lateral.
4. `stall_count` se reseteó (ciclo límite B) → al ciclo siguiente, el decisor volvió a crucero.
5. `stall_count` volvió a crecer rápidamente (umbral demasiado bajo por la métrica inconsistente C).
6. El ciclo se repitió centenares de veces, con un ascenso neto acumulado.

Desde el exterior, la corrida registraba una misión "sin errores" (no hay excepciones en el log) que simplemente "no llegó a destino". Sin el análisis del visor cuadro a cuadro y la lectura del JSONL de auditoría, el patrón es opaco.

---

## A11.2 Falla 4: instancias adicionales de estado descartado y precedencia entre rutas

Otras tres situaciones comparten la propiedad que organiza el capítulo 9: el sistema produce respuestas válidas y plausibles, sin excepciones en el log, y aun así no las ejecuta.

**(a) Un flag descartado por LangGraph.** Un indicador que difería la inyección de un desvío hasta el escaneo siguiente se escribía correctamente pero no estaba declarado en `DroneState`; desaparecía entre invocaciones y el desvío nunca se inyectaba, de modo que el dron volvía a la misma fachada. Es otra instancia de la Vulnerabilidad A.

**(b) Resultados válidos del VLM que nunca se ejecutan.** Dos errores de *precedencia* entre rutas, no de estado descartado, con el mismo síntoma:

- *Maniobra cancelada por un disparador de atasco.* Si al despachar `EVADIR_DERECHA` no se reinicia el contador de atasco, en el ciclo siguiente un disparador basado en ese contador vuelve a enrutar hacia una nueva consulta, cuyo resultado sobrescribe la maniobra comprometida antes de que se ejecute. En una corrida de diagnóstico, el VLM devolvió `EVADIR_DERECHA` durante 200 ciclos consecutivos sin que la maniobra se ejecutara una sola vez.
- *Resultado huérfano por el camino de deadlock.* Si la rama de escape por deadlock se evalúa antes que la lectura del pedido pendiente, y el contador de progreso queda congelado por encima del umbral, la rama intercepta todos los ciclos y el resultado nunca se lee: durante 80 ciclos, el log del VLM contenía la respuesta correcta y la acción ejecutada era `MANTENER_RUMBO` o `FRENAR`.

Ninguno de los dos se ve en las métricas agregadas; los muestra la comparación, ciclo a ciclo, del campo `slm.raw_response` de la traza JSONL con la acción realmente ejecutada (técnica 2 de IT.9.7).

**(c) Un pedido pendiente que nunca se cierra.** Si la consulta estratégica y el barrido comparten la cola del servicio (tamaño 1), un barrido que se encola mientras hay una consulta estratégica en vuelo la invalida. Si el sistema solo cerrara el pedido al llegar un resultado con *ese* identificador, el pedido quedaría activo indefinidamente, y un detector de atasco que interpretara la espera como intencional detendría sus contadores.

**Contención, en detalle.**

- **Estado declarado y verificado sobre el grafo compilado.** Todo campo que cruza la frontera entre invocaciones está declarado en `DroneState`, los contadores de atasco y el estado de la capa estratégica viven en objetos de proceso (`StallDetector`, `StrategicLayer`) y no en el estado, y los tests de integración corren el **grafo compilado** y verifican que las claves de control (`inject_corner`, `_escape_reset`, `_deadlock_event`, `_vlm_strategic`) cruzan la frontera (cap. 5, IT.5.2; `tests/test_graph_integration.py`, `tests/test_vlm_strategic_graph.py`).
- **Escape absorbente.** Un barrido en curso es dueño del dron hasta resolver o caer por sus watchdogs, y el deadlock se reinicia solo cuando se resuelve (`_escape_reset`), nunca dentro de su propia rama (cap. 5, IT.5.3.2, IT.5.3.4).
- **Progreso físicamente alcanzable.** El progreso se mide como distancia horizontal al objetivo, y los umbrales de atasco se derivan del avance mínimo demostrable a la velocidad mínima (cap. 5, IT.5.3.1, IT.A10.8.2).
- **Precedencia explícita.** El orden de las reglas de `navigate` es fijo y está justificado (cap. 5, IT.5.3.2): barrido en curso, deadlock, maniobra comprometida, contacto, piso óptico y TTC. El resultado de cada consulta se recupera por su identificador (`get_result`) al inicio de cada ciclo, de modo que no depende de qué ruta tome el ciclo. En la FSM, el escape exige además que la percepción no muestre un corredor libre (`has_open_corridor()`, cap. 6, IT.6.10).
- **Pedidos perdidos.** La capa estratégica da por perdido un pedido reemplazado si el servicio no tiene resultado ni pedido pendiente durante 3 s, o al cumplir 10 s, y el deadlock cancela explícitamente la consulta estratégica en vuelo (cap. 5, IT.5.5.3, IT.5.3.4).

---

## A11.3 Falla 5 en detalle: degradaciones sensoriales silenciosas

### A11.3.1 Inversión de canales de color RGB/BGR

`simGetImages` entrega el buffer de imagen en el orden RGB del motor, mientras que OpenCV y el resto del pipeline asumen la convención BGR, en la que el canal azul ocupa el índice 0. Sin conversión, cada píxel tiene los canales rojo y azul invertidos: fachadas de ladrillo rojo en tonos azulados, cielo amarillento, vegetación de colores no naturales. Un VLM entrenado sobre datos fotométricamente correctos delibera sobre esas imágenes sin emitir ninguna queja sobre su calidad ni reducir su confianza: no tiene cómo detectar que la imagen recibida está fuera de distribución por inversión de canal.

Detectarlo exige guardar en disco las imágenes exactas enviadas al VLM y abrirlas en un visor externo — el análogo de "mirar los datos crudos", primer paso de depuración en visión por computadora pero fácil de omitir en un sistema integrado cuando el modelo "parece razonar correctamente".

**Mecanismo de contención.** `AirSimClient.capture()` invierte el orden de canales en el punto de captura (cap. 3, IT.3.3), y cada consulta del lazo lento guarda sus fotogramas exactos como `photo-*.png` de auditoría (cap. 4, IT.4.4).

### A11.3.2 Contaminación por primitivas de depuración persistentes

El simulador AirSim/cosysairsim permite dibujar primitivas geométricas en el mundo virtual (`simPlotLineStrip`, `simPlotPoints`, `simPlotArrows`) para visualización durante el desarrollo: trayectorias planificadas, sectores del `ObstacleField`, vectores de flujo. Estas primitivas son *persistentes* en la sesión del simulador: no se borran al reiniciar el script de control, solo al llamar explícitamente `simFlushPersistentMarkers()`.

Al relanzar un vuelo sin reiniciar AirSim, las primitivas de la sesión anterior permanecen en el mundo virtual y la cámara a bordo las captura como geometría física: franjas de colores brillantes que el VLM interpreta como cables, estructuras metálicas o señales de tráfico. El comportamiento depende entonces del historial de la sesión: un vuelo iniciado tras reiniciar AirSim se comporta normalmente, y el mismo vuelo sin reiniciar produce evasiones espurias repetidas. [Jansen et al. (2023)](../13-REFERENCIAS.md#ref-jansen-2023) documentan comportamientos similares de estado persistente en CosysAirSim como fuente de irreproducibilidad entre corridas.

**Mecanismo de contención.** Cada sesión de conexión empieza con `AirSimClient.clear_debug_markers()`, que invoca `simFlushPersistentMarkers()` (cap. 3, IT.3.3).

### A11.3.3 Supresión de ángulos de actitud en la telemetría

El binding `cosysairsim` (fork de AirSim con soporte UE5 — Jansen et al., 2023) no implementa el método `to_eularian_angles()` del binding oficial de Microsoft AirSim. Un fallback que no lo note reporta pitch y roll en `0.0°` en cada ciclo, independientemente de la inclinación física del vehículo. Durante maniobras de aceleración (pitch de −8° a −12°), descenso agresivo o giros, el sistema recibe la información de que el dron está perfectamente nivelado: la derotación del flujo óptico pierde dos de sus tres ejes y cualquier consumidor de la actitud queda desalineado con la imagen.

**Mecanismo de contención.** El cliente convierte directamente el cuaternión de orientación, disponible en la telemetría de CosysAirSim, a ángulos de Euler (roll, pitch, yaw) con las fórmulas estándar de [Wahba (1965)](../13-REFERENCIAS.md#ref-wahba-1965), sin depender del método del binding:

$$\phi = \arctan2(2(q_w q_x + q_y q_z),\ 1 - 2(q_x^2 + q_y^2))$$
$$\theta = \arcsin(2(q_w q_y - q_z q_x))$$
$$\psi = \arctan2(2(q_w q_z + q_x q_y),\ 1 - 2(q_y^2 + q_z^2))$$

Un test unitario (`tests/test_airsim_client_telemetry.py`) verifica la conversión contra cuaterniones conocidos.

---

## A11.4 Falla 6: incidentes de integración del VLM y del lazo rápido

Los casos de esta sección provienen de las mismas auditorías que los de IT.9.8 —corridas de diagnóstico y piloto sobre `citysim_pilot`, comparando ciclo a ciclo la respuesta cruda del modelo con la acción ejecutada y con la profundidad de referencia del simulador, consultada a posteriori solo para la auditoría—. El capítulo 9 los resume en una tabla (IT.9.8.5).

### A11.4.1 Deadlock falso en el despegue

En todas las corridas de diagnóstico, el primer deadlock se declaró en los ciclos 17–18, con el dron todavía subiendo a la altitud de crucero. Durante el despegue el guiado ordena subir y girar en el lugar hacia el primer waypoint con `vx = 0`; un contador de «detenido» que suma esos ciclos dispara la resolución de atasco al cruzar el piso óptico de 4.5 m.

**Mecanismo de contención.** «Detenido» se define como «se ordenó avanzar y el dron no se movió», y no se cuenta bajo el piso óptico ni durante el despegue (cap. 5, IT.5.3.1). Aplicada sobre la telemetría registrada, esa definición no declara el deadlock en ninguna de las tres corridas.

### A11.4.2 Una señal de referencia dentro del brazo evaluado

Un runner que captura el canal de profundidad del simulador «solo como métrica» puede terminar alimentando al brazo evaluado: en una configuración de diagnóstico, esa captura armaba un freno de proximidad que el grafo consumía, cancelaba maniobras, inyectaba retrocesos y registraba puntos de contacto que el tracker usaba para validar desvíos. El brazo evaluado tenía así acceso indirecto a la profundidad exacta del simulador, lo que invalida su comparación con un sistema monocular, y una guardia estática limitada a `src/` no lo detecta porque el runner está fuera de su alcance.

**Mecanismo de contención.** Ningún componente del lazo de vuelo lee el canal de profundidad, tampoco como métrica, y la guardia (`test_no_depth_in_flight_path.py`) cubre el runner, `main.py` y todos los módulos de vuelo, incluido el canal indirecto; la distancia mínima a obstáculo la mide un hilo de auditoría aislado (cap. 5, IT.5.8; cap. 10, IT.10.4.1, punto 3).

### A11.4.3 La causa física de los `physics_locked`

En las tres corridas de diagnóstico que terminaron por `physics_locked`, el dron no chocó de frente: quedó apoyado sobre una **superficie horizontal a la altura de crucero** —el tablero de una autopista elevada (dos corridas) y la cornisa de un edificio (una)—, con los sectores frontales del flujo libres (`occ = 0`, TTC infinito). En una corrida, un `GANAR_ALTURA` liberó al dron hasta −12.2 m y el guiado de altitud lo devolvió a −10 m, sobre la cornisa. Ni el flujo óptico ni una descripción por columnas representan ese tipo de obstáculo.

**Mecanismo de contención.** El manifiesto evita la autopista (`WP_0_SUR`, Anexo 12, IT.A12.3.3); la capa estratégica juzga el fotograma en una grilla de 3×3, de modo que un obstáculo a la altura del dron puede rodearse por la fila de arriba; y el escape determinista ante falla de la fuente es `GANAR_ALTURA` (cap. 5, IT.5.3.4, IT.5.5).

### A11.4.4 Señales que se tapan entre sí: un techo inventado y una velocidad que no existe

En una corrida piloto sobre `citysim_pilot`, el dron quedó 220 ciclos apoyado sobre el parapeto de la autopista elevada, pegada al punto de partida, sin que se declarara un solo deadlock. Tres mecanismos, cada uno razonable por separado, se encadenaron:

1. **Avance durante el ascenso.** El guiado avanzaba hacia el primer waypoint mientras subía; a 7.4 m, todavía por debajo del borde del parapeto, el TTC frontal cayó a 0.23 s y el lazo ejecutó `GIRAR_90`.
2. **Un techo inventado.** La detección de techo contaba los ciclos en que el *guiado* pedía subir sin que la cota cambiara. Durante el giro el comando vertical era cero, de modo que diez ciclos de giro se leyeron como diez ciclos empujando contra una losa: techo en z = −7.44. Con ese techo, el waypoint a −10 m quedó «bloqueado verticalmente» y el lazo ordenó `PERDER_ALTURA` en cada ciclo, contra el parapeto.
3. **Una velocidad que no existe.** Con el dron apoyado en la estructura, AirSim reportaba 0.31 m/s horizontales y 0.75 m/s verticales con la posición inmóvil. El contador de «detenido» leía esa velocidad y nunca avanzó; el de «sin progreso» sí llegó a 200 ciclos, pero la regla de descenso por techo se evaluaba antes que la de deadlock y tomaba el ciclo.

Ninguna de las tres produjo un error: cada ciclo tenía una acción válida y una justificación registrada. Es la misma clase de falla que IT.9.5 y IT.9.7 —el sistema «funciona» mientras repite indefinidamente una acción inútil—, en este caso entre señales del lazo rápido y no entre el modelo y el lazo.

**Mecanismo de contención.** El despegue es vertical hasta la altitud del primer objetivo (cap. 5, IT.5.4); la detección de techo usa el comando efectivamente ejecutado, no la demanda del guiado (IT.A10.8.3); el `StallDetector` mide la velocidad por desplazamiento entre ciclos (IT.5.3.1); y el deadlock se evalúa antes que cualquier otra regla salvo el barrido en curso (IT.5.3.2), de modo que ninguna acción que se repita sin mover al dron puede taparlo. Un test reproduce la secuencia sobre el grafo compilado (`tests/test_pilot_seed99_regressions.py`).

### A11.4.5 Sub-metas que ocultan al waypoint real

En otra corrida piloto, el dron llegó a la zona del primer waypoint a los 40 s y pasó el resto de la corrida —más de cuatro minutos— pegado a la fachada vidriada del edificio contiguo. Estuvo **573 ciclos a menos de 3.5 m del waypoint**, el radio de aceptación, sin aceptarlo nunca. Cinco mecanismos se encadenaron:

1. **La sub-meta ocultaba al waypoint.** El tracker solo medía la llegada al objetivo activo. En los 573 ciclos el objetivo activo era una sub-meta del VLM (332 de la capa estratégica, 241 del barrido), de modo que pasar por encima del waypoint no contaba.
2. **Sub-metas más lejos que el waypoint.** La sub-meta se fijaba siempre a 15 m. Con el waypoint a 6 m, una sub-meta a 15 m queda 9 m más allá: en este caso, dentro del edificio. A 1 m del waypoint, el rumbo hacia la meta que usa el barrido es casi ruido, y la sub-meta lo amplifica.
3. **Sin re-planificación.** La capa estratégica solo consultaba con un waypoint real como objetivo. Con una sub-meta mala activa quedaba muda, y el lazo rápido entraba en un ciclo límite: el guiado apuntaba a la sub-meta dentro del edificio, el TTC caía a 0–0.2 s, `GIRAR_90` desviaba un segundo y el guiado volvía a apuntar a la fachada (cinco giros en 55 ciclos, seis en 50). Solo un deadlock, 10 s después, reemplazaba la sub-meta.
4. **Respuestas casi constantes, incluso sobre imágenes del interior del edificio.** La capa estratégica, con una partición en columnas, respondió «la primera columna bloqueada, las demás libres» en 5 de 6 consultas, incluida una con la fachada ocupando casi todo el cuadro, y marcó «estructura debajo» en 5 de 6, lo que subía todas las sub-metas 4 m. En los 8 barridos, las imágenes 2 y 4 salieron libres y la 1 y la 3 bloqueadas, sin importar hacia dónde miraba el dron. Con el dron pegado a la fachada, la cámara quedó dentro de la malla del edificio en dos barridos: el modelo marcó el interior de una oficina como `libre, ok: true` y, como apuntaba hacia el waypoint, el barrido lo eligió.
5. **Un techo inventado por una pared.** Con el dron trabado contra la fachada, el roce impedía subir y la detección de techo declaró una losa a −11.8 m; los escapes `GANAR_ALTURA` subieron después hasta −16 m sin obstáculo, y la regla de techo los devolvía hacia abajo.

Además, el waypoint mismo estaba mal ubicado: sus coordenadas se habían tomado del mapa y caían sobre la fachada, en contra del principio de derivar coordenadas solo de posiciones ya voladas (cap. 10, IT.10.4.1).

**Mecanismo de contención.** El tracker acepta el waypoint real aunque haya una sub-meta activa y descarta los desvíos pendientes (cap. 5, IT.5.5.3); ninguna sub-meta queda más lejos que el waypoint real, y a menos de 8 m del waypoint no se consulta a la capa estratégica ni se barre (IT.5.5.1, IT.5.6); la capa estratégica re-planifica con una sub-meta activa, y si ve libre el camino directo descarta el desvío (IT.5.5.3); el barrido no usa entradas que se contradicen (`free: true` con una vista distinta de `open`), lo que no reemplaza la decisión de la fuente sino que descarta respuestas internamente inconsistentes, igual que una respuesta mal formada (IT.5.6); la capa estratégica juzga una grilla de 3×3 en lugar de columnas, de modo que el eje vertical sale de la descripción y no de una pregunta abstracta (cap. 8, IT.8.3.2); la detección de techo no cuenta los ciclos en que el dron está trabado de costado (IT.A10.8.3); y los waypoints de los manifiestos están en puntos ya volados. Los tests `tests/test_pilot_190842z_regressions.py` reproducen cada mecanismo.

Estas medidas no corrigen el punto 4: que el modelo casi no distinga escenas. Con ellas, una respuesta mala deja de atrapar al dron; que la fuente aporte información es la pregunta de IT.9.9, riesgo D.

### A11.4.6 Una respuesta cortada y una capa sin voz

En una tercera corrida piloto, el dron llegó a los tres primeros waypoints —incluido el que está detrás de una manzana— y quedó trabado en el tramo hacia el cuarto, contra la fachada de un edificio que la recta atraviesa. Tres mecanismos lo dejaron sin salida:

1. **El modelo marcó libres los costados de una fachada.** En las cinco consultas del tramo marcó bloqueado el sector de frente —lo correcto— y libres los demás, incluso en fotogramas en los que la fachada ocupaba todo el cuadro. En las 28 consultas de la corrida, el sector de la izquierda a la altura del dron salió libre las 28 veces y el de arriba a la izquierda, bloqueado 24: un sesgo por posición en la grilla, no una descripción de la escena. La sub-meta elegida quedó del otro lado de la fachada, y el dron se deslizó a lo largo de ella unos 180 ciclos.
2. **La capa estratégica no consultó en todo ese tiempo.** El dron miraba a lo largo de la pared, con la meta fuera de los ±40° del eje óptico, la condición para consultar: justo cuando hacía falta replanificar, la capa no tenía cómo hacerlo.
3. **Los barridos se perdían por el tope de tokens.** Un tope de 160 tokens cortaba la respuesta del barrido —un JSON con indentación— antes de la llave final, en 5 de 12 barridos; esos barridos caían al escape vertical sin usar la respuesta del modelo. La falla no se veía: el registro la clasificaba como «sin formato válido», igual que una respuesta mal formada.

La corrida terminó por `physics_locked`, con el dron apoyado en la baranda de un balcón (IT.A11.4.3). Además, se ejecutó con cambios sin commitear y quedó registrada con el mismo `code_version` que otra corrida con distinto código: un criterio de descarte por versión basado solo en el hash no la distingue.

**Mecanismo de contención.** Los topes de tokens son 384 (estratégico) y 512 (barrido), y una respuesta cortada se reporta como `respuesta_truncada`, separada de las respuestas mal formadas (Anexo 10, IT.A10.6.2); la capa estratégica consulta con la meta fuera de cuadro cuando el dron lleva `VLM_STUCK_QUERY_CYCLES` (15 ciclos, 3 s) sin acercarse a su objetivo, sin interpretar nunca esa respuesta como «camino directo libre» (IT.5.5.1); y `code_version` lleva el sufijo `-dirty` si hay cambios sin commitear, lo que excluye la corrida de un lote (Anexo 12, IT.A12.7.2). Los tests `tests/test_pilot_193631z_regressions.py` reproducen cada caso. El punto 1 —que el modelo describa la grilla por posición y no por contenido— no tiene mecanismo de contención dentro del VLM: es la pregunta de IT.9.9, riesgo D, y la medición que la responde es la comparación sector por sector contra una etiqueta de referencia (cap. 10, IT.10.2).

### A11.4.7 Un barrido que no describe la escena

Con las respuestas del barrido completas, tres corridas piloto suman 19 respuestas utilizables. En las 19 el patrón de transitabilidad fue el mismo: las imágenes 2 y 4 —a 90° a cada lado del rumbo inicial— transitables, y la 1 y la 3 —el frente y la dirección de la que venía el dron— bloqueadas, sin importar dónde estaba el dron ni qué mostraban las imágenes. La dirección de la que venía el dron, casi siempre libre, salió bloqueada las 19 veces. Además, el modelo marcó todas las respuestas como degradadas, incluidas imágenes nítidas de calle abierta, y en varias asignó `ok: true` a imágenes de tipo `fachada` o `interior`. Medido contra el avance hacia el waypoint real, las sub-metas del barrido no mostraron efecto: en la mayoría de los casos el avance a los 20 s fue nulo, y en dos el dron se alejó más de 5 m.

La consecuencia de diseño es doble. Primero, una respuesta constante convierte al barrido, en la práctica, en una regla fija («girar 90° hacia el lado más cercano a la meta»), y una regla de falla basada en el indicador de imagen degradada lo convertiría en un escape vertical ciego (en una de esas corridas habría descartado los 8 barridos). Segundo, elegir el rumbo transitable más cercano a la meta devuelve al dron, deadlock tras deadlock, contra el mismo obstáculo.

**Mecanismo de contención.** El esquema no pide indicador de imagen degradada ni certeza (cap. 8, IT.8.2.1); y la salida del deadlock descarta el rumbo que falló y los rumbos ya probados en la zona, y con deadlocks repetidos explora el rumbo libre más distinto de lo ya probado (cap. 5, IT.5.6). Esto no corrige que el modelo responda lo mismo siempre: con una respuesta constante, la salida queda determinada por la historia del dron y no por la imagen. El registro de la selección permite separar ambos efectos.
