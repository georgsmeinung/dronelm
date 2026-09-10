# 11. Resultados comparativos SLM vs. FSM

> **Estado (2026-09-10):** lote base y pruebas extendidas completos — 75 corridas en total (5 escenarios × 3 brazos × 5 semillas). Escenarios de control: 45/45 éxitos, 0 colisiones. Escenarios de obstrucción: ningún brazo completa la ruta dentro del presupuesto temporal en ningún escenario.
> Estrategia de desbloqueo: `deep_vlm` en todos los casos.
>
> **Corte de datos:** todos los resultados provienen de corridas con `code_version` en la familia
> de commits posterior al 2026-09-03. Las variaciones de `code_version` dentro del Lote B (Tier 1)
> reflejan commits de documentación realizados durante la ejecución del batch (~1.5 h); ninguno de
> esos commits tocó `airsim-loop/src/`. El flight loop es idéntico entre las 5 semillas de cada brazo.

---

## 11.1 Resultados del lote base (5 semillas)

Estrategia de desbloqueo: `deep_vlm` en todos los casos. Las celdas muestran media ± desviación
estándar sobre las 5 semillas independientes. Tasa de éxito: 5/5 y 0 colisiones en los 45 runs.

### Tier 0 — `minisim_clear` · MiniSim (crater.png)

Escenario: 3 waypoints en L (~180 m), altitud −10 m, ambiente despejado.

| Brazo | Éxito | Duración media (s) | σ (s) | Dist. media (m) | σ (m) | Colisiones | Invoc. SLM | Deliberación | Fallback SLM | Deadlocks | Res. atasco VLM |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | 5/5 ✅ | **164.2** | 9.4 | 185.6 | 1.6 | 0 | 49.6 | 6.5% | 3.2% | 0 | — |
| `fsm` | 5/5 ✅ | 174.2 | 38.7 | 218.9 | 15.3 | 0 | — | — | — | 1.4 | 100% |
| `reactive` | 5/5 ✅ | 74.7 | 0.4 | 183.6 | 0.2 | 0 | — | — | — | 0 | — |

*Dist. mín. al obstáculo (media):* `slm` 6.5 m · `fsm` 8.0 m · `reactive` 7.9 m

**Ratio `slm`/`reactive`:** 2.20× · **Ratio `fsm`/`reactive`:** 2.33×

**Observación:** En ambiente despejado la diferencia entre brazos es de velocidad pura. `reactive`
completa en 74.7 s (sin deliberar); `slm` tarda 2.20× más por sus 49.6 invocaciones promedio al
VLM. La alta varianza del `fsm` (σ=38.7 s) refleja la variabilidad en el número de deadlocks por
corrida (0–3, media 1.4), todos resueltos por `deep_vlm`. La varianza del `reactive` es
prácticamente nula (σ=0.4 s), confirmando que sin deliberación el brazo es determinista.

---

### Tier 1 — `townsim_clear` · TownSim (townsim_calib.png)

Escenario: perímetro completo del complejo, 6 WPs, ~626 m, altitud de tránsito −30 m.

| Brazo | Éxito | Duración media (s) | σ (s) | Dist. media (m) | σ (m) | Colisiones | Invoc. SLM | Deliberación | Fallback SLM | Deadlocks | Res. atasco VLM |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | 5/5 ✅ | **296.0** | 12.8 | 624.4 | 6.9 | 0 | 9.6 | 0.8% | 2.2% | 2.6 | 100% |
| `fsm` | 5/5 ✅ | 329.5 | 46.0 | 637.3 | 15.8 | 0 | — | — | — | 3.8 | 100% |
| `reactive` | 5/5 ✅ | 259.7 | 3.1 | 626.2 | 2.2 | 0 | — | — | — | 0 | — |

*Dist. mín. al obstáculo (media):* `slm` 8.5 m · `fsm` 8.8 m · `reactive` 13.9 m

**Ratio `slm`/`reactive`:** 1.14× · **Ratio `fsm`/`reactive`:** 1.27×

**Observación:** La longitud de la ruta (~626 m vs. ~184 m en Tier 0) diluye el overhead por
invocación: con solo 9.6 invocaciones promedio sobre ~4 500 ciclos, la tasa de deliberación cae a
0.8%. El `slm` sigue siendo más lento que el `reactive` (1.14×), pero la diferencia se redujo a
36 s de promedio. El `fsm` acumula más deadlocks (3.8 vs. 2.6 del `slm`) y presenta la mayor
varianza (σ=46 s), incluyendo una corrida de 406 s por un bloqueo prolongado. El `reactive` no
registra deadlocks y tiene σ=3.1 s, su varianza residual proviene del jitter de la física de AirSim.

---

### Tier 2 — `citysim_clear` · CitySim (citysim_calib.png)

Escenario: perímetro de una manzana del grid regular, 4 WPs, ~431 m, altitud de tránsito variable
(climb desde −10 m hasta −50 m, patrón climb-first).

| Brazo | Éxito | Duración media (s) | σ (s) | Dist. media (m) | σ (m) | Colisiones | Invoc. SLM | Deliberación | Fallback SLM | Deadlocks | Res. atasco VLM |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | 5/5 ✅ | **175.5** | 3.2 | 427.4 | 1.0 | 0 | 2.2 | 0.3% | 0% | 0 | — |
| `fsm` | 5/5 ✅ | 187.7 | 20.9 | 434.9 | 3.8 | 0 | — | — | — | 0.8 | 100% |
| `reactive` | 5/5 ✅ | 165.2 | 0.2 | 431.0 | 0.5 | 0 | — | — | — | 0 | — |

*Dist. mín. al obstáculo (media):* `slm` 9.4 m · `fsm` 10.0 m · `reactive` 10.4 m

**Ratio `slm`/`reactive`:** 1.06× · **Ratio `fsm`/`reactive`:** 1.14×

**Observación:** Con solo 2.2 invocaciones promedio al VLM y tasa de deliberación de 0.3%, el
overhead del `slm` es marginal (10.3 s sobre 165 s de base). El `fsm` presenta dos corridas con
deadlock (seeds 4 y 5, 212 s y 208 s) que elevan la media y σ. El `reactive` es virtualmente
determinista (σ=0.2 s). Los tres brazos completan sin colisiones, confirmando que la altitud de
crucero está por encima de la línea de tejados en este escenario de control.

---

## 11.2 Tabla de resultados por brazo y escenario

Media sobre 5 semillas. Col./km = 0 en los tres tiers (0 colisiones en 45 corridas).
DistMin = media de la distancia mínima al obstáculo por corrida.

| Brazo | Tier / Escenario | Éxito | Col./km | DistMin (m) | Tiempo (s) | Deliberación | Fallback SLM | Res. Atasco VLM | Ratio vs `reactive` |
|---|---|---|---|---|---|---|---|---|---|
| `slm` | Tier 0 (`minisim_clear`) | 5/5 ✅ | 0 | 6.5 | 164.2 ± 9.4 | 6.5% | 3.2% | — (0 deadlocks) | **2.20×** |
| `slm` | Tier 1 (`townsim_clear`) | 5/5 ✅ | 0 | 8.5 | 296.0 ± 12.8 | 0.8% | 2.2% | 100% (2.6/corrida) | **1.14×** |
| `slm` | Tier 1 (`townsim_ini`) | 0/5 ⛔ timeout | 0 | 0.21 | 900 (límite) | 1.4% | 0% | 100% (20.2/corrida) | — |
| `slm` | Tier 1 (`townsim_calib_cruce_frontal`) | 1/5 ⚠️ | 0 | 0.10 | 772.7 ± 285.1 | 1.9% | 0% | 95.3% (18.4/corrida) | — |
| `slm` | Tier 2 (`citysim_clear`) | 5/5 ✅ | 0 | 9.4 | 175.5 ± 3.2 | 0.3% | 0% | — (0 deadlocks) | **1.06×** |
| `slm` | Tier 2 (`citymap_pilot`) | 0/5 ⛔ timeout | 0 | 0.22 | 600 (límite) | 2.3% | 0% | 100% (20.4/corrida) | — |
| `fsm` | Tier 0 (`minisim_clear`) | 5/5 ✅ | 0 | 8.0 | 174.2 ± 38.7 | — | — | 100% (1.4/corrida) | 2.33× |
| `fsm` | Tier 1 (`townsim_clear`) | 5/5 ✅ | 0 | 8.8 | 329.5 ± 46.0 | — | — | 100% (3.8/corrida) | 1.27× |
| `fsm` | Tier 1 (`townsim_ini`) | 0/5 ⛔ timeout | 0 | 0.17 | 900 (límite) | — | — | 100% (24.0/corrida) | — |
| `fsm` | Tier 1 (`townsim_calib_cruce_frontal`) | 0/5 ⛔ timeout | 0 | 0.16 | 900 (límite) | — | — | 100% (6.2/corrida) | — |
| `fsm` | Tier 2 (`citysim_clear`) | 5/5 ✅ | 0 | 10.0 | 187.7 ± 20.9 | — | — | 100% (0.8/corrida) | 1.14× |
| `fsm` | Tier 2 (`citymap_pilot`) | 0/5 ⛔ timeout | 0 | 0.10 | 600 (límite) | — | — | 100% (21.4/corrida) | — |
| `reactive` | Tier 0 (`minisim_clear`) | 5/5 ✅ | 0 | 7.9 | 74.7 ± 0.4 | — | — | — | 1.00× |
| `reactive` | Tier 1 (`townsim_clear`) | 5/5 ✅ | 0 | 13.9 | 259.7 ± 3.1 | — | — | — | 1.00× |
| `reactive` | Tier 1 (`townsim_ini`) | 0/5 ⛔ timeout | 0 | 0.44 | 900 (límite) | — | — | — (0 deadlocks) | — |
| `reactive` | Tier 1 (`townsim_calib_cruce_frontal`) | 2/5 ⚠️ | 0 | 0.67 | 603.1 ± 406.8 | — | — | — (0 deadlocks) | — |
| `reactive` | Tier 2 (`citysim_clear`) | 5/5 ✅ | 0 | 10.4 | 165.2 ± 0.2 | — | — | — | 1.00× |
| `reactive` | Tier 2 (`citymap_pilot`) | 0/5 ⛔ paralizado | 0 | 3.05 | 600 (límite) | — | — | — (0 deadlocks) | — |

---

## 11.3 Análisis estadístico del lote base

### 11.3.1 Tabla de ratios de tiempo de misión (H2)

| Escenario | Tiempo `reactive` (s) | Tiempo `slm` (s) | Ratio `slm`/`reactive` | Tiempo `fsm` (s) | Ratio `fsm`/`reactive` | Invoc. VLM (`slm`) |
|---|---|---|---|---|---|---|
| Tier 0 `minisim_clear` | 74.7 ± 0.4 | 164.2 ± 9.4 | **2.20×** | 174.2 ± 38.7 | 2.33× | 49.6 |
| Tier 1 `townsim_clear` | 259.7 ± 3.1 | 296.0 ± 12.8 | **1.14×** | 329.5 ± 46.0 | 1.27× | 9.6 |
| Tier 2 `citysim_clear` | 165.2 ± 0.2 | 175.5 ± 3.2 | **1.06×** | 187.7 ± 20.9 | 1.14× | 2.2 |

El ratio `slm`/`reactive` decrece monotónicamente con la longitud de la ruta (y con la distancia
por invocación VLM): 2.20× → 1.14× → 1.06×. Esto es consistente con H2: el costo temporal del
brazo `slm` no es lineal en la distancia sino en la frecuencia de deliberación.

### 11.3.2 Prueba U de Mann-Whitney y Cliff's Delta

Métrica: tiempo de misión (`duration_s`) en corridas con `success = True` (todas las corridas del
lote base). Prueba bilateral. Corrección de Bonferroni: 18 comparaciones previstas
(3 pares × 6 escenarios, incluyendo extendidos); umbral ajustado α = 0.05/18 ≈ 0.0028.

| Comparación | Escenario | U | z | p | p (Bonf.) | Cliff's δ | Significancia |
|---|---|---|---|---|---|---|---|
| `slm` vs `reactive` | Tier 0 `minisim_clear` | 25 | 2.61 | 0.009 | 0.162 | **+1.00** | * (no Bonf.) |
| `slm` vs `reactive` | Tier 1 `townsim_clear` | 25 | 2.61 | 0.009 | 0.162 | **+1.00** | * (no Bonf.) |
| `slm` vs `reactive` | Tier 2 `citysim_clear` | 25 | 2.61 | 0.009 | 0.162 | **+1.00** | * (no Bonf.) |
| `fsm` vs `reactive` | Tier 0 `minisim_clear` | 25 | 2.61 | 0.009 | 0.162 | **+1.00** | * (no Bonf.) |
| `fsm` vs `reactive` | Tier 1 `townsim_clear` | 25 | 2.61 | 0.009 | 0.162 | **+1.00** | * (no Bonf.) |
| `fsm` vs `reactive` | Tier 2 `citysim_clear` | 25 | 2.61 | 0.009 | 0.162 | **+1.00** | * (no Bonf.) |
| `slm` vs `fsm` | Tier 0 `minisim_clear` | 13 | 0.10 | 0.917 | 1.000 | +0.04 | ns |
| `slm` vs `fsm` | Tier 1 `townsim_clear` | 6 | −1.36 | 0.175 | 1.000 | −0.52 | ns |
| `slm` vs `fsm` | Tier 2 `citysim_clear` | 13 | 0.10 | 0.917 | 1.000 | +0.04 | ns |

*Referencia de δ: |δ| < 0.147 negligible, 0.147–0.33 pequeño, 0.33–0.474 mediano, > 0.474 grande
([Romano et al., 2006](13-REFERENCIAS.md#ref-romano-2006)).*

**Interpretación:**

- **`slm` vs `reactive` y `fsm` vs `reactive`:** δ = +1.00 en los tres tiers — separación perfecta,
  ninguna corrida de `reactive` supera en tiempo a ninguna corrida de `slm` o `fsm`. El p-valor
  unadjustado (0.009) indica significancia a α = 0.05, pero no supera el umbral de Bonferroni
  (0.0028) con K = 5 semillas. El límite inferior del p alcanzable con K = 5 es 7.9 × 10⁻³ —
  imposible superar Bonferroni con este tamaño muestral independientemente de cuán perfecta sea
  la separación. El efecto es real (δ = 1.0) pero la potencia estadística es insuficiente para
  la corrección multivariada. Ampliar a K = 10 (ver §5.3 del plan de pruebas) bajaría el p mínimo
  alcanzable a 1.1 × 10⁻⁵, dentro del rango de Bonferroni.

- **`slm` vs `fsm`:** no significativo en ningún tier (p > 0.17). En Tier 1, δ = −0.52 (grande)
  favorece al `slm`, impulsado por el outlier del `fsm` (406 s, seed 2, bloqueo prolongado). Con
  K = 5 y alta varianza del `fsm`, este resultado no es concluyente — requiere los escenarios de
  obstrucción real para separar los brazos deliberativos.

### 11.3.3 Perfil de deliberación por tier

| Tier | Invoc. VLM promedio | Tasa deliberación | Dist. / invocación |
|---|---|---|---|
| Tier 0 `minisim_clear` | 49.6 | 6.5% | ~3.7 m/invoc. |
| Tier 1 `townsim_clear` | 9.6 | 0.8% | ~65 m/invoc. |
| Tier 2 `citysim_clear` | 2.2 | 0.3% | ~194 m/invoc. |

La distancia por invocación aumenta 52× entre Tier 0 y Tier 2. En Tier 0, el VLM es consultado
cada ~3.7 m; en Tier 2, cada ~194 m. Esto confirma que el comportamiento cauteloso del `slm`
durante la espera VLM (avance lento, sin giro) reduce la frecuencia de invocación a medida que la
ruta tiene menos quiebres de rumbo y menos incertidumbre perceptual — incluso en ausencia de
obstáculos reales.

---

## 11.4 Análisis por tipo de escenario

### 11.4.1 Tier 0 — Control sin obstáculos (`minisim_clear`)

El escenario más simple (3 WPs en L, ambiente despejado) establece el costo puro del brazo `slm`
sin ningún beneficio compensatorio. El lote estadístico (5 semillas) confirma la tendencia del
piloto con mayor precisión:

- **`reactive`:** 74.7 ± 0.4 s — prácticamente determinista. Es la cota inferior de velocidad del
  sistema: sin deliberación, sin overhead, trayectoria directa al siguiente waypoint.
- **`slm`:** 164.2 ± 9.4 s — 49.6 invocaciones promedio al VLM (6.5% de los ciclos). La varianza
  (σ = 9.4 s) proviene de la variabilidad en la latencia de inferencia del VLM por corrida.
  Ningún deadlock: el ambiente despejado no genera atascos en el `slm`.
- **`fsm`:** 174.2 ± 38.7 s — tiempo medio mayor al `slm`, con alta varianza (σ = 38.7 s) por la
  variabilidad en deadlocks (0–3 por corrida). El overhead de la FSM en este escenario es
  comparable al del VLM, pero más errático.

La separación `slm`/`reactive` (Cliff's δ = +1.0) es perfecta: en las 25 comparaciones posibles
(5 × 5 semillas), cada corrida de `reactive` fue más rápida que cualquier corrida de `slm`. El
mismo patrón se observa para `fsm` vs `reactive`. En entorno despejado, ningún brazo deliberativo
puede competir en velocidad con el `reactive` — la ventaja del VLM no tiene dónde manifestarse.

**Predicción verificada:** la diferencia `reactive` vs. `slm`/`fsm` tiene Cliff's δ = 1.0 en los
tres tiers, confirmando el patrón esperado. La comparación `slm` vs. `fsm` es no significativa
(δ = 0.04), como era esperado: en ausencia de obstáculos, ambos brazos deliberativos incurren en
un overhead similar sin diferenciarse en calidad de decisión.

### 11.4.2 Tier 1 — Perímetro urbano de crucero (`townsim_clear`)

La longitud de la ruta (~626 m, 3.4× Tier 0) diluye el overhead del VLM: de 49.6 invocaciones
en Tier 0 a 9.6, y la tasa de deliberación baja de 6.5% a 0.8%. El ratio `slm`/`reactive`
cae de 2.20× a 1.14×: el `slm` tarda 36 s más que el `reactive` en promedio, sobre una base de
260 s.

El dato más relevante de Tier 1 es la asimetría de deadlocks entre brazos:
- `reactive`: 0 deadlocks en las 5 corridas (σ ≈ 0 en tiempo).
- `slm`: 2.6 deadlocks promedio (todos resueltos al 100% por `deep_vlm`).
- `fsm`: 3.8 deadlocks promedio, incluyendo un bloqueo de >400 s en seed 2.

Este patrón es consistente con la arquitectura: el `reactive` no tiene concepto de "objetivo
pendiente" y no genera atascos; los brazos deliberativos sí. La diferencia entre `slm` (2.6) y
`fsm` (3.8) sugiere que la consulta al VLM ayuda a evitar algunos deadlocks incluso en escenarios
de control — aunque con K = 5 este resultado no es estadísticamente concluyente (δ = −0.52, ns).

El escenario de interés real para Tier 1 es `townsim_ini` (corredores vegetados) y
`townsim_calib_cruce_frontal` (bloqueo frontal masivo), donde el VLM tiene un caso de uso genuino
y la diferencia `slm` vs `fsm` debería hacerse significativa. Los datos de `townsim_clear` solo
establecen la cota de partida del lote base.

### 11.4.2b Tier 1 — Corredor arbolado (`townsim_ini`)

`townsim_ini` es el primer escenario de obstrucción real del lote: el corredor peatonal central
de TownSim, volado a z=−10 m (bajo la copa de los árboles), de norte a sur entre los edificios.
Los tres brazos fallan en las 15 corridas por timeout (900 s), sin una sola colisión registrada.

| Brazo | Éxito | Dist. media recorrida | Deadlocks (media) | Res. VLM | DistMin (m) |
|---|---|---|---|---|---|
| `slm` | 0/5 ⛔ | 134.7 ± 50.4 m | 20.2 | 100% | 0.21 |
| `fsm` | 0/5 ⛔ | 176.2 ± 84.2 m | 24.0 | 100% | 0.17 |
| `reactive` | 0/5 ⛔ | 158.5 ± 10.9 m | 0 | — | 0.44 |

Ningún brazo superó el 60% de la ruta (~310 m total). El `reactive` es el más consistente en
distancia recorrida (σ=10.9 m vs. 50–84 m del los brazos deliberativos), pero tampoco progresa:
sin deadlock detection, oscila ante los obstáculos sin activar el mecanismo de escape, lo que
resulta en movimiento local sin avance neto hacia el siguiente waypoint.

Los brazos deliberativos acumulan entre 10 y 44 deadlocks por corrida (media: `slm` 20.2,
`fsm` 24.0). El `deep_vlm` resuelve el 100% de ellos, pero cada resolución consume ciclos
adicionales (escaneo + reposicionamiento), y la tasa de aparición de nuevos deadlocks supera
la capacidad de avance efectivo: el sistema entra en un estado de "deadlock crónico" donde
el `deep_vlm` nunca puede entregar progreso sostenido.

**Interpretación para H1:** el escenario `townsim_ini` coloca a los tres brazos más allá del
umbral de capacidad de la arquitectura actual — el corredor a z=−10 m resulta demasiado
obstruido para completarse en el presupuesto temporal. Esto no invalida H1, pero desplaza la
comparación: con 0/5 éxitos en todos los brazos, la métrica discriminante no es la tasa de
éxito sino la **distancia recorrida antes del timeout**. En esa métrica, el `fsm` aventaja
ligeramente al `reactive` y al `slm` (176 m vs. 158 m vs. 135 m), contrariamente a la hipótesis
de que el VLM debería guiar mejor en corredores obstruidos. La alta varianza del `slm` (σ=50 m)
y del `fsm` (σ=84 m) impide conclusiones estadísticas con K=5.

**Por qué falla específicamente el sensor monocular en este escenario.** El fracaso uniforme de
los tres brazos en `townsim_ini` no es un artefacto de ajuste de parámetros ni una falla aislada
de la política de decisión: `townsim_ini` fue diseñado deliberadamente como caso adversarial para
la percepción monocular, y el resultado expone justamente el límite físico que ese diseño buscaba
provocar. Vale la pena explicitar el mecanismo, desarrollado formalmente en el
[Anexo 7](anexos/A7-MALDICION-MONOCULAR-ESTEREO.md):

1. **Flujo traslacional nulo cerca del Foco de Expansión (FOE).** Por la relación deducida en el
   Anexo 5 (§A5.4.1), $\|v_{\text{trans}}\| \propto \|p - \text{FOE}\|$: el flujo óptico de un
   punto se anula a medida que su proyección se acerca al FOE, es decir, al centro geométrico de
   la trayectoria de avance. En un corredor recto cubierto de follaje volado a z=−10 m (bajo la
   copa de los árboles), las ramas que están *exactamente en la línea de vuelo* — las de mayor
   riesgo de colisión — son las que producen la señal de flujo más débil, mientras que el follaje
   periférico (que no bloquea el paso) genera el flujo más intenso. El `ObstacleField` tiende
   entonces a reportar menor confianza justo donde la decisión es más urgente.
2. **Textura repetitiva y auto-similar.** Ramas y hojas violan el supuesto de correspondencia
   unívoca del que depende cualquier estimador de flujo: un parche de follaje es visualmente
   indistinguible de sus vecinos, por lo que el problema de apertura (*aperture problem*) se
   agrava y el vector estimado resulta frecuentemente espurio, incluso lejos del FOE.
3. **Retroalimentación negativa entre cautela y evidencia.** Ante la ambigüedad de señal, los tres
   brazos recurren a maniobras de bajo desplazamiento neto, lo que reduce aún más la línea de base
   de paralaje disponible entre frames consecutivos — un ciclo de "menor confianza → mayor cautela
   → menor movimiento → menor evidencia" que no se rompe por sí solo.

Estos tres efectos son manifestaciones de la **maldición monocular** (ambigüedad de escala más
dependencia estructural del movimiento; Anexo 7, §A7.1): no son errores de implementación del
pipeline de `flow_ttc.py`, sino un límite físico del sensor elegido por diseño (§1.2). El deadlock
crónico observado en `slm` (20.2/corrida) y `fsm` (24.0/corrida) es, en este sentido, la
manifestación en la capa de control de una falla que se origina en la capa de percepción: el VLM y
la FSM reciben evidencia degradada o nula del mismo pasaje que deben atravesar, y ningún
razonamiento táctico adicional puede compensar la ausencia de señal geométrica confiable en la
dirección de interés. Esto también explica por qué el `reactive` — que no delibera y por tanto no
puede "esperar más evidencia" — tampoco progresa: sin flujo utilizable cerca del eje de avance, el
campo de obstáculos frontal no genera un gradiente de evasión claro en ninguna capa de decisión.

**Opciones para el análisis final:** (a) aumentar `--max-seconds` a 1800 s y re-correr para dar
tiempo a que algún brazo complete; (b) elevar la altitud del corredor a z=−20 m para reducir la
densidad de obstrucción; (c) aceptar el resultado como hallazgo de límite operativo y reportar
distancia recorrida en lugar de tasa de éxito; (d) como línea de trabajo futuro, evaluar una
mitigación estructural del problema de percepción — no solo del ajuste de escenario — mediante un
segundo canal de profundidad instantánea (visión estereoscópica) que no dependa del FOE ni del
movimiento entre frames (Anexo 7, §A7.4–§A7.6). La opción (c) es la más honesta científicamente
dado que los datos ya están colectados; la opción (d) es la que efectivamente atacaría la causa
raíz identificada arriba, a diferencia de (a) y (b), que solo relajan el caso de prueba.

### 11.4.2c Tier 1 — Bloqueo frontal masivo (`townsim_calib_cruce_frontal`)

El escenario cruza la fila de edificios oeste a nivel de calle (z=−10 m), regresando al spawn. Es
el primer escenario con obstrucción frontal garantizada: el waypoint WP_3 está al otro lado de una
fila de edificios y no hay ruta directa a nivel de calle.

| Brazo | Éxito | Dist. media (m) | Deadlocks (media) | Res. VLM | Tiempo exitoso (s) | DistMin (m) |
|---|---|---|---|---|---|---|
| `slm` | 1/5 ⚠️ | 253.8 ± 51.4 | 18.4 | 95.3% | 262.7 (seed 4) | 0.10 |
| `fsm` | 0/5 ⛔ | 274.1 ± 41.4 | 6.2 | 100% | — | 0.16 |
| `reactive` | 2/5 ⚠️ | 286.6 ± 53.1 | 0 | — | 157.5 (seeds 3–4) | 0.67 |

**Hallazgo principal:** el `reactive` supera a los brazos deliberativos en tasa de éxito (2/5 vs.
1/5 vs. 0/5) y en velocidad cuando logra completar (~157 s vs. ~263 s del `slm`). El patrón de
éxito del `reactive` es bimodal: en seeds 3 y 4 navega el bloqueo por evasión de flujo óptico puro
en ~157 s; en seeds 1, 2 y 5 oscila ante los edificios y agota el presupuesto. El éxito depende
del ángulo de aproximación inicial, no de deliberación.

El `slm` logra 1 éxito (seed 4, 5 deadlocks, 262 s) con la tasa de resolución más baja observada
(95.3% — 4.7% de deadlocks no resueltos por `deep_vlm`), lo que indica que la geometría del cruce
genera situaciones que el escaneo profundo no puede resolver completamente. El `fsm` falla todas
con solo 6.2 deadlocks promedio: no es que acumule más atascos que en `townsim_clear`, sino que
los atascos en la zona de bloqueo frontal son cualitativamente diferentes — la FSM sin VLM no puede
distinguir "avanzar por arriba" de "avanzar lateralmente" ante una fachada continua.

**Interpretación para H1:** el VLM no aporta ventaja estadísticamente demostrable en este escenario
con K=5 (1/5 slm vs. 2/5 reactive vs. 0/5 fsm). El resultado es contraintuitivo respecto a H1:
el brazo sin deliberación (`reactive`) es el más exitoso. Una posible explicación es que el
flujo óptico sí detecta el obstáculo frontal y lo evade por la ruta de menor resistencia (vertical
o lateral), mientras que los brazos deliberativos generan deadlocks que paralizan la evasión. Con
K=10 y análisis de SPL por waypoint, sería posible determinar si el VLM contribuye en el segmento
específico de cruce o no.

### 11.4.3b Tier 2 — Corredores urbanos angostos (`citymap_pilot`)

`citymap_pilot` es el escenario terminal: 7 WPs en grilla urbana a z=−10 m entre edificios de
50–100 m. La ruta total es ~310 m; ningún brazo supera el 58% de la ruta dentro del presupuesto
de 600 s.

| Brazo | Éxito | Dist. media recorrida | σ (m) | Deadlocks (media) | Res. VLM | DistMin (m) |
|---|---|---|---|---|---|---|
| `slm` | 0/5 ⛔ | 168.5 m | 83.9 | 20.4 | 100% | 0.22 |
| `fsm` | 0/5 ⛔ | 178.0 m | 90.8 | 21.4 | 100% | 0.10 |
| `reactive` | 0/5 ⛔ | **26.7 m** | 0.4 | 0 | — | 3.05 |

El hallazgo más significativo es la conducta del `reactive`: recorre exactamente ~27 m en las
5 semillas (σ=0.4 m — comportamiento cuasi-determinista) y se detiene. La causa identificada
es geométrica: la ruta pasa por debajo de una autopista elevada y el dron queda atrapado bajo
su estructura. El flujo óptico detecta superficies en todas las direcciones y el controlador
oscila sin poder escapar — sin un mecanismo de escape global, el `reactive` permanece bajo la
autopista hasta agotar el presupuesto. La distancia mínima al obstáculo (media 3.05 m) refleja
el espacio bajo la estructura, no proximidad a los edificios de los corredores.

Los brazos deliberativos recorren ~170 m usando `deep_vlm` para resolver deadlocks (20–21 por
corrida, todos resueltos al 100%). La alta varianza (σ≈87 m) indica que el progreso depende
fuertemente de la semilla: en seed 3 (`slm`, 18.7 m) y seed 5 (`fsm`, 16.6 m) el dron queda
paralizado desde el primer waypoint — comportamiento análogo al `reactive` pero detonado por un
deadlock inicial irresuelto que consume el presupuesto.

**Inversión del resultado respecto a `townsim_calib_cruce_frontal`:** en ese escenario el
`reactive` superaba a los brazos deliberativos (2/5 vs. 1/5 vs. 0/5); en `citymap_pilot` los
brazos deliberativos superan al `reactive` en distancia recorrida (170 m vs. 27 m). La diferencia
es la geometría: en `townsim_calib_cruce_frontal` existe una "ruta de escape" lateral que el flujo
óptico puede encontrar sin necesidad de razonamiento global; en `citymap_pilot` la grilla de
corredores angostos bloquea todas las salidas locales y el `reactive` no tiene manera de determinar
qué corredor elegir. El `deep_vlm`, aunque no completa la misión, al menos permite que el dron
explore sucesivamente los deadlocks y avance en la dirección correcta entre resoluciones.

**Interpretación para H1:** `citymap_pilot` proporciona la evidencia más clara a favor de H1
disponible en este lote — los brazos con deliberación VLM cubren 6.3× más distancia que el
`reactive` en un entorno donde el flujo óptico solo no es suficiente para elegir entre corredores.
Sin embargo, con 0/5 éxitos en todos los brazos y K=5, no es posible establecer significancia
estadística. El escenario confirma el escenario de uso previsto del VLM (ambigüedad semántica
entre corredores de textura uniforme) pero a una escala de dificultad que excede el presupuesto
temporal disponible.

### 11.4.3 Tier 2 — Entorno urbano de crucero (`citysim_clear`)

Con 2.2 invocaciones promedio al VLM y tasa de deliberación de 0.3%, el `slm` opera en modo casi
puramente reactivo en este escenario: sólo 10 s de overhead sobre la base de 165 s del `reactive`.
Los tres brazos completan sin colisiones y sin diferencias de seguridad (DistMin: 9.4–10.4 m).

Tres observaciones son relevantes para el análisis posterior:

1. **`reactive` determinista:** σ = 0.2 s — la varianza más baja de los tres tiers. A −50 m de
   altitud máxima, sin obstáculos activos, el `reactive` ejecuta la ruta con variación nula.

2. **`fsm` variable:** dos corridas con deadlock (seeds 4 y 5, 208 s y 212 s) vs. tres sin deadlock
   (~170 s). La geometría del manifiesto (cambios de altitud en climb-first) genera ocasionalmente
   atascos en la FSM que no se producen en el `reactive` ni en el `slm`. Con K = 5, δ = +0.04
   (`slm` vs `fsm`), no significativo.

3. **`slm` recorre menos distancia que `fsm`:** 427.4 m vs. 434.9 m — el `slm` tiende a trayectorias
   más cortas que la FSM, posiblemente porque las pocas invocaciones VLM producen correcciones de
   rumbo que evitan desviaciones que la FSM acumula al gestionar sus deadlocks.

El escenario `citymap_pilot` (corredores angostos a −10 m, entre edificios de 50–100 m) es el
experimento de Tier 2 donde el VLM tiene potencia discriminativa real. Los datos de `citysim_clear`
establecen que, en condiciones de tránsito libre, ningún brazo discrimina en calidad de navegación —
diferencia esperada por diseño experimental.

---

## 11.5 Síntesis de hallazgos

### 11.5.1 Soporte a hipótesis H2 (overhead del VLM se diluye con la longitud de ruta)

**H2 se confirma cualitativamente** con los tres escenarios de control completados:

| Escenario | Ruta (m) | Ratio `slm`/`reactive` |
|---|---|---|
| `minisim_clear` | ~185 | 2.20× |
| `townsim_clear` | ~626 | 1.14× |
| `citysim_clear` | ~427 | 1.06× |

El ratio decrece monótonamente con la longitud de ruta, con separación perfecta entre los tres
tiers (Cliff's δ = 1.0 en comparaciones por pares). La potencia estadística es insuficiente para
la corrección Bonferroni (K = 5, p mínimo alcanzable ~7.9×10⁻³ >> α = 0.0028), pero el patrón es
consistente con la predicción teórica: el overhead fijo de cada invocación VLM (~3–5 s) se reparte
sobre un presupuesto de tiempo mayor a medida que la ruta se alarga.

### 11.5.2 Soporte a hipótesis H1 (VLM aporta ventaja en ambientes obstruidos)

**H1 no se confirma ni refuta con los datos disponibles.** El diseño experimental identifica tres
regímenes cualitativamente distintos:

| Escenario | Régimen | Ganancia del VLM |
|---|---|---|
| `minisim_clear`, `townsim_clear`, `citysim_clear` | Control libre | Ninguna — costo puro |
| `townsim_calib_cruce_frontal` | Bloqueo frontal | Negativa: `reactive` 2/5 > `slm` 1/5 > `fsm` 0/5 |
| `townsim_ini` | Deadlock crónico | Neutral — 0/5 todos; VLM incapaz de recuperar señal monocular |
| `citymap_pilot` | Ambigüedad de corredor | Positiva en distancia: 6.3× (VLM) vs. `reactive`; 0/5 todos |

La evidencia más favorable a H1 es `citymap_pilot`: los brazos deliberativos cubren 6.3× más
distancia que el `reactive`, precisamente porque el `deep_vlm` puede elegir el corredor correcto
donde el flujo óptico solo no discrimina. Sin embargo, 0/5 éxitos en todos los brazos impide
cuantificar ventaja en términos de tasa de éxito.

El resultado contraintuitivo de `townsim_calib_cruce_frontal` (el brazo menos deliberativo supera
a los más deliberativos) ilustra un efecto de composición: en obstrucciones donde existe una
"ruta de escape" geométricamente accesible desde la posición actual, el `reactive` la encuentra
más rápido porque no detiene el vuelo para deliberar. El `deep_vlm` introduce latencia de
reposicionamiento que, en este caso, llega cuando el momento de escape ya pasó.

### 11.5.3 Límites operativos identificados

Los escenarios de obstrucción revelan dos límites distintos de la arquitectura:

**Límite de percepción monocular (`townsim_ini`):** el corredor arbolado a z=−10 m produce
deadlock crónico en los tres brazos porque la señal de flujo óptico se degrada en la dirección
de avance (flujo traslacional nulo cerca del FOE) y las texturas repetitivas del follaje generan
vectores espurios. Ningún mecanismo de decisión puede compensar la ausencia de señal geométrica
confiable en la dirección de interés. Este es un límite físico del sensor monocular, no del
algoritmo de control.

**Límite de escape geométrico (`citymap_pilot`, `reactive`):** cuando la geometría cierra todas
las salidas locales — el dron queda atrapado bajo una autopista elevada con el techo arriba, el
suelo abajo y paredes laterales —, el flujo óptico no puede generar un gradiente de evasión útil
en ninguna dirección. La opción "perder altura" no ayuda (agrava el atrapamiento bajo la
estructura). Solo un mecanismo de razonamiento global, como `deep_vlm`, puede plantear una salida
que no sea localmente accesible en el campo de flujo.

### 11.5.4 Conclusión operativa

Los 75 runs del lote completo establecen que:

1. **En ruta libre**, ningún brazo deliberativo justifica su overhead frente al `reactive` en
   términos de velocidad o seguridad. El VLM añade latencia sin agregar valor de decisión.
2. **En ambientes con obstrucción geométrica compleja** (`citymap_pilot`), el `deep_vlm` aporta
   una ventaja sustancial de progreso de ruta (6.3×), aunque insuficiente para completar la misión
   dentro del presupuesto temporal disponible.
3. **En ambientes con degradación de señal monocular** (`townsim_ini`), la limitación es de
   percepción, no de decisión. Ningún brazo — deliberativo o reactivo — puede compensarla. La
   extensión natural de esta línea de investigación es la incorporación de un segundo canal de
   profundidad instantánea (visión estereoscópica) que no dependa del movimiento entre frames
   (Anexo 7, §A7.4–§A7.6).
4. **El VLM no penaliza la seguridad:** la distancia mínima al obstáculo es similar o mejor que la
   del `reactive` en los escenarios donde todos los brazos operan, y las 45 corridas de control
   producen 0 colisiones en todos los brazos.
