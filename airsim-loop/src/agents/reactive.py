# Paso 4A: Reflejo rapido (control reactivo).
# Ruta de computo casi nulo: cuando el Gatekeeper considera que el camino
# esta despejado, el planificador reactivo simplemente mantiene el rumbo
# por defecto y devuelve un comando de velocidad neutro/avance.
from __future__ import annotations

import os
from typing import Any, Dict

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

# Velocidad por defecto en el eje X (marco NED: positivo = hacia adelante).
DEFAULT_FORWARD_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "2.0"))


def reactive_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Nodo Reactivo de Guiado Nominal: Cuando el camino visual está despejado,

    orienta y desplaza al dron hacia el waypoint activo de la misión.
    """
    guidance = state.get("waypoint_guidance") or {}
    is_completed = state.get("mission_completed", False) or guidance.get("is_completed", False)

    if is_completed:
        command = {
            "macro_action": "FRENAR",
            "vx": 0.0,
            "vy": 0.0,
            "vz": 0.0,
            "yaw_rate": 0.0,
            "rationale": "Misión completada: todos los waypoints alcanzados.",
        }
        state["next_action"] = "FRENAR"
        state["flight_status"] = "mision_completada"
    elif guidance and guidance.get("target_wp"):
        wp = guidance["target_wp"]
        label = wp.get("label", "WP")
        dist = guidance.get("distance", 0.0)
        err = guidance.get("bearing_err_deg", 0.0)
        command = {
            "macro_action": "MANTENER_RUMBO",
            "vx": guidance.get("vx", DEFAULT_FORWARD_SPEED),
            "vy": guidance.get("vy", 0.0),
            "vz": guidance.get("vz", 0.0),
            "yaw_rate": float(guidance.get("yaw_rate", 0.0)),
            "target_yaw": None,
            "rationale": f"Navegando hacia {label} a dist={dist:.1f}m (desvío={err:+.0f}°, giro={guidance.get('yaw_rate', 0.0):+.1f}°/s).",
        }
        state["next_action"] = "MANTENER_RUMBO"
        state["flight_status"] = "vuelo_waypoint"
    else:
        # Fallback sin waypoints: mantener rumbo frontal
        telemetry = state.get("telemetry") or {}
        velocity = telemetry.get("velocity", {}) if isinstance(telemetry, dict) else {}
        vz = float(velocity.get("vz", 0.0)) if isinstance(velocity, dict) else 0.0
        vz_correction = -0.1 * vz
        command = {
            "macro_action": "MANTENER_RUMBO",
            "vx": DEFAULT_FORWARD_SPEED,
            "vy": 0.0,
            "vz": vz_correction,
            "yaw_rate": 0.0,
            "rationale": "Camino despejado: se mantiene el rumbo por defecto.",
        }
        state["next_action"] = "MANTENER_RUMBO"
        state["flight_status"] = "vuelo"

    state["velocity_command"] = command
    state["route"] = "reactive"
    return state

