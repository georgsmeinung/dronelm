# Fase H2 (PLAN-MEJORAS-3): escaneo espacial profundo en atasco duro.
from __future__ import annotations

import math
import time

import numpy as np
import pytest

import src.agents.deep_scan as deep_scan_mod
import src.agents.deliberative as deliberative_mod
from src.perception.obstacle_field import empty_field


def _base_state():
    return {
        "waypoints": [], "current_wp_index": 0, "target_waypoint": None,
        "waypoint_guidance": {}, "mission_completed": False, "rgb_image": None,
        "telemetry": {}, "frame_history": [],
        "estimated_ttc": float("inf"), "next_action": "", "flight_status": "vuelo",
        "deliberations": [], "active_maneuver": None, "maneuver_cycles_left": 0,
        "maneuver_command": None, "evasion_stuck_cycles": 0, "slm_request_id": None,
    }


def _run_cycles(node, state, n, on_action=None):
    telemetry_yaw = 0.0
    actions = []
    for i in range(n):
        state["evasion_stuck_cycles"] = 999
        state["telemetry"] = {
            "position": {"x": 0.0, "y": 0.0, "z": -10.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": math.radians(telemetry_yaw)},
        }
        state["rgb_image"] = np.zeros((10, 10, 3), dtype=np.uint8)
        state = node(state)
        actions.append(state["next_action"])
        cmd = state.get("velocity_command") or {}
        target_yaw = cmd.get("target_yaw")
        if target_yaw is not None:
            telemetry_yaw = target_yaw
        if on_action and on_action(state, actions):
            break
        time.sleep(0.02)  # deja avanzar el reloj real para los watchdogs
    return state, actions


def test_deep_scan_never_touches_depth_capture(monkeypatch):
    """H2.4.1 (misma invariante que H1.3.1): deep_scan.py reutiliza el frame
    ya presente en el DroneState, nunca invoca capture() ni pide profundidad."""
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 2)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)

    def _query(payload):
        assert "depth" not in payload
        if payload.get("mode") == "deep_scan":
            return {"macro_action": "EVADIR_IZQUIERDA", "rationale": "ok"}, "raw", 5.0, None
        return None, "", 5.0, "no deberia llamarse en modo tactico"

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _query)

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        state = _base_state()
        state["obstacle_field"] = empty_field()
        state, actions = _run_cycles(
            node, state, 40, on_action=lambda s, acts: acts[-1] not in ("ESCANEO",)
        )
        assert actions[-1] == "EVADIR_IZQUIERDA"
    finally:
        service.stop()


def test_deep_scan_resolution_does_not_also_force_blind_escape_same_cycle(monkeypatch):
    """H2.4.2: si el escaneo profundo resuelve, el bloque de escape sincronico
    NO debe ejecutarse ese mismo ciclo (nunca aparece GANAR_ALTURA/
    PERDER_ALTURA duplicando la accion ya resuelta por el escaneo)."""
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 2)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)

    def _query(payload):
        if payload.get("mode") == "deep_scan":
            return {"macro_action": "EVADIR_DERECHA", "rationale": "corredor visto en el panorama"}, "raw", 5.0, None
        return None, "", 5.0, "no deberia llamarse en modo tactico"

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _query)

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        state = _base_state()
        state["obstacle_field"] = empty_field()
        state, actions = _run_cycles(
            node, state, 40, on_action=lambda s, acts: acts[-1] not in ("ESCANEO",)
        )
        assert "GANAR_ALTURA" not in actions
        assert "PERDER_ALTURA" not in actions
        assert actions[-1] == "EVADIR_DERECHA"

        deliberations = state.get("deliberations") or []
        assert deliberations, "el escaneo resuelto debe dejar una entrada en deliberations[]"
        assert deliberations[-1]["arm"] == "slm_deep_scan"
        assert deliberations[-1]["macro_action"] == "EVADIR_DERECHA"
    finally:
        service.stop()


def test_deep_scan_timeout_falls_back_to_existing_blind_escape(monkeypatch):
    """H2.4.3: regresion de comportamiento -- si el escaneo profundo expira o
    falla, el escape sincronico existente se ejecuta exactamente como antes
    (misma alternancia GANAR_ALTURA/PERDER_ALTURA de 2026-0827)."""
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 1)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    monkeypatch.setattr(deep_scan_mod, "SLM_DEEP_WATCHDOG_MS", 50.0)
    monkeypatch.setenv("MAX_CONSECUTIVE_ESCAPES", "3")

    def _never_resolves(payload):
        time.sleep(0.3)  # mas lento que el watchdog profundo (50ms)
        return None, "", 300.0, "timeout simulado"

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _never_resolves)

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        state = _base_state()
        state["obstacle_field"] = empty_field()
        state, actions = _run_cycles(
            node, state, 80, on_action=lambda s, acts: acts[-1] in ("GANAR_ALTURA", "PERDER_ALTURA")
        )
        assert actions[-1] in ("GANAR_ALTURA", "PERDER_ALTURA")
    finally:
        service.stop()


def test_deep_scan_bounds_total_images_in_payload(monkeypatch):
    """H2.4.4: el total de imagenes en el pedido profundo nunca excede el
    maximo configurado (MAX_DEEP_SCAN_IMAGES)."""
    monkeypatch.setattr(deep_scan_mod, "MAX_DEEP_SCAN_IMAGES", 3)

    captured = {}

    class _FakeService:
        def request(self, payload):
            captured.update(payload)
            return 1

        def poll(self):
            return None, 0.0, True

    state = {
        "_scan_phase": "capturado",
        "_scan_frames": [(float(i * 30), np.zeros((10, 10, 3), dtype=np.uint8), 1735689000.0 + i) for i in range(6)],
        "_deep_scan_request_id": None,
    }
    telemetry = {"position": {"x": 0.0, "y": 0.0, "z": -10.0}, "orientation": {"yaw": 0.0}}
    handled = deep_scan_mod.deep_scan_cycle(
        state, _FakeService(), empty_field(), telemetry, {}, arm="slm", deadlock_cycles=1, consecutive_escapes=0
    )
    assert handled is True
    assert len(captured.get("images_b64") or []) <= 3
    assert len(captured.get("image_labels") or []) <= 3


def test_fsm_arm_shares_the_deep_scan_capability(monkeypatch):
    """H3.1: el escaneo profundo es una capacidad compartida entre slm y fsm,
    seleccionable con DEADLOCK_STRATEGY sin importar AGENT_ARM."""
    import src.agents.fsm as fsm_mod

    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 1)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)

    def _query(payload):
        if payload.get("mode") == "deep_scan":
            return {"macro_action": "PERDER_ALTURA", "rationale": "vegetacion con salida abajo"}, "raw", 5.0, None
        return None, "", 5.0, "no deberia llamarse en modo tactico"

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _query)

    from src.agents.deliberative import make_deliberation_service

    service = make_deliberation_service()
    try:
        state = _base_state()
        state["obstacle_field"] = empty_field()
        node = lambda s: fsm_mod.fsm_node(s, service=service)
        state, actions = _run_cycles(
            node, state, 40, on_action=lambda s, acts: acts[-1] not in ("ESCANEO",)
        )
        assert actions[-1] == "PERDER_ALTURA"
        deliberations = state.get("deliberations") or []
        assert deliberations and deliberations[-1]["arm"] == "fsm_deep_scan"
    finally:
        service.stop()


def test_deep_scan_state_survives_compiled_graph_invoke(monkeypatch):
    """H2.4.5: _scan_phase/_scan_heading_index/_scan_frames deben sobrevivir
    varias invocaciones sucesivas a graph.invoke() sobre el GRAFO COMPILADO
    (no al nodo llamado directamente) -- el bug de claves no declaradas del
    2026-0824 solo era visible en esa frontera (ver test_graph_integration.py)."""
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 3)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 2)
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", lambda payload: (None, "", 5.0, "sin servidor SLM"))
    monkeypatch.setattr("src.agents.graph.AGENT_ARM", "slm")

    from src.agents.graph import compile_workflow

    class _StubAirSimClient:
        def __init__(self):
            self.commands = []

        def capture(self):
            frame = np.zeros((120, 160, 3), dtype=np.uint8)
            telemetry = {
                "position": {"x": 0.0, "y": 0.0, "z": -10.0},
                "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
                "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
                "collision": {"has_collided": False, "object_name": ""},
                "timestamp": time.time(),
                "source": "airsim",
            }
            return frame, telemetry

        def get_telemetry(self):
            return self.capture()[1]

        def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
            self.commands.append((vx, vy, vz, yaw_rate, target_yaw))
            return True

    client = _StubAirSimClient()
    graph, service = compile_workflow(client)
    try:
        state = _base_state()
        state["evasion_stuck_cycles"] = 999

        state = graph.invoke(state)
        assert state.get("_scan_phase") in ("rotando", "asentando", "capturado")

        for _ in range(6):
            state["evasion_stuck_cycles"] = 999
            state = graph.invoke(state)

        # El barrido debio avanzar mas alla del primer rumbo (heading_index
        # 0 == rumbo de partida, siempre satisfecho de inmediato con un
        # telemetry sin rotacion real) a traves de MULTIPLES graph.invoke().
        assert state.get("_scan_heading_index", 0) >= 1 or state.get("_scan_phase") == "capturado"
    finally:
        service.stop()
