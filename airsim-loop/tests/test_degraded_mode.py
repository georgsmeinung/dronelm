"""F0.6 regresion: si AirSim no responde (capture devuelve source != "airsim"

o imagen None), el lazo debe comandar hover y NO ejecutar percepcion ni
deliberacion, en lugar de "volar" sobre datos simulados como hacia la
version original (que devolvia un frame sintetico y seguia operando).
"""
from __future__ import annotations

import numpy as np

import src.agents.deliberative as deliberative_mod
from src.agents.graph import compile_workflow


class _UnavailableAirSimClient:
    """Simula AirSim caído: capture() devuelve None + telemetría 'simulated'."""

    def __init__(self):
        self.loop_hz = 5.0
        self.commands = []

    def capture(self):
        return None, {
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
            "timestamp": 0.0,
            "source": "simulated",
        }

    def get_telemetry(self):
        return self.capture()[1]

    def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
        self.commands.append((vx, vy, vz, yaw_rate, target_yaw))
        return True


def _base_state():
    return {
        "waypoints": [], "current_wp_index": 0, "target_waypoint": None,
        "waypoint_guidance": {}, "mission_completed": False, "rgb_image": None,
        "telemetry": {}, "frame_history": [], "xor_change_ratio": 1.0,
        "estimated_ttc": float("inf"), "next_action": "", "flight_status": "vuelo",
        "deliberations": [], "active_maneuver": None, "maneuver_cycles_left": 0,
        "maneuver_command": None, "evasion_stuck_cycles": 0, "slm_request_id": None,
    }


def test_unavailable_airsim_commands_hover_not_flight(monkeypatch):
    def _fail_query(payload):
        raise AssertionError("El SLM no debe consultarse en modo degradado")

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _fail_query)

    client = _UnavailableAirSimClient()
    graph, service = compile_workflow(client)
    try:
        state = graph.invoke(_base_state())
        assert state["degraded"] is True
        assert state["route"] == "degraded"
        cmd = state["velocity_command"]
        assert cmd["vx"] == 0.0 and cmd["vy"] == 0.0 and cmd["vz"] == 0.0 and cmd["yaw_rate"] == 0.0
        assert state.get("obstacle_field") is None  # percepcion nunca corrio
        assert state.get("deliberations") == []  # deliberacion nunca corrio
    finally:
        service.stop()
