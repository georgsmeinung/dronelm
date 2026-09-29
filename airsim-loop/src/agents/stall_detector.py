"""Process-level stall/obstacle detection encapsulation.

Replaces 15+ counter fields that lived in DroneState. The StallDetector is
instantiated once in _build_nodes() (alongside FlightTrajectory) and persists
across graph.invoke() calls. Each cycle: update(state) then publish(state).
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict

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

_STOPPED_CYCLES_THRESHOLD = int(os.getenv("STOPPED_CYCLES_THRESHOLD", "15"))
_STOPPED_DELIBERATIVE_CYCLES = int(os.getenv("STOPPED_DELIBERATIVE_CYCLES", "10"))

_POS_FREEZE_DIST_M = float(os.getenv("POS_FREEZE_DIST_M", "0.50"))
_POS_FREEZE_THRESHOLD = int(os.getenv("POS_FREEZE_THRESHOLD", "30"))

_WP_NO_PROGRESS_MIN_M = float(os.getenv("WP_NO_PROGRESS_MIN_M", "2.0"))
_WP_NO_PROGRESS_THRESHOLD = int(os.getenv("WP_NO_PROGRESS_THRESHOLD", "50"))

_OPTICAL_MIN_ALT_M = float(os.getenv("OPTICAL_MIN_ALT_M", "4.5"))


class StallDetector:
    """Unified stall/invisible-obstacle detection.

    Process-level singleton: counters persist across graph.invoke() calls.
    """

    def __init__(self) -> None:
        self._imu_contact_cycles: int = 0
        self._jitter_level: str = "normal"
        self._blind_wall_cycles: int = 0
        self._stopped_cycles: int = 0
        self._pos_freeze_cycles: int = 0
        self._pf_ref_x: float = 0.0
        self._pf_ref_y: float = 0.0
        self._pf_ref_age: int = 0
        self._pf_ref_set: bool = False
        self._wp_best_dist: float | None = None
        self._wp_no_progress_cycles: int = 0
        self._wp_np_wp_idx: int = 0

    # --- Public signals (read by navigate_node) ---

    @property
    def imu_contact(self) -> bool:
        return self._imu_contact_cycles >= 2

    @property
    def blind_wall(self) -> bool:
        return self._blind_wall_cycles >= _CMD_BLIND_CYCLES

    @property
    def stuck_invisible(self) -> bool:
        return (
            self.imu_contact
            or self.blind_wall
            or self._stopped_cycles >= _STOPPED_CYCLES_THRESHOLD
            or self._pos_freeze_cycles >= _POS_FREEZE_THRESHOLD
        )

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
    def pos_freeze_cycles(self) -> int:
        return self._pos_freeze_cycles

    def reset_freeze(self) -> None:
        """Reinicia contadores de inmovilidad tras un escape forzado."""
        self._pos_freeze_cycles = 0
        self._stopped_cycles = 0
        self._pf_ref_set = False

    @property
    def jitter_level(self) -> str:
        return self._jitter_level

    # --- Update methods ---

    def update(self, state: Dict[str, Any]) -> None:
        """Run all detectors. Call once per cycle, after perception_node."""
        self._update_imu(state)
        self._update_blind_wall(state)
        self._update_stopped(state)
        self._update_pos_freeze(state)
        self._update_wp_progress(state)

    def _update_imu(self, state: Dict[str, Any]) -> None:
        telemetry = state.get("telemetry") or {}
        imu_la = (telemetry.get("imu_linear_acceleration") or {}) if isinstance(telemetry, dict) else {}
        ax = float(imu_la.get("ax", 0.0))
        ay = float(imu_la.get("ay", 0.0))
        jitter_rms = math.sqrt(ax * ax + ay * ay)

        if jitter_rms >= _IMU_JITTER_CRITICAL_MPS2:
            self._jitter_level = "critico"
        elif jitter_rms >= _IMU_JITTER_ELEVATED_MPS2:
            self._jitter_level = "elevado"
        else:
            self._jitter_level = "normal"

        cmd_vel = state.get("velocity_command") or {}
        cmd_speed = math.hypot(float(cmd_vel.get("vx", 0.0)), float(cmd_vel.get("vy", 0.0)))
        if jitter_rms >= _IMU_CONTACT_THRESHOLD_MPS2 and cmd_speed > 0.3:
            self._imu_contact_cycles += 1
        else:
            self._imu_contact_cycles = 0

    def _update_blind_wall(self, state: Dict[str, Any]) -> None:
        from src.perception.obstacle_field import empty_field

        vel_cmd = state.get("velocity_command") or {}
        cmd_vx = float(vel_cmd.get("vx", 0.0))
        vel_now = (state.get("telemetry") or {}).get("velocity") or {}
        act_spd = math.sqrt(float(vel_now.get("vx", 0.0)) ** 2 + float(vel_now.get("vy", 0.0)) ** 2)
        prev_vel = (state.get("prev_telemetry") or {}).get("velocity") or {}
        prev_act_spd = math.sqrt(float(prev_vel.get("vx", 0.0)) ** 2 + float(prev_vel.get("vy", 0.0)) ** 2)
        field = state.get("obstacle_field") or empty_field()

        blind_cond = (
            cmd_vx >= _CMD_BLIND_FWD_MIN_MPS
            and act_spd < _CMD_BLIND_ACT_MAX_MPS
            and field.blocked_fraction() < _CMD_BLIND_BF_MAX
            and (prev_act_spd >= 0.20 or self._blind_wall_cycles > 0)
        )
        self._blind_wall_cycles = (self._blind_wall_cycles + 1) if blind_cond else 0

    def _update_stopped(self, state: Dict[str, Any]) -> None:
        vel_now = (state.get("telemetry") or {}).get("velocity") or {}
        act_spd = math.sqrt(float(vel_now.get("vx", 0.0)) ** 2 + float(vel_now.get("vy", 0.0)) ** 2)
        slm_active = state.get("slm_request_id") is not None
        if act_spd > 0.10 or slm_active:
            self._stopped_cycles = 0
        else:
            self._stopped_cycles = min(self._stopped_cycles + 1, 200)

    def _update_pos_freeze(self, state: Dict[str, Any]) -> None:
        telemetry = state.get("telemetry") or {}
        slm_active = state.get("slm_request_id") is not None
        scan_active = state.get("_scan_phase") is not None
        pos_now = telemetry.get("position") or {}
        px = float(pos_now.get("x", 0.0))
        py = float(pos_now.get("y", 0.0))

        if not self._pf_ref_set:
            self._pf_ref_x = px
            self._pf_ref_y = py
            self._pf_ref_age = 0
            self._pf_ref_set = True

        self._pf_ref_age += 1
        disp = math.sqrt((px - self._pf_ref_x) ** 2 + (py - self._pf_ref_y) ** 2)

        if disp >= _POS_FREEZE_DIST_M or slm_active or scan_active:
            self._pos_freeze_cycles = 0
            self._pf_ref_x = px
            self._pf_ref_y = py
            self._pf_ref_age = 0
        else:
            self._pos_freeze_cycles = min(self._pos_freeze_cycles + 1, 200)
            if self._pf_ref_age >= _POS_FREEZE_THRESHOLD:
                self._pf_ref_x = px
                self._pf_ref_y = py
                self._pf_ref_age = 0

    def _update_wp_progress(self, state: Dict[str, Any]) -> None:
        guidance = state.get("waypoint_guidance") or {}
        dist = float(guidance.get("dist_xy") or 0.0)
        wp_idx = int(state.get("current_wp_index") or 0)
        slm_active = state.get("slm_request_id") is not None
        scan_active = state.get("_scan_phase") is not None
        telemetry = state.get("telemetry") or {}
        alt_m = abs(float((telemetry.get("position") or {}).get("z", 0.0)))
        # Bajo el piso optico se suprime el conteo (despegue/aterrizaje) salvo que la altitud baja sea
        # deliberada por un techo detectado: ahi el dron vuela de verdad y debe poder marcar "sin progreso".
        under_ceiling = (state.get("waypoint_guidance") or {}).get("ceiling_z") is not None
        suppress = slm_active or scan_active or (alt_m < _OPTICAL_MIN_ALT_M and not under_ceiling)
        wp_changed = wp_idx != self._wp_np_wp_idx
        escape_reset = bool(state.get("_escape_reset"))

        if wp_changed or escape_reset or suppress:
            self._wp_best_dist = dist
            self._wp_np_wp_idx = wp_idx
            self._wp_no_progress_cycles = 0
        elif self._wp_best_dist is None or dist < self._wp_best_dist - _WP_NO_PROGRESS_MIN_M:
            self._wp_best_dist = dist
            self._wp_np_wp_idx = wp_idx
            self._wp_no_progress_cycles = 0
        else:
            if self._wp_best_dist is not None:
                self._wp_best_dist = min(self._wp_best_dist, dist)
            else:
                self._wp_best_dist = dist
            self._wp_np_wp_idx = wp_idx
            self._wp_no_progress_cycles = min(self._wp_no_progress_cycles + 1, 200)

    def publish(self, state: Dict[str, Any]) -> None:
        """Write boolean signals to state for logging and downstream compat."""
        state["imu_jitter_level"] = self._jitter_level
        state["imu_contact_event"] = self.imu_contact
        state["blind_wall_event"] = self.blind_wall
        state["stuck_invisible"] = self.stuck_invisible
        state["_stopped_cycles"] = self._stopped_cycles
        state["_pos_freeze_cycles"] = self._pos_freeze_cycles
        state["_wp_no_progress_cycles"] = self._wp_no_progress_cycles
