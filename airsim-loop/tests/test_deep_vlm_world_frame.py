"""deep_vlm sin overrides y con interpretacion en marco mundo (2026-0930).

Reproduce el bug de las corridas citysim_pilot seed 99 (2026-0929): el VLM respondio que el rumbo
-53 deg (el que apuntaba a la meta) estaba libre, pero la etiqueta era absoluta, el parser la leia
como relativa y el bearing se media desde el yaw FINAL del barrido (153 deg): resultado
EVADIR_IZQUIERDA, alejandose de la meta.
"""
from __future__ import annotations

import math
import time

import numpy as np

import src.agents.deep_scan as deep_scan_mod
import src.agents.vlm_client as deliberative_mod
from src.navigation.waypoint_tracker import WaypointTracker
from src.perception.obstacle_field import empty_field


def _telem(x=0.0, y=0.0, yaw_deg=0.0):
    return {"position": {"x": x, "y": y, "z": -10.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": math.radians(yaw_deg)}}


def _pano(raw):
    return deep_scan_mod.parse_panorama_description(raw)["rumbos"]


def test_regression_goal_heading_free_is_followed_not_evaded():
    # Barrido desde -53 deg (hacia la meta) y 127 deg (atras); el dron termina mirando 127.
    rumbos = _pano({"rumbos": [{"img": 1, "tipo": "libre", "ok": True},
                               {"img": 2, "tipo": "muro", "ok": False}], "degradada": False})
    telem = _telem(-6.3, 7.2, yaw_deg=153.0)
    goal_bearing = math.degrees(math.atan2(-78.2 - 7.2, 26.1 + 6.3))  # ~ -69
    macro, corner, _why = deep_scan_mod.panorama_to_subgoal(rumbos, [-53.0, 127.0], telem, goal_bearing)
    assert macro == "MANTENER_RUMBO"
    assert corner is not None and corner["label"] == "VLM_SCAN_GOAL"
    heading = math.degrees(math.atan2(corner["y"] - 7.2, corner["x"] + 6.3))
    assert abs(heading - (-53.0)) < 1.0


def test_absolute_deg_in_model_answer_is_ignored():
    # El modelo copio el rumbo absoluto en "deg": el codigo se guia por el numero de imagen.
    rumbos = _pano({"rumbos": [{"img": 2, "deg": 0, "tipo": "libre", "ok": True},
                               {"img": 1, "deg": -53, "tipo": "fachada", "ok": False}], "degradada": False})
    macro, corner, _ = deep_scan_mod.panorama_to_subgoal(rumbos, [0.0, 90.0], _telem(), 0.0)
    heading = math.degrees(math.atan2(corner["y"], corner["x"]))
    assert macro == "MANTENER_RUMBO" and abs(heading - 90.0) < 1.0


def test_extra_hallucinated_entries_are_dropped():
    rumbos = _pano({"rumbos": [{"tipo": "fachada", "ok": False}, {"tipo": "libre", "ok": True},
                               {"tipo": "libre", "ok": True}], "degradada": False})
    assigned = deep_scan_mod.assign_panorama_entries(rumbos, 2)
    assert len(assigned) == 2 and assigned[0]["tipo"] == "fachada" and assigned[1]["tipo"] == "libre"


def test_nothing_transitable_climbs():
    rumbos = _pano({"rumbos": [{"img": 1, "tipo": "muro", "ok": False},
                               {"img": 2, "tipo": "fachada", "ok": False}], "degradada": False})
    macro, corner, _ = deep_scan_mod.panorama_to_subgoal(rumbos, [0.0, 180.0], _telem(), 0.0)
    assert macro == "GANAR_ALTURA" and corner is None


def test_closest_transitable_to_goal_wins():
    rumbos = _pano({"rumbos": [{"img": i + 1, "tipo": "libre", "ok": True} for i in range(4)], "degradada": False})
    _, corner, _ = deep_scan_mod.panorama_to_subgoal(rumbos, [0.0, 90.0, 180.0, -90.0], _telem(), 100.0)
    assert abs(math.degrees(math.atan2(corner["y"], corner["x"])) - 90.0) < 1.0


def test_scan_resolution_keeps_vlm_macro():
    """Fix L/L2 ya no reescriben la decision: dos EVADIR opuestos seguidos se respetan."""
    state = {"deliberations": []}
    for macro in ("EVADIR_IZQUIERDA", "EVADIR_DERECHA"):
        deep_scan_mod._apply_scan_resolution(
            state, {"macro_action": macro, "rationale": "vlm"}, "raw", 5.0, {}, _telem(), "slm", 1,
        )
        assert state["next_action"] == macro
        assert state["active_maneuver"] == macro


def test_deep_vlm_starts_scanning_without_blind_reverse(monkeypatch):
    """Sin Fix M: el primer ciclo del deadlock gira para escanear, no retrocede a ciegas."""
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 4)

    class _Svc:
        def request(self, payload):
            return 1

        def poll(self):
            return None, 0.0, True

    state = {"rgb_image": np.zeros((10, 10, 3), dtype=np.uint8)}
    for _ in range(3):
        deep_scan_mod.deep_scan_cycle(state, _Svc(), empty_field(), _telem(yaw_deg=10.0), {}, "slm", 1, 0)
        assert state["next_action"] == "ESCANEO"
    assert "_post_retroceder_corner_pending" not in state


def test_full_scan_injects_forced_world_subgoal(monkeypatch):
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "deep_vlm")
    monkeypatch.setattr(deep_scan_mod, "SCAN_HEADING_COUNT_DEEP", 2)
    monkeypatch.setattr(deep_scan_mod, "SCAN_SETTLE_CYCLES_DEEP", 1)
    seen = {}

    def _query(payload):
        seen.update(payload)
        # Imagen 1 = rumbo inicial (bloqueado), imagen 2 = opuesto (libre)
        return ({"rumbos": [{"img": 1, "tipo": "fachada", "transitable": False, "relativo_deg": 0.0, "confianza": 0.8},
                            {"img": 2, "tipo": "libre", "transitable": True, "relativo_deg": 0.0, "confianza": 0.8}],
                 "imagen_degradada_global": False, "rationale": ""}, "raw", 5.0, None)

    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _query)
    service = deliberative_mod.make_deliberation_service()
    try:
        state = {"rgb_image": np.zeros((10, 10, 3), dtype=np.uint8), "deliberations": [],
                 "waypoints": [{"x": 0.0, "y": -50.0, "z": -10.0, "label": "WP_1"}], "current_wp_index": 0}
        yaw = 0.0
        for _ in range(60):
            deep_scan_mod.deep_scan_cycle(state, service, empty_field(), _telem(yaw_deg=yaw), {}, "slm", 1, 0)
            tgt = (state.get("velocity_command") or {}).get("target_yaw")
            if tgt is not None:
                yaw = tgt
            if state.get("inject_corner"):
                break
            time.sleep(0.02)
        corner = state.get("inject_corner")
        assert corner and corner["label"] == "VLM_SCAN_GOAL"
        assert abs(abs(math.degrees(math.atan2(corner["y"], corner["x"]))) - 180.0) < 2.0
        assert seen["image_labels"][0] == "[Image 1]"
        assert "Prioriza" not in seen["prompt"]
    finally:
        service.stop()


def test_tracker_inserts_vlm_subgoal_as_is_and_replaces_pending():
    """Sin filtros deterministas: una sub-meta que aleja del WP (rodeo) se inserta tal cual, y una nueva
    reemplaza a la pendiente."""
    tr = WaypointTracker([{"x": 0.0, "y": 0.0, "z": -10.0, "label": "A"},
                          {"x": 100.0, "y": 0.0, "z": -10.0, "label": "B"}])
    tr.update({"x": 0.0, "y": 0.0, "z": -10.0})
    assert tr.inject_corner_waypoint(-10.0, 15.0, -10.0)
    assert tr.inject_corner_waypoint(5.0, 20.0, -10.0)
    temps = [w for w in tr.waypoints if w.get("is_temporary")]
    assert len(temps) == 1 and temps[0]["x"] == 5.0
    assert tr.current_waypoint["label"] == "VLM_SUBGOAL"
