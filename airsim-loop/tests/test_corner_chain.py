"""Cadena de esquinas del WaypointTracker (2026-0929)."""
from __future__ import annotations

from src.navigation.waypoint_tracker import WaypointTracker, CORNER_CHAIN_MAX


def _tracker():
    # WP_A real en (0,0); objetivo real WP_B en (100,0) al este.
    tr = WaypointTracker([{"x": 0.0, "y": 0.0, "z": -10.0, "label": "A"},
                          {"x": 100.0, "y": 0.0, "z": -10.0, "label": "B"}])
    tr.update({"x": 0.0, "y": 0.0, "z": -10.0})  # alcanza A -> objetivo B
    assert tr.current_index == 1
    return tr


def _reach_corner(tr):
    wp = tr.current_waypoint
    tr.update({"x": wp["x"], "y": wp["y"], "z": wp["z"]})


def test_chain_inserted_when_leg_passes_near_contact():
    tr = _tracker()
    tr.record_contact(50.0, 3.0)                      # contacto a 3 m de la recta esquina->B
    tr.inject_corner_waypoint(10.0, 8.0, -10.0)       # esquina (norte de la recta)
    _reach_corner(tr)
    wp = tr.current_waypoint
    assert str(wp["label"]).startswith("CORNER_CHAIN_")
    # el contacto (50,3) queda al sur de la recta esquina->B (en x=50 la recta esta en y~4.4):
    # la esquina encadenada debe ir al lado contrario, hacia el norte
    assert wp["y"] > 8.0 + 5.0


def test_no_chain_when_contact_is_far_from_leg():
    tr = _tracker()
    tr.record_contact(50.0, 40.0)                     # a 32 m del tramo
    tr.inject_corner_waypoint(10.0, 8.0, -10.0)
    _reach_corner(tr)
    assert tr.current_waypoint["label"] == "B"


def test_chain_is_bounded_and_cleared_on_real_wp():
    tr = _tracker()
    tr.record_contact(50.0, 0.0)
    tr.inject_corner_waypoint(10.0, 8.0, -10.0)
    for _ in range(CORNER_CHAIN_MAX + 3):
        _reach_corner(tr)
        if tr.current_waypoint["label"] == "B":
            break
    assert tr._chain_count <= CORNER_CHAIN_MAX
    # al alcanzar el WP real se limpian contactos y contador
    tr.update({"x": 100.0, "y": 0.0, "z": -10.0})
    assert tr._contacts == [] and tr._chain_count == 0


def test_record_contact_merges_nearby_points():
    tr = _tracker()
    tr.record_contact(10.0, 10.0)
    tr.record_contact(11.0, 10.5)
    assert len(tr._contacts) == 1
