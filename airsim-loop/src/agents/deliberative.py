# Paso 4B: Cerebro Deliberativo (SLM local).
# Esta ruta se activa cuando el Gatekeeper detecta un obstaculo inminente
# en el sector central. El SLM local recibe un resumen textual de la
# escena y devuelve un macro-comando ("esquivar por la derecha", etc.).
from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "ollama")
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")

DEFAULT_FORWARD_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "2.0"))
EVASION_FORWARD_SPEED = float(os.getenv("EVASION_FORWARD_SPEED", "0.5"))
EVASION_LATERAL_SPEED = float(os.getenv("EVASION_LATERAL_SPEED", "1.2"))
EVASION_BACK_SPEED = float(os.getenv("EVASION_BACK_SPEED", "1.0"))
EVASION_UP_SPEED = float(os.getenv("EVASION_UP_SPEED", "1.5"))

VALID_ACTIONS = {
    "MANTENER_RUMBO",
    "EVADIR_IZQUIERDA",
    "EVADIR_DERECHA",
    "GANAR_ALTURA",
    "PERDER_ALTURA",
    "FRENAR",
}

# --------------------------------------------------------------------------- #
# Mapeo Cinemático Determinista (Body Frame con ForwardOnly)                 #
# --------------------------------------------------------------------------- #
ACTION_VELOCITY_MAP: Dict[str, Dict[str, float]] = {
    "MANTENER_RUMBO": {
        "vx": DEFAULT_FORWARD_SPEED,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": 0.0,
    },
    "EVADIR_DERECHA": {
        "vx": EVASION_FORWARD_SPEED,
        "vy": EVASION_LATERAL_SPEED,
        "vz": 0.0,
        "yaw_rate": 0.0,
    },
    "EVADIR_IZQUIERDA": {
        "vx": EVASION_FORWARD_SPEED,
        "vy": -EVASION_LATERAL_SPEED,
        "vz": 0.0,
        "yaw_rate": 0.0,
    },
    "GANAR_ALTURA": {
        "vx": 0.4,
        "vy": 0.0,
        "vz": -EVASION_UP_SPEED,
        "yaw_rate": 0.0,
    },
    "PERDER_ALTURA": {
        "vx": 0.4,
        "vy": 0.0,
        "vz": EVASION_UP_SPEED,
        "yaw_rate": 0.0,
    },
    "FRENAR": {
        "vx": 0.0,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": 0.0,
    },
}


SYSTEM_PROMPT = (
    "Sos el cerebro deliberativo de un dron autonomo. Tu mision es seleccionar UNA macro-accion segura "
    "analizando la Evaluacion de Sectores (IZQUIERDA, CENTRO, DERECHA) y los obstaculos criticos.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido con este formato exacto:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicacion breve de 1 linea>"}\n\n'
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: Si el sector CENTRO esta DESPEJADO.\n"
    "- EVADIR_IZQUIERDA: Si CENTRO esta BLOQUEADO o PARCIAL y el sector IZQUIERDA tiene menos peligro que DERECHA.\n"
    "- EVADIR_DERECHA: Si CENTRO esta BLOQUEADO o PARCIAL y el sector DERECHA tiene menos peligro que IZQUIERDA.\n"
    "- GANAR_ALTURA: Si todo el frente (IZQUIERDA, CENTRO, DERECHA) esta BLOQUEADO.\n"
    "- FRENAR: Si el peligro es critico en todas las direcciones y no hay espacio de maniobra.\n"
    "- PERDER_ALTURA: Solo si es seguro y necesario para la mision.\n\n"
    "Reglas estrictas:\n"
    "1. Nunca elijas evadir hacia un sector BLOQUEADO si el otro sector esta DESPEJADO.\n"
    "2. Si CENTRO esta BLOQUEADO y solo un lateral esta DESPEJADO, elige ESE lateral.\n"
    "3. Salida estrictamente JSON sin texto adicional."
)


def _summarize_sectors(obstacles: List[Dict[str, Any]]) -> str:
    """Genera una evaluacion agregada y limpia de los sectores espaciales."""
    sectors = {
        "Izquierda": {"Inminente": 0, "Cerca": 0, "Lejos": 0},
        "Centro": {"Inminente": 0, "Cerca": 0, "Lejos": 0},
        "Derecha": {"Inminente": 0, "Cerca": 0, "Lejos": 0},
    }

    critical_obstacles = []

    for o in obstacles:
        sec = o.get("sector", "Centro")
        if sec not in sectors:
            sec = "Centro"
        prox = o.get("proximity", "Lejos")
        if prox in sectors[sec]:
            sectors[sec][prox] += 1
        else:
            sectors[sec]["Lejos"] += 1

        dist = o.get("distance_m")
        if dist is not None and (dist < 25.0 or prox in ("Inminente", "Cerca")):
            critical_obstacles.append(o)

    def sector_status(counts: Dict[str, int]) -> str:
        if counts["Inminente"] > 0:
            return f"BLOQUEADO ({counts['Inminente']} inminente, {counts['Cerca']} cerca, {counts['Lejos']} lejos)"
        elif counts["Cerca"] > 0:
            return f"PARCIAL ({counts['Cerca']} cerca, {counts['Lejos']} lejos)"
        elif counts["Lejos"] > 0:
            return f"DESPEJADO (0 cercanos, {counts['Lejos']} lejanos)"
        else:
            return "DESPEJADO (0 obstaculos)"

    lines = [
        "Evaluacion de Sectores:",
        f"- IZQUIERDA: {sector_status(sectors['Izquierda'])}",
        f"- CENTRO: {sector_status(sectors['Centro'])}",
        f"- DERECHA: {sector_status(sectors['Derecha'])}",
    ]

    if critical_obstacles:
        lines.append("\nObstaculos Criticos (< 25m):")
        critical_sorted = sorted(
            critical_obstacles,
            key=lambda x: (
                0 if x.get("proximity") == "Inminente" else 1 if x.get("proximity") == "Cerca" else 2,
                float(x.get("distance_m") if x.get("distance_m") is not None else 999.0),
            ),
        )
        for co in critical_sorted[:8]:
            dist_val = co.get("distance_m")
            dist_str = f"{dist_val:.1f}m" if isinstance(dist_val, (int, float)) else "N/A"
            lines.append(f"- {co.get('object', 'objeto')} en sector {co.get('sector', '?')} ({co.get('proximity', '?')}, {dist_str})")
    else:
        lines.append("\nObstaculos Criticos (< 25m): Ninguno.")

    return "\n".join(lines)


def _build_user_prompt(
    obstacles: List[Dict[str, Any]],
    telemetry: Dict[str, Any],
    guidance: Optional[Dict[str, Any]] = None,
) -> str:
    sector_summary = _summarize_sectors(obstacles)

    pos = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    vel = telemetry.get("velocity", {}) if isinstance(telemetry, dict) else {}

    altitude = abs(float(pos.get("z", 0.0))) if isinstance(pos, dict) and "z" in pos else 0.0
    vx = float(vel.get("vx", 0.0)) if isinstance(vel, dict) and "vx" in vel else 0.0
    vy = float(vel.get("vy", 0.0)) if isinstance(vel, dict) and "vy" in vel else 0.0
    speed = math.hypot(vx, vy)

    wp_info = ""
    if guidance and guidance.get("target_wp"):
        wp = guidance["target_wp"]
        label = wp.get("label", "WP")
        dist = guidance.get("distance", 0.0)
        err = guidance.get("bearing_err_deg", 0.0)
        direction = "Izquierda" if err < -10.0 else "Derecha" if err > 10.0 else "Frente"
        wp_info = (
            "\nObjetivo de Navegacion:\n"
            f"- Destino: {label} [{wp.get('x',0):.1f}, {wp.get('y',0):.1f}, {wp.get('z',0):.1f}]\n"
            f"- Distancia: {dist:.1f} m | Direccion hacia la meta: {direction} ({err:+.0f}°)\n"
        )

    return (
        f"{sector_summary}\n\n"
        "Telemetria:\n"
        f"- Altitud: {altitude:.1f} m\n"
        f"- Velocidad horizontal: {speed:.1f} m/s\n"
        f"{wp_info}\n"
        "Selecciona la macro-accion correspondiente. Devuelve SOLO el JSON."
    )


def _fallback_decision(
    obstacles: List[Dict[str, Any]],
    guidance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Heuristica determinista orientada al waypoint cuando el SLM no esta disponible."""
    if not obstacles:
        vels = ACTION_VELOCITY_MAP["MANTENER_RUMBO"]
        return {
            "macro_action": "MANTENER_RUMBO",
            "vx": vels["vx"],
            "vy": vels["vy"],
            "vz": vels["vz"],
            "yaw_rate": vels["yaw_rate"],
            "rationale": "Fallback: sin obstaculos.",
        }

    front = [o for o in obstacles if o.get("sector") == "Centro"]
    left = [o for o in obstacles if o.get("sector") == "Izquierda"]
    right = [o for o in obstacles if o.get("sector") == "Derecha"]

    if front:
        # Preferir evadir hacia el lado donde queda el waypoint si no está bloqueado
        target_dir = (guidance.get("bearing_err_deg") or 0.0) if guidance else 0.0
        left_imminent = any(o.get("proximity") == "Inminente" for o in left)
        right_imminent = any(o.get("proximity") == "Inminente" for o in right)

        if target_dir < -10.0 and not left_imminent:
            macro = "EVADIR_IZQUIERDA"
            rationale = "Fallback: bloqueo central, evadiendo hacia la izquierda (rumbo al waypoint)."
        elif target_dir > 10.0 and not right_imminent:
            macro = "EVADIR_DERECHA"
            rationale = "Fallback: bloqueo central, evadiendo hacia la derecha (rumbo al waypoint)."
        elif len(left) <= len(right) and not left_imminent:
            macro = "EVADIR_IZQUIERDA"
            rationale = "Fallback: bloqueo central, lateral izquierdo con menor densidad."
        elif not right_imminent:
            macro = "EVADIR_DERECHA"
            rationale = "Fallback: bloqueo central, lateral derecho con menor densidad."
        else:
            macro = "GANAR_ALTURA"
            rationale = "Fallback: ambos laterales bloqueados, ganando altura de seguridad."
    elif left and not right:
        macro = "EVADIR_DERECHA"
        rationale = "Fallback: obstaculos a la izquierda, derivando a la derecha."
    elif right and not left:
        macro = "EVADIR_IZQUIERDA"
        rationale = "Fallback: obstaculo derecho, abrir a la izquierda."
    else:
        macro = "MANTENER_RUMBO"
        rationale = "Fallback: sin bloqueo central."

    vels = ACTION_VELOCITY_MAP[macro]
    return {
        "macro_action": macro,
        "vx": vels["vx"],
        "vy": vels["vy"],
        "vz": vels["vz"],
        "yaw_rate": vels["yaw_rate"],
        "rationale": rationale,
    }


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_decision(raw: str) -> Optional[Dict[str, Any]]:
    """Extrae el primer objeto JSON valido del texto del SLM y aplica el mapeo cinematico."""
    if not raw:
        return None
    match = _JSON_RE.search(raw)
    if not match:
        return None
    candidate = match.group(0)
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    macro = str(data.get("macro_action", "")).upper().strip()
    if macro not in VALID_ACTIONS:
        return None

    vels = ACTION_VELOCITY_MAP.get(macro, ACTION_VELOCITY_MAP["MANTENER_RUMBO"])
    rationale = str(data.get("rationale", "")).strip() or f"Decision SLM: {macro}."

    return {
        "macro_action": macro,
        "vx": vels["vx"],
        "vy": vels["vy"],
        "vz": vels["vz"],
        "yaw_rate": vels["yaw_rate"],
        "rationale": rationale,
    }


def _query_slm(prompt: str) -> Optional[Dict[str, Any]]:
    """Consulta al servidor compatible con OpenAI (LM Studio u Ollama)."""
    if OpenAI is None:
        return None
    try:
        client = OpenAI(base_url=LOCAL_LLM_URL, api_key=LOCAL_LLM_API_KEY)
        completion = client.chat.completions.create(
            model=LOCAL_LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        raw = completion.choices[0].message.content or ""
        return _parse_decision(raw)
    except Exception as exc:
        print(f"[deliberative] SLM no disponible ({exc}). Usando fallback.")
        return None


def deliberative_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Nodo deliberativo (Paso 5): Freno de seguridad (Hover) y consulta al SLM."""
    state["flight_status"] = "hover_slm"

    obstacles = state.get("detected_obstacles", []) or []
    telemetry = state.get("telemetry", {}) or {}
    guidance = state.get("waypoint_guidance")

    prompt = _build_user_prompt(obstacles, telemetry, guidance)
    decision = _query_slm(prompt) or _fallback_decision(obstacles, guidance)

    state["next_action"] = decision["macro_action"]
    state["velocity_command"] = decision
    state["route"] = "deliberative"
    state.setdefault("deliberations", []).append(
        {
            "prompt": prompt,
            "decision": decision,
        }
    )
    return state

