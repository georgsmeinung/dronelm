# Barrido panoramico + VLM ante un deadlock (deep_vlm). 2026-0930: se maneja deep_scan_cycle
# directamente (el nodo deliberativo legacy que lo envolvia se movio a legacy/) y el VLM responde en el
# formato actual (una entrada por imagen). Los tests de scene_to_action se fueron con slam_assess.
from __future__ import annotations

import math
import time

import numpy as np

import src.agents.deep_scan as deep_scan_mod
import src.agents.vlm_client as vlm_client
from src.perception.obstacle_field import empty_field


def _pano(*tipos_ok):
    return ({"rumbos": [{"img": i + 1, "tipo": t, "transitable": ok, "relativo_deg": 0.0, "confianza": 0.8}
                        for i, (t, ok) in enumerate(tipos_ok)],
             "imagen_degradada_global": False, "rationale": ""}, "raw", 5.0, None)


def _drive(state, service, n, arm="slm"):
    """Corre deep_scan_cycle como lo hace navigate_node, girando el dron a lo que ordena el barrido."""
    yaw, handled = 0.0, True
    for _ in range(n):
        state["rgb_image"] = np.zeros((10, 10, 3), dtype=np.uint8)
        telem = {"position": {"x": 0.0, "y": 0.0, "z": -10.0},
                 "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": math.radians(yaw)}}
        handled = deep_scan_mod.deep_scan_cycle(state, service, empty_field(), telem, {}, arm, 1)
        if not handled or state.get("next_action") != "ESCANEO":
            break
        tgt = (state.get("velocity_command") or {}).get("target_yaw")
        if tgt is not None:
            yaw = tgt
        time.sleep(0.02)
    return state, handled


def test_deep_scan_never_touches_depth_capture(monkeypatch):
    """Reutiliza el frame del DroneState: el pedido nunca lleva profundidad."""
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 2)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    payloads = []

    def _q(payload):
        payloads.append(payload)
        return _pano(("fachada", False), ("libre", True))

    monkeypatch.setattr(vlm_client, "_query_slm_impl", _q)
    service = vlm_client.make_deliberation_service()
    try:
        state, _ = _drive({"deliberations": []}, service, 60)
        assert payloads and all("depth" not in p for p in payloads)
        assert state["next_action"] == "MANTENER_RUMBO" and state.get("inject_corner")
    finally:
        service.stop()


def test_resolution_leaves_one_audit_entry_and_no_blind_escape(monkeypatch):
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 2)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    monkeypatch.setattr(vlm_client, "_query_slm_impl", lambda p: _pano(("fachada", False), ("libre", True)))
    service = vlm_client.make_deliberation_service()
    try:
        state, handled = _drive({"deliberations": []}, service, 60)
        assert handled is True
        assert [d["arm"] for d in state["deliberations"]] == ["slm_deep_scan"]
        assert state["_deadlock_event"]["resolved_by_scan"] is True
    finally:
        service.stop()


def test_timeout_returns_false_so_the_caller_escapes(monkeypatch):
    """Si el VLM no responde a tiempo, deep_scan_cycle devuelve False (el grafo escapa por altura)."""
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 1)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    monkeypatch.setattr(deep_scan_mod, "SLM_DEEP_WATCHDOG_MS", 50.0)

    def _slow(payload):
        time.sleep(0.3)
        return None, "", 300.0, "timeout simulado"

    monkeypatch.setattr(vlm_client, "_query_slm_impl", _slow)
    service = vlm_client.make_deliberation_service()
    try:
        state, handled = _drive({"deliberations": []}, service, 80)
        assert handled is False and state["_deadlock_event"]["fell_back_to_blind"] is True
    finally:
        service.stop()


def test_unparseable_answer_returns_false(monkeypatch):
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 1)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    monkeypatch.setattr(vlm_client, "_query_slm_impl", lambda p: ({"macro_action": "EVADIR_DERECHA"}, "raw", 5.0, None))
    service = vlm_client.make_deliberation_service()
    try:
        _state, handled = _drive({"deliberations": []}, service, 60)
        assert handled is False                                          # el formato viejo ya no se acepta
    finally:
        service.stop()


def test_deep_scan_bounds_total_images_in_payload(monkeypatch):
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
    assert deep_scan_mod.deep_scan_cycle(state, _FakeService(), empty_field(), telemetry, {}, "slm", 1) is True
    assert len(captured.get("images_b64") or []) <= 3
    assert len(captured.get("image_labels") or []) <= 3


def test_fsm_arm_shares_the_deep_scan_capability(monkeypatch):
    """El barrido es compartido entre slm y fsm (DEADLOCK_STRATEGY=deep_vlm, sin importar AGENT_ARM)."""
    import src.agents.fsm as fsm_mod

    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 1)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    monkeypatch.setattr(vlm_client, "_query_slm_impl", lambda p: _pano(("vegetacion", False)))
    service = vlm_client.make_deliberation_service()
    try:
        state = {"deliberations": [], "obstacle_field": empty_field(), "active_maneuver": None,
                 "maneuver_cycles_left": 0, "slm_request_id": None, "waypoint_guidance": {}}
        yaw = 0.0
        for _ in range(40):
            state["evasion_stuck_cycles"] = 999
            state["telemetry"] = {"position": {"x": 0.0, "y": 0.0, "z": -10.0},
                                  "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": math.radians(yaw)}}
            state["rgb_image"] = np.zeros((10, 10, 3), dtype=np.uint8)
            state = fsm_mod.fsm_node(state, service=service)
            tgt = (state.get("velocity_command") or {}).get("target_yaw")
            if tgt is not None:
                yaw = tgt
            if state["next_action"] != "ESCANEO":
                break
            time.sleep(0.02)
        assert state["next_action"] == "PERDER_ALTURA"                    # todo vegetacion
        assert state["deliberations"][-1]["arm"] == "fsm_deep_scan"
    finally:
        service.stop()


def test_deep_scan_state_survives_compiled_graph_invoke(monkeypatch):
    """_scan_phase/_scan_heading_index/_scan_frames sobreviven a graph.invoke() sucesivos."""
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 3)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 2)
    monkeypatch.setattr(vlm_client, "_query_slm_impl", lambda payload: (None, "", 5.0, "sin servidor"))
    monkeypatch.setattr("src.agents.graph.AGENT_ARM", "slm")
    from src.agents.graph import compile_workflow

    class _Client:
        def capture(self):
            return np.zeros((120, 160, 3), dtype=np.uint8), {
                "position": {"x": 0.0, "y": 0.0, "z": -10.0}, "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
                "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0},
                "collision": {"has_collided": False, "object_name": ""}, "timestamp": time.time(), "source": "airsim",
            }

        def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
            return True

    graph, service = compile_workflow(_Client())
    try:
        state = {"deliberations": [], "_scan_phase": "rotando", "_scan_heading_index": 0,
                 "_scan_frames": [], "_scan_start_yaw_deg": 0.0, "_scan_settle_left": 0, "_scan_rot_stall": 0}
        state = graph.invoke(state)
        assert state.get("_scan_phase") in ("rotando", "asentando", "capturado")
        for _ in range(6):
            state = graph.invoke(state)
        assert state.get("_scan_heading_index", 0) >= 1 or state.get("_scan_phase") == "capturado"
    finally:
        service.stop()


def test_panorama_english_views_are_translated():
    pano = deep_scan_mod.parse_panorama_description(
        {"views": [{"img": 1, "view": "facade", "free": False}, {"img": 2, "view": "open", "free": True}]})
    assert [r["tipo"] for r in pano["rumbos"]] == ["fachada", "libre"]
    assert [r["transitable"] for r in pano["rumbos"]] == [False, True]
    props = deep_scan_mod.RESPONSE_JSON_SCHEMA_PANORAMA["json_schema"]["schema"]["properties"]
    assert set(props) == {"views"} and "conf" not in props["views"]["items"]["properties"]
