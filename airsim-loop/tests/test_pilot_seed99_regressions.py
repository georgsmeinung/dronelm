"""Regresiones del piloto v3 citysim_pilot seed 99 (2026-09-30 220813Z).

Secuencia real: el dron avanzaba mientras subia y llego al parapeto de la autopista elevada a 7.4 m;
un GIRAR_90 (vz=0) con el guiado pidiendo subir fabrico un techo falso en z=-7.44; el WP quedo
"bloqueado verticalmente" y PERDER_ALTURA se repitio 220 ciclos con el dron apoyado en el parapeto.
AirSim reportaba 0.31 m/s horizontales con la posicion fija, asi que "detenido" nunca conto, y la
regla de techo precedia a la de deadlock.
"""
from __future__ import annotations

import time

import numpy as np

import src.agents.deep_scan as deep_scan_mod
import src.agents.vlm_client as vlm_client
from src.agents.stall_detector import StallDetector, measured_xy_speed
from src.navigation.waypoint_tracker import CEILING_DETECT_CYCLES, WaypointTracker

WPS = [{"x": -11.0, "y": -50.5, "z": -10.0, "label": "WP_0_SUR"},
       {"x": 26.1, "y": -78.2, "z": -10.0, "label": "WP_1"}]


# --------------------------------------------------------------------------- techo falso
def test_turn_in_place_with_zero_vz_does_not_fabricate_a_ceiling():
    tr = WaypointTracker([dict(w) for w in WPS])
    for _ in range(CEILING_DETECT_CYCLES + 5):
        tr.compute_guidance({"x": -2.6, "y": -3.9, "z": -7.44}, 0.0)   # el guiado pide subir
        tr.note_executed_command({"macro_action": "GIRAR_90", "vx": 0.0, "vz": 0.0, "yaw_rate": 20.0})
    assert tr.ceiling_z is None


def test_real_ceiling_still_detected_when_the_climb_is_executed():
    tr = WaypointTracker([dict(w) for w in WPS])
    for _ in range(CEILING_DETECT_CYCLES + 2):
        g = tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -7.0}, 0.0)
        tr.note_executed_command({"vx": 0.0, "vz": g["vz"]})
    assert tr.ceiling_z is not None


# --------------------------------------------------------------------------- despegue vertical
def test_takeoff_climbs_in_place_until_cruise_altitude():
    tr = WaypointTracker([dict(w) for w in WPS])
    g = tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -5.8}, 0.0)
    assert g["takeoff"] is True and g["vx"] == 0.0 and g["vz"] < 0.0
    g = tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -9.2}, 0.0)
    assert g["takeoff"] is False
    # la fase es una sola vez por mision: bajar despues no vuelve a frenar el avance
    g = tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -7.0}, 0.0)
    assert g["takeoff"] is False


def test_takeoff_ends_if_a_ceiling_blocks_the_climb():
    tr = WaypointTracker([dict(w) for w in WPS])
    g = None
    for _ in range(CEILING_DETECT_CYCLES + 2):
        g = tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -6.0}, 0.0)
        tr.note_executed_command({"vx": 0.0, "vz": g["vz"]})
    g = tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -6.0}, 0.0)
    assert tr.ceiling_z is not None and g["takeoff"] is False


def test_takeoff_is_not_a_stall():
    det = StallDetector()
    st = {"telemetry": {"position": {"x": 0.0, "y": 0.0, "z": -6.0}, "velocity": {}},
          "prev_telemetry": {"position": {"x": 0.0, "y": 0.0, "z": -5.9}},
          "velocity_command": {"vx": 1.0, "vz": -0.8},
          "waypoint_guidance": {"takeoff": True, "dist_xy": 52.0,
                                "target_wp": WPS[0]}}
    for _ in range(80):
        det.update(st)
    assert not det.stopped_prolonged and not det.wp_no_progress


# --------------------------------------------------------------------------- velocidad medida
def _contact_state():
    return {
        "telemetry": {"position": {"x": -2.6, "y": -3.9, "z": -7.0}, "timestamp": 10.2,
                      "velocity": {"vx": -0.13, "vy": -0.29, "vz": 0.75},   # lo que reportaba AirSim
                      "imu_linear_acceleration": {"ax": 0.0, "ay": 0.0}},
        "prev_telemetry": {"position": {"x": -2.6, "y": -3.9, "z": -7.0}, "timestamp": 10.0},
        "velocity_command": {"macro_action": "PERDER_ALTURA", "vx": 1.0, "vz": 0.8},
        "waypoint_guidance": {"dist_xy": 47.4, "ceiling_z": -7.44, "target_wp": WPS[0]},
    }


def test_frozen_position_counts_as_stopped_despite_reported_velocity():
    st = _contact_state()
    assert measured_xy_speed(st) == 0.0
    det = StallDetector()
    for _ in range(10):
        det.update(st)
    assert det.stopped_prolonged


def test_measured_speed_uses_displacement():
    st = _contact_state()
    st["telemetry"]["position"]["x"] = -2.0   # 0.6 m en 0.2 s
    assert abs(measured_xy_speed(st) - 3.0) < 1e-6


# --------------------------------------------------------------------------- orden de reglas (grafo compilado)
class _OnParapetClient:
    """Dron apoyado en el parapeto: la posicion no cambia y AirSim reporta velocidad no nula."""

    def __init__(self):
        self.commands = []

    def capture(self):
        return np.zeros((72, 108, 3), dtype=np.uint8), {
            "position": {"x": -2.6, "y": -3.9, "z": -7.0},
            "velocity": {"vx": -0.13, "vy": -0.29, "vz": 0.75},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": -1.8},
            "collision": {"has_collided": False, "object_name": ""},
            "imu_linear_acceleration": {"ax": 0.0, "ay": 0.0},
            "timestamp": time.time(), "source": "airsim",
        }

    def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
        self.commands.append((vx, vy, vz, yaw_rate, target_yaw))
        return True


def test_ceiling_descent_against_a_structure_reaches_deadlock(monkeypatch):
    import src.agents.graph as graph_mod

    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "blind")
    monkeypatch.setattr(vlm_client, "_query_slm_impl", lambda p: (None, "", 1.0, "stub"))
    from src.agents.graph import compile_workflow

    wp = dict(WPS[0])
    state = {
        "waypoints": [wp], "current_wp_index": 0, "target_waypoint": wp,
        "waypoint_guidance": {"target_wp": wp, "distance": 47.4, "dist_xy": 47.4, "bearing_err_deg": 3.0,
                              "vx": 1.0, "vy": 0.0, "vz": 0.8, "yaw_rate": 0.0, "ceiling_z": -7.44,
                              "z_path_blocked": True, "dz": 2.6, "takeoff": False},
        "deliberations": [], "evasion_stuck_cycles": 0, "active_maneuver": None, "maneuver_cycles_left": 0,
        "slm_request_id": None, "next_action": "",
    }
    graph, service = compile_workflow(_OnParapetClient())
    try:
        actions = []
        for _ in range(40):
            state = graph.invoke(state)
            actions.append(state["next_action"])
            if state.get("_deadlock_event"):
                break
            state.pop("_escape_reset", None)
        assert state.get("_deadlock_event"), actions
        assert actions[0] == "PERDER_ALTURA"
        assert len(actions) <= 25
    finally:
        service.stop()
