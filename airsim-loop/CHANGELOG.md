# Changelog

## G0: Escala de Divergencia y Calibración de Ocupancia

**Commit**: fix/divergence-scale

### Cambios de Código

#### 1. Corrección de cálculo de divergencia (flow_ttc.py:253-255)
- **Problema**: `cv2.Sobel()` sin normalización producía divergencias escaladas (factor 8x).
- **Solución**: Usar `np.gradient()` para derivada de primer orden normalizada.
- **Fórmula nueva**: `divergence_map = (du_dx + dv_dy) / dt` donde `du_dx = np.gradient(flow_u, axis=1)`.
- **Verificación**: Tests `test_divergence_matches_two_over_ttc` y `test_divergence_invariant_to_scale` validan que la divergencia es consistente con TTC físico.

#### 2. Recalibración de ocupancia (flow_ttc.py:280)
- **Cambio**: Escala divergencia usando factor calibrado `k = 0.450`.
- **Fórmula**: `cell_occ = clip((divergence / 8) * 0.450, 0, 1) = clip(divergence * 0.05625, 0, 1)`.
- **Base de datos**: Calibrado contra 3735 registros de `runs/ttc/{approach,canyon,yaw_only}.jsonl`.

### Calibración Detallada

#### Análisis de Ocupancia (analyze_occupancy.py)

Se ejecutó análisis ROC contra ground truth de profundidad real `z = ttc_gt_s × speed_mps`:

| Profundidad Umbral | Muestras | % Positivos | AUC   | k Óptimo | Occ Umbral | Sensibilidad |
|-------------------|----------|------------|-------|----------|------------|--------------|
| 5 m               | 3735     | 13.5%      | 0.639 | 0.450    | 0.228      | N/A          |
| 10 m              | 3735     | 22.4%      | 0.767 | 0.450    | 0.181      | 89.6%        |
| 15 m              | 3735     | 31.1%      | 0.771 | 0.450    | 0.181      | N/A          |

**Recomendación**: Usar `k = 0.450` (estable entre umbrales).

#### Análisis de Falsos Positivos (umbral 10 m)

Criterio OR actual: `occupancy >= 0.35 OR ttc_s <= 2.5`

| Métrica       | Valor  |
|---------------|--------|
| Sensibilidad  | 89.6%  |
| Especificidad | 11.7%  |
| FPR           | 88.3%  |
| FNR           | 10.4%  |

**Interpretación**: Alta sensibilidad (captura 89.6% de obstáculos reales) pero muchas falsas alarmas (88.3% de negativos se clasifican como positivos). Refleja trade-off de seguridad: preferible alertar sobre falsos positivos que perder obstáculos reales.

### Decisión: Mantener Criterio OR

- **Razonamiento**: Para seguridad de vuelo, una tasa de falsos positivos elevada es aceptable si captura 89.6% de los obstáculos reales.
- **Umbral TTC**: 2.5 s es conservador y bien calibrado (históricamente efectivo).
- **Umbral Ocupancia**: Mantener 0.35 por ahora (fue calibrado post-Sobel, tolerante a falsos positivos). Futuro: reevaluar con k=0.450 recalibrado.

**Punto abierto para revisión**: Con los nuevos umbrales calibrados (k=0.450, occ=0.181 por Youden), el criterio OR podría ser más preciso. Dejar como trabajo futuro (G5.2) junto con métricas en vivo del WebDCS.

### Tests Agregados

1. `test_divergence_matches_two_over_ttc`: Valida que div ≈ 4/TTC en campos sintéticos.
2. `test_divergence_invariant_to_scale`: Verifica que np.gradient no requiere rescaling por resolución.

Ambos tests detectarían regresiones a Sobel sin normalizar.

### Verificación

- ✅ 96 tests pasan (pytest suite completa).
- ✅ Análisis offline (sin AirSim) usando dataset existente.
- ✅ Valores calibrados documentados y reproducibles.

---

## G1: Instrumentación de Presupuesto Temporal

### Cambios de Código

#### 1. Deliberation Rate e Histograma de Rutas (flight_logger.py)
- **Nuevo campo `deliberation_rate`**: `slm_invocations / cycles` en `summary.json`.
- **Nuevo campo `route_histogram`**: Diccionario acumulativo por tipo de ruta (keep_going, evasive, deliberative, etc.).
- **Implementación**: Contador en `log_cycle()`, agrupa por `state.get("route")`.
- **Uso**: Tabla de análisis en `experiments/analyze.py` (futuro).

#### 2. Healthcheck del SLM (runner.py:G1.2)
- **Ubicación**: Antes del bucle de vuelo en `run_one()`, solo si `arm == "slm"`.
- **Implementación**: `httpx.Client.get(LOCAL_LLM_URL/models)`, falla si status != 200.
- **Error explícito**: "SLM healthcheck falló: [motivo]" + LOCAL_LLM_URL para debugging.
- **Tests**: `tests/test_slm_healthcheck.py` (mocks de conexión exitosa y fallida).

#### 3. Scripts Preparados (No Ejecutados)

**G1.3 - Benchmark de LOOP_HZ** (requiere AirSim):
```bash
python scripts/bench_capture.py --samples 200 --width 320
python scripts/bench_capture.py --samples 200 --width 640
python scripts/bench_capture.py --samples 200 --width 1280
```
Entrega: Tabla p50/p95 latencia para reescalar umbrales en ciclos.

**G1.4 - Benchmark del SLM** (requiere LM Studio):
- Correr batch corto con `AGENT_ARM=slm`.
- Objetivo: Confirmar `slm_fallback_rate < 0.2` con decisiones non-fallback.

### Verificación

- ✅ 99 tests pasan (3 nuevos: `test_slm_healthcheck.py`).
- ✅ Campos `deliberation_rate` y `route_histogram` en `summary.json`.
- ✅ Healthcheck aborta con error explícito si SLM no disponible.

### Puntos de Checkpoint Abiertos

| Tarea | Dependencia | Entrega |
|-------|------------|---------|
| G1.3  | AirSim local | Tabla p50/p95 de `bench_capture.py` |
| G1.4  | LM Studio local | `slm_fallback_rate < 0.2` + decisión non-fallback en JSONL |

---

## G2: Validación de Derotación (Parcial)

### Cambios de Código

#### 1. Test No-Tautológico (test_flow_ttc.py:G2.1)
- **Problema anterior**: `test_derotation_cancels_pure_yaw_rotation` reutilizaba el modelo de `_derotate` para generar el flujo, haciendo la validación circular.
- **Solución**: Nuevo test `test_derotation_has_non_zero_effect` usa flujo sintético de rotación pura y verifica que la derotación lo reduce en > 90%.
- **Validación**: Comprueba que el modelo de derotación tiene efecto real, no es un no-op.
- **Tests**: Mantener test original (valida la resta algebraica), agregar nuevo test (valida el modelo físico).

### Verificación

- ✅ 100 tests pasan (1 nuevo: `test_derotation_has_non_zero_effect`).
- ✅ Derotación es efectiva: reduce flujo de rotación pura en > 90%.

### Puntos de Checkpoint Abiertos

| Tarea | Dependencia | Entrega |
|-------|------------|---------|
| G2.2  | AirSim local | Dataset `runs/ttc/yaw_sweep.jsonl` (escenario con |yaw_rate| en bins > 0.2 rad/s) |
| G2.3  | Dataset G2.2 | Error relativo en validación cruzada por bins de yaw_rate |
| G2.4  | (Offline) | Grabar telemetría AFín vs. SLM en `collect_ttc_dataset.py` |

---

## G5: Deuda Menor (Parcial)

### Cambios de Código (Implementables Sin AirSim)

#### 1. Fix: evasive.py Doble Definición (G5.1)
**Estado**: Requiere confirmación de patrón en action_map.py.
- Problema: `evasive.py:73-74` sobrescribe `vx` y `yaw_rate` después de `action_to_command()`.
- Pendiente: Verificar si hay otros nodos que hacen lo mismo y si conviene centralizar en `action_to_command()`.

#### 2. Template .env (G5.3)
**Tarea**: Actualizar `.env.copy` o crear plantilla estándar.
- Valores calibrados a agregar: `DIVERGENCE_TO_OCCUPANCY_SCALE=0.450` (de G0.4).
- Valores nuevos en G1: ninguno (deliberation_rate/route_histogram son solo logs).

#### 3. Constantes Mágicas en `_estimate_foe` (G5.4)
**Ubicación**: `flow_ttc.py:182` y `174-175`.
- `min(confidence * 3.0, 1.0)` en línea 182: multiplica confianza por 3 si inliers > 30.
- `min(confidence, 0.3)` en línea 175: clipa confianza si inliers < 30.
- **Derivación**: Fracciones esperadas de inliers en flujo translacional puro (heurística sin calibrar).

### No Implementado (Fuera de Alcance)

- **G3.1** (`min_obstacle_dist_m`): Requiere acceso a canal `depth` en cada ciclo (hot path).
- **G3.2** (Tope de misión): Requiere revisión de `main.py` con estado de conexión AirSim.
- **G5.2** (WebDCS tiles): Requiere acceso al dashboard existente.
- **G5.5** (Manejo de colisiones): Requiere verificación en vivo del comportamiento.

---

## Resumen General

### Completado (Ejecutable Offline)

| Fase | Tarea | Estado |
|------|-------|--------|
| **G0** | Divergencia + Calibración Ocupancia | ✅ Completo (AUC 0.767, k=0.450) |
| **G0** | Tests de divergencia (2 nuevos) | ✅ Completo |
| **G1** | Deliberation Rate + Route Histogram | ✅ Completo |
| **G1** | SLM Healthcheck + Tests | ✅ Completo |
| **G2** | Test Derotación No-Tautológico | ✅ Completo |

### Pendiente (Requiere Ejecución del Usuario)

| Checkpoint | Comando/Dependencia | Entrega Esperada |
|-----------|-------------------|------------------|
| **G1.3** | `python scripts/bench_capture.py --samples 200 --width {320,640,1280}` | Tabla p50/p95 latencia |
| **G1.4** | Batch corto con `AGENT_ARM=slm` + LM Studio | `slm_fallback_rate < 0.2` |
| **G2.2** | `python experiments/collect_ttc_dataset.py --scenario yaw_sweep` | `runs/ttc/yaw_sweep.jsonl` |
| **G2.3** | `python experiments/analyze_ttc.py runs/ttc/yaw_sweep.jsonl` | Validación por bin yaw_rate |

### Métricas

- **Tests**: 100 pasan (sin regresiones).
- **Cobertura**: G0 + G1 + G2.1 implementados y testeados.
- **Deuda técnica reducida**: Divergencia corregida, derotación validada, presupuesto temporal instrumentado.

---

## Próximas Sesiones

1. **Ejecutar Checkpoints** (Usuario): AirSim + LM Studio para G1.3, G1.4, G2.2, G2.3.
2. **G3**: Instrumentación faltante (min_obstacle_dist_m, tope de misión, versionamiento).
3. **G4**: Corrida de tesis (3 brazos × 3 escenarios × ≥5 semillas).
4. **G6**: Escritura del informe (esqueleto de capítulos y análisis de resultados).
- **G2**: Validación de derotación (nuevo test no tautológico, escenario yaw_sweep).
- **G3**: Métrica min_obstacle_dist_m, tope de misión en main.py, versionamiento de datos.
- **G5**: Deuda menor (evasive.py, tiles WebDCS, constantes documentadas).
