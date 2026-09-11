# PLAN-RL — Política de Navegación Visual por RL

## Contexto y motivación

El brazo `slm` del proyecto usa un VLM como árbitro deliberativo a ~1 Hz.  
La hipótesis de este plan es agregar un cuarto brazo (`rl`) que implementa una **política de navegación visual end-to-end** entrenada por Reinforcement Learning.

### Ubicación en la arquitectura jerárquica

```
[Lenguaje / Misión]
        │
        ▼
┌─────────────────────────────────────────────┐
│ Capa Cognitiva — VLM  (0.5–2 Hz)            │  ← ya implementada (brazo slm)
│  razonamiento semántico → waypoints          │
└──────────────────┬──────────────────────────┘
                   │ waypoints semánticos
                   ▼
┌─────────────────────────────────────────────┐
│ Capa Táctica — RL visual  (5–20 Hz)         │  ← este plan
│  cámara + TTC → comandos de velocidad        │
└──────────────────┬──────────────────────────┘
                   │ velocity setpoints
                   ▼
┌─────────────────────────────────────────────┐
│ Capa Motora — PX4 / PID  (400 Hz)           │  ← intocada, maneja actitud
└─────────────────────────────────────────────┘
```

**¿Es S7?** Sí: es "control de vuelo por red neuronal" aplicado al nivel de navegación,  
no al nivel de actitud/motores. En AirSim/SITL ese es el nivel alcanzable y el  
académicamente relevante (equivalente en concepto a Swift de UZH, pero en simulación).

### Ventaja comparativa en la tesis

Permite una tabla de comparación de cuatro brazos:

| Métrica | `fsm` | `reactive` | `slm` | `rl` |
|---|---|---|---|---|
| Tasa de éxito | ref | ref | ref | ? |
| Tiempo de reacción | ref | ref | ref | ? |
| Consumo GPU | ref | ref | ref | ? |
| Latencia decisión | ref | ref | ref | ? |

---

## Decisiones de diseño

### Espacio de observaciones (input)

Opción A (recomendada): el mismo stack que ya usa el sistema.

```python
obs = {
    "rgb":     (H, W, 3),   # cámara monocular delantera — ya disponible
    "depth":   (H, W, 1),   # mapa TTC/flujo óptico de flow_ttc.py
    "imu":     (6,),         # gyro + accel — ya en telemetría
}
```

Opción B (end-to-end puro): solo `rgb` sin profundidad — más difícil de entrenar  
pero más impactante como resultado.

### Espacio de acciones

**Discreto** (recomendado para empezar): mapear al conjunto de acciones ya definido en  
`airsim-loop/src/agents/action_map.py`. Esto reutiliza toda la cinemática validada.

```python
# 7 acciones (expandible)
ACTIONS = [AVANZAR, RETROCEDER, GIRAR_IZQ, GIRAR_DER,
           SUBIR, BAJAR, MANTENER]
```

**Continuo** (siguiente paso): Box(low=−1, high=1, shape=(4,)) → vx, vy, vz, yaw_rate.

### Algoritmo

| Candidato | Razón |
|---|---|
| **PPO** (recomendado) | robusto, on-policy, funciona bien en AirSim (referencia: Swift) |
| SAC | mayor sample efficiency, útil si el entrenamiento es lento |
| DQN | solo para espacio discreto; línea base fácil de implementar |

Implementación: **Stable-Baselines3** (SB3) — mínima fricción con AirSim.

### Función de recompensa

```python
r = (
    + w_progress * delta_distancia_al_wp      # progreso hacia waypoint
    − w_collision * colision_detectada        # penalidad dura
    − w_near * ttc_min_inverso                # penalidad suave cerca de obstáculos
    + w_arrival * llegada_al_wp               # bonus de llegada
    − w_time * dt                             # penalidad por tiempo (eficiencia)
)
```

Las constantes `w_*` son hiperparámetros. Empezar con `w_collision` alto y  
`w_progress` moderado para que primero aprenda a no chocar.

---

## Fases de implementación

### R0 · Gimnasio AirSim

**Objetivo:** crear un entorno `gym.Env` que envuelva AirSim.

**Archivos a crear:**

```
airsim-loop/src/rl/
  __init__.py
  airsim_env.py      # gym.Env — reset(), step(), render()
  reward.py          # función de recompensa parametrizada
  obs_builder.py     # construye el dict de observaciones desde AirSim
```

**Criterio de aceptación:** `env.reset()` y `env.step(action)` funcionan sin error;  
`check_env(env)` de SB3 pasa sin warnings.

**Estimación:** 2–3 días.

---

### R1 · Entrenamiento en MiniSim (Tier 0)

**Objetivo:** política básica de evasión de obstáculos en el escenario más simple.

**Setup:**
- Mapa: `minimap.png` (Tier 0, pocos obstáculos)
- Algoritmo: DQN sobre espacio discreto (baseline rápida)
- Observación: `depth` únicamente (más fácil de aprender)
- 500k pasos de entrenamiento

**Métricas de éxito:**
- Tasa de colisión < 20% en eval de 50 episodios
- Tasa de llegada al WP > 50%

**Archivos:**

```
airsim-loop/experiments/r1_dqn_minisim.py
airsim-loop/experiments/r1_eval.py
```

**Estimación:** 3–5 días (incluye debugging del env).

---

### R2 · Visual end-to-end en TownSim (Tier 1)

**Objetivo:** política que usa `rgb + depth` como input; entrenada en townsim.

**Cambios respecto a R1:**
- Algoritmo: PPO con política CNN (`CnnPolicy` de SB3)
- Observación: `rgb (84×84)` + `depth (84×84)` → concatenados
- 2M pasos con curriculum: primero pasillos anchos, luego calles densas
- Domain randomization: tiempo, iluminación, texturas (ya soportado en AirSim)

**Referencia de arquitectura CNN:**

```
Input(84,84,4) → Conv(32,8,4) → Conv(64,4,2) → Conv(64,3,1)
→ Flatten → Linear(512) → Actor/Critic heads
```

**Métricas de éxito:**
- Tasa de llegada WP ≥ brazo `reactive` en same scenarios
- Tiempo promedio de misión ≤ 1.5× brazo `fsm`

**Estimación:** 1–2 semanas (entrenamiento puede correr overnight).

---

### R3 · Integración con VLM (arquitectura jerárquica)

**Objetivo:** el VLM genera waypoints; la política RL navega entre ellos.

**Cambio de interfaz:**

```python
# graph.py — nuevo brazo "rl"
class RLNavigator:
    def __init__(self):
        self.policy = PPO.load("runs/rl/r2_best.zip")
        self.current_wp = None

    def step(self, obs, state):
        action, _ = self.policy.predict(obs, deterministic=True)
        return action_map[action]
```

El VLM (`deep_scan.py`) sigue corriendo a 1 Hz para actualizar `self.current_wp`.  
La política RL usa ese waypoint como parte de la observación (distancia + heading al WP).

**Estimación:** 2–3 días (principalmente plumbing de integración).

---

### R4 · Evaluación comparativa

**Objetivo:** tabla de resultados para el cap. 11 de la tesis.

**Protocolo:** mismo que corridas S6 de PLAN-SLAM.

```
townsim_ini
  K=5 semillas × 3 brazos (slm, fsm, rl) × 2 niveles (Tier 1, Tier 2)
= 30 corridas
```

**Métricas:**
- `success_rate` — waypoints alcanzados / total
- `collision_rate` — colisiones / episodio
- `mission_time_s` — promedio
- `cpu_gpu_pct` — consumo durante inferencia de política
- `decision_latency_ms` — tiempo de step de la política

**Archivos:**

```
airsim-loop/experiments/r4_comparative_eval.py
airsim-loop/tests/test_r4_metrics.py
```

**Estimación:** 2–3 días + tiempo de corridas.

---

## Dependencias y herramientas

```bash
# ambiente: conda airsimenv (ya activo)
pip install stable-baselines3[extra]  # PPO, SAC, DQN + tensorboard
pip install gymnasium                 # gym API moderna
pip install sb3-contrib               # TQC, RecurrentPPO si se necesitan
```

**GPU requerida para entrenamiento:** cualquier CUDA >= 11.x (PC de desarrollo).  
La política *inferida* corre en CPU en Jetson Nano (<5ms para CNN pequeña).

---

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| AirSim env muy lento (< 5 FPS) para RL | Alta | usar `--no-display` + resolución 84×84; paralelizar con SubprocVecEnv si hay varias licencias |
| Recompensa densa difícil de calibrar | Media | empezar con recompensa sparse (llegó/no llegó) y agregar términos de a uno |
| Sim-to-real gap para tesis | Baja | es in-sim, no hay gap; mencionar en limitaciones |
| Tiempo de entrenamiento excesivo | Media | R1 con DQN da baseline en horas; R2 puede correr overnight |

---

## Relación con objetivos de la tesis

| Objetivo tesis | Cobertura por PLAN-RL |
|---|---|
| "evaluación comparativa SLM vs FSM" | extiende a SLM vs FSM vs **RL** |
| "modelos ligeros en hardware bajo costo" | política CNN pequeña (<1MB) corre en Jetson Nano |
| "aprendizaje por refuerzo en SLM" | sección 4 de plan-tesis.md lo menciona explícitamente |

---

## Estado

| Fase | Estado |
|---|---|
| R0 — gym env | 🔲 Pendiente |
| R1 — DQN MiniSim | 🔲 Pendiente |
| R2 — PPO visual TownSim | 🔲 Pendiente |
| R3 — integración VLM+RL | 🔲 Pendiente |
| R4 — evaluación comparativa | 🔲 Pendiente |

**Prerequisito:** S6 de PLAN-SLAM debe estar completo (baseline `slm` validada)  
para que la comparación en R4 sea con datos consistentes.
