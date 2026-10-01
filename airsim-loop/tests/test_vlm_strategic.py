"""Capa estrategica del VLM anclada a la pose de captura (2026-0930)."""
from __future__ import annotations

import math
import time
from types import SimpleNamespace

import numpy as np

import src.agents.vlm_strategic as vs


def _state(x=0.0, y=0.0, yaw_deg=0.0, wp=(100.0, 0.0), alt=10.0, temp=False):
    wps = [{"x": wp[0], "y": wp[1], "z": -10.0, "label": "WP_1"}]
    if temp:
        wps.insert(0, {"x": 5.0, "y": 5.0, "z": -10.0, "label": "VLM_SUBGOAL", "is_temporary": True})
    return {
        "telemetry": {"position": {"x": x, "y": y, "z": -alt},
                      "orientation": {"yaw": math.radians(yaw_deg)}, "timestamp": time.time()},
        "rgb_image": np.full((72, 108, 3), 100, dtype=np.uint8),
        "waypoints": wps, "current_wp_index": 0,
    }


def _cols(**kw):
    c = {k: "libre" for k in vs.COLUMN_LABELS}
    c.update(kw)
    return c


def _parsed(cols, meta_bloqueada=False, estructura=False):
    return {"columnas": cols, "meta_bloqueada": meta_bloqueada, "estructura_debajo": estructura}


def test_column_geometry_is_symmetric():
    centers = vs.column_centers_deg(90.0, 5)
    assert centers == {"A": -36.0, "B": -18.0, "C": 0.0, "D": 18.0, "E": 36.0}
    assert vs.column_for_angle(0.0) == "C" and vs.column_for_angle(-44.0) == "A" and vs.column_for_angle(44.0) == "E"


def test_annotation_never_touches_the_flow_frame():
    frame = np.full((72, 108, 3), 100, dtype=np.uint8)
    before = frame.copy()
    b64 = vs.annotate_columns(frame, 10.0)
    assert b64 and np.array_equal(frame, before)


def test_request_anchors_capture_pose_and_goal_column():
    payload, anchor = vs.build_request(_state(yaw_deg=0.0, wp=(100.0, 20.0)))
    assert payload["mode"] == "strategic" and len(payload["images_b64"]) == 1
    assert anchor["goal_col"] == "D" and abs(anchor["goal_rel_deg"] - 11.3) < 0.5  # C cubre -9..9 deg
    assert anchor["x"] == 0.0 and anchor["yaw_deg"] == 0.0


def test_no_request_when_goal_is_out_of_view():
    assert vs.build_request(_state(yaw_deg=90.0, wp=(100.0, 0.0))) is None


def test_direct_path_free_adds_nothing():
    _p, anchor = vs.build_request(_state())
    sub, why = vs.decide_subgoal(_parsed(_cols()), anchor, _state())
    assert sub is None and why == "directo_libre"


def test_blocked_goal_column_goes_to_nearest_free_column_in_world_frame():
    _p, anchor = vs.build_request(_state(yaw_deg=0.0))
    parsed = _parsed(_cols(B="bloqueada", C="bloqueada", D="bloqueada", E="libre", A="libre"), meta_bloqueada=True)
    # Mientras el VLM pensaba el dron giro 70 deg: la sub-meta NO debe cambiar (anclada al frame).
    later = _state(yaw_deg=70.0, x=1.0)
    sub, why = vs.decide_subgoal(parsed, anchor, later)
    assert sub is not None and sub["label"] == "VLM_SUBGOAL"
    bearing = math.degrees(math.atan2(sub["y"], sub["x"]))
    assert abs(abs(bearing) - 36.0) < 0.5            # A (-36) o E (+36), mismo empate por |angulo|
    assert abs(math.hypot(sub["x"], sub["y"]) - vs.VLM_SUBGOAL_DIST_M) < 0.1


def test_stale_or_wrong_wp_answers_are_discarded():
    _p, anchor = vs.build_request(_state())
    parsed = _parsed(_cols(C="bloqueada"), meta_bloqueada=True)
    sub, why = vs.decide_subgoal(parsed, anchor, _state(), now=time.time() + vs.VLM_STRATEGIC_MAX_AGE_S + 1)
    assert sub is None and why.startswith("vencida")
    other = _state()
    other["waypoints"][0]["label"] = "WP_2"
    assert vs.decide_subgoal(parsed, anchor, other)[1] == "wp_cambio"


def test_subgoal_already_passed_is_discarded():
    _p, anchor = vs.build_request(_state())
    parsed = _parsed(_cols(C="bloqueada", B="libre"), meta_bloqueada=True)
    # El dron avanzo casi toda la distancia en el rumbo de la columna B mientras el modelo pensaba.
    rad = math.radians(-18.0)
    d = vs.VLM_SUBGOAL_DIST_M - 1.0
    later = _state(x=d * math.cos(rad), y=d * math.sin(rad))
    assert vs.decide_subgoal(parsed, anchor, later) == (None, "superada")


def test_structure_below_climbs():
    _p, anchor = vs.build_request(_state())
    sub, why = vs.decide_subgoal(_parsed(_cols(), estructura=True), anchor, _state())
    assert sub is not None and sub["z"] == -10.0 - vs.VLM_CLIMB_M and "subir" in why


def test_parse_rejects_malformed():
    assert vs.parse_strategic({"columnas": {"A": "libre"}}) is None
    assert vs.parse_strategic({"columnas": _cols(C="quizas")}) is None
    assert vs.parse_strategic({"columnas": _cols(), "meta_bloqueada": True})["meta_bloqueada"] is True


class _FakeService:
    def __init__(self, parsed):
        self.parsed = parsed
        self.requests = []

    def request(self, payload):
        self.requests.append(payload)
        return len(self.requests)

    def get_result(self, rid):
        return SimpleNamespace(request_id=rid, parsed_decision=self.parsed, raw_response="{}",
                               latency_ms=3500.0, completed_at=time.time())

    def poll(self):
        return None, 0.0, False


def test_layer_sends_then_injects_and_respects_period(monkeypatch):
    monkeypatch.setattr(vs, "VLM_STRATEGIC_PERIOD_S", 100.0)
    svc = _FakeService(_parsed(_cols(C="bloqueada", B="bloqueada", D="libre"), meta_bloqueada=True))
    layer = vs.StrategicLayer(svc)
    st = _state()
    assert layer.tick(st) is None and len(svc.requests) == 1        # envia
    audit = layer.tick(st)                                           # recibe
    assert audit is not None and st["inject_corner"]["label"] == "VLM_SUBGOAL"
    assert layer.tick(_state()) is None and len(svc.requests) == 1   # respeta el periodo


def test_layer_skips_during_scan_takeoff_and_temporary_targets():
    svc = _FakeService(None)
    layer = vs.StrategicLayer(svc)
    scan = _state()
    scan["_scan_phase"] = "rotando"
    layer.tick(scan)
    layer.tick(_state(alt=3.0))
    layer.tick(_state(temp=True))
    assert svc.requests == []
