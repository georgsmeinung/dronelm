# Paso 4A-bis: Maniobra Evasiva Local Rapida (brazo SLM).
# Ejecuta una correccion lateral rapida usando el ObstacleField (F1.1) en
# lugar de las detecciones YOLO que ya no existen, o continua la ejecucion
# comprometida de una macro-accion previa para evitar oscilaciones (flip-flop).
from __future__ import annotations

import os
from typing import Any, Dict

from .action_map import action_to_command
from src.perception import ObstacleField, empty_field

FSM_MANEUVER_DURATION_S = float(os.getenv("EVASIVE_MANEUVER_DURATION_S", "1.0"))


def evasive_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Caso B del router: TTC dinamico en ventana de advertencia, sin llegar a

    peligro critico. Corrige lateralmente hacia el sector con menor ocupacion
    y mayor TTC, o continua una maniobra deliberada previa (persistencia
    anti-flip-flop).
    """
    active_man = state.get("active_maneuver")
    cycles_left = int(state.get("maneuver_cycles_left", 0))
    maneuver_cmd = state.get("maneuver_command")

    telemetry = state.get("telemetry", {}) or {}

    if active_man and cycles_left > 0 and isinstance(maneuver_cmd, dict):
        import math

        orient_data = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
        yaw_raw = float(orient_data.get("yaw", 0.0)) if isinstance(orient_data, dict) else 0.0
        current_yaw_deg = math.degrees(yaw_raw)

        target_yaw_deg = maneuver_cmd.get("target_yaw")
        if target_yaw_deg is not None:
            yaw_diff = (float(target_yaw_deg) - current_yaw_deg + 180.0) % 360.0 - 180.0
            if abs(yaw_diff) <= 3.0:
                maneuver_cmd["yaw_rate"] = 0.0
                if float(maneuver_cmd.get("vx", 0.0)) < 0.5:
                    maneuver_cmd["vx"] = 0.8
            else:
                maneuver_cmd["yaw_rate"] = max(-15.0, min(15.0, 0.6 * yaw_diff))

        state["maneuver_cycles_left"] = cycles_left - 1
        state["next_action"] = active_man
        state["velocity_command"] = maneuver_cmd
        state["route"] = "evasive"
        state["flight_status"] = "evasion_persistente"
        if cycles_left - 1 <= 0:
            state["active_maneuver"] = None
            state["maneuver_command"] = None
        return state

    field: ObstacleField = state.get("obstacle_field") or empty_field()
    guidance = state.get("waypoint_guidance") or {}

    left_occ = field.sector_occupancy("izquierda")
    right_occ = field.sector_occupancy("derecha")
    left_ttc = field.sector_ttc("izquierda")
    right_ttc = field.sector_ttc("derecha")

    # Elegir el lado con menor ocupacion; a igualdad, el de mayor TTC.
    if left_occ < right_occ or (left_occ == right_occ and left_ttc >= right_ttc):
        action = "EVADIR_IZQUIERDA"
        rationale = f"Evasion rapida: izquierda mas despejada (ocup izq={left_occ:.2f} vs der={right_occ:.2f})."
    else:
        action = "EVADIR_DERECHA"
        rationale = f"Evasion rapida: derecha mas despejada (ocup der={right_occ:.2f} vs izq={left_occ:.2f})."

    # Evasión rápida: usa velocidades agresivas para corregir lateralmente de forma rápida.
    command = action_to_command(action, guidance=guidance, telemetry=telemetry, close_structural=False, aggressive=True)
    command["rationale"] = rationale

    state["next_action"] = action
    state["velocity_command"] = command
    state["route"] = "evasive"
    state["flight_status"] = "evasion_local"
    return state
