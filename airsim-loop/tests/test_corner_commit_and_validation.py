"""vz en giro y freno por profundidad (2026-0929/0930).

2026-0930: los tests del compromiso de esquina, el reflejo contra contactos y el filtro de avance se
eliminaron junto con esa maquinaria (waypoint_tracker.py): las sub-metas ahora las decide el VLM.
"""
from __future__ import annotations

import src.navigation.waypoint_tracker as wt


# ---------------------------------------------------------------- vz con yaw_rate
def test_rotate_only_branch_requires_zero_vz():
    from pathlib import Path
    src = (Path(wt.__file__).parents[1] / "hardware" / "airsim_client.py").read_text(encoding="utf-8")
    # rotateByYawRateAsync descarta vz: el guard debe exigir |vz| pequeno
    assert "abs(vz) < 0.05 and abs(yaw_rate) > 0.01 and target_yaw is None" in src


# ---------------------------------------------------------------- sin freno por profundidad
def test_graph_ignores_external_depth_brake_key(monkeypatch):
    """2026-0930: el grafo ya no acepta un tope armado desde afuera con profundidad del simulador."""
    import numpy as np
    import src.agents.vlm_client as deliberative_mod
    from src.agents.graph import _build_nodes
    from src.perception.obstacle_field import empty_field

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", lambda payload: (None, "", 5.0, "stub"))
    sent = []

    class _Stub:
        loop_hz = 5.0

        def capture(self):
            return np.zeros((48, 64, 3), dtype=np.uint8), {}

        def execute_velocity(self, **k):
            sent.append(k)
            return True

    n = _build_nodes(_Stub())
    try:
        state = {
            "telemetry": {"position": {"x": 0.0, "y": 0.0, "z": -10.0}, "velocity": {"vx": 2.0, "vy": 0.0, "vz": 0.0},
                          "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
                          "collision": {"has_collided": False, "object_name": ""}, "source": "airsim"},
            "waypoint_guidance": {"target_wp": {"x": 50.0, "y": 0.0, "z": -10.0, "label": "WP_1"}, "distance": 50.0,
                                  "dist_xy": 50.0, "bearing_err_deg": 0.0, "vx": 2.0, "vy": 0.0, "vz": 0.0,
                                  "yaw_rate": 0.0, "ceiling_z": None},
            "obstacle_field": empty_field(), "deliberations": [], "slm_request_id": None, "evasion_stuck_cycles": 0,
            "active_maneuver": None, "maneuver_cycles_left": 0, "maneuver_command": None,
            "current_wp_index": 0, "next_action": "", "route": "", "_depth_brake_" + "left": 2,
        }
        state = n["navigate"](state)
        state = n["motor"](state)
        assert state["next_action"] != "RETROCEDER"
        assert state["_depth_brake_" + "left"] == 2                      # nadie lo consume
    finally:
        n["_deliberation_service"].stop()
