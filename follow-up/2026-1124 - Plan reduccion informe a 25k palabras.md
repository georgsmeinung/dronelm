# Plan: reducir el cuerpo del informe a ~25.000 palabras

**Fecha:** 2026-11-24. **Punto de partida:** el cuerpo (capítulos 01–12, sin portada, referencias ni anexos) tiene **32.339 palabras** contando prosa y tablas, después de la revisión de cierre (título, `depth2loop`, avance a 20 s, limitaciones). **Meta:** ~25.000, o sea un recorte de **~7.300 palabras (23 %)**. El plan apunta a ~24.200 para tener margen.

Contador: prosa + tablas, sin bloques de código, imágenes, URLs ni etiquetas HTML de una sola línea (el mismo criterio del plan de 30k, con la regex de etiquetas acotada a una línea).

## Criterio

Queda en el cuerpo lo que sostiene el argumento: la pregunta (objetivos 3a y 3b, H1–H3), el hilo conductor (contratos de datos), qué se midió y qué se concluye, y las limitaciones declaradas. Va a anexos lo que es **especificación, procedimiento o detalle de un resultado secundario**: cómo se implementa algo que ya se entiende con una frase, la ingeniería del VLM que no vuela, los casos de falla adicionales, el detalle de la validación de la dinámica y de los dominios de aplicación.

Ningún resultado ni limitación de la revisión de cierre se pierde: si se condensa en el cuerpo, el detalle queda en un anexo con remisión.

## Presupuesto por capítulo

| Cap. | Hoy | Meta | Recorte | Qué sale del cuerpo | Destino |
|---|---:|---:|---:|---|---|
| 1 Introducción | 1.605 | 1.300 | −300 | 1.1: los cuatro dominios en un párrafo corto (el detalle ya está en 2.4); 1.5 más breve | — |
| 2 Estado del arte | 1.595 | 1.150 | −450 | 2.4 Dominios de aplicación (497 → ~100, una síntesis) | **A14 nuevo** (sus 9 referencias solo se citan ahí) |
| 3 Entorno | 1.630 | 1.100 | −530 | 3.4: protocolo, estadística y los tres hallazgos (628 → ~250, queda la conclusión y que no hubo reajuste); 3.1 más breve | **A15 nuevo** (comparación con telemetría DJI) |
| 4 Planificación y WebDCS | 1.754 | 1.250 | −500 | 4.3.1 plan de ruta (610 → ~300); 4.4 visor y auditoría (346 → ~200); 4.2 a un párrafo | A13 |
| 5 Lazo táctico | 3.687 | 2.700 | −1.000 | 5.1.2, 5.3.1, 5.3.4, 5.4, 5.5.1–5.5.4, 5.6, 5.7 condensados; queda la tabla de reglas de 5.3.2 | A10 |
| 6 Percepción | 3.240 | 2.350 | −900 | Etapas 6.3–6.8 condensadas (la matemática ya está en A5); 6.12 profundidad (774 → ~400) | A5 |
| 7 Validación del TTC | 2.383 | 1.800 | −580 | 7.1 y 7.3 más breves; 7.7 (783 → ~550): la explicación única del disparo queda, el detalle de NB1.12 se resume | A5 |
| 8 Ingeniería del VLM | 2.298 | 1.300 | −1.000 | El VLM no vuela: quedan selección del modelo (8.1), salida estructurada (8.2, breve) y la pregunta que se le hace (8.3.1–8.3.2). Salen 8.3.3–8.3.4, 8.4, 8.5 prompt, 8.6 latencia, 8.7 LoRA | **A16 nuevo** (ingeniería del VLM: prompt, latencia, vocabulario) |
| 9 Modos de falla | 3.417 | 2.600 | −800 | 9.1 más breve; fallas 1–5 a ~200 c/u (descripción, por qué es invisible, contención); 9.8.5 «otros casos» a una tabla; 9.7 condensado | A11 |
| 10 Metodología | 3.864 | 3.000 | −860 | 10.2 banco (545 → ~300); 10.4.2 (queda la tabla); 10.3.1; método del avance a 20 s en 10.6.3 | A12 |
| 11 Resultados | 4.333 | 3.500 | −830 | 11.0 (queda la tabla; el plan de ruta, más breve); 11.3 costo; 11.4 (1.187 → ~900): avance a 20 s y barrido condensados; 11.5 | A12 |
| 12 Conclusiones | 2.533 | 2.150 | −380 | 12.1 más breve; 12.3 sin repeticiones con 11 (las limitaciones quedan todas, más cortas); 12.4 | — |
| **Total** | **32.339** | **~24.200** | **−8.130** | | |

## Anexos nuevos

| Anexo | Contenido | Origen |
|---|---|---|
| A14 Dominios de aplicación de pertinencia local | Litoral marítimo, incendios, agricultura de precisión, seguridad y logística urbana, con sus referencias | Cap. 2, IT.2.4 (y el detalle de 1.1) |
| A15 Comparación de la dinámica con telemetría real | Fuente Zenodo, protocolo, metodología estadística, tres hallazgos, figuras | Cap. 3, IT.3.4 |
| A16 Ingeniería del VLM: prompt, latencia y vocabulario | Barrido con imágenes numeradas, vocabulario de macro-acciones, `action_to_command`, ingeniería del prompt, gestión de latencia, nota LoRA | Cap. 8, IT.8.3.3–IT.8.7 |

El resto del material va a anexos que ya existen (A5, A10, A11, A12, A13), como secciones nuevas al final para no renumerar las existentes.

## Procedimiento

1. **Un capítulo por paso**, con diff y recuento antes de pasar al siguiente. Orden propuesto: los de mayor recorte primero (8, 5, 6, 9, 10, 11), después 2, 3, 4, 7, 12 y 1.
2. **Referencias cruzadas:** antes de mover una sección, tabla de correspondencia `vieja → nueva` (por ejemplo `IT.8.5 → IT.A16.3`), aplicada con un script al informe, los anexos, NB1–NB5, `docs/index.html` y los comentarios de código. Verificación: cada `IT.x` que quede tiene destino; mkdocs sin advertencias nuevas.
3. **Lo que no se toca:** los números, las tablas de resultados, las limitaciones y las frases acordadas en la revisión de cierre (resumen, objetivos, 7.7, seguridad, H1 «No atribuible»).
4. **Al final:** `mkdocs.yml` con A14–A16 en el nav, recuento final y regeneración del HTML y el PDF.

## Avance

| Paso | Estado | Palabras |
|---|---|---|
| — | Punto de partida | 32.339 |
| Cap. 8 → A16 | Hecho | 2.298 → 1.291. Quedan 8.1 (selección), 8.2 (salida estructurada, sin subsecciones), 8.3 (pregunta y grilla) y una síntesis nueva 8.4; parser, geometría, barrido, vocabulario, `action_to_command`, prompts, latencia y LoRA pasan a A16.1–A16.8. Cuerpo: 31.334 |
| Cap. 5 → A10 | Hecho | 3.687 → 2.642. Misma numeración (sin reasignar referencias); A10 suma A10.6.5 (cuándo se consulta), A10.6.6 (formato y validación de la respuesta) y la tabla de estados de la FSM en A10.4.8. El resto del detalle ya estaba en A10. Cuerpo: 30.289 |
| Cap. 6 → A5 | Hecho | 3.240 → 2.050. Misma numeración; A5 suma A5.11 (guard de rotación, ancho de trabajo, giroscopio, constante de ocupación, calibrador de `main.py`, umbrales de confianza) y A5.12 (profundidad estimada: decisión, dónde corre y limitaciones). Cuerpo: 29.099 |
| Cap. 9 → A11 | Hecho | 3.417 → 2.281. Misma numeración; A11 suma A11.5–A11.7 (fallas 1 a 3 en detalle, con las fórmulas de la falla 3) y A11.8 (reglas apiladas); la tabla de 9.8.5 pierde la columna de contención, que está en A11.4. Cuerpo: 27.961 |
| Cap. 10 → A12 | Hecho | 3.864 → 3.014. Misma numeración; 10.4.1 pasa de lista numerada a párrafo (las referencias «IT.10.4.1, punto N» quedan como «IT.10.4.1»); A12 suma A12.10.4 (por qué un banco y sus reglas) y el método del avance a 20 s en A12.6.4. Cuerpo: 27.111 |
| Cap. 11 → A12 | Hecho | 4.333 → 3.641. Misma numeración y todas las tablas; prosa por lote, datos del banco, costo en ruta libre y avance a 20 s completo pasan a A12.12 (texto original). Cuerpo: 26.417 |
| Cap. 2 → A14 | Hecho | 1.595 → 1.241. 2.4 queda en un párrafo de síntesis; los cuatro dominios con sus 9 referencias propias pasan a A14 (nuevo). |
| Cap. 3 → A15 | Hecho | 1.630 → 1.047. 3.4 queda en un párrafo (comparación, no calibración; sin reajuste); fuente, protocolo, estadística, resultados y figuras pasan a A15 (nuevo); 3.1 más breve. |
| Cap. 4 → A13 | Hecho | 1.754 → 1.317. 4.2 a un párrafo; candidatas, juicio por parches y «por qué parches» pasan a A13.1.3; 4.4 más breve. Nav, README e IT.1.5 con A14–A16. Cuerpo: 25.072 |
| Cap. 7 | Hecho | 2.383 → 1.921. 7.1–7.6 más breves; 7.7 conserva la explicación única del disparo y la auditoría en vuelo; NB1.12 resumido. |
| Cap. 12 | Hecho | 2.533 → 2.256. Sin repeticiones con el cap. 11; todas las limitaciones quedan, más cortas. |
| Cap. 1 | Hecho | 1.605 → 1.486. Dominios de 1.1 en un párrafo (las referencias quitadas siguen citadas en A14); 1.5 más breve. |
| **Total** | **Cerrado** | **32.339 → 24.187** (−8.152, −25 %). 0 referencias sin destino; mkdocs sin advertencias nuevas. Referencia sin cita preexistente: Kruskal (1952). Falta regenerar HTML y PDF. |
