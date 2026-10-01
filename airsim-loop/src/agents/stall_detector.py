"""Deteccion de atasco a nivel de proceso (persiste entre graph.invoke()).

2026-0930 -- de 5 senales solapadas quedan 4, cada una con un uso concreto en navigate_node:
  - imu_contact / blind_wall: reaccion inmediata (evasion lateral) ante un contacto que el flujo
    optico no ve.
  - stopped_prolonged: se ORDENO avanzar y el dron no se mueve (trabado)          -> deadlock.
  - wp_no_progress: ~10 s sin acercarse al objetivo actual                        -> deadlock.
Se quitaron `stuck_invisible` y `pos_freeze` (duplicaban a las anteriores) y los disparadores basados
en FlightTrajectory / contador del tracker / "frentes bloqueados" que vivian en graph.py: en las 12
corridas v2 disparaban deadlocks en paralelo y ninguna resolucion de deadlock mostro avance.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional, Tuple

try:
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / "config" / ".env")
except Exception:
    pass

_IMU_JITTER_ELEVATED_MPS2 = float(os.getenv("IMU_JITTER_ELEVATED_MPS2", "3.0"))
_IMU_JITTER_CRITICAL_MPS2 = float(os.getenv("IMU_JITTER_CRITICAL_MPS2", "8.0"))
_IMU_CONTACT_THRESHOLD_MPS2 = float(os.getenv("IMU_CONTACT_THRESHOLD_MPS2", "5.0"))

_CMD_BLIND_FWD_MIN_MPS = float(os.getenv("CMD_BLIND_FWD_MIN_MPS", "0.45"))
_CMD_BLIND_ACT_MAX_MPS = float(os.getenv("CMD_BLIND_ACT_MAX_MPS", "0.30"))
_CMD_BLIND_BF_MAX = float(os.getenv("CMD_BLIND_BF_MAX", "0.25"))
_CMD_BLIND_CYCLES = int(os.getenv("CMD_BLIND_CYCLES", "2"))

_STOPPED_DELIBERATIVE_CYCLES = int(os.getenv("STOPPED_DELIBERATIVE_CYCLES", "10"))
# Velocidad horizontal comandada minima para que "no moverse" cuente como detenido.
_STOPPED_MIN_CMD_MPS = float(os.getenv("STOPPED_MIN_CMD_MPS", "0.30"))

_WP_NO_PROGRESS_MIN_M = float(os.getenv("WP_NO_PROGRESS_MIN_M", "2.0"))
_WP_NO_PROGRESS_THRESHOLD = int(os.getenv("WP_NO_PROGRESS_THRESHOLD", "50"))

_OPTICAL_MIN_ALT_M = float(os.getenv("OPTICAL_MIN_ALT_M", "4.5"))


def _below_optical_floor(state: Dict[str, Any]) -> bool:
    """Despegue/aterrizaje: bajo el piso optico y sin techo detectado (con techo el dron vuela bajo
    a proposito y si debe poder marcar atasco)."""
    alt_m = abs(float(((state.get("telemetry") or {}).get("position") or {}).get("z", 0.0)))
    under_ceiling = (state.get("waypoint_guidance") or {}).get("ceiling_z") is not None
    return alt_m < _OPTICAL_MIN_ALT_M and not under_ceiling


def _target_key(state: Dict[str, Any]) -> Optional[Tuple[Any, float, float]]:
    wp = (state.get("waypoint_guidance") or {}).get("target_wp")
    if not isinstance(wp, dict):
        return None
    return (wp.get("label"), round(float(wp.get("x", 0.0)), 1), round(float(wp.get("y", 0.0)), 1))


class StallDetector:
    def __init__(self) -> None:
        self._imu_contact_cycles = 0
        self._jitter_level = "normal"
        self._blind_wall_cycles = 0
        self._stopped_cycles = 0
        self._wp_best_dist: Optional[float] = None
        self._wp_no_progress_cycles = 0
        self._target: Optional[Tuple[Any, float, float]] = None

    # --- Senales publicas (las lee navigate_node) ---
    @property
    def imu_contact(self) -> bool:
        return self._imu_contact_cycles >= 2

    @property
    def blind_wall(self) -> bool:
        return self._blind_wall_cycles >= _CMD_BLIND_CYCLES

    @property
    def stopped_prolonged(self) -> bool:
        return self._stopped_cycles >= _STOPPED_DELIBERATIVE_CYCLES

    @property
    def wp_no_progress(self) -> bool:
        return self._wp_no_progress_cycles >= _WP_NO_PROGRESS_THRESHOLD

    @property
    def stopped_cycles(self) -> int:
        return self._stopped_cycles

    @property
    def jitter_level(self) -> str:
        return self._jitter_level

    def reset(self) -> None:
        """Tras resolver un deadlock: el conteo arranca de cero."""
        self._stopped_cycles = 0
        self._wp_no_progress_cycles = 0
        self._wp_best_dist = None

    # --- Actualizacion ---
    def update(self, state: Dict[str, Any]) -> None:
        """Una vez por ciclo, despues de perception_node."""
        self._update_imu(state)
        self._update_blind_wall(state)
        self._update_stopped(state)
        self._update_wp_progress(state)

    def _update_imu(self, state: Dict[str, Any]) -> None:
        imu_la = (state.get("telemetry") or {}).get("imu_linear_acceleration") or {}
        jitter_rms = math.hypot(float(imu_la.get("ax", 0.0)), float(imu_la.get("ay", 0.0)))
        if jitter_rms >= _IMU_JITTER_CRITICAL_MPS2:
            self._jitter_level = "critico"
        elif jitter_rms >= _IMU_JITTER_ELEVATED_MPS2:
            self._jitter_level = "elevado"
        else:
            self._jitter_level = "normal"
        cmd = state.get("velocity_command") or {}
        cmd_speed = math.hypot(float(cmd.get("vx", 0.0)), float(cmd.get("vy", 0.0)))
        if jitter_rms >= _IMU_CONTACT_THRESHOLD_MPS2 and cmd_speed > 0.3:
            self._imu_contact_cycles += 1
        else:
            self._imu_contact_cycles = 0

    def _update_blind_wall(self, state: Dict[str, Any]) -> None:
        from src.perception.obstacle_field import empty_field

        cmd_vx = float((state.get("velocity_command") or {}).get("vx", 0.0))
        vel = (state.get("telemetry") or {}).get("velocity") or {}
        act_spd = math.hypot(float(vel.get("vx", 0.0)), float(vel.get("vy", 0.0)))
        prev = (state.get("prev_telemetry") or {}).get("velocity") or {}
        prev_spd = math.hypot(float(prev.get("vx", 0.0)), float(prev.get("vy", 0.0)))
        field = state.get("obstacle_field") or empty_field()
        blind = (
            cmd_vx >= _CMD_BLIND_FWD_MIN_MPS
            and act_spd < _CMD_BLIND_ACT_MAX_MPS
            and field.blocked_fraction() < _CMD_BLIND_BF_MAX
            and (prev_spd >= 0.20 or self._blind_wall_cycles > 0)
        )
        self._blind_wall_cycles = self._blind_wall_cycles + 1 if blind else 0

    def _update_stopped(self, state: Dict[str, Any]) -> None:
        """Ciclos seguidos en que se ORDENO avanzar y el dron no se movio.

        Antes contaba cualquier ciclo sin velocidad horizontal: en el despegue (subir y girar en el
        lugar, vx=0) llegaba a 15 y disparaba un deadlock falso en el 100 % de las corridas
        (citysim_pilot seed 99, c17-c20). Girar, subir o esperar en hover no es estar trabado.
        """
        vel = (state.get("telemetry") or {}).get("velocity") or {}
        act_spd = math.hypot(float(vel.get("vx", 0.0)), float(vel.get("vy", 0.0)))
        cmd = state.get("velocity_command") or {}
        cmd_spd = math.hypot(float(cmd.get("vx", 0.0)), float(cmd.get("vy", 0.0)))
        if act_spd > 0.10 or cmd_spd < _STOPPED_MIN_CMD_MPS or _below_optical_floor(state):
            self._stopped_cycles = 0
        else:
            self._stopped_cycles = min(self._stopped_cycles + 1, 200)

    def _update_wp_progress(self, state: Dict[str, Any]) -> None:
        """Ciclos sin acercarse WP_NO_PROGRESS_MIN_M al objetivo ACTUAL.

        El objetivo se identifica por etiqueta y posicion, no por indice: una sub-meta del VLM se
        inserta en el mismo indice y cambia la distancia de golpe (antes eso heredaba el "mejor"
        valor del objetivo anterior y disparaba un deadlock falso).
        """
        dist = float((state.get("waypoint_guidance") or {}).get("dist_xy") or 0.0)
        target = _target_key(state)
        suppress = (
            state.get("_scan_phase") is not None
            or bool(state.get("_escape_reset"))
            or _below_optical_floor(state)
        )
        if suppress or target != self._target or self._wp_best_dist is None:
            self._target = target
            self._wp_best_dist = dist
            self._wp_no_progress_cycles = 0
        elif dist < self._wp_best_dist - _WP_NO_PROGRESS_MIN_M:
            self._wp_best_dist = dist
            self._wp_no_progress_cycles = 0
        else:
            self._wp_no_progress_cycles = min(self._wp_no_progress_cycles + 1, 200)

    def publish(self, state: Dict[str, Any]) -> None:
        """Senales al estado, solo para logging."""
        state["imu_jitter_level"] = self._jitter_level
        state["imu_contact_event"] = self.imu_contact
        state["blind_wall_event"] = self.blind_wall
        state["_stopped_cycles"] = self._stopped_cycles
        state["_wp_no_progress_cycles"] = self._wp_no_progress_cycles
