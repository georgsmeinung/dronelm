# Paso 4B: Cerebro Deliberativo (VLM / SLM local).
# Esta ruta se activa cuando el Gatekeeper detecta un obstaculo inminente
# en el sector central. El VLM local recibe el fotograma anotado junto con
# un resumen textual de la escena y devuelve un macro-comando.
# Si VLM_VISION_ENABLED es False, se degrada a modo texto puro (SLM).
from __future__ import annotations

import base64
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
VLM_VISION_ENABLED = os.getenv("VLM_VISION_ENABLED", "true").lower() == "true"
VLM_IMAGE_MAX_SIZE = int(os.getenv("VLM_IMAGE_MAX_SIZE", "384"))
VLM_FRAME_HISTORY_SIZE = int(os.getenv("VLM_FRAME_HISTORY_SIZE", "4"))

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
        "vx": 0.5,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": 20.0,
    },
    "EVADIR_IZQUIERDA": {
        "vx": 0.5,
        "vy": 0.0,
        "vz": 0.0,
        "yaw_rate": -20.0,
    },
    "GANAR_ALTURA": {
        "vx": 0.0,   # No avanzar hacia la pared durante la subida
        "vy": 0.5,   # Deslizamiento lateral suave para alejarse del obstáculo
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


SAFE_MARGIN_METERS = float(os.getenv("SAFE_MARGIN_METERS", "1.0"))

# --------------------------------------------------------------------------- #
# System Prompts: Texto Puro (SLM) y Visión Directa (VLM)                    #
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT_TEXT = (
    "Sos el cerebro deliberativo táctico de un dron autónomo en una cuadrícula urbana (Manhattan Grid).\n"
    "Tu objetivo principal es lograr un vuelo suave, fluido y seguro hacia el waypoint general.\n\n"
    "Reglas de navegación:\n"
    "1. Trayectoria Libre y Dirección al Waypoint: Elige MANTENER_RUMBO únicamente si la trayectoria hacia el frente en la dirección general del waypoint deseado está libre de estructuras.\n"
    "2. Evasión Proactiva por Calles Libres: Si el frente está bloqueado por una estructura, evalúa los laterales. "
    "Elige EVADIR_IZQUIERDA o EVADIR_DERECHA únicamente si hay una calle transversal o pasaje despejado en esa dirección.\n"
    "3. Bloqueo Total (Callejón sin salida): Si el frente está bloqueado y ambos laterales también están cerrados por estructuras (edificios/paredes), "
    "debes elegir GANAR_ALTURA para sobrevolar el obstáculo de manera suave, en lugar de intentar girar lateralmente contra las paredes.\n"
    "4. Peligro Inminente: Si estás en peligro crítico inminente en todas las direcciones, elige FRENAR.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicacion breve basada en la trayectoria y suavidad>"}\n\n'
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: Frente y rumbo al waypoint despejados.\n"
    "- EVADIR_IZQUIERDA: Calle transversal libre a la izquierda.\n"
    "- EVADIR_DERECHA: Calle transversal libre a la derecha.\n"
    "- GANAR_ALTURA: Frente y laterales bloqueados por estructuras (subir).\n"
    "- FRENAR: Peligro crítico en todas direcciones.\n\n"
    "Reglas estrictas:\n"
    f"1. No elijas MANTENER_RUMBO si hay una estructura a menos de {SAFE_MARGIN_METERS} metros al frente.\n"
    "2. Si estás rodeado de estructuras de cerca, prioriza GANAR_ALTURA para sobrevolarlas.\n"
    "3. Salida estrictamente JSON sin texto adicional."
)

SYSTEM_PROMPT_VISION = (
    "Sos el cerebro deliberativo táctico de un dron autónomo en una cuadrícula urbana (Manhattan Grid).\n"
    "Tu objetivo principal es lograr un vuelo suave, fluido y seguro hacia el waypoint general.\n\n"
    "Reglas de navegación y suavidad:\n"
    "1. Trayectoria Libre y Dirección al Waypoint: Prioriza trazar un rumbo (MANTENER_RUMBO) "
    "únicamente si ves una trayectoria libre hacia el frente y en la dirección general del waypoint deseado.\n"
    "2. Evasión Proactiva por Calles Libres: Si el frente está obstruido por una estructura, evalúa los laterales. "
    "Solo elige EVADIR_IZQUIERDA o EVADIR_DERECHA si ves claramente una calle transversal o pasillo libre y abierto en esa dirección.\n"
    "3. Bloqueo Total (Callejón sin salida): Si el frente está bloqueado y no hay una calle transversal visiblemente despejada a los lados "
    "(ambos laterales cerrados por paredes/edificios), debes elegir GANAR_ALTURA de inmediato para sobrevolar la estructura en lugar de girar en círculos contra las paredes.\n"
    "4. Peligro Inminente: Si estás en una situación de peligro inminente y necesitas detenerte a evaluar, elige FRENAR.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicacion breve basada en la trayectoria y suavidad>"}\n\n'
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: Frente y rumbo al waypoint despejados.\n"
    "- EVADIR_IZQUIERDA: Calle transversal libre visible a la izquierda.\n"
    "- EVADIR_DERECHA: Calle transversal libre visible a la derecha.\n"
    "- GANAR_ALTURA: Frente y ambos lados bloqueados por estructuras (callejón sin salida).\n"
    "- FRENAR: Peligro crítico inmediato en todas las direcciones.\n\n"
    "Reglas estrictas:\n"
    f"1. No elijas MANTENER_RUMBO si hay una estructura a menos de {SAFE_MARGIN_METERS} metros al frente.\n"
    "2. Evita giros innecesarios o alternantes si no hay una vía de escape abierta. Si estás rodeado, gana altura.\n"
    "3. Salida estrictamente JSON sin texto adicional."
)

# Alias de compatibilidad: se selecciona según la configuración
SYSTEM_PROMPT = SYSTEM_PROMPT_VISION if VLM_VISION_ENABLED else SYSTEM_PROMPT_TEXT


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
    stuck_cycles: int = 0,
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

    # Contexto de estado de evasión para que el LLM tome mejores decisiones
    stuck_note = ""
    if stuck_cycles >= 5:
        stuck_note = (
            f"\n- AVISO: el dron lleva {stuck_cycles} ciclos evasivos sin progresar. "
            "Si los 3 sectores están bloqueados, elige GANAR_ALTURA en lugar de seguir girando."
        )

    return (
        f"{sector_summary}\n\n"
        f"OBJETIVO Y ALTITUD:\n"
        f"- {wp_str}\n"
        f"- Altitud actual: {altitude:.1f}m (Cota segura: 10.0m){stuck_note}\n\n"
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
        front_has_struct = any(str(o.get("object", "")).lower() in structural_names for o in front)

        # Callejón sin salida: estructuras en los 3 sectores → ganar altura directamente
        if front_has_struct and left_has_struct and right_has_struct:
            macro = "GANAR_ALTURA"
            rationale = "Fallback: estructuras en frente, izquierda Y derecha. Callejón sin salida. Ganando altura."
        elif left_danger < right_danger and not left_has_struct:
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


def _encode_frame_base64(frame: Any, max_size: int = VLM_IMAGE_MAX_SIZE) -> Optional[str]:
    """Codifica un frame numpy (H,W,3 BGR) a base64 JPEG para la API multimodal.

    Redimensiona a max_size en el lado mayor para reducir tokens visuales
    y latencia sin perder información espacial crítica.
    """
    if frame is None:
        return None
    try:
        # pyrefly: ignore [missing-import]
        import cv2
        h, w = frame.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Codificar como JPEG con calidad moderada (reduce tamaño ~5x vs PNG)
        success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not success:
            return None
        return base64.b64encode(buffer).decode("utf-8")
    except Exception as exc:
        print(f"[deliberative] Error codificando frame a base64: {exc}")
        return None


def _query_slm(
    prompt: str,
    images_b64: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]:
    """Consulta al servidor compatible con OpenAI (LM Studio u Ollama).

    Si images_b64 contiene imágenes y VLM_VISION_ENABLED es True, envía un
    mensaje multimodal con la secuencia temporal de fotogramas (t-3...t)
    junto al prompt textual.

    Retorna: (parsed_decision, raw_response, latency_ms, error_message)
    """
    if OpenAI is None:
        return None, "", 0.0, "Libreria openai no instalada"
    t0 = time.time()
    try:
        client = OpenAI(base_url=LOCAL_LLM_URL, api_key=LOCAL_LLM_API_KEY)

        # Construir mensaje del usuario: multimodal o solo texto
        if VLM_VISION_ENABLED and images_b64:
            total_frames = len(images_b64)
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]

            for i, img_b64 in enumerate(images_b64):
                delta = total_frames - 1 - i
                frame_label = f"t-{delta}" if delta > 0 else "t (actual)"
                user_content.append({"type": "text", "text": f"[Fotograma {frame_label}]:"})
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{img_b64}",
                        },
                    }
                )
            system_prompt = SYSTEM_PROMPT_VISION
        else:
            user_content = prompt
            system_prompt = SYSTEM_PROMPT_TEXT

        completion = client.chat.completions.create(
            model=LOCAL_LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=200,
            timeout=8.0,
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
    print("[Deliberativo] -> Iniciando nodo deliberativo...")
    state["flight_status"] = "hover_slm"

    # --- ESCAPE DE DEADLOCK POR ALTURA ---
    # Si el drone lleva N ciclos consecutivos en modo evasivo/deliberativo sin progresar
    # (building omnidireccional), subir directamente sin consultar al LLM.
    STUCK_THRESHOLD = int(os.getenv("EVASION_STUCK_THRESHOLD", "10"))
    stuck_cycles = int(state.get("evasion_stuck_cycles", 0))
    if stuck_cycles >= STUCK_THRESHOLD:
        print(
            f"[Deliberativo] -> ESCAPE POR ALTURA: drone atascado {stuck_cycles} ciclos "
            "sin progresar. Forzando GANAR_ALTURA sin consultar al LLM."
        )
        climb_decision = {
            "macro_action": "GANAR_ALTURA",
            "vx": 0.0,   # No avanzar hacia la pared durante la subida
            "vy": 0.5,   # Deslizamiento lateral para alejarse del obstáculo
            "vz": -1.5,
            "yaw_rate": 0.0,
            "rationale": f"Escape de deadlock: {stuck_cycles} ciclos bloqueado. Subiendo para superar el obstáculo.",
        }
        state["next_action"] = "GANAR_ALTURA"
        state["velocity_command"] = climb_decision
        state["route"] = "deliberative"
        state["flight_status"] = "escape_altura"
        state["active_maneuver"] = "GANAR_ALTURA"
        state["maneuver_cycles_left"] = 8  # Ciclos extra para ganar altura suficiente
        state["maneuver_command"] = climb_decision
        state["evasion_stuck_cycles"] = 0  # Resetear el contador
        state["_escape_reset"] = True       # Flag para main.py: no re-incrementar
        return state

    obstacles = state.get("detected_obstacles", []) or []
    telemetry = state.get("telemetry", {}) or {}
    guidance = state.get("waypoint_guidance") or {}

    yaw_rate = float(guidance.get("yaw_rate", 0.0))
    vz = float(guidance.get("vz", 0.0))

    prompt = _build_user_prompt(obstacles, telemetry, guidance, stuck_cycles=stuck_cycles)

    # Codificar la secuencia temporal de fotogramas anotados para el VLM
    images_b64: Optional[List[str]] = None
    if VLM_VISION_ENABLED:
        print("[Deliberativo] -> Preparando codificación de frames para VLM...")
        frame_history = state.get("frame_history") or []
        if not frame_history:
            current = state.get("annotated_image") if state.get("annotated_image") is not None else state.get("rgb_image")
            frame_history = [current] if current is not None else []

        print(f"[Deliberativo] -> Codificando historial de {len(frame_history)} frames a base64...")
        encoded_list = []
        for idx, frame in enumerate(frame_history):
            enc = _encode_frame_base64(frame)
            if enc:
                encoded_list.append(enc)
        if encoded_list:
            images_b64 = encoded_list
        print(f"[Deliberativo] -> Codificación terminada. {len(encoded_list)} frames listos.")

    print(f"[Deliberativo] -> Enviando petición al LLM (Url: {LOCAL_LLM_URL}, Modelo: {LOCAL_LLM_MODEL_NAME})...")
    parsed_decision, raw_response, latency_ms, err = _query_slm(prompt, images_b64=images_b64)
    print(f"[Deliberativo] -> Petición al LLM terminada. Latencia: {latency_ms:.1f}ms | Error: {err}")
    is_fallback = parsed_decision is None
    decision = parsed_decision or _fallback_decision(obstacles, guidance)

    # Determinar si hay una estructura críticamente cercana en el centro
    structural_names = {"building", "wall", "house", "roof", "tower", "bridge", "structure"}
    close_structural = any(
        o.get("sector") == "Centro"
        and (str(o.get("object", "")).lower() in structural_names or o.get("category") == "structural")
        and o.get("distance_m") is not None
        and float(o.get("distance_m")) < SAFE_MARGIN_METERS
        for o in obstacles
    )

    # Override programático de seguridad: Prohibir MANTENER_RUMBO si hay una estructura
    # a menos de SAFE_MARGIN_METERS en frente, PERO solo cuando hay riesgo real:
    # - TTC < infinito (el drone se acerca a la estructura), O
    # - altitud < SAFE_ALT_FOR_OVERRIDE (todavía dentro del rango de colisión vertical).
    # A alta altitud con TTC=inf el drone ya está sobre el peligro real y el LLM puede decidir libremente.
    SAFE_ALT_FOR_OVERRIDE = float(os.getenv("SAFE_ALT_FOR_OVERRIDE", "20.0"))
    pos_data_ov = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    altitude_now = abs(float(pos_data_ov.get("z", 0.0))) if isinstance(pos_data_ov, dict) else 0.0
    ttc_now = float(state.get("estimated_ttc", float("inf")))
    override_active = close_structural and (ttc_now < float("inf") or altitude_now < SAFE_ALT_FOR_OVERRIDE)

    macro_candidate = decision.get("macro_action", "MANTENER_RUMBO")
    if macro_candidate == "MANTENER_RUMBO" and override_active:
        print("[Deliberativo] -> OVERRIDE DE SEGURIDAD: Estructura a menos de 5.5m en CENTRO. Forzando evasión.")
        fallback = _fallback_decision(obstacles, guidance)
        if fallback.get("macro_action") == "MANTENER_RUMBO":
            fallback = {
                "macro_action": "EVADIR_IZQUIERDA",
                "vx": 0.0,
                "vy": 0.0,
                "vz": -0.8,
                "yaw_rate": -15.0,
                "rationale": "Override crítico: evasión por defecto.",
            }
        decision = fallback
        is_fallback = True

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
        decision["vx"] = 0.3 if close_structural else 0.8  # Avanza lentamente incluso con estructura cerca
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
        decision["vx"] = 0.3 if close_structural else 0.8  # Avanza lentamente incluso con estructura cerca
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
        "vision_enabled": VLM_VISION_ENABLED and images_b64 is not None,
        "vision_frames": len(images_b64) if images_b64 else 0,
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

