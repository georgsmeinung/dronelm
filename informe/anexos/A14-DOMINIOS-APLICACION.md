# Anexo 14: Dominios de aplicación de alta pertinencia local

El capítulo 2 (IT.2.4) sintetiza por qué los dominios de aplicación de este anexo motivan las restricciones de diseño del trabajo. Este anexo los desarrolla con su literatura. Ninguno de ellos se evalúa en la tesis, cuya evaluación es enteramente en simulación (cap. 1, IT.1.3): son la motivación de las restricciones —cámara monocular, cómputo local, sin conectividad—, no un ámbito de validación.

---

Cuatro dominios aplicados de relevancia para Argentina requieren exactamente lo que este trabajo estudia: percepción monocular en tiempo real, evasión reactiva y decisión de borde.

## A14.1 Vigilancia del litoral marítimo

Para una Zona Económica Exclusiva de 1,6 millones de km², Argentina acordó en 2026 incorporar drones VTOL V-Bat y aeronaves de patrulla ([Infobae, 2026](../13-REFERENCIAS.md#ref-infobae-2026)), y se discute un Sistema Nacional de Vigilancia Marítima con drones ([El Estratégico, 2026](../13-REFERENCIAS.md#ref-el-estrategico-2026)). La literatura específica es incipiente, pero [Barišić Kulas et al. (2025)](../13-REFERENCIAS.md#ref-barisic-2025) resuelven un problema isomorfo: detección e identificación autónoma de embarcaciones sobre grandes áreas marítimas, sin GNSS y con visión a bordo bajo restricciones de cómputo de borde.

## A14.2 Incendios forestales

El Ministerio de Ambiente opera 17 UAVs autónomos de detección temprana en parques nacionales de Neuquén y Chubut ([Argentina.gob.ar, s.f.](../13-REFERENCIAS.md#ref-argentina-sf)), y Misiones ensaya torres de videovigilancia con IA que despachan un dron autónomo al detectar humo ([Norte Misionero, 2026](../13-REFERENCIAS.md#ref-norte-misionero-2026)). La investigación internacional combina detección satelital y UAVs: [Liu y Sziranyi (2023)](../13-REFERENCIAS.md#ref-liu-c-2023) fusionan imágenes Sentinel-2 con UAVs que planifican rutas de evacuación, y [Danish et al. (2025)](../13-REFERENCIAS.md#ref-danish-2025) revisan sistemáticamente la gestión de incendios con UAVs de visión artificial.

## A14.3 Agricultura de precisión

Es el dominio de adopción más masiva en el país ([Dataportuaria, 2026](../13-REFERENCIAS.md#ref-dataportuaria-2026); [Infocampo, 2025](../13-REFERENCIAS.md#ref-infocampo-pulverizacion-2025)), con la Red de Drones del INTA extendiendo su uso al fenotipado y el monitoreo ([INTA, 2025](../13-REFERENCIAS.md#ref-inta-2025)) y ensayos que detectan y corrigen fallas de plantación en el mismo ciclo operativo ([Agrolatam, 2025](../13-REFERENCIAS.md#ref-agrolatam-2025)). La literatura converge en el problema técnico de este trabajo: [Zhang et al. (2024)](../13-REFERENCIAS.md#ref-zhang-g-2024) planifican trayectorias bajo restricciones de batería; [Wei et al. (2025)](../13-REFERENCIAS.md#ref-wei-2025) navegan dentro de las hileras de un huerto con una sola cámara frontal, y [Li et al. (2025)](../13-REFERENCIAS.md#ref-li-j-2025) resuelven lo mismo con LiDAR, la disyuntiva de costo sensorial que motiva la elección monocular de este trabajo; [Castro et al. (2020)](../13-REFERENCIAS.md#ref-castro-2020) fenotipan pasturas con cámaras RGB de bajo costo. El vuelo cercano a canopeo, ramas y alambrados es la morfología de obstáculo orgánico que reproduce el Tier 1 (`TownSim`).

## A14.4 Seguridad y logística urbana en Buenos Aires

Es el único de los cuatro dominios que ya opera UAVs en el mismo tejido urbano que reproduce el entorno de evaluación: el Escuadrón de Drones de la Policía de la Ciudad, integrado a un sistema de videovigilancia con 3.400 cámaras ([Perfil, 2026](../13-REFERENCIAS.md#ref-perfil-2026)), vuela con sensores capaces de detectar cables de un milímetro —el desafío de estructuras delgadas que enfrenta el flujo óptico de este trabajo— en persecuciones, incendios y búsqueda de personas ([Buenos Aires Ciudad, 2023](../13-REFERENCIAS.md#ref-buenos-aires-ciudad-2023)), y la Ciudad habilitó la entrega comercial con drones ([iProfesional, 2025](../13-REFERENCIAS.md#ref-iprofesional-2025)). Sus cañones en cuadrícula, con GPS degradado y cableado cercano, son la morfología del Tier 2 (`CitySim`).

## A14.5 Patrón común

En los cuatro dominios, el patrón subyacente —un vehículo que percibe en tiempo real y decide sin intervención humana bajo restricciones de cómputo de borde— es el que este trabajo estudia en simulación. La escasez de literatura argentina específica no resta relevancia a los resultados: señala una oportunidad de transferencia directa.
