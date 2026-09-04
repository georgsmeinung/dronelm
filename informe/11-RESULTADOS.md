# 11. Resultados comparativos SLM vs. FSM

> **Estado:** pendiente de la ejecución del batch final de tesis (G4) estructurado en el capítulo 10.
> Las corridas piloto previas validaron con éxito el criterio de arranque exigido (`success = True`, 0
> colisiones) tanto en Tier 0 (`minisim_clear`, validado en verde en los tres brazos con 120s de
> presupuesto) como en Tier 1 (`townsim_ini`, validado con éxito sin colisiones y resolviendo la
> totalidad de atascos observados mediante escaneo profundo).
>
> Para preservar el rigor metodológico, los resultados definitivos se restringen a ejecuciones
> posteriores a los fixes de calibración del 2026-09-03 (canales de color consistentes, ausencia de
> artefactos gráficos en simulación y ángulos de Euler continuos), ejecutadas de forma headless
> mediante `experiments/batch_runner.py` sobre un diseño factorial completo:
> $\text{Brazo} \times \text{Estrategia de Atasco} \times \text{Tier} \times \text{Semillas } (\ge 5)$.

## 11.1 Tabla de resultados agregados (placeholder)

| Brazo | Tier / Escenario | Estrategia Atasco | Tasa de éxito | Colisiones/km | DistMin p5 (m) | SPL | Tiempo a destino (s) | Latencia p95 (ms) | `deliberation_rate` | Fallback SLM | Timeout watchdog | Res. Atasco VLM |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | Tier 0 (`minisim_clear`) | `blind` | | | | | | | | | | — |
| `slm` | Tier 1 (`townsim_ini`) | `deep_vlm` | | | | | | | | | | |
| `slm` | Tier 1 (`townsim_cruce`) | `deep_vlm` | | | | | | | | | | |
| `slm` | Tier 1 (`townsim_ini`) | `blind` | | | | | | | | | | — |
| `slm` | Tier 2 (`citymap_pilot`) | `deep_vlm` | | | | | | | | | | |
| `fsm` | Tier 0 (`minisim_clear`) | `blind` | | | | | | | | — | — | — |
| `fsm` | Tier 1 (`townsim_ini`) | `deep_vlm` | | | | | | | | — | — | |
| `fsm` | Tier 1 (`townsim_cruce`) | `deep_vlm` | | | | | | | | — | — | |
| `fsm` | Tier 1 (`townsim_ini`) | `blind` | | | | | | | | — | — | — |
| `fsm` | Tier 2 (`citymap_pilot`) | `deep_vlm` | | | | | | | | — | — | |
| `reactive` | Tier 0 (`minisim_clear`) | — | | | | | | | — | — | — | — |
| `reactive` | Tier 1 (`townsim_ini`) | — | | | | | | | — | — | — | — |
| `reactive` | Tier 2 (`citymap_pilot`) | — | | | | | | | — | — | — | — |

## 11.2 Histograma de rutas por brazo

Placeholder para la distribución de rutas de decisión por ciclo en el grafo de control (`reactive`, `evasive`, `deliberative`, `girar_90`, `fsm`, `spatial_scan`, `deep_scan`), desagregada por brazo y por Tier ambiental.

## 11.3 Significancia estadística

Placeholder — análisis no paramétrico mediante prueba U de Mann-Whitney y estimación de tamaño de efecto (Cliff's Delta / correlación de rango biserial) por celda factorial sobre las $\ge 5$ semillas independientes (§10.3).

## 11.4 Análisis por tipo de escenario

Discusión desagregada de la hipótesis central: ¿aporta la deliberación contextual del VLM sobre la heurística rígida de la FSM? Contrastación orientada por la morfología de cada nivel:
- **Tier 0 (Control):** confirmación de convergencia cinemática básica y consumo mínimo de latencia.
- **Tier 1 (Bloqueo frontal y vegetación):** evaluación del aporte del escaneo espacial profundo (`deep_vlm`) para resolver atascos en entornos con desvíos laterales viables frente al escape ciego.
- **Tier 2 (Cañones urbanos):** evaluación de la navegación en pasajes ortogonales estrechos con geometría tipo cuadrícula.
