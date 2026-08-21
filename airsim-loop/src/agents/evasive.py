from __future__ import annotations

import os
from typing import Any, Dict
import math

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

DEFAULT_FORWARD_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "2.0"))
EVASION_FORWARD_SPEED = float(os.getenv("EVASION_FORWARD_SPEED", "0.8"))
EVASION_LATERAL_SPEED = float(os.getenv("EVASION_LATERAL_SPEED", "0.8"))


def evasive_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Caso B: Maniobra Evasiva Local Directa o Ejecución Persistente de Maniobra Táctica.

    Ejecuta una corrección física lateral o continúa la ejecución comprometida
    de una macro-acción deliberada por el SLM para evitar oscilaciones (flip-flop).
    """
    # 1. Si hay una maniobra deliberativa activa persistente, continuar su ejecución
    active_man = state.get("active_maneuver")
    cycles_left = int(state.get("maneuver_cycles_left", 0))
    maneuver_cmd = state.get("maneuver_command")

    telemetry = state.get("telemetry", {}) or {}
    orient_data = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    yaw_raw = float(orient_data.get("yaw", 0.0)) if isinstance(orient_data, dict) else 0.0
    current_yaw_deg = math.degrees(yaw_raw)

    if active_man and cycles_left > 0 and isinstance(maneuver_cmd, dict):
        target_yaw_deg = maneuver_cmd.get("target_yaw_deg") or maneuver_cmd.get("target_yaw")
        if target_yaw_deg is not None:
            # Control proporcional de rumbo acotado en grados: cesa el giro al alinearse con la calle
            yaw_diff = (float(target_yaw_deg) - current_yaw_deg + 180.0) % 360.0 - 180.0
            if abs(yaw_diff) <= 3.0:
                maneuver_cmd["yaw_rate"] = 0.0
                # Alineado con la calle lateral: impulsar avance para recorrerla.
                # Si el vx sigue siendo el mínimo de seguridad (0.3) o menos, aumentar
                # ahora que el frente ya no apunta al edificio.
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

    roi_detections = state.get("roi_detections", []) or state.get("detections", []) or []
    roi_info = state.get("roi_info", (0, 0, 1080, 720))
    roi_w = roi_info[2] if len(roi_info) >= 3 and roi_info[2] > 0 else 1080

    guidance = state.get("waypoint_guidance") or {}
    vz = float(guidance.get("vz", 0.0))
    abs_err = abs(float(guidance.get("bearing_err_deg", 0.0)))

    STRUCTURAL_NAMES = {"building", "wall", "house", "roof", "tower", "bridge", "structure"}

    left_weight = 0.0
    right_weight = 0.0

    # Determinar distribucion y peso de peligro a la izquierda vs derecha del ROI
    for det in roi_detections:
        bbox = det.get("bbox", [0, 0, 0, 0]) if isinstance(det, dict) else getattr(det, "bbox", [0, 0, 0, 0])
        obj_name = str(det.get("object", "") if isinstance(det, dict) else getattr(det, "object", "")).lower()
        is_struct = obj_name in STRUCTURAL_NAMES or (isinstance(det, dict) and det.get("category") == "structural")
        weight = 3.0 if is_struct else 1.0

        if len(bbox) == 4:
            cx = (bbox[0] + bbox[2]) / 2.0
            if cx < (roi_w / 2.0):
                left_weight += weight
            else:
                right_weight += weight

    # Si hay mas peligro/estructuras a la izquierda, virar a la derecha; y viceversa
    if left_weight >= right_weight:
        action = "EVADIR_DERECHA"
        command_yaw = 15.0
        vy = 0.3
        rationale = f"Evasión rápida: mayor peligro a la izq ({left_weight:.0f}) vs der ({right_weight:.0f}). Avanzando por pasillo derecho."
    else:
        action = "EVADIR_IZQUIERDA"
        command_yaw = -15.0
        vy = -0.3
        rationale = f"Evasión rápida: mayor peligro a la der ({right_weight:.0f}) vs izq ({left_weight:.0f}). Avanzando por pasillo izquierdo."

    command = {
        "macro_action": action,
        "vx": 1.2,
        "vy": vy,
        "vz": vz,
        "yaw_rate": float(command_yaw),
        "rationale": rationale,
    }

    state["next_action"] = action
    state["velocity_command"] = command
    state["route"] = "evasive"
    state["flight_status"] = "evasion_local"
    return state
