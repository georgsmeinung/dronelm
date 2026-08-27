# F3.1: Brazo de comparacion FSM (Maquina de Estados Finitos).
#
# Mismo ObstacleField, mismo espacio de macro-acciones y el mismo
# action_to_command() que usan evasive_node y deliberative_node: lo unico
# que cambia frente al brazo SLM es quien elige la etiqueta de macro-accion.
# Esto permite una comparacion limpia SLM vs FSM sobre el objetivo especifico
# del plan de tesis (tasa de exito, tiempo de reaccion, consumo computacional).
#
# reactive_node NO es esta FSM: reactive_node solo guia a waypoint sin
# evasion (se usa como tercer brazo, cota inferior). Esta FSM si evade.
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .action_map import action_to_command, compute_corner_waypoint
from src.navigation.waypoint_tracker import effective_stall_threshold, hard_stall_threshold
from src.perception import ObstacleField, empty_field, has_open_corridor

FSM_TTC_BRAKE_S = float(os.getenv("FSM_TTC_BRAKE_S", "1.5"))
FSM_TTC_AVOID_S = float(os.getenv("FSM_TTC_AVOID_S", "3.5"))
FSM_MANEUVER_DURATION_S = float(os.getenv("FSM_MANEUVER_DURATION_S", "1.5"))

# Estados de la FSM (para logging/depuracion; el "estado" real que persiste
# entre ciclos es active_maneuver + maneuver_cycles_left, igual que el brazo SLM).
STATE_CRUISE = "CRUISE"
STATE_AVOID_LEFT = "AVOID_LEFT"
STATE_AVOID_RIGHT = "AVOID_RIGHT"
STATE_CLIMB = "CLIMB"
STATE_DESCEND = "DESCEND"
STATE_BRAKE = "BRAKE"

_STATE_TO_ACTION = {
    STATE_CRUISE: "MANTENER_RUMBO",
    STATE_AVOID_LEFT: "EVADIR_IZQUIERDA",
    STATE_AVOID_RIGHT: "EVADIR_DERECHA",
    STATE_CLIMB: "GANAR_ALTURA",
    STATE_DESCEND: "PERDER_ALTURA",
    STATE_BRAKE: "FRENAR",
}

# Secuencia de estrategias de escape por atasco/bloqueo total (2026-0827, ver
# CHANGELOG.md). Antes "todo bloqueado" siempre devolvia STATE_CLIMB -- sin
# alternativa si arriba tampoco habia salida (confirmado visualmente en UE:
# el dron quedaba insistiendo dentro de la copa de un arbol, subiendo mas
# adentro en vez de salir). Se evaluo tambien RETROCEDER (retroceder por el
# camino recien recorrido) pero se descarto: agregaba ruido notable a la
# trayectoria (ver CHANGELOG.md) sin justificarse frente a la alternancia
# CLIMB/DESCEND, mas simple.
_ESCAPE_SEQUENCE = (STATE_CLIMB, STATE_DESCEND)


def _vertical_escape_state(escape_attempt_no: int) -> str:
    """Elige la estrategia de escape segun el numero de intento (0-indexado),

    alternando CLIMB -> DESCEND -> CLIMB -> ...
    """
    return _ESCAPE_SEQUENCE[escape_attempt_no % len(_ESCAPE_SEQUENCE)]


def _decide_state(
    field: ObstacleField,
    stuck_cycles: int,
    stuck_threshold: int,
    guidance: Optional[Dict[str, Any]] = None,
    escape_locked: bool = False,
    escape_attempt_no: int = 0,
) -> str:
    """Transiciones deterministas por umbral sobre el ObstacleField.

    Replica la logica tactica del router SLM (ttc_router / _fallback_decision)
    pero sin invocar ningun modelo: es la maquina de estados clasica contra la
    que se compara el brazo SLM.
    """
    # El escape vertical por atasco ya no es ciego: no dispara si la
    # percepcion ve un corredor transitable (salvo atasco duro) ni si el
    # escape esta enclavado por haberse agotado. Mismo criterio que
    # policy_router/deliberative, para que la comparacion SLM vs FSM siga
    # siendo sobre quien elige la accion y no sobre quien tiene la
    # salvaguarda mejor puesta.
    if stuck_cycles >= stuck_threshold and not escape_locked:
        hard_stuck = stuck_cycles >= hard_stall_threshold()
        if hard_stuck or not has_open_corridor(field, guidance):
            return _vertical_escape_state(escape_attempt_no)

    center_ttc = field.sector_ttc("centro")
    if center_ttc <= FSM_TTC_BRAKE_S and field.is_blocked("centro"):
        left_blocked = field.is_blocked("izquierda")
        right_blocked = field.is_blocked("derecha")
        if left_blocked and right_blocked:
            return _vertical_escape_state(escape_attempt_no)
        return STATE_BRAKE

    if field.is_blocked("centro") or center_ttc <= FSM_TTC_AVOID_S:
        left_occ = field.sector_occupancy("izquierda")
        right_occ = field.sector_occupancy("derecha")
        left_blocked = field.is_blocked("izquierda")
        right_blocked = field.is_blocked("derecha")

        if left_blocked and right_blocked:
            return _vertical_escape_state(escape_attempt_no)
        if left_blocked:
            return STATE_AVOID_RIGHT
        if right_blocked:
            return STATE_AVOID_LEFT
        return STATE_AVOID_LEFT if left_occ <= right_occ else STATE_AVOID_RIGHT

    return STATE_CRUISE


def fsm_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Nodo del brazo FSM: decide la macro-accion por umbrales sobre ObstacleField."""
    field: ObstacleField = state.get("obstacle_field") or empty_field()
    telemetry = state.get("telemetry", {}) or {}
    guidance = state.get("waypoint_guidance") or {}

    active_man = state.get("active_maneuver")
    cycles_left = int(state.get("maneuver_cycles_left", 0))
    maneuver_cmd = state.get("maneuver_command")
    if active_man and cycles_left > 0 and isinstance(maneuver_cmd, dict):
        # Persistencia de maniobra: misma anti-oscilacion que el brazo SLM.
        state["maneuver_cycles_left"] = cycles_left - 1
        state["next_action"] = active_man
        state["velocity_command"] = maneuver_cmd
        state["route"] = "fsm"
        state["flight_status"] = "fsm_maneuver"
        if cycles_left - 1 <= 0:
            state["active_maneuver"] = None
            state["maneuver_command"] = None
        return state

    stuck_threshold = effective_stall_threshold()
    stuck_cycles = int(state.get("evasion_stuck_cycles", 0))

    # Red de seguridad (2026-0824, mismo mecanismo que deliberative.py):
    # tope de intentos de CLIMB consecutivos. Sin esto, subir para escapar
    # de un atasco puede no resolverlo nunca (obstaculo genuinamente
    # imposible de superar subiendo) y el estado quedaria disparando CLIMB
    # sin techo. Se cuenta CUALQUIER CLIMB (por stuck_cycles o por bloqueo
    # lateral en ambos sectores), no solo el de stuck_cycles.
    #
    # El tope ENCLAVA: antes, al pasar a BRAKE la rama `else` ponia el
    # contador en cero y el ciclo siguiente volvia a subir -- la red de
    # seguridad se reseteaba a si misma y producia un ciclo limite
    # (CLIMB, CLIMB, CLIMB, BRAKE, CLIMB, ...) en vez de un estado terminal.
    # El enclavamiento se levanta solo cuando el atasco se resuelve de verdad
    # (stuck_cycles vuelve por debajo del umbral). A diferencia del brazo SLM,
    # aca el contador de atasco no se fuerza a cero desde el nodo, asi que
    # `stuck_cycles < stuck_threshold` ya es evidencia de progreso real.
    escape_locked = bool(state.get("_escape_locked", False))
    consecutive_escapes = int(state.get("_consecutive_escapes", 0))
    if stuck_cycles < stuck_threshold:
        escape_locked = False
        consecutive_escapes = 0

    fsm_state = _decide_state(
        field, stuck_cycles, stuck_threshold, guidance, escape_locked,
        escape_attempt_no=consecutive_escapes,
    )

    max_escapes = int(os.getenv("MAX_CONSECUTIVE_ESCAPES", "3"))
    if fsm_state in (STATE_CLIMB, STATE_DESCEND):
        consecutive_escapes += 1
        if consecutive_escapes > max_escapes:
            # ESCAPE AGOTADO (2026-0827, ver CHANGELOG.md): antes esta rama
            # pasaba a STATE_BRAKE y enclavaba para siempre -- si el
            # obstaculo era horizontal (p. ej. trabado contra ramas), subir
            # nunca acerca al waypoint, el enclave nunca se libera (solo se
            # libera con progreso horizontal medido), y el dron quedaba
            # frenando de forma indefinida hasta el timeout de la mision.
            # Mismo mecanismo que ya tenia el brazo SLM (deliberative.py,
            # F: "ESCAPE AGOTADO"): en vez de frenar sin salida, cambiar de
            # estrategia con un giro de 90 grados hacia el lado del waypoint
            # para buscar un corredor lateral. GANAR_ALTURA queda descartada
            # (enclavada) hasta que haya progreso real; los ciclos siguientes
            # caen a la evaluacion normal por TTC (_decide_state con
            # escape_locked=True se salta el bloque de atasco).
            escape_locked = True
            state["_consecutive_escapes"] = consecutive_escapes
            state["_escape_locked"] = escape_locked

            loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
            escape_duration_s = float(os.getenv("ESCAPE_MANEUVER_DURATION_S", "1.6"))
            cmd = action_to_command("GIRAR_90", guidance=guidance, telemetry=telemetry)
            side = "izquierda" if cmd["yaw_rate"] < 0 else "derecha"
            cmd["rationale"] = (
                f"FSM: escape agotado tras {max_escapes} intentos verticales (CLIMB/DESCEND alternados) "
                f"sin progreso horizontal. Girando 90° hacia la {side} para buscar corredor; escape "
                f"vertical descartado hasta que haya progreso."
            )
            state["next_action"] = "GIRAR_90"
            state["velocity_command"] = cmd
            state["route"] = "fsm"
            state["flight_status"] = "fsm_escape_agotado"
            # Desvio persistente (2026-0827, ver CHANGELOG.md): sin esto, el
            # guiado por corredor vuelve a apuntar a la misma linea bloqueada
            # apenas termina el giro -- confirmado en UE, dron trabado dentro
            # de la copa de un arbol. inject_corner ya estaba declarado en
            # DroneState pero ningun nodo lo producia.
            target_yaw = cmd.get("target_yaw")
            if target_yaw is not None:
                state["inject_corner"] = compute_corner_waypoint(telemetry, float(target_yaw), guidance=guidance)
            state["active_maneuver"] = "GIRAR_90"
            state["maneuver_cycles_left"] = max(1, round(escape_duration_s * loop_hz))
            state["maneuver_command"] = cmd
            return state
    state["_consecutive_escapes"] = consecutive_escapes
    state["_escape_locked"] = escape_locked

    action = _STATE_TO_ACTION[fsm_state]

    close_structural = field.is_blocked("centro") and field.sector_ttc("centro") <= FSM_TTC_BRAKE_S
    command = action_to_command(action, guidance=guidance, telemetry=telemetry, close_structural=close_structural)
    command["rationale"] = f"FSM: estado {fsm_state} (TTC centro={field.sector_ttc('centro'):.1f}s)"

    state["next_action"] = action
    state["velocity_command"] = command
    state["route"] = "fsm"
    state["flight_status"] = f"fsm_{fsm_state.lower()}"

    if action in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA", "GANAR_ALTURA", "PERDER_ALTURA"):
        loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
        cycles = max(1, round(FSM_MANEUVER_DURATION_S * loop_hz))
        state["active_maneuver"] = action
        state["maneuver_cycles_left"] = cycles
        state["maneuver_command"] = command
    else:
        state["active_maneuver"] = None
        state["maneuver_cycles_left"] = 0
        state["maneuver_command"] = None

    return state
