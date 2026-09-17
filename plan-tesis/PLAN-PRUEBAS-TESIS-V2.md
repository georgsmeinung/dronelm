# Plan de Pruebas — Corridas de Tesis V2

> **Versión:** 2026-09-16 (v2.0)
> **Referencia metodológica:** `informe/10-METODOLOGIA-EXPERIMENTAL.md`
> **Resultados destino:** `informe/11-RESULTADOS.md` §11.3 – §11.5
> **Predecesor:** `PLAN-PRUEBAS-TESIS.md` (lote base clear completo — 45 corridas, 5 semillas × 3 brazos × 3 tiers)
> **Origen del V2:** mejoras de Zona 1 (simplificación de control) y Zona 2 (percepción real + memoria histórica) implementadas entre 2026-09-07 y 2026-09-11 — ver `PLAN-MEJORAS-4.md` fases I0–I7.

---

## Motivación

El lote base (PLAN-PRUEBAS-TESIS §2–4) completó los 45 runs en escenarios despejados. El código actual incorpora mejoras sustanciales que cambian el comportamiento observable del brazo `slm` **en presencia de obstáculos**:

| Módulo nuevo/modificado | Qué cambia en el comportamiento |
|---|---|
| **V4** — Depth Anything V2 Metric (`DepthEstimator`) | Freno proactivo a ≤5 m por profundidad monocular, sin esperar obstrucción de flujo óptico |
| **E2** — Clasificación de textura de profundidad | Hint táctico "follaje" / "superficie plana" → el SLM puede distinguir árbol de muro |
| **C1** — Evasión lateral con memoria de trayectoria | `eff_occ` penalizado para lados con historial de stall ≥60% — no repite la dirección fallida |
| **D1** — GIRAR_90 con historia de zonas | Invierte el bearing si la zona destino tiene stall ≥70% — evita girar al lado ya bloqueado |
| **F1** — Corner injection en escape deliberativo | Reduce offset a 3 m cuando ambos lados tienen historial de bloqueo |
| **Override 3/3a** (`_apply_trajectory_overrides`) | Anula MANTENER_RUMBO con progreso <0.28 m/ciclo o altitud <5 m bajo techo, forzando evasión |
| **G1** — Detección de muro invisible | Warning al SLM cuando frente_stall ≥20% con occ <15% (obstáculo de baja textura) |
| **Zona 1** — Señal `stuck_invisible` unificada; V2 proactivo eliminado | Menos falsos positivos de percepción; menor carga de tokens innecesarios |

Estas mejoras son irrelevantes en escenarios despejados (los 45 runs base no los ejercen). **Son necesarias corridas con obstáculos reales bajo el código V2 para:**

1. Validar que las mejoras resuelven los atascos observados en corridas piloto (corridas de septiembre-11 con seed 1 mostraban drone atascado en ESCANEO 691 ciclos).
2. Llenar `§11.3` (escenarios con obstrucción Tier 1) y `§11.4` / `§11.5` (Tier 2 con corredores) del cap. 11.
3. Generar la comparación estadística principal de la tesis: SPL `slm` vs. `fsm` vs. `reactive` ante obstáculos reales.

---

## Índice

1. [Prerequisitos y versión de código](#1-prerequisitos)
2. [Lote D — Tier 1 con vegetación (`townsim_ini`)](#2-lote-d)
3. [Lote E — Tier 1 bloqueo frontal (`townsim_calib_cruce_frontal`)](#3-lote-e)
4. [Lote F — Tier 2 corredores (`citymap_pilot`)](#4-lote-f)
5. [Métricas V2 adicionales](#5-metricas-v2)
6. [Verificación de integridad post-lote](#6-verificacion)
7. [Análisis estadístico y mapa de §11](#7-analisis-y-mapa-11)
8. [Orden de ejecución recomendado](#8-orden)

---

## 1. Prerequisitos

### 1.1 Versión de código base para V2

Antes de ejecutar cualquier lote, registrar el hash del commit actual:

```bash
git rev-parse HEAD
```

Todo `summary.json` de este lote debe tener este `code_version`. Si durante la sesión se hace algún commit, **detener el lote activo, verificar el hash, y continuar solo si el commit no modifica código de vuelo** (solo docs/scripts de análisis son seguros).

Código mínimo requerido: commit que incluye `_apply_trajectory_overrides` en `deliberative.py` y `_finalize()` (sesión del 2026-09-11).

### 1.2 Checklist de entorno (ejecutar antes de cada lote)

- [ ] Proyecto UE del tier correspondiente lanzado y en estado `idle`.
- [ ] Servidor VLM respondiendo: `GET {LOCAL_LLM_URL}/models` devuelve 200.
- [ ] `DEPTH_BRAKE_M=5.0` activo: verificar en logs que `DepthEstimator` inicializa sin error.
- [ ] Ningún proceso Python de corridas anteriores activo.
- [ ] Directorio de salida creado bajo `airsim-runs/produccion/v2/`.

```bash
# Verificar DepthEstimator activo
cd airsim-loop
python -c "from src.airsim_loop.depth_estimator import DepthEstimator; d=DepthEstimator(); print('OK', d._brake_m)"
```

### 1.3 Condición de descarte de corrida

Una corrida individual se descarta (no entra al análisis) si:

- `code_version` difiere del hash de referencia del lote.
- El log muestra `DepthEstimator` deshabilitado o con error de inicialización al inicio de la corrida.
- `total_cycles < 50` (corrida abortada por error de infraestructura, no por el drone).

Las corridas descartadas se documentan en la carpeta `airsim-runs/produccion/v2/DESCARTE.md` con motivo.

---

## 2. Lote D — Tier 1 con vegetación (`townsim_ini`)

**Proyecto UE:** TownSim (`townsim_calib.png`)
**Escenario:** `townsim_ini.json` — vuelta al perímetro cruzando el interior del complejo con corredores vegetados. Obstáculos primarios: árboles y follaje de textura difusa.
**Hipótesis ejercidas:** H1 (el SLM mejora la navegación ante obstáculos reales), H2 (el overhead del SLM se justifica cuando hay obstáculos a resolver).
**Mejoras V2 que se ejercen aquí:** E2 (hint "follaje"), C1 (no repetir lado bloqueado por vegetación), G1 (detección de muro invisible), Override 3 (progreso nulo).

### 2.1 Celdas

| Brazo | Semillas | Total |
|---|---|---|
| `slm` | 1 2 3 4 5 | 5 |
| `fsm` | 1 2 3 4 5 | 5 |
| `reactive` | 1 2 3 4 5 | 5 |
| **Total** | | **15** |

### 2.2 Piloto de validación pre-lote (seed=99)

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_ini.json \
  --arms slm \
  --deadlock-strategies deep_vlm \
  --seeds 99 \
  --out-dir ../airsim-runs/produccion/v2/tier1_ini/pilot \
  --max-cycles 4500 --max-seconds 900
```

Criterio de pase: `success=True`, Override 3 disparó al menos una vez (verificar en logs `[TRAJ-OVERRIDE-3]`), `deep_scan_resolution_rate > 0`.

### 2.3 Comando de ejecución

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_ini.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/v2/tier1_ini \
  --max-cycles 4500 --max-seconds 900
```

### 2.4 Presupuesto

| Parámetro | Valor | Justificación |
|---|---|---|
| `--max-seconds` | 900 s | Base de `townsim_clear` ~296 s `slm`; margen 3× por atascos esperados con vegetación. |
| `--max-cycles` | 4500 | A 5 Hz. |
| Tiempo estimado | ~2.0–2.5 h | 15 corridas × promedio ~8–10 min (obstáculos aumentan duración). |

### 2.5 Alertas

| Condición | Acción |
|---|---|
| `success=0/5` en `reactive` | Manifiesto inválido o escenario no alcanzable sin deliberación — re-validar. |
| `deep_scan_events = 0` en todas las corridas `slm` | Override 3 / deep_scan no disparó — verificar `DEADLOCK_STRATEGY=deep_vlm`. |
| `slm` tarda más que `fsm` Y más que `reactive` en media | Regresión en Zona 1 o profundidad generando falsos frenos — revisar logs `depth_proximity_m`. |

---

## 3. Lote E — Tier 1 bloqueo frontal (`townsim_calib_cruce_frontal`)

**Proyecto UE:** TownSim (`townsim_calib.png`)
**Escenario:** `townsim_calib_cruce_frontal.json` — WP cruza directamente una fachada de edificio. Obstáculo primario: muro de baja textura (poca activación de flujo óptico).
**Hipótesis ejercidas:** H1 (resolución de bloqueo con información semántica), H3 (SPL: ¿el SLM encuentra el corredor correcto?).
**Mejoras V2 que se ejercen aquí:** G1 (muro invisible: occ<15% + stall≥20%), D1 (GIRAR_90 no repite el lado bloqueado), F1 (corner offset reducido a 3 m cuando ambos lados probados), Override 3 (progreso nulo ante muro).

### 3.1 Celdas

| Brazo | Semillas | Total |
|---|---|---|
| `slm` | 1 2 3 4 5 | 5 |
| `fsm` | 1 2 3 4 5 | 5 |
| `reactive` | 1 2 3 4 5 | 5 |
| **Total** | | **15** |

### 3.2 Piloto de validación pre-lote (seed=99)

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_calib_cruce_frontal.json \
  --arms slm \
  --deadlock-strategies deep_vlm \
  --seeds 99 \
  --out-dir ../airsim-runs/produccion/v2/tier1_cruce/pilot \
  --max-cycles 4500 --max-seconds 900
```

Criterio de pase: el drone llega al WP tras el edificio o al menos lo rodea (no termina por timeout en el lado de entrada); `[G1]` o `[TRAJ-OVERRIDE-3]` visibles en log.

### 3.3 Comando de ejecución

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_calib_cruce_frontal.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/v2/tier1_cruce \
  --max-cycles 4500 --max-seconds 900
```

### 3.4 Presupuesto

| Parámetro | Valor | Justificación |
|---|---|---|
| `--max-seconds` | 900 s | Bloqueos frontales pueden tomar hasta 5+ minutos en resolver. |
| `--max-cycles` | 4500 | A 5 Hz. |
| Tiempo estimado | ~2.0–3.0 h | 15 corridas × promedio ~9–12 min. |

### 3.5 Alerta crítica

| Condición | Acción |
|---|---|
| `deadlock_events = 0` en ≥80% de corridas `slm` | La fachada no se detecta como obstáculo — re-validar manifiesto (WP frontal real al edificio). |
| `success = 0/5` en los 3 brazos | El bloqueo es impenetrable — reducir `CORNER_OFFSET_M` o verificar que `citymap_pilot.json` no interfiere. |

---

## 4. Lote F — Tier 2 corredores (`citymap_pilot`)

**Proyecto UE:** CitySim (`citysim_calib.png`)
**Escenario:** `citymap_pilot.json` — 7 WPs en grilla urbana a −10 m entre edificios de 50–100 m. El escape por altura no es viable. Obstáculos: fachadas de alta densidad, esquinas de manzana, callejones.
**Hipótesis ejercidas:** H1 (el SLM distingue pasillos navegables), H3 (SPL máximo del dataset — mayor potencia discriminativa).
**Mejoras V2 que se ejercen aquí:** Override 3a (altitud baja bajo techo → PERDER_ALTURA), C1 (historial lateral en callejones), D1+F1 (navegación de esquinas con historia), G1 (muros de baja textura urbanos).

### 4.1 Celdas

| Brazo | Semillas | Total |
|---|---|---|
| `slm` | 1 2 3 4 5 | 5 |
| `fsm` | 1 2 3 4 5 | 5 |
| `reactive` | 1 2 3 4 5 | 5 |
| **Total** | | **15** |

### 4.2 Piloto de validación pre-lote (seed=99)

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/citymap_pilot.json \
  --arms slm \
  --deadlock-strategies deep_vlm \
  --seeds 99 \
  --out-dir ../airsim-runs/produccion/v2/tier2_pilot/pilot \
  --max-cycles 5000 --max-seconds 1200
```

Criterio de pase: el drone avanza al menos 2 WPs sin colisión. Tasas de éxito <5/5 en el lote completo son esperadas y científicamente válidas.

### 4.3 Comando de ejecución

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/citymap_pilot.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 1 2 3 4 5 \
  --out-dir ../airsim-runs/produccion/v2/tier2_pilot \
  --max-cycles 5000 --max-seconds 1200
```

### 4.4 Presupuesto

| Parámetro | Valor | Justificación |
|---|---|---|
| `--max-seconds` | 1200 s | 20 min: corrida más larga esperada. Override 3a necesita múltiples ciclos para activar. |
| `--max-cycles` | 5000 | A 5 Hz. |
| Tiempo estimado | ~4.0–5.0 h | 15 corridas × promedio ~16–20 min. |

### 4.5 Extensión K=10 (opcional, alta potencia estadística)

Con K=5 ninguna comparación alcanza significancia con Bonferroni salvo separación perfecta. Si los resultados de Lote E y Lote F muestran separación parcial, ejecutar 5 seeds adicionales (6–10) en `townsim_calib_cruce_frontal` y `citymap_pilot`:

```bash
cd airsim-loop
python experiments/runner.py \
  --scenarios ../airsim-plan/missions/flightplans/townsim_calib_cruce_frontal.json \
               ../airsim-plan/missions/flightplans/citymap_pilot.json \
  --arms slm fsm reactive \
  --deadlock-strategies deep_vlm \
  --seeds 6 7 8 9 10 \
  --out-dir ../airsim-runs/produccion/v2/extended_k10 \
  --max-cycles 5000 --max-seconds 1200
```

Tiempo adicional: ~6–8 h (30 corridas adicionales × 2 escenarios).

---

## 5. Métricas V2 adicionales

Además de las métricas base (éxito, duración, SPL, colisiones, deliberation\_rate), el CSV y JSONL V2 incluyen columnas nuevas. Verificar que `analyze_tesis_results.py` las lee del CSV antes del primer análisis.

### 5.1 Nuevas columnas CSV (`ctrl_*` y `field_source`)

| Columna | Descripción | Análisis sugerido |
|---|---|---|
| `ctrl_depth_proximity_m` | Profundidad Depth Anything V2 en el momento del freno | Distribución — cuántas veces la profundidad fue el sensor decisivo |
| `ctrl_depth_obstacle_type` | Clasificación de textura: "follaje" / "superficie plana" / "desconocido" | Frecuencia por tipo de escenario (follaje esperado en townsim_ini) |
| `ctrl_traj_frente_stall_rate` | Tasa de stall en zona frontal acumulada al final de la corrida | Correlación con duración y número de deadlocks |
| `ctrl_traj_izq_stall_rate` | Tasa de stall en zona izquierda | Evidencia de que C1 penalizó el lado más bloqueado |
| `ctrl_traj_der_stall_rate` | Tasa de stall en zona derecha | Ídem |
| `field_source` | Fuente del campo de obstáculos: "flujo óptico" / "flujo óptico + profundidad monocular" | Fracción de ciclos donde la profundidad contribuyó |

### 5.2 Nuevas columnas JSONL (sub-objeto `perception`)

Los campos `stuck_invisible`, `imu_contact`, `blind_wall`, `depth_proximity_m`, `depth_obstacle_type`, `depth_below_cycles` en el sub-objeto `perception` de cada evento JSONL permiten reconstruir la cadena causal de cada deadlock. El script `analyze.py` ya los extrae; confirmar con:

```bash
cd airsim-loop
python experiments/analyze.py \
  --jsonl ../airsim-runs/produccion/v2/tier1_cruce/slm/seed_1.jsonl \
  --show-perception
```

### 5.3 Métrica de validación de Override 3 (`traj_override_events`)

Extraer del log la frecuencia con que Override 3/3a disparó:

```bash
grep -c "\[TRAJ-OVERRIDE-3\]" airsim-runs/produccion/v2/tier1_cruce/slm/seed_1.jsonl
```

Si `traj_override_events > 0` en la mayoría de corridas con obstáculos, el mecanismo está activo. Incluir en §11.3 como validación cualitativa del módulo.

---

## 6. Verificación de integridad post-lote

### 6.1 Script de verificación V2

```bash
# Contar corridas completadas por lote
$dirs = @("v2/tier1_ini", "v2/tier1_cruce", "v2/tier2_pilot")
foreach ($d in $dirs) {
  $n = (Get-ChildItem "airsim-runs/produccion/$d" -Recurse -Filter "*.summary.json").Count
  Write-Host "$d : $n corridas"
}

# Verificar code_version uniforme en V2
python -c "
import json, glob
for lote in ['v2/tier1_ini', 'v2/tier1_cruce', 'v2/tier2_pilot']:
    files = glob.glob(f'airsim-runs/produccion/{lote}/**/*.summary.json', recursive=True)
    if not files:
        print(f'{lote}: sin archivos')
        continue
    versions = set(json.load(open(f))['code_version'] for f in files)
    status = 'OK' if len(versions) == 1 else 'MEZCLA'
    print(f'{status} {lote}: {versions}')
"

# Tasa de éxito por brazo y lote
python -c "
import json, glob
for lote in ['v2/tier1_ini', 'v2/tier1_cruce', 'v2/tier2_pilot']:
    files = glob.glob(f'airsim-runs/produccion/{lote}/**/*.summary.json', recursive=True)
    for arm in ['slm', 'fsm', 'reactive']:
        arm_files = [f for f in files if f'/{arm}/' in f or f'\\\\{arm}\\\\' in f]
        if not arm_files: continue
        s = sum(1 for f in arm_files if json.load(open(f)).get('success'))
        print(f'{lote}/{arm}: {s}/{len(arm_files)}')
"
```

### 6.2 Condiciones de invalidación de lote

1. Corridas con `code_version` distinto dentro del mismo lote → descartar las corridas no coincidentes y completar con nuevas.
2. `depth_proximity_m` = 0 en todos los eventos de todas las corridas `slm` → `DepthEstimator` deshabilitado durante la corrida — reflejar en §6.3.
3. Cualquier colisión en Lote D (townsim_ini) con `reactive` → posible colisión de spawn, no de obstáculo; documentar pero no descartar el lote.

---

## 7. Análisis estadístico y mapa de §11

### 7.1 Script de análisis V2

```bash
cd airsim-loop
python experiments/analyze_tesis_results.py \
  --batch-dir ../airsim-runs/produccion/v2 \
  --out ../airsim-runs/produccion/v2/analysis \
  --include-perception-cols
```

Verificar que el script genera `RESULTS_SUMMARY_V2.json`, tablas de SPL por escenario, y la comparación Mann-Whitney + Cliff's Delta para el par `slm` vs. `fsm` y `slm` vs. `reactive`.

### 7.2 Mapa de placeholders en §11 — qué llena cada lote V2

| Sección §11 | Datos necesarios | Lote V2 |
|---|---|---|
| **§11.3** Tier 1 con vegetación — tabla 5 semillas | Lote D (`townsim_ini`) | D |
| **§11.3** Tier 1 bloqueo frontal — tabla 5 semillas | Lote E (`townsim_calib_cruce_frontal`) | E |
| **§11.4** Tier 2 corredores — tabla 5 semillas | Lote F (`citymap_pilot`) | F |
| **§11.5** Comparación estadística (Mann-Whitney, Cliff's Delta) por escenario con obstáculos | Lotes D + E + F | D+E+F |
| **§11.5** Validación cualitativa Override 3 | `traj_override_events` de Lote E | E |
| **§11.5** Validación cualitativa G1 / profundidad | `depth_obstacle_type`, `field_source` de Lotes D+E | D+E |

### 7.3 Tablas para §11.3 (estructura de referencia)

Para cada escenario con obstáculos, incluir las mismas columnas que §11.1 más las columnas V2:

| Brazo | Éxito | Duración media (s) | σ (s) | SPL media | σ SPL | Deadlocks | `depth_proximity_m` media | Override-3 disparos | Colisiones |
|---|---|---|---|---|---|---|---|---|---|
| `slm` | | | | | | | | | |
| `fsm` | | | | | | | | | |
| `reactive` | | | | | | | | | |

*SPL = (dist_óptima / max(dist_recorrida, dist_óptima)) × success* — ya implementado en `analyze.py`.

### 7.4 Comparación con lote base

Calcular el **factor de costo adicional por obstáculo**:

```
costo_obstáculo_slm = duración_media(escenario_obstáculo) / duración_media(escenario_clear_tier)
```

Comparar con `fsm` y `reactive`. Si `costo_obstáculo_slm < costo_obstáculo_fsm`, la hipótesis H1 tiene soporte empírico.

---

## 8. Orden de ejecución recomendado

```
PREPARACIÓN (~30 min)
────────────────────────────────────────────────────────────────────────────
[0] git rev-parse HEAD → anotar como CODE_VERSION_V2                [~2 min]
[0] Verificar DepthEstimator activo (§1.2)                          [~5 min]

LOTE V2 CON OBSTÁCULOS (~7.5 – 10.5 h total)
────────────────────────────────────────────────────────────────────────────
[1] TownSim activo
    → Piloto Lote D (seed=99, townsim_ini, brazo slm)               [~15 min]
    → Lote D completo (15 corridas, townsim_ini)                    [~2.0 h]

[2] Verificación Lote D (§6.1 parcial)                             [~10 min]

[3] TownSim activo (puede ser la misma sesión)
    → Piloto Lote E (seed=99, townsim_calib_cruce_frontal)          [~20 min]
    → Lote E completo (15 corridas, townsim_calib_cruce_frontal)   [~2.5 h]

[4] Verificación Lote E (§6.1 parcial)                             [~10 min]

[5] CitySim activo
    → Piloto Lote F (seed=99, citymap_pilot, brazo slm)             [~25 min]
    → Lote F completo (15 corridas, citymap_pilot)                  [~4.5 h]

[6] Verificación de integridad completa (§6.1)                      [~20 min]

ANÁLISIS Y ACTUALIZACIÓN DEL INFORME (~2 h)
────────────────────────────────────────────────────────────────────────────
[7] Ejecutar analyze_tesis_results.py con --include-perception-cols [~15 min]

[8] Llenar §11.3 con datos de Lotes D y E                          [~30 min]

[9] Llenar §11.4 con datos de Lote F                               [~20 min]

[10] Escribir §11.5: comparación estadística + conclusión H1/H2/H3 [~45 min]

EXTENSIÓN OPCIONAL (si tiempo y resultados lo justifican)
────────────────────────────────────────────────────────────────────────────
[11] K=10 en Lotes E + F (seeds 6–10) — solo si §11.5 muestra      [~7 h]
     separación parcial sin significancia formal

[12] Barrido de velocidad en MiniSim (§5.4 del plan original)       [~2 h]
```

---

## Apéndice — Relación con capítulos del informe

| Capítulo | Depende de lote V2 | Contenido a actualizar |
|---|---|---|
| **10 — Metodología** | — | Agregar descripción de mejoras V2 como variable de versión de software; declarar `CODE_VERSION_V2` como corte de datos para §11.3–11.5 |
| **11 — Resultados** | D, E, F | §11.3 (obstáculos Tier 1), §11.4 (corredores Tier 2), §11.5 (análisis estadístico completo con H1) |
| **12 — Conclusiones** | D, E, F | Respaldar o refutar H1 con evidencia cuantitativa real |
| **08 — Decisiones SLM** | D, E | Citar ejemplos de G1 / Override 3 en corridas reales como evidencia de que el módulo deliberativo interviene de forma causal |
