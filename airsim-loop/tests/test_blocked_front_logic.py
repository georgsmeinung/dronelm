"""Frente bloqueado: desvio comprometido, disparo por eventos repetidos y tope en el motor (2026-0929)."""
from __future__ import annotations

import numpy as np
import pytest

import src.agents.deep_scan as deep_scan_mod
import src.agents.deliberative as deliberative_mod
from src.agents.graph import _build_nodes
from src.perception.obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field


class _Stub:
    def __init__(self):
        self.loop_hz = 5.0
        self.commands = []

    def capture(self):
        return np.zeros((48, 64, 3), dtype=np.uint8), {}

    def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
        self.commands.append((vx, vy, vz, yaw_rate, target_yaw))
        return True


def _blocked_field():
    cells = {(s, b): Cell(sector=s, band=b, occupancy=0.9, ttc_s=1.0, confidence=0.9) for s in SECTORS for b in BANDS}
    return ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)


def _state(field):
    return {
        "telemetry": {"position": {"x": 0.0, "y": 0.0, "z": -10.0},
                      "velocity": {"vx": 1.0, "vy": 0.0, "vz": 0.0},
                      "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
                      "collision": {"has_collided": False, "object_name": ""}, "source": "airsim"},
        "waypoint_guidance": {"target_wp": {"x": 0.0, "y": -50.0, "z": -10.0, "label": "WP"}, "distance": 50.0,
                              "dist_xy": 50.0, "bearing_err_deg": 0.0, "vx": 3.0, "vy": 0.0, "vz": 0.0,
                              "yaw_rate": 0.0},
        "obstacle_field": field, "deliberations": [], "slm_request_id": None, "evasion_stuck_cycles": 0,
        "active_maneuver": None, "maneuver_cycles_left": 0, "maneuver_command": None,
        "current_wp_index": 0, "next_action": "", "route": "",
    }


@pytest.fixture
def nodes(monkeypatch):
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", lambda payload: (None, "", 5.0, "stub"))
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    n = _build_nodes(_Stub())
    yield n
    n["_deliberation_service"].stop()


def _finish_maneuver(state):
    state["active_maneuver"], state["maneuver_command"], state["maneuver_cycles_left"] = None, None, 0


def test_girar90_commits_a_lateral_detour_corner(nodes):
    state = nodes["navigate"](_state(_blocked_field()))
    assert state["next_action"] == "GIRAR_90"
    corner = state.get("inject_corner")
    assert corner is not None                                   # antes: giraba y volvia recto al muro
    # rumbo 0 rad + bearing_err 0 -> giro a +90 grados: la esquina queda a ~15 m hacia ese lado (y+)
    assert abs(corner["x"]) < 1.0 and 10.0 < corner["y"] < 20.0


def test_three_blocked_fronts_in_a_window_trigger_deadlock_even_with_progress(nodes):
    state = _state(_blocked_field())
    actions = []
    for _ in range(3):
        state = nodes["navigate"](state)
        actions.append(state["next_action"])
        _finish_maneuver(state)
    assert actions[:2] == ["GIRAR_90", "GIRAR_90"]
    assert actions[2] != "GIRAR_90"                             # el 3ro escala a la resolucion de deadlock
    assert state.get("_blocked_events") == 3
    assert int(state.get("_deadlock_cycles", 0)) >= 1


def test_motor_caps_cruise_without_flow_evidence_but_not_other_macros(nodes):
    stub = nodes["_airsim_client"]
    state = _state(empty_field())                               # source "none": sin evidencia
    cruise = {"macro_action": "MANTENER_RUMBO", "vx": 3.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0}
    seen = []
    for _ in range(4):
        state["velocity_command"] = dict(cruise)
        state["next_action"] = "MANTENER_RUMBO"
        state = nodes["motor"](state)
        seen.append(stub.commands[-1][0])
    assert seen[0] == 3.0 and seen[-1] == pytest.approx(1.5)    # tras unos ciclos ciegos el crucero se topa
    assert state["_speed_cap"] == pytest.approx(1.5)
    state["velocity_command"] = {"macro_action": "EVADIR_IZQUIERDA", "vx": 2.4, "vy": 0.0, "vz": 0.0, "yaw_rate": -15.0}
    state["next_action"] = "EVADIR_IZQUIERDA"
    nodes["motor"](state)
    assert stub.commands[-1][0] == 2.4                          # solo se topa MANTENER_RUMBO
