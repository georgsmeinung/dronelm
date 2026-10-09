"""Profundidad estimada como fuente de la capa estrategica y del barrido (2026-10-08)."""
from __future__ import annotations

import json
import math
import time

import numpy as np

import src.agents.vlm_strategic as vs
from src.agents import deep_scan
from src.agents.depth_client import SCAN_SECTOR, depth_to_decision, make_depth_query, make_depth_service
from src.perception.depth_estimator import CELLS, DEPTH_FREE_M, sector_p5

W, H = 108, 72


class FakeEstimator:
    """p5 por sector fijo, o por fotograma segun su valor medio (para el barrido)."""

    def __init__(self, p5=None, by_mean=None):
        self.p5, self.by_mean, self.calls = p5, by_mean, 0

    def sectors(self, frame):
        self.calls += 1
        if self.by_mean is not None:
            return {"p5": self.by_mean[int(frame.mean())], "latency_ms": 1.0}
        return {"p5": self.p5, "latency_ms": 1.0}


def _grid(blocked=()):
    return {c: (3.0 if c in blocked else 50.0) for c in CELLS}


def _state(yaw_deg=0.0, wp=(100.0, 0.0), alt=10.0):
    return {
        "telemetry": {"position": {"x": 0.0, "y": 0.0, "z": -alt},
                      "orientation": {"yaw": math.radians(yaw_deg)}, "timestamp": time.time()},
        "rgb_image": np.full((H, W, 3), 100, dtype=np.uint8),
        "waypoints": [{"x": wp[0], "y": wp[1], "z": -10.0, "label": "WP_1"}], "current_wp_index": 0,
    }


def _wait(svc, rid, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = svc.get_result(rid)
        if r is not None:
            return r
        time.sleep(0.01)
    raise AssertionError("el servicio de profundidad no respondio")


def test_sector_p5_uses_thirds_of_the_square_crop():
    depth = np.full((72, 108), 60.0)
    depth[:, 18 + 48:18 + 72] = 2.0           # tercio derecho del recorte cuadrado central (x 18..90)
    p5 = sector_p5(depth)
    assert all(p5[c] < 3 for c in ("C1", "C2", "C3"))
    assert all(p5[c] > 50 for c in ("A1", "B2", "A3"))


def test_decision_has_the_shape_of_the_vlm_answers():
    strategic = depth_to_decision({"mode": "strategic"}, [_grid(blocked=("B2",))])
    assert strategic["sectores"]["B2"] == "bloqueado" and strategic["sectores"]["A2"] == "libre"
    assert vs.parse_strategic({"cells": {c: ("free" if v == "libre" else "blocked")
                                         for c, v in strategic["sectores"].items()}}) is not None
    scan = depth_to_decision({"mode": "deep_scan"}, [_grid(blocked=(SCAN_SECTOR,)), _grid()])
    assert [v["free"] for v in scan["views"]] == [False, True]
    pano = deep_scan.parse_panorama_description(scan)
    assert [r["tipo"] for r in pano["rumbos"]] == ["muro", "libre"]


def test_query_reports_failure_instead_of_a_default():
    q = make_depth_query(FakeEstimator(p5=_grid()))
    parsed, raw, _lat, err = q({"mode": "strategic", "frames": []})
    assert parsed is None and err == "sin_fotograma"

    class Broken:
        def sectors(self, frame):
            raise RuntimeError("cuda")

    parsed, _raw, _lat, err = make_depth_query(Broken())({"mode": "strategic", "frames": [np.zeros((4, 4, 3))]})
    assert parsed is None and "cuda" in err
    parsed, raw, _lat, err = q({"mode": "strategic", "frames": [np.zeros((4, 4, 3))]})
    assert err is None and json.loads(raw)["p5_m"][0]["B2"] == 50.0


def test_strategic_layer_with_depth_injects_a_world_subgoal():
    svc = make_depth_service(FakeEstimator(p5=_grid(blocked=("A1", "B1", "C1", "B2", "A3", "B3", "C3"))),
                             warmup=False)
    layer = vs.StrategicLayer(svc, "depth")
    assert layer.period_s == vs.DEPTH_STRATEGIC_PERIOD_S
    st = _state()
    layer.tick(st)
    assert layer.payload["frames"][0] is st["rgb_image"] and "images_b64" not in layer.payload
    _wait(svc, layer.req_id)
    audit = layer.tick(st)
    assert audit is not None and audit["arm"] == "depth_strategic"
    assert st["inject_corner"]["sector"] in ("A2", "C2") and st["inject_corner"]["z"] == -10.0
    svc.stop()


def test_scan_with_depth_picks_the_free_heading():
    # Dos rumbos: 0 deg (frente, bloqueado) y 90 deg (libre). El fotograma de cada rumbo se distingue
    # por su valor medio.
    est = FakeEstimator(by_mean={10: _grid(blocked=(SCAN_SECTOR,)), 20: _grid()})
    svc = make_depth_service(est, warmup=False)
    st = _state(wp=(100.0, 100.0))
    st["_scan_phase"] = "capturado"
    st["_scan_frames"] = [(0.0, np.full((H, W, 3), 10, np.uint8), 0.0), (90.0, np.full((H, W, 3), 20, np.uint8), 0.0)]
    st["_scan_start_yaw_deg"] = 0.0
    guidance = {"target_wp": st["waypoints"][0]}
    assert deep_scan.deep_scan_cycle(st, svc, None, st["telemetry"], guidance, "slm", 1)
    rid = st["_deep_scan_request_id"]
    _wait(svc, rid)
    assert deep_scan.deep_scan_cycle(st, svc, None, st["telemetry"], guidance, "slm", 2)
    corner = st["inject_corner"]
    assert abs(math.degrees(math.atan2(corner["y"], corner["x"])) - 90.0) < 1.0
    assert st["_deadlock_event"]["resolved_by_scan"] is True
    assert est.calls == 2
    svc.stop()


def test_free_threshold_is_the_subgoal_distance():
    assert DEPTH_FREE_M == float(vs.VLM_SUBGOAL_DIST_M)
