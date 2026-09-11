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
# V3b/V3c: ciclos de RETROCEDER cuando la causa es colisión invisible.
# 5 ciclos = 1 s a 5 Hz: suficiente para salir del convex hull sin alejarse demasiado.
_RETROCEDER_CYCLES = int(os.getenv("RETROCEDER_ESCAPE_CYCLES", "5"))
# C1 (Zona 2): penalización por historia de stalls laterales.
# Mínimo de intentos para confiar en la tasa de stall; por debajo, el campo óptico manda.
_TRAJ_MIN_ATTEMPTS = int(os.getenv("EVASIVE_TRAJ_MIN_ATTEMPTS", "3"))
# Tasa de stall a partir de la cual se aplica penalización a la occupancy efectiva.
_TRAJ_STALL_THRESHOLD = float(os.getenv("EVASIVE_TRAJ_STALL_THRESHOLD", "0.60"))
# Peso de la penalización: eff_occ += stall_rate * WEIGHT.
# 0.5 es suficiente para superar cualquier diferencia de occ óptica entre
# lados (los valores típicos son 0.00–0.05); no se aplica si no hay evidencia.
_TRAJ_STALL_WEIGHT = float(os.getenv("EVASIVE_TRAJ_STALL_WEIGHT", "0.50"))


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

    # V3b/V3c-VLM-REFINEMENT: colisión invisible → RETROCEDER es el único vector
    # garantizado de escape. EVADIR_IZQ/DER falla dentro de un convex hull porque
    # la malla bloquea todos los laterales desde adentro.
    # Condiciones de activación (OR):
    #   • blind_wall_event: cmd_vx > 0 pero el drone no se mueve + bf≈0 (2 ciclos).
    #     Fase de aproximación: el drone aún comanda velocidad frontal.
    #   • _stopped_cycles >= 10: el drone lleva ≥ 2 s parado sin moverse.
    #     Fase freeze: ESCANEO (cmd_vx=0) o MANTENER_RUMBO con malla que absorbe empuje.
    is_blind_collision = (
        state.get("blind_wall_event")
        or int(state.get("_stopped_cycles", 0)) >= 10
    )
    if is_blind_collision:
        action = "RETROCEDER"
        rationale = (
            f"Escape colision invisible: blind_wall={state.get('blind_wall_event')}, "
            f"parado_ciclos={state.get('_stopped_cycles', 0)}. "
            "Retroceso al vector de entrada para salir del convex hull."
        )
        command = action_to_command(action, guidance=guidance, telemetry=telemetry)
        command["rationale"] = rationale
        state["next_action"] = action
        state["velocity_command"] = command
        state["route"] = "evasive"
        state["flight_status"] = "escape_retroceso"
        state["active_maneuver"] = action
        state["maneuver_cycles_left"] = _RETROCEDER_CYCLES
        state["maneuver_command"] = command
        return state

    left_occ = field.sector_occupancy("izquierda")
    right_occ = field.sector_occupancy("derecha")
    left_ttc = field.sector_ttc("izquierda")
    right_ttc = field.sector_ttc("derecha")

    # C1 (Zona 2): occupancy efectiva con penalización por historia de stalls.
    # Cuando el campo óptico es ambiguo (malla de árbol, convex hull) los stalls
    # laterales acumulados son la única señal fiable de "ese lado ya falló N veces".
    # eff_occ += stall_rate * WEIGHT solo si hay suficientes intentos y la tasa
    # supera el umbral; si no hay datos de trayectoria, eff_occ == occ óptica.
    izq_stall = float(state.get("_traj_izq_stall_rate") or 0.0)
    izq_att   = int(state.get("_traj_izq_attempts")    or 0)
    der_stall = float(state.get("_traj_der_stall_rate") or 0.0)
    der_att   = int(state.get("_traj_der_attempts")    or 0)
    eff_left_occ  = left_occ  + (izq_stall * _TRAJ_STALL_WEIGHT
                                  if izq_stall >= _TRAJ_STALL_THRESHOLD and izq_att >= _TRAJ_MIN_ATTEMPTS
                                  else 0.0)
    eff_right_occ = right_occ + (der_stall * _TRAJ_STALL_WEIGHT
                                  if der_stall >= _TRAJ_STALL_THRESHOLD and der_att >= _TRAJ_MIN_ATTEMPTS
                                  else 0.0)

    traj_note_izq = f" [traj izq: {izq_stall:.0%}/{izq_att}int]" if izq_att >= _TRAJ_MIN_ATTEMPTS else ""
    traj_note_der = f" [traj der: {der_stall:.0%}/{der_att}int]" if der_att >= _TRAJ_MIN_ATTEMPTS else ""

    if eff_left_occ < eff_right_occ or (eff_left_occ == eff_right_occ and left_ttc >= right_ttc):
        action = "EVADIR_IZQUIERDA"
        rationale = (
            f"Evasion rapida: izquierda mas despejada "
            f"(eff_occ izq={eff_left_occ:.3f} vs der={eff_right_occ:.3f};"
            f" opt izq={left_occ:.3f} der={right_occ:.3f}){traj_note_izq}{traj_note_der}."
        )
    else:
        action = "EVADIR_DERECHA"
        rationale = (
            f"Evasion rapida: derecha mas despejada "
            f"(eff_occ der={eff_right_occ:.3f} vs izq={eff_left_occ:.3f};"
            f" opt der={right_occ:.3f} izq={left_occ:.3f}){traj_note_der}{traj_note_izq}."
        )

    # Evasión rápida: usa velocidades agresivas para corregir lateralmente de forma rápida.
    command = action_to_command(action, guidance=guidance, telemetry=telemetry, close_structural=False, aggressive=True)
    command["rationale"] = rationale

    state["next_action"] = action
    state["velocity_command"] = command
    state["route"] = "evasive"
    state["flight_status"] = "evasion_local"
    return state
