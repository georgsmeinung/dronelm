# Plan: reducir el cuerpo del informe a ~30.000 palabras

Fecha: 2026-11-13

## Punto de partida

El cuerpo (capítulos 01–12, sin portada, referencias ni anexos) tiene **≈ 65.100 palabras** contando prosa y tablas (≈ 59.700 solo prosa). La meta es **≈ 30.000**, o sea un recorte del 54 %.

> **Corrección (2026-11-13).** La primera versión de este plan decía 54.700. El contador que usé tenía un error: la regex que quitaba etiquetas HTML podía abarcar varias líneas entre un «<» y un «>» sueltos de la prosa, y descontaba texto. Las cifras de esta sección y de «Avance» están recalculadas con el contador corregido; los presupuestos por capítulo de la tabla siguiente quedaron con las cifras viejas como referencia relativa.

## Criterio: qué queda en el cuerpo y qué va a un anexo

Una sección **queda en el cuerpo** si hace falta para seguir alguno de estos tres argumentos:

1. **La pregunta de investigación**: ¿qué aporta una capa de decisión con SLM/VLM frente a una FSM y a un controlador reactivo? Esto incluye las hipótesis H1–H3, el diseño, los resultados y las conclusiones.
2. **El hilo conductor** (IT.1.4): las fallas más costosas están en el contrato de datos entre percepción, modelo y control, no en el modelo.
3. **Los objetivos específicos 1–4** (IT.1.2).

Una sección **pasa a un anexo** si es alguna de estas cosas:

- **Especificación de implementación**: nombres de archivo, variables de entorno, máquinas de estado internas, umbrales con su valor por defecto, API de clases.
- **Procedimiento operativo**: cómo se arma y se ejecuta un lote, la disposición de carpetas, los pilotos, la publicación.
- **Casuística**: más instancias del mismo argumento cuando una o dos ya alcanzan para sostenerlo.
- **Contexto que no se usa después**: dominios de aplicación en detalle, casos de uso de la literatura.
- **Trabajo futuro desarrollado**: el cuerpo lo deja en una lista y el desarrollo va a los anexos A3, A4 y A7–A9, que ya existen.

Regla de redacción para lo que queda: cada sección que se achica conserva **la idea y su porqué en prosa** y remite al anexo para el detalle, con una línea del tipo «la especificación completa está en el Anexo X, IT.AX.n».

## Presupuesto por capítulo

Las cifras incluyen prosa y tablas.

| Cap. | Actual | Meta | Recorte | Dónde está el recorte |
|---|---:|---:|---:|---|
| 01 Introducción | 2.336 | 1.600 | −700 | 1.1 Motivación (1.031 → 500); 1.5 Estructura se reescribe con la nueva estructura |
| 02 Estado del arte | 3.507 | 2.300 | −1.200 | 2.4 Dominios de aplicación (1.610 → 400) |
| 03 Entorno | 2.767 | 1.800 | −950 | «Casos de uso de AirSim en la literatura» (864 → 150, el resto va al cap. 2 o a un anexo); 3.3 Rendimiento e higiene de captura → A6 |
| 04 Planificación / WebDCS | 3.931 | 2.000 | −1.900 | 4.3 Componentes del manifiesto → tabla corta; 4.4 WebDCS, estructura de `airsim-runs/` y visor → A12 |
| 05 Lazo táctico | 6.728 | 3.200 | −3.500 | Ver detalle abajo |
| 06 Percepción | 4.284 | 2.600 | −1.700 | 6.10 API de `ObstacleField`, 6.11 consultas, 6.13 variables calibrables → A5; 6.12 y 6.14 condensados |
| 07 Validación TTC | 2.801 | 2.200 | −600 | 7.7 Implicaciones (788 → 400); 7.2 dataset más compacto |
| 08 VLM | 1.978 | 1.500 | −480 | 8.5 Prompts completos y 8.7 nombres compactos → A4; 8.8 LoRA queda en una oración que remite a A3 |
| 09 Modos de falla | 7.563 | 3.600 | −4.000 | Ver detalle abajo |
| 10 Metodología | 12.167 | 4.500 | −7.700 | Ver detalle abajo |
| 11 Resultados | 2.433 | 2.500 | ≈ 0 | Es el núcleo y no se recorta; solo se reordena (ver abajo) |
| 12 Conclusiones | 4.222 | 2.400 | −1.800 | 12.3 Limitaciones (1.178 → 700); 12.4 Trabajo futuro (1.429 → 600, en lista, remitiendo a A3/A4/A7–A9) |
| **Total** | **54.700** | **≈ 30.200** | **−24.500** | |

### Cap. 10 Metodología (12.200 → 4.500): el recorte más grande

| Sección | Hoy | Destino |
|---|---:|---|
| 10.1 Preguntas e hipótesis | 447 | **Queda** |
| 10.2 Diseño factorial | 1.128 | **Queda, condensado a ~600.** Se le incorpora la celda `fsm:blind` y las comparaciones planificadas de 10.12.2 |
| 10.3.0 Principios de diseño de escenarios | 827 | **~200 en el cuerpo**: sin teletransporte, sin profundidad en el lazo, protocolo previo. El detalle (`client.reset()`, marcadores, pasos a–d del protocolo) → A12 |
| 10.3.1–10.3.4 Tiers y síntesis | 1.083 | **~600**: tabla de la batería con una línea de particularidad por escenario |
| 10.4 Semillas | 1.376 | **~250 en el cuerpo**: «una semilla es una réplica, no una condición; la variación viene de la estocasticidad del lazo». Las cinco fuentes, el modo `--seed-jitter` y la asignación → A12 |
| 10.5 Organización en lotes | 843 | → A12 |
| 10.6 Métricas | 1.129 | **~600**: tabla de métricas primarias y secundarias con su definición. Las de dinámica del lazo y el desglose por waypoint, en una línea |
| 10.7 Protocolo estadístico | 556 | **~400** |
| 10.8 Análisis esperado | 688 | **Se elimina.** Las predicciones se integran a las hipótesis de 10.1, que es donde corresponden |
| 10.9 Artefactos, auditoría y publicación | 502 | → A12 (la trazabilidad, en una oración en 10.11) |
| 10.10 Plan extendido de pruebas | 693 | → se fusiona con 12.4 Trabajo futuro (en lista) o va a A12 |
| 10.11 Amenazas a la validez | 307 | **Queda** |
| 10.12.1 Componentes que ejercen la obstrucción | 275 | **~100**, dentro de 10.3 |
| 10.12.2 Celdas, pilotos, comparaciones | 442 | Las celdas y comparaciones van a 10.2; los pilotos y criterios de pase → A12 |
| 10.13 Banco `vlm_bench` | 1.883 | **~700**: qué es, etiqueta de referencia, criterio de pase y qué decide. La construcción (tabla de etapas y módulos) y el alcance → A12 |

Nota de orden: hoy 10.12 y 10.13 quedan después de «Amenazas a la validez». En la versión corta, el banco pasa a ser 10.4 (antes del diseño de vuelo, porque decide qué fuente responde cada pregunta) y las amenazas cierran el capítulo.

### Cap. 9 Modos de falla (7.600 → 3.600)

Este capítulo es el **hilo conductor** y por eso queda con un peso relativo alto. Pero hoy las seis fallas se cuentan con toda su casuística.

- **9.1 Argumento central**: queda (~450).
- **Fallas 1–5** (9.2–9.6): cada una se reduce a *descripción + por qué es invisible + contención*, ~250 palabras por falla. Las «cuatro vulnerabilidades» y las «instancias adicionales» de LangGraph (9.5.2, 9.5.4) se condensan; el detalle va a A11.
- **9.7 Observabilidad**: queda (~400). Es la bisagra del argumento.
- **9.8 Falla 6, integración del VLM** (11 subsecciones, 3.000 palabras): quedan **dos o tres casos representativos**. Candidatos: 9.8.1 «marco de referencia invertido», 9.8.2 «default silencioso» y 9.8.9 «sub-metas que ocultan al waypoint», que es el más ilustrativo pero hay que condensarlo de 651 a ~250. Los otros ocho van a A11 con una tabla resumen en el cuerpo (caso, síntoma, causa, contención).
- **9.9 Riesgos residuales**: queda (~300).

### Cap. 5 Lazo táctico (6.700 → 3.200)

Hoy es una especificación nodo por nodo (112 nombres de variables de entorno). En el cuerpo queda **la arquitectura y sus decisiones**; la especificación pasa a un anexo nuevo, A10.

- **Quedan**: 5.1 Visión general, con los dos lazos desacoplados y la figura del grafo; 5.2 `DroneState`, solo los campos que importan al argumento; 5.10 Capa estratégica (~900), que es la contribución, junto con 5.10.7 «Por qué la profundidad y no el VLM»; 5.16 Salvaguardas y contratos (que conecta con el cap. 9); 5.18 Registro y auditoría, en un párrafo.
- **Se reemplazan por una tabla** de una línea por nodo (qué hace y cuándo actúa): 5.3–5.9, 5.11, 5.13, 5.14.
- **Van a A10**: 5.0 `spatial_scan`, 5.3.1–5.3.4 (`StallDetector`, orden de evaluación, deadlock), 5.10.3–5.10.5 (ancla, auditoría, `DeliberationService`, en detalle), 5.12 `deep_scan` (la máquina de estados), 5.15 `WaypointTracker`, 5.17, 5.19.

### Cap. 11 Resultados: reordenar, no recortar

- 11.0 (banco del VLM) puede pasar a ser 11.1, con la corrida v4 como 11.2, para que la numeración empiece en 1. Esto es cosmético y solo vale si ya se van a renumerar las referencias.
- Se puede mover alguna tabla de detalle por celda a un anexo si hace falta espacio, pero no es prioritario.

## Anexos: nuevos y ampliados

| Anexo | Contenido | Origen |
|---|---|---|
| **A5** (se amplía) | API de `ObstacleField`, consultas de alto nivel, variables calibrables | 6.10, 6.11, 6.13 |
| **A6** (se amplía) | Rendimiento gráfico e higiene de captura | 3.3 |
| **A4** (se amplía) | Prompts completos, parámetros de inferencia, nombres de campo compactos | 8.5, 8.7 |
| **A10** (nuevo) | Especificación del lazo táctico: nodos, máquinas de estado y umbrales | cap. 5 |
| **A11** (nuevo) | Catálogo de incidentes de integración | 9.5.2, 9.5.4, 9.6 (detalle), 9.8.3–9.8.11 |
| **A12** (nuevo) | Operación del experimento: protocolo de escenarios, semillas en detalle, lotes, pilotos, construcción de `vlm_bench`, artefactos y publicación (y el plan extendido, si no se fusiona con 12.4) | 10.3.0, 10.4, 10.5, 10.9, 10.10, 10.12.2, 10.13.2 |
| **A13** (nuevo, opcional) | Estación terrena WebDCS, dataset `airsim-runs/` y visor de auditoría | 4.4 |
| — | Dominios de aplicación (2.4) y casos de uso de AirSim (3.1): **condensar en el lugar y descartar el resto**, o un A14 si no se quiere perder el texto | 2.4, 3.1 |

Con esto los anexos pasan de ≈ 20.000 a ≈ 42.000 palabras. No es un problema: los anexos no cuentan para la extensión.

## Referencias cruzadas: el costo oculto

- En `informe/` hay **365 referencias** del tipo `IT.5.x`, `IT.9.x` e `IT.10.x`, más las de los caps. 4, 6 y 8 que también se mueven.
- Fuera del informe también se citan secciones: `airsim-loop/experiments/runner.py`, `airsim-loop/README.md`, `airsim-loop/src/logging/code_version.py`, `docs/informe/fig-src/anexos_svg.py`, `README.md` y `follow-up/2026-1112 - Revision informe y cuadernos.md`.
- **Procedimiento**: antes de mover nada, armar una tabla de correspondencia `vieja → nueva` (por ejemplo `IT.5.12 → IT.A10.4`) y aplicarla con un script. Después hacer un grep de cada `IT.` que quede para verificar que existe el destino. Lo mismo para los anclajes `#...` de los enlaces Markdown.

## Orden de ejecución sugerido

Un capítulo por vez, de mayor a menor recorte, para poder revisar cada uno antes de seguir:

1. **Cap. 10 → A12.** Es el recorte más grande (−7.700) y el más mecánico.
2. **Cap. 9 → A11.** Hay que elegir qué casos de 9.8 quedan; conviene que lo decidas vos.
3. **Cap. 5 → A10.**
4. **Caps. 4, 6, 8 → A13, A5, A4.**
5. **Caps. 2, 3, 7, 12 y 01:** condensación en el lugar. La 1.5 «Estructura del informe» se reescribe al final.
6. **Referencias cruzadas**: tabla de correspondencia, script y verificación, también en el código y los README.
7. **`mkdocs.yml`**: nav con A10–A13, recuento final de palabras, y regenerar el HTML y el PDF.

## Avance

Cifras de prosa + tablas con el contador corregido.

| Paso | Estado | Cap. antes → ahora | Anexo |
|---|---|---|---|
| 1. Cap. 10 → A12 | Hecho | 14.133 → 5.582 | A12 nuevo (operación del experimento) |
| 2. Cap. 9 → A11 | Hecho | 7.620 → 3.857. Quedan cuatro casos de la Falla 6 (9.8.1–9.8.4) y una tabla resumen (9.8.5) de los otros siete | A11 nuevo (catálogo de incidentes) |
| 3. Cap. 5 → A10 | Hecho | 8.081 → 4.162 | A10 nuevo (especificación del lazo) |
| 4a. Cap. 4 → A13 | Hecho | 4.665 → 2.215. Numeración de secciones sin cambios | A13 nuevo (WebDCS, plan de ruta, dataset, visor) |
| 4b. Cap. 6 → A5 | Hecho | 5.511 → 3.344. Nuevas 6.10 (contrato), 6.11 (condiciones extremas), 6.12 (profundidad), 6.13 (complementariedad) | A5.8–A5.10 (API, holdover, variables) |
| 4c. Cap. 8 → A4 | Hecho | 3.902 → 3.336. 8.5 queda con los principios; 8.7 pasa a ser la nota sobre LoRA | A4.9 (esquemas, prompts, parámetros, nombres compactos) |

**Cuerpo 01–12 tras los pasos 1–4: 65.100 → 43.700.**

### Pasos 5 y 6: primera pasada en 1, 2, 3, 7 y 12, y segunda pasada en el resto (2026-11-13)

| Cap. | HEAD | Final |
|---|---:|---:|
| 01 Introducción | 2.336 | 1.491 |
| 02 Estado del arte | 3.507 | 1.591 |
| 03 Entorno | 2.767 | 1.579 |
| 04 Planificación / WebDCS | 4.665 | 1.751 |
| 05 Lazo táctico | 8.081 | 3.611 |
| 06 Percepción | 5.511 | 3.008 |
| 07 Validación TTC | 3.465 | 2.077 |
| 08 VLM | 3.902 | 2.283 |
| 09 Modos de falla | 7.620 | 3.343 |
| 10 Metodología | 14.133 | 3.602 |
| 11 Resultados | 4.879 | 3.855 |
| 12 Conclusiones | 4.222 | 2.202 |
| **Total** | **65.088** | **30.393** |

Anexos: 24.546 → 47.338 (A10–A13 nuevos; A4 y A5 ampliados).

En la segunda pasada no se movieron secciones ni se renumeró: se condensó la prosa dentro de cada sección. Parte de lo condensado en los capítulos 1, 2, 3, 7, 11 y 12 (detalle de los dominios de aplicación, casos de uso de AirSim, tabla de campos del dataset de TTC, cifras secundarias de resultados, lista larga de limitaciones y trabajo futuro) no pasó a un anexo: queda en el historial de git. Se verificó que ninguna referencia `IT.x` quedó sin destino en el repositorio, que todas las citas bibliográficas que se citaban antes se siguen citando en algún lado, que no quedan fórmulas dañadas y que mkdocs compila sin advertencias nuevas. Falta regenerar el HTML de `docs/informe/` y el PDF.

En todos los pasos se reasignaron las referencias `IT.x` en el informe, los README, los comentarios de código, NB1–NB5, los SVG de `fig-src/anexos/` y `docs/index.html` / `docs/grafo-de-control.html`; 0 referencias sin destino y mkdocs compila sin advertencias nuevas.

Cambios respecto del plan en el cap. 10: 10.8 «Análisis esperado» no se eliminó, sino que pasó a A12.8, porque el cap. 11 lo cita para contrastar los resultados contra lo que se esperaba. Su criterio para H3 quedó en el cuerpo (IT.10.7.4). El plan extendido (10.10) pasó a A12.11; la decisión pendiente 3 sigue abierta. A12 queda numerado antes de que existan A10 y A11.

## Decisiones pendientes

1. ¿Hay un límite formal en el reglamento de la carrera (páginas o palabras)? Si lo hay, cambia la meta.
2. ¿Qué dos o tres casos de 9.8 quedan en el cuerpo?
3. 10.10 Plan extendido: ¿se fusiona con 12.4 o va a A12?
4. 2.4 Dominios de aplicación y 3.1 Casos de uso: ¿descartar el excedente o crear A14?
5. ¿Se renumera 11.0 → 11.1?
