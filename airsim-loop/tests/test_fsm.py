from src.agents.fsm import STATE_AVOID_LEFT, STATE_AVOID_RIGHT, STATE_BRAKE, STATE_CLIMB, STATE_CRUISE, _decide_state
from src.perception.obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field


def _field(center_ttc=float("inf"), center_occ=0.0, left_occ=0.0, right_occ=0.0):
    cells = {(s, b): Cell(sector=s, band=b, confidence=0.9) for s in SECTORS for b in BANDS}
    cells[("centro", "medio")] = Cell(sector="centro", band="medio", occupancy=center_occ, ttc_s=center_ttc, confidence=0.9)
    cells[("izquierda", "medio")] = Cell(sector="izquierda", band="medio", occupancy=left_occ, ttc_s=float("inf"), confidence=0.9)
    cells[("derecha", "medio")] = Cell(sector="derecha", band="medio", occupancy=right_occ, ttc_s=float("inf"), confidence=0.9)
    return ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)


def test_clear_field_cruises():
    assert _decide_state(empty_field(), stuck_cycles=0, stuck_threshold=10) == STATE_CRUISE


def test_deterministic_same_input_same_output():
    field = _field(center_ttc=3.0, center_occ=0.5, left_occ=0.1, right_occ=0.6)
    results = {_decide_state(field, 0, 10) for _ in range(20)}
    assert len(results) == 1


def test_critical_ttc_and_open_sides_brakes():
    field = _field(center_ttc=1.0, center_occ=0.9, left_occ=0.0, right_occ=0.0)
    assert _decide_state(field, 0, 10) == STATE_BRAKE


def test_critical_ttc_boxed_in_climbs():
    field = _field(center_ttc=1.0, center_occ=0.9, left_occ=0.9, right_occ=0.9)
    assert _decide_state(field, 0, 10) == STATE_CLIMB


def test_moderate_block_avoids_toward_less_occupied_side():
    field = _field(center_ttc=3.0, center_occ=0.5, left_occ=0.1, right_occ=0.8)
    assert _decide_state(field, 0, 10) == STATE_AVOID_LEFT


def test_moderate_block_both_sides_blocked_climbs():
    field = _field(center_ttc=3.0, center_occ=0.5, left_occ=0.9, right_occ=0.9)
    assert _decide_state(field, 0, 10) == STATE_CLIMB


def test_stuck_cycles_force_climb_regardless_of_field():
    assert _decide_state(empty_field(), stuck_cycles=15, stuck_threshold=10) == STATE_CLIMB
