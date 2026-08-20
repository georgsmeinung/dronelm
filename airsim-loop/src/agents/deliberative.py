# Paso 4B: Cerebro Deliberativo (SLM local).
# Esta ruta se activa cuando el Gatekeeper detecta un obstaculo inminente
# en el sector central. El SLM local recibe un resumen textual de la
# escena y devuelve un macro-comando ("esquivar por la derecha", etc.).
from __future__ import annotations

import json
import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

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
EVASION_FORWARD_SPEED = float(os.getenv("EVASION_FORWARD_SPEED", "0.8"))
EVASION_LATERAL_SPEED = float(os.getenv("EVASION_LATERAL_SPEED", "0.8"))
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
        "vx": 2.5,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": 20.0,
    },
    "EVADIR_IZQUIERDA": {
        "vx": 2.5,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": -20.0,
    },
    "GANAR_ALTURA": {
        "vx": 1.0,
        "vy": 0.0,
        "vz": -EVASION_UP_SPEED,
        "yaw_rate": 0.0,
    },
    "PERDER_ALTURA": {
        "vx": 1.0,
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
    "Sos el cerebro deliberativo táctico de un dron autónomo en una CUADRÍCULA URBANA (Manhattan Grid). "
    "Tu misión es rodear manzanas y estructuras bloqueantes navegando por las calles y pasajes transversales libres.\n\n"
    "Estrategia Urbana en Cuadrícula:\n"
    "- Si el frente está bloqueado por una manzana/edificio, tu objetivo es desviarte 90° hacia la calle transversal despejada (EVADIR_IZQUIERDA o EVADIR_DERECHA).\n"
    "- El dron avanzará por la calle lateral a velocidad continua para superar la fachada del edificio.\n"
    "- Si ambos laterales están bloqueados en un callejón sin salida, selecciona GANAR_ALTURA para sobrevolar la estructura.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido con este formato exacto:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicacion breve de 1 linea>"}\n\n'
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: Si el sector CENTRO esta DESPEJADO de estructuras en la calle.\n"
    "- EVADIR_IZQUIERDA: Desvío ortogonal a la izquierda por la calle transversal abierta.\n"
    "- EVADIR_DERECHA: Desvío ortogonal a la derecha por la calle transversal abierta.\n"
    "- GANAR_ALTURA: Si frente y laterales están cerrados, elevarse para sobrevolar la estructura.\n"
    "- FRENAR: Solo en peligro inminente insalvable en todas direcciones.\n\n"
    "Reglas estrictas:\n"
    "1. Prefiere la calle lateral que coincida con la dirección general de la meta siempre que no tenga edificios bloqueantes.\n"
    "2. Salida estrictamente JSON sin texto adicional."
)


def _summarize_sectors(obstacles: List[Dict[str, Any]]) -> str:
    structural_names = {"building", "wall", "house", "roof", "tower", "bridge", "structure"}

    sec_data = {
        "Izquierda": {"status": "DESPEJADO", "dist": 999.0},
        "Centro": {"status": "DESPEJADO", "dist": 999.0},
        "Derecha": {"status": "DESPEJADO", "dist": 999.0},
    }

    for o in obstacles:
        sec = o.get("sector")
        if sec not in sec_data:
            continue
        prox = o.get("proximity", "Lejos")
        dist = o.get("distance_m", 999.0)
        dist_val = float(dist) if dist is not None else 999.0
        obj = str(o.get("object", "")).lower()
        is_struct = obj in structural_names or o.get("category") == "structural"

        if prox in ("Inminente", "Cerca") or dist_val < 8.0:
            if is_struct:
                sec_data[sec]["status"] = f"BLOQUEADO POR ESTRUCTURA ({dist_val:.1f}m)"
            else:
                sec_data[sec]["status"] = f"OBSTACULO CERCANO ({dist_val:.1f}m)"
            sec_data[sec]["dist"] = min(sec_data[sec]["dist"], dist_val)

    lines = [
        "SECTORES VISUALES:",
        f"- IZQUIERDA: {sec_data['Izquierda']['status']}",
        f"- CENTRO: {sec_data['Centro']['status']}",
        f"- DERECHA: {sec_data['Derecha']['status']}",
    ]
    return "\n".join(lines)


def _build_user_prompt(
    obstacles: List[Dict[str, Any]],
    telemetry: Dict[str, Any],
    guidance: Optional[Dict[str, Any]] = None,
) -> str:
    sector_summary = _summarize_sectors(obstacles)

    pos = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    altitude = abs(float(pos.get("z", 0.0))) if isinstance(pos, dict) and "z" in pos else 0.0

    wp_str = "Meta: Frente (0m)"
    if guidance and guidance.get("target_wp"):
        wp = guidance["target_wp"]
        label = wp.get("label", "WP")
        dist = guidance.get("distance", 0.0)
        err = guidance.get("bearing_err_deg", 0.0)
        direction = "Izquierda" if err < -10.0 else "Derecha" if err > 10.0 else "Frente"
        wp_str = f"Meta ({label}): {dist:.1f}m hacia {direction} ({err:+.0f}°)"

    return (
        f"{sector_summary}\n\n"
        f"OBJETIVO Y ALTITUD:\n"
        f"- {wp_str}\n"
        f"- Altitud actual: {altitude:.1f}m (Cota segura: 10.0m)\n\n"
        "INSTRUCCION:\n"
        "Elige la macro_action ('EVADIR_IZQUIERDA', 'EVADIR_DERECHA', 'GANAR_ALTURA' o 'MANTENER_RUMBO').\n"
        "Responde SOLO con este JSON:\n"
        '{"macro_action": "<ACCION>", "rationale": "<motivo corto>"}'
    )


def _fallback_decision(
    obstacles: List[Dict[str, Any]],
    guidance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Heuristica determinista priorizando la evasión de edificios cuando el SLM no responde."""
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

    structural_names = {"building", "wall", "house", "roof", "tower", "bridge", "structure"}

    def calc_danger(obs_list: List[Dict[str, Any]]) -> float:
        score = 0.0
        for o in obs_list:
            is_struct = str(o.get("object", "")).lower() in structural_names or o.get("category") == "structural"
            mult = 4.0 if is_struct else 1.0
            prox = o.get("proximity", "Lejos")
            if prox == "Inminente":
                score += 10.0 * mult
            elif prox == "Cerca":
                score += 4.0 * mult
            else:
                score += 1.0 * mult
        return score

    front = [o for o in obstacles if o.get("sector") == "Centro"]
    left = [o for o in obstacles if o.get("sector") == "Izquierda"]
    right = [o for o in obstacles if o.get("sector") == "Derecha"]

    front_danger = calc_danger(front)
    left_danger = calc_danger(left)
    right_danger = calc_danger(right)

    target_dir = (guidance.get("bearing_err_deg") or 0.0) if guidance else 0.0

    if front_danger > 0:
        # Hay peligro frontal: elegir el lateral con menor peligro de estructuras
        left_has_struct = any(str(o.get("object", "")).lower() in structural_names for o in left)
        right_has_struct = any(str(o.get("object", "")).lower() in structural_names for o in right)

        if left_danger < right_danger and not left_has_struct:
            macro = "EVADIR_IZQUIERDA"
            rationale = f"Fallback: bloqueo frontal, lateral izquierdo despejado de estructuras (peligro izq={left_danger:.0f} vs der={right_danger:.0f})."
        elif right_danger < left_danger and not right_has_struct:
            macro = "EVADIR_DERECHA"
            rationale = f"Fallback: bloqueo frontal, lateral derecho despejado de estructuras (peligro der={right_danger:.0f} vs izq={left_danger:.0f})."
        elif target_dir < -10.0 and left_danger <= right_danger:
            macro = "EVADIR_IZQUIERDA"
            rationale = "Fallback: bloqueo frontal, evadiendo a la izquierda rumbo al waypoint."
        elif target_dir > 10.0 and right_danger <= left_danger:
            macro = "EVADIR_DERECHA"
            rationale = "Fallback: bloqueo frontal, evadiendo a la derecha rumbo al waypoint."
        elif left_danger <= right_danger:
            macro = "EVADIR_IZQUIERDA"
            rationale = f"Fallback: evasión izquierda (densidad izq={left_danger:.0f} vs der={right_danger:.0f})."
        elif right_danger < left_danger:
            macro = "EVADIR_DERECHA"
            rationale = f"Fallback: evasión derecha (densidad der={right_danger:.0f} vs izq={left_danger:.0f})."
        else:
            macro = "GANAR_ALTURA"
            rationale = "Fallback: ambos laterales comprometidos por estructuras, ganando altura de seguridad."
    elif left_danger > right_danger and left_danger >= 4.0:
        macro = "EVADIR_DERECHA"
        rationale = "Fallback: estructuras a la izquierda, abriendo a la derecha."
    elif right_danger > left_danger and right_danger >= 4.0:
        macro = "EVADIR_IZQUIERDA"
        rationale = "Fallback: estructuras a la derecha, abriendo a la izquierda."
    else:
        macro = "MANTENER_RUMBO"
        rationale = "Fallback: camino frontal despejado de estructuras."

    vels = ACTION_VELOCITY_MAP[macro]
    return {
        "macro_action": macro,
        "vx": vels["vx"],
        "vy": vels["vy"],
        "vz": vels["vz"],
        "yaw_rate": vels["yaw_rate"],
        "rationale": rationale,
    }


def _parse_decision(raw: str) -> Optional[Dict[str, Any]]:
    """Extrae la decisión del texto del SLM de manera ultratolerante a Markdown o texto conversacional."""
    if not raw:
        return None

    cleaned = raw.strip()
    # 1. Remover bloques markdown ```json o ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    # 2. Intentar buscar el bloque {...}
    match = re.search(r"\{[\s\S]*\}", cleaned)
    data = None
    if match:
        candidate = match.group(0)
        try:
            data = json.loads(candidate)
        except Exception:
            try:
                fixed = candidate.replace("'", '"')
                data = json.loads(fixed)
            except Exception:
                data = None

    # 3. Si json.loads falló, extraer directamente con Regex
    macro = ""
    rationale = ""
    if isinstance(data, dict):
        macro = str(data.get("macro_action", "")).upper().strip()
        rationale = str(data.get("rationale", "")).strip()

    if not macro or macro not in VALID_ACTIONS:
        m_action = re.search(r'["\']?macro_action["\']?\s*:\s*["\']([A-Z_]+)["\']', raw, re.IGNORECASE)
        if m_action:
            cand_macro = m_action.group(1).upper().strip()
            if cand_macro in VALID_ACTIONS:
                macro = cand_macro
        else:
            for act in VALID_ACTIONS:
                if act in raw.upper():
                    macro = act
                    break

    if not macro or macro not in VALID_ACTIONS:
        return None

    if not rationale:
        m_rat = re.search(r'["\']?rationale["\']?\s*:\s*["\']([^"\'\n\r]+)["\']', raw, re.IGNORECASE)
        if m_rat:
            rationale = m_rat.group(1).strip()
        else:
            rationale = f"Decisión SLM: {macro}."

    vels = ACTION_VELOCITY_MAP.get(macro, ACTION_VELOCITY_MAP["MANTENER_RUMBO"])
    return {
        "macro_action": macro,
        "vx": vels["vx"],
        "vy": vels["vy"],
        "vz": vels["vz"],
        "yaw_rate": vels["yaw_rate"],
        "rationale": rationale,
    }


def _query_slm(prompt: str) -> Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]:
    """Consulta al servidor compatible con OpenAI (LM Studio u Ollama).

    Retorna: (parsed_decision, raw_response, latency_ms, error_message)
    """
    if OpenAI is None:
        return None, "", 0.0, "Libreria openai no instalada"
    t0 = time.time()
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
        latency_ms = (time.time() - t0) * 1000.0
        raw = completion.choices[0].message.content or ""
        parsed = _parse_decision(raw)
        return parsed, raw, latency_ms, None
    except Exception as exc:
        latency_ms = (time.time() - t0) * 1000.0
        err_msg = str(exc)
        print(f"[deliberative] SLM no disponible ({err_msg}). Usando fallback.")
        return None, "", latency_ms, err_msg


def deliberative_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Nodo deliberativo (Paso 5): Freno de seguridad (Hover), consulta al SLM y guiado motriz."""
    state["flight_status"] = "hover_slm"

    obstacles = state.get("detected_obstacles", []) or []
    telemetry = state.get("telemetry", {}) or {}
    guidance = state.get("waypoint_guidance") or {}

    yaw_rate = float(guidance.get("yaw_rate", 0.0))
    vz = float(guidance.get("vz", 0.0))

    prompt = _build_user_prompt(obstacles, telemetry, guidance)
    parsed_decision, raw_response, latency_ms, err = _query_slm(prompt)
    is_fallback = parsed_decision is None
    decision = parsed_decision or _fallback_decision(obstacles, guidance)

    # Inyección de guiado al waypoint y control de curvatura anti-cangrejeo
    macro = decision.get("macro_action", "MANTENER_RUMBO")

    target_wp = guidance.get("target_wp") or {}
    target_z = float(target_wp.get("z", -10.0))
    pos_data = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    current_z = float(pos_data.get("z", 0.0)) if isinstance(pos_data, dict) else 0.0

    # Ascenso continuo hacia la cota objetivo de la misión (z negativo en NED = altitud positiva)
    vz_cmd = vz
    if current_z > target_z + 1.0:
        vz_cmd = -0.8

    orient_data = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    yaw_raw = float(orient_data.get("yaw", 0.0)) if isinstance(orient_data, dict) else 0.0
    current_yaw_deg = math.degrees(yaw_raw)

    pos_data = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    curr_x = float(pos_data.get("x", 0.0))
    curr_y = float(pos_data.get("y", 0.0))
    curr_z = float(pos_data.get("z", -10.0))

    if macro == "EVADIR_DERECHA":
        # Desvío ortogonal a +90° alineado con la cuadrícula de la ciudad (Manhattan Grid Snap)
        raw_yaw = current_yaw_deg + 90.0
        snapped_yaw = round(raw_yaw / 90.0) * 90.0
        target_yaw_deg = (snapped_yaw + 180.0) % 360.0 - 180.0
        yaw_rad = math.radians(target_yaw_deg)
        decision["target_yaw"] = target_yaw_deg
        decision["target_yaw_deg"] = target_yaw_deg
        decision["vx"] = 2.5
        decision["vy"] = 0.0
        decision["vz"] = vz_cmd
        decision["yaw_rate"] = 15.0
        state["inject_corner"] = {
            "x": round(curr_x + 25.0 * math.cos(yaw_rad), 2),
            "y": round(curr_y + 25.0 * math.sin(yaw_rad), 2),
            "z": curr_z,
            "label": "CORNER_DER",
        }
    elif macro == "EVADIR_IZQUIERDA":
        # Desvío ortogonal a -90° alineado con la cuadrícula de la ciudad (Manhattan Grid Snap)
        raw_yaw = current_yaw_deg - 90.0
        snapped_yaw = round(raw_yaw / 90.0) * 90.0
        target_yaw_deg = (snapped_yaw + 180.0) % 360.0 - 180.0
        yaw_rad = math.radians(target_yaw_deg)
        decision["target_yaw"] = target_yaw_deg
        decision["target_yaw_deg"] = target_yaw_deg
        decision["vx"] = 2.5
        decision["vy"] = 0.0
        decision["vz"] = vz_cmd
        decision["yaw_rate"] = -15.0
        state["inject_corner"] = {
            "x": round(curr_x + 25.0 * math.cos(yaw_rad), 2),
            "y": round(curr_y + 25.0 * math.sin(yaw_rad), 2),
            "z": curr_z,
            "label": "CORNER_IZQ",
        }
    elif macro == "GANAR_ALTURA":
        decision["target_yaw"] = None
        decision["vx"] = 1.0
        decision["vy"] = 0.0
        decision["vz"] = -1.5
        decision["yaw_rate"] = yaw_rate
    elif macro == "PERDER_ALTURA":
        decision["target_yaw"] = None
        decision["vx"] = 1.0
        decision["vy"] = 0.0
        decision["vz"] = 0.8
        decision["yaw_rate"] = yaw_rate
    elif macro == "MANTENER_RUMBO":
        decision["target_yaw"] = None
        decision["vx"] = DEFAULT_FORWARD_SPEED
        decision["vy"] = 0.0
        decision["vz"] = vz_cmd
        decision["yaw_rate"] = yaw_rate

    deliberations_list = state.setdefault("deliberations", [])
    entry_id = len(deliberations_list) + 1

    deliberation_entry = {
        "id": entry_id,
        "timestamp": time.time(),
        "model": LOCAL_LLM_MODEL_NAME,
        "system_prompt": SYSTEM_PROMPT,
        "prompt": prompt,
        "raw_response": raw_response if not is_fallback else f"Fallback activado: {err or 'Formato JSON inválido'}",
        "macro_action": decision.get("macro_action", "FRENAR"),
        "rationale": decision.get("rationale", ""),
        "decision": decision,
        "is_fallback": is_fallback,
        "latency_ms": round(latency_ms, 1),
    }
    deliberations_list.append(deliberation_entry)
    state["route"] = "deliberative"
    state["next_action"] = macro
    state["velocity_command"] = decision

    # Persistencia Táctica de Maniobra en Cuadrícula (5 ciclos para recorrer la calle transversal)
    if macro in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA", "GANAR_ALTURA"):
        state["active_maneuver"] = macro
        state["maneuver_cycles_left"] = 5
        state["maneuver_command"] = decision
    else:
        state["active_maneuver"] = None
        state["maneuver_cycles_left"] = 0
        state["maneuver_command"] = None

    return state

