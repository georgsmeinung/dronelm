"""Compromiso con la esquina, validacion contra contactos, freno por profundidad y vz en giro (2026-0929)."""
from __future__ import annotations

import math

import src.navigation.waypoint_tracker as wt
from src.navigation.waypoint_tracker import WaypointTracker


def _tracker(pos=(0.0, 0.0)):
    tr = WaypointTracker([{"x": 0.0, "y": 0.0, "z": -10.0, "label": "A"},
                          {"x": 100.0, "y": 0.0, "z": -10.0, "label": "B"}])
    tr.update({"x": 0.0, "y": 0.0, "z": -10.0})
    tr.update({"x": pos[0], "y": pos[1], "z": -10.0})
    return tr


def _temps(tr):
    return [(w["x"], w["y"]) for w in tr.waypoints if w.get("is_temporary")]


def test_young_pending_corner_is_not_replaced():
    tr = _tracker()
    assert tr.inject_corner_waypoint(10.0, 20.0, -10.0)
    assert not tr.inject_corner_waypoint(-30.0, 40.0, -10.0)          # dentro del compromiso
    assert _temps(tr) == [(10.0, 20.0)]


def test_pending_corner_is_replaceable_after_commit_window():
    tr = _tracker()
    tr.inject_corner_waypoint(10.0, 20.0, -10.0)
    for _ in range(wt.CORNER_COMMIT_CYCLES):
        tr.update({"x": 0.0, "y": 0.0, "z": -10.0})
    assert tr.inject_corner_waypoint(80.0, 5.0, -10.0)                # mas cerca de B=(100,0): pasa el filtro
    assert _temps(tr) == [(80.0, 5.0)]


def test_corner_mirrored_into_regressive_zone_is_rejected():
    tr = _tracker()
    tr.record_contact(8.0, 8.0)                                        # sobre el trayecto a (15,15)
    # (15,15) cruza el contacto -> reflejo a (-15,-15), pero dist(-15,-15, B=100,0)=116m > 100m
    assert not tr.inject_corner_waypoint(15.0, 15.0, -10.0)           # rechazada por filtro de avance
    assert _temps(tr) == []


def test_corner_far_from_contacts_is_kept():
    tr = _tracker()
    tr.record_contact(60.0, 60.0)
    tr.inject_corner_waypoint(15.0, 15.0, -10.0)
    assert _temps(tr) == [(15.0, 15.0)]


def test_contact_at_the_drone_feet_does_not_reject_the_escape():
    tr = _tracker()
    tr.record_contact(0.0, 0.0)                                        # donde quedo atascado
    tr.inject_corner_waypoint(15.0, 0.0, -10.0)
    assert _temps(tr) == [(15.0, 0.0)]


def test_mirror_is_skipped_when_it_is_also_blocked():
    tr = _tracker()
    tr.record_contact(8.0, 8.0)
    tr.record_contact(-8.0, -8.0)
    tr.inject_corner_waypoint(15.0, 15.0, -10.0)
    assert _temps(tr) == [(15.0, 15.0)]                                # sin alternativa: se conserva


# ---------------------------------------------------------------- filtro de avance
def test_progress_filter_accepts_corner_closer_to_wp():
    tr = _tracker()                                                    # dron en (0,0), WP B en (100,0)
    assert tr.inject_corner_waypoint(50.0, 0.0, -10.0)                # dist(50,0 -> B)=50m < 100m
    assert _temps(tr) == [(50.0, 0.0)]


def test_progress_filter_rejects_corner_farther_than_drone():
    tr = _tracker()                                                    # dron en (0,0), WP B en (100,0)
    assert not tr.inject_corner_waypoint(-50.0, 0.0, -10.0)           # dist(-50,0 -> B)=150m > 100m
    assert _temps(tr) == []


def test_progress_filter_skipped_when_no_last_pos():
    # Sin llamar a update(): _last_pos=None -> filtro omitido
    tr = WaypointTracker([{"x": 0.0, "y": 0.0, "z": -10.0, "label": "A"},
                          {"x": 100.0, "y": 0.0, "z": -10.0, "label": "B"}])
    assert tr.inject_corner_waypoint(-50.0, 0.0, -10.0)               # regresiva pero sin pos de referencia
    assert _temps(tr) == [(-50.0, 0.0)]


# ---------------------------------------------------------------- vz con yaw_rate
def test_rotate_only_branch_requires_zero_vz():
    from pathlib import Path
    src = (Path(wt.__file__).parents[1] / "hardware" / "airsim_client.py").read_text(encoding="utf-8")
    # rotateByYawRateAsync descarta vz: el guard debe exigir |vz| pequeno
    assert "abs(vz) < 0.05 and abs(yaw_rate) > 0.01 and target_yaw is None" in src


# ---------------------------------------------------------------- freno por profundidad
def test_depth_brake_caps_forward_speed_and_counts_down(monkeypatch):
    import numpy as np
    import src.agents.deep_scan as deep_scan_mod
    import src.agents.deliberative as deliberative_mod
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
            "current_wp_index": 0, "next_action": "", "route": "", "_depth_brake_left": 2,
        }
        for _ in range(3):
            state = n["navigate"](state)
            state = n["motor"](state)
        assert sent[0]["vx"] == 0.0 and sent[1]["vx"] == 0.0           # tope activo 2 ciclos
        assert state["_depth_brake_left"] == 0
    finally:
        n["_deliberation_service"].stop()
