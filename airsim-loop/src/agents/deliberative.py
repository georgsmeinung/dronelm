# Paso 4B: Cerebro Deliberativo (SLM local).
# Esta ruta se activa cuando el Gatekeeper detecta un obstaculo inminente
# en el sector central. El SLM local recibe un resumen textual de la
# escena y devuelve un macro-comando ("esquivar por la derecha", etc.).
from __future__ import annotations

import json
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


LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:1234/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "not-needed-for-local")
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi-3")

DEFAULT_FORWARD_SPEED = float(os.getenv("REACTIVE_FORWARD_SPEED", "2.0"))
EVASION_LATERAL_SPEED = float(os.getenv("EVASION_LATERAL_SPEED", "2.5"))
EVASION_BACK_SPEED = float(os.getenv("EVASION_BACK_SPEED", "1.0"))
EVASION_UP_SPEED = float(os.getenv("EVASION_UP_SPEED", "1.0"))

VALID_ACTIONS = {
    "MANTENER_RUMBO",
    "EVADIR_IZQUIERDA",
    "EVADIR_DERECHA",
    "GANAR_ALTURA",
    "PERDER_ALTURA",
    "FRENAR",
}


SYSTEM_PROMPT = (
    "Eres el cerebro deliberativo de un dron autonomo. Recibiras un resumen "
    "de la escena con obstaculos detectados y su sector (Izquierda, Centro, "
    "Derecha) y proximidad (Inminente, Cerca, Lejos). Tu mision es proponer "
    "UNA unica macro-accion segura. Responde UNICAMENTE con un objeto JSON "
    "valido con esta forma exacta: "
    '{"macro_action": "<valor>", "vx": <float>, "vy": <float>, "vz": <float>, '
    '"yaw_rate": <float>, "rationale": "<texto corto>"}. '
    "Valores permitidos para macro_action: "
    + ", ".join(VALID_ACTIONS) + ". "
    "Reglas: si el obstaculo esta en el Centro y es Inminente, evita por el "
    "lado con menos obstaculos; si todo el frente esta bloqueado, considera "
    "GANAR_ALTURA o FRENAR. Evita colisiones. Salida SOLO JSON."
)


def _build_user_prompt(obstacles: List[Dict[str, Any]], telemetry: Dict[str, Any]) -> str:
    if not obstacles:
        scene = "Sin obstaculos detectados."
    else:
        scene_lines = []
        for o in obstacles:
            scene_lines.append(
                f"- {o.get('object', 'objeto')} en sector {o.get('sector', '?')} "
                f"(proximidad {o.get('proximity', '?')}, "
                f"distancia {o.get('distance_m', '?')}, "
                f"confianza {o.get('confidence', '?')})"
            )
        scene = "\n".join(scene_lines)
    velocity = telemetry.get("velocity", {}) if isinstance(telemetry, dict) else {}
    return (
        "Resumen de la escena:\n"
        f"{scene}\n\n"
        "Telemetria actual:\n"
        f"- posicion: {telemetry.get('position', {})}\n"
        f"- velocidad: {velocity}\n"
        f"- orientacion: {telemetry.get('orientation', {})}\n\n"
        "Devuelve solo el JSON con la macro-accion y los vectores de velocidad."
    )


def _fallback_decision(obstacles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Heuristica determinista por si el SLM no esta disponible o falla."""
    if not obstacles:
        return {
            "macro_action": "MANTENER_RUMBO",
            "vx": DEFAULT_FORWARD_SPEED,
            "vy": 0.0,
            "vz": 0.0,
            "yaw_rate": 0.0,
            "rationale": "Fallback: sin obstaculos.",
        }

    front = [o for o in obstacles if o.get("sector") == "Centro"]
    left = [o for o in obstacles if o.get("sector") == "Izquierda"]
    right = [o for o in obstacles if o.get("sector") == "Derecha"]

    if front:
        # Bloqueo frontal: si un lateral esta libre, evadir; si no, subir.
        left_min = min((o.get("distance_m") or 1e9 for o in left), default=1e9)
        right_min = min((o.get("distance_m") or 1e9 for o in right), default=1e9)
        if right_min >= left_min:
            return {
                "macro_action": "EVADIR_DERECHA",
                "vx": DEFAULT_FORWARD_SPEED * 0.5,
                "vy": EVASION_LATERAL_SPEED,
                "vz": 0.0,
                "yaw_rate": -0.2,
                "rationale": "Fallback: bloqueo central, lateral derecho libre.",
            }
        return {
            "macro_action": "EVADIR_IZQUIERDA",
            "vx": DEFAULT_FORWARD_SPEED * 0.5,
            "vy": -EVASION_LATERAL_SPEED,
            "vz": 0.0,
            "yaw_rate": 0.2,
            "rationale": "Fallback: bloqueo central, lateral izquierdo libre.",
        }

    if left and not right:
        return {
            "macro_action": "EVADIR_DERECHA",
            "vx": DEFAULT_FORWARD_SPEED,
            "vy": EVASION_LATERAL_SPEED * 0.6,
            "vz": 0.0,
            "yaw_rate": 0.0,
            "rationale": "Fallback: obstaculo izquierdo, abrir a la derecha.",
        }
    if right and not left:
        return {
            "macro_action": "EVADIR_IZQUIERDA",
            "vx": DEFAULT_FORWARD_SPEED,
            "vy": -EVASION_LATERAL_SPEED * 0.6,
            "vz": 0.0,
            "yaw_rate": 0.0,
            "rationale": "Fallback: obstaculo derecho, abrir a la izquierda.",
        }

    return {
        "macro_action": "MANTENER_RUMBO",
        "vx": DEFAULT_FORWARD_SPEED,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": 0.0,
        "rationale": "Fallback: sin bloqueo central.",
    }


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_decision(raw: str) -> Optional[Dict[str, Any]]:
    """Extrae el primer objeto JSON valido del texto del SLM."""
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
    try:
        return {
            "macro_action": macro,
            "vx": float(data.get("vx", 0.0)),
            "vy": float(data.get("vy", 0.0)),
            "vz": float(data.get("vz", 0.0)),
            "yaw_rate": float(data.get("yaw_rate", 0.0)),
            "rationale": str(data.get("rationale", "")).strip() or "Sin rationale.",
        }
    except Exception:
        return None


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
    """Nodo deliberativo: consulta al SLM y traduce su salida a un comando."""
    obstacles = state.get("detected_obstacles", []) or []
    telemetry = state.get("telemetry", {}) or {}

    prompt = _build_user_prompt(obstacles, telemetry)
    decision = _query_slm(prompt) or _fallback_decision(obstacles)

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
