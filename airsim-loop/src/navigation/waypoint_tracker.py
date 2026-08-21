from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

DEFAULT_ACCEPTANCE_RADIUS = float(os.getenv("WAYPOINT_ACCEPTANCE_RADIUS", "3.5"))
DEFAULT_CRUISE_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "5.0"))


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

    def set_waypoints(self, waypoints: List[Dict[str, Any]]) -> None:
        """Inicializa o reemplaza la lista de waypoints."""
        self.waypoints = waypoints or []
        self.current_index = 0
        self.is_completed = len(self.waypoints) == 0
        self._locked_turn_dir = None

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

        if seg_len > 1.0 and dist_xy > 3.0:
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
        else:
            # Aproximación final directa al waypoint
            target_yaw = math.atan2(dy, dx)

        # Error angular relativo respecto a la orientación actual del dron (-180° a +180°)
        delta_yaw = (target_yaw - current_yaw + math.pi) % (2.0 * math.pi) - math.pi
        delta_yaw_deg = math.degrees(delta_yaw)
        abs_err = abs(delta_yaw_deg)

        # Zona muerta de 2.5° para vuelo rectilíneo perfecto sin micro-correcciones continuas
        if abs_err <= 2.5:
            yaw_rate = 0.0
        else:
            kp_yaw = 0.35
            yaw_rate = max(-15.0, min(15.0, kp_yaw * delta_yaw_deg))

        # Avance continuo fluido de crucero sin frenazos intermitentes
        if abs_err > 60.0:
            # Curva pronunciada en lugar de giro sobre su eje (pivot turn) para no detenerse.
            vx = max(0.5, cruise_speed * 0.4)
        elif dist_3d < 4.0:
            vx = 1.2 * math.cos(delta_yaw)  # Aproximación suave en metros finales
        else:
            # Crucero lineal continuo: nunca bajar de 0.5 para que no parezca atascado
            vx = max(0.5, cruise_speed * math.cos(delta_yaw))

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
