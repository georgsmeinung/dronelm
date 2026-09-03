from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

DEFAULT_ACCEPTANCE_RADIUS = float(os.getenv("WAYPOINT_ACCEPTANCE_RADIUS", "3.5"))
DEFAULT_CRUISE_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "5.0"))
# F2.5: margen (metros) para considerar que hubo progreso real hacia el
# waypoint activo. Un desvio Manhattan largo pero que reduce distancia no
# cuenta como atasco; solo cuenta la falta de progreso sostenida.
PROGRESS_EPS_M = float(os.getenv("WAYPOINT_PROGRESS_EPS_M", "0.5"))
# Umbral (metros) por debajo del cual la distancia horizontal al waypoint es
# demasiado chica para que atan2(dy,dx) devuelva un rumbo fisicamente
# significativo -- ver compute_guidance(). Confirmado en vuelo real
# (2026-0903, TOWNSIM_INI): un waypoint casi vertical (mismo x/y que el
# punto de partida, solo cambia z, para forzar un ascenso recto) producia un
# rumbo objetivo inestable ciclo a ciclo -- ruido de posicion de centimetros
# alcanzaba para que el angulo saltara decenas de grados -- visible en vuelo
# como una espiral durante el ascenso en vez de una subida derecha, y como
# deliberacion/evasion excesiva (la camara barria obstaculos distintos en
# cada giro espurio).
BEARING_UNSTABLE_DIST_XY_M = float(os.getenv("BEARING_UNSTABLE_DIST_XY_M", "1.0"))
# Suavizado exponencial (EMA) de vx/yaw_rate entre ciclos: alpha=1.0 desactiva
# el filtro (usa el valor crudo cada vez); valores mas bajos = mas suave pero
# mas lento en reaccionar a un cambio real de rumbo/velocidad. Con alpha=0.5
# a LOOP_HZ=5.0 el filtro converge a ~94% de un cambio escalon en ~4 ciclos
# (~0.8s). Ataca el ruido residual que la histeresis de umbrales (arriba) no
# cubre: incluso dentro de un mismo regimen, vx/yaw_rate se recalculan desde
# cero cada ciclo sin memoria del valor anterior.
GUIDANCE_SMOOTHING_ALPHA = float(os.getenv("GUIDANCE_SMOOTHING_ALPHA", "0.5"))
# Velocidad de acercamiento (m/s) por debajo de la cual se acepta que el dron
# "no progresa". Es el parametro que reconcilia PROGRESS_EPS_M (metros) con
# EVASION_STUCK_THRESHOLD (ciclos) -- ver effective_stall_threshold().
MIN_PROGRESS_SPEED_MPS = float(os.getenv("MIN_PROGRESS_SPEED_MPS", "0.25"))
# Error de rumbo (grados) por encima del cual un ciclo se considera "girando
# activamente hacia el waypoint" y se excluye del contador de atasco
# (2026-0826, ver CHANGELOG.md). record_progress() media el progreso solo por
# distancia radial al waypoint; al completar un tramo y arrancar el
# siguiente, la distancia apenas baja mientras el dron gira para encarar el
# nuevo rumbo (avance casi nulo por diseno, no por obstaculo), y el contador
# de atasco se disparaba en cada esquina -- confundiendo un giro normal con
# un deadlock real. Un obstaculo genuino se sigue detectando aparte via
# ObstacleField/TTC (policy_router), independiente de este contador.
PROGRESS_STALL_BEARING_EXEMPT_DEG = float(os.getenv("PROGRESS_STALL_BEARING_EXEMPT_DEG", "30.0"))
# Tope de ciclos CONSECUTIVOS que la exencion de arriba puede perdonar sin que
# el error de rumbo converja (2026-0827, ver CHANGELOG.md). La exencion no
# distingue un giro normal que progresa de uno que nunca converge -- si el
# dron queda fisicamente trabado (p. ej. enganchado en ramas, colision que no
# dispara has_collided) mientras intenta un giro grande, bearing_err_deg se
# mantiene sobre el umbral indefinidamente y el contador de atasco queda
# congelado para siempre, desactivando el escape de seguridad existente
# (GANAR_ALTURA por atasco en fsm.py/deliberative.py). Pasado este tope, se
# deja de eximir y el contador vuelve a acumular normalmente.
PROGRESS_STALL_BEARING_EXEMPT_MAX_CYCLES = int(os.getenv("PROGRESS_STALL_BEARING_EXEMPT_MAX_CYCLES", "15"))
# Topes de yaw_rate (grados/s) de compute_guidance(). El tope de giro brusco
# es mayor: con un solo tope de 15 deg/s, realinear un desvio de 70 grados
# tomaba 6-8s de giro (mas todavia por el EMA), mientras el reloj de atasco
# vencia en 1-2s -- el dron se declaraba atascado por no haber terminado un
# giro que el propio limitador le impedia terminar a tiempo.
YAW_RATE_MAX_DPS = float(os.getenv("GUIDANCE_YAW_RATE_MAX_DPS", "15.0"))
YAW_RATE_SHARP_MAX_DPS = float(os.getenv("GUIDANCE_YAW_RATE_SHARP_MAX_DPS", "45.0"))
# Ciclos de espera en el lugar (vx=0) al salir de un giro pronunciado, antes
# de retomar avance (2026-0826, ver CHANGELOG.md: "horcajadas" en las
# esquinas). Antes, un desvio grande (>60 grados) volaba en curva ancha a
# 40% de cruise en vez de girar en el lugar -- ese avance simultaneo al giro
# es lo que se percibia como bandazo. Ahora se detiene la traslacion durante
# el giro entero; este settle adicional despues de alinear le da a la
# percepcion (degradada durante rotacion rapida, ver FLOW_MAX_ROTATION_DEG en
# flow_ttc.py) un par de frames de baja rotacion para producir evidencia
# valida ANTES de comprometerse a avanzar -- el chequeo de corredor bloqueado
# de policy_router actua sobre esa evidencia en el primer ciclo de avance.
ORIENT_SETTLE_CYCLES = int(os.getenv("ORIENT_SETTLE_CYCLES", "2"))


def effective_stall_threshold() -> int:
    """Ciclos sin progreso antes de declarar atasco, coherente con la metrica.

    `record_progress()` solo resetea el contador cuando la distancia al
    waypoint mejora en PROGRESS_EPS_M metros. Declarar el umbral en CICLOS y
    el epsilon en METROS de forma independiente produce combinaciones
    imposibles: para nunca acumular atasco hace falta una velocidad de
    acercamiento de al menos `PROGRESS_EPS_M * LOOP_HZ / umbral`.

    Con los valores de .env del 2026-0824 (eps=0.5m, umbral=5 ciclos, 5Hz) eso
    exigia 0.5 m/s sostenidos. Durante un giro cerrado el guiado limita vx a
    `max(0.5, cruise*0.4)` = 0.8 m/s y el rumbo esta a ~70 grados del objetivo,
    o sea ~0.25 m/s de acercamiento real: el atasco se declaraba solo, sin
    ningun obstaculo, a los 5 ciclos de arrancar la mision (ver el vuelo del
    2026-0824, ciclos 1-5). Esta funcion eleva el umbral configurado hasta el
    minimo que hace fisicamente demostrable el progreso.
    """
    configured = int(os.getenv("EVASION_STUCK_THRESHOLD", "10"))
    eps_m = float(os.getenv("WAYPOINT_PROGRESS_EPS_M", PROGRESS_EPS_M))
    loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
    min_speed = float(os.getenv("MIN_PROGRESS_SPEED_MPS", MIN_PROGRESS_SPEED_MPS))

    if min_speed <= 0.0 or loop_hz <= 0.0:
        return max(1, configured)

    coherent = int(math.ceil(eps_m * loop_hz / min_speed))
    return max(1, configured, coherent)


def hard_stall_threshold() -> int:
    """Umbral de "atasco duro": a partir de aca el escape se fuerza aunque la
    percepcion crea ver un corredor libre.

    Es el techo del bypass por percepcion de policy_router/deliberative: un
    campo despejado espurio (o un sector con evidencia debil) no debe poder
    desactivar el escape indefinidamente.
    """
    factor = float(os.getenv("STUCK_HARD_FACTOR", "3.0"))
    return max(1, int(math.ceil(effective_stall_threshold() * max(1.0, factor))))


class WaypointTracker:
    """Gestiona el seguimiento secuencial de waypoints de una misión y el cálculo

    de guiado en coordenadas Body Frame (orientado al objetivo con ForwardOnly).
    """

    def __init__(
        self,
        waypoints: Optional[List[Dict[str, Any]]] = None,
        acceptance_radius: float = DEFAULT_ACCEPTANCE_RADIUS,
    ) -> None:
        self.waypoints: List[Dict[str, Any]] = waypoints or []
        self.acceptance_radius: float = acceptance_radius
        self.current_index: int = 0
        self.is_completed: bool = len(self.waypoints) == 0
        self._locked_turn_dir: Optional[int] = None
        # F2.5: seguimiento de progreso real (distancia minima vista al WP
        # activo) en lugar de contar ciclos en rutas evasivas/deliberativas.
        self._min_dist_seen: Optional[float] = None
        self.progress_stall_cycles: int = 0
        # Ciclos consecutivos eximidos del contador de atasco por estar
        # "girando activamente" (ver PROGRESS_STALL_BEARING_EXEMPT_MAX_CYCLES).
        self._bearing_exempt_streak: int = 0
        # Enclavamiento de "ya pase el waypoint activo por el eje del
        # corredor" (ver compute_guidance). Se resetea al avanzar de waypoint.
        self._overshot_latch: bool = False
        # Histeresis de compute_guidance() (banda de entrada != banda de
        # salida) para que abs_err/dist_3d oscilando justo en el borde de un
        # umbral no haga alternar vx/yaw_rate entre formulas cada ciclo --
        # esa alternancia es lo que se ve como cabeceo (pitch) en vuelo real.
        self._sharp_turn_active: bool = False
        self._final_approach_active: bool = False
        self._yaw_correcting: bool = False
        # Ciclos de espera en el lugar pendientes al salir de un giro
        # pronunciado, antes de retomar avance (ver ORIENT_SETTLE_CYCLES).
        self._orient_settle_cycles_left: int = 0
        # Estado del filtro EMA (ver GUIDANCE_SMOOTHING_ALPHA); None = sin
        # historia todavia, el primer valor calculado se usa tal cual.
        self._smoothed_vx: Optional[float] = None
        self._smoothed_yaw_rate: Optional[float] = None

    def set_waypoints(self, waypoints: List[Dict[str, Any]]) -> None:
        """Inicializa o reemplaza la lista de waypoints."""
        self.waypoints = waypoints or []
        self.current_index = 0
        self.is_completed = len(self.waypoints) == 0
        self._locked_turn_dir = None
        self._min_dist_seen = None
        self.progress_stall_cycles = 0
        self._bearing_exempt_streak = 0
        self._overshot_latch = False
        self._sharp_turn_active = False
        self._final_approach_active = False
        self._yaw_correcting = False
        self._orient_settle_cycles_left = 0
        self._smoothed_vx = None
        self._smoothed_yaw_rate = None

    def record_progress(self, dist_to_wp: float, bearing_err_deg: float = 0.0) -> int:
        """Registra la distancia actual al waypoint activo y actualiza el

        contador de ciclos sin progreso real (F2.5). Devuelve el contador
        actualizado. Un desvío correcto que sigue reduciendo la distancia
        mínima vista nunca incrementa el contador, aunque tome muchos ciclos.

        Si ``bearing_err_deg`` supera ``PROGRESS_STALL_BEARING_EXEMPT_DEG``,
        el dron esta girando activamente hacia el rumbo objetivo: el ciclo se
        excluye del conteo (ni incrementa ni resetea la distancia minima
        vista) en lugar de contarlo como atasco -- pero solo hasta
        ``PROGRESS_STALL_BEARING_EXEMPT_MAX_CYCLES`` ciclos consecutivos. Un
        giro que nunca converge (p. ej. el dron fisicamente trabado contra un
        obstaculo que no dispara colision) no debe poder eximirse para
        siempre: pasado el tope, se cuenta como atasco real para que el
        escape de seguridad existente pueda activarse.
        """
        if abs(bearing_err_deg) > PROGRESS_STALL_BEARING_EXEMPT_DEG:
            if self._bearing_exempt_streak < PROGRESS_STALL_BEARING_EXEMPT_MAX_CYCLES:
                self._bearing_exempt_streak += 1
                return self.progress_stall_cycles
            # Tope agotado: el giro no convergio en el plazo esperado, tratar
            # como atasco real (cae al conteo normal de abajo).
        else:
            self._bearing_exempt_streak = 0
        if self._min_dist_seen is None or dist_to_wp < self._min_dist_seen - PROGRESS_EPS_M:
            self._min_dist_seen = dist_to_wp
            self.progress_stall_cycles = 0
        else:
            self.progress_stall_cycles += 1
        return self.progress_stall_cycles

    def reset_progress(self) -> None:
        """Reinicio manual del contador de atasco (p. ej. tras un escape forzado)."""
        self._min_dist_seen = None
        self.progress_stall_cycles = 0
        self._bearing_exempt_streak = 0

    @property
    def current_waypoint(self) -> Optional[Dict[str, Any]]:
        """Retorna el waypoint activo actual o None si la misión ha concluido."""
        if self.is_completed or self.current_index >= len(self.waypoints):
            return None
        return self.waypoints[self.current_index]

    def inject_corner_waypoint(self, x: float, y: float, z: float, label: str = "CORNER_WP") -> bool:
        """Inserta un sub-waypoint temporal de esquina en la ruta para rodear una manzana."""
        if self.is_completed or self.current_index >= len(self.waypoints):
            return False

        # Evitar inyecciones duplicadas consecutivas
        current_wp = self.current_waypoint
        if current_wp and str(current_wp.get("label", "")).startswith("CORNER_"):
            dx = float(current_wp.get("x", 0.0)) - x
            dy = float(current_wp.get("y", 0.0)) - y
            if math.hypot(dx, dy) < 10.0:
                return False

        corner_wp = {
            "x": round(float(x), 2),
            "y": round(float(y), 2),
            "z": round(float(z), 2),
            "label": label,
            "is_temporary": True,
        }
        self.waypoints.insert(self.current_index, corner_wp)
        print(f"[Manhattan] Sub-waypoint de esquina inyectado: {label} (X: {corner_wp['x']}, Y: {corner_wp['y']}, Z: {corner_wp['z']})")
        return True

    def update(self, current_pos: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Verifica la posición del dron y avanza al siguiente waypoint si se alcanzó

        el radio de aceptación.
        """
        if self.is_completed or not self.waypoints:
            self.is_completed = True
            return None

        wp = self.waypoints[self.current_index]
        x = float(current_pos.get("x", 0.0))
        y = float(current_pos.get("y", 0.0))
        z = float(current_pos.get("z", 0.0))

        wx = float(wp.get("x", 0.0))
        wy = float(wp.get("y", 0.0))
        wz = float(wp.get("z", 0.0))

        dist_3d = math.sqrt((wx - x) ** 2 + (wy - y) ** 2 + (wz - z) ** 2)

        if dist_3d <= self.acceptance_radius:
            label = wp.get("label", f"WP_{self.current_index + 1}")
            print(f"[WaypointTracker] ¡Waypoint {label} alcanzado ({dist_3d:.2f}m)! Avanzando...")
            self.current_index += 1
            self._locked_turn_dir = None
            self._sharp_turn_active = False
            self._final_approach_active = False
            self._yaw_correcting = False
            self._orient_settle_cycles_left = 0
            self._overshot_latch = False
            # _smoothed_vx/_smoothed_yaw_rate NO se resetean aqui a proposito:
            # aproximan la velocidad real del dron, que es continua a traves
            # del cambio de waypoint activo (a diferencia de los flags de
            # histeresis, que son propiedades del segmento hacia el WP
            # anterior y no tiene sentido que sobrevivan al avance).
            self.reset_progress()
            if self.current_index >= len(self.waypoints):
                self.is_completed = True
                print("[WaypointTracker] ¡Misión completada! Todos los waypoints alcanzados.")
                return None
            return self.waypoints[self.current_index]

        return wp

    def compute_guidance(
        self,
        current_pos: Dict[str, float],
        current_yaw: float,
        cruise_speed: float = DEFAULT_CRUISE_SPEED,
    ) -> Dict[str, Any]:
        """Calcula el vector de velocidad en Body Frame hacia el waypoint activo.

        Returns:
            Dict con vx, vy, vz, target_wp, distance, bearing_err_deg, is_completed.
        """
        if self.is_completed or not self.waypoints:
            self._locked_turn_dir = None
            self._sharp_turn_active = False
            self._final_approach_active = False
            self._yaw_correcting = False
            self._orient_settle_cycles_left = 0
            return {
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "yaw_rate": 0.0,
                "target_yaw_deg": None,
                "target_wp": None,
                "distance": 0.0,
                "bearing_err_deg": 0.0,
                "is_completed": True,
            }

        wp = self.waypoints[self.current_index]
        x = float(current_pos.get("x", 0.0))
        y = float(current_pos.get("y", 0.0))
        z = float(current_pos.get("z", 0.0))

        wx = float(wp.get("x", 0.0))
        wy = float(wp.get("y", 0.0))
        wz = float(wp.get("z", 0.0))

        dx = wx - x
        dy = wy - y
        dz = wz - z

        dist_xy = math.hypot(dx, dy)
        dist_3d = math.sqrt(dx**2 + dy**2 + dz**2)

        # Identificar el waypoint de partida del segmento actual
        prev_idx = max(0, self.current_index - 1)
        prev_wp = self.waypoints[prev_idx] if prev_idx < len(self.waypoints) else wp

        # Vector del tramo de calle (Segmento A -> B)
        seg_x = wx - float(prev_wp.get("x", wx))
        seg_y = wy - float(prev_wp.get("y", wy))
        seg_len = math.hypot(seg_x, seg_y)

        # Progreso a lo largo del segmento (parametro t de la proyeccion de la
        # posicion actual sobre A->B, 0=en A, 1=en B). El cross-track error de
        # abajo solo mide desvio LATERAL a la linea infinita A->B -- no tiene
        # forma de saber si el dron ya paso el punto B. Sin este chequeo
        # (2026-0827, ver CHANGELOG.md), una maniobra evasiva que empuja al
        # dron mas alla de B mientras sigue a >3m de distancia (nunca entro al
        # radio de aceptacion) hace que el guiado en modo corredor lo siga
        # apuntando a lo largo de la extension infinita de la linea, en vez de
        # girarlo de vuelta hacia B -- el dron se aleja del waypoint sin limite.
        # Enclavamiento (2026-0828, ver CHANGELOG.md): el chequeo de arriba
        # solo evalua la posicion INSTANTANEA -- cerca del borde (t~1.0), un
        # desvio lateral minimo (perpendicular al segmento) puede hacer que
        # t_progress oscile por encima y por debajo de 1.0 ciclo a ciclo,
        # alternando el modo corredor/directo. Cada alternancia recalcula un
        # rumbo objetivo completamente distinto (la linea del corredor vs. el
        # punto real), lo que se traduce en saltos de decenas de grados en
        # bearing_err_deg de un ciclo al siguiente -- forzando un giro en el
        # lugar espurio justo en el tramo final antes de un waypoint (medido
        # en vuelo real: 5+ segundos frenado girando, en la aproximacion a
        # aterrizaje de townsim_demo). Una vez detectado el overshoot para el
        # waypoint activo, se mantiene el modo directo para el resto de la
        # aproximacion a ESE waypoint -- se libera solo al avanzar al
        # siguiente (ver update()).
        if seg_len > 1.0:
            t_progress = ((x - float(prev_wp.get("x", 0.0))) * seg_x + (y - float(prev_wp.get("y", 0.0))) * seg_y) / (seg_len**2)
            if t_progress >= 1.0:
                self._overshot_latch = True
        overshot_segment = self._overshot_latch

        if seg_len > 1.0 and dist_xy > 3.0 and not overshot_segment:
            # Ángulo del corredor de la calle
            street_yaw = math.atan2(seg_y, seg_x)

            # Cross-track error (desviación lateral perpendicular al eje de la calle)
            cte = (-(x - float(prev_wp.get("x", 0.0))) * seg_y + (y - float(prev_wp.get("y", 0.0))) * seg_x) / seg_len

            # Corrección angular suave para reincorporarse al centro de la calle (máximo ±20°)
            k_cte = 0.15
            cte_correction_rad = -math.atan(k_cte * cte)
            cte_correction_rad = max(-math.radians(20.0), min(math.radians(20.0), cte_correction_rad))

            # Rumbo deseado proyectado a lo largo del corredor
            target_yaw = street_yaw + cte_correction_rad
        elif dist_xy < BEARING_UNSTABLE_DIST_XY_M:
            # Vector horizontal casi nulo (waypoint casi directamente arriba/
            # abajo, o ya alcanzado en el plano horizontal): atan2(dy,dx) no
            # tiene un angulo fisicamente significativo que devolver aca, y
            # perseguirlo solo mete ruido. Mantener el rumbo actual.
            target_yaw = current_yaw
        else:
            # Aproximación final directa al waypoint (incluye el caso de
            # haberse pasado del punto B por el corredor: overshot_segment).
            target_yaw = math.atan2(dy, dx)

        # Error angular relativo respecto a la orientación actual del dron (-180° a +180°)
        delta_yaw = (target_yaw - current_yaw + math.pi) % (2.0 * math.pi) - math.pi
        delta_yaw_deg = math.degrees(delta_yaw)
        abs_err = abs(delta_yaw_deg)

        # Histeresis (banda de entrada != banda de salida) para que abs_err/
        # dist_3d oscilando justo en el borde no alterne la formula de vx/
        # yaw_rate cada ciclo -- esa alternancia es la causa del cabeceo
        # (pitch) observado en vuelo real: cada cambio de formula es un
        # salto discontinuo de velocidad que el controlador debe perseguir.
        if not self._yaw_correcting and abs_err > 2.5:
            self._yaw_correcting = True
        elif self._yaw_correcting and abs_err < 1.5:
            self._yaw_correcting = False

        was_sharp_turn = self._sharp_turn_active
        if not self._sharp_turn_active and abs_err > 60.0:
            self._sharp_turn_active = True
        elif self._sharp_turn_active and abs_err < 50.0:
            self._sharp_turn_active = False
        if was_sharp_turn and not self._sharp_turn_active:
            # Recien alineado tras un giro pronunciado: mantener vx=0 unos
            # ciclos mas para que la percepcion (degradada durante la
            # rotacion) tenga frames de baja rotacion validos antes de
            # comprometerse a avanzar (ver ORIENT_SETTLE_CYCLES).
            self._orient_settle_cycles_left = ORIENT_SETTLE_CYCLES

        if not self._final_approach_active and dist_3d < 4.0:
            self._final_approach_active = True
        elif self._final_approach_active and dist_3d > 4.5:
            self._final_approach_active = False

        # Zona muerta para vuelo rectilíneo perfecto sin micro-correcciones continuas
        if not self._yaw_correcting:
            yaw_rate = 0.0
        else:
            kp_yaw = 0.35
            # Mas autoridad de giro cuando el desvio es grande: con el tope
            # unico de 15 deg/s un desvio de 70 grados tardaba mas en
            # corregirse que lo que tarda el contador de atasco en dispararse.
            cap = YAW_RATE_SHARP_MAX_DPS if self._sharp_turn_active else YAW_RATE_MAX_DPS
            yaw_rate = max(-cap, min(cap, kp_yaw * delta_yaw_deg))

        # Avance continuo fluido de crucero sin frenazos intermitentes, EXCEPTO
        # durante un giro pronunciado: ahi se gira en el lugar (2026-0826, ver
        # CHANGELOG.md) en vez de volar en curva ancha simultaneamente con el
        # giro -- eso era lo que se percibia como bandazo/"horcajada" en las
        # esquinas. El settle posterior (ver arriba) retiene vx=0 un par de
        # ciclos mas tras alinear, dandole a la percepcion evidencia valida
        # antes del primer ciclo de avance; policy_router ya frena ese avance
        # si esa evidencia muestra un corredor bloqueado (evasive/deliberative
        # en vez de keep_going), sin cambios necesarios ahi.
        if self._sharp_turn_active:
            vx = 0.0
        elif self._orient_settle_cycles_left > 0:
            vx = 0.0
            self._orient_settle_cycles_left -= 1
        elif self._final_approach_active:
            vx = 1.2 * math.cos(delta_yaw)  # Aproximación suave en metros finales
        else:
            # Crucero lineal continuo: nunca bajar de 0.5 para que no parezca atascado
            vx = max(0.5, cruise_speed * math.cos(delta_yaw))

        # Suavizado exponencial (EMA): vx/yaw_rate se recalculan desde cero
        # cada ciclo a partir de la geometria instantanea, sin memoria del
        # valor anterior. Incluso dentro de un mismo regimen (sin cruzar
        # ningun umbral de histeresis), eso produce pequenos saltos ciclo a
        # ciclo que el controlador de AirSim persigue como cabeceo. El EMA
        # los convierte en una rampa.
        #
        # 2026-0826 (ver CHANGELOG.md): se probo un limitador de tasa
        # (m/s^2) separado de este EMA, para acotar la desaceleracion real
        # en la entrada/salida del pivot. Revertido: con cap=1.5 no cambio
        # el promedio de |vz| en vuelo real (0.0488 -> 0.0524, peor);
        # bajando el cap a 0.4 para forzar que el dedup de comandos
        # saltee reemisiones, el promedio empeoro mas (0.0581) Y ademas
        # peor: la rampa de despegue tan lenta no cubria PROGRESS_EPS_M
        # dentro de effective_stall_threshold(), disparando escapes
        # GANAR_ALTURA espurios a los pocos segundos de cada mision (falso
        # atasco). Conclusion: cada reemision real de comando (cambie mucho o
        # poco el valor) parece tener un costo de perturbacion fijo -- estirar
        # el cambio en mas ciclos mas chicos no reduce el total, solo lo
        # reparte, y en este caso ademas creaba una interaccion nueva con el
        # detector de atasco. El EMA solo (alpha=0.5) queda como esta.
        if self._smoothed_vx is None:
            self._smoothed_vx = vx
        else:
            self._smoothed_vx = GUIDANCE_SMOOTHING_ALPHA * vx + (1.0 - GUIDANCE_SMOOTHING_ALPHA) * self._smoothed_vx
        vx = self._smoothed_vx

        if self._smoothed_yaw_rate is None:
            self._smoothed_yaw_rate = yaw_rate
        else:
            self._smoothed_yaw_rate = (
                GUIDANCE_SMOOTHING_ALPHA * yaw_rate + (1.0 - GUIDANCE_SMOOTHING_ALPHA) * self._smoothed_yaw_rate
            )
        yaw_rate = self._smoothed_yaw_rate

        # Cero vuelo lateral (Avance frontal en el eje de la cámara)
        vy = 0.0

        # Corrección de altitud críticamente amortiguada con zona muerta
        # (NED: z negativo es hacia arriba). Zona muerta de 0.3m para evitar rebotes senoidales.
        if abs(dz) < 0.3:
            vz = 0.0
        else:
            vz = max(-0.8, min(0.8, 0.35 * dz))

        return {
            "vx": float(vx),
            "vy": 0.0,
            "vz": float(vz),
            "yaw_rate": float(yaw_rate),
            "target_yaw_deg": float(math.degrees(target_yaw)),
            "target_wp": wp,
            "distance": float(dist_3d),
            "dist_xy": float(dist_xy),
            "bearing_err_deg": float(delta_yaw_deg),
            "is_completed": False,
        }
