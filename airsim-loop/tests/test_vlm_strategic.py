"""Capa estrategica del VLM anclada a la pose de captura, con grilla de 3x3 (2026-1001)."""
from __future__ import annotations

import math
import time
from types import SimpleNamespace

import numpy as np

import src.agents.vlm_strategic as vs

W, H = 108, 72          # frame de prueba 3:2: f = 54 px con HFOV 90; recorte cuadrado de 72 px
SIDE, F = 72, 54.0
AZ = math.degrees(math.atan(24 / 54))   # 23.96: centro de las columnas A y C del recorte
EL = AZ                                 # recorte cuadrado: filas 1 y 3 a la misma distancia angular


def _state(x=0.0, y=0.0, yaw_deg=0.0, wp=(100.0, 0.0), alt=10.0, temp=False):
    wps = [{"x": wp[0], "y": wp[1], "z": -10.0, "label": "WP_1"}]
    if temp:
        wps.insert(0, {"x": 5.0, "y": 5.0, "z": -10.0, "label": "VLM_SUBGOAL", "is_temporary": True})
    return {
        "telemetry": {"position": {"x": x, "y": y, "z": -alt},
                      "orientation": {"yaw": math.radians(yaw_deg)}, "timestamp": time.time()},
        "rgb_image": np.full((H, W, 3), 100, dtype=np.uint8),
        "waypoints": wps, "current_wp_index": 0,
    }


def _grid(blocked=(), free_only=None):
    if free_only is not None:
        return {"sectores": {c: ("libre" if c in free_only else "bloqueado") for c in vs.CELLS}}
    return {"sectores": {c: ("bloqueado" if c in blocked else "libre") for c in vs.CELLS}}


def test_square_crop_cuts_both_sides_of_the_width():
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    frame[:, :18] = 255                     # franja izquierda que el recorte debe descartar
    frame[:, -18:] = 255                    # franja derecha
    crop, side, f = vs.square_crop(frame)
    assert crop.shape[:2] == (SIDE, SIDE) and side == SIDE and abs(f - F) < 1e-9
    assert crop.max() == 0                  # quedo solo el centro
    assert abs(vs.crop_half_fov_deg(SIDE, F) - math.degrees(math.atan(36 / 54))) < 1e-9


def test_grid_geometry_follows_the_thirds_of_the_square_crop():
    centers = vs.cell_centers_deg(SIDE, F)
    assert centers["B2"] == (0.0, 0.0)
    assert abs(centers["A2"][0] + AZ) < 1e-6 and abs(centers["C2"][0] - AZ) < 1e-6
    assert abs(centers["B1"][1] - EL) < 1e-6 and abs(centers["B3"][1] + EL) < 1e-6
    # laterales y verticales a la misma distancia angular: ninguno gana por la forma del cuadro
    assert abs(abs(centers["A2"][0]) - abs(centers["B1"][1])) < 1e-9
    assert vs.cell_for_direction(0.0, 0.0, SIDE, F) == "B2"
    assert vs.cell_for_direction(-44.0, 0.0, SIDE, F) == "A2"
    assert vs.cell_for_direction(0.0, 30.0, SIDE, F) == "B1"
    assert vs.cell_for_direction(30.0, -30.0, SIDE, F) == "C3"


def test_annotation_never_touches_the_flow_frame():
    frame = np.full((H, W, 3), 100, dtype=np.uint8)
    before = frame.copy()
    crop, side, f = vs.square_crop(frame)
    b64 = vs.annotate_grid(crop, f, 10.0, 0.0)
    assert b64 and np.array_equal(frame, before)


def test_request_anchors_capture_pose_and_goal_cell():
    payload, anchor = vs.build_request(_state(yaw_deg=0.0, wp=(100.0, 20.0)))
    assert payload["mode"] == "strategic" and len(payload["images_b64"]) == 1
    assert anchor["goal_cell"] == "B2" and abs(anchor["goal_az_deg"] - 11.3) < 0.5
    assert abs(anchor["goal_el_deg"]) < 1e-6 and anchor["wp_dist_xy"] > 100.0
    assert anchor["x"] == 0.0 and anchor["yaw_deg"] == 0.0


def test_no_request_when_goal_is_out_of_view_or_close():
    assert vs.build_request(_state(yaw_deg=90.0, wp=(100.0, 0.0))) is None
    assert vs.build_request(_state(wp=(vs.VLM_NEAR_WP_M - 1.0, 0.0))) is None


def test_direct_path_free_adds_nothing():
    _p, anchor = vs.build_request(_state())
    sub, why = vs.decide_subgoal(_grid(), anchor, _state())
    assert sub is None and why == "directo_libre"


def test_blocked_goal_sector_goes_to_nearest_free_sector_in_world_frame():
    _p, anchor = vs.build_request(_state(yaw_deg=0.0))
    parsed = _grid(blocked=("A1", "B1", "C1", "B2", "A3", "B3", "C3"))
    # Mientras el VLM pensaba el dron giro 70 deg: la sub-meta NO debe cambiar (anclada al frame).
    later = _state(yaw_deg=70.0, x=1.0)
    sub, why = vs.decide_subgoal(parsed, anchor, later)
    assert sub is not None and sub["label"] == "VLM_SUBGOAL" and sub["sector"] in ("A2", "C2")
    bearing = math.degrees(math.atan2(sub["y"], sub["x"]))
    assert abs(abs(bearing) - AZ) < 0.5
    assert abs(math.hypot(sub["x"], sub["y"]) - vs.VLM_SUBGOAL_DIST_M) < 0.1
    assert sub["z"] == -10.0                      # fila del medio: misma altura


def test_lateral_and_vertical_detours_tie_and_the_middle_row_wins():
    _p, anchor = vs.build_request(_state())
    sub, _why = vs.decide_subgoal(_grid(free_only=("B1", "C2")), anchor, _state())
    assert sub["sector"] == "C2" and sub["z"] == -10.0


def test_only_the_upper_row_free_climbs():
    _p, anchor = vs.build_request(_state())
    sub, why = vs.decide_subgoal(_grid(free_only=("A1", "B1", "C1")), anchor, _state())
    assert sub["sector"] == "B1" and "B1" in why
    assert sub["z"] == -10.0 - vs.VLM_MAX_DZ_M    # 15 m * tan(24 deg) = 6.7 m, acotado a VLM_MAX_DZ_M


def test_subgoal_never_beyond_the_real_waypoint():
    st = _state(wp=(12.0, 0.0))
    _p, anchor = vs.build_request(st)
    sub, _why = vs.decide_subgoal(_grid(blocked=("B2",)), anchor, st)
    assert sub is not None and abs(math.hypot(sub["x"], sub["y"]) - 12.0) < 0.1


def test_lower_row_respects_the_minimum_altitude():
    st = _state(alt=9.0)
    _p, anchor = vs.build_request(st)
    sub, _why = vs.decide_subgoal(_grid(free_only=("B3",)), anchor, st)
    assert sub["sector"] == "B3" and sub["z"] == -vs.VLM_SUBGOAL_MIN_ALT_M


def test_no_free_sector_adds_nothing():
    _p, anchor = vs.build_request(_state())
    assert vs.decide_subgoal(_grid(free_only=()), anchor, _state()) == (None, "sin_sector_libre")


def test_stale_or_wrong_wp_answers_are_discarded():
    _p, anchor = vs.build_request(_state())
    parsed = _grid(blocked=("B2",))
    sub, why = vs.decide_subgoal(parsed, anchor, _state(), now=time.time() + vs.VLM_STRATEGIC_MAX_AGE_S + 1)
    assert sub is None and why.startswith("vencida")
    other = _state()
    other["waypoints"][0]["label"] = "WP_2"
    assert vs.decide_subgoal(parsed, anchor, other)[1] == "wp_cambio"


def test_subgoal_already_passed_is_discarded():
    _p, anchor = vs.build_request(_state())
    parsed = _grid(free_only=("A2",))
    # El dron avanzo casi toda la distancia en el rumbo del sector A2 mientras el modelo pensaba.
    rad = math.radians(-AZ)
    d = vs.VLM_SUBGOAL_DIST_M - 1.0
    later = _state(x=d * math.cos(rad), y=d * math.sin(rad))
    assert vs.decide_subgoal(parsed, anchor, later) == (None, "superada")


def test_parse_rejects_malformed():
    assert vs.parse_strategic({"sectores": {"A1": "libre"}}) is None
    bad = _grid()
    bad["sectores"]["B2"] = "quizas"
    assert vs.parse_strategic(bad) is None
    assert vs.parse_strategic({"columnas": {}}) is None
    assert vs.parse_strategic(_grid(blocked=("B2",)))["sectores"]["B2"] == "bloqueado"


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
    svc = _FakeService(_grid(blocked=("B2", "A2")))
    layer = vs.StrategicLayer(svc)
    st = _state()
    assert layer.tick(st) is None and len(svc.requests) == 1        # envia
    audit = layer.tick(st)                                           # recibe
    assert audit is not None and st["inject_corner"]["label"] == "VLM_SUBGOAL"
    assert layer.tick(_state()) is None and len(svc.requests) == 1   # respeta el periodo


def test_layer_skips_during_scan_and_takeoff():
    svc = _FakeService(None)
    layer = vs.StrategicLayer(svc)
    scan = _state()
    scan["_scan_phase"] = "rotando"
    layer.tick(scan)
    layer.tick(_state(alt=3.0))
    assert svc.requests == []


def test_layer_replans_with_a_subgoal_active_and_clears_it_when_direct_is_free():
    svc = _FakeService(_grid())          # todo libre: camino directo
    layer = vs.StrategicLayer(svc)
    st = _state(temp=True)
    layer.tick(st)
    assert len(svc.requests) == 1        # consulta aunque el objetivo activo sea una sub-meta
    layer.tick(st)
    assert st.get("_clear_subgoals") is True and "inject_corner" not in st
