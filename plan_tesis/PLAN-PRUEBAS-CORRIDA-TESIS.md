# Plan de Pruebas — Corridas de Tesis

> **Versión:** 2026-09-08 (rev. 3)  
> **Referencia metodológica:** `informe/10-METODOLOGIA-EXPERIMENTAL.md`  
> **Resultados destino:** `informe/11-RESULTADOS.md`  
> **Estado del lote piloto:** corridas de una semilla completas para Tier 0, Tier 1 base y Tier 2 base.  
> **Pendiente:** lote estadístico completo (≥5 semillas, análisis Mann-Whitney).

---

## Sobre los tres lotes base

Los **tres lotes base** son un escenario de control por tier. Todas las corridas usan el mecanismo `deep_vlm` (única configuración de producción).

| Lote | Tier | Escenario | Rol |
|---|---|---|---|
| A | 0 — MiniSim | `minisim_clear` | Control sin obstáculos, costo puro de deliberación |
| B | 1 — TownSim | `townsim_clear` | Control de crucero largo, dilución del costo |
| C | 2 — CitySim | `citysim_clear` | Control a altitud franca, patrón climb-first |

Los escenarios con obstrucción real (`townsim_ini`, `townsim_calib_cruce_frontal`, `citymap_pilot`) son **pruebas extendidas** (§6).

**Volumen total del lote base:**

| Lote | Escenario | Corridas | Tiempo estimado |
|---|---|---|---|
| A — Tier 0 | `minisim_clear` | 15 | ~1.2 h |
| B — Tier 1 | `townsim_clear` | 15 | ~1.5 h |
| C — Tier 2 | `citysim_clear` | 15 | ~1.0 h |
| **Total base** | | **45** | **~3.7 h** |

**Criterio de éxito:** todos los `*.summary.json` comparten `code_version`; tasa de éxito 5/5 en los tres brazos.

---

## Índice

1. [Prerequisitos de entorno](#1-prerequisitos)
2. [Lote A — Tier 0 (MiniSim)](#2-lote-a--tier-0-minisim)
3. [Lote B — Tier 1 (TownSim)](#3-lote-b--tier-1-townsim)
4. [Lote C — Tier 2 (CitySim)](#4-lote-c--tier-2-citysim)
5. [Pruebas extendidas](#5-pruebas-extendidas)
6. [Verificación de integridad post-lote](#6-verificacion-de-integridad)
7. [Mapa de placeholders en §11 por corrida](#7-mapa-de-placeholders)
8. [Orden de ejecución recomendado](#8-orden-de-ejecucion)

---

## 1. Prerequisitos

### 1.1 Checklist de entorno (ejecutar antes de cada lote)

- [ ] Proyecto UE del tier correspondiente lanzado y en estado `idle`.
- [ ] Servidor de inferencia VLM respondiendo: `GET {LOCAL_LLM_URL}/models` devuelve 200.
- [ ] Ningún proceso Python de corridas anteriores activo.
- [ ] Directorio de salida creado: `airsim-runs/produccion/tier<N>/`.
- [ ] `code_version` anotada antes de empezar: `git rev-parse HEAD`.
- [ ] Manifiesto de misión verificado visualmente en el viewport de UE con `scripts/plot_mission_route.py`.

### 1.2 Manifiesto `citysim_clear.json` — acción requerida antes del Lote C

> **BLOQUEANTE para Lote C.** El archivo `airsim-plan/missions/flightplans/citysim_clear.json` contiene actualmente una variante de 4 waypoints con altitud máxima de −50 m que ya falló por colisión. Debe restaurarse al manifiesto de 7 waypoints a −70 m con el que se obtuvieron los resultados piloto exitosos (2026-09-07).

Las coordenadas no se derivan del mapa PNG — provienen de la corrida piloto ya volada. Dos vías para recuperarlas:

```bash
# Opción 1: recuperar desde git
git log --oneline -- airsim-plan/missions/flightplans/citysim_clear.json
git show <commit-hash>:airsim-plan/missions/flightplans/citysim_clear.json \
  > airsim-plan/missions/flightplans/citysim_clear.json

# Opción 2: extraer del summary.json del piloto exitoso (2026-09-07)
# campo: waypoints o similar según el logger
```

Después de restaurar: `python scripts/plot_mission_route.py --plan citysim_clear.json` y confirmar en viewport que el ascenso es vertical puro y la altitud máxima es −70 m.

### 1.3 Política de cuarentena de datos

Ninguna corrida con `code_version` anterior al 2026-09-03 entra al análisis estadístico. Los tres artefactos instrumentales corregidos en esa fecha afectan directamente lo que el modelo ve.

---

## 2. Lote A — Tier 0 (MiniSim)

**Proyecto UE:** MiniSim (`crater.png`)  
**Escenario:** `minisim_clear` — 3 WPs en L, ~191 m, −10 m, terreno abierto.  
**Hipótesis:** H2 (costo puro del VLM sin beneficio compensatorio), H3 (cota inferior en entorno despejado).

### 2.1 Celdas

| Brazo | Semillas | Total |
|---|---|---|
| `slm` | 5 | 5 |
| `fsm` | 5 | 5 |
| `reactive` | 5 | 5 |
| **Total** | | **15** |

### 2.2 Piloto de validación pre-lote

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/minisim_clear.json \
  --arms slm \
  --deadlock-strategies deep_vlm \
  --seeds 99 \
  --out-dir ../airsim-runs/produccion/tier0/pilot_validation \
  --max-cycles 2400 --max-seconds 480
```

Criterio de pase: `success=True`, 0 colisiones.

### 2.3 Comando de ejecución

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/minisim_clear.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier0 \
  --max-cycles 2400 \
  --max-seconds 480
```

### 2.4 Presupuesto

| Parámetro | Valor | Justificación |
|---|---|---|
| `--max-seconds` | 480 s | Piloto `slm` completó en 235 s. Margen >2×. |
| `--max-cycles` | 2400 | A 5 Hz: 480 s = 2400 ciclos. |
| Tiempo total estimado | ~1.2 h | 15 corridas × promedio ~5 min. |

### 2.5 Métricas a registrar

| Métrica | Campo | Tabla §11 |
|---|---|---|
| Éxito | `success` | §11.1, §11.2 |
| Ciclos totales | `total_cycles` | §11.1 |
| Duración (s) | `flight_duration_s` | §11.1 |
| Distancia (m) | `distance_m` | §11.1 |
| Colisiones | `collision_count` | §11.1, §11.2 |
| Invocaciones SLM | `slm_invocations` | §11.1 |
| Tasa de deliberación | `deliberation_rate` | §11.1 |
| Fallback SLM | `slm_fallback_rate` | §11.1 |
| Deadlocks | `deadlock_events` | §11.1 |
| Res. atasco VLM | `deep_scan_resolution_rate` | §11.1 |
| Dist. mín. obstáculo (p5) | `min_obstacle_dist_m` | §11.1, §11.2 |
| SPL | calculado en `analyze.py` | §11.2 |
| Colisiones/km | calculado | §11.2 |

### 2.6 Resultados esperados y alertas

| Resultado esperado | Condición de alerta |
|---|---|
| Orden tiempo: `reactive` < `fsm` < `slm` | Tasa de éxito < 5/5 → problema de infraestructura |
| Ratio `slm`/`reactive` ≈ 2.5–3.5× (piloto: 2.8×) | `deliberation_rate` > 15% → regresión al estado pre-fix |
| Sin diferencias significativas en `min_obstacle_dist_m` | Diferencias grandes en campo despejado → sesgo instrumental |

---

## 3. Lote B — Tier 1 (TownSim)

**Proyecto UE:** TownSim (`townsim_calib.png`)  
**Escenario:** `townsim_clear` — perímetro completo, 6 WPs, ~640 m, −30 m.  
**Hipótesis:** H2 (dilución del costo con longitud de ruta), H3 (rendimiento en crucero largo).

### 3.1 Celdas

| Brazo | Semillas | Total |
|---|---|---|
| `slm` | 5 | 5 |
| `fsm` | 5 | 5 |
| `reactive` | 5 | 5 |
| **Total** | | **15** |

### 3.2 Piloto de validación pre-lote

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_clear.json \
  --arms slm \
  --deadlock-strategies deep_vlm \
  --seeds 99 \
  --out-dir ../airsim-runs/produccion/tier1/pilot_validation \
  --max-cycles 4500 --max-seconds 900
```

### 3.3 Comando de ejecución

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_clear.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier1 \
  --max-cycles 4500 --max-seconds 900
```

### 3.4 Presupuesto

| Parámetro | Valor | Justificación |
|---|---|---|
| `--max-seconds` | 900 s | Piloto `fsm` completó en 347 s. Margen >2.5×. |
| `--max-cycles` | 4500 | A 5 Hz: 900 s = 4500 ciclos. |
| Tiempo total estimado | ~1.5 h | 15 corridas × promedio ~6 min. |

### 3.5 Métrica clave y alertas

- **Ratio $t_{\text{slm}}/t_{\text{reactive}}$** — métrica central para H2. Piloto: 1.17×; debe caer respecto del 2.8× de Tier 0.
- **`deliberation_rate` media** — esperado ~0.8–1.5% (piloto: 0.82%). Valores > 5% indican regresión.
- **Alerta:** si `deadlock_events > 0` en ≥3 corridas de cualquier brazo, registrar para análisis pero no alarma — el escenario sigue siendo control válido si la tasa de éxito se mantiene en 5/5.

---

## 4. Lote C — Tier 2 (CitySim)

**Proyecto UE:** CitySim (`citysim_calib.png`)  
**Escenario:** `citysim_clear` — perímetro de manzana, 7 WPs, ~430 m, −70 m, climb-first.  
**Hipótesis:** H2 (ratio más bajo de los tres tiers, piloto: 1.09×), H3 (cota inferior Tier 2).

### 4.1 Celdas

| Brazo | Semillas | Total |
|---|---|---|
| `slm` | 5 | 5 |
| `fsm` | 5 | 5 |
| `reactive` | 5 | 5 |
| **Total** | | **15** |

### 4.2 Prerequisito: recuperar coordenadas del manifiesto (ver §1.2)

### 4.3 Piloto de validación pre-lote

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/citysim_clear.json \
  --arms slm \
  --deadlock-strategies deep_vlm \
  --seeds 99 \
  --out-dir ../airsim-runs/produccion/tier2/pilot_validation \
  --max-cycles 3000 --max-seconds 600
```

### 4.4 Comando de ejecución

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/citysim_clear.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier2 \
  --max-cycles 3000 --max-seconds 600
```

### 4.5 Presupuesto y alertas críticas

| Parámetro | Valor | Justificación |
|---|---|---|
| `--max-seconds` | 600 s | Piloto `fsm` completó en 182 s. Margen >3×. |
| `--max-cycles` | 3000 | A 5 Hz: 600 s = 3000 ciclos. |
| Tiempo total estimado | ~1.0 h | 15 corridas × promedio ~4 min. |

| Condición | Acción |
|---|---|
| Cualquier colisión en cualquier brazo | **Detener el lote.** Manifiesto no restaurado o −70 m no despeja algún edificio. Re-validar en viewport. |
| Tasa de éxito < 5/5 en `reactive` | La ruta cruza algo a −70 m. Re-validar manifiesto. |

---

## 5. Pruebas extendidas

Ordenadas por prioridad. Requieren que el lote base del tier correspondiente haya completado con éxito.

### 5.1 Escenarios con obstrucción real — Tier 1 (alta prioridad)

**`townsim_ini`** — cruza el interior del complejo con corredores vegetados. Primera manifestación esperada de H1. Métrica primaria: SPL. Requiere análisis por waypoint (`summary_by_wp.csv`) para aislar `WP_0_ASCENSO`.

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_ini.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier1 \
  --max-cycles 4500 --max-seconds 900
```

**`townsim_calib_cruce_frontal`** — bloqueo frontal masivo a nivel de calle. Métrica primaria: SPL (calidad de la solución lateral vs. escalada). Alerta: si `deadlock_events = 0` en ≥80% de las corridas, la fachada no está siendo encontrada — re-validar manifiesto.

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_calib_cruce_frontal.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier1 \
  --max-cycles 4500 --max-seconds 900
```

### 5.2 `citymap_pilot` — corredores urbanos angostos (alta prioridad)

Escenario terminal de Tier 2: 7 WPs en grilla urbana a −10 m, entre edificios de 50–100 m. El escape por altura está efectivamente vetado. Mayor potencia discriminativa para H1 y H3. El resultado negativo (VLM no discrimina entre corredores de textura uniforme) es igualmente válido.

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/citymap_pilot.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/tier2 \
  --max-cycles 3000 --max-seconds 600
```

Se esperan tasas de éxito < 5/5 en los tres brazos. Mayor dispersión entre semillas.

### 5.3 Elevación de K=10 en escenarios decisivos (máximo retorno estadístico)

Con K=5 ninguna comparación puede superar el umbral de Bonferroni salvo separación perfecta. K=10 en `townsim_calib_cruce_frontal` y `citymap_pilot` baja el p mínimo alcanzable de 7.9×10⁻³ a 1.1×10⁻⁵.

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_calib_cruce_frontal.json \
               ../airsim-plan/missions/flightplans/citymap_pilot.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 6 7 8 9 10 \
  --out-dir ../airsim-runs/produccion \
  --max-cycles 4500 --max-seconds 900
```

Tiempo adicional estimado: ~6 h (30 corridas adicionales × 2 escenarios).

### 5.4 Barrido de velocidad de crucero — Tier 0 (prioridad media)

Establece la frontera de viabilidad temporal del brazo `slm`: a qué velocidad la latencia del VLM deja de ser absorbible por el avance cauto.

```bash
for speed in 2.0 5.0 7.0; do
  REACTIVE_FORWARD_SPEED=$speed python experiments/runner.py \
    --scenarios ../airsim-plan/missions/flightplans/minisim_clear.json \
    --arms slm reactive \
    --deadlock-strategies deep_vlm \
    --seeds 1 2 3 4 5 \
    --out-dir ../airsim-runs/produccion/extended/speed_v${speed} \
    --max-cycles 2400 --max-seconds 480
done
```

Resultado esperado: ratio $t_{\text{slm}}/t_{\text{reactive}}$ decrece con la velocidad si el costo del VLM es aditivo.

### 5.5 `citymap_a` — corredores con densidad graduada (mayor valor científico)

Traza la curva de degradación de la tasa de éxito en función del ancho del corredor. Estado: **pendiente de construcción** del manifiesto. Coordenadas sólo por vuelo de validación previo, nunca por mapa PNG.

### 5.6 Reproducibilidad entre sesiones (prioridad baja)

```bash
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/minisim_clear.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/extended/reproducibility_s2 \
  --max-cycles 2400 --max-seconds 480
```

Mide el efecto de sesión declarado en §10.5.1 del informe. Valida la comparación entre tiers por razones normalizadas.

---

## 6. Verificación de integridad post-lote

### 6.1 Script de verificación

```bash
# Contar corridas completadas
find airsim-runs/produccion/tier0 -name "*.summary.json" | wc -l   # esperado: 15
find airsim-runs/produccion/tier1 -name "*.summary.json" | wc -l   # esperado: 15
find airsim-runs/produccion/tier2 -name "*.summary.json" | wc -l   # esperado: 15

# Verificar code_version uniforme
python -c "
import json, glob, sys
for tier in ['tier0', 'tier1', 'tier2']:
    files = glob.glob(f'airsim-runs/produccion/{tier}/**/*.summary.json', recursive=True)
    if not files: continue
    versions = set(json.load(open(f))['code_version'] for f in files)
    status = 'OK' if len(versions) == 1 else 'ERROR'
    print(f'{status} {tier}: {versions}')
"

# Verificar tasa de éxito por brazo
python -c "
import json, glob
for tier in ['tier0', 'tier1', 'tier2']:
    files = glob.glob(f'airsim-runs/produccion/{tier}/**/*.summary.json', recursive=True)
    for arm in ['slm', 'fsm', 'reactive']:
        arm_files = [f for f in files if f'/{arm}/' in f]
        if not arm_files: continue
        successes = sum(1 for f in arm_files if json.load(open(f)).get('success'))
        print(f'{tier}/{arm}: {successes}/{len(arm_files)}')
"
```

### 6.2 Análisis estadístico

```bash
cd airsim-loop
python experiments/analyze_tesis_results.py \
  --batch-dir ../airsim-runs/produccion \
  --out ../airsim-runs/produccion/analysis
```

### 6.3 Condiciones de invalidación

1. Corridas con `code_version` distinto dentro del mismo lote.
2. Tasa de éxito = 0/5 en cualquier escenario de control en cualquier brazo.
3. Cualquier colisión en Lote C — indica manifiesto no restaurado.

---

## 7. Mapa de placeholders en §11 por corrida

### §11.1 — Tablas piloto → reemplazar con medias sobre 5 semillas

| Tabla §11.1 | Datos | Lote |
|---|---|---|
| Tier 0 completa | 5 seeds × 3 brazos | A |
| Tier 1 completa | 5 seeds × 3 brazos | B |
| Tier 2 completa | 5 seeds × 3 brazos | C |

### §11.2 — Filas `[pendiente]`

| Fila en §11.2 | Lote |
|---|---|
| `slm / Tier 1 (townsim_ini)` | Extendido §5.1 |
| `fsm / Tier 1 (townsim_ini)` | Extendido §5.1 |
| `reactive / Tier 1 (townsim_ini)` | Extendido §5.1 |
| `slm / Tier 1 (townsim_calib_cruce_frontal)` | Extendido §5.1 |
| `fsm / Tier 1 (townsim_calib_cruce_frontal)` | Extendido §5.1 |
| `reactive / Tier 1 (townsim_calib_cruce_frontal)` | Extendido §5.1 |
| `slm / Tier 2 (citymap_pilot)` | Extendido §5.2 |
| `fsm / Tier 2 (citymap_pilot)` | Extendido §5.2 |
| `reactive / Tier 2 (citymap_pilot)` | Extendido §5.2 |

### §11.3 — Estadísticos del lote completo

| Análisis | Datos necesarios | Disponible tras |
|---|---|---|
| Tabla de ratios `slm`/`reactive` por tier (H2) | Lotes A + B + C | Lote C |
| Mann-Whitney por par, por escenario control | ≥5 semillas, lotes A+B+C | Lote C |
| Cliff's Delta por par | Idem | Lote C |
| Corrección de Bonferroni (18 pruebas) | Todos los lotes + extendidos | Extendidos |

### §11.4 — Análisis por escenario

| Sección §11.4 | Datos necesarios | Lote |
|---|---|---|
| §11.4.1 Tier 0 costo puro | Distribuciones Lote A, `deliberation_rate` | A |
| §11.4.2 Tier 1 crucero largo | Distribuciones Lote B | B |
| §11.4.2 Tier 1 vegetación y bloqueo | §5.1 extendido | Extendidos |
| §11.4.3 Tier 2 control | Distribuciones Lote C | C |
| §11.4.3 Tier 2 corredores | §5.2 extendido | Extendidos |

---

## 8. Orden de ejecución recomendado

```
LOTE BASE (~3.7 h total)
────────────────────────────────────────────────────────────────────────────
[1] Recuperar citysim_clear.json (7 WPs / −70 m) desde git o summary piloto
    → Validar con plot_mission_route.py en viewport CitySim            [~15 min]

[2] MiniSim activo → piloto Lote A (seed=99, 1 corrida slm)           [~10 min]
[3] Lote A completo (15 corridas)                                      [~1.2 h]

[4] TownSim activo → piloto Lote B (seed=99, townsim_clear)           [~15 min]
[5] Lote B completo (15 corridas)                                      [~1.5 h]

[6] CitySim activo → piloto Lote C (seed=99, citysim_clear)           [~10 min]
[7] Lote C completo (15 corridas)                                      [~1.0 h]

[8] Verificación de integridad + análisis parcial (H2 y H3)           [~30 min]
    → Con los 3 lotes base: tabla de ratios, Mann-Whitney en escenarios
      de control, perfil de deliberation_rate vs. tier.

PRUEBAS EXTENDIDAS (en orden de prioridad)
────────────────────────────────────────────────────────────────────────────
[9]  TownSim → townsim_ini + townsim_calib_cruce_frontal (30 corridas) [~3.5 h]
     → Habilita §11.4.2 completo (H1 en vegetación y bloqueo)

[10] CitySim → citymap_pilot (15 corridas)                            [~1.5 h]
     → Habilita §11.4.3 completo (H1 en corredores)

[11] K=10 en townsim_calib_cruce_frontal y citymap_pilot              [~6.0 h]
     → Único camino a significancia estadística formal

[12] Barrido de velocidad (MiniSim)                                   [~2.0 h]
     → Frontera de viabilidad temporal del slm

[13] Reproducibilidad entre sesiones (MiniSim)                        [~1.2 h]
     → Validación del supuesto de comparabilidad entre tiers

[14] citymap_a (pendiente construcción del manifiesto)
```
