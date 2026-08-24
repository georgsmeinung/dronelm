# F3.2: Logging estructurado por ciclo, un JSONL por corrida.
#
# Registra todo lo que F3.3 (runner + analyze) necesita para comparar los
# brazos SLM / FSM / reactivo: tasa de exito, colisiones, distancia minima a
# obstaculo, latencias por rama, invocaciones/fallback/timeout del SLM,
# adherencia al formato JSON. min_obstacle_dist_m sale del canal depth y es
# SOLO para metricas: no se realimenta al control (no contamina el experimento).
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional


class FlightLogger:
    """Escribe un registro JSON por ciclo a un archivo .jsonl, mas un summary.json final."""

    def __init__(self, out_path: str, scenario: str = "default", seed: int = 0, arm: str = "slm") -> None:
        self.out_path = Path(out_path)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.scenario = scenario
        self.seed = seed
        self.arm = arm
        self._t0 = time.time()
        self._fh = open(self.out_path, "w", encoding="utf-8")
        self._cycle = 0
        self._collisions = 0
        self._min_obstacle_dist: Optional[float] = None
        self._path_length_m = 0.0
        self._last_pos: Optional[Dict[str, float]] = None
        self._slm_invocations = 0
        self._slm_fallbacks = 0
        self._slm_timeouts = 0
        self._success = False

    def log_cycle(
        self,
        state: Dict[str, Any],
        latency_ms: Dict[str, float],
        min_obstacle_dist_m: Optional[float] = None,
    ) -> None:
        self._cycle += 1
        telemetry = state.get("telemetry", {}) or {}
        pos = telemetry.get("position", {}) or {}
        vel = telemetry.get("velocity", {}) or {}
        orient = telemetry.get("orientation", {}) or {}
        collision = telemetry.get("collision", {}) or {}
        guidance = state.get("waypoint_guidance") or {}
        field = state.get("obstacle_field")

        if collision.get("has_collided"):
            self._collisions += 1

        if min_obstacle_dist_m is not None:
            if self._min_obstacle_dist is None or min_obstacle_dist_m < self._min_obstacle_dist:
                self._min_obstacle_dist = min_obstacle_dist_m

        if self._last_pos is not None:
            dx = float(pos.get("x", 0.0)) - self._last_pos.get("x", 0.0)
            dy = float(pos.get("y", 0.0)) - self._last_pos.get("y", 0.0)
            dz = float(pos.get("z", 0.0)) - self._last_pos.get("z", 0.0)
            self._path_length_m += (dx * dx + dy * dy + dz * dz) ** 0.5
        self._last_pos = {"x": pos.get("x", 0.0), "y": pos.get("y", 0.0), "z": pos.get("z", 0.0)}

        deliberations = state.get("deliberations") or []
        last_delib = deliberations[-1] if deliberations and state.get("route") == "deliberative" else None
        slm_block = None
        if last_delib is not None:
            self._slm_invocations += 1
            if last_delib.get("is_fallback"):
                self._slm_fallbacks += 1
            if last_delib.get("timeout"):
                self._slm_timeouts += 1
            slm_block = {
                "invoked": True,
                "latency_ms": last_delib.get("latency_ms"),
                "fallback": last_delib.get("is_fallback", False),
                "timeout": last_delib.get("timeout", False),
                "adherent": last_delib.get("adherent", False),
                "used_json_schema": last_delib.get("used_json_schema", False),
            }

        record = {
            "t": round(time.time() - self._t0, 3),
            "cycle": self._cycle,
            "arm": self.arm,
            "scenario": self.scenario,
            "seed": self.seed,
            "pos": pos,
            "vel": vel,
            "yaw_deg": round(__import__("math").degrees(float(orient.get("yaw", 0.0))), 2),
            "route": state.get("route", ""),
            "action": state.get("next_action", ""),
            "obstacle_field": field.to_dict() if field is not None else None,
            "latency_ms": latency_ms,
            "slm": slm_block,
            "collision": {"has_collided": bool(collision.get("has_collided", False)), "object": collision.get("object_name", "")},
            "min_obstacle_dist_m": min_obstacle_dist_m,
            "wp_index": state.get("current_wp_index", 0),
            "dist_to_wp_m": guidance.get("distance", 0.0),
            "degraded": state.get("degraded", False),
        }
        self._fh.write(json.dumps(record, default=str) + "\n")
        self._fh.flush()

    def mark_success(self, success: bool) -> None:
        self._success = success

    def close(self) -> Dict[str, Any]:
        summary = {
            "scenario": self.scenario,
            "seed": self.seed,
            "arm": self.arm,
            "cycles": self._cycle,
            "duration_s": round(time.time() - self._t0, 2),
            "success": self._success,
            "collisions": self._collisions,
            "min_obstacle_dist_m": self._min_obstacle_dist,
            "path_length_m": round(self._path_length_m, 2),
            "slm_invocations": self._slm_invocations,
            "slm_fallback_rate": (self._slm_fallbacks / self._slm_invocations) if self._slm_invocations else None,
            "slm_timeout_rate": (self._slm_timeouts / self._slm_invocations) if self._slm_invocations else None,
        }
        summary_path = self.out_path.with_name(self.out_path.stem + ".summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        self._fh.close()
        return summary
