"""Escape por altura del brazo FSM (CHANGELOG 2026-0824/0827).

2026-0930: los tests del escape del nodo deliberativo legacy se eliminaron junto con el nodo
(src/agents/legacy/deliberative_v2.py). El brazo FSM conserva su propio escape determinista.
"""
from __future__ import annotations

import src.agents.deep_scan as deep_scan_mod
from src.agents import fsm as fsm_mod
from src.perception.obstacle_field import empty_field


def _base_state():
    return {
        "waypoints": [], "current_wp_index": 0, "target_waypoint": None,
        "waypoint_guidance": {}, "mission_completed": False, "rgb_image": None,
        "telemetry": {}, "frame_history": [],
        "estimated_ttc": float("inf"), "next_action": "", "flight_status": "vuelo",
        "deliberations": [], "active_maneuver": None, "maneuver_cycles_left": 0,
        "maneuver_command": None, "evasion_stuck_cycles": 0, "slm_request_id": None,
    }


def test_fsm_max_consecutive_escapes_latches_and_changes_strategy(monkeypatch):
    """Fix 3 (fsm.py, 2026-0827): mismo tope Y mismo cambio de estrategia que

    el brazo SLM (test_max_consecutive_escapes_latches_and_changes_strategy
    arriba). Antes, agotado el tope, fsm.py pasaba a STATE_BRAKE y enclavaba
    para siempre -- si el obstaculo era horizontal (p. ej. trabado contra
    ramas que no disparan colision), subir nunca genera el progreso
    horizontal que libera el enclave, y el dron quedaba frenando hasta el
    timeout de la mision (ver CHANGELOG.md 2026-0827, corrida real en
    townsim_a). Ahora gira 90 grados para buscar corredor, igual que
    deliberative.py.
    """
    monkeypatch.setenv("MAX_CONSECUTIVE_ESCAPES", "3")
    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "blind")  # escape propio del FSM, sin VLM

    state = _base_state()
    state["obstacle_field"] = empty_field()

    actions = []
    flight_statuses = []
    for _ in range(5):
        state["evasion_stuck_cycles"] = 999
        # Evita que la persistencia de maniobra de fsm_node tape el resultado:
        # cada iteracion simula una evaluacion nueva, no la continuacion de
        # la anterior (esa continuacion ya esta cubierta por otro test).
        state["active_maneuver"] = None
        state["maneuver_cycles_left"] = 0
        state = fsm_mod.fsm_node(state)
        actions.append(state["next_action"])
        flight_statuses.append(state["flight_status"])

    # 2026-0827: alterna CLIMB/DESCEND entre intentos sucesivos (ver
    # _vertical_escape_state en fsm.py) en vez de insistir siempre con
    # GANAR_ALTURA -- confirmado en UE que el dron podia quedar insistiendo
    # dentro de la copa de un arbol sin nunca intentar bajar. Se evaluo
    # tambien RETROCEDER (retroceder por el camino recien recorrido) pero se
    # descarto: agregaba ruido notable a la trayectoria.
    assert actions[:3] == ["GANAR_ALTURA", "PERDER_ALTURA", "GANAR_ALTURA"]
    assert actions[3] == "GIRAR_90"  # cambio de estrategia, no mas escape vertical
    assert flight_statuses[3] == "fsm_escape_agotado"
    # 2026-0827: el giro de cambio de estrategia tambien inyecta un waypoint
    # de desvio persistente (antes declarado en DroneState pero nunca
    # producido por ningun nodo -- ver CHANGELOG.md).
    corner = state.get("inject_corner")
    assert isinstance(corner, dict)
    assert {"x", "y", "z"} <= corner.keys()
    # Una vez enclavado, la 5ta evaluacion ya no reintenta CLIMB/DESCEND: cae
    # a la evaluacion normal por TTC (aca sin obstaculos, cruce normal).
    assert actions[4] not in ("GANAR_ALTURA", "PERDER_ALTURA")
