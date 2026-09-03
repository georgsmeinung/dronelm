# 2026-0903 (pedido explicito, ver CHANGELOG.md): mientras se espera la
# respuesta del SLM/VLM, el brazo slm ya no frena del todo salvo que haya un
# bloqueo central confirmado con TTC bajo -- antes SIEMPRE frenaba, lo que
# cortaba la traslacion y con ella la confianza del estimador de flujo
# (analisis de TOWNSIM_INI: 82.5% de las deliberaciones con evidencia casi
# nula, la mayoria disparadas por FRENAR/ESCANEO en los ciclos previos, no
# por un obstaculo real). Este test cubre las dos ramas: avance cauteloso
# cuando es seguro, freno real cuando no lo es.
from __future__ import annotations

import time

from src.agents import deliberative as deliberative_mod
from src.perception.obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field


def _base_state():
    return {
        "waypoints": [], "current_wp_index": 0, "target_waypoint": None,
        "waypoint_guidance": {}, "mission_completed": False, "rgb_image": None,
        "telemetry": {}, "frame_history": [],
        "estimated_ttc": float("inf"), "next_action": "", "flight_status": "vuelo",
        "deliberations": [], "active_maneuver": None, "maneuver_cycles_left": 0,
        "maneuver_command": None, "evasion_stuck_cycles": 0, "slm_request_id": None,
    }


def _slow_query(payload):
    # Nunca resuelve dentro de la ventana del test: el nodo queda en la rama
    # "esperando respuesta" en cada invocacion.
    time.sleep(5.0)
    return None, "", 5000.0, None


def test_creeps_forward_instead_of_full_stop_when_no_confirmed_blockage(monkeypatch):
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _slow_query)
    monkeypatch.setenv("DELIB_WAIT_CREEP_SPEED_MPS", "0.5")

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        state = _base_state()
        state["obstacle_field"] = empty_field()  # sin evidencia, nada bloqueado -> close_structural=False
        state["waypoint_guidance"] = {"vx": 3.0, "distance": 50.0}

        # Primer ciclo: recien encolado.
        state = node(state)
        assert state["next_action"] == "MANTENER_RUMBO"
        assert 0.0 < state["velocity_command"]["vx"] <= 0.5

        # Segundo ciclo: sigue pendiente, dentro del watchdog.
        state = node(state)
        assert state["next_action"] == "MANTENER_RUMBO"
        assert 0.0 < state["velocity_command"]["vx"] <= 0.5
    finally:
        service.stop()


def test_still_fully_brakes_when_center_is_genuinely_blocked(monkeypatch):
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _slow_query)

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        cells = {
            (s, b): Cell(sector=s, band=b, occupancy=0.9, ttc_s=1.0, confidence=0.9)
            for s in SECTORS for b in BANDS
        }
        field = ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)

        state = _base_state()
        state["obstacle_field"] = field  # centro bloqueado, TTC=1.0s <= SAFE_MARGIN_TTC_S -> close_structural=True
        state["waypoint_guidance"] = {"vx": 3.0, "distance": 50.0}

        state = node(state)
        assert state["next_action"] == "FRENAR"
        assert state["velocity_command"]["vx"] == 0.0

        state = node(state)
        assert state["next_action"] == "FRENAR"
        assert state["velocity_command"]["vx"] == 0.0
    finally:
        service.stop()
