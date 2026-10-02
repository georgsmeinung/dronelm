"""La capa estrategica (grilla 3x3) atraviesa la frontera graph.invoke() del grafo COMPILADO."""
from __future__ import annotations

import math
import time

import numpy as np

import src.agents.vlm_client as deliberative_mod
import src.agents.vlm_strategic as vs


def test_strategic_subgoal_survives_compiled_graph(monkeypatch):
    monkeypatch.setattr("src.agents.graph.AGENT_ARM", "slm")
    monkeypatch.setattr(vs, "VLM_STRATEGIC_PERIOD_S", 0.0)
    calls = []

    def _query(payload):
        calls.append(payload.get("mode"))
        cells = {c: "bloqueado" for c in vs.CELLS}
        cells.update({"A2": "libre", "C2": "libre"})   # solo los costados, a la altura del dron
        return {"sectores": cells}, "{}", 30.0, None

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _query)
    from src.agents.graph import compile_workflow

    class _Client:
        def capture(self):
            return np.full((72, 108, 3), 90, dtype=np.uint8), {
                "position": {"x": 0.0, "y": 0.0, "z": -10.0}, "velocity": {"vx": 1.5, "vy": 0.0, "vz": 0.0},
                "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
                "collision": {"has_collided": False, "object_name": ""}, "timestamp": time.time(), "source": "airsim",
            }

        def execute_velocity(self, **k):
            return True

    graph, service = compile_workflow(_Client())
    try:
        state = {
            "waypoints": [{"x": 100.0, "y": 0.0, "z": -10.0, "label": "WP_1"}], "current_wp_index": 0,
            "waypoint_guidance": {"target_wp": {"x": 100.0, "y": 0.0, "z": -10.0, "label": "WP_1"},
                                  "distance": 100.0, "dist_xy": 100.0, "bearing_err_deg": 0.0,
                                  "vx": 2.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0, "ceiling_z": None},
            "deliberations": [], "evasion_stuck_cycles": 0, "active_maneuver": None, "maneuver_cycles_left": 0,
            "slm_request_id": None, "next_action": "",
        }
        corner = None
        for _ in range(40):
            state = graph.invoke(state)
            corner = state.pop("inject_corner", None) or corner
            if corner:
                break
            time.sleep(0.02)
        assert calls and set(calls) == {"strategic"}          # nunca el tactico por sector
        assert corner and corner["label"] == "VLM_SUBGOAL"
        assert abs(abs(math.degrees(math.atan2(corner["y"], corner["x"]))) - math.degrees(math.atan(36 / 54))) < 0.5
        assert state.get("_vlm_strategic", {}).get("outcome") == "subgoal"
        assert any(d.get("arm") == "vlm_strategic" for d in state.get("deliberations") or [])
    finally:
        service.stop()
