"""DroneState completo en CSV/JSONL (2026-0929)."""
from __future__ import annotations

import csv
import json

import numpy as np

from src.logging.flight_logger import FlightLogger
from src.logging.state_serializer import serialize_drone_state


def _state():
    return {
        "telemetry": {"position": {"x": 1.0, "y": 2.0, "z": -6.0}, "velocity": {"vx": 0, "vy": 0, "vz": 0},
                      "orientation": {"yaw": 0.0}, "collision": {"has_collided": False, "object_name": ""}},
        "waypoint_guidance": {"distance": float("inf"), "ceiling_z": -6.05},
        "obstacle_field": None, "route": "reactive", "next_action": "MANTENER_RUMBO",
        "current_wp_index": 0, "degraded": False,
        "rgb_image": np.zeros((4, 4, 3), dtype=np.uint8),
        "frame_history": [np.zeros((4, 4, 3))] * 2,
        "deliberations": [{"id": 1, "prompt": "P", "raw_response": "R", "macro_action": "RETROCEDER"}],
        "_scan_track": {"futile_scans": 2, "vertical_escapes": 1},
    }


def test_serializer_is_json_safe_and_drops_images():
    snap = serialize_drone_state(_state())
    json.dumps(snap, allow_nan=False)  # sin NaN/inf crudos
    assert snap["rgb_image"].startswith("<ndarray shape=(4, 4, 3)")
    assert snap["frame_history"] == "<2 items>"
    assert snap["waypoint_guidance"]["distance"] == "inf"
    assert snap["deliberations"]["count"] == 1
    assert "prompt" not in snap["deliberations"]["last"]
    assert snap["_scan_track"]["futile_scans"] == 2


def test_flatten_expands_nested_dicts_and_short_lists():
    from src.logging.state_serializer import flatten_state

    flat = flatten_state({"telemetry": {"position": {"x": 1.0, "z": -6.0}}, "foe": [3.0, 4.0],
                          "waypoints": [{"x": 1}, {"x": 2}], "n": 5, "none": None})
    assert flat["state.telemetry.position.z"] == -6.0
    assert flat["state.foe.0"] == 3.0 and flat["state.foe.1"] == 4.0
    assert flat["state.waypoints.0.x"] == 1 and flat["state.waypoints.1.x"] == 2   # lista de dicts corta
    long = flatten_state({"big": list(range(20))})
    assert json.loads(long["state.big"]) == list(range(20))                      # lista larga -> un JSON
    assert flat["state.n"] == 5 and flat["state.none"] is None


def test_logger_writes_flattened_state_columns_on_close(tmp_path):
    lg = FlightLogger(str(tmp_path / "r" / "r.jsonl"), scenario="s", seed=1, arm="slm")
    lg.log_cycle(_state(), latency_ms={"graph": 12.5, "telemetry": 3.0})
    lg.log_cycle(_state(), latency_ms={"graph": 13.5})
    lg.close()
    rows = list(csv.DictReader(open(tmp_path / "r" / "r.csv", encoding="utf-8")))
    assert len(rows) == 2
    r = rows[0]
    assert "state_json" not in r and "latency_ms_json" not in r
    assert r["latency_graph_ms"] == "12.5" and r["latency_telemetry_ms"] == "3.0"
    assert r["state.route"] == "reactive"
    assert r["state.waypoint_guidance.ceiling_z"] == "-6.05"
    assert r["state.waypoint_guidance.distance"] == "inf"
    assert r["state.telemetry.position.z"] == "-6.0"
    assert r["state._scan_track.futile_scans"] == "2"
    # ningun valor de columna es un blob JSON de un dict
    assert not any(str(v).startswith("{") for k, v in r.items() if k.startswith("state."))
    rec = json.loads(open(tmp_path / "r" / "r.jsonl", encoding="utf-8").readline())
    assert rec["state"]["current_wp_index"] == 0   # el JSONL conserva el estado anidado
