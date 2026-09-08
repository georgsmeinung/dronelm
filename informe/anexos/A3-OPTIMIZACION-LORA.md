> **Nota de ubicación:** este documento constituye el estudio formal y la especificación metodológica de la especialización de Modelos de Visión y Lenguaje Pequeños (*Small Vision-Language Models*, sVLMs) mediante técnicas de Ajuste Fino Eficiente en Parámetros (*Parameter-Efficient Fine-Tuning*, PEFT / LoRA / QLoRA). Sirve como referencia técnica complementaria para el capítulo 8 (`08-DECISIONES-SLM.md`, §8.7), el capítulo 12 (`12-CONCLUSIONES.md`, §12.4) y los anexos A1, A2 y A4. Estructurado como la especificación de trabajo futuro y hoja de ruta de optimización del nodo deliberativo de DroneLM.

---

# Anexo 3: Optimización y especialización de modelos de visión-lenguaje mediante LoRA/QLoRA para navegación aérea autónoma

La arquitectura deliberativa desarrollada en esta tesis adopta un modelo multimodal de pesos abiertos de 3 mil millones de parámetros (**Qwen2.5-VL-3B-Instruct**; Qwen Team, 2025) ejecutado localmente bajo cuantización Q4_K_M en un entorno con recursos de cómputo y memoria de video acotados (§8.1). En la versión evaluada en el lazo táctico de control, dicho modelo opera en régimen *zero-shot / in-context learning*, guiado por un prompt estructurado de cinco componentes (§8.5) y acoplado a un motor de decodificación gramaticalmente restringida por esquema JSON (§8.2, Anexo 4; Willard & Louf, 2023).

Si bien esta configuración resuelve con éxito la extracción de semántica visual y el rescate ante fallas del estimador de flujo óptico (§6.12), introduce dos limitaciones operativas para el vuelo reactivo:
1. **Sobrecarga de latencia por longitud de contexto (*prompt overhead*):** verbalizar la telemetría, el resumen del campo de obstáculos (`ObstacleField`), el historial de maniobras y las instrucciones sintácticas insume entre 400 y 600 tokens de entrada por ciclo. Esto eleva la fase de pre-llenado (*pre-fill*), empujando la latencia de inferencia hacia la frontera del perro guardián del sistema (`SLM_WATCHDOG_MS = 1500 ms`).
2. **Dependencia de restricciones externas de muestreo:** el modelo preentrenado retiene sesgos conversacionales y un amplio espacio léxico generalista, lo que exige filtrar activamente sus *logits* en cada token mediante gramáticas para asegurar el cumplimiento de la lista blanca de macro-acciones (§8.3).

Este anexo desarrolla los fundamentos matemáticos y metodológicos de **Adaptación de Bajo Rango (LoRA; Hu et al., 2022)** y sus extensiones contemporáneas (**QLoRA; Dettmers et al., 2024** y **DoRA; Liu et al., 2024**) como línea de trabajo futuro (§12.4): internalizar el dominio físico-espacial y el formato estricto directamente en los tensores de ponderación de la red, habilitando respuestas en tiempo real (< 500 ms) sin alterar la arquitectura base ni requerir hardware de nivel servidor.

---

## A3.1 Fundamentos matemáticos y variantes avanzadas de PEFT

El ajuste fino completo (*Full Fine-Tuning*, FFT) de una red neuronal profunda requiere actualizar y almacenar en memoria los gradientes y momentos del optimizador (e.g., AdamW en precisión simple FP32) para la totalidad de los parámetros entrenables $\Phi_0$. Para un modelo de 3B parámetros, esto demanda más de 24 GB de VRAM únicamente para el estado del optimizador, tornando inviable el entrenamiento en GPUs de escritorio (tales como la NVIDIA RTX 5060 de 8 GB utilizada en este proyecto).

Las técnicas de Ajuste Fino Eficiente en Parámetros (*Parameter-Efficient Fine-Tuning*, PEFT; Mangrulkar et al., 2022) resuelven este cuello de botella congelando la red preentrenada y acoplando un conjunto microscópico de parámetros adaptativos.

```
       Flujo de Inferencia Estándar                Adaptación de Bajo Rango (LoRA)
       
              Entrada: x                                    Entrada: x
                  │                                             ├─────────────────────┐
                  ▼                                             ▼                     ▼
         ┌─────────────────┐                           ┌─────────────────┐   ┌─────────────────┐
         │  Matriz Base    │                           │  Matriz Base    │   │ Adaptador A     │
         │  W₀ ∈ ℝ^(d×k)   │ (Congelada)               │  W₀ ∈ ℝ^(d×k)   │   │ A ∈ ℝ^(r×k)     │
         └────────┬────────┘                           └────────┬────────┘   └────────┬────────┘
                  │                                             │                     │
                  ▼                                             │                     ▼
              Salida: h                                         │            ┌─────────────────┐
               h = W₀·x                                         │            │ Adaptador B     │
                                                                │            │ B ∈ ℝ^(d×r)     │
                                                                │            └────────┬────────┘
                                                                │                     │ Escala: (α/r)
                                                                ▼                     ▼
                                                               ┌────────────────────────┐
                                                               │  Suma: h = W₀·x + ΔW·x │
                                                               └────────────────────────┘
```

### A3.1.1 Formulación matemática de LoRA
La premisa matemática de LoRA (Hu et al., 2022) se basa en la hipótesis de que las actualizaciones de peso $\Delta W$ durante la adaptación a una tarea especializada exhiben un «rango intrínseco» muy bajo (*low intrinsic dimension*). Para una matriz lineal preentrenada $W_0 \in \mathbb{R}^{d \times k}$, la actualización se descompone como el producto de dos matrices de bajo rango:

$$W = W_0 + \Delta W = W_0 + \frac{\alpha}{r} (B \cdot A)$$

donde:
* $r \ll \min(d, k)$ es el hiperparámetro de **rango intrínseco** (típicamente $r \in [8, 32]$).
* $B \in \mathbb{R}^{d \times r}$ se inicializa estrictamente en ceros ($B = 0$).
* $A \in \mathbb{R}^{r \times k}$ se inicializa con una distribución normal gaussiana aleatoria $A \sim \mathcal{N}(0, \sigma^2)$, con $\sigma = \frac{1}{r}$.
* $\alpha \in \mathbb{R}^+$ es una constante de escala que atenúa o amplifica el impacto de la adaptación sin requerir reajustar la tasa de aprendizaje (*learning rate*) al modificar $r$.

**Propiedad de preservación funcional:** gracias a la inicialización $B = 0$, en el paso inicial de entrenamiento se cumple que $\Delta W = 0 \cdot A = 0$. Por lo tanto, $W = W_0$ y el comportamiento inicial del modelo es matemáticamente idéntico al modelo preentrenado de fábrica, evitando saltos destructivos en los pesos durante las primeras iteraciones.

### A3.1.2 Selección de módulos objetivo en arquitecturas multimodales
En modelos basados en Transformer, las proyecciones lineales se dividen entre el bloque de autoatención (*Multi-Head Attention*) y el perceptrón multicapa (*Feed-Forward Network* / MLP):
* **Atención:** matrices de consulta ($W_q$), clave ($W_k$), valor ($W_v$) y proyección de salida ($W_o$).
* **MLP:** matrices de compuerta ($W_{\text{gate}}$), subida ($W_{\text{up}}$) y bajada ($W_{\text{down}}$).

Para modelos multimodales (sVLMs como Qwen2.5-VL), existe una disyuntiva de diseño crítica:
1. **Codificador visual (*Vision Transformer*, ViT):** procesa los parches de píxeles brutos de la cámara monocular. Adaptar el ViT con LoRA introduce el riesgo de destruir filtros de detección de bordes y texturas universales ante conjuntos de datos de vuelo acotados. Por ello, la práctica recomendada consiste en **mantener el ViT congelado**.
2. **Proyector multimodal y capas del LLM autorregresivo:** adaptar $W_q, W_v$ y las capas lineales del MLP permite al modelo remapear las representaciones visuales hacia la lógica de control del dron. La literatura empírica demuestra que incorporar tanto los módulos de atención como los del bloque MLP ($W_{\text{gate}}, W_{\text{up}}, W_{\text{down}}$) con rangos moderados ($r=16$) supera consistentemente a adaptar únicamente $W_q$ con rangos mayores ($r=64$).

### A3.1.3 QLoRA: cuantización en 4 bits y optimizadores paginados
Para posibilitar la sintonización en hardware de desarrollo restringido, Dettmers et al. (2024) introdujeron **QLoRA**, una extensión que combina tres innovaciones clave:
* **Formato NormalFloat4 (NF4):** un tipo de datos no lineal de 4 bits con espaciado óptimo para representar tensores con distribución normal estándar centrada en cero, conservando un error de cuantización teóricamente menor que el formato entero uniforme INT4.
* **Doble Cuantización (*Double Quantization*):** proceso que cuantiza las propias constantes de escala de cuantización del modelo (de FP32 a FP8 en bloques de 256 elementos), ahorrando un promedio de 0.37 bits por parámetro (~370 MB en un modelo de 3B).
* **Optimizadores Paginados (*Paged Optimizers*):** integración con CUDA Memory Management para trasladar dinámicamente los estados de memoria de la GPU a la memoria RAM del sistema operativo durante picos transitorios de gradientes, previniendo fallos por memoria agotada (*Out-Of-Memory*, OOM).

En este esquema, el modelo base $W_0$ reside en VRAM cuantizado en 4 bits NF4 ($~1.8\text{ GB}$ para 3B), mientras que los adaptadores $A$ y $B$ se mantienen y optimizan en precisión bfloat16 ($~25\text{ MB}$).

### A3.1.4 DoRA: adaptación desacoplada en magnitud y dirección
Liu et al. (2024) observaron una discrepancia estructural en la dinámica de gradientes: mientras que el ajuste completo (FFT) modifica tanto la magnitud como la dirección de los vectores de pesos de forma desbalanceada e independiente, LoRA exhibe un acoplamiento simétrico entre ambas dimensiones.

Para solventar esta limitación, **DoRA (*Weight-Decomposed Low-Rank Adaptation*)** factoriza cada columna de la matriz de ponderación $W \in \mathbb{R}^{d \times k}$ en su vector de magnitud de norma euclidiana $m \in \mathbb{R}^{1 \times k}$ y su matriz direccional unitaria normalizada $V \in \mathbb{R}^{d \times k}$:

$$W = m \odot \frac{V}{\|V\|_c} = m \odot \frac{W_0 + \Delta W}{\|W_0 + \Delta W\|_c}$$

donde $\| \cdot \|_c$ denota la norma $L_2$ a lo largo de las columnas y $\Delta W = \frac{\alpha}{r} B A$. DoRA permite que el gradiente ajuste la escala global de activación ($m$) independientemente de las reorientaciones vectoriales ($\Delta W$), logrando una capacidad de modelado que equipara prácticamente a FFT en tareas espaciales y de razonamiento lógico, manteniendo la ventaja de poder fusionarse íntegramente en inferencia sin penalización de velocidad.

### A3.1.5 Comparativa de paradigmas de ajuste fino para sVLMs

| Dimensión | Full Fine-Tuning (FFT) | LoRA estándar | QLoRA (NF4) | DoRA |
|---|---|---|---|---|
| **VRAM entrenamiento (3B)** | > 24 GB | ~12–14 GB | **~5.5–7.0 GB** | ~6.5–8.0 GB |
| **Parámetros entrenables** | 100% (~3.090 M) | ~0.15–0.30% (~5–10 M) | ~0.15–0.30% (~5–10 M) | ~0.20–0.35% (~6–11 M) |
| **Precisión pesos base** | FP16 / BF16 | FP16 / BF16 | **NF4 (4 bits)** | NF4 / FP16 |
| **Sobrecarga en inferencia** | Cero (pesos nativos) | Cero (tras fusión) | Cero (tras fusión + quant) | Cero (tras fusión) |
| **Fidelidad respecto a FFT** | Referencia (100%) | 92–95% | 91–94% | **97–99%** |
| **Viabilidad en GPU 8 GB** | No viable | Crítico / Marginal | **Plenamente viable** | **Plenamente viable** |

---

## A3.2 Justificación técnica: impacto de LoRA en el lazo táctico de DroneLM

La integración de un adaptador LoRA en el nodo deliberativo transforma la interfaz entre el modelo de lenguaje y el sistema ciberfísico:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        ARQUITECTURA DEL NODO DELIBERATIVO                              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   FASE ACTUAL (In-Context Zero-Shot + Gramáticas):                                     │
│   [ Telemetría + Resumen ObstacleField + Historial + Instrucción Schema ] ~500 tokens  │
│                                       │                                                │
│                                       ▼                                                │
│                 [ Qwen2.5-VL-3B Base (Pesos Genéricos Congelados) ]                    │
│                                       │ (Logits dispersos)                             │
│                                       ▼                                                │
│                 [ Filtro de Gramática json_schema (Outlines/GBNF) ]                    │
│                                       │ (Forzado externo)                              │
│                                       ▼                                                │
│                       { "action": "evasive", "reason": "..." }                         │
│                               Latencia: 850 - 1400 ms                                  │
│                                                                                        │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   FASE PROPUESTA OPTIMIZADA (Adaptador LoRA / QLoRA Fusionado):                        │
│   [ Frames (t, t-1) + Tupla Compacta de Estado + TTC ]                    ~90 tokens   │
│                                       │                                                │
│                                       ▼                                                │
│                 [ Qwen2.5-VL-3B + Adaptador LoRA Especializado ]                       │
│                                       │ (Logits intrínsecamente alineados)             │
│                                       ▼                                                │
│                 [ Verificación Pasiva de Esquema (json_schema) ]                       │
│                                       │                                                │
│                                       ▼                                                │
│                       { "action": "evasive", "reason": "..." }                         │
│                               Latencia: 300 - 550 ms                                   │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### A3.2.1 Reducción del presupuesto de tokens y compresión de latencia
En la implementación *zero-shot* de referencia (§8.5), el prompt de usuario debe reiterar en cada invocación:
* Las definiciones semánticas de los sectores del sensor (`SECTOR_FRONTAL`, `SECTOR_LATERAL`).
* La sintaxis exacta y el orden de los campos del esquema JSON.
* La lista cerrada de macro-acciones admisibles (`keep_going`, `evasive`, `girar_90`, `fsm`, `degraded`).

Este contexto insume cientos de tokens de procesamiento previo (*prefill*). Al especializar el modelo con LoRA, **la gramática de salida y las reglas de dominio quedan cristalizadas en los tensores de ponderación**. El prompt de entrada puede simplificarse a una codificación tabular mínima:

```
[ESTADO: Vz=-0.1, Vh=3.2 | TTC: F=1.4s, L=inf, R=4.1s | HIST: keep_going(x3) | REASON: TTC_CRITICO]
```

Esta reducción comprime la ventana de entrada de ~500 a menos de 100 tokens, acelerando el tiempo de respuesta del modelo en un 60%, garantizando que la inferencia opere de forma consistente entre 300 ms y 550 ms, muy por debajo de los 1500 ms del perro guardián.

### A3.2.2 Alineación causal directa: de la imagen a la maniobra
Un modelo generalista tiende a verbalizar descripciones visuales pasivas (*«Veo un muro con sombras proyectadas»*). LoRA permite reentrenar la distribución de probabilidad condicional $P(y \mid X)$ para que el modelo efectúe una **asociación sensoriomotora directa**:
* Reconocer cómo el patrón de divergencia óptica entre $I_t$ e $I_{t-1}$ anticipa colisiones inminentes.
* Discriminar si una región oscura corresponde a una sombra sobre el pavimento (transitable) o a un obstáculo sólido en el volumen de vuelo (no transitable), suprimiendo alucinaciones visuales que el flujo monocular no logra desagregar (§6.1).

---

## A3.3 Pipeline de ingeniería de datos para navegación aérea

El factor determinante del éxito de la adaptación no radica en el volumen de parámetros, sino en la calidad informativa y la diversidad topológica del conjunto de datos de entrenamiento.

### A3.3.1 Estructura del dataset multimodal de navegación
Cada instancia de entrenamiento se define como un par supervisado $(X_t, Y_t)$ estructurado de la siguiente forma:

$$X_t = \left\{ I_t, I_{t-1}, \text{telemetry}_t, \text{obstacle\_field}_t, \text{reason\_note}_t \right\}$$

$$Y_t = \left\{ \text{"action"}: a_t^*, \text{"reason"}: r_t^* \right\}$$

donde:
* $I_t, I_{t-1}$ son los dos fotogramas RGB monoculares recientes capturados a 640×360 píxeles.
* $\text{telemetry}_t$ incluye el vector de velocidad tridimensional, ángulo de cabeceo (*pitch*), alabeo (*roll*) y distancia al waypoint activo.
* $\text{obstacle\_field}_t$ codifica el TTC estimado y la tasa de ocupación por sector angular (cap. 6 y 7).
* $a_t^* \in \mathcal{A}_{\text{whitelist}}$ es la macro-acción supervisada óptima.
* $r_t^*$ es una cadena de justificación condensada (< 120 caracteres) que verbaliza el razonamiento causal subyacente (e.g., `"TTC crítico de 1.2s en cuadrante frontal-izquierdo; espacio despejado a la derecha; iniciar maniobra evasiva"`).

### A3.3.2 Mitigación de la deriva cinemática mediante DAgger
El entrenamiento mediante simple Clonación de Comportamiento (*Behavioral Cloning*, BC) a partir de vuelos nominales perfectos sufre del problema de **deriva covariada (*Covariate Shift*)** (Codevilla et al., 2019): ante el menor error acumulado de predicción, el vehículo ingresa en estados cinemáticos no presentes en el conjunto de entrenamiento, colapsando en decisiones divergentes.

Para inmunizar al modelo frente a este fenómeno, se define la aplicación del algoritmo **DAgger (*Dataset Aggregation*; Ross et al., 2011)** adaptado a simulación en AirSim / Unreal Engine 5:
1. **Vuelo con política actual** $\pi_{\text{LoRA}}$ en AirSim UE5.5 bajo perturbaciones controladas (ráfagas de viento sintéticas, desviaciones forzadas).
2. **Consulta al oráculo experto** (FSM determinista o supervisor experto) ante desvíos: determinación de la acción correctiva óptima $a^*$.
3. **Agregación de tuplas críticas** $\mathcal{D}_{\text{total}} = \mathcal{D}_{\text{previo}} \cup \{(X_{\text{perturbado}}, a^*_{\text{experto}})\}$.
4. **Reentrenamiento iterativo** de los adaptadores LoRA sobre el conjunto enriquecido.

### A3.3.3 Aumentación sintética y métricas objetivo de evaluación
Para evitar el sobreajuste a texturas específicas de los mapas virtuales de Unreal Engine (Neighborhood, Manhattan; cap. 3 y 10), el conjunto de datos se somete a aumentaciones dinámicas: variación de la hora solar en UE5, degradación atmosférica sintética (niebla y dispersión lumínica; Marazzato & Sparavigna, 2015) y desenfoque por movimiento angular (*motion blur*).

| Métrica de Validación | Meta Operativa (Zero-Shot Actual) | Meta Objetivo (LoRA / QLoRA) |
|---|---|---|
| **Cumplimiento de Esquema JSON** | 99.8% (gracias a gramática forzada) | **100% nativo** (verificación pasiva) |
| **Latencia media de inferencia** | ~1100 ms (límite de watchdog) | **< 450 ms** (margen amplio) |
| **Tokens de entrada promedio** | 480–520 tokens | **< 100 tokens** |
| **Tasa de resolución de atasco** | 60.0% (Tier 3, cap. 10) | **> 85.0%** |
| **Tasa de colisiones evitables** | 20.0% en Tier 3 | **< 5.0%** |

---

## A3.4 Fusión de pesos, despliegue y preservación de la seguridad híbrida

### A3.4.1 Fusión algebraica de pesos (*Weight Merging*) y exportación
Una de las ventajas arquitectónicas centrales de LoRA frente a otros esquemas modulares radica en la posibilidad de **fusionar algebraicamente los adaptadores con los pesos base preentrenados** antes del despliegue en el vehículo:

$$W_{\text{despliegue}} = W_0 + \frac{\alpha}{r} (B \cdot A)$$

Al realizar la fusión de tensores en punto flotante previo (FP16 o BF16), la matriz resultante $W_{\text{despliegue}}$ adquiere exactamente las mismas dimensiones y topología que la red preentrenada original. No existe ninguna bifurcación de memoria ni sobrecarga computacional adicional durante la inferencia. 

Posteriormente, el modelo fusionado se compila a formato **GGUF** cuantizado (`Q4_K_M`) mediante `llama.cpp` (Gerganov, 2023), produciendo un binario de ~2.0 GB listo para ejecución local embebida sin dependencias de librerías de entrenamiento.

### A3.4.2 Sinergia entre LoRA y decodificación restringida (`json_schema`)
El ajuste fino no reemplaza la decodificación restringida por gramáticas (§8.2, Anexo 4), sino que la complementa:
* **LoRA moldea la distribución interna de logits:** el modelo aprende a concentrar prácticamente el 100% de su masa de probabilidad en las palabras clave del esquema JSON y la lista blanca de macro-acciones.
* **`json_schema` opera como barrera determinista externa:** enmascara el residuo infinitesimal de probabilidad en situaciones fuera de distribución, garantizando formalmente cero violaciones de formato.
* **Aceleración de generación:** al fluir la decodificación sin colisionar con tokens suprimidos por la gramática, la tasa de muestreo alcanza el máximo rendimiento teórico del motor de inferencia.

### A3.4.3 Salvaguardas inalteradas y hoja de ruta de transferencia
Un principio fundacional de DroneLM es que los modelos de lenguaje son aproximadores estocásticos y **bajo ninguna circunstancia deben gobernar de forma directa los actuadores físicos sin arbitraje determinista** (Gat, 1998; cap. 5 y 8). La incorporación de adaptadores LoRA preserva íntegramente las tres salvaguardas del sistema:
1. **Supervisión Jerárquica por FSM:** la máquina de estados retiene la potestad para anular cualquier macro-acción deliberativa ante condiciones de riesgo inminente ($TTC < 1.0\text{ s}$).
2. **Parser Tolerante de Tres Etapas:** permanece activo en `_parse_decision()` como red de contención frente a anomalías de serialización.
3. **Perro Guardián Temporal (`SLM_WATCHDOG_MS = 1500 ms`):** cualquier sobrepaso temporal fuerza el retorno inmediato al régimen conservador de sustentación.

Como línea de extensión formulada en el trabajo futuro (§12.4), esta especialización posibilitará la transferencia del nodo deliberativo a plataformas de cómputo en borde (NVIDIA Jetson Orin Nano / Xavier NX con enlaces serie MAVLink hacia autopilotos PX4), consolidando a DroneLM como un copiloto táctico local, seguro por diseño y plenamente autónomo en entornos reales.
