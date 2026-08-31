# F3.2: Logging estructurado por ciclo, un JSONL por corrida.
#
# Registra todo lo que F3.3 (runner + analyze) necesita para comparar los
# brazos SLM / FSM / reactivo: tasa de exito, colisiones, distancia minima a
# obstaculo, latencias por rama, invocaciones/fallback/timeout del SLM,
# adherencia al formato JSON. min_obstacle_dist_m sale del canal depth y es
# SOLO para metricas: no se realimenta al control (no contamina el experimento).
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Mismo orden que src/perception/obstacle_field.py:SECTORS -- se repite aca en
# vez de importar para no acoplar el logger al modulo de percepcion.
_CSV_SECTORS = ("izquierda", "centro", "derecha")

_CSV_FIELDNAMES = [
    "t", "cycle", "arm", "scenario", "seed",
    "route", "action", "wp_index", "dist_to_wp_m", "degraded",
    "pos_x", "pos_y", "pos_z", "vel_x", "vel_y", "vel_z", "yaw_deg",
    "has_collided", "collision_object", "min_obstacle_dist_m",
    "latency_ms_json",
    "slm_invoked", "slm_latency_ms", "slm_fallback", "slm_timeout", "slm_adherent",
] + [f"field_{s}_{k}" for s in _CSV_SECTORS for k in ("occ", "ttc_s", "conf", "blocked")]


class FlightLogger:
    """Escribe un registro JSON por ciclo a un archivo .jsonl, mas un summary.json final.

    Ademas escribe un .csv "plano" (mismo stem que out_path) con las columnas
    mas relevantes para inspeccion manual -- pedido explicito para poder
    revisar corridas de prueba interactivas (main.py) sin tener que parsear
    JSONL a mano.
    """

    def __init__(self, out_path: str, scenario: str = "default", seed: int = 0, arm: str = "slm") -> None:
        self.out_path = Path(out_path)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.scenario = scenario
        self.seed = seed
        self.arm = arm
        self._t0 = time.time()
        self._fh = open(self.out_path, "w", encoding="utf-8")
        self.csv_path = self.out_path.with_suffix(".csv")
        self._csv_fh = open(self.csv_path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_fh, fieldnames=_CSV_FIELDNAMES)
        self._csv_writer.writeheader()
        self._cycle = 0
        self._collisions = 0
        self._min_obstacle_dist: Optional[float] = None
        self._path_length_m = 0.0
        self._last_pos: Optional[Dict[str, float]] = None
        self._slm_invocations = 0
        self._slm_fallbacks = 0
        self._slm_timeouts = 0
        self._success = False
        self._route_histogram: Dict[str, int] = {}  # Contar por tipo de ruta

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

        # Contar ruta (keep_going, evasive, deliberative, etc.).
        route = state.get("route", "unknown")
        self._route_histogram[route] = self._route_histogram.get(route, 0) + 1

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

        field_dict = record["obstacle_field"]["sectors"] if record["obstacle_field"] else {}
        csv_row = {
            "t": record["t"],
            "cycle": record["cycle"],
            "arm": record["arm"],
            "scenario": record["scenario"],
            "seed": record["seed"],
            "route": record["route"],
            "action": record["action"],
            "wp_index": record["wp_index"],
            "dist_to_wp_m": record["dist_to_wp_m"],
            "degraded": record["degraded"],
            "pos_x": pos.get("x"), "pos_y": pos.get("y"), "pos_z": pos.get("z"),
            "vel_x": vel.get("x"), "vel_y": vel.get("y"), "vel_z": vel.get("z"),
            "yaw_deg": record["yaw_deg"],
            "has_collided": record["collision"]["has_collided"],
            "collision_object": record["collision"]["object"],
            "min_obstacle_dist_m": record["min_obstacle_dist_m"],
            "latency_ms_json": json.dumps(latency_ms, default=str),
            "slm_invoked": slm_block is not None,
            "slm_latency_ms": slm_block.get("latency_ms") if slm_block else None,
            "slm_fallback": slm_block.get("fallback") if slm_block else None,
            "slm_timeout": slm_block.get("timeout") if slm_block else None,
            "slm_adherent": slm_block.get("adherent") if slm_block else None,
        }
        for s in _CSV_SECTORS:
            cell = field_dict.get(s) or {}
            csv_row[f"field_{s}_occ"] = cell.get("occupancy")
            csv_row[f"field_{s}_ttc_s"] = cell.get("ttc_s")
            csv_row[f"field_{s}_conf"] = cell.get("confidence")
            csv_row[f"field_{s}_blocked"] = cell.get("blocked")
        self._csv_writer.writerow(csv_row)
        self._csv_fh.flush()

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
            "deliberation_rate": (self._slm_invocations / self._cycle) if self._cycle else 0.0,
            "slm_fallback_rate": (self._slm_fallbacks / self._slm_invocations) if self._slm_invocations else None,
            "slm_timeout_rate": (self._slm_timeouts / self._slm_invocations) if self._slm_invocations else None,
            "route_histogram": self._route_histogram,
        }
        summary_path = self.out_path.with_name(self.out_path.stem + ".summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        self._fh.close()
        self._csv_fh.close()
        return summary
