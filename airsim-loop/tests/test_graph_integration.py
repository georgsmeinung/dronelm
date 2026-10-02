"""Integracion end-to-end del grafo COMPILADO (sin AirSim real), 2026-0930.

Las claves de control cruzan la frontera graph.invoke() solo si estan declaradas en DroneState:
estos tests corren el grafo compilado, no los nodos sueltos, porque ese bug solo existe ahi.
"""
from __future__ import annotations

import time

import numpy as np

import src.agents.deep_scan as deep_scan_mod
import src.agents.vlm_client as vlm_client


class _StuckClient:
    """Dron a 10 m que recibe orden de avanzar pero no se mueve (trabado)."""

    def __init__(self):
        self.commands = []
        self.yaw = 0.0

    def capture(self):
        frame = np.zeros((72, 108, 3), dtype=np.uint8)  # sin textura: el flujo no da evidencia
        return frame, {
            "position": {"x": 0.0, "y": 0.0, "z": -10.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": self.yaw},
            "collision": {"has_collided": False, "object_name": ""},
            "timestamp": time.time(), "source": "airsim",
        }

    def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
        self.commands.append((vx, vy, vz, yaw_rate, target_yaw))
        if target_yaw is not None:  # el giro del barrido se completa al instante
            import math
            self.yaw = math.radians(target_yaw)
        return True


def _state():
    wp = {"x": 100.0, "y": 0.0, "z": -10.0, "label": "WP_1"}
    return {
        "waypoints": [wp], "current_wp_index": 0, "target_waypoint": wp,
        "waypoint_guidance": {"target_wp": wp, "distance": 100.0, "dist_xy": 100.0, "bearing_err_deg": 0.0,
                              "vx": 2.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0, "ceiling_z": None},
        "deliberations": [], "evasion_stuck_cycles": 0, "active_maneuver": None, "maneuver_cycles_left": 0,
        "slm_request_id": None, "next_action": "",
    }


def _panorama_query(seen):
    def _q(payload):
        seen.append(payload.get("mode"))
        if payload.get("mode") == "deep_scan":
            n = len(payload.get("images_b64") or [])
            rumbos = [{"img": i + 1, "tipo": "fachada", "transitable": False, "relativo_deg": 0.0, "confianza": 0.8}
                      for i in range(n)]
            rumbos[1]["tipo"], rumbos[1]["transitable"] = "libre", True  # imagen 2 (+90 deg) libre
            return ({"rumbos": rumbos, "imagen_degradada_global": False, "rationale": ""}, "raw", 5.0, None)
        return None, "", 5.0, "sin estrategico en este test"
    return _q


def _run(graph, state, n, stop=None):
    for _ in range(n):
        state = graph.invoke(state)
        if stop and stop(state):
            break
        state.pop("_escape_reset", None)
        time.sleep(0.01)
    return state


def test_graph_compiles_and_runs_one_cycle(monkeypatch):
    monkeypatch.setattr("src.agents.graph.AGENT_ARM", "slm")
    monkeypatch.setattr(vlm_client, "_query_slm_impl", lambda p: (None, "", 1.0, "stub"))
    from src.agents.graph import compile_workflow

    client = _StuckClient()
    graph, service = compile_workflow(client)
    try:
        state = graph.invoke(_state())
        assert state["next_action"] and len(client.commands) == 1
    finally:
        service.stop()


def test_stuck_drone_scans_and_vlm_subgoal_crosses_graph_boundary(monkeypatch):
    monkeypatch.setattr("src.agents.graph.AGENT_ARM", "slm")
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    seen = []
    monkeypatch.setattr(vlm_client, "_query_slm_impl", _panorama_query(seen))
    from src.agents.graph import compile_workflow

    graph, service = compile_workflow(_StuckClient())
    try:
        state = _run(graph, _state(), 120, stop=lambda s: s.get("inject_corner") is not None)
        corner = state.get("inject_corner")
        assert "deep_scan" in seen
        assert corner and corner["label"] == "VLM_SCAN_GOAL"
        assert state.get("_escape_reset") is True                      # reinicia el tracker en el lazo
        assert state.get("_deadlock_event", {}).get("resolved_by_scan") is True
        assert any(d.get("arm") == "slm_deep_scan" for d in state["deliberations"])
        assert "RETROCEDER" not in {d.get("macro_action") for d in state["deliberations"]}
    finally:
        service.stop()


def test_blind_strategy_climbs_without_calling_the_vlm(monkeypatch):
    import src.agents.graph as graph_mod

    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "blind")
    seen = []
    monkeypatch.setattr(vlm_client, "_query_slm_impl", _panorama_query(seen))
    from src.agents.graph import compile_workflow

    graph, service = compile_workflow(_StuckClient())
    try:
        state = _run(graph, _state(), 30, stop=lambda s: s.get("next_action") == "GANAR_ALTURA")
        assert state["next_action"] == "GANAR_ALTURA"
        assert state["_deadlock_event"]["fell_back_to_blind"] is True
        assert "deep_scan" not in seen
    finally:
        service.stop()


def test_at_most_one_vlm_request_per_cycle(monkeypatch):
    monkeypatch.setattr("src.agents.graph.AGENT_ARM", "slm")
    monkeypatch.setattr(vlm_client, "_query_slm_impl", lambda p: (None, "", 1.0, "stub"))
    from src.agents.graph import compile_workflow

    graph, service = compile_workflow(_StuckClient())
    calls = []
    original = service.request
    service.request = lambda payload: calls.append(payload) or original(payload)
    try:
        state = _state()
        for _ in range(40):
            before = len(calls)
            state = graph.invoke(state)
            assert len(calls) - before <= 1
            state.pop("_escape_reset", None)
    finally:
        service.stop()


def test_scan_answer_marked_degraded_falls_back_to_the_vertical_escape(monkeypatch):
    """degradada=true: el propio modelo dice que las imagenes no sirven -> falla, no descripcion."""
    import src.agents.graph as graph_mod

    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    seen = []
    base = _panorama_query(seen)

    def _degraded(payload):
        out = base(payload)
        if payload.get("mode") == "deep_scan":
            out[0]["imagen_degradada_global"] = True
        return out

    monkeypatch.setattr(vlm_client, "_query_slm_impl", _degraded)
    from src.agents.graph import compile_workflow

    graph, service = compile_workflow(_StuckClient())
    try:
        state = _run(graph, _state(), 120, stop=lambda s: (s.get("_deadlock_event") or {}).get("fell_back_to_blind"))
        assert "deep_scan" in seen
        assert state["_deadlock_event"]["fell_back_to_blind"] is True
        assert state.get("inject_corner") is None
    finally:
        service.stop()
