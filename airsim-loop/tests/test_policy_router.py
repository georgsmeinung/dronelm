from src.agents import graph as graph_mod
from src.navigation.waypoint_tracker import effective_stall_threshold, hard_stall_threshold
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


def test_stuck_does_not_short_circuit_an_open_corridor(monkeypatch):
    """El escape de deadlock ya no cortocircuita la percepcion.

    En el vuelo del 2026-0824 el router devolvia "deliberative" por
    `evasion_stuck_cycles` ANTES de mirar el ObstacleField, asi que el dron
    subio 12 metros mientras la percepcion reportaba `DERECHA: DESPEJADO`
    ciclo tras ciclo. Con evidencia valida de corredor libre, la decision
    tactica normal manda.
    """
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    field = _field_with()  # los tres sectores libres, con evidencia valida
    state = {
        "obstacle_field": field,
        "waypoint_guidance": {"bearing_err_deg": 30.0},  # waypoint a la derecha
        "evasion_stuck_cycles": effective_stall_threshold(),
    }
    assert graph_mod.policy_router(state) == "keep_going"


def test_hard_stuck_overrides_the_open_corridor_bypass(monkeypatch):
    """El bypass por percepcion tiene techo: un campo "despejado" espurio no
    puede desactivar el escape indefinidamente.
    """
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    field = _field_with()  # mismo campo despejado que el test anterior
    state = {
        "obstacle_field": field,
        "waypoint_guidance": {"bearing_err_deg": 30.0},
        "evasion_stuck_cycles": hard_stall_threshold(),
    }
    assert graph_mod.policy_router(state) == "deliberative"


def test_committed_maneuver_is_not_preempted_by_the_stall_counter(monkeypatch):
    """Una maniobra ya comprometida (p. ej. el giro de cambio de estrategia
    que emite el escape agotado) debe poder ejecutarse: el contador de atasco
    no la preempta mientras el TTC sea seguro.
    """
    monkeypatch.setattr(graph_mod, "AGENT_ARM", "slm")
    state = {
        "obstacle_field": empty_field(),
        "evasion_stuck_cycles": 999,
        "active_maneuver": "GIRAR_90",
        "maneuver_cycles_left": 3,
    }
    assert graph_mod.policy_router(state) == "evasive"


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
    assert graph_mod.degraded_router({"degraded": False}) == "perception"
