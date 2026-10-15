# Corrida productiva v4: lotes finales de la tesis

Seis lotes, uno por escenario, que evalúan el sistema descrito en los capítulos 5–8 del informe:
capa estratégica y barrido de atascos con profundidad monocular estimada (`STRATEGIC_SOURCE=depth`,
`DEADLOCK_STRATEGY=depth`); el VLM solo planifica la ruta en CitySim, antes del vuelo. Regeneran la
línea base completa, incluidos los tres escenarios despejados: los resultados de lotes anteriores (septiembre
y octubre) no se usan, porque corrieron con otras configuraciones.

- **Scripts (versionados):** esta carpeta. `run_lotes.ps1` define el diseño; cada `run_loteN_*.ps1` lo llama
  con su número de lote.
- **Resultados (fuera de git):** `airsim-runs/produccion/v4/loteN_<escenario>/`. Los logs, CSV y videos de
  cada corrida son demasiado pesados para GitHub; `airsim-runs/` está en `.gitignore`.
- **Análisis:** `airsim-loop/experiments/analyze_lotes.py` (ver [Análisis](#análisis)).

## Diseño común

| Aspecto | Valor |
|---|---|
| Celdas, escenarios despejados (lotes 1, 2, 5) | `slm:depth`, `fsm:depth`, `reactive` (cap. 10 §10.5.3) |
| Celdas, escenarios con obstrucción (lotes 3, 4, 6) | las tres anteriores + `fsm:blind` (FSM sin barrido, §10.12.2) |
| Semillas | 10 por celda; los primeros 60 primos, sin repetir entre lotes |
| Orden | las celdas se alternan dentro de cada semilla, con el orden rotado por semilla (`runner.py --cells`), para repartir la deriva del simulador entre celdas |
| Presupuesto | 1200 s / 6000 ciclos en todos los lotes: el mismo techo en todos los escenarios, holgado para que un brazo lento falle por el obstáculo y no por el tiempo (en octubre `slm:depth` tardó 430–500 s en `citysim_pilot`). Las corridas exitosas terminan antes; el techo solo alarga las que se traban. A 5 Hz, se agota antes el tiempo que los ciclos |
| Arranque | spawn limpio de AirSim; la semilla identifica una réplica (§10.4.2). `-SeedJitter` usa `start_pose` con jitter |
| Versión | el runner no arranca con cambios sin commitear en `airsim-loop/`, `config/`, `airsim-plan/` o `experiments/`; todas las corridas de un lote llevan el mismo `code_version` |
| Python | el de `AIRSIM_ENV_DIR` en `config/.env` (`D:\TesisMCD\airsimenv\python.exe`); no hace falta activar el entorno. `runner.py` no arranca un lote con otro intérprete |

Qué aísla cada celda:

- `slm:depth`: el sistema completo (capa estratégica + política del lazo rápido del brazo `slm` + barrido).
- `fsm:depth`: la misma resolución de atascos con profundidad, sin capa estratégica y con política FSM.
- `fsm:blind`: la FSM sin barrido (escape determinista). Solo en obstrucción, donde hay atascos que resolver.
- `reactive`: flujo óptico + TTC, sin deliberación; su varianza entre semillas es el control negativo del diseño.

## Los lotes

Total: 210 corridas, unas 44 h en el peor caso. Los tiempos son de reloj, a partir de los lotes de octubre y
del lote base: en los despejados, la duración típica de una corrida; en los de obstrucción, el peor caso
(`slm:depth` con su duración de octubre y las demás celdas agotando los 1200 s, ~21 min con el cierre).

### Lote 1 — `minisim_clear` (Tier 0, control)

- **Nivel UE:** MiniSim. **Celdas:** 3. **Corridas:** 30. **Presupuesto:** 1200 s / 6000 ciclos. **Plan de ruta:** off. Sin plan de ruta: el nivel MiniSim es un plano liso con textura de tablero, sin obstáculos, de modo que la recta entre waypoints ya es la ruta óptima y no hay mapa que juzgar (`crater.png` no corresponde al mundo).
- **Semillas:** 2 3 5 7 11 13 17 19 23 29. **Tiempo:** ~1.5 h (las corridas terminan en 1–4 min; el techo solo pesa si alguna se traba).
- **Qué mide:** el costo de la arquitectura sin obstáculos (H2): tres waypoints en L a −10 m, campo despejado.
- **Qué se espera:** tiempo `reactive` < `fsm` < `slm`; sin diferencias de seguridad.
- **Invalida el lote:** cualquier fallo de misión. Sin obstáculos, un fallo es un problema del sistema
  (percepción, guiado o infraestructura), no del escenario.

### Lote 2 — `townsim_clear` (Tier 1, control)

- **Nivel UE:** TownSim. **Celdas:** 3. **Corridas:** 30. **Presupuesto:** 1200 s / 6000 ciclos. **Plan de ruta:** vlm.
- **Semillas:** 31 37 41 43 47 53 59 61 67 71. **Tiempo:** ~3 h (corridas de 4–7 min).
- **Qué mide:** el mismo costo (H2) en crucero largo por un perímetro urbano con vegetación y edificios bajos.

### Lote 3 — `townsim_ini` (Tier 1, vegetación; lote D de §10.12.2)

- **Nivel UE:** TownSim. **Celdas:** 4. **Corridas:** 40. **Presupuesto:** 1200 s / 6000 ciclos. **Plan de ruta:** vlm.
- **Semillas:** 73 79 83 89 97 101 103 107 109 113. **Tiempo:** ≤ 11.5 h.
- **Qué mide:** cruce del corredor peatonal arbolado a nivel de calle; la obstrucción es un dosel, no un
  muro. El manifiesto incluye WP_0b y WP_1b (evitan la copa de la plaza y la moldura del edificio oeste).
- **Piloto (`-Pilot`):** el dron cruza el corredor arbolado.

### Lote 4 — `townsim_calib_cruce_frontal` (Tier 1, bloqueo frontal; lote E de §10.12.2)

- **Nivel UE:** TownSim. **Celdas:** 4. **Corridas:** 40. **Presupuesto:** 1200 s / 6000 ciclos. **Plan de ruta:** vlm.
- **Semillas:** 127 131 137 139 149 151 157 163 167 173. **Tiempo:** ≤ 14 h.
- **Qué mide:** rodeo de un edificio que bloquea la recta entre waypoints (bloqueo frontal masivo).
- **Piloto (`-Pilot`):** el dron rodea el edificio o al menos lo bordea.
- **Atención:** es el único escenario que nunca voló con la configuración actual; el piloto es su primer dato.

### Lote 5 — `citysim_clear` (Tier 2, control)

- **Nivel UE:** CitySim. **Celdas:** 3. **Corridas:** 30. **Presupuesto:** 1200 s / 6000 ciclos. **Plan de ruta:** vlm.
- **Semillas:** 179 181 191 193 197 199 211 223 227 229. **Tiempo:** ~2 h (corridas de ~3 min).
- **Qué mide:** el costo de la arquitectura (H2) entre edificios altos, con cambios de altitud en cada tramo.
- **Ruta:** 4 waypoints, ~420 m, perímetro de una manzana con altitud creciente en rampa (−10, −30, −50 m) y
  retorno a −10 m (§10.3.3).

### Lote 6 — `citysim_pilot` (Tier 2, rodeo de manzanas; lote F de §10.12.2)

- **Nivel UE:** CitySim. **Celdas:** 4. **Corridas:** 40. **Presupuesto:** 1200 s / 6000 ciclos. **Plan de ruta:** vlm.
- **Semillas:** 233 239 241 251 257 263 269 271 277 281. **Tiempo:** ≤ 12 h.
- **Qué mide:** rodeo de manzanas y elección de corredor; el manifiesto incluye WP_0_SUR (evita la autopista elevada).
- **Piloto (`-Pilot`):** el dron alcanza WP_0_SUR y WP_1 sin quedar trabado sobre la autopista.

## Requisitos antes de cada lote

1. Árbol commiteado (si no, el runner aborta con código 2).
2. El nivel de UE del escenario abierto en Unreal. Correr juntos solo los lotes del mismo nivel:
   1 | 2, 3, 4 | 5, 6.
3. Lotes 2 a 6: Ollama en `127.0.0.1:11434` para el plan de ruta con el VLM (`startOllama.ps1`); el script lo
   verifica. El plan se calcula una vez por escenario, antes de la primera corrida, sobre el mapa cenital
   registrado con el mundo (`citysim_ortho.png`, `townsim_ortho.png`); durante el vuelo el VLM no corre.
4. Lotes 3, 4 y 6: correr y revisar el piloto antes del lote. Un piloto que no cumple su criterio indica una
   regresión que se diagnostica antes de lanzar.

## Uso

Desde esta carpeta, en PowerShell:

```powershell
.\run_lote3_townsim_ini.ps1 -Pilot    # piloto -> airsim-runs\produccion\v4\pilotos\lote3_townsim_ini
.\run_lote3_townsim_ini.ps1           # lote completo
.\run_lote3_townsim_ini.ps1 -Resume   # reanudar un lote cortado (saltea corridas validas ya hechas)
.\run_lotes.ps1 -Lotes 3,4            # varios lotes del mismo nivel de UE
```

Opciones: `-Pilot`, `-Resume`, `-SeedJitter`, `-NoVideo`; en `run_lotes.ps1` además `-OutRoot` y `-Python`.

Salida por corrida: `airsim-runs/produccion/v4/loteN_<escenario>/<escenario>/<brazo>/<estrategia>/seed_<N>_<ts>/`
y un `batch_<ts>.log` por lote.

## Análisis

```powershell
D:\TesisMCD\airsimenv\python.exe ..\airsim-loop\experiments\analyze_lotes.py ..\airsim-runs\produccion\v4 --family 18
```

Escribe `analisis_lotes.md` y dos CSV en `airsim-runs/produccion/v4/`:

- **Por celda:** tasa de éxito con IC de Wilson 95 %; SPL, tiempo de las misiones exitosas y distancia mínima
  al obstáculo (mediana y cuartiles).
- **Comparaciones primarias, tres por lote:**
  - lotes con `fsm:blind` (3, 4, 6): `slm:depth` vs `fsm:blind`, `fsm:depth` vs `fsm:blind`,
    `slm:depth` vs `fsm:depth`, sobre SPL;
  - lotes de 3 brazos (1, 2, 5): `slm`–`fsm`, `slm`–`reactive`, `fsm`–`reactive`, sobre el tiempo de las
    misiones exitosas.
  Delta de Cliff con IC bootstrap y prueba de permutación exacta sobre rangos (Mann-Whitney exacto con
  empates). Bonferroni sobre 18 comparaciones (α = 0.0028).
- **Secundarias, sin corrección:** éxito (Fisher exacto y diferencia de tasas con IC de Newcombe) y distancia
  mínima.
- **Descartes (§10.12.2):** otro `code_version`, sufijo `-dirty`, menos de 50 ciclos; los pilotos no entran.

Con K = 10, la separación perfecta da p = 1.1 × 10⁻⁵ y pasa la corrección; con K = 5, el p mínimo posible
(0.0079) no pasaría nunca.
