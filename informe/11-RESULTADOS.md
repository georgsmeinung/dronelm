# 11. Resultados comparativos SLM vs. FSM

> **Estado:** pendiente de la corrida experimental comparativa descrita en el capítulo 10. Un primer
> batch de validación de punta a punta (dos escenarios, dos y tres semillas, presupuestos de 60 y 300
> segundos) sirvió para validar el pipeline y expuso la cadena de fallas del grafo de control
> documentada en el capítulo 9, ya corregida en la arquitectura descrita en el capítulo 5, pero no
> constituye todavía la corrida de tesis: ninguna misión llegó a completarse en esos batches
> preliminares, y en la corrida con el brazo `slm` el servidor del modelo de lenguaje no estaba
> accesible, por lo que esa comparación medía en la práctica la FSM y el brazo reactivo contra la
> política de respaldo determinista del brazo `slm`, no contra el modelo en sí.
>
> **Criterio de arranque** para el batch completo: una corrida piloto de una sola combinación
> brazo×escenario debe completar la misión (`success = True`) antes de ejecutar el resto de las
> combinaciones.

## 11.1 Tabla de resultados agregados (placeholder)

| Brazo | Escenario | Tasa de éxito | Colisiones/misión | Colisiones/km | DistMin p5 (m) | SPL | Tiempo a destino (s) | Latencia p50 (ms) | Latencia p95 (ms) | `deliberation_rate` | Fallback SLM | Timeout watchdog |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `slm` | manhattan_a | | | | | | | | | | | |
| `slm` | manhattan_b | | | | | | | | | | | |
| `slm` | (tercer escenario) | | | | | | | | | | | |
| `fsm` | manhattan_a | | | | | | | | | | | |
| `fsm` | manhattan_b | | | | | | | | | | | |
| `fsm` | (tercer escenario) | | | | | | | | | | | |
| `reactive` | manhattan_a | | | | | | | | | | | |
| `reactive` | manhattan_b | | | | | | | | | | | |
| `reactive` | (tercer escenario) | | | | | | | | | | | |

## 11.2 Histograma de rutas por brazo

Placeholder para el gráfico de distribución de rutas de decisión por ciclo
(`keep_going` / `evasive` / `deliberative` / `girar_90` / `fsm` / `degraded`), por brazo y escenario.

## 11.3 Significancia estadística

Placeholder — prueba U de Mann-Whitney y tamaño de efecto por combinación brazo × escenario, sobre las
semillas (§10.3).

## 11.4 Análisis por tipo de escenario

Responder aquí, desagregado por escenario y no en agregado, la pregunta de investigación central: ¿el
SLM aporta sobre la FSM? Un resultado del tipo "no aporta en el bloqueo frontal masivo, donde la FSM
decide igual y más rápido; sí aporta en la elección de una calle transversal" es un resultado válido y
publicable — más defendible en una instancia de defensa que un empate agregado y ambiguo.
