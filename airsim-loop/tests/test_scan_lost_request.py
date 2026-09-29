"""Escaneo profundo: pedido pisado por otro consumidor del servicio (2026-0929)."""
from __future__ import annotations

import time

import src.agents.deep_scan as deep_scan_mod
from src.agents.deliberation_service import DeliberationResult, DeliberationService
from src.perception.obstacle_field import empty_field


def test_service_keeps_results_by_id_after_newer_ones():
    calls = []

    def _q(payload):
        calls.append(payload["n"])
        return {"macro_action": "MANTENER_RUMBO", "rationale": str(payload["n"])}, "raw", 1.0, None

    svc = DeliberationService(_q)
    try:
        a = svc.request({"n": 1})
        for _ in range(100):
            if svc.get_result(a):
                break
            time.sleep(0.02)
        b = svc.request({"n": 2})
        for _ in range(100):
            if svc.get_result(b):
                break
            time.sleep(0.02)
        assert svc.poll()[0].request_id == b          # el "ultimo" ya es otro...
        assert svc.get_result(a) is not None          # ...pero el primero no se perdio
        assert svc.get_result(999) is None
    finally:
        svc.stop()


class _FakeService:
    """Servicio donde el pedido del escaneo (id 6) desaparecio: nada pendiente, sin resultado."""

    def poll(self):
        return None, 0.0, False

    def get_result(self, rid):
        return None


def _state_waiting(age_s):
    return {
        "_scan_phase": "capturado", "_scan_heading_index": 2, "_scan_frames": [],
        "_deep_scan_request_id": 6, "_deep_scan_request_ts": time.time() - age_s,
        "deliberations": [], "_deliberation_pending": True,
    }


def _call(state, monkeypatch):
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_LOST_GRACE_MS", 1000.0)
    telem = {"orientation": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}, "position": {"x": 0, "y": 0, "z": -10}}
    return deep_scan_mod.deep_scan_cycle(
        state, _FakeService(), empty_field(), telem, {}, "slm", 20, 0, None,
    )


def test_lost_scan_request_falls_back_instead_of_waiting_forever(monkeypatch):
    state = _state_waiting(age_s=5.0)          # > gracia (1 s), < watchdog (12 s)
    resolved = _call(state, monkeypatch)
    assert resolved is False                   # cae al escape sincronico
    ev = state["_deadlock_event"]
    assert ev["fell_back_to_blind"] is True and ev["resolved_by_scan"] is False
    assert state["_scan_phase"] is None and state["_deep_scan_request_id"] is None
    assert state["deliberations"][-1]["timeout"] is True


def test_fresh_pending_request_keeps_waiting(monkeypatch):
    state = _state_waiting(age_s=0.1)          # recien enviado: dentro de la gracia
    resolved = _call(state, monkeypatch)
    assert resolved is True and state["next_action"] == "ESCANEO"
    assert state["_scan_phase"] == "capturado"


def test_scan_poll_uses_result_by_id_even_if_latest_is_another():
    other = DeliberationResult(request_id=10, completed_at=time.time(), parsed_decision=None,
                               raw_response="", latency_ms=1.0, error=None)
    mine = DeliberationResult(request_id=6, completed_at=time.time(), parsed_decision=None,
                              raw_response="", latency_ms=1.0, error=None)

    class _Svc:
        def poll(self):
            return other, 0.0, False

        def get_result(self, rid):
            return mine if rid == 6 else None

    res, age_ms, lost = deep_scan_mod._scan_poll({"_deep_scan_request_ts": time.time() - 20}, _Svc(), 6)
    assert res is mine and lost is False
