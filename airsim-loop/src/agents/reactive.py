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
    """Devuelve una decision de "mantener rumbo" con velocidad por defecto.

    No consulta al LLM. Solo inspecciona la telemetria para mantener la
    altitud y proyecta una velocidad horizontal constante hacia adelante.
    """
    telemetry = state.get("telemetry") or {}
    velocity = telemetry.get("velocity", {}) if isinstance(telemetry, dict) else {}
    vz = float(velocity.get("vz", 0.0)) if isinstance(velocity, dict) else 0.0

    # Correccion simple de altitud (mantener z ~= 0) sin gastar tokens.
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
    state["velocity_command"] = command
    state["route"] = "reactive"
    return state
