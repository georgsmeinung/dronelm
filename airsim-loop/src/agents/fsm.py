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

from .action_map import action_to_command
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
STATE_BRAKE = "BRAKE"

_STATE_TO_ACTION = {
    STATE_CRUISE: "MANTENER_RUMBO",
    STATE_AVOID_LEFT: "EVADIR_IZQUIERDA",
    STATE_AVOID_RIGHT: "EVADIR_DERECHA",
    STATE_CLIMB: "GANAR_ALTURA",
    STATE_BRAKE: "FRENAR",
}


def _decide_state(
    field: ObstacleField,
    stuck_cycles: int,
    stuck_threshold: int,
    guidance: Optional[Dict[str, Any]] = None,
    escape_locked: bool = False,
) -> str:
    """Transiciones deterministas por umbral sobre el ObstacleField.

    Replica la logica tactica del router SLM (ttc_router / _fallback_decision)
    pero sin invocar ningun modelo: es la maquina de estados clasica contra la
    que se compara el brazo SLM.
    """
    # El CLIMB por atasco ya no es ciego: no dispara si la percepcion ve un
    # corredor transitable (salvo atasco duro) ni si el escape esta enclavado
    # por haberse agotado. Mismo criterio que policy_router/deliberative, para
    # que la comparacion SLM vs FSM siga siendo sobre quien elige la accion y
    # no sobre quien tiene la salvaguarda mejor puesta.
    if stuck_cycles >= stuck_threshold and not escape_locked:
        hard_stuck = stuck_cycles >= hard_stall_threshold()
        if hard_stuck or not has_open_corridor(field, guidance):
            return STATE_CLIMB

    center_ttc = field.sector_ttc("centro")
    if center_ttc <= FSM_TTC_BRAKE_S and field.is_blocked("centro"):
        left_blocked = field.is_blocked("izquierda")
        right_blocked = field.is_blocked("derecha")
        if left_blocked and right_blocked:
            return STATE_CLIMB
        return STATE_BRAKE

    if field.is_blocked("centro") or center_ttc <= FSM_TTC_AVOID_S:
        left_occ = field.sector_occupancy("izquierda")
        right_occ = field.sector_occupancy("derecha")
        left_blocked = field.is_blocked("izquierda")
        right_blocked = field.is_blocked("derecha")

        if left_blocked and right_blocked:
            return STATE_CLIMB
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

    fsm_state = _decide_state(field, stuck_cycles, stuck_threshold, guidance, escape_locked)

    max_escapes = int(os.getenv("MAX_CONSECUTIVE_ESCAPES", "3"))
    if fsm_state == STATE_CLIMB:
        consecutive_escapes += 1
        if consecutive_escapes > max_escapes:
            fsm_state = STATE_BRAKE
            escape_locked = True
    state["_consecutive_escapes"] = consecutive_escapes
    state["_escape_locked"] = escape_locked

    action = _STATE_TO_ACTION[fsm_state]

    close_structural = field.is_blocked("centro") and field.sector_ttc("centro") <= FSM_TTC_BRAKE_S
    command = action_to_command(action, guidance=guidance, telemetry=telemetry, close_structural=close_structural)
    command["rationale"] = f"FSM: estado {fsm_state} (TTC centro={field.sector_ttc('centro'):.1f}s)"
    if fsm_state == STATE_BRAKE and consecutive_escapes > max_escapes:
        command["rationale"] = f"FSM: escape agotado tras {max_escapes} CLIMB consecutivos sin resolver el atasco. Frenando."

    state["next_action"] = action
    state["velocity_command"] = command
    state["route"] = "fsm"
    state["flight_status"] = f"fsm_{fsm_state.lower()}"

    if action in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA", "GANAR_ALTURA"):
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
