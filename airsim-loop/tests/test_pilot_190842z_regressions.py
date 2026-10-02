"""Regresiones del piloto v3 citysim_pilot seed 99 (2026-10-01 190842Z).

El dron paso 573 ciclos a < 3.5 m de WP_0_SUR sin aceptarlo (el objetivo activo era siempre una
sub-meta del VLM); las sub-metas quedaban a 15 m aunque el WP estuviera a 1-6 m (dentro del
edificio); el barrido eligio una imagen del interior de una oficina marcada "libre, ok:true" con
"degradada": true; y un techo falso, detectado con el dron trabado contra una fachada, peleaba con
los escapes verticales.
"""
from __future__ import annotations

from src.agents import deep_scan as ds
from src.navigation.waypoint_tracker import CEILING_DETECT_CYCLES, WaypointTracker

WP = {"x": -5.0, "y": -51.0, "z": -10.0, "label": "WP_0_SUR"}


def _tracker_with_subgoal():
    tr = WaypointTracker([dict(WP), {"x": 26.1, "y": -78.2, "z": -10.0, "label": "WP_1"}])
    assert tr.inject_corner_waypoint(-20.0, -49.0, -14.0, label="VLM_SUBGOAL")
    return tr


# --------------------------------------------------------------------------- WP real con sub-meta activa
def test_real_waypoint_is_accepted_while_a_subgoal_is_active():
    tr = _tracker_with_subgoal()
    assert tr.current_waypoint["label"] == "VLM_SUBGOAL"
    tr.update({"x": -5.5, "y": -50.0, "z": -10.5})      # a 1.2 m del WP real, lejos de la sub-meta
    assert tr.current_waypoint["label"] == "WP_1"
    assert not any(w.get("is_temporary") for w in tr.waypoints[tr.current_index:])


def test_subgoal_still_reached_normally_when_the_real_wp_is_far():
    tr = _tracker_with_subgoal()
    tr.update({"x": -19.0, "y": -49.0, "z": -14.0})
    assert tr.current_waypoint["label"] == "WP_0_SUR"


def test_drop_temporary_returns_to_the_real_waypoint():
    tr = _tracker_with_subgoal()
    assert tr.drop_temporary("prueba") == 1
    assert tr.current_waypoint["label"] == "WP_0_SUR"
    assert tr.drop_temporary() == 0


# --------------------------------------------------------------------------- techo con el dron trabado de costado
def test_pressed_against_a_wall_is_not_a_ceiling():
    tr = WaypointTracker([dict(WP)])
    for _ in range(CEILING_DETECT_CYCLES + 5):
        g = tr.compute_guidance({"x": -10.0, "y": -52.6, "z": -11.8}, 0.0)
        # se ordena avanzar y subir, y el dron no se desplaza: roce contra la fachada
        tr.note_executed_command({"vx": 1.0, "vz": -0.8})
    assert tr.ceiling_z is None


def test_ceiling_with_free_horizontal_motion_is_still_detected():
    tr = WaypointTracker([dict(WP)])
    for i in range(CEILING_DETECT_CYCLES + 2):
        tr.compute_guidance({"x": 20.0 - 0.3 * i, "y": -30.0, "z": -7.0}, 0.0)
        tr.note_executed_command({"vx": 1.5, "vz": -0.8})
    assert tr.ceiling_z is not None


# --------------------------------------------------------------------------- barrido
HEADINGS = [-90.0, 0.0, 90.0, 180.0]
TELEM = {"position": {"x": -9.9, "y": -50.0, "z": -8.0}}


def _rumbos(*entries):
    return [{"img": i + 1, "tipo": t, "transitable": ok, "confianza": 0.9} for i, (t, ok) in enumerate(entries)]


def test_contradictory_entries_are_not_transitable():
    # img 2 (rumbo 0) es el interior de una oficina marcado ok:true; img 4 (180) es una calle libre.
    rumbos = _rumbos(("fachada", False), ("interior", True), ("muro", False), ("libre", True))
    macro, corner, why = ds.panorama_to_subgoal(rumbos, HEADINGS, TELEM, goal_bearing_deg=10.0)
    assert macro == "MANTENER_RUMBO" and "180" in why


def test_only_contradictory_entries_means_nothing_transitable():
    rumbos = _rumbos(("fachada", True), ("interior", True), ("muro", False), ("fachada", False))
    macro, corner, _why = ds.panorama_to_subgoal(rumbos, HEADINGS, TELEM, goal_bearing_deg=10.0)
    assert macro == "GANAR_ALTURA" and corner is None


def test_scan_subgoal_never_beyond_the_real_waypoint():
    rumbos = _rumbos(("libre", True), ("fachada", False), ("muro", False), ("fachada", False))
    _m, corner, _why = ds.panorama_to_subgoal(rumbos, HEADINGS, TELEM, goal_bearing_deg=-90.0, goal_dist_m=9.0)
    assert abs(abs(corner["y"] - TELEM["position"]["y"]) - 9.0) < 0.05


def test_no_scan_near_the_real_waypoint():
    state = {"waypoints": [dict(WP)], "current_wp_index": 0}
    telem = {"position": {"x": -6.0, "y": -50.0, "z": -10.0}, "orientation": {"yaw": 0.0}}
    handled = ds.deep_scan_cycle(state, service=None, field=None, telemetry=telem,
                                 guidance={"target_wp": WP}, arm="slm", deadlock_cycles=1)
    assert handled is False and state.get("_scan_phase") is None
    assert state["_deadlock_event"]["reason"] == "cerca_del_wp"
