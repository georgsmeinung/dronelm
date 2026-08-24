# Fuente unica de verdad para la cinematica de cada macro-accion.
# Todos los nodos que emiten un comando de velocidad (deliberative, evasive,
# fsm, reactive) pasan por action_to_command() en lugar de definir vx/vy/vz
# por su cuenta. Evita que una macro-accion tenga dos definiciones distintas
# segun quien la ejecute.
from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional

DEFAULT_FORWARD_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "2.0"))
EVASION_LATERAL_YAW_RATE = float(os.getenv("EVASION_LATERAL_YAW_RATE", "15.0"))
EVASION_UP_SPEED = float(os.getenv("EVASION_UP_SPEED", "1.5"))
EVASION_DOWN_SPEED = float(os.getenv("EVASION_DOWN_SPEED", "0.8"))

VALID_ACTIONS = {
    "MANTENER_RUMBO",
    "EVADIR_IZQUIERDA",
    "EVADIR_DERECHA",
    "GANAR_ALTURA",
    "PERDER_ALTURA",
    "FRENAR",
    "GIRAR_90",
}


def _manhattan_snap_yaw(current_yaw_deg: float, delta_deg: float) -> float:
    """Redondea el rumbo objetivo al eje mas cercano de la cuadricula (multiplo de 90)."""
    raw_yaw = current_yaw_deg + delta_deg
    snapped = round(raw_yaw / 90.0) * 90.0
    return (snapped + 180.0) % 360.0 - 180.0


def action_to_command(
    action: str,
    guidance: Optional[Dict[str, Any]] = None,
    telemetry: Optional[Dict[str, Any]] = None,
    close_structural: bool = False,
) -> Dict[str, Any]:
    """Traduce una macro-accion discreta a un comando de velocidad Body Frame.

    Es la unica funcion que decide vx/vy/vz/yaw_rate por macro-accion; todos los
    nodos de politica (deliberative, evasive, fsm, reactive) la comparten.
    """
    guidance = guidance or {}
    telemetry = telemetry or {}

    orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    current_yaw_deg = math.degrees(float(orient.get("yaw", 0.0))) if isinstance(orient, dict) else 0.0

    vz_guidance = float(guidance.get("vz", 0.0))
    yaw_rate_guidance = float(guidance.get("yaw_rate", 0.0))

    if action == "MANTENER_RUMBO":
        return {
            "macro_action": action,
            "vx": float(guidance.get("vx", DEFAULT_FORWARD_SPEED)),
            "vy": 0.0,
            "vz": vz_guidance,
            "yaw_rate": yaw_rate_guidance,
            "target_yaw": None,
        }

    if action == "EVADIR_DERECHA":
        target_yaw_deg = _manhattan_snap_yaw(current_yaw_deg, 90.0)
        return {
            "macro_action": action,
            "vx": 0.3 if close_structural else 0.8,
            "vy": 0.0,
            "vz": vz_guidance,
            "yaw_rate": EVASION_LATERAL_YAW_RATE,
            "target_yaw": target_yaw_deg,
        }

    if action == "EVADIR_IZQUIERDA":
        target_yaw_deg = _manhattan_snap_yaw(current_yaw_deg, -90.0)
        return {
            "macro_action": action,
            "vx": 0.3 if close_structural else 0.8,
            "vy": 0.0,
            "vz": vz_guidance,
            "yaw_rate": -EVASION_LATERAL_YAW_RATE,
            "target_yaw": target_yaw_deg,
        }

    if action == "GANAR_ALTURA":
        return {
            "macro_action": action,
            "vx": 0.0,
            "vy": 0.5,
            "vz": -EVASION_UP_SPEED,
            "yaw_rate": 0.0,
            "target_yaw": None,
        }

    if action == "PERDER_ALTURA":
        return {
            "macro_action": action,
            "vx": 1.0,
            "vy": 0.0,
            "vz": EVASION_DOWN_SPEED,
            "yaw_rate": 0.0,
            "target_yaw": None,
        }

    if action == "GIRAR_90":
        target_yaw_deg = _manhattan_snap_yaw(current_yaw_deg, 90.0)
        return {
            "macro_action": action,
            "vx": 0.0,
            "vy": 0.0,
            "vz": 0.0,
            "yaw_rate": 20.0,
            "target_yaw": target_yaw_deg,
        }

    # FRENAR y cualquier accion desconocida: parar en el lugar.
    return {
        "macro_action": "FRENAR",
        "vx": 0.0,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": 0.0,
        "target_yaw": None,
    }
