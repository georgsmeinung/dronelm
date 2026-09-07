# Plan de implementación 4 — De demo parcial a demo de los 3 tiers + corrida de tesis limpia

**Fecha:** 2026-09-04
**Origen:** revisión crítica del estado del repo al HEAD `ad83c05` (2026-09-03 19:09, sin commits
posteriores), cruzando el `CHANGELOG.md` con el estado real de misiones y corridas en disco. Ningún
batch G4 se ejecutó todavía (no existe `runs/tesis/`); Tier 2 no voló ni una sola vez desde que se
renombró (2026-08-28); dos bugs de percepción corregidos el 2026-09-03 invalidan, para fines
comparativos, cualquier dato de vuelo del brazo `slm` anterior a esa fecha.
**Estado de partida:** H0–H4 de `PLAN-MEJORAS-3.md` implementadas (guardia de no-profundidad, escaneo
inicial y profundo, `DEADLOCK_STRATEGY=blind|deep_vlm` con `deep_vlm` como default de producción desde
el 3-sep). `PLAN-PRUEBAS-TOWNSIM.md` define 6 escenarios T-CALIB sobre `townsim_calib.png`, de los
cuales solo T-CALIB-0 (`perimetro`) tiene corrida real validada; T-CALIB-1/2 tienen manifiesto
(`townsim_calib_pilot.json`, `townsim_calib_cruce_frontal.json`) sin protocolo §5 corrido; T-CALIB-3/4/5
siguen sin manifiesto, con coordenadas marcadas PROVISORIAS. Tier 0 (MiniSim) cerrado en verde el
2026-08-28 (1 semilla × 3 brazos), sin revalidar contra los ~15 fixes posteriores. Tier 2 (CitySim)
solo tiene un piloto renombrado (`citymap_pilot.json`, ex `manhattan_b`), nunca volado con el código
actual — ni siquiera contra el propio bug de canales de color, activo hasta ayer.
**Objetivo:** (a) una demo grabable y presentable en los 3 tiers de dificultad, con evidencia visual
(`.webm` + `viewer.html`) por brazo relevante; (b) dejar corrido, por primera vez, el batch G4 real
(3 brazos × 3 escenarios × ≥5 semillas) sobre datos posteriores a los fixes del 3-sep, habilitando el
cap. 11 del informe con datos reales en vez de placeholders.

---

## 0. Criterio de orden

Igual que los planes anteriores: ordenado **por dependencia, no por importancia**. La diferencia con
`PLAN-MEJORAS-2.md` es que ahora no hay un solo bloqueante técnico — hay tres tiers en estados muy
distintos, y el riesgo real está en el que menos atención tuvo (Tier 2), no en el que más código nuevo
acumuló (Tier 1).

| Fase | Qué desbloquea | Estado final |
|---|---|---|
| **I0** Cuarentena de datos pre-fix + trazabilidad de versión | Que cualquier corrida usada en la tesis sea auditable por commit | Runs manuales previos al 3-sep documentados como no comparables; `summary.json` incluye el hash de código |
| **I1** Revalidación de Tier 0 | Confianza de que los fixes de esta semana no rompieron el caso base | 3 brazos, 1 semilla, verde, con video de referencia |
| **I2** Cierre de Tier 1 | El tier con más evidencia queda demo-ready y batch-ready | T-CALIB-2/3 pasan el protocolo §5; `TOWNSIM_INI` grabado con los 3 brazos |
| **I3** Bootstrap de Tier 2 | El tier que hoy es el riesgo real de toda la demo | `citymap_pilot` piloteado con el código actual; riesgo de fachadas de baja textura diagnosticado; parámetros de navegación Manhattan (`MAX_CONSECUTIVE_ESCAPES`, `CORNER_OFFSET_M`) revalidados a escala de manzana; `citymap_a.json` creado y validado |
| **I4** Empaquetado de la demo | El entregable en sí | 1 video+viewer por brazo relevante por tier, guión de presentación |
| **I5** Ablation del brazo `slm` (4 mejoras del 3-sep) | Saber si el efecto medido es real o ruido de una corrida, y si queda un residuo no-mecánico del bucle de confianza | Comparación multi-semilla antes/después de los 4 cambios; residuo del bucle de confianza clasificado por causa |
| **I6** Corrida de tesis G4 | El cap. 11 del informe, con datos reales | 3×3×5 corridas posteriores a los fixes del 3-sep, `ANALYSIS.json` con Mann-Whitney |
| **I7** Deuda de escritura | Coherencia del informe con el código actual | Cap. 09 documenta el hallazgo de color invertido; cap. 11 remapeado; prosa `manhattan_a/b` limpia |
| **I8** Deuda menor | Higiene | Política de `FLIGHT_RECORD_VIDEO` para batches grandes; versión de paquete unificada |

**Regla transversal nueva:** ningún resultado que vaya al cap. 11 puede provenir de una corrida anterior
al fix de "canales de color R/B invertidos en toda captura de AirSim" (2026-09-03) ni al fix de
marcadores de debug contaminando la captura del VLM (mismo día) — ambos afectan directamente lo que el
brazo `slm` vio antes de decidir. I0 existe para que esto sea verificable en cada `summary.json`, no
solo recordado.

---

## Fase I0 — Cuarentena de datos pre-fix y trazabilidad de versión

Duración estimada: medio día. Sin dependencias — hacer primero, es barato y evita contaminar todo lo
demás.

### I0.1 — Marcar las corridas manuales anteriores al 3-sep

`airsim-plan/runs/manual/TOWNSIM_CALIB_0_20260831T234305Z.*` y `..._20260901T001142Z.*` son anteriores
tanto al fix de color invertido como al de marcadores de debug — ambos afectan directamente lo que el
VLM vio en esas corridas. No se descartan (siguen sirviendo como evidencia de que la geometría
T-CALIB-0 es volable, y de que el corredor central es transitable), pero se documentan explícitamente
como **no aptas para comparación `slm` vs `fsm`/`reactive`**: agregar una nota con la fecha de corte en
`PLAN-PRUEBAS-TOWNSIM.md §1.2`.

### I0.2 — `code_version` en el summary de cada corrida

`FlightLogger.close()` (`src/logging/flight_logger.py:348`) no registra qué versión del código voló.
Agregar `"code_version": <hash corto de git>` al dict de `summary` (junto a `deadlock_strategy`, línea
~376), obtenido con `subprocess.run(["git", "rev-parse", "--short", "HEAD"])` y fallback a `"unknown"`
si falla (por ejemplo, corriendo desde un export sin `.git`). Mismo campo en el `RESULTS_SUMMARY.json`
de `batch_runner.py`. Un test de regresión que confirme que el campo existe y no es `None`/`"unknown"`
en una corrida real dentro de un repo con `.git`.

**Criterio de aceptación:** cualquier corrida nueva (manual o batch) queda auditable por commit;
`experiments/analyze.py` puede filtrar por `code_version` si en el futuro hace falta excluir un rango
de fechas sin depender de comparar timestamps a mano.

---

## Fase I1 — Revalidación de Tier 0 (MiniSim)

Duración estimada: 30–45 min de cómputo. Depende de I0.2 (para que la corrida quede trazada).

### I1.1 — Re-correr el piloto de referencia

El "cerrado en verde" del 28-08 es anterior a los fixes de color invertido, pitch/roll, creep speed y
`deep_vlm` por default. Repetir exactamente la misma corrida de entonces:

```
python experiments/batch_runner.py \
    --scenarios ../airsim-plan/missions/minisim_clear.json \
    --arms slm fsm reactive \
    --seeds 1 \
    --out-dir runs/i1_minisim_revalidation \
    --max-cycles 600 --max-seconds 120
```

**Criterio de aceptación:** los 3 brazos siguen en `success=True`, 0 colisiones — mismo resultado que
el 28-08. Si algo cambió, investigar antes de tocar Tier 1/2: es el escenario más simple del proyecto;
si se rompió acá, probablemente se rompió en todos lados.

### I1.2 — Un video de referencia

Con `FLIGHT_RECORD_VIDEO=true`, una corrida manual de `minisim_clear` con brazo `slm` — sirve como la
pieza "caso base, sin obstáculos" de la demo, el mismo rol que ya describe `PLAN-PRUEBAS-TOWNSIM.md`
para `T-CALIB-4` pero un nivel más simple todavía.

---

## Fase I2 — Cierre de Tier 1 (TownSim)

Duración estimada: 1–2 sesiones de vuelo. Depende de I0, I1.

### I2.1 — Protocolo §5 sobre T-CALIB-2 y T-CALIB-3

`PLAN-PRUEBAS-TOWNSIM.md` ya especifica los manifiestos (§2) y el protocolo de validación (§5);
ejecutarlo sobre los dos escenarios que ejercitan la rama deliberativa real (bloqueo frontal genuino y
elección de corredor):

1. `python scripts/plot_mission_route.py airsim-plan/missions/townsim_calib_cruce_frontal.json` —
   confirmar visualmente en el viewport de UE que la línea cruza una fachada, no una calle abierta.
2. Piloto de 1 semilla, brazo `slm`. Si `success=True` (o el fallo es instructivo — atasco real, no
   error de geometría), pasar a T-CALIB-3.
3. Repetir para `eleccion_corredor`, recordando que su `y=32` está marcado PROVISORIO en el plan de
   pruebas: si el trazado no cae cerca del límite de bloque real, ajustar la coordenada antes de dar
   por bueno el escenario.

### I2.2 — Comparación de los 3 brazos sobre el mismo escenario

`TOWNSIM_INI` (7 waypoints, `townsim_calib.png`) ya corre limpio con `slm` — la corrida más reciente de
la sesión del 3-sep cerró en 0 colisiones, 3582 ciclos/722s, 22/22 atascos resueltos por escaneo
profundo — pero nunca se corrió con `fsm` ni `reactive` sobre el mismo manifiesto:

```
python experiments/batch_runner.py \
    --scenarios ../airsim-plan/missions/townsim_ini.json \
    --arms slm fsm reactive \
    --seeds 1 \
    --out-dir runs/i2_townsim_comparison \
    --max-cycles 3000 --max-seconds 600
```

Presupuesto calculado con el mismo criterio de margen ×2.5 sobre velocidad de crucero real que ya usa
`PLAN-PRUEBAS-TOWNSIM.md §3` (no la velocidad nominal, que sobreestima el avance).

### I2.3 — Video + viewer por brazo

`FLIGHT_RECORD_VIDEO=true` en las tres corridas de I2.2 — es el material de demo de Tier 1: mismo
recorrido, tres políticas de decisión, comparables lado a lado en `viewer.html`.

---

## Fase I3 — Bootstrap de Tier 2 (CitySim)

Duración estimada: 2–3 sesiones — es el tier con más incertidumbre real, hay que tratarlo con la misma
disciplina iterativa que ya rindió en Tier 1 (un tramo a la vez, confirmado visualmente en el
viewport, sin inventar geometría a partir de la imagen). Depende de I0.

### I3.1 — Sanity check del piloto existente

`citymap_pilot.json` no voló ni una vez desde que se renombró (28-08) — ni siquiera contra el propio
bug de color invertido, activo hasta ayer. Antes de cualquier otra cosa:

1. `plot_mission_route.py` sobre `citymap_pilot.json`: confirmar visualmente que la ruta no arranca
   dentro de un edificio ni cruza una fachada por accidente — mismo riesgo que motivó la regla de "sin
   teletransporte" en TownSim (`PLAN-PRUEBAS-TOWNSIM.md §0.4`).
2. Piloto de 1 semilla, brazo `slm`, presupuesto generoso: el mapa es nuevo, no hay velocidad de
   crucero medida todavía sobre él — partir de `--max-seconds 300` y ajustar según lo que muestre el
   log, en vez de asumir el presupuesto de otro tier.

**Criterio de arranque (igual que cap. 10/11 del informe):** si esta corrida no da `success=True` ni un
fallo instructivo, no tiene sentido avanzar a I3.2 — el problema es de geometría o presupuesto, no de
política de decisión, y hay que resolverlo antes de construir nada nuevo sobre este mapa.

### I3.2 — Diagnóstico de textura en fachadas planas (riesgo distinto al bucle mecánico del 3-sep)

Tier 2 introduce un tipo de superficie que Tier 0/1 apenas tuvieron: fachadas grandes, planas y de baja
textura (hormigón pintado, vidrio). `flow_ttc.py` ya documenta que el cielo/nubes —misma categoría de
superficie, poquísima textura— producían flujo óptico ruidoso leído como obstáculo falso (bug del
2026-0826), mitigado hoy solo para rotación fuerte (`FLOW_MAX_ROTATION_DEG=2.0`). Una fachada lisa
encontrada en **crucero recto** (no girando) no está cubierta por ese fix, y el creep-speed del 3-sep
tampoco la resuelve: más traslación hacia una superficie sin textura no sube la confianza, solo acerca
más rápido al obstáculo sin nunca resolver la duda — es un modo de falla estructural, no mecánico.

En el piloto de I3.1, además de `success=True`, revisar explícitamente `centro_conf` del CSV en los
tramos donde el dron cruza cerca de una fachada — mismo método que el análisis de deliberación excesiva
del 3-sep. Si aparece confianza baja sostenida pese a traslación confirmada, documentar el hallazgo antes
de I3.3: la corrección ahí no es de velocidad (ya se probó esa vía), sino de qué hacer cuando la
confianza se mantiene baja sin evidencia de peligro real — una estrategia de degradación explícita
(p. ej. tope de ciclos con confianza baja + traslación confirmada, antes de forzar una decisión distinta
a seguir escalando) que no existe todavía porque nunca hizo falta.

### I3.3 — `citymap_a.json`: el escenario con bloqueo real

`G4_THESIS_RUN.md` lo marca pendiente desde el 28-08. Mismo patrón que T-CALIB-2 en TownSim: identificar
por inspección directa del viewport (nunca por lectura de píxeles del PNG, misma regla que
`PLAN-PRUEBAS-TOWNSIM.md §0`) un tramo con corredor angosto entre edificios altos — es precisamente la
característica que la tabla de tiers del 28-08 usa para definir Tier 2 frente a Tier 1 ("edificios
altos, corredores angostos" vs. "vegetación, obstáculos orgánicos"). Construir el manifiesto de forma
iterativa (un tramo, confirmar en el viewport, agregar el siguiente), igual que se hizo con
`TOWNSIM_DEMO` — no de una sola vez.

### I3.4 — Comparación de brazos

Con I3.3 en verde, repetir el patrón de I2.2 sobre `citymap_a.json`: 3 brazos, 1 semilla, video por
corrida.

### I3.5 — Re-validar parámetros de navegación Manhattan a escala de manzana

`compute_corner_waypoint`/`CORNER_OFFSET_M`/`MAX_CONSECUTIVE_ESCAPES` están calibrados sobre Tier 1
(obstáculos puntuales tipo árbol, un solo giro de 90° suele bastar). Rodear un bloque rectangular
completo en Tier 2 puede necesitar 3-4 giros encadenados solo por geometría — potencialmente al límite
de `MAX_CONSECUTIVE_ESCAPES=3` (hoy), lo que puede leer un desvío largo pero legítimo como un atasco real
y forzar la caída a escape ciego innecesariamente (mismo tipo de falso positivo que ya se corrigió una
vez con `progress_stall_cycles`). Medir en `citymap_a.json`:

- Cuántos giros consecutivos hace falta encadenar para completar un desvío real de manzana; subir
  `MAX_CONSECUTIVE_ESCAPES` si el dato lo justifica, documentando la medición (misma disciplina de
  "todo umbral sale de una medición" de `PLAN-MEJORAS-2.md`).
- Si `CORNER_OFFSET_M=12.0` es compatible con el ancho de calle real de `citymap.png` — si las calles son
  más angostas, el offset puede depositar al dron cerca de la fachada opuesta. Ajustar contra el ancho
  medido, no contra el valor que funcionó en TownSim.

### I3.6 — Retener la intención de rodeo a través de varias esquinas, no re-deliberar en cada una

Hoy cada esquina de un desvío se trata como un evento independiente: si rodear una manzana requiere
varios `CORNER_WP` encadenados, cada uno puede disparar una deliberación completa del SLM, generando el
mismo efecto de "idas y vueltas" que ya se identificó en el bucle de confianza, pero por una causa
distinta (re-litigar una decisión ya tomada, no falta de confianza). Extender el `MANEUVER_LOCK` ya
existente en `main.py` para que, decidido un rodeo, la intención se retenga a través de toda la secuencia
de esquinas (no solo los 4-5 ciclos de una maniobra), y solo se re-invoque al SLM ante una obstrucción
nueva no prevista por esa intención. No requiere memoria espacial ni cambios a `DroneState` — es una
generalización del enclavamiento de "una maniobra" a "una secuencia de maniobras" ya prevista por el
mecanismo actual.

### I3.7 — Adaptar el prompt del escaneo inicial (H1) para lectura de cuadrícula

Una manzana es geometría rectangular predecible — mucho más legible desde una foto aérea que un dosel de
vegetación orgánico. Revisar si el prompt de H1 pregunta explícitamente por orientación de calle/corredor
por rumbo ("¿hacia dónde corre la calle visible acá?"), no solo clear/blocked/sin evidencia — es
aprovechar la herramienta que ya construye el equivalente cualitativo de un mapa, específicamente donde
más rinde: geometría urbana rectilínea, no vegetación dispersa.

---

## Fase I4 — Empaquetado de la demo

Duración estimada: medio día. Depende de I1, I2, I3.

- Un video + `viewer.html` por combinación tier×brazo relevante — mínimo `slm` en los 3 tiers para
  mostrar progresión de dificultad; idealmente también `fsm` en Tier 1/2 para el contraste que motiva
  la tesis.
- Guión corto de presentación: Tier 0 (costo fijo, sin nada que negociar) → Tier 1 (evasión real +
  escaneo profundo resolviendo atascos, `TOWNSIM_INI` ya lo muestra) → Tier 2 (corredor angosto, la
  razón de ser del proyecto).
- Para demo en vivo: la tarjeta "Guía de Inicio Rápido" de WebDCS (agregada el 3-sep) sirve para lanzar
  misiones frente a audiencia sin depender de la línea de comandos.
- Para versión grabada/offline: los `viewer.html` generados en I1.2/I2.3/I3.4, con video y CSV
  sincronizados por slider.
- Etiquetar explícitamente cada resultado mostrado como **1 semilla, ilustrativo** — la tabla con
  significancia estadística es I6, no esta fase.

---

## Fase I5 — Ablation del brazo `slm`: ¿el efecto de las 4 mejoras del 3-sep es real?

Duración estimada: medio día de cómputo. Puede correr en paralelo con I3.

Las cuatro mejoras del 3-sep (`VLM_FRAME_HISTORY_SIZE=2`, estado de vuelo en el prompt, motivo de
consulta explícito, avance cauteloso en vez de frenar del todo mientras se espera al SLM) se validaron
con comparaciones de una sola corrida antes/después (108→48→26 invocaciones sobre la misma ruta) — el
propio `CHANGELOG.md` lo describe como "alentador, no concluyente". Antes de reportarlo como una mejora
establecida:

```
python experiments/runner.py \
    --scenarios ../airsim-plan/missions/townsim_ini.json \
    --arms slm --seeds 1 2 3 4 5 \
    --out-dir runs/i5_slm_ablation_post \
    --max-cycles 3000 --max-seconds 600
```

Comparar `slm_invocations`/`deliberation_rate` (5 semillas, código actual) contra una corrida
equivalente revirtiendo temporalmente los 4 cambios en una rama descartable (no se mergea) — mismo
escenario, mismas semillas, para que la comparación sea limpia. Si la reducción se sostiene con
varianza entre semillas, el hallazgo pasa de anecdótico a reportable en cap. 11/H4; si no, es un
resultado negativo válido igual (mismo criterio que G4.3).

### I5.1 — Diagnóstico del residuo: ¿cuánto del bucle de confianza sigue vivo después del creep-speed?

El análisis del 3-sep sobre 103 deliberaciones de `TOWNSIM_INI` encontró que el 82.5% se disparaba por
`centro_conf < 0.1` sin obstáculo real (`centro_blocked=True` en solo 0.97%), y atribuyó la causa a un
bucle mecánico auto-inducido (frenar/rotar mata la traslación que el propio estimador necesita para
recuperar confianza) — ya parchado con el avance cauteloso. Sobre las 5 semillas de este mismo I5,
repetir esa clasificación (`centro_conf`/`centro_blocked`/velocidad horizontal en los ciclos previos a
cada disparo) para separar, del total de deliberaciones que sobrevivan:

- las que siguen siendo mecánicas (traslación insuficiente pese al creep-speed — señal de que el parche
  necesita ajuste fino, no de que el enfoque esté mal);
- las que ya no lo son (traslación confirmada, confianza baja igual) — candidatas a la causa de textura
  de I3.2, no al bucle mecánico.

Este número es el que decide si vale la pena diseñar algo más allá de lo ya hecho: si el residuo es
chico, no hay mucho margen para una mejora adicional; si es grande y de causa no-mecánica, es la
confirmación de que el hallazgo de I3.2 (fachadas de baja textura) es un problema real y no solo teórico.

---

## Fase I6 — Corrida de tesis G4 (la real, no la demo)

Duración estimada: ~1 día de cómputo (más si Tier 2 resulta lento) + 1 día de análisis. **Depende de
I0, I2, I3** — no se ejecuta hasta que los 3 tiers tengan al menos un piloto verde posterior a los
fixes del 3-sep.

### I6.1 — Diseño

Retoma el diseño de `G4_THESIS_RUN.md`/`PLAN-MEJORAS-2.md §G4.1`, ahora completable por primera vez:

- **Brazos:** `slm`, `fsm`, `reactive`.
- **Escenarios:** `minisim_clear` (Tier 0), el escenario T-CALIB validado en I2 o `townsim_ini` (Tier
  1), `citymap_a` de I3.3 (Tier 2) — el "tercer escenario con bloqueo frontal masivo" que pide el cap.
  10.1 del informe queda cubierto por Tier 1 y reforzado por Tier 2.
- **Semillas:** 5 (1–5).
- **`DEADLOCK_STRATEGY`:** aprovechar la misma tanda para correr el ablation `blind` vs `deep_vlm` de
  H3 (`--deadlock-strategies blind deep_vlm`, ya soportado por `experiments/runner.py`).

```
python experiments/batch_runner.py \
    --scenarios ../airsim-plan/missions/minisim_clear.json \
               ../airsim-plan/missions/townsim_ini.json \
               ../airsim-plan/missions/citymap_a.json \
    --arms slm fsm reactive \
    --seeds 1 2 3 4 5 \
    --out-dir runs/tesis \
    --max-cycles 3000 --max-seconds 600
```

Ajustar `--max-cycles`/`--max-seconds` por escenario si la duración real difiere mucho entre tiers —
no forzar el mismo presupuesto fijo si Tier 2 resulta sustancialmente más largo que Tier 0.

### I6.2 — Verificación de procedencia

Antes de usar `RESULTS_SUMMARY.json` para el cap. 11: confirmar que **todas** las corridas tienen
`code_version` (I0.2) posterior al commit del fix de canales de color invertidos. Si el batch corrió
antes de que I0.2 estuviera mergeado, repetirlo — no vale la pena analizar, para el capítulo central de
la tesis, datos de procedencia dudosa.

### I6.3 — Análisis

`experiments/analyze_tesis_results.py` + la tabla de resolución de atascos por
`AGENT_ARM × DEADLOCK_STRATEGY` (H3.3, ya instrumentada en `flight_logger.py`) → llenar cap. 11.1
(tabla), 11.2 (histograma de rutas), 11.3 (Mann-Whitney + tamaño de efecto), 11.4 (análisis por
escenario, no en agregado — la pregunta "¿aporta el SLM sobre la FSM?" respondida por tier, como ya lo
pide el cap. 10.3).

---

## Fase I7 — Deuda de escritura

Duración estimada: 1–2 días. Sin dependencias de código; corre en paralelo con I1–I6, salvo I7.2 que
necesita los datos reales de I6.

### I7.1 — Documentar el hallazgo de color invertido en cap. 09

`informe/09-MODOS-DE-FALLA-LLM.md` no menciona el bug de canales R/B invertidos — es un modo de falla
real, del mismo género que los ya documentados (percepción vacía, historial inventado, ocupación
saturada): la interfaz de captura le mintió al modelo sobre el color del mundo durante toda la vida del
proyecto hasta el 3-sep, sin que el desempeño lo delatara de forma obvia. Vale como hallazgo de diseño
para la tesis, no solo como bug corregido en el CHANGELOG.

### I7.2 — Remapear la tabla placeholder del cap. 11

`11-RESULTADOS.md` todavía referencia `manhattan_a`/`manhattan_b`/"(tercer escenario)" — nombres
retirados desde el 28-08. Reemplazar por los nombres reales usados en I6 (`minisim_clear`/
`townsim_ini`/`citymap_a`) antes de llenar la tabla con datos.

### I7.3 — Limpieza de prosa `manhattan_a`/`manhattan_b`

Pendiente desde el 28-08 ("tarea de limpieza de prosa para cuando los tres tiers nuevos estén
corriendo" — ya lo están): capítulos 02, 03, 04 y 10 del informe, `CREATEENV.md`, `PLAN-MEJORAS-2.md`.

---

## Fase I8 — Deuda menor

Duración estimada: medio día. Sin dependencias.

- **Política de `FLIGHT_RECORD_VIDEO` para I6:** una sola corrida ya pesó 213.7 MB. Para las 45
  corridas del batch completo, grabar video en todas es innecesario y caro en disco — reservarlo para
  las corridas que efectivamente van a la demo (I4) o a alguna figura puntual del informe, no al batch
  estadístico completo. Documentar la decisión en `G4_THESIS_RUN.md`.
- **Versionar el dataset de I6 en Zenodo** (cap. 10.4, sigue pendiente) — tiene sentido recién una vez
  que exista el dataset real, no antes.
- **`airsim-plan/version` (`0.32.6`) vs. `airsim_plan.__version__` (`"0.1.0"`, en
  `src/airsim_plan/__init__.py`):** dos números de versión desincronizados en el mismo paquete. No es
  crítico, pero conviene unificar a una sola fuente de verdad antes de que algún número de versión se
  cite en la tesis.

---

## Dependencias y camino crítico

```
I0.1 (cuarentena) ─┐
I0.2 (code_version)┴──> I1 (Tier 0) ──> I2 (Tier 1) ──┬──> I4 (demo)
                                                        │
                                          I3 (Tier 2) ──┤
                                                        │
                                                        v
                                          I6 (G4 real) ──> I7.2 (cap. 11)

I5 (ablation slm) corre en paralelo a I3, no bloquea I6.
I7.1, I7.3, I8 corren en paralelo desde el día 1.
```

**Camino crítico:** I0 → I1 → I2 → I3 → I6 → I7.2.

---

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Tier 2 (`citymap.png`) resulta geométricamente distinto de lo que sugiere el nombre (edificios más separados/juntos) | I3 se estira mucho más de lo estimado, retrasa I6 | Mismo principio que TownSim: nunca inventar geometría, iterar tramo a tramo con confirmación visual; si el mapa no da un bloqueo real, usar `citymap_pilot` solo como escenario de crucero y documentar la limitación en vez de forzar un escenario que no existe |
| El ablation I5 no confirma el efecto de las 4 mejoras del 3-sep | Hay que reportar el hallazgo como no concluyente, no como mejora validada | Es un resultado válido igual — mismo espíritu que G4.3/H3: riesgo negativo medido, no ocultado |
| El batch I6 corre antes de que I0.2 esté mergeado | Datos sin `code_version`, hay que re-correr el batch completo | I6.2 lo verifica explícitamente antes de tocar `analyze_tesis_results.py` |
| Grabar video en las 45 corridas de I6 llena el disco o degrada el rendimiento de la corrida | Corridas fallan a mitad de camino por espacio, o los tiempos dejan de ser comparables entre corridas con/sin grabación | I8 lo resuelve por diseño: video solo opt-in en corridas seleccionadas (I1.2/I2.3/I3.4/I4), nunca en el batch estadístico completo |
| Tier 2 nunca llega a `success=True` ni con presupuesto generoso | I6 queda con solo 2 tiers reales | Documentarlo como resultado honesto (mismo criterio que G4.3): "el sistema no completa el escenario de mayor dificultad" es información, no un fallo del plan — decidir en ese momento si I6 corre con 2 escenarios y Tier 2 queda para trabajo futuro, explícitamente marcado así en el informe |
| Fachadas planas de baja textura reproducen (en crucero recto) el mismo síntoma que el bug de cielo/nubes del 26-08, sin que el fix de rotación (`FLOW_MAX_ROTATION_DEG`) ni el creep-speed del 3-sep lo cubran | El sistema se queda "dudando" indefinidamente frente a una pared sin obstáculo real que lo justifique, en vez de resolver y seguir | I3.2 lo mide explícitamente antes de I3.4; si aparece, es un hallazgo de diseño para el informe (mismo género que los ya documentados en cap. 09), no algo a ocultar |
| `MAX_CONSECUTIVE_ESCAPES=3` (calibrado sobre obstáculos puntuales de Tier 1) resulta insuficiente para rodear una manzana rectangular completa en Tier 2 | Desvíos legítimos y largos se clasifican como atasco y caen a escape ciego innecesariamente | I3.5 lo mide contra `citymap_a.json` antes de correr I3.4/I6, mismo criterio que ya se aplicó una vez con `progress_stall_cycles` |

---

## Lo que no se toca

Fortalezas ya construidas que este plan debe **preservar**:

1. **La guardia de no-profundidad (H0)** y todo lo que garantiza: ningún escenario nuevo de I2/I3
   reintroduce sensores de rango, solo waypoints/altitud — el mismo test estático de
   `test_no_depth_in_flight_path.py` sigue siendo la garantía automática.
2. **El criterio de arranque** (`success=True` en piloto antes de batch) — se aplica sin excepción a
   Tier 2 en I3.1, tal como ya se aplicó a Tier 0 y Tier 1.
3. **La disciplina de "sin teletransporte"** (`PLAN-PRUEBAS-TOWNSIM.md §0.4`) — I3 la hereda
   íntegramente para Tier 2.
4. **`DEADLOCK_STRATEGY=deep_vlm` como default de producción**, con `blind` como red de seguridad — I6
   lo pone a prueba estadísticamente (H3), no lo cambia.
5. **El formato único de misión** (`airsim-plan/missions/*.json`, consolidado el 31-08) — los
   manifiestos nuevos de I3.3 y cualquier ajuste de I2.1 lo respetan, sin reintroducir el formato
   `.preloop.json` divergente.
6. **`deliberations[]` como contrato congelado** y toda la instrumentación de auditoría del 3-sep
   (`viewer.html`, `summary_by_wp.csv`, overlay de video) — I4 las usa tal cual están, no las modifica.
