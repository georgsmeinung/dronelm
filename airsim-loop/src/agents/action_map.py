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
# Distancia (metros) del waypoint de desvio temporal que se inyecta cuando el
# escape sincronico se agota (ver compute_corner_waypoint mas abajo). Primera
# aproximacion sin medir en vuelo real (2026-0827, ver CHANGELOG.md) -- punto
# de partida razonable, no un valor calibrado.
CORNER_OFFSET_M = float(os.getenv("CORNER_OFFSET_M", "12.0"))

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
    aggressive: bool = False,
) -> Dict[str, Any]:
    """Traduce una macro-accion discreta a un comando de velocidad Body Frame.

    Es la unica funcion que decide vx/vy/vz/yaw_rate por macro-accion; todos los
    nodos de politica (deliberative, evasive, fsm, reactive) la comparten.

    Args:
        aggressive: Si True, usa velocidades mayores para evasion rapida (vx=1.2).
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
        vx_evasion = 1.2 if aggressive else (0.3 if close_structural else 0.8)
        return {
            "macro_action": action,
            "vx": vx_evasion,
            "vy": 0.0,
            "vz": vz_guidance,
            "yaw_rate": EVASION_LATERAL_YAW_RATE,
            "target_yaw": target_yaw_deg,
        }

    if action == "EVADIR_IZQUIERDA":
        target_yaw_deg = _manhattan_snap_yaw(current_yaw_deg, -90.0)
        vx_evasion = 1.2 if aggressive else (0.3 if close_structural else 0.8)
        return {
            "macro_action": action,
            "vx": vx_evasion,
            "vy": 0.0,
            "vz": vz_guidance,
            "yaw_rate": -EVASION_LATERAL_YAW_RATE,
            "target_yaw": target_yaw_deg,
        }

    if action == "GANAR_ALTURA":
        # 2026-0824: se retira `vy=0.5` (deriva lateral constante sin ninguna
        # justificacion en una macro-accion de ASCENSO) y `yaw_rate=0.0`.
        # Juntas producian el peor caso medido en vuelo: el dron subia 12m
        # derivando 0.5 m/s de costado -- lo que ALEJABA el waypoint en el
        # plano XY, la misma metrica que decide si el atasco se resolvio, y
        # con el rumbo congelado en -5.3 grados mientras el objetivo estaba a
        # -67 grados. El escape se alimentaba a si mismo. Ahora sube en el
        # lugar y aprovecha el ascenso para alinear el rumbo al waypoint.
        return {
            "macro_action": action,
            "vx": 0.0,
            "vy": 0.0,
            "vz": -EVASION_UP_SPEED,
            "yaw_rate": yaw_rate_guidance,
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
        # El giro de exploracion elige el lado por el error de rumbo al
        # waypoint. Antes era siempre +90 (derecha): en el vuelo del
        # 2026-0824 eso mando al dron a girar a la DERECHA con el waypoint 68
        # grados a la IZQUIERDA, en contra de la correccion que el guiado
        # venia aplicando. Sin guidance (llamador sin mision) se conserva el
        # comportamiento historico: +90.
        bearing_err_deg = float(guidance.get("bearing_err_deg", 0.0))
        turn_sign = -1.0 if bearing_err_deg < 0.0 else 1.0
        target_yaw_deg = _manhattan_snap_yaw(current_yaw_deg, 90.0 * turn_sign)
        return {
            "macro_action": action,
            "vx": 0.0,
            "vy": 0.0,
            "vz": 0.0,
            "yaw_rate": 20.0 * turn_sign,
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


def compute_corner_waypoint(
    telemetry: Optional[Dict[str, Any]],
    target_yaw_deg: float,
    guidance: Optional[Dict[str, Any]] = None,
    offset_m: float = CORNER_OFFSET_M,
) -> Dict[str, float]:
    """Calcula un waypoint de desvio temporal (2026-0827, ver CHANGELOG.md).

    Se usa cuando el escape sincronico se agota (GIRAR_90 de cambio de
    estrategia, en fsm.py y deliberative.py): un solo punto, a `offset_m`
    metros de la posicion actual, en la direccion del giro ya decidido
    (`target_yaw_deg`, calculado igual que el comando GIRAR_90 via
    `_manhattan_snap_yaw`). Reutiliza esa misma direccion en vez de recalcular
    el lado por separado, para que el giro y el desvio apunten al mismo lugar.

    La altitud se toma del waypoint objetivo original (`guidance.target_wp`)
    si esta disponible, para no arrastrar la cota alcanzada por un escape
    vertical previo (GANAR_ALTURA/PERDER_ALTURA) al punto de desvio.
    """
    pos = (telemetry or {}).get("position", {}) if isinstance(telemetry, dict) else {}
    x = float(pos.get("x", 0.0))
    y = float(pos.get("y", 0.0))
    z = float(pos.get("z", -10.0))

    target_wp = (guidance or {}).get("target_wp") if isinstance(guidance, dict) else None
    if isinstance(target_wp, dict) and "z" in target_wp:
        z = float(target_wp.get("z", z))

    yaw_rad = math.radians(target_yaw_deg)
    return {
        "x": round(x + offset_m * math.cos(yaw_rad), 2),
        "y": round(y + offset_m * math.sin(yaw_rad), 2),
        "z": round(z, 2),
    }
