# PLAN-ANALISIS.md — Notebooks de análisis y didáctica

> **Estado:** borrador inicial — 2026-09-09
> **Objetivo:** tres notebooks Jupyter que cubren (1) el pipeline estadístico completo que
> produce `informe/11-RESULTADOS.md`, (2) la exploración interactiva de los logs de auditoría
> `.jsonl`/`.csv`, y (3) la traza didáctica del grafo LangGraph ciclo a ciclo a partir de una
> fila real del CSV de auditoría.

---

## Contexto: fuentes de datos disponibles

| Archivo | Generado por | Contenido |
|---|---|---|
| `<runs>/…/seed_N.jsonl` | `FlightLogger` | Un objeto JSON por ciclo: telemetría, `ObstacleField`, `slm`, latencias, colisión |
| `<runs>/…/seed_N.csv` | `FlightLogger` | Misma información en formato tabular; campos `field_*`, `slm_*`, `latency_ms_json` |
| `<runs>/…/seed_N.summary.json` | `FlightLogger.close()` | Resumen por corrida: success, SPL, invocaciones SLM, tasa fallback, deadlocks |
| `viewer.html` | `flight_viewer.py` | HTML autocontenido con video + tabla CSV inline; no es fuente de datos para análisis |

Los datos del lote base (45 corridas, 5 semillas × 3 brazos × 3 tiers) están en
`airsim-runs/` (fuera de `airsim-loop/`). La ruta exacta depende del entorno de ejecución;
los notebooks deben aceptar `RUNS_DIR` como variable de entorno o parámetro de celda.

---

## NB1 — Pipeline de análisis estadístico (reproduce `§11`)

**Archivo destino:** `airsim-loop/notebooks/nb1_analisis_estadistico.ipynb`

**Propósito:** notebook ejecutable que replique de forma transparente y reproducible todas las
tablas y cifras de `informe/11-RESULTADOS.md`, mostrando cada cálculo con código visible.

### Estructura de celdas

#### Sección 0 — Configuración
```
[MD]  Cabecera: propósito, fuentes, cómo ejecutar
[CODE] imports: pandas, numpy, scipy.stats, matplotlib/seaborn, pathlib
[CODE] RUNS_DIR = os.environ.get("RUNS_DIR", "../airsim-runs")
       MISSIONS_DIR = os.environ.get("MISSIONS_DIR", "../airsim-loop/missions")
```

#### Sección 1 — Carga de datos
```
[MD]  §1: Carga de summary.json
[CODE] load_summaries(runs_dir) → DataFrame con una fila por corrida
       Columnas: scenario, arm, seed, success, duration_s, path_length_m,
                 min_obstacle_dist_m, slm_invocations, deliberation_rate,
                 slm_fallback_rate, deadlock_events, deadlock_strategy, code_version
[CODE] Mostrar .info() y .head(10) del DataFrame resultante
[CODE] load_optimal_lengths(missions_dir) → dict{scenario: float}
[CODE] Agregar columna spl = L_opt / max(L_recorrida, L_opt) según Anderson et al. 2018
```

#### Sección 2 — Tabla §11.1: resultados por tier (media ± σ)
```
[MD]  §2: Agregación por (arm, scenario) — reproduce tablas Tier 0/1/2 de §11.1
[CODE] group = df.groupby(["arm","scenario"])
       stats = group["duration_s"].agg(["mean","std"])  # + dist, deadlocks, invoc.
[CODE] Tabla pivoteada: una sub-tabla por escenario, brazos como filas
[CODE] Verificación: comparar con valores de 11-RESULTADOS.md (assert dentro de ±0.1 s)
```

#### Sección 3 — Tabla §11.2: resumen cruzado por brazo y escenario
```
[MD]  §3: Tabla §11.2 — col/km, DistMin, Deliberación, Fallback, Ratio vs reactive
[CODE] Calcular ratio = mean_duration[arm] / mean_duration["reactive"] por escenario
[CODE] Generar DataFrame con todas las combinaciones (incluye [pendiente] para escenarios futuros)
```

#### Sección 4 — Tabla §11.3.1: ratios de tiempo de misión (H2)
```
[MD]  §4: Ratios slm/reactive y fsm/reactive — tabla §11.3.1
[CODE] pivot por arm para cada escenario; calcular ratios
[CODE] Gráfico de línea: ratio vs. longitud de ruta (muestra la dilución del overhead)
```

#### Sección 5 — Prueba Mann-Whitney + Cliff's δ (§11.3.2)
```
[MD]  §5: Test de Mann-Whitney U bilateral, corrección de Bonferroni, Cliff's δ
[MD]  Explicación: por qué K=5 impone un p mínimo de 7.9×10⁻³ y no puede superar
      Bonferroni con α_ajustado=0.0028
[CODE] Para cada par (slm/reactive, fsm/reactive, slm/fsm) × escenario:
         stat, p = mannwhitneyu(a, b, alternative="two-sided")
         p_bonf = min(p * n_comparaciones, 1.0)  # n=18
         delta = cliffs_delta(a, b)               # implementar desde cero
[CODE] Función cliffs_delta(x, y): mean(sign(xi - yj) for xi in x for yj in y)
[CODE] Generar tabla igual a §11.3.2 con columnas U, z, p, p(Bonf.), δ, Significancia
[CODE] Gráfico: distribución de tiempos por arm/escenario (boxplot o strip)
```

#### Sección 6 — Perfil de deliberación (§11.3.3)
```
[MD]  §6: Invocaciones VLM, tasa deliberación, dist/invocación — tabla §11.3.3
[CODE] Calcular dist_per_invocation = path_length_m / max(slm_invocations, 1)
[CODE] Gráfico: invocaciones y ratio vs. longitud de ruta (tres puntos, regresión)
```

#### Sección 7 — Latencia por ciclo (de JSONL)
```
[MD]  §7: Latencia p50/p95 por (arm, route) — requiere leer ciclos individuales
[CODE] load_cycles(runs_dir) → DataFrame de ciclos con latency_ms_graph, route, arm
[CODE] Tabla y boxplot de latencias por ruta (keep_going / evasive / deliberative / fsm)
```

#### Sección 8 — Análisis townsim_ini (§11.4.2b)
```
[MD]  §8: Escenario de falla — distancia recorrida antes del timeout (0/15 éxitos)
[CODE] Filtrar scenario == "townsim_ini"; métrica = path_length_m en lugar de success
[CODE] Boxplot de distancia recorrida por arm
[CODE] Tabla: media ± σ de distancia, deadlocks, DistMin
```

#### Sección 9 — Exportación
```
[CODE] Guardar todas las tablas como CSV en notebooks/output/
[CODE] Guardar figuras como PNG en notebooks/output/figures/
```

### Dependencias Python
```
pandas >= 2.0, numpy, scipy, matplotlib, seaborn, jupyter
```

---

## NB2 — Exploración interactiva de logs de auditoría

**Archivo destino:** `airsim-loop/notebooks/nb2_auditoria.ipynb`

**Propósito:** notebook para cargar un run completo (un `.jsonl` o su `.csv` paralelo),
visualizar la traza temporal de cada variable y reproducir lo que muestra `viewer.html`
en forma analizable con Python — con acceso a todos los campos, no solo los visibles en la
vista compacta del viewer.

### Estructura de celdas

#### Sección 0 — Selección de corrida
```
[MD]  Instrucciones: apuntar a un directorio de corrida o a un archivo .jsonl/.csv
[CODE] RUN_PATH = "../../airsim-runs/..."   # cambiar aquí
       # Detectar si es .jsonl o .csv y cargar apropiadamente
[CODE] df = load_jsonl(RUN_PATH) si .jsonl, else pd.read_csv(RUN_PATH)
[CODE] Mostrar metadata: scenario, arm, seed, success, duración, ciclos
```

#### Sección 1 — Vista temporal de la traza de control
```
[MD]  §1: Traza de route (nodo activo) a lo largo del tiempo
[CODE] Mapa de colores por route: keep_going=verde, evasive=naranja, 
       deliberative=azul, girar_90=rojo, fsm=morado
[CODE] Gráfico de barras apiladas o imshow por ciclo; eje X = tiempo (s)
[CODE] Superponer: dist_to_wp_m en eje secundario
```

#### Sección 2 — ObstacleField en el tiempo
```
[MD]  §2: Señal de percepción por sector (izquierda / centro / derecha)
[CODE] Parsear field_* columns (o obstacle_field JSON en JSONL)
[CODE] Subplots: occupancy, ttc_s, confidence, blocked por sector vs. tiempo
[CODE] Marcar en rojo los ciclos donde centro bloqueado
```

#### Sección 3 — Eventos SLM / deliberación
```
[MD]  §3: Cuándo y cómo delibera el SLM
[CODE] Filtrar ciclos donde slm_invoked == True
[CODE] Mostrar: slm_prompt (truncado a 120 chars), slm_raw_response, slm_adherent
[CODE] Timeline: barras verticales en los ciclos de invocación SLM
[CODE] Distribución de slm_latency_ms (histograma + p50/p95)
```

#### Sección 4 — Eventos de deadlock y resolución
```
[MD]  §4: Atascos y resolución por deep_vlm
[CODE] Detectar transiciones route == "girar_90" o cambios abruptos de wp_index
[CODE] Para cada deadlock: ciclos de duración, resolución (sí/no), ciclos hasta resolución
[CODE] Tabla: evento, ciclo_inicio, ciclo_fin, duración_ciclos, resuelto
```

#### Sección 5 — Trayectoria 2D
```
[MD]  §5: Posición XY del dron a lo largo de la corrida
[CODE] Scatter plot pos_x vs. pos_y, coloreado por route
[CODE] Superponer waypoints del manifiesto (leer desde missions/)
[CODE] Marcar posiciones en deadlock con X
```

#### Sección 6 — Latencia por ciclo
```
[MD]  §6: Latencia del grafo por ciclo (latency_ms_graph) y picos
[CODE] Serie temporal de latency_ms (del JSON latency_ms_json o campo JSONL)
[CODE] Marcar ciclos > p95 como picos; correlacionar con route activa
```

#### Sección 7 — Comparar dos corridas (misma semilla, brazos distintos)
```
[MD]  §7: Modo comparación — cargar dos runs del mismo scenario/seed, arms distintos
[CODE] RUN_A = "..."  # slm
       RUN_B = "..."  # fsm o reactive
[CODE] Comparar: traza de route, dist_to_wp, ObstacleField en los mismos timestamps
[CODE] Diferencia de tiempo de misión, deadlocks, DistMin
```

### Dependencias Python
```
pandas, numpy, matplotlib, json, pathlib, ipywidgets (opcional para slider)
```

---

## NB3 — Traza didáctica del grafo LangGraph (ciclo a ciclo)

**Archivo destino:** `airsim-loop/notebooks/nb3_langgraph_traza.ipynb`

**Propósito:** notebook pedagógico que toma una fila del CSV de auditoría y reproduce
exactamente qué nodo del `StateGraph` se activaría en ese ciclo, con qué estado de entrada
y qué estado de salida produciría — sin necesitar AirSim corriendo. Útil para explicar la
lógica de control en la defensa de tesis.

### Concepto central

```
Una fila del CSV = un ciclo completo del grafo.
El grafo ejecuta: capture → [degraded_hover | perception] → policy_router → nodo_activo → motor → END
El notebook "replay" ese ciclo con datos reales en lugar de datos de AirSim en vivo.
```

### Estructura de celdas

#### Sección 0 — Importar el grafo real
```
[MD]  §0: Importamos el grafo de producción (src/agents/graph.py) en modo dry-run
[CODE] import sys; sys.path.insert(0, "../src")
[CODE] from agents.graph import build_workflow, DroneState
       # build_workflow acepta arm="slm"|"fsm"|"reactive"
[CODE] # Monkey-patch de los nodos que necesitan hardware real:
       #   - capture_node: reemplazar con función que devuelve estado del CSV
       #   - motor_node: reemplazar con no-op que imprime el comando resultante
       #   - deliberation_service: reemplazar con mock que devuelve slm_raw_response del CSV
```

#### Sección 1 — Cargar el CSV y seleccionar una fila
```
[MD]  §1: Selección del ciclo a trazar
[CODE] CSV_PATH = "../../airsim-runs/.../seed_N.csv"
       df = pd.read_csv(CSV_PATH)
[CODE] # Selector: ciclo de interés (ej: un ciclo deliberativo, uno evasivo, uno con deadlock)
       CYCLE = 42   # ← cambiar aquí; mostrar df.iloc[CYCLE] completo
[CODE] row = df.iloc[CYCLE]
       print(f"Ciclo {row['cycle']} | arm={row['arm']} | route={row['route']} "
             f"| action={row['action']} | dist_to_wp={row['dist_to_wp_m']:.1f}m")
```

#### Sección 2 — Reconstruir el DroneState desde la fila
```
[MD]  §2: El DroneState es el diccionario que el grafo pasa de nodo en nodo
[CODE] def row_to_state(row) -> DroneState:
           """Reconstruye el estado de entrada al ciclo desde una fila CSV."""
           return DroneState(
               pos={"x": row.pos_x, "y": row.pos_y, "z": row.pos_z},
               vel={"vx": row.vel_x, "vy": row.vel_y, "vz": row.vel_z},
               yaw_deg=row.yaw_deg,
               wp_index=int(row.wp_index),
               dist_to_wp_m=row.dist_to_wp_m,
               obstacle_field=parse_obstacle_field(row),  # reconstruir del CSV
               arm=row.arm,
               route=row.route,          # estado previo del ciclo anterior
               action=None,              # se llenará por el nodo activo
               # ... resto de campos con valores del CSV o defaults
           )
```

#### Sección 3 — Diagrama del grafo
```
[MD]  §3: Arquitectura del StateGraph — todos los nodos y edges condicionales
[CODE] # Generar diagrama Mermaid del grafo
       diagram = """
       graph TD
           capture --> degraded_router{degraded?}
           degraded_router -->|sí| degraded_hover --> capture
           degraded_router -->|no| perception
           perception --> policy_router{arm + state}
           policy_router -->|reactive| keep_going
           policy_router -->|slm, libre| deliberative
           policy_router -->|evasiva activa| evasive
           policy_router -->|girar| girar_90
           policy_router -->|fsm| fsm
           keep_going --> motor
           deliberative --> motor
           evasive --> motor
           girar_90 --> motor
           fsm --> motor
           motor --> END
       """
[CODE] from IPython.display import display, Markdown
       display(Markdown(f"```mermaid\n{diagram}\n```"))
```

#### Sección 4 — Traza del ciclo seleccionado (paso a paso)
```
[MD]  §4: Ejecución paso a paso del ciclo seleccionado
[CODE] # Hook de traza: interceptar cada nodo antes y después de ejecutar
       execution_trace = []

       def make_traced_node(name, fn):
           def traced(state):
               print(f"\n{'─'*60}")
               print(f"NODO: {name}")
               print(f"  Entrada relevante:")
               print_relevant_state(state, name)
               out = fn(state)
               print(f"  Salida (campos modificados):")
               print_state_diff(state, out)
               execution_trace.append({"node": name, "in": state, "out": out})
               return out
           return traced
[CODE] # Ejecutar el ciclo con nodos tracificados (capture ya parchado con datos del CSV)
       result = workflow.invoke(initial_state)
```

#### Sección 5 — Análisis de la decisión tomada
```
[MD]  §5: ¿Por qué el policy_router eligió este nodo?
[CODE] # Mostrar los valores exactos que dispararon el router:
       #   - arm (env var / campo del CSV)
       #   - route anterior (committed evasive?)
       #   - obstacle_field.centro.blocked
       #   - obstacle_field.centro.ttc_s vs. TTC_EVASIVE_THRESHOLD
       #   - dist_to_wp_m vs. WP_ARRIVAL_THRESHOLD
[CODE] print_decision_tree(initial_state)   # función que muestra cada condición y su valor
```

#### Sección 6 — Comparar la decisión real vs. la reproducida
```
[MD]  §6: Verificación — la fila CSV registró route={row.route}; ¿el notebook reproduce lo mismo?
[CODE] reproduced_route = result["route"]
       expected_route = row["route"]
       match = reproduced_route == expected_route
       print(f"Route reproducida: {reproduced_route}")
       print(f"Route registrada:  {expected_route}")
       print(f"{'✅ Match' if match else '⚠️ Divergencia — revisar mock de estado'}")
```

#### Sección 7 — Recorrido de múltiples ciclos consecutivos
```
[MD]  §7: Traza de una ventana de ciclos (ej: los 20 ciclos alrededor de un deadlock)
[CODE] WINDOW_START = 100; WINDOW_END = 120
       for i in range(WINDOW_START, WINDOW_END):
           row_i = df.iloc[i]
           state_i = row_to_state(row_i)
           result_i = workflow_silent.invoke(state_i)  # sin prints internos
           print(f"Ciclo {i:4d} | route={result_i['route']:<14} | action={result_i['action']:<20} "
                 f"| centro_blocked={row_i['field_centro_blocked']} "
                 f"| ttc={row_i['field_centro_ttc_s']:.1f}s")
```

#### Sección 8 — Casos de uso pedagógicos preconfigurados
```
[MD]  §8: Escenarios de ejemplo (seleccionar uno cambiando PRESET)
       - PRESET="libre": ciclo keep_going sin obstáculos
       - PRESET="deliberativo": ciclo con consulta al SLM activa
       - PRESET="evasivo": ciclo en ejecución de maniobra evasiva
       - PRESET="deadlock": ciclo de detección de atasco
       - PRESET="deep_vlm": ciclo de resolución de atasco por escaneo 360°
[CODE] PRESET = "deliberativo"
       CYCLE = PRESETS[PRESET]  # diccionario con ciclos representativos del CSV cargado
```

### Dependencias Python
```
pandas, numpy, pathlib, IPython
# El grafo de producción: sys.path a airsim-loop/src/
# No requiere AirSim, MSBuild, ni GPU — solo los mocks de capture y motor
```

### Nota sobre los mocks

Los nodos que necesitan hardware real se parchean con funciones que leen del CSV:

| Nodo original | Mock en NB3 |
|---|---|
| `capture_node` | devuelve imagen None + estado del CSV; frame_history se llena con Nones |
| `motor_node` | imprime `execute_velocity(vx,vy,vz,yaw_rate)` sin llamar a AirSim |
| `DeliberationService.get_decision()` | devuelve `slm_raw_response` y `slm_adherent` del CSV |
| `FlowTTCEstimator.estimate()` | devuelve el `ObstacleField` reconstruido de los campos `field_*` del CSV |

El grafo real (`graph.py`) **no se modifica** — solo se parchean las dependencias externas
mediante monkey-patching en el notebook. Esto garantiza que la lógica de control tracificada
es exactamente la de producción.

---

## Orden de implementación

| Prioridad | Notebook | Motivo |
|---|---|---|
| 1 | NB1 | Directamente ligado a `11-RESULTADOS.md`; necesario para la defensa |
| 2 | NB3 | Alta carga pedagógica; explica la arquitectura a evaluadores no técnicos |
| 3 | NB2 | Útil para análisis exploratorio pero duplica parte de NB1 |

## Directorio de salida

```
airsim-loop/
  notebooks/
    nb1_analisis_estadistico.ipynb
    nb2_auditoria.ipynb
    nb3_langgraph_traza.ipynb
    output/
      *.csv          — tablas exportadas
      figures/
        *.png        — gráficos para el informe
```

---

## Relación con los scripts existentes

| Script | Relación con los notebooks |
|---|---|
| `experiments/analyze.py` | NB1 reimplementa su lógica con pandas; añade Bonferroni, δ, y gráficos |
| `experiments/analyze_tesis_results.py` | NB1 incorpora sus tablas por escenario |
| `experiments/analyze_occupancy.py` | NB2 §2 extiende su análisis interactivamente |
| `experiments/analyze_ttc.py` | NB2 §2 integra su análisis de TTC por sector |
| `src/logging/flight_viewer.py` | NB2 es el equivalente Python del viewer HTML |
| `src/agents/graph.py` | NB3 importa y parchea el grafo de producción |
