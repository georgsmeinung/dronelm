from __future__ import annotations

import os
from typing import Any, Dict

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

DEFAULT_FORWARD_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "2.0"))
EVASION_FORWARD_SPEED = float(os.getenv("EVASION_FORWARD_SPEED", "0.5"))
EVASION_LATERAL_SPEED = float(os.getenv("EVASION_LATERAL_SPEED", "1.2"))


def evasive_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Caso B: Maniobra Evasiva Local Directa (2.0s < TTC <= 5.0s).

    Ejecuta una corrección física simple lateral (izquierda o derecha) sin
    detener el dron ni llamar al SLM, reduciendo el avance frontal para evitar colisión.
    """
    roi_detections = state.get("roi_detections", []) or state.get("detections", []) or []
    roi_info = state.get("roi_info", (0, 0, 1080, 720))
    roi_w = roi_info[2] if len(roi_info) >= 3 and roi_info[2] > 0 else 1080

    guidance = state.get("waypoint_guidance") or {}
    yaw_rate = float(guidance.get("yaw_rate", 0.0))
    vz = float(guidance.get("vz", 0.0))
    abs_err = abs(float(guidance.get("bearing_err_deg", 0.0)))

    left_count = 0
    right_count = 0

    # Determinar distribucion de obstaculos a la izquierda vs derecha del ROI
    for det in roi_detections:
        bbox = det.get("bbox", [0, 0, 0, 0]) if isinstance(det, dict) else getattr(det, "bbox", [0, 0, 0, 0])
        if len(bbox) == 4:
            cx = (bbox[0] + bbox[2]) / 2.0
            if cx < (roi_w / 2.0):
                left_count += 1
            else:
                right_count += 1

    # Si hay mas obstaculos a la izquierda, evadir a la derecha; y viceversa
    if left_count >= right_count:
        action = "EVADIR_DERECHA"
        vy = EVASION_LATERAL_SPEED
        rationale = f"Evasion local rapida: {left_count} obs a la izq vs {right_count} a la der. Desplazando a la derecha y manteniendo rumbo WP."
    else:
        action = "EVADIR_IZQUIERDA"
        vy = -EVASION_LATERAL_SPEED
        rationale = f"Evasion local rapida: {right_count} obs a la der vs {left_count} a la izq. Desplazando a la izquierda y manteniendo rumbo WP."

    # Si el desvio hacia el waypoint es grande (> 60°), priorizar pivot turn hacia el WP
    if abs_err > 60.0:
        vx = 0.0
        vy = 0.0
    else:
        vx = EVASION_FORWARD_SPEED

    command = {
        "macro_action": action,
        "vx": vx,
        "vy": vy,
        "vz": vz,
        "yaw_rate": yaw_rate,
        "rationale": rationale,
    }

    state["next_action"] = action
    state["velocity_command"] = command
    state["route"] = "evasive"
    state["flight_status"] = "evasion_local"
    return state
