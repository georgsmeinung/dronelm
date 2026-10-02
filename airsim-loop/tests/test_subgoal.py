"""Sub-metas del VLM: una sola regla para la capa estrategica y el barrido (src/agents/subgoal.py)."""
from __future__ import annotations

import math

from src.agents import deep_scan as ds
from src.agents import subgoal as sg


def test_distance_is_capped_and_never_beyond_the_waypoint():
    assert sg.subgoal_distance(100.0) == sg.VLM_SUBGOAL_DIST_M
    assert sg.subgoal_distance(9.0) == 9.0
    assert sg.subgoal_distance(1.0) == sg.VLM_SUBGOAL_MIN_AHEAD_M + 1.0


def test_altitude_follows_elevation_with_caps():
    level = sg.build_subgoal(0.0, 0.0, -10.0, 0.0, 0.0, 100.0, "X")
    assert level["z"] == -10.0 and abs(level["x"] - sg.VLM_SUBGOAL_DIST_M) < 1e-6
    up = sg.build_subgoal(0.0, 0.0, -10.0, 0.0, 24.0, 100.0, "X")
    assert up["z"] == -10.0 - sg.VLM_MAX_DZ_M
    down = sg.build_subgoal(0.0, 0.0, -8.0, 0.0, -24.0, 100.0, "X")
    assert down["z"] == -sg.VLM_SUBGOAL_MIN_ALT_M


def test_scan_uses_the_same_rule_at_the_current_altitude():
    rumbos = [{"img": 1, "tipo": "libre", "transitable": True, "confianza": 0.9},
              {"img": 2, "tipo": "fachada", "transitable": False, "confianza": 0.9}]
    telem = {"position": {"x": 10.0, "y": 0.0, "z": -12.0}}
    _m, corner, _why = ds.panorama_to_subgoal(rumbos, [90.0, 0.0], telem, goal_bearing_deg=80.0, goal_dist_m=30.0)
    expected = sg.build_subgoal(10.0, 0.0, -12.0, 90.0, 0.0, 30.0, "VLM_SCAN_GOAL")
    expected.pop("dist_m")
    assert corner == expected
    assert abs(math.hypot(corner["x"] - 10.0, corner["y"]) - sg.VLM_SUBGOAL_DIST_M) < 1e-6
