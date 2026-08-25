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
from typing import Any, Dict

from .action_map import action_to_command
from src.perception import ObstacleField, empty_field

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


def _decide_state(field: ObstacleField, stuck_cycles: int, stuck_threshold: int) -> str:
    """Transiciones deterministas por umbral sobre el ObstacleField.

    Replica la logica tactica del router SLM (ttc_router / _fallback_decision)
    pero sin invocar ningun modelo: es la maquina de estados clasica contra la
    que se compara el brazo SLM.
    """
    if stuck_cycles >= stuck_threshold:
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

    stuck_threshold = int(os.getenv("EVASION_STUCK_THRESHOLD", "10"))
    stuck_cycles = int(state.get("evasion_stuck_cycles", 0))
    fsm_state = _decide_state(field, stuck_cycles, stuck_threshold)

    # Red de seguridad (2026-0824, mismo mecanismo que deliberative.py):
    # tope de intentos de CLIMB consecutivos. Sin esto, subir para escapar
    # de un atasco puede no resolverlo nunca (obstaculo genuinamente
    # imposible de superar subiendo) y el estado quedaria disparando CLIMB
    # sin techo. Se cuenta CUALQUIER CLIMB (por stuck_cycles o por bloqueo
    # lateral en ambos sectores), no solo el de stuck_cycles.
    max_escapes = int(os.getenv("MAX_CONSECUTIVE_ESCAPES", "3"))
    consecutive_escapes = int(state.get("_consecutive_escapes", 0))
    if fsm_state == STATE_CLIMB:
        consecutive_escapes += 1
        if consecutive_escapes > max_escapes:
            fsm_state = STATE_BRAKE
    else:
        consecutive_escapes = 0
    state["_consecutive_escapes"] = consecutive_escapes

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
