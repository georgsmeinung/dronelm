# Plan deuda técnica — mejoras derivadas de §12.4 (Conclusiones)

**Fecha:** 2026-09-10
**Estado:** comprometido como paso previo al PLAN-SLAM.md
**Origen:** `informe/12-CONCLUSIONES.md` §12.3–§12.4. Cubre las mejoras ejecutables dentro del
alcance de la tesis, excluyendo LoRA/QLoRA (§12.4 bullet 1, requiere dataset y entrenamiento) y
transferencia a hardware (§12.4 bullet 5, fuera de alcance declarado).

**Criterio de inclusión:** son mejoras sin corrida experimental nueva. No requieren
recolectar datos comparativos con K=5 semillas; su validación es offline o en un único run de
verificación. El impacto en el informe es resolver deuda declarada como "pendiente" o "provisorio"
en §12.3, no añadir secciones de resultados nuevas.

---

## 0. Tabla de fases (orden de ejecución sugerido)

| Fase | Requiere AirSim | Impacto en informe | Costo |
|---|---|---|---|
| **D1** Decodificación restringida dinámica | No | §12.4 bullet 2 pasa de propuesta a implementado | ~1 día |
| **D2** Calibración del canal de ocupación | Solo para captura del dataset | §12.3 bullet 4 deja de ser limitación abierta | ~1-2 días |
| **D3** Validación de derotación con yaw agresivo | Sí | §12.4 bullet 3 (segundo sub-bullet) cierra | ~1 día |

D1 es puro código, sin AirSim, con test unitario. D2 requiere AirSim solo para capturar el dataset
de calibración (una sesión corta en una escena estática); el análisis es offline. D3 requiere AirSim
para los runs de validación con yaw > 0.3 rad/s.

---

## Fase D1 — Decodificación restringida dinámica por `reason_note`

**Archivo:** `airsim-loop/src/agents/deliberative.py`

### Estado actual

`RESPONSE_JSON_SCHEMA` (línea 69) ya usa JSON Schema con `"enum": sorted(PROMPT_ACTIONS)` para
todas las invocaciones. El enum es estático — el mismo conjunto completo de 6 macro-acciones
independientemente de por qué se consulta al VLM. `VLM_USE_JSON_SCHEMA=true` (env var, línea 46)
ya habilita que el servidor local (Ollama/llama.cpp) aplique esta restricción durante el sampling.

### Cambio propuesto

Convertir `RESPONSE_JSON_SCHEMA` de constante a función que recibe el `reason_note` del payload y
devuelve un schema con el `enum` podado:

```python
_ACTIONS_BY_REASON: dict[str, set[str]] = {
    "TTC_CRITICO": {
        "EVADIR_IZQUIERDA", "EVADIR_DERECHA",
        "GANAR_ALTURA", "PERDER_ALTURA", "FRENAR",
        # MANTENER_RUMBO excluido: hay colisión inminente confirmada
    },
    "DEADLOCK_ESCAPE": {
        "EVADIR_IZQUIERDA", "EVADIR_DERECHA",
        "GANAR_ALTURA", "PERDER_ALTURA",
        # MANTENER_RUMBO excluido: ya falló. FRENAR excluido: no avanza.
    },
}

def _schema_for_reason(reason_note: str) -> dict:
    allowed = _ACTIONS_BY_REASON.get(reason_note, PROMPT_ACTIONS)
    schema = copy.deepcopy(RESPONSE_JSON_SCHEMA)
    schema["json_schema"]["schema"]["properties"]["macro_action"]["enum"] = sorted(allowed)
    return schema
```

El `reason_note` ya está en el payload que se arma en `_build_prompt()` y se pasa a
`_query_slm_impl()` — no hace falta cambiar la interfaz de `DeliberationService`.

### Qué resuelve

En el análisis de deliberaciones de `townsim_calib_cruce_frontal` (Régimen 3, §12.2), el VLM
eligió `FRENAR` o `MANTENER_RUMBO` en situaciones donde la única acción razonable era evadir
lateralmente. La poda sintáctica elimina esas opciones antes del sampling, concentrando la
distribución en alternativas físicamente coherentes con el motivo de consulta. El prompt en texto
no cambia — la restricción opera en el schema de respuesta, que ya está integrado como
`response_format` en la llamada a la API.

### Qué NO cambia

- `deep_scan.py`: el prompt del escaneo profundo no pasa por `_schema_for_reason()` (tiene su
  propio conjunto de acciones, ya definido como `PROMPT_ACTIONS` en `deep_scan.py` línea 56).
- `deliberation_service.py`: ningún cambio — el schema se pasa dentro del payload, igual que hoy.
- Tests existentes: el cambio es backward-compatible; si `reason_note` no está en
  `_ACTIONS_BY_REASON`, se usa el enum completo.

### Validación

Test unitario en `tests/`: verificar que `_schema_for_reason("TTC_CRITICO")` devuelve un schema
cuyo `enum` no contiene `"MANTENER_RUMBO"`, y que `_schema_for_reason("OTRO")` devuelve el
conjunto completo. No requiere AirSim.

### Impacto en el informe

`12-CONCLUSIONES.md` §12.4 bullet 2 se actualiza: la gramática dinámica por `reason_note` está
implementada. Describir brevemente en el párrafo correspondiente qué motivos tienen poda y por qué,
con referencia al mecanismo `VLM_USE_JSON_SCHEMA` ya documentado en cap. 8 §8.2.

---

## Fase D2 — Calibración formal del canal de ocupación de `ObstacleField`

**Archivos involucrados:**
- `airsim-loop/src/perception/obstacle_field.py` línea 16: `OCCUPANCY_BLOCKED_THRESHOLD = 0.35`
  (marcado como PROVISORIO)
- `airsim-loop/src/hardware/airsim_client.py`: `capture(return_depth=True)` ya soportado

### Estado actual

El canal de TTC fue formalmente validado en cap. 7 (§7.5: curva ROC, índice de Youden). El canal
de ocupación (`occupancy`, fracción de píxeles con flujo divergente por encima del piso de ruido)
usa `OCCUPANCY_BLOCKED_THRESHOLD = 0.35` derivado heurísticamente (cap. 6, §6.9). Esta asimetría
entre los dos canales quedó declarada como limitación en §12.3.

### Procedimiento (análogo al cap. 7, §7.5)

**Paso 1 — Captura del dataset de calibración (requiere AirSim, ~30 min):**
Volar el dron en una escena estática conocida (MiniSim o TownSim con paredes a distancias
controladas), capturar pares `(frame_RGB, DepthPlanar)` con `capture(return_depth=True)` para
cada ciclo. Registrar también el `ObstacleField` completo (campos `occupancy` y `confidence` por
celda). Cubrir distancias entre 2 m y 15 m al obstáculo, variando la velocidad de aproximación.

**Paso 2 — Análisis offline (sin AirSim, notebook en `airsim-loop/notebooks/`):**

Para cada frame del dataset:
- Ground truth: celda bloqueada si la profundidad media de la zona correspondiente en `DepthPlanar`
  < umbral de referencia (mismo criterio que cap. 7, §7.5.2).
- Predicción: `cell.occupancy >= threshold` con threshold variando en [0.1, 0.9].
- Construir la curva ROC (TPR vs. FPR) y derivar el umbral óptimo por índice de Youden:
  `J = TPR - FPR`, `threshold* = argmax J`.

**Paso 3 — Actualizar la constante:**
Si `threshold*` difiere de 0.35 por más de 0.05, actualizar `OCCUPANCY_BLOCKED_THRESHOLD` en
`obstacle_field.py` y en `config/.env`, y registrar el valor calibrado con su metodología en
cap. 7 §7.5 (nota al pie o sub-sección §7.5.3) y en cap. 6 §6.9.

### Impacto en el informe

- `12-CONCLUSIONES.md` §12.3: eliminar o actualizar el bullet de "calibración pendiente".
- `informe/06-ARQUITECTURA.md` §6.9 y `informe/07-VALIDACION.md` §7.5: registrar el valor
  calibrado con metodología.

---

## Fase D3 — Validación de derotación con yaw agresivo

**Archivo:** `airsim-loop/src/perception/flow_ttc.py`

### Estado actual

La compensación por rotación propia (derotación angular, `flow_ttc.py` paso 2) fue validada con
un dataset de maniobras moderadas (cap. 7, §7.4). El §7.6 y §12.4 bullet 3 declaran que la
validación está acotada a yaw < 0.3 rad/s y que el comportamiento con yaw agresivo no fue medido.
En `townsim_calib_cruce_frontal` y en el escape `GIRAR_90` (que dura `GIRAR90_DURATION_S=1.0 s`
a velocidad de giro libre), el dron puede superar ese umbral.

### Procedimiento (requiere AirSim, ~1 día)

1. En MiniSim, ejecutar yaw sweeps a 0.3, 0.5, 0.8, 1.0 rad/s con el dron en hover frente a un
   obstáculo de distancia conocida. Capturar `ObstacleField` en cada ciclo.
2. Comparar `foe_confidence` y `sector_occupancy("centro")` contra el ground truth de `DepthPlanar`
   durante el giro: si la derotación funciona, el sector frontal mantiene la detección del obstáculo
   aunque el dron esté girando; si falla, `foe_confidence` cae a 0 y el obstáculo queda invisible
   durante el giro.
3. Si hay degradación medible por encima de un umbral de yaw específico, documentarlo como
   limitación cuantificada en §7.6 (en vez de la limitación cualitativa actual: "no validado
   con yaw agresivo").

### Impacto en el informe

- `informe/07-VALIDACION.md` §7.6: reemplazar la limitación cualitativa por el umbral medido.
- `12-CONCLUSIONES.md` §12.4 bullet 3 (segundo sub-bullet): marca como "validado con umbral X".
- Si se detecta degradación relevante (foe_confidence = 0 durante `GIRAR_90`), agrega una nota
  técnica en `CHANGELOG.md` y evalúa si `GIRAR90_DURATION_S` debe reducirse o si el nodo debe
  detener la derotación durante la maniobra.

---

## Qué queda como trabajo futuro real (no ejecutar en este cierre)

- **LoRA/QLoRA** (§12.4 bullet 1): requiere dataset de maniobras exitosas + infraestructura de
  entrenamiento. Semanas de trabajo. Referencia: `informe/anexos/A3-OPTIMIZACION-LORA.md`.
- **SLAM visual completo** (§12.4 bullet 4, línea futura): triangulación 3D, cierre de bucle,
  mapa dinámico. Cubierto como trabajo de segunda iteración en `PLAN-SLAM.md`.
- **Transferencia a hardware** (§12.4 bullet 5): fuera del alcance declarado en el plan de trabajo
  aprobado.
