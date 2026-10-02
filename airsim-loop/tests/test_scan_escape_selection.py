"""Seleccion de salida en deadlock (deep_scan.panorama_to_subgoal), 2026-10-01."""
from __future__ import annotations

from src.agents import deep_scan as ds

HEADINGS = [0.0, 90.0, 180.0, -90.0]          # frente (meta), derecha, atras, izquierda
TELEM = {"position": {"x": 0.0, "y": 0.0, "z": -10.0}}


def _rumbos(*free_imgs):
    return [{"img": i + 1, "tipo": "libre" if i + 1 in free_imgs else "fachada",
             "transitable": i + 1 in free_imgs, "confianza": 0.9} for i in range(4)]


def test_failed_heading_is_not_chosen_even_if_the_model_marks_it_free():
    log = {}
    _m, corner, why = ds.panorama_to_subgoal(_rumbos(1, 2), HEADINGS, TELEM, goal_bearing_deg=0.0,
                                             failed_heading_deg=10.0, log=log)
    assert log["chosen_heading_deg"] == 90.0 and log["mode"] == "hacia_meta"
    assert log["excluded"] == [{"heading_deg": 0.0, "reason": "rumbo_fallido"}]
    assert corner is not None and corner["y"] > 0


def test_headings_already_tried_nearby_are_excluded_and_exploration_picks_the_most_different():
    log = {}
    # Ya se probo la derecha (90) en este lugar; libres: derecha, atras, izquierda. La meta esta al frente.
    _m, _c, _w = ds.panorama_to_subgoal(_rumbos(2, 3, 4), HEADINGS, TELEM, goal_bearing_deg=0.0,
                                        failed_heading_deg=0.0, tried_headings_deg=[90.0], log=log)
    assert {"heading_deg": 90.0, "reason": "ya_probado"} in log["excluded"]
    assert log["mode"] == "exploracion"
    # izquierda (-90) esta a 90 del fallido y a 180 del probado; atras (180) a 180 y 90: empatan en el
    # minimo (90) y desempata la cercania a la meta -> izquierda.
    assert log["chosen_heading_deg"] == -90.0


def test_only_failed_or_tried_headings_free_climbs():
    log = {}
    macro, corner, why = ds.panorama_to_subgoal(_rumbos(1, 2), HEADINGS, TELEM, goal_bearing_deg=0.0,
                                                failed_heading_deg=0.0, tried_headings_deg=[90.0], log=log)
    assert macro == "GANAR_ALTURA" and corner is None and log["mode"] == "sin_rumbo_nuevo"


def test_history_is_local_to_the_place_and_the_waypoint():
    st = {}
    ds.record_deadlock(st, {"x": 0.0, "y": 0.0}, "WP_3", 0.0, 90.0, "subgoal")
    ds.record_deadlock(st, {"x": 50.0, "y": 0.0}, "WP_3", 180.0, -90.0, "subgoal")   # lejos
    ds.record_deadlock(st, {"x": 1.0, "y": 0.0}, "WP_2", 45.0, 135.0, "subgoal")     # otro WP
    assert ds.nearby_tried_headings(st, {"x": 2.0, "y": 1.0}, "WP_3") == [0.0, 90.0]
    for i in range(ds.SCAN_HISTORY_MAX + 3):
        ds.record_deadlock(st, {"x": 0.0, "y": 0.0}, "WP_3", None, None, "falla_watchdog")
    assert len(st["_deadlock_history"]) == ds.SCAN_HISTORY_MAX
