"""Regresion del bug de escape por altura descontrolado (CHANGELOG 2026-0824).

Diagnostico original: `deliberative.py` y `fsm.py` comparten un escape
sincrono ("GANAR_ALTURA"/CLIMB) cuando `evasion_stuck_cycles` supera
`EVASION_STUCK_THRESHOLD`. Dos bugs compuestos:

- Fix 1: frenar a proposito mientras se espera al SLM (dentro del watchdog)
  contaba como "sin progresar" -- con `EVASION_STUCK_THRESHOLD=10` ciclos
  (~2s a `LOOP_HZ=5.0`) y latencia real del SLM de 2-8s medida, el escape
  descartaba el pedido pendiente casi siempre antes de que pudiera resolverse.
- Fix 3 (red de seguridad): sin un tope de intentos, subir para escapar de
  un atasco puede no resolverlo nunca (los waypoints estan a altitud
  constante, asi que subir empeora la metrica de distancia usada para medir
  progreso) y el dron queda ascendiendo sin techo -- 356m medidos en una
  corrida real de 5 minutos.

Fix 2 (distancia horizontal en vez de 3D) se prueba en test_waypoint_tracker.py.
"""
from __future__ import annotations

import time

from src.agents import deliberative as deliberative_mod
from src.agents import fsm as fsm_mod
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
    # Simula un SLM real que tarda mas que EVASION_STUCK_THRESHOLD a 5Hz
    # (~2s) -- nunca deberia resolverse durante la ventana del test.
    time.sleep(1.0)
    return None, "", 1000.0, None


def test_waiting_for_slm_does_not_trigger_altitude_escape(monkeypatch):
    """Fix 1: reproduce el loop de runner.py/main.py (record_progress() se

    salta mientras _deliberation_pending este activo). Sin el fix, 15 ciclos
    de espera (mas que EVASION_STUCK_THRESHOLD=10) dispararian GANAR_ALTURA
    antes de que el SLM (simulado con 1s de latencia) pudiera responder.
    """
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", _slow_query)

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node
    from src.navigation.waypoint_tracker import WaypointTracker

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        cells = {(s, b): Cell(sector=s, band=b, occupancy=0.9, ttc_s=1.0, confidence=0.9) for s in SECTORS for b in BANDS}
        field = ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)

        tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
        state = _base_state()
        state["obstacle_field"] = field

        for _ in range(15):
            guidance = tracker.compute_guidance({"x": 0.0, "y": 0.0, "z": -10.0}, current_yaw=0.0)
            if not state.get("_deliberation_pending", False):
                tracker.record_progress(guidance["dist_xy"])
            state["waypoint_guidance"] = guidance
            state["evasion_stuck_cycles"] = tracker.progress_stall_cycles
            state = node(state)
            assert state["next_action"] != "GANAR_ALTURA"
    finally:
        service.stop()


def test_max_consecutive_escapes_latches_and_changes_strategy(monkeypatch):
    """Fix 3 (deliberative.py): tras MAX_CONSECUTIVE_ESCAPES disparos

    seguidos del escape sincrono, deja de comandar GANAR_ALTURA, ENCLAVA el
    escape y cambia de estrategia (giro) en vez de seguir subiendo sin techo.

    Regresion del ciclo limite del 2026-0824: la version anterior frenaba
    pero ademas ponia `_consecutive_escapes = 0` en la misma rama, asi que el
    ciclo siguiente volvia a subir. La red de seguridad se reseteaba a si
    misma y el resultado medido en vuelo fue (SUBIR, SUBIR, FRENAR) repetido
    indefinidamente, con el dron ganando altura sin parar.
    """
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", lambda payload: (None, "", 5.0, "sin servidor SLM"))
    monkeypatch.setenv("MAX_CONSECUTIVE_ESCAPES", "3")

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        state = _base_state()
        state["obstacle_field"] = empty_field()

        actions = []
        for _ in range(8):
            state["evasion_stuck_cycles"] = 999  # simula atasco persistente
            state = node(state)
            actions.append(state["next_action"])

        # 2026-0827 (ver CHANGELOG.md): alterna GANAR_ALTURA/PERDER_ALTURA
        # entre intentos, mismo fix que fsm.py -- antes solo subia, sin
        # alternativa si el obstaculo tambien bloqueaba por arriba
        # (confirmado en UE: dron trabado dentro de la copa de un arbol).
        assert actions[:3] == ["GANAR_ALTURA", "PERDER_ALTURA", "GANAR_ALTURA"]
        assert actions[3] == "GIRAR_90"  # cambio de estrategia, no mas escape vertical
        assert state["flight_status"] in ("escape_agotado", "hover_slm")
        # 2026-0827: el giro de cambio de estrategia tambien inyecta un
        # waypoint de desvio persistente (antes declarado en DroneState pero
        # nunca producido por ningun nodo -- ver CHANGELOG.md).
        corner = state.get("inject_corner")
        assert isinstance(corner, dict)
        assert {"x", "y", "z"} <= corner.keys()
        # El enclavamiento persiste: sin progreso horizontal medido, el escape
        # por altura no vuelve a dispararse NUNCA (antes reaparecia al ciclo
        # siguiente de cada freno).
        assert "GANAR_ALTURA" not in actions[3:]
        assert state["_escape_locked"] is True
    finally:
        service.stop()


def test_escape_lock_releases_after_real_horizontal_progress(monkeypatch):
    """El enclavamiento se levanta solo con progreso horizontal MEDIDO.

    No puede colgarse de `evasion_stuck_cycles`: el propio escape pide
    `_escape_reset`, que lo pone en cero al ciclo siguiente. Si se usara esa
    senal, cada escape pareceria haber resuelto el atasco y el tope de
    intentos consecutivos nunca se alcanzaria.
    """
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", lambda payload: (None, "", 5.0, "sin servidor SLM"))
    monkeypatch.setenv("MAX_CONSECUTIVE_ESCAPES", "1")

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        state = _base_state()
        state["obstacle_field"] = empty_field()
        state["waypoint_guidance"] = {"dist_xy": 80.0, "distance": 80.0, "bearing_err_deg": 0.0}

        state["evasion_stuck_cycles"] = 999
        state = node(state)
        assert state["next_action"] == "GANAR_ALTURA"

        # Sin progreso: se agota y enclava.
        state["evasion_stuck_cycles"] = 999
        state = node(state)
        assert state["_escape_locked"] is True

        # Con progreso horizontal real (80 -> 70m), el enclavamiento se libera
        # y el escape vuelve a estar disponible.
        state["waypoint_guidance"] = {"dist_xy": 70.0, "distance": 70.0, "bearing_err_deg": 0.0}
        state["evasion_stuck_cycles"] = 999
        state = node(state)
        assert state["next_action"] == "GANAR_ALTURA"
        assert state["_escape_locked"] is False
    finally:
        service.stop()


def test_escape_does_not_fire_when_perception_sees_an_open_corridor(monkeypatch):
    """El escape ya no es ciego a la percepcion.

    En el vuelo del 2026-0824 el dron subio 12m seguidos mientras el
    ObstacleField reportaba `DERECHA: DESPEJADO` ciclo tras ciclo: la rama de
    escape se ejecutaba antes de mirar el campo.
    """
    monkeypatch.setattr(deliberative_mod, "_query_slm_impl", lambda payload: (None, "", 5.0, "sin servidor SLM"))

    from src.agents.deliberative import make_deliberation_service, make_deliberative_node
    from src.navigation.waypoint_tracker import effective_stall_threshold

    service = make_deliberation_service()
    node = make_deliberative_node(service)
    try:
        cells = {(s, b): Cell(sector=s, band=b, occupancy=0.9, ttc_s=1.0, confidence=0.9) for s in SECTORS for b in BANDS}
        for band in BANDS:  # corredor libre a la derecha, con evidencia valida
            cells[("derecha", band)] = Cell(sector="derecha", band=band, occupancy=0.0, ttc_s=float("inf"), confidence=0.9)
        field = ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)

        state = _base_state()
        state["obstacle_field"] = field
        state["waypoint_guidance"] = {"dist_xy": 80.0, "distance": 80.0, "bearing_err_deg": 30.0}
        state["evasion_stuck_cycles"] = effective_stall_threshold()

        state = node(state)
        assert state["next_action"] != "GANAR_ALTURA"
    finally:
        service.stop()


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
