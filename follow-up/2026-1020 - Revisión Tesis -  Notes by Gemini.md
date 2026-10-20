oct 20, 2026

## **Revisión Tesis**

Invitado [Jorge NICOLAU](mailto:jenicolau@gmail.com) [enuske@gmail.com](mailto:enuske@gmail.com)

Archivos adjuntos [Revisión Tesis](https://calendar.google.com/calendar/event?eid=NW1ucjYxNzY4N3A4djU3NWdwbDMyajcxNHYgamVuaWNvbGF1QG0)

Registros de la reunión [Transcripción](https://docs.google.com/document/d/1ztN_A_Bwlyxkt1GlTg4X1DLbO9yvE7db-8xapVJaIv8/edit?usp=drive_web&tab=t.6xd0gbr7u9ht) 

### **Resumen**

Definición del alcance de tesis con cierre de experimentos y establecimiento de trabajos futuros.

**Limitaciones técnicas y alcance**  
Evaluación del alcance del informe y limitaciones de navegación en Unreal Engine.

**Metodología y modelos**  
Validación de modelos de frontera y optimización del tamaño de modelos.

**Cierre y trabajos futuros**  
Establecimiento del cierre definitivo de la tesis y definición de trabajos futuros.

### **Decisiones**

## **Acordada**

* **Limitación del entorno por cajas de colisión** Se estableció marcar las discrepancias en las cajas de colisión como una limitación del entorno de simulación sin ampliar el alcance.  
* **Reejecución de pruebas con diez semillas** Se estableció reejecutar el lote completo de pruebas utilizando diez semillas para asegurar la relevancia estadística.  
* **Exclusión del aprendizaje por refuerzo del alcance** Se estableció trasladar la propuesta de aprendizaje por refuerzo y otros apéndices al anexo de trabajos futuros.  
* **Documentación del comportamiento físico en la discusión** Se estableció documentar las especificaciones físicas y el comportamiento de pandeo del dron en la sección de discusión.  
* **Postergación del experimento con cámara binocular** Se acordó presentar la tesis con el alcance actual y dejar el experimento de la cámara binocular para después de la presentación inicial.

### **Próximos pasos**

- [ ] \[Jorge NICOLAU\] Ejecutar pruebas finales: Ejecutar el conjunto de pruebas con 10 semillas y 10 millones de puntos. Finalizar este experimento para asegurar la relevancia estadística.  
- [ ] \[Jorge NICOLAU\] Reescribir capítulo 11: Redactar nuevamente el capítulo 11 incorporando los resultados obtenidos en las nuevas pruebas.  
- [ ] \[Jorge NICOLAU\] Documentar limitaciones técnicas: Incluir las limitaciones del entorno de simulación y la tecnología de visión como parte de la discusión en la tesis.  
- [ ] \[Jorge NICOLAU\] Preparar borrador publicación: Escribir una versión resumida de 5000 palabras de la tesis para su futura publicación tras la aprobación.

### **Detalles**

**Alcance del informe y preservación del trabajo de configuración**: Jorge NICOLAU plantea que el tamaño del informe de tesis se ha expandido demasiado al intentar incorporar constantemente nuevos avances científicos publicados diariamente. Ante esto, Ezequiel Nuske solicita dar un cierre definitivo al alcance para evitar retrasos indefinidos, enfatizando que es fundamental presentar adecuadamente el laborioso trabajo inicial de configuración del entorno y calibración realizado manualmente por Jorge NICOLAU, para evitar que un tribunal subestime dicho esfuerzo comparándolo con la automatización actual mediante agentes modernos.

---

**Limitaciones de los modelos de lenguaje en la navegación y discrepancias en Unreal Engine**: Al revisar los capítulos 5, 8 y 11, Jorge NICOLAU señala que utilizar un modelo de lenguaje grande para la toma de decisiones de navegación resulta ineficiente en comparación con herramientas especializadas de visión por computador, siendo útil únicamente en escenarios visualmente complejos con corredores arbolados. Asimismo, Jorge NICOLAU identifica un problema técnico donde la malla de colisión renderizada en Unreal Engine no coincide con la descripción visual, como ocurre en escaleras de servicio, acordando con Ezequiel Nuske documentarlo como una limitación del entorno de simulación ([00:02:06](#00:02:06)).

---

**Limitaciones monoculares y ejecución final de pruebas con diez semillas**: Jorge NICOLAU expone que el cálculo de distancia monocular es muy limitado en comparación con un sistema binocular, aunque Ezequiel Nuske frena la propuesta de nuevos cambios tecnológicos para evitar alargar el proyecto ([00:04:01](#00:04:01)). Finalmente, Jorge NICOLAU se compromete a reejecutar el conjunto completo de pruebas básicas y con obstáculos utilizando 10 semillas (aplicando el límite estadístico de Bonferroni), lo cual tomará aproximadamente 48 horas de procesamiento ([00:05:01](#00:05:01)).

---

**Creación del banco de pruebas mediante modelos de frontera**: Jorge NICOLAU explica que, ante la dificultad de estructurar las pruebas piloto fallidas, recurrió a un modelo de frontera (Claude, con 3 mil millones de parámetros) para analizar las limitaciones del modelo de lenguaje en el borde y sincronizar la telemetría, el grafo de control y los fotogramas de las cámaras del dron ([00:07:20](#00:07:20)). Ezequiel Nuske valida positivamente esta metodología y los resultados obtenidos, destacando la utilidad de documentarlos objetivamente ([00:08:09](#00:08:09)).

---

**Tamaño de los modelos, cuantización y sistemas de tipo uno**: Jorge NICOLAU detalla la transición hacia modelos de lenguaje fluidos de menor tamaño (reduciendo de 3 mil millones a 1.6 mil millones de parámetros y aplicando cuantización basada en pesos cuantizados para optimizar el consumo de memoria RAM) ([00:09:50](#00:09:50)). Por su parte, Ezequiel Nuske introduce el concepto de sistemas de tipo uno —análogos al sistema cognitivo humano rápido—, los cuales responden de forma tipada (arrojando únicamente valores booleanos o escalas numéricas) en aproximadamente 200 milisegundos, optimizando los procesos en tiempo real en comparación con los modelos de lenguaje convencionales ([00:10:52](#00:10:52)).

---

**Especificaciones físicas y comportamiento de balanceo en la simulación**: Jorge NICOLAU analiza por qué los datos simulados presentan un marcado balanceo, descubriendo tras revisar las definiciones en formato JSON que el dron simulado tiene un tamaño físico de 1.5 a 1.2 metros, correspondiente a un modelo grande (DJI), lo cual justifica el comportamiento físico observado dentro de Unreal Engine ([00:14:24](#00:14:24)). Ezequiel Nuske acuerda incluir esta especificación física en la sección de discusión para mayor claridad ([00:15:22](#00:15:22)).

---

**Cierre de la tesis y definición de trabajos futuros**: Ezequiel Nuske y Jorge NICOLAU acuerdan cerrar definitivamente el alcance de la tesis sin realizar más experimentos adicionales, salvo la ejecución pendiente para comparar métricas de manera equitativa ([00:16:12](#00:16:12)). Se decide que posibles incorporaciones tecnológicas avanzadas, como una cámara binocular adicional o aprendizaje por refuerzo, queden relegadas como trabajos futuros para una futura tesis de doctorado, estimando Jorge NICOLAU que el depósito final de la tesis actual estará listo en aproximadamente una semana ([00:16:50](#00:16:50)).

*Revisa las notas de Gemini para asegurarte de que sean precisas. [Obtén sugerencias y descubre cómo Gemini toma notas](https://support.google.com/meet/answer/14754931)*

*Cómo es la calidad de **estas notas específicas?** [Responde una breve encuesta](https://google.qualtrics.com/jfe/form/SV_5bXzKQfylMIhSXc?confid=U5SK4QTcTuuTsoMkuAUzDxIQOBEQAjIGCIoCIAAYBQg&detailLevel=standard&hasImages=False&entryPoint=footerMain&isGoogler=False&lang=es-US) para darnos tu opinión; por ejemplo, cuán útiles te resultaron las notas.*

oct 20, 2026

## **Revisión Tesis \- Transcripción**

### **00:00:00**

**Jorge NICOLAU:** está. Ya viene takinges. Okay. Eh, a ver, varias cosas. Sí, ya sé que se me está desmadrando el tamaño del informe.

**Ezequiel Nuske:** Cerrémoslo.

**Jorge NICOLAU:** Quería preguntar por dónde agarr tijera porque claro,

**Ezequiel Nuske:** Cer No, no.

**Jorge NICOLAU:** salió lo de salió el pozo y entonces dio, "Ah, esto podría funcionar, esto me serviría.

**Ezequiel Nuske:** Sí, sí, pero no, no, no,

**Jorge NICOLAU:** Cada esto me serviría es una semana de probar.

**Ezequiel Nuske:** no, no. Pero lo vamos si terminamos de si tratamos de estar a a la misma velocidad de lo de de la ciencia que sale este no olvidate,

**Jorge NICOLAU:** No es una es una batalla perdida.

**Ezequiel Nuske:** no vamos a terminar más.

**Jorge NICOLAU:** Olvídate.

**Ezequiel Nuske:** Vamos a darle un cierre. Sí, vamos a darle un cierre. Sí,

**Jorge NICOLAU:** Entonces voy a buscar,

**Ezequiel Nuske:** déjame que mi

**Jorge NICOLAU:** voy a buscar las notas que me pusiste en la mail.

**Ezequiel Nuske:** Sí.

**Jorge NICOLAU:** email de cada día salen cosas más nuevas, más eficientes.

**Ezequiel Nuske:** Sí, pero por yo creo que ya recontrastamos porque además,

### **00:00:59**

**Jorge NICOLAU:** Sí, sí,

**Ezequiel Nuske:** ¿sabes por qué quiero que que presentes?

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** Porque eh se va a deslucir todo el laburo que hiciste, porque vos hiciste todo un laburo de setup del environment,

**Jorge NICOLAU:** claro,

**Ezequiel Nuske:** de calibración inicial y de todo eso que hoy día con los agentes ya se puede automatizar, pero vos lo hiciste toda manopla.

**Jorge NICOLAU:** claro,

**Ezequiel Nuske:** Entonces yo no quiero que se que se desluzca ese laburo, ¿viste?

**Jorge NICOLAU:** claro.

**Ezequiel Nuske:** Eh, nada,

**Jorge NICOLAU:** Sí,

**Ezequiel Nuske:** porque si no lo que va a decir un jurado es Sí,

**Jorge NICOLAU:** te entiendo.

**Ezequiel Nuske:** escúchame, yo lo pongo a Grock, este a Cloud Code y te lo esto te lo levanta en una noche. Sí, hermano,

**Jorge NICOLAU:** Sí,

**Ezequiel Nuske:** pero Claro,

**Jorge NICOLAU:** pero el entorno estaba armado antes de que salga CL del mercado justamente.

**Ezequiel Nuske:** claro, claro.

**Jorge NICOLAU:** Sí, sí, sí, sí,

**Ezequiel Nuske:** Por eso entonces quiero romper esa esa impresión.

**Jorge NICOLAU:** sí, claro. Okay, perfecto, perfecto. tema agar el email incorrecto. Okay. Tema principal, los capítulos 5 y 8 el sistema actual, pero resultado capítulo 11\. Tema resultado.

### **00:02:06** {#00:02:06}

**Ezequiel Nuske:** Está Mhm.

**Jorge NICOLAU:** Lo lo voy a correr de nuevo porque la última cosa que tú que traté no quiero cambiar nuevo el ¿cómo se llama? El grafo de control.

**Ezequiel Nuske:** Sí.

**Jorge NICOLAU:** Así que lo que vi es que un un BLM no solo no ayuda a a tomar mejores decisiones de navegación, sino es la caga,

**Ezequiel Nuske:** Okay.

**Jorge NICOLAU:** es mucho es mucho más eh eficiente utilizar otro otra herramienta de computer vision y lo voy a poner así.

**Ezequiel Nuske:** Tal cual.

**Jorge NICOLAU:** solamente puede servir en en algunos casos en que en que tenés este bloqueos muy raros, como por ejemplo hay un escenario que es un pueblito y tiene un montón de corredores arbolados

**Ezequiel Nuske:** Sí.

**Jorge NICOLAU:** y aparte tiene dos problemas, es visualmente complicado y el mes que que es lo que en realidad te define la La la colisión del dron no sigue no sigue la

**Ezequiel Nuske:** Mhm.

**Jorge NICOLAU:** descripción visual, como simplificado.

**Ezequiel Nuske:** Okay. Mhm.

**Jorge NICOLAU:** Vos ves el lo que renderiza real engine y lo ponés en Wframe y es totalmente es muy diferente, es parecido,

### **00:03:12**

**Ezequiel Nuske:** Okay.

**Jorge NICOLAU:** sigue, sigue. Entonces, entonces eso ya ahí te complica dos cosas. Te complica, o sea, visualmente lo que la información que recibe el drone es lo que renderiza real engine, pero la la grilla de colisión no coincide,

**Ezequiel Nuske:** Okay.

**Jorge NICOLAU:** ¿no? Entonces ese es el otro problema. Bueno,

**Ezequiel Nuske:** Y y ¿cómo hacemos para

**Jorge NICOLAU:** y está viendo que el centro de la ciudad también hay hay partes que que acá hay una acá hay un una escalera, por ejemplo, de servicio que debería chocar y ves que la traviesa ahí.

**Ezequiel Nuske:** Sí, no, la caja de colisión no te está no te está cerrando.

**Jorge NICOLAU:** Sí,

**Ezequiel Nuske:** Bueno, nada, marquémoslo como limitación de del entorno que tenemos.

**Jorge NICOLAU:** es una limitación de obviamente. Sí,

**Ezequiel Nuske:** Sí,

**Jorge NICOLAU:** sí.

**Ezequiel Nuske:** sí, sí, sí. No nos volvamos luego.

**Jorge NICOLAU:** Yo había puesto en el plan de tesis que que una de la uno de de los objetivos era hacer un una captura foto realista del entorno a partir de video,

**Ezequiel Nuske:** Sí.

### **00:04:01** {#00:04:01}

**Jorge NICOLAU:** pero eso es todo un problema por sí mismo.

**Ezequiel Nuske:** Bueno, lo lo lo documentamos, lo documentamos como que que es un problema que que la tecnología que tenemos hoy hoy por hoy no nos está ayudando para esto.

**Jorge NICOLAU:** Otra cosa,

**Ezequiel Nuske:** Y listo.

**Jorge NICOLAU:** con todas las cosas que probé para calcular a distancia, el tema de que sea monocular lo hace muy limitado.

**Ezequiel Nuske:** Okay. Okay.

**Jorge NICOLAU:** Por dos mangos podés hacer este un sistema binocular y y tenés la ventaja de de que el cálculo de distancia en los dos no tienen que ser dos

**Ezequiel Nuske:** Tienes la percepción de profundidad. ¿Sabes

**Jorge NICOLAU:** cámaras. Le pones un adaptador binocular, perdés información porque porque estás recortando la mitad del cuadro, ¿verdad? Pero la información que te aporta eh dos ojos separado es lo que usamos nosotros para calcular profundidad, ¿no?

**Ezequiel Nuske:** que odio hablar con vos, Jorge? Porque este, vos me decís estas cosas y yo te yo a mí me darían ganas de decirte, che, bueno, y pensemos en líder o o con milo de los modelos y decir, che, estaríamos bueno que usemos un un modelo sistema uno para probar qué anda con esto y no vamos a terminar nunca más para no vamos a

### **00:05:01** {#00:05:01}

**Jorge NICOLAU:** Claro. No,

**Ezequiel Nuske:** terminar nunca más,

**Jorge NICOLAU:** no terminar nunca.

**Ezequiel Nuske:** así que cerrémoslo, cerrémoslo.

**Jorge NICOLAU:** Aparte soy de la postura de de de Elo Má debería con visión debería poder supionar está elimo y está el ciber c taxi que tendrá 16 cámaras pero

**Ezequiel Nuske:** Sí. Mm.

**Jorge NICOLAU:** son ahora es mucho más barato una cámara que un líder pudiera ser un

**Ezequiel Nuske:** Claro,

**Jorge NICOLAU:** huevo claro sí que bueno,

**Ezequiel Nuske:** claro, claro. Total. Bueno, nada, nada. Este,

**Jorge NICOLAU:** dale Pokémon esto.

**Ezequiel Nuske:** enfoquémonos,

**Jorge NICOLAU:** Sí, sí. No, ¿por qué todo esto? Porque estoy por correo nuevo todo el set de el set de pruebas, incluso los de base,

**Ezequiel Nuske:** bien.

**Jorge NICOLAU:** que son los básicos,

**Ezequiel Nuske:** Sí,

**Jorge NICOLAU:** que no tiene ninguna ninguna obstáculo,

**Ezequiel Nuske:** sí.

**Jorge NICOLAU:** que a propósito está elegido el la traza para que no tenga obstáculo. Este y voy a correr de nuevo los tres que tienen obstáculo, ¿okay?

**Ezequiel Nuske:** Okay.

**Jorge NICOLAU:** Para ver la tasa de la tasa de de de mejora, ¿okay?

### **00:05:52**

**Jorge NICOLAU:** Eh, así que el 11 lo voy a escribir totalmente de nuevo.

**Ezequiel Nuske:** Bueno,

**Jorge NICOLAU:** Okay.

**Ezequiel Nuske:** me prometés que es la última vez que corremos que corremos todo este lote.

**Jorge NICOLAU:** Sí, sí. Sí, porque además yo lo de la lo de la lo de la semilla me parecía que eran poca, entonces me puse a googlear cantidad suficiente de semilla, cuánto dataset. Si hago un dataset, ¿cuánto tiene que tener? ¿Cuántos puntos tiene que tener? 1,000ón, 2 millones, 3 millones. Bueno, no me dice que este límite de este límite de, a ver, no me acuerdo el nombre italiano, eh, de Bon Ferroni. No sabía que existía.

**Ezequiel Nuske:** Ferroni. Sí,

**Jorge NICOLAU:** Creo que vimos alguna algún test de Bon Ferroni,

**Ezequiel Nuske:** sí, sí, sí,

**Jorge NICOLAU:** pero bueno,

**Ezequiel Nuske:** sí. Total,

**Jorge NICOLAU:** no sabía que había puesto,

**Ezequiel Nuske:** total,

**Jorge NICOLAU:** mira, esto es el mínimo, así que estoy por correrlo todo con 10 millón.

**Ezequiel Nuske:** con 10 semillas.

**Jorge NICOLAU:** Okay,

**Ezequiel Nuske:** Perfecto. Sí.

**Jorge NICOLAU:** perfecto.

### **00:06:38**

**Ezequiel Nuske:** Eh,

**Jorge NICOLAU:** Son como unas 48 horas más de test,

**Ezequiel Nuske:** ¿cuánto y

**Jorge NICOLAU:** pero las tengo que correr. No tuve, no tuve tiempo.

**Ezequiel Nuske:** sí lo puedes correr? 48 horas más.

**Jorge NICOLAU:** Sí, sí, sí, sí, sí.

**Ezequiel Nuske:** Listo.

**Jorge NICOLAU:** La dejo corriendo.

**Ezequiel Nuske:** Dale.

**Jorge NICOLAU:** Dejo, a ver, yo trabajo en mi casa, prendo la computadora, lo pongo a correr solo.

**Ezequiel Nuske:** Okay.

**Jorge NICOLAU:** Sí, sí,

**Ezequiel Nuske:** Genial.

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** Espectacular.

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** Bueno, listo. Entonces ese con ese experimento ya cerraríamos este quilombito que tenemos acá en el Listo.

**Jorge NICOLAU:** exactamente el tema de de relevancia estadística,

**Ezequiel Nuske:** Genial.

**Jorge NICOLAU:** ¿no?

**Ezequiel Nuske:** Sí, sí, sí, sí, sí, sí.

**Jorge NICOLAU:** Okay.

**Ezequiel Nuske:** Porque además eso nos va a generar un intervalo de confianza, ¿viste? va a estar va a estar bueno en ese aspecto. Este,

**Jorge NICOLAU:** Mm.

**Ezequiel Nuske:** nada,

**Jorge NICOLAU:** Clar

**Ezequiel Nuske:** eh eso me va a dejar muy tranquilo. Eh, entonces abajo lo de reencuadrar con lo que con lo que muestra el banco de

### **00:07:20** {#00:07:20}

**Jorge NICOLAU:** el banco de prueba.

**Ezequiel Nuske:** prueba.

**Jorge NICOLAU:** ¿Cómo me surgió el banco de prueba? Había había tanta y piloto y no me cerraba nada. Entonces, bueno, agarremos, tratemos de hacer un barrido más estructurado de lo que tengo y lo que no tengo.

**Ezequiel Nuske:** Sí,

**Jorge NICOLAU:** Y tenía como dos semanas de pilotos ahí que fallaban. Entonces,

**Ezequiel Nuske:** sí.

**Jorge NICOLAU:** lo que lo que hice es armar como un set de prueba, ver lo que decía el BLM que es limitado,

**Ezequiel Nuske:** Sí.

**Jorge NICOLAU:** son 3 billones de parámetro y lo que y lo que dice es un una modelo

**Ezequiel Nuske:** Sí.

**Jorge NICOLAU:** de frontera. Esto esto lo hice con Cloud. ¿Por qué? Por esto que Cloud me analice y vea lo que dijo el el el BLM. ¿Sí entendés? O sea, que un modelo de frontera que tiene más capacidad de elaborar lo que está viendo, me diga si lo que dijo el que el que el Edge sirve o no. Y con eso armé el banco de pruebas, ¿no?

### **00:08:09** {#00:08:09}

**Ezequiel Nuske:** Okay, está eso está buenísimo. Está buenísimo. Y el resultado que tenés está perfecto.

**Jorge NICOLAU:** O sea, es común. Exacto.

**Ezequiel Nuske:** Y contalo, contalo como no todos los resultados nos tienen que dar.

**Jorge NICOLAU:** Sí. A ver, el cloud no me hubiera permitido este si no hubiese hecho cosas con cloud como armar el visualizador de los set de pruebas, que si no hubiera sido un quilombo,

**Ezequiel Nuske:** Sí.

**Jorge NICOLAU:** cruzar la telemetría con la captura y todo eso, o sea, la última opción de prueba dice que capture dos cámaras,

**Ezequiel Nuske:** Mhm.

**Jorge NICOLAU:** la del dron y una que va siguiéndolo para que entender mejor la el contexto.

**Ezequiel Nuske:** S.

**Jorge NICOLAU:** Okay.

**Ezequiel Nuske:** Aha.

**Jorge NICOLAU:** Y eso lo y por ejemplo el visualizador que me que me sincroniza el estado del del grafo con el la línea de set de prueba con el fotograma, eso lo que hizo Cloud, no no me voy a poner hacerlo,

**Ezequiel Nuske:** Perfecto.

**Jorge NICOLAU:** ¿verdad?

**Ezequiel Nuske:** Sí, sí, sí, sí.

**Jorge NICOLAU:** lo mismo el el web de CSS para para trazar la bien

### **00:08:58**

**Ezequiel Nuske:** Perfecto,

**Jorge NICOLAU:** analizar.

**Ezequiel Nuske:** perfecto.

**Jorge NICOLAU:** Claro,

**Ezequiel Nuske:** Okay, eso lo dejamos bien. Entonces, eh no tenemos problemas con lo del banco de prueba.

**Jorge NICOLAU:** por eso te yo te había dicho del capítulo del uso de la no que no es menor, no es que no se puede hacer con sin pasa que me tomado 3 años.

**Ezequiel Nuske:** Es que ese es el tema.

**Jorge NICOLAU:** Ese es el punto

**Ezequiel Nuske:** Ese es el tema. Bueno, listo. Por eso, okay.

**Jorge NICOLAU:** perfecto.

**Ezequiel Nuske:** Eso, eso dejamos reencuadrado. Lo de la semilla. Ya dijimos K10 conferroni. Perfecto.

**Jorge NICOLAU:** Con K igual a a 10\. Sí,

**Ezequiel Nuske:** Perfecto.

**Jorge NICOLAU:** también la las pus semilla con números primos distinto. No sé si va a cambiar algo porque me parece que no acaba cambiar nada.

**Ezequiel Nuske:** No, no. Y si querés podemos hacer unap que lo tengo.

**Jorge NICOLAU:** Bueno, listo, listo,

**Ezequiel Nuske:** Basta, basta.

**Jorge NICOLAU:** basta. Sí, el resumen dice Quen y BFM.

**Ezequiel Nuske:** Sí,

**Jorge NICOLAU:** Yo empecé a usar LFM porque era mucho más eficiente.

### **00:09:50** {#00:09:50}

**Ezequiel Nuske:** sí.

**Jorge NICOLAU:** El,

**Ezequiel Nuske:** Okay.

**Jorge NICOLAU:** no sé si viste estos de Liqui, tienen como un procesamiento distinto,

**Ezequiel Nuske:** Sí,

**Jorge NICOLAU:** no sé si aprovechan lo de quad, pero ahora casi todos los modelos que están en face aprovechan el quad,

**Ezequiel Nuske:** sí,

**Jorge NICOLAU:** que es este básicamente el peso cuantizado.

**Ezequiel Nuske:** sí. La cuantización. Sí.

**Jorge NICOLAU:** Exactamente.

**Ezequiel Nuske:** Okay,

**Jorge NICOLAU:** Y eso consume mucho menos este RAM. Sí.

**Ezequiel Nuske:** perfecto.

**Jorge NICOLAU:** Y después una molada calculo 90 K. Ah, sí, el avance. Podría descartar dos por lo menos dos o tres apéndices. Por ejemplo, me gustaba una idea de de proponer el escenario de por reinforcement learning, pero es un, no sé,

**Ezequiel Nuske:** Sí,

**Jorge NICOLAU:** es un chino. No,

**Ezequiel Nuske:** sí,

**Jorge NICOLAU:** no lo voy a no lo voy a hacer. Simplemente escribí el el escribí el

**Ezequiel Nuske:** déjalo. No, lo de anexo de trabajos futuros, eso lo dejamos aparte y y eso este después si querés si querés presentar tesis de doctorado

### **00:10:52** {#00:10:52}

**Jorge NICOLAU:** buen perfecto.

**Ezequiel Nuske:** va para ahí. Sí.

**Jorge NICOLAU:** Es que hay 1 formas para entrar a la tesis de doctorado. Primero lo que pensé, okay, este, este o este LFM tiene los pesos abiertos, o sea, que con un poquito de entrenamiento lo podría afinar, un poquito de entrenamiento, sabe si me gasto 3,000 en AWS, ¿no?

**Ezequiel Nuske:** No,

**Jorge NICOLAU:** Sí,

**Ezequiel Nuske:** eh, ¿sabes lo que te iba a decir?

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** Este,

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** acá sí en este tipo de cosas sí te diría que más que estos sistemas cuantizados este vayamos tirándonos a un sistema tipo uno. Sí.

**Jorge NICOLAU:** okay.

**Ezequiel Nuske:** Eh,

**Jorge NICOLAU:** Tipo uno es con Q8,

**Ezequiel Nuske:** que son los no como sheviste estos sistemas o

**Jorge NICOLAU:** con K8. Okay.

**Ezequiel Nuske:** el man tiro el link lo ubicas o

**Jorge NICOLAU:** Sí. A ver. No.

**Ezequiel Nuske:** o son sistemas que sí.

**Jorge NICOLAU:** Olama. Sí. Oamaí,

**Ezequiel Nuske:** Hola,

**Jorge NICOLAU:** pero N.

**Ezequiel Nuske:** sí. Eh, mira, son son sistemas que eh se le llama tipo uno porque son como el análogo a a lo que es, viste que que nosotros en la mente tenemos dos sistemas, el sistema de tipo uno que te responde rápido así sin pensar y el sistema tipo dos que eh

### **00:11:50**

**Jorge NICOLAU:** Ah, sí.

**Ezequiel Nuske:** recuero.

**Jorge NICOLAU:** Ok.

**Ezequiel Nuske:** Entonces, la idea de esto es que vos estás generando o vos tenés un LLM y ese LLM

**Jorge NICOLAU:** Sí,

**Ezequiel Nuske:** este te está tipado. ¿Qué significa que está tipado? Que solamente te puede responder lo que vos le definís en el contrato, ¿sí? Que te puede responder solamente true false,

**Jorge NICOLAU:** correcto.

**Ezequiel Nuske:** eh una escala numérica y y son muchísimo muchísimo más rápidos que

**Jorge NICOLAU:** Ah,

**Ezequiel Nuske:** este los LLM normales, ¿viste? como no tienen que no no no van procesando por token,

**Jorge NICOLAU:** no tienen que usar su vocabulario sin la estructura.

**Ezequiel Nuske:** sino que te tiran, claro, te tira directamente o una probabilidad eh o una categoría o o algo así que que está tipado,

**Jorge NICOLAU:** Mm.

**Ezequiel Nuske:** eh tenés este respuestas en en 200 milisegundos, una cosa así. Entonces, eh nada,

**Jorge NICOLAU:** Está 200 milundos es claro,

**Ezequiel Nuske:** son sistemas que que y para un Llado con cualquier otro

**Jorge NICOLAU:** ¿no?

**Ezequiel Nuske:** Llás pasando por arriba.

**Jorge NICOLAU:** Un LM irregular está en 100, 100\.

### **00:12:49**

**Ezequiel Nuske:** Claro.

**Jorge NICOLAU:** Claro.

**Ezequiel Nuske:** Y y y lo que estamos trabajando acá,

**Jorge NICOLAU:** 200 es un Sí.

**Ezequiel Nuske:** que son este que son sistemas de tiempo real donde nada,

**Jorge NICOLAU:** Sistema de tiempo real. Claro, es otra historia.

**Ezequiel Nuske:** ¿no?

**Jorge NICOLAU:** Nada,

**Ezequiel Nuske:** Este,

**Jorge NICOLAU:** por eso me están dando lo el banco programa dice que es más eficiente no usar el salvo que sea un un algo muy peludo.

**Ezequiel Nuske:** claro. Bueno, eh eh eh y eso, ¿sabes por qué?

**Jorge NICOLAU:** Sí.

**Ezequiel Nuske:** ¿Sabes por qué? Porque Cloud está entrenado con un con eh con un dataset que todavía no conoce los sistemas tipo uno.

**Jorge NICOLAU:** Ah,

**Ezequiel Nuske:** Y vos este lo apuntas alguna de estas páginas o el sistema del comercial del JEB.

**Jorge NICOLAU:** sí. Ah, Jep, sí, lo vi. Lo que pasa que je no es instalable en leche.

**Ezequiel Nuske:** Bueno, no, no,

**Jorge NICOLAU:** Estoy hablando en email,

**Ezequiel Nuske:** no,

**Jorge NICOLAU:** no sé.

**Ezequiel Nuske:** pero el limb sí,

**Jorge NICOLAU:** Sí,

**Ezequiel Nuske:** el limbel es instalable y lo puedes correr local,

### **00:13:29**

**Jorge NICOLAU:** ya.

**Ezequiel Nuske:** pero si vos apuntas a tu cloud a estos sistemas tipo uno para que el tipo aprenda y sepan que existen y y lo tenés en el

**Jorge NICOLAU:** Sí, sí,

**Ezequiel Nuske:** contexto de que sabe que que existe esto, listo, ahí ya este abrís una puerta de posibilidad más. Basta, no vamos a abrir,

**Jorge NICOLAU:** bien.

**Ezequiel Nuske:** no vamos a hacer ningún otro experimento.

**Jorge NICOLAU:** No, no, no, no lo voy a hacer. Esto queda, esta configuración queda así, pero me interesa porque a ver,

**Ezequiel Nuske:** Esto lo pensamos para futuro.

**Jorge NICOLAU:** no 9 billones, 9 billones de parámetros es algo se puede, ¿no?

**Ezequiel Nuske:** Sí. Y encima es es rapidito, eh te responde te responde bien rápido,

**Jorge NICOLAU:** Bueno,

**Ezequiel Nuske:** ¿eh?

**Jorge NICOLAU:** este yo bajé del de tres de tres billones a este LFM de 1.6 porque no consume nada de memoria y sabes que no baja mucho el

**Ezequiel Nuske:** Okay,

**Jorge NICOLAU:** rendimiento, ¿no? Sí. La verdad,

**Ezequiel Nuske:** mira.

**Jorge NICOLAU:** bueno,

**Ezequiel Nuske:** Excelente.

**Jorge NICOLAU:** está anexo y después el rock de ocupación 7,5 corre el escribir agresivo.

### **00:14:24** {#00:14:24}

**Jorge NICOLAU:** Esto te estás refiriendo a la maniobra rataset el último.

**Ezequiel Nuske:** Eh, ¿dónde estás?

**Jorge NICOLAU:** algunos detalles. Resumen,

**Ezequiel Nuske:** Ah, a ver qué dice, ah, el RC de ocupación 7 es correr el script que ya tenés. Sí, lo agresión loía como la limitación. Sí, sí. Este, no, no te preocupes por eso. dejar.

**Jorge NICOLAU:** ¿vos sabes que yo me me preguntab por qué en los dataset que yo quería imitar el camino del drone real?

**Ezequiel Nuske:** Mm.

**Jorge NICOLAU:** Me pregun por tiene tanto pandeo. Después me pongo a leer la especificación en la definición de Jason y es un de

**Ezequiel Nuske:** Sí, sí.

**Jorge NICOLAU:** un metro y medio 12 que está simulando.

**Ezequiel Nuske:** Ah,

**Jorge NICOLAU:** Tiene una máxa de la putísima madre.

**Ezequiel Nuske:** okay. Claro.

**Jorge NICOLAU:** DJ 3 que se puede que vos si querés podés este e creo que tenés que compilar agarrar un un archivo en C en C++ y compilar el P para

**Ezequiel Nuske:** Mhm.

**Jorge NICOLAU:** que sea del tamaño que vos querés.

**Ezequiel Nuske:** Sí.

### **00:15:22** {#00:15:22}

**Jorge NICOLAU:** Pero el que viene por defecto es un bicho grande, eh,

**Ezequiel Nuske:** Ah, okay.

**Jorge NICOLAU:** es como Entonces si tiene sentido el pandeo ese que hacen.

**Ezequiel Nuske:** Mira,

**Jorge NICOLAU:** Claro,

**Ezequiel Nuske:** bueno, dejalo. Anotá eso y ponerlo pongámoslo eso en de la discusión. Así,

**Jorge NICOLAU:** si pong las especificaciones físicas porque el a ver,

**Ezequiel Nuske:** así queda claro.

**Jorge NICOLAU:** vos lo metés en el en el Andre sigue las leyes físicas.

**Ezequiel Nuske:** Sí, claro.

**Jorge NICOLAU:** Yo estaba leyendo que le puedes cambiar la gravedad y todas esas cosas.

**Ezequiel Nuske:** No, no.

**Jorge NICOLAU:** Vi vi que incluso el Anriel Engine lo usan para para probar eh modelos de acoplación en el espacio, acompanamiento en el espacio.

**Ezequiel Nuske:** Claro.

**Jorge NICOLAU:** Lo que hace este space de tirar una una constelación de satélite y que se acomoden, lo utilizan para eso también.

**Ezequiel Nuske:** Mira,

**Jorge NICOLAU:** Está bien pensado,

**Ezequiel Nuske:** estamos en la punta,

**Jorge NICOLAU:** la verdad.

**Ezequiel Nuske:** ¿eh?

**Jorge NICOLAU:** Punta. Bueno,

**Ezequiel Nuske:** No, pero por eso,

**Jorge NICOLAU:** dale.

**Ezequiel Nuske:** por eso, por eso eh yo quiero que la tecnología no nos pase por encima,

### **00:16:12** {#00:16:12}

**Jorge NICOLAU:** No,

**Ezequiel Nuske:** eh porque ya por eso digo,

**Jorge NICOLAU:** porque todo el día sale algo nuevo, así que no no está. Sí,

**Ezequiel Nuske:** cerrémoslo,

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** cerrémoslo,

**Jorge NICOLAU:** gracias.

**Ezequiel Nuske:** pegámosle el golpe en la cabeza y vamos a defenderlo.

**Jorge NICOLAU:** Perfecto. Y hago después pienso en una versión de 5000 palabra contando la novedad, así que sea publicable una vez que la aprueben,

**Ezequiel Nuske:** Dale. Sí, sí, sí,

**Jorge NICOLAU:** obviamente.

**Ezequiel Nuske:** sí,

**Jorge NICOLAU:** Sí,

**Ezequiel Nuske:** sí, sí, sí.

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** Una vez que que lo tengamos probado,

**Jorge NICOLAU:** sí.

**Ezequiel Nuske:** ya lo pasamos.

**Jorge NICOLAU:** Dale, perfecto.

**Ezequiel Nuske:** Perfecto, Jorge,

**Jorge NICOLAU:** Bueno,

**Ezequiel Nuske:** por fin este terminamos la reunión sin más experimentos, o sea, tenemos bueno este que es el último,

**Jorge NICOLAU:** sí.

**Ezequiel Nuske:** pero ya no más scope.

**Jorge NICOLAU:** Bueno, pero es es recorrer la prueba que ya había corrido con el otro, ¿no?

**Ezequiel Nuske:** Sí, sí. No, no,

**Jorge NICOLAU:** Y anotar y anotar el resultado y que sacar conclusiones.

**Ezequiel Nuske:** no quiero que simplemente es simplemente para comprar peras con peras,

### **00:16:50** {#00:16:50}

**Jorge NICOLAU:** Punto. Sí.

**Ezequiel Nuske:** manzanas con manzanas. No, no, no hay ningún

**Jorge NICOLAU:** Si me queda un experimento y no lo voy a hacer, pero el único experimento que me interesaba es agarrar y meter otra cámara al dron para ver que cómo es el comporte con binocular. Y tampoco es tan complicado porque el grafo tiene un nodo de percepción que es ahí donde se calcula, ya sea por n, ya sea por TTL. Podés cambiar eso y no lo voy a hacer, pero difícil.

**Ezequiel Nuske:** te propongo algo. Te propongo algo. Te propongo algo.

**Jorge NICOLAU:** Sí, sí,

**Ezequiel Nuske:** metamos la tesis así como está y si en el tiempo que tardan en

**Jorge NICOLAU:** sí,

**Ezequiel Nuske:** aprobarla,

**Jorge NICOLAU:** claro.

**Ezequiel Nuske:** el tiempo que tardan en aprobarla,

**Jorge NICOLAU:** En defenderla. Sí, sí,

**Ezequiel Nuske:** podés hacer ese experimento, lo metemos, pero primero metamos la tesis,

**Jorge NICOLAU:** sí, dale.

**Ezequiel Nuske:** eh,

**Jorge NICOLAU:** Sí, sí, te maté. Sí.

**Ezequiel Nuske:** para el depósito final.

**Jorge NICOLAU:** Y en todo caso aparecerá como parte del resultado de del del anexo que habla de maldición monocular.

### **00:17:44**

**Ezequiel Nuske:** Sí, sí, sí, sí. Después, este los anexos le puedes agregar los que quieran. Presentémosla, presentémosla y y listo.

**Jorge NICOLAU:** Perfecto, perfecto. Dale. Listo. Te digo cuando tenga esto, cálculo que espero cuando una semana esté.

**Ezequiel Nuske:** Dale.

**Jorge NICOLAU:** y luego y hablamos.

**Ezequiel Nuske:** Perfecto, Jorge. Me esta tesis está increíble,

**Jorge NICOLAU:** Ahí está.

**Ezequiel Nuske:** la verdad que que me encanta,

**Jorge NICOLAU:** Buenísim buenísimo.

**Ezequiel Nuske:** me encanta. Eh, está buenísimo y y lamento si no he sido lo suficientemente veemente como para achicarte el scope, eh,

**Jorge NICOLAU:** No, sí, sí.

**Ezequiel Nuske:** porque la verdad que necesito nada este

**Jorge NICOLAU:** Mira, yo ya me podría haber probado mil cosas y vos dijiste, "No, para, para, cortemos acá." Eso me ayuda,

**Ezequiel Nuske:** eh porque sí es que lo tenemos que cerrar,

**Jorge NICOLAU:** me ayuda mucho porque ya lo ves que lo hace todo el mundo, ¿no? Entonces es más,

**Ezequiel Nuske:** lo tenemos que cerrar.

**Jorge NICOLAU:** clar,

**Ezequiel Nuske:** Este, sí, tenemos que presentar y está buenísimo y me encanta, pero dejemos dejemos algo para trabajo futuro. Eh,

**Jorge NICOLAU:** perfecto.

**Ezequiel Nuske:** no quiero que le metas más trabajo porque vas a tener una tesis de maestría, vas a ser magista. Eh,

**Jorge NICOLAU:** Claro,

**Ezequiel Nuske:** si vos le querés meter un montón de de esfuerzo y laburo, está bien, pero vos te mereces un doctorado, o sea,

**Jorge NICOLAU:** claro.

**Ezequiel Nuske:** sí, clarísimo.

**Jorge NICOLAU:** Mm.

**Ezequiel Nuske:** Sí.

**Jorge NICOLAU:** Sí, sí. Bueno, dale. Perfecto. Bueno, gracias.

**Ezequiel Nuske:** Bueníore.

**Jorge NICOLAU:** Nos vemos.

### **La transcripción finalizó después de 00:19:01**

*Esta transcripción editable se generó por computadora y puede contener errores. Los usuarios también pueden cambiar el texto después de que se cree.*