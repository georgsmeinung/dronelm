from src.navigation.waypoint_tracker import WaypointTracker


def test_single_waypoint_mission_completes():
    tracker = WaypointTracker([{"x": 10, "y": 0, "z": -10, "label": "WP1"}], acceptance_radius=2.0)
    assert not tracker.is_completed
    tracker.update({"x": 10, "y": 0, "z": -10})
    assert tracker.is_completed


def test_empty_waypoint_list_is_immediately_completed():
    tracker = WaypointTracker([])
    assert tracker.is_completed


def test_zero_length_segment_does_not_crash_guidance():
    # Waypoints duplicados: segmento de longitud 0 entre WP0 y WP1.
    wps = [
        {"x": 0, "y": 0, "z": -10, "label": "A"},
        {"x": 0, "y": 0, "z": -10, "label": "B"},
        {"x": 50, "y": 0, "z": -10, "label": "C"},
    ]
    tracker = WaypointTracker(wps, acceptance_radius=1.0)
    guidance = tracker.compute_guidance({"x": 0.0, "y": 0.0, "z": -10.0}, current_yaw=0.0)
    assert guidance is not None
    assert not (guidance["vx"] != guidance["vx"])  # no NaN


def test_inject_corner_waypoint_dedup_within_radius():
    tracker = WaypointTracker([{"x": 100, "y": 100, "z": -10, "label": "FAR"}])
    first = tracker.inject_corner_waypoint(10.0, 10.0, -10.0, label="CORNER_A")
    assert first is True
    # Segunda inyeccion muy cerca de la primera: debe ser rechazada (dedup).
    second = tracker.inject_corner_waypoint(11.0, 11.0, -10.0, label="CORNER_B")
    assert second is False


def test_record_progress_resets_on_real_progress():
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    tracker.record_progress(100.0)
    tracker.record_progress(99.0)
    assert tracker.progress_stall_cycles == 0


def test_record_progress_increments_when_stalled():
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    tracker.record_progress(50.0)
    tracker.record_progress(50.2)
    tracker.record_progress(50.1)
    assert tracker.progress_stall_cycles == 2


def test_long_correct_manhattan_detour_does_not_count_as_stuck():
    """Regresion F2.5: un desvio largo pero que sigue acercando al waypoint

    (aunque tome muchos ciclos) no debe contar como atasco.
    """
    tracker = WaypointTracker([{"x": 200, "y": 0, "z": -10, "label": "WP1"}])
    distances = [200 - i for i in range(0, 60, 2)]  # progreso monotono, de a 2m
    for d in distances:
        tracker.record_progress(float(d))
    assert tracker.progress_stall_cycles == 0


def test_reset_progress_clears_stall_counter():
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    tracker.record_progress(50.0)
    tracker.record_progress(50.0)
    assert tracker.progress_stall_cycles == 1
    tracker.reset_progress()
    assert tracker.progress_stall_cycles == 0


def test_waypoint_advance_resets_progress_tracking():
    tracker = WaypointTracker(
        [{"x": 10, "y": 0, "z": -10, "label": "A"}, {"x": 20, "y": 0, "z": -10, "label": "B"}],
        acceptance_radius=2.0,
    )
    tracker.record_progress(10.0)
    tracker.record_progress(10.0)
    assert tracker.progress_stall_cycles == 1
    tracker.update({"x": 10, "y": 0, "z": -10})  # alcanza WP A
    assert tracker.progress_stall_cycles == 0
