# Anexo 15: Comparación de la dinámica de vuelo simulada con telemetría real

El capítulo 3 (IT.3.4) resume esta comparación. Este anexo reúne la fuente de datos, el protocolo, la metodología estadística, los resultados con sus figuras y el alcance.

---

La dinámica de vuelo simulada —no la geometría de la escena urbana, cuya fidelidad fotográfica es el desvío documentado en el cap. 3 (IT.3.2)— se comparó con telemetría de drones reales, con el objetivo de saber si la comparación experimental entre brazos (cap. 10) se apoya en vuelos simulados cuya cinemática es comparable a la de un cuadricóptero real o solo físicamente plausible en abstracto. Es una comparación, no una calibración: la simulación no se reajustó con sus resultados.

## A15.1 Fuente de datos reales

Se descargó un conjunto de datos de telemetría real de drones cuadricópteros comerciales (DJI) desde el repositorio público de Zenodo (<https://zenodo.org/records/15912415>).

## A15.2 Protocolo de comparación

Sobre esa telemetría real se identificaron dos trayectorias de vuelo distintas —un patrón rectangular simple (Drone 1) y un patrón de cruz combinado con rectángulo (Drone 2)— y se reprodujeron en simulación con `moveOnPath`/`move` de la API de AirSim, ajustando la simulación a la misma altura y la misma velocidad que los vuelos reales correspondientes. La trayectoria completa se envía como un único comando `moveOnPath`, y no como una secuencia de tramos independientes, para que el perfil de aceleración simulado se parezca al de un vuelo real continuo; la telemetría de cada vuelo simulado se registra en un CSV individual.

![Trayectorias de vuelos reales usadas como referencia](../2026-0610%20Trayectoria%20vuelos%20Reales.png)

## A15.3 Metodología estadística

El análisis se implementó en notebooks de Jupyter del repositorio complementario del proyecto (`consolidate_telemetry.ipynb` y `telemetry_analysis_*.ipynb`, [georgsmeinung/lm-drone](https://github.com/georgsmeinung/lm-drone)), con estadística descriptiva y pruebas de significancia —en particular la prueba de Levene para diferencia de varianzas— aplicadas al cambio de velocidad en los tres ejes, para determinar si la distribución de la telemetría simulada difiere de forma significativa de la real.

## A15.4 Resultados

El análisis documenta tres hallazgos consistentes:

1. **La varianza de actitud difiere de forma significativa** (prueba de Levene, p ≪ 0,05): en simulación, el dron ejecuta inclinaciones de *roll*/*pitch* extremas durante los giros rápidos para alcanzar instantáneamente el punto de trayectoria siguiente. Los drones reales, en cambio, están limitados electrónicamente por su controlador PID de estabilización (típicamente a ±30°), y muestran una varianza mucho menor y acotada durante las mismas maniobras.
2. **La segregación por trayectoria es significativa y consistente.** El Drone 1 (patrón rectangular, giros menos frecuentes) concentra la aceleración en las esquinas; el Drone 2 (patrón de cruz y rectángulo continuo) presenta una dinámica transicional más exigente y oscilaciones de *roll*/ *pitch* más ruidosas, tanto en el vuelo real como en el simulado.
3. **El vuelo simulado en tramos rectos es idealizado.** Durante las fases rectas, la telemetría simulada muestra varianza de actitud cercana a cero, sin fuerzas externas de viento ni ruido de sensores; el dron real, en cambio, mantiene una variabilidad permanente de ±2°–3° en *roll* y *pitch* incluso en tramos rectos estables, producto del viento real y de las correcciones continuas del piloto automático.

![Comparación de trayectorias y perfil de velocidad — Drone 1](../2026-0627%20Comparaci%C3%B3n%20de%20Pefiles%20de%20velocidad%20-%20Drone%201.png)

![Comparación de trayectorias y perfil de velocidad — Drone 2](../2026-0627%20Comparaci%C3%B3n%20de%20Pefiles%20de%20velocidad%20-%20Drone%202.png)

## A15.5 Alcance de la comparación

Muestra que la dinámica de vuelo simulada —cómo se mueve el dron dado un comando— difiere de la de un dron real equivalente: es más ágil y menos amortiguada, con una brecha de idealización conocida y cuantificada (varianza de actitud, ausencia de viento simulado). Esa brecha no se corrigió: los parámetros de vuelo de AirSim no se reajustaron para acercarlos a la telemetría real, de modo que la corrida v4 vuela con la dinámica idealizada. No valida, en cambio, la fidelidad fotográfica de la escena urbana frente a Buenos Aires real: esa es una validación distinta, no realizada, y coincide con el desvío documentado en el cap. 3 (IT.3.2). Un ejercicio de validación relacionado pero diferente —si el suavizado por histéresis y media móvil exponencial de `WaypointTracker` (cap. 5, IT.5.4) acerca de forma medible la telemetría simulada a la real— da un resultado ambiguo (`std(Δvx)` prácticamente igual con y sin suavizado) y se informa como tal, no como una mejora confirmada.
