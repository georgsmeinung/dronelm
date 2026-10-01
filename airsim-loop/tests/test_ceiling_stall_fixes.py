"""Bloqueo bajo el techo de la autopista (seed 99 02:57, 2026-0929): 4 correcciones encadenadas."""
from __future__ import annotations

import math
import time

import numpy as np
import pytest

import src.agents.deep_scan as deep_scan_mod
import src.agents.vlm_client as deliberative_mod
import src.navigation.waypoint_tracker as wt
from src.agents.graph import _build_nodes
from src.navigation.waypoint_tracker import CEILING_DETECT_CYCLES, WaypointTracker
from src.perception.obstacle_field import empty_field

CORNER = {"x": -11.46, "y": -11.26, "z": -10.0, "label": "CORNER_WP"}


def _tracker_under_ceiling():
    tr = WaypointTracker([dict(CORNER), {"x": 26.0, "y": -78.0, "z": -10.0, "label": "WP_1"}])
    warm = {"x": -5.0, "y": -12.0, "z": -5.83}
    yaw0 = math.atan2(CORNER["y"] - warm["y"], CORNER["x"] - warm["x"])  # mirando al WP: sin histeresis de giro residual
    for _ in range(CEILING_DETECT_CYCLES + 2):                       # detectar techo a z=-5.83
        tr.compute_guidance(warm, yaw0)
    assert tr.ceiling_z is not None
    return tr


# ------------------------------------------------- 1. aceptacion horizontal bajo techo
def test_wp_is_accepted_by_horizontal_distance_under_a_ceiling():
    tr = _tracker_under_ceiling()
    # z=-4.4: con la z del WP sin limitar (-10) la distancia 3D seria >= 5.6 m y jamas se aceptaba
    tr.update({"x": -8.5, "y": -12.0, "z": -4.4})                    # dist_xy ~ 3.2 m < 3.5 m
    assert tr.current_index == 1                                     # esquina aceptada


def test_without_ceiling_the_3d_distance_still_applies():
    tr = WaypointTracker([dict(CORNER), {"x": 26.0, "y": -78.0, "z": -10.0, "label": "WP_1"}])
    tr.update({"x": -8.5, "y": -12.0, "z": -4.4})                    # 3D ~ 6.4 m: no se acepta
    assert tr.current_index == 0


# ------------------------------------------------- 2. "vertical puro" solo si el WP es realmente vertical
def test_small_altitude_error_does_not_zero_forward_speed(monkeypatch):
    monkeypatch.setattr(wt, "BEARING_UNSTABLE_DIST_XY_M", 4.0)       # valor real de config/.env (en tests no se carga)
    pos = {"x": -8.6, "y": -13.9, "z": -4.42}                        # posicion real del bloqueo: 3.89 m horizontales, dz < 1 m
    yaw = math.atan2(CORNER["y"] - pos["y"], CORNER["x"] - pos["x"])  # ya orientado al WP (sin giro en el sitio)

    def _vx():
        tr = _tracker_under_ceiling()
        tr._orient_settle_cycles_left = 0                            # sin espera de orientacion pendiente
        vx = None
        for _ in range(12):                                          # regimen permanente: vx pasa por un EMA
            vx = tr.compute_guidance(pos, yaw)["vx"]
        return vx

    assert _vx() > 0.0                                               # antes vx=0 durante 178 ciclos
    monkeypatch.setattr(wt, "NEAR_VERTICAL_RATIO", 0.0)              # control: la regla antigua (|dz| > 0.3 sin cono)
    assert _vx() < 0.05                                              # converge a parado, como en la corrida real


def test_wp_almost_directly_above_is_still_vertical_only():
    tr = WaypointTracker([{"x": 0.5, "y": 0.0, "z": -10.0, "label": "ASCENSO"}])
    g = tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -1.5}, 0.0)    # 0.5 m horizontales, 8.5 m de altura
    assert g["vx"] == 0.0 and g["vz"] < 0.0                          # sigue ascendiendo en vertical


# ------------------------------------------------- 3. y 4. grafo
class _Stub:
    def __init__(self):
        self.loop_hz = 5.0

    def capture(self):
        return np.zeros((48, 64, 3), dtype=np.uint8), {}

    def execute_velocity(self, *a, **k):
        return True


def _state(z, ceiling):
    return {
        "telemetry": {"position": {"x": 0.0, "y": 0.0, "z": z}, "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
                      "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
                      "collision": {"has_collided": False, "object_name": ""}, "source": "airsim"},
        "waypoint_guidance": {"target_wp": {"x": -11.0, "y": -11.0, "z": -10.0, "label": "CORNER_WP"},
                              "distance": 4.0, "dist_xy": 3.9, "bearing_err_deg": 0.0, "vx": 0.5, "vy": 0.0,
                              "vz": 0.0, "yaw_rate": 0.0, "ceiling_z": ceiling},
        "obstacle_field": empty_field(), "deliberations": [], "slm_request_id": None, "evasion_stuck_cycles": 0,
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


def test_below_optical_floor_under_ceiling_still_escalates_a_stopped_drone(nodes):
    state = _state(z=-4.4, ceiling=-5.83)                              # alt 4.4 < piso optico 4.5, por un techo
    actions = []
    for _ in range(14):
        state = nodes["navigate"](state)
        actions.append(state["next_action"])
        if state.get("active_maneuver"):
            break
    assert any(a != "MANTENER_RUMBO" for a in actions)                # antes: 158 ciclos parado sin reaccion
    assert int(state.get("_deadlock_cycles", 0)) >= 1


def test_below_optical_floor_without_ceiling_stays_pure_reactive(nodes):
    state = _state(z=-4.4, ceiling=None)                               # despegue/aterrizaje: comportamiento previo
    for _ in range(14):
        state = nodes["navigate"](state)
        assert state["next_action"] == "MANTENER_RUMBO" and state["route"] == "reactive"
    assert int(state.get("_deadlock_cycles", 0)) == 0


def test_scan_in_progress_owns_the_drone_until_resolved(nodes):
    """2026-0930: reemplaza la deteccion de escaneo "huerfano" (71 descartes en las corridas v2): un
    barrido en curso tiene prioridad en navigate_node hasta resolver o caer por sus watchdogs."""
    state = _state(z=-10.0, ceiling=None)
    state["telemetry"]["velocity"]["vx"] = 2.0                        # volando: ningun detector de atasco activo
    state.update({"_scan_phase": "rotando", "_scan_started_ts": time.time(), "_scan_start_yaw_deg": 0.0,
                  "_scan_heading_index": 1, "_deliberation_pending": True})
    state = nodes["navigate"](state)
    assert state["next_action"] == "ESCANEO" and state.get("_scan_phase") is not None
