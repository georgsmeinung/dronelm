# Revisión del informe y de los cuadernos NB1–NB5 frente al código (2026-11-12)

Alcance: código en HEAD `6cecff7d` (`airsim-loop/src` sin cambios desde la corrida v4), informe completo con búsqueda dirigida y los cinco cuadernos `airsim-loop/NB*.ipynb`, código y salidas guardadas. No se re-ejecutaron los cuadernos: se leyeron sus salidas y se recalcularon por separado las cifras en disputa.

## 1. Referencias

- **`§` → `IT.`**: los capítulos 1–13 ya usaban `IT.`. Se convirtieron las 186 referencias que quedaban, en los anexos A1–A9 y en `informe/README.md`. Las de anexos quedan como `IT.A7.2`.
- **Notebooks**:
  - las `§` internas pasaron a `NBk.n`;
  - las que apuntan al informe, a `IT.x`;
  - en NB5.12 se cambiaron también las etiquetas de la tabla de salida guardada, para que coincidan con el código.
- **El informe cita ahora los cuadernos** donde reproducen un cálculo:
  - IT.4.3.1 → NB4.1–NB4.8;
  - IT.4.4 → NB2;
  - IT.5 → NB3;
  - IT.5.8 → NB3.3;
  - IT.5.10.3 → NB4.9;
  - IT.6.6 → NB3.4;
  - IT.7.4 → NB5.10;
  - IT.7.5 → NB5.11;
  - IT.10.7 → NB1;
  - IT.10.13.4 → NB5 y NB5.9;
  - IT.11.0 → NB5.2;
  - IT.11.1 → NB1 y NB1.10;
  - IT.11.6 → NB1.9.
- **Verificación**: todas las referencias `IT.x` del informe, de los cuadernos y de los README apuntan a un encabezado existente, y todas las `NBk.n` a una sección de cuaderno. La única rota era `IT.4.4.1`, que no existe; pasó a `IT.4.4`.

## 2. Informe frente al código y los datos: corregido

| Dónde | Decía | Lo verificado |
|---|---|---|
| IT.5.8 | La evasión lateral se compromete en `active_maneuver` y la regla 3 la continúa | `evasive_node` no escribe `active_maneuver`: el lado se elige cada ciclo y puede alternar. NB3.3 lo muestra |
| IT.5.14 | `MANEUVER_DURATION_S` (2 s) para `EVADIR_*` | En `slm` solo rige para la macro del barrido; las evasiones no se comprometen. La FSM sí compromete `EVADIR_*` y los escapes durante 1.5 s |
| IT.7.4 | Sens./espec. 0.91/0.88, 0.93/0.89, 0.90/0.91; umbral τ=1 ~2.1 s | Recalculado: 0.90/0.94, 0.95/0.93, 0.96/0.89; umbral 1.93 s (coincide con NB5.10) |
| IT.7.7 | Sensibilidad 93 %, especificidad 89 %; FN 7 %, FP 11 % | 95 %/93 % con el umbral de 3.2 s; FN 5 %, FP 7 %. Las cifras anteriores salían de la tabla errónea |
| IT.7.7 | Completar con obstrucción «por la reacción a contacto y la salida de atascos» | La FSM no tiene reacción a contacto y completa igual: queda «salida de atascos y, en `slm`, reacción a contacto» |
| IT.11.0 | Ruta `airsim-runs/vlm_bench/v2/` | `airsim-runs/test/vlm_bench/v2/` |
| IT.11.0 | Exclusiones 190 / 384 / 589 | Los motivos no son excluyentes: suman 1163 sobre 993 excluidas. Se agrega el conteo excluyente (190 / 381 / 422, NB5.2) |
| IT.11.4, IT.11.6, IT.12.2 | Latencia de la capa estratégica 114–135, 104–135 y ~110–135 ms | 104.0–134.4 ms (`v4_latencias.csv`) → 114–134 y 104–134 |
| IT.10.13.4, IT.12.3 | No mencionaban el lote piloto de fuentes | Se agrega: `depth`, `vlm` y `off` son equivalentes en avance (13 waypoints a los 400 s en las tres); `off` logra 5/5 éxitos, `depth` 3/5. Es el único dato previo sobre el aporte de la capa estratégica (NB5.9) |

## 3. Notebooks: corregido

| Cuaderno | Problema | Corrección |
|---|---|---|
| NB1.8 | Atribuía la no-bloqueante a IT.9 | IT.5.1.2. Además, nota de que el eje usa la longitud óptima del SPL (120 / 345 / 588 m) y el informe la ruta desde el *spawn* (181 / 421 / 598 m) |
| NB2.6 | La sub-meta remitía a NB4.5 (logprobs) | NB4.9 |
| NB2.10 | «La semilla fija el *jitter* de arranque» | Falso en los lotes (IT.10.4.2): la semilla solo identifica la réplica |
| NB3.0 | Datos de v4 citados como IT.3, IT.4 e IT.9 | IT.10.9.1 e IT.11.1 |
| NB3.5 | «Tres umbrales, todos calibrados (IT.7)» | Son cuatro, y solo el de ocupación está calibrado; los demás son valores de diseño (IT.6.9) |
| NB3.6 | Encabezado `NB.6` | `NB3.6` |
| NB3.9 y NB3.10 | Erratas «preubas» y «vuelso»; IT.9 como referencia del registro | Erratas corregidas; la referencia del registro pasó a IT.5.18 |
| NB4 | «Video Language Model»; «las inspección» | «Vision-Language Model»; «la inspección» |
| `airsim-loop/README.md` | Dos enlaces a cuadernos con el nombre viejo, que ya no existen | Nombres `NB*_…` y orden NB1–NB5 |

Lo que se verificó y está bien:
- **NB1** reproduce `analisis_lotes.md` y sus CSV, con las aserciones de NB1.10 en verde.
- **NB3.9** reproduce el 99.13 % de las decisiones de una corrida. Las diferencias son empates de ocupación redondeados en el log.
- **NB4.6** reproduce el plan del lote 6.
- **NB4.9** reproduce las 77 sub-metas de esa corrida, exactas.
- **NB5** recalcula el banco, el `map_probe`, el `route_bench`, el TTC y D2 con los mismos valores que el informe, salvo la tabla de IT.7.4, ya corregida.

## 4. Pendiente: necesita decisión o trabajo aparte

1. **NB5.9: la elección de `depth` frente a `off` no sale de la regla del lote.** La regla decide por costo y seguridad ante avance equivalente. `off` no tiene costo de inferencia y completó 5/5, contra 3/5 de `depth`; la única ventaja de `depth` es una DistMin mediana algo mayor (5.8 frente a 4.9 m), con 5 corridas. El cuaderno ya dice que el lote no muestra ventaja de la capa. Conviene declarar en IT.10.13.4 por qué se conservó la capa en la v4: por ejemplo, para evaluarla con 10 semillas.
2. **Trazabilidad de IT.7.7.** Ningún cuaderno ni script guardado produce estas cifras:
   - las 11 621 muestras de DistMin contra el campo registrado;
   - el 23 % / 17 % de bloqueo del sector central;
   - la evaluación de la corrección de *inliers* (20–27 % frente a 33–40 %).

   Sugerencia: una sección NB3.x o NB5.x que las recalcule.
3. **La fila 3 de la grilla siempre sale bloqueada con la profundidad** (NB2.6, NB4.9). A 10 m de altura, el borde inferior del recorte corta el suelo a 15 m, así que el p5 del sector nunca llega a 15 m. Por eso la capa con profundidad nunca propone pasar por abajo, y el piso de altitud de la sub-meta no llega a actuar. El informe no lo dice (IT.5.10.3 e IT.5.10.6).
4. **Evidencia del flujo en vuelo.** En la corrida de referencia de NB2.5, el campo tiene fuente `flow` en el 38 % de los ciclos, `holdover` en el 26 % y `degraded` en el 35 %. El informe no informa esta proporción, que explica en parte el gobernador activo y la discriminación pobre del IT.7.7.
5. **Sitio publicado.** `docs/informe` no se regeneró: hay que correr `build.ps1` o `mkdocs build` para que el sitio y el PDF tengan los cambios.
6. **Archivos históricos.** `CHANGELOG.md` y `plan-tesis/PLAN-ANALISIS.md` conservan los nombres viejos de los cuadernos. No se tocaron porque son registros históricos.

## 5. Actualización: pendientes 1–4 aplicados

1. **IT.10.13.4.** Se agregó por qué la v4 conserva la capa: con 5 pares el lote piloto no puede descartarla (el *p* de Wilcoxon no baja de 0.0625), y se la juzga con 10 semillas en `slm:depth`–`fsm:depth`. Es una justificación metodológica propuesta: confirmar que coincide con la razón real.
2. **NB1.11 (nuevo).** Recalcula desde los registros de la v4 la fuente del campo por celda y el sector central frente a DistMin. Reproduce los porcentajes de IT.7.7 (23 % / 17 %; con fuente `flow`, 24 % / 14 %), con 11 642 muestras y 1003 positivos, en lugar de 11 621 y 999 (cambia la asociación muestra–ciclo). IT.7.7 usa ahora esas cifras y cita NB1.11. La evaluación de la corrección de *inliers* sigue sin reproducir: IT.7.7 lo declara.
3. **IT.5.10.6.** A 10 m de altura la fila de abajo no sale libre con la profundidad; a 30 m sí puede. Remite a NB2.6 y NB4.9.
4. **IT.11.3.** El campo es `flow` en el 39 % de los ciclos de `slm`, el 37–41 % de las FSM y el 70 % de `reactive`. Los giros explican la diferencia y el gobernador activo (NB1.11).

Las salidas de NB1.11 se generaron ejecutando sus dos celdas con el mismo contexto del cuaderno. El resto de NB1 no se re-ejecutó.
