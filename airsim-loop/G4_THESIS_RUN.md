# G4: Corrida de Tesis - Guía de Ejecución

## Resumen

G4 ejecuta un experimento factorial: **3 brazos × N escenarios × N semillas**.

- **Brazos**: `slm` (deliberativo), `fsm` (máquina de estados), `reactive` (reactivo)
- **Escenarios**: Misiones con waypoints, organizadas por tier de dificultad (ver plan 2026-0827):
  - Tier 0 (base, `crater.png`/MiniSim): `minisim_clear.json` — debe cerrar en verde antes que el resto.
  - Tier 1 (intermedio, `townsim.png`/TownSim): pendiente de crear (`townsim_pilot.json`, `townsim_a.json`).
  - Tier 2 (complejo, `citymap.png`/CitySim): `citymap_pilot.json` (antes `manhattan_b.json`), pendiente `citymap_a.json`.
  - `manhattan_a.json` queda **descartado** (2026-0827): sus waypoints vienen de un manifiesto que declara `crater.png`, no el mapa urbano que su nombre sugiere.
- **Semillas**: Variables de control para reproducibilidad (default 5: 1-5)

Total de corridas: 3 × 3 × 5 = **45 corridas** (ajustar semillas según disponibilidad)

## Requisitos

- AirSim local corriendo en la máquina Windows
- LM Studio corriendo (si se usa brazo `slm`)
- Misiones disponibles en `missions/` (minisim_clear.json, citymap_pilot.json, etc.)
- Python venv activado: `.venv/Scripts/activate`

## Ejecución

### Opción 1: Corrida Completa (5 semillas)

```bash
cd airsim-loop
python experiments/batch_runner.py \
    --scenarios ../airsim-plan/missions/minisim_clear.json ../airsim-plan/missions/townsim_a.json ../airsim-plan/missions/citymap_pilot.json \
    --arms slm fsm reactive \
    --seeds 1 2 3 4 5 \
    --out-dir runs/tesis \
    --max-cycles 2000 \
    --max-seconds 300
```

Ajustar `--max-seconds`/`--max-cycles` por escenario según la distancia total de sus waypoints y la
velocidad de crucero (ver plan 2026-0827): el presupuesto por defecto de este ejemplo alcanza para los
tres tiers, pero un piloto corto (p. ej. `minisim_clear`) puede correr con un presupuesto menor.

**Tiempo estimado**: ~5-7 horas (45 corridas × 5-8 minutos c/u)

### Opción 2: Prueba Rápida (2 semillas, debug)

```bash
python experiments/batch_runner.py \
    --scenarios ../airsim-plan/missions/minisim_clear.json \
    --arms slm fsm reactive \
    --seeds 1 2 \
    --out-dir runs/tesis_debug \
    --max-cycles 600 \
    --max-seconds 120
```

**Tiempo estimado**: ~20-30 minutos (6 corridas)

### Monitoreo

Durante la ejecución, verá:
```
[1/45] manhattan_a × slm × seed=1... ✓ (45.2s, cycles=254, success=True)
[2/45] manhattan_a × fsm × seed=1... ✓ (52.1s, cycles=289, success=True)
[3/45] manhattan_a × reactive × seed=1... ✓ (38.9s, cycles=218, success=False)
...
[G4] Corrida completada. Resultados en runs/tesis/RESULTS_SUMMARY.json
```

## Post-Procesamiento

### Generar Análisis

```bash
python experiments/analyze_tesis_results.py runs/tesis/
```

Genera:
- `runs/tesis/ANALYSIS.json` (estadísticas consolidadas)
- Tabla de tasas de éxito por brazo
- Análisis de ciclos, duración, colisiones

### Inspeccionar Corrida Individual

```bash
# Ver logs de una corrida específica
less runs/tesis/manhattan_a/slm/seed_1.jsonl

# Ver resumen de una corrida
cat runs/tesis/manhattan_a/slm/seed_1.summary.json | python -m json.tool
```

### Extraer Métricas Clave

```python
# Script ad-hoc para extraer tabla de comparativas
import json
from pathlib import Path

results = json.load(open("runs/tesis/RESULTS_SUMMARY.json"))
for arm in ["slm", "fsm", "reactive"]:
    arm_results = [r for r in results if r["arm"] == arm and r.get("success")]
    print(f"{arm}: {len(arm_results)} éxitos, "
          f"{sum(r['collisions'] for r in arm_results)} colisiones totales")
```

## Estructura de Salida

```
runs/tesis/
├── manhattan_a/
│   ├── slm/
│   │   ├── seed_1.jsonl          # Logs por ciclo
│   │   ├── seed_1.summary.json   # Resumen: cycles, duration, collisions, etc.
│   │   ├── seed_2.jsonl
│   │   └── seed_2.summary.json
│   ├── fsm/
│   └── reactive/
├── manhattan_b/
├── manhattan_c/
├── RESULTS_SUMMARY.json           # Tabla consolidada de todas las corridas
└── ANALYSIS.json                  # Estadísticas por brazo/escenario
```

## Notas Importantes

### Variables de Control

- **MISSION_MAX_SECONDS**: 300s (cierre automático de misión por timeout)
- **MISSION_MAX_CYCLES**: 2000 (cierre automático por ciclos)
- **DEPTH_METRIC_EVERY_N**: 5 (capturar profundidad cada 5 ciclos, solo métricas)
- **LOOP_HZ**: 5.0 (Hz del lazo, ya calibrado en G1.3)

### Troubleshooting

**Problema**: Todas las corridas fallan
- **Causa**: AirSim no está corriendo
- **Solución**: Verificar que AirSim esté abierto y responda (`AIRSIM_IP`/`AIRSIM_PORT` en `.env`)

**Problema**: Brazo `slm` falla inmediatamente
- **Causa**: LM Studio no está corriendo
- **Solución**: Iniciar LM Studio en `http://localhost:11434` o verificar `LOCAL_LLM_URL`

**Problema**: Algunas corridas no generan summary.json
- **Causa**: Crash durante la corrida (revisar stderr del subproceso)
- **Solución**: Ejecutar manualmente esa corrida para debugging

## Análisis de Resultados (Próximo Paso)

Una vez completada G4, los datos están listos para:
1. Comparación de tasas de éxito (slm vs fsm vs reactive)
2. Análisis de desempeño: ciclos, duración, colisiones
3. Validación estadística: t-test entre brazos
4. Escritura de capítulo de resultados en tesis (G6)

Ejemplo de tabla esperada:

| Brazo | Escenario | Éxito | Ciclos Promedio | Duración (s) | Colisiones |
|-------|-----------|-------|-----------------|--------------|-----------|
| SLM | manhattan_a | 5/5 | 287 | 52.3 | 0 |
| FSM | manhattan_a | 4/5 | 234 | 41.2 | 1 |
| Reactive | manhattan_a | 3/5 | 198 | 35.1 | 2 |
| ... | ... | ... | ... | ... | ... |

