from src.agents import graph as graph_mod
from src.perception.obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field


def _field_with(center_ttc=float("inf"), center_occ=0.0, left_occ=0.0, right_occ=0.0, confidence=0.9):
    cells = {(s, b): Cell(sector=s, band=b) for s in SECTORS for b in BANDS}
    cells[("centro", "medio")] = Cell(sector="centro", band="medio", occupancy=center_occ, ttc_s=center_ttc, confidence=confidence)
    cells[("izquierda", "medio")] = Cell(sector="izquierda", band="medio", occupancy=left_occ, ttc_s=float("inf"), confidence=confidence)
    cells[("derecha", "medio")] = Cell(sector="derecha", band="medio", occupancy=right_occ, ttc_s=float("inf"), confidence=confidence)
    return ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)


def test_clear_path_keeps_going(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    state = {"obstacle_field": empty_field(), "evasion_stuck_cycles": 0}
    assert graph_mod.policy_router(state) == "keep_going"


def test_moderate_ttc_without_center_block_triggers_evasive(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    # Centro sin ocupacion (no "bloqueado"), pero TTC dentro de la ventana de
    # advertencia: corresponde a una correccion evasiva rapida, no a
    # deliberacion (que se reserva para bloqueo estructural o TTC critico).
    field = _field_with(center_ttc=4.0, center_occ=0.0)
    state = {"obstacle_field": field, "evasion_stuck_cycles": 0}
    assert graph_mod.policy_router(state) == "evasive"


def test_center_blocked_with_moderate_ttc_triggers_deliberative(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    # Centro con ocupacion por encima del umbral ("bloqueado"): aunque el TTC
    # todavia no sea critico, un bloqueo estructural franco escala a
    # deliberacion en lugar de una correccion lateral rapida.
    field = _field_with(center_ttc=4.0, center_occ=0.5)
    state = {"obstacle_field": field, "evasion_stuck_cycles": 0}
    assert graph_mod.policy_router(state) == "deliberative"


def test_imminent_center_ttc_triggers_deliberative(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    field = _field_with(center_ttc=1.0, center_occ=0.8)
    state = {"obstacle_field": field, "evasion_stuck_cycles": 0}
    assert graph_mod.policy_router(state) == "deliberative"


def test_imminent_with_high_blocked_fraction_triggers_girar_90(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    cells = {
        (s, b): Cell(sector=s, band=b, occupancy=0.9, ttc_s=1.0, confidence=0.9)
        for s in SECTORS for b in BANDS
    }
    field = ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)
    state = {"obstacle_field": field, "evasion_stuck_cycles": 0}
    assert graph_mod.policy_router(state) == "girar_90"


def test_stuck_deadlock_forces_deliberative_regardless_of_field(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    state = {"obstacle_field": empty_field(), "evasion_stuck_cycles": 999}
    assert graph_mod.policy_router(state) == "deliberative"


def test_active_maneuver_persists_as_evasive_when_ttc_safe(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    field = _field_with(center_ttc=float("inf"))
    state = {
        "obstacle_field": field,
        "evasion_stuck_cycles": 0,
        "active_maneuver": "EVADIR_DERECHA",
        "maneuver_cycles_left": 3,
    }
    assert graph_mod.policy_router(state) == "evasive"


def test_reactive_arm_always_keeps_going(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "reactive")
    field = _field_with(center_ttc=0.5, center_occ=1.0)
    state = {"obstacle_field": field, "evasion_stuck_cycles": 999}
    assert graph_mod.policy_router(state) == "keep_going"


def test_fsm_arm_routes_to_fsm_node(monkeypatch):
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "fsm")
    state = {"obstacle_field": empty_field(), "evasion_stuck_cycles": 0}
    assert graph_mod.policy_router(state) == "fsm"


def test_degraded_router_routes_to_hover():
    assert graph_mod.degraded_router({"degraded": True}) == "degraded_hover"
    assert graph_mod.degraded_router({"degraded": False}) == "canny_xor_gate"


def test_xor_router_below_threshold_skips_perception():
    state = {"xor_change_ratio": 0.0}
    assert graph_mod.xor_router(state) == "keep_going"


def test_xor_router_above_threshold_runs_perception():
    state = {"xor_change_ratio": 1.0}
    assert graph_mod.xor_router(state) == "perception"
