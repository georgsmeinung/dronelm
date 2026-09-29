"""Deteccion de techo en WaypointTracker (2026-0928)."""
from src.navigation.waypoint_tracker import WaypointTracker, CEILING_DETECT_CYCLES, CEILING_MARGIN_M

WPS = [{"x": 50.0, "y": 0.0, "z": -10.0, "label": "A"}, {"x": 90.0, "y": 0.0, "z": -10.0, "label": "B"}]


def _fly(tr, z, n, x=0.0):
    g = None
    for _ in range(n):
        g = tr.compute_guidance({"x": x, "y": 0.0, "z": z}, 0.0)
    return g


def test_ceiling_detected_and_target_altitude_capped():
    tr = WaypointTracker(list(WPS))
    g = _fly(tr, -6.0, CEILING_DETECT_CYCLES + 2)
    assert tr.ceiling_z is not None and abs(tr.ceiling_z + 6.0) < 0.01
    assert g["ceiling_z"] == tr.ceiling_z
    # objetivo -5.0: ya no demanda ascenso (dz=+1.0 -> vz positivo o cero)
    assert g["vz"] >= 0.0
    assert CEILING_MARGIN_M > 0


def test_no_false_ceiling_when_climbing_or_on_ground():
    tr = WaypointTracker(list(WPS))
    for i in range(CEILING_DETECT_CYCLES + 5):
        tr.compute_guidance({"x": 0.0, "y": 0.0, "z": -4.0 - 0.2 * i}, 0.0)
    assert tr.ceiling_z is None
    tr2 = WaypointTracker(list(WPS))
    _fly(tr2, -1.5, CEILING_DETECT_CYCLES + 5)
    assert tr2.ceiling_z is None


def test_ceiling_released_after_moving_away():
    tr = WaypointTracker(list(WPS))
    _fly(tr, -6.0, CEILING_DETECT_CYCLES + 2)
    assert tr.ceiling_z is not None
    tr.compute_guidance({"x": 20.0, "y": 0.0, "z": -5.0}, 0.0)
    assert tr.ceiling_z is None
