# Paso 4B: Cerebro Deliberativo (VLM / SLM local), brazo "slm".
#
# Se activa cuando el router detecta peligro critico en el sector central del
# ObstacleField (F1.1) o FOV bloqueado sin bypass determinista disponible.
# La consulta al SLM corre en un hilo aparte (DeliberationService, F0.5): el
# nodo NUNCA bloquea el lazo de control. En el ciclo que encola el pedido (o
# mientras espera respuesta) el comando es FRENAR; cuando el resultado llega
# (o el watchdog expira) se aplica la decision y se libera el freno.
from __future__ import annotations

import base64
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

import json as _json

from . import deep_scan
from .action_map import action_to_command, compute_corner_waypoint
from .deep_scan import SYSTEM_PROMPT_DEEP_SCAN  # usado en _query_slm_impl (mode="deep_scan")
from .deliberation_service import DeliberationService
from src.navigation.waypoint_tracker import effective_stall_threshold, hard_stall_threshold
from src.perception import ObstacleField, empty_field, has_open_corridor

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "ollama")
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")
VLM_VISION_ENABLED = os.getenv("VLM_VISION_ENABLED", "true").lower() == "true"
VLM_IMAGE_MAX_SIZE = int(os.getenv("VLM_IMAGE_MAX_SIZE", "384"))
VLM_FRAME_HISTORY_SIZE = int(os.getenv("VLM_FRAME_HISTORY_SIZE", "1"))
VLM_USE_JSON_SCHEMA = os.getenv("VLM_USE_JSON_SCHEMA", "true").lower() == "true"

MANEUVER_DURATION_S = float(os.getenv("MANEUVER_DURATION_S", "1.0"))
ESCAPE_MANEUVER_DURATION_S = float(os.getenv("ESCAPE_MANEUVER_DURATION_S", "1.6"))

# Macro-acciones que el SLM puede elegir. GIRAR_90 queda fuera: es un bypass
# determinista (ver policy_router en graph.py), nunca una eleccion del modelo.
PROMPT_ACTIONS = {
    "MANTENER_RUMBO",
    "EVADIR_IZQUIERDA",
    "EVADIR_DERECHA",
    "GANAR_ALTURA",
    "PERDER_ALTURA",
    "FRENAR",
}

SAFE_MARGIN_TTC_S = float(os.getenv("SAFE_MARGIN_TTC_S", "2.0"))

RESPONSE_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "macro_decision",
        "schema": {
            "type": "object",
            "properties": {
                "macro_action": {"type": "string", "enum": sorted(PROMPT_ACTIONS)},
                "rationale": {"type": "string"},
            },
            "required": ["macro_action", "rationale"],
            "additionalProperties": False,
        },
    },
}

# --------------------------------------------------------------------------- #
# System Prompts: Texto Puro (SLM) y Vision Directa (VLM)                    #
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT_TEXT = (
    "Sos el cerebro deliberativo táctico de un dron autónomo en una cuadrícula urbana (Manhattan Grid).\n"
    "Tu objetivo principal es lograr un vuelo suave, fluido y seguro hacia el waypoint general.\n\n"
    "Reglas de navegación:\n"
    "1. Trayectoria Libre y Dirección al Waypoint: Elige MANTENER_RUMBO únicamente si la trayectoria hacia el frente en la dirección general del waypoint deseado está libre de estructuras.\n"
    "2. Evasión Proactiva por Calles Libres: Si el frente está bloqueado por una estructura, evalúa los laterales. "
    "Elige EVADIR_IZQUIERDA o EVADIR_DERECHA únicamente si hay una calle transversal o pasaje despejado en esa dirección.\n"
    "3. Bloqueo Total (Callejón sin salida): Si el frente está bloqueado y ambos laterales también están cerrados por estructuras (edificios/paredes), "
    "elegí GANAR_ALTURA para sobrevolar el obstáculo, o PERDER_ALTURA si el obstáculo es orgánico (copa de un árbol, ramas) y hay espacio despejado "
    "más abajo (suelo, sendero) en lugar de intentar girar lateralmente contra el bloqueo.\n"
    "4. Peligro Inminente: Si estás en peligro crítico inminente en todas las direcciones, elige FRENAR.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicacion breve basada en la trayectoria y suavidad>"}\n\n'
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: Frente y rumbo al waypoint despejados.\n"
    "- EVADIR_IZQUIERDA: Calle transversal libre a la izquierda.\n"
    "- EVADIR_DERECHA: Calle transversal libre a la derecha.\n"
    "- GANAR_ALTURA: Frente y laterales bloqueados por estructuras (subir).\n"
    "- PERDER_ALTURA: Frente y laterales bloqueados por un obstáculo orgánico (árbol/ramas) con espacio despejado abajo (bajar).\n"
    "- FRENAR: Peligro crítico en todas direcciones.\n\n"
    "Reglas estrictas:\n"
    f"1. No elijas MANTENER_RUMBO si el sector central está BLOQUEADO con TTC menor a {SAFE_MARGIN_TTC_S:.1f} segundos.\n"
    "2. Si estás rodeado de estructuras de cerca, prioriza GANAR_ALTURA (edificios/paredes) o PERDER_ALTURA (vegetación con salida abajo) para superarlas.\n"
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
    "(ambos laterales cerrados por paredes/edificios), elegí GANAR_ALTURA de inmediato para sobrevolar la estructura. Si en cambio lo que bloquea "
    "es vegetación (ramas, copa de un árbol) y ves claramente espacio despejado más abajo en la imagen (suelo, sendero, calle), elegí PERDER_ALTURA "
    "para pasar por debajo en lugar de subir más adentro del follaje. No sigas girando en círculos contra el bloqueo.\n"
    "4. Peligro Inminente: Si estás en una situación de peligro inminente y necesitas detenerte a evaluar, elige FRENAR.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicacion breve basada en la trayectoria y suavidad>"}\n\n'
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: Frente y rumbo al waypoint despejados.\n"
    "- EVADIR_IZQUIERDA: Calle transversal libre visible a la izquierda.\n"
    "- EVADIR_DERECHA: Calle transversal libre visible a la derecha.\n"
    "- GANAR_ALTURA: Frente y ambos lados bloqueados por estructuras (callejón sin salida).\n"
    "- PERDER_ALTURA: Frente y ambos lados bloqueados por vegetación (árbol/ramas), con espacio despejado visible más abajo.\n"
    "- FRENAR: Peligro crítico inmediato en todas las direcciones.\n\n"
    "Reglas estrictas:\n"
    f"1. No elijas MANTENER_RUMBO si el sector central está BLOQUEADO con TTC menor a {SAFE_MARGIN_TTC_S:.1f} segundos.\n"
    "2. Evita giros innecesarios o alternantes si no hay una vía de escape abierta. Si estás rodeado por estructuras, gana altura; "
    "si estás rodeado por vegetación con salida visible abajo, perdé altura.\n"
    "3. Salida estrictamente JSON sin texto adicional."
)

SYSTEM_PROMPT = SYSTEM_PROMPT_VISION if VLM_VISION_ENABLED else SYSTEM_PROMPT_TEXT


def _build_user_prompt(
    field: ObstacleField,
    telemetry: Dict[str, Any],
    guidance: Optional[Dict[str, Any]] = None,
    stuck_cycles: int = 0,
    recent_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    sector_summary = field.summary_text()

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

    stuck_note = ""
    if stuck_cycles >= 5:
        stuck_note = (
            f"\n- AVISO: el dron lleva {stuck_cycles} ciclos sin progresar hacia el waypoint. "
            "Si los 3 sectores están bloqueados, elige GANAR_ALTURA en lugar de seguir girando."
        )

    history_note = ""
    if recent_history:
        lines = ["\nHISTORIAL RECIENTE (accion -> resultado):"]
        for h in recent_history[-3:]:
            delta_d = h.get("delta_dist_wp")
            delta_ttc = h.get("delta_min_ttc")
            delta_d_str = f"{delta_d:+.1f}m" if delta_d is not None else "N/D"
            delta_ttc_str = f"{delta_ttc:+.1f}s" if delta_ttc is not None else "N/D"
            lines.append(f"- {h.get('macro_action', '?')}: Δdist_waypoint={delta_d_str}, Δttc_min={delta_ttc_str}")
        history_note = "\n".join(lines)

    return (
        f"{sector_summary}\n\n"
        f"OBJETIVO Y ALTITUD:\n"
        f"- {wp_str}\n"
        f"- Altitud actual: {altitude:.1f}m (Cota segura: 10.0m){stuck_note}"
        f"{history_note}\n\n"
        "INSTRUCCION:\n"
        "Elige la macro_action ('EVADIR_IZQUIERDA', 'EVADIR_DERECHA', 'GANAR_ALTURA' o 'MANTENER_RUMBO').\n"
        "Responde SOLO con este JSON:\n"
        '{"macro_action": "<ACCION>", "rationale": "<motivo corto>"}'
    )


def _fallback_decision(field: ObstacleField, guidance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Heuristica determinista sobre ObstacleField cuando el SLM no responde o no adhiere al formato."""
    if not field.has_evidence():
        return {"macro_action": "FRENAR", "rationale": "Fallback: sin evidencia de percepcion valida, frenando por seguridad."}

    center_blocked = field.is_blocked("centro")
    left_blocked = field.is_blocked("izquierda")
    right_blocked = field.is_blocked("derecha")
    left_occ = field.sector_occupancy("izquierda")
    right_occ = field.sector_occupancy("derecha")

    target_dir = (guidance.get("bearing_err_deg") or 0.0) if guidance else 0.0

    if center_blocked:
        if left_blocked and right_blocked:
            return {"macro_action": "GANAR_ALTURA", "rationale": "Fallback: centro, izquierda y derecha bloqueados. Callejon sin salida."}
        if not left_blocked and not right_blocked:
            if target_dir < -10.0:
                return {"macro_action": "EVADIR_IZQUIERDA", "rationale": "Fallback: ambos laterales despejados, evadiendo hacia el waypoint (izquierda)."}
            if target_dir > 10.0:
                return {"macro_action": "EVADIR_DERECHA", "rationale": "Fallback: ambos laterales despejados, evadiendo hacia el waypoint (derecha)."}
            side = "EVADIR_IZQUIERDA" if left_occ <= right_occ else "EVADIR_DERECHA"
            return {"macro_action": side, "rationale": f"Fallback: ambos laterales despejados (ocup izq={left_occ:.2f} der={right_occ:.2f})."}
        if not left_blocked:
            return {"macro_action": "EVADIR_IZQUIERDA", "rationale": "Fallback: bloqueo frontal, izquierda despejada."}
        return {"macro_action": "EVADIR_DERECHA", "rationale": "Fallback: bloqueo frontal, derecha despejada."}

    return {"macro_action": "MANTENER_RUMBO", "rationale": "Fallback: sector central despejado."}


def _parse_decision(raw: str) -> Optional[Dict[str, Any]]:
    """Extrae la decisión del texto del SLM de manera ultratolerante a Markdown o texto conversacional.

    Sigue siendo la red de seguridad aunque se use decodificación restringida
    (F2.3): un servidor que no soporte json_schema, o que lo soporte mal,
    debe seguir produciendo una decisión utilizable.
    """
    if not raw:
        return None

    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    match = re.search(r"\{[\s\S]*\}", cleaned)
    data = None
    if match:
        candidate = match.group(0)
        try:
            data = _json.loads(candidate)
        except Exception:
            try:
                data = _json.loads(candidate.replace("'", '"'))
            except Exception:
                data = None

    macro = ""
    rationale = ""
    if isinstance(data, dict):
        macro = str(data.get("macro_action", "")).upper().strip()
        rationale = str(data.get("rationale", "")).strip()

    if not macro or macro not in PROMPT_ACTIONS:
        m_action = re.search(r'["\']?macro_action["\']?\s*:\s*["\']([A-Z_]+)["\']', raw, re.IGNORECASE)
        if m_action:
            cand_macro = m_action.group(1).upper().strip()
            if cand_macro in PROMPT_ACTIONS:
                macro = cand_macro
        else:
            for act in PROMPT_ACTIONS:
                if act in raw.upper():
                    macro = act
                    break

    if not macro or macro not in PROMPT_ACTIONS:
        return None

    if not rationale:
        m_rat = re.search(r'["\']?rationale["\']?\s*:\s*["\']([^"\'\n\r]+)["\']', raw, re.IGNORECASE)
        rationale = m_rat.group(1).strip() if m_rat else f"Decisión SLM: {macro}."

    return {"macro_action": macro, "rationale": rationale}


def _encode_frame_base64(frame: Any, max_size: int = VLM_IMAGE_MAX_SIZE) -> Optional[str]:
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
        success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not success:
            return None
        return base64.b64encode(buffer).decode("utf-8")
    except Exception as exc:
        print(f"[deliberative] Error codificando frame a base64: {exc}")
        return None


def _query_slm_impl(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]:
    """Consulta al servidor compatible con OpenAI (LM Studio u Ollama).

    Intenta primero con decodificación restringida (json_schema, F2.3); si el
    servidor no la soporta, reintenta en modo libre y el parser tolerante
    sigue siendo la red de seguridad final. Corre en el hilo worker de
    DeliberationService: esta función nunca se llama desde el hilo del grafo.
    """
    if OpenAI is None:
        return None, "", 0.0, "Libreria openai no instalada"

    prompt = payload["prompt"]
    images_b64 = payload.get("images_b64")
    # H2 (PLAN-MEJORAS-3): el escaneo profundo reusa esta misma funcion de
    # consulta (una unica cola/hilo worker, ver DeliberationService) pero con
    # su propio system prompt y etiquetas por rumbo en vez de por fotograma
    # -- reusar la etiqueta temporal aca seria el mismo error que corrigio
    # F2.1 (afirmarle al modelo un eje que no es el real, ver deep_scan.py).
    is_deep_scan = payload.get("mode") == "deep_scan"
    image_labels = payload.get("image_labels")

    t0 = time.time()
    try:
        client = OpenAI(base_url=LOCAL_LLM_URL, api_key=LOCAL_LLM_API_KEY)

        if VLM_VISION_ENABLED and images_b64:
            total_frames = len(images_b64)
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
            for i, img_b64 in enumerate(images_b64):
                # Invariante (F2.1 / test_prompt_invariants): una etiqueta por
                # imagen efectivamente enviada, nunca una historia inventada.
                if image_labels and i < len(image_labels):
                    user_content.append({"type": "text", "text": f"{image_labels[i]}:"})
                elif total_frames > 1:
                    delta = total_frames - 1 - i
                    frame_label = f"t-{delta}" if delta > 0 else "t (actual)"
                    user_content.append({"type": "text", "text": f"[Fotograma {frame_label}]:"})
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
            system_prompt = SYSTEM_PROMPT_DEEP_SCAN if is_deep_scan else SYSTEM_PROMPT_VISION
        else:
            user_content = prompt
            system_prompt = SYSTEM_PROMPT_TEXT

        # El barrido multi-imagen del escaneo profundo tiene un prefill mas
        # lento que una consulta tactica de 1 fotograma; SLM_DEEP_WATCHDOG_MS
        # (mayor que SLM_WATCHDOG_MS) es el watchdog del lado del llamador,
        # este timeout de cliente HTTP debe ser al menos igual de generoso.
        kwargs = dict(
            model=LOCAL_LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=200,
            timeout=15.0 if is_deep_scan else 8.0,
        )

        raw = ""
        used_schema = False
        if VLM_USE_JSON_SCHEMA:
            try:
                completion = client.chat.completions.create(response_format=RESPONSE_JSON_SCHEMA, **kwargs)
                raw = completion.choices[0].message.content or ""
                used_schema = True
            except Exception:
                raw = ""
        if not raw:
            completion = client.chat.completions.create(**kwargs)
            raw = completion.choices[0].message.content or ""

        latency_ms = (time.time() - t0) * 1000.0
        parsed = _parse_decision(raw)
        if parsed is not None:
            parsed["used_json_schema"] = used_schema
        return parsed, raw, latency_ms, None
    except Exception as exc:
        latency_ms = (time.time() - t0) * 1000.0
        err_msg = str(exc)
        print(f"[deliberative] SLM no disponible ({err_msg}). Usando fallback.")
        return None, "", latency_ms, err_msg


def make_deliberation_service() -> DeliberationService:
    """Factory del servicio asincrono de deliberacion (F0.5)."""
    return DeliberationService(query_fn=_query_slm_impl)


def _dist_xy(guidance: Dict[str, Any]) -> float:
    """Distancia horizontal al waypoint activo (0.0 si no hay guiado)."""
    value = guidance.get("dist_xy", guidance.get("distance", 0.0))
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _escape_resolved_the_stall(state: Dict[str, Any], guidance: Dict[str, Any]) -> bool:
    """True si hubo progreso horizontal REAL desde el ultimo escape forzado.

    El contador de escapes consecutivos no puede colgarse de
    `evasion_stuck_cycles`: el propio escape pide `_escape_reset`, que pone
    ese contador en cero en el ciclo siguiente. Si se usara esa senal, cada
    escape "pareceria" haber resuelto el atasco y MAX_CONSECUTIVE_ESCAPES
    nunca se alcanzaria. La unica evidencia valida de que subir sirvio es que
    la distancia horizontal al waypoint bajo de verdad.
    """
    baseline = state.get("_escape_baseline_dist")
    if baseline is None:
        return True  # todavia no hubo ningun escape que evaluar
    eps_m = float(os.getenv("WAYPOINT_PROGRESS_EPS_M", "0.5"))
    return _dist_xy(guidance) < float(baseline) - eps_m


def _apply_maneuver_kinematics(decision: Dict[str, Any], guidance: Dict[str, Any], telemetry: Dict[str, Any], close_structural: bool) -> Dict[str, Any]:
    macro = decision.get("macro_action", "MANTENER_RUMBO")
    cmd = action_to_command(macro, guidance=guidance, telemetry=telemetry, close_structural=close_structural)
    cmd["rationale"] = decision.get("rationale", "")
    return cmd


def make_deliberative_node(service: DeliberationService):
    """Construye el nodo deliberativo ligado a un DeliberationService concreto."""

    def deliberative_node(state: Dict[str, Any]) -> Dict[str, Any]:
        print("[Deliberativo] -> Iniciando nodo deliberativo...")
        state["flight_status"] = "hover_slm"
        state["route"] = "deliberative"
        # Flanco, no nivel: el lazo consume `_escape_reset` con pop(), pero el
        # nodo tampoco debe depender de que lo haga -- un consumidor que se lo
        # olvide dejaria el tracker reseteandose en todos los ciclos.
        state["_escape_reset"] = False

        field: ObstacleField = state.get("obstacle_field") or empty_field()
        telemetry = state.get("telemetry", {}) or {}
        guidance = state.get("waypoint_guidance") or {}

        # --- ESCAPE DE DEADLOCK POR ALTURA (sincronico, no consulta al LLM) ---
        # evasion_stuck_cycles ya NO cuenta los ciclos en que se frena a
        # proposito esperando al SLM (ver _deliberation_pending mas abajo y
        # el call site de record_progress en runner.py/main.py) -- antes,
        # esperar una respuesta del LLM (2-8s medidos) contaba como "sin
        # progresar" y disparaba este escape en ~2s (EVASION_STUCK_THRESHOLD
        # a LOOP_HZ=5.0), descartando el pedido pendiente antes de que
        # pudiera resolverse.
        #
        # 2026-0824: esta rama tiene ahora tres guardas que antes no tenia, y
        # que juntas explican el vuelo en el que el dron subio 12m sin
        # consultar al SLM ni una vez (ver CHANGELOG.md):
        #   1. Umbral coherente con la metrica que lo alimenta
        #      (effective_stall_threshold): antes se declaraba atasco a los 5
        #      ciclos, mas rapido de lo que era fisicamente demostrable el
        #      progreso durante un giro.
        #   2. No se sube a ciegas si la percepcion ve corredor transitable.
        #   3. El escape agotado ENCLAVA en vez de resetear su propio contador
        #      (el reseteo lo convertia en un ciclo limite de periodo 3).
        stuck_threshold = effective_stall_threshold()
        stuck_cycles = int(state.get("evasion_stuck_cycles", 0))
        loop_hz = float(os.getenv("LOOP_HZ", "5.0"))

        # El escape solo se "perdona" con progreso horizontal medido, nunca
        # por el mero hecho de que el contador de atasco se haya reseteado.
        if _escape_resolved_the_stall(state, guidance):
            state["_consecutive_escapes"] = 0
            state["_escape_locked"] = False
            state["_escape_baseline_dist"] = None
            state["_deadlock_cycles"] = 0

        escape_locked = bool(state.get("_escape_locked", False))
        hard_stuck = stuck_cycles >= hard_stall_threshold()
        # Mismo criterio que policy_router: no se sube a ciegas si la
        # percepcion ve un corredor transitable (salvo atasco duro).
        corridor_open = (not hard_stuck) and has_open_corridor(field, guidance)

        if stuck_cycles >= stuck_threshold and not escape_locked and not corridor_open:
            state["_deadlock_cycles"] = int(state.get("_deadlock_cycles", 0)) + 1

            # H2 (PLAN-MEJORAS-3): antes de forzar el escape ciego, intentar
            # un escaneo panoramico + una consulta al VLM (DEADLOCK_STRATEGY=
            # deep_vlm). El escape sincronico de abajo queda intacto como red
            # de seguridad final -- si el escaneo no resuelve (timeout,
            # formato invalido, sin accion viable), la ejecucion sigue hacia
            # abajo en el mismo ciclo, sin cambios en esa rama.
            if deep_scan.DEADLOCK_STRATEGY == "deep_vlm":
                handled = deep_scan.deep_scan_cycle(
                    state, service, field, telemetry, guidance,
                    arm="slm",
                    deadlock_cycles=state["_deadlock_cycles"],
                    consecutive_escapes=int(state.get("_consecutive_escapes", 0)),
                )
                if handled:
                    return state

            max_escapes = int(os.getenv("MAX_CONSECUTIVE_ESCAPES", "3"))
            consecutive_escapes = int(state.get("_consecutive_escapes", 0)) + 1
            state["_consecutive_escapes"] = consecutive_escapes
            state["_escape_baseline_dist"] = _dist_xy(guidance)
            state["_deliberation_pending"] = False
            state["evasion_stuck_cycles"] = 0
            state["_escape_reset"] = True
            state["slm_request_id"] = None

            # Alterna GANAR_ALTURA/PERDER_ALTURA entre intentos sucesivos
            # (2026-0827, ver CHANGELOG.md, mismo fix que fsm.py): antes el
            # escape sincronico solo sabia subir, sin alternativa si el
            # obstaculo bloqueaba tambien por arriba -- confirmado en UE con
            # el dron trabado dentro de la copa de un arbol, insistiendo con
            # GANAR_ALTURA hasta agotar los intentos y quedar frenando (sin
            # evidencia de percepcion en ese punto, el fallback determinista
            # de _fallback_decision elige FRENAR indefinidamente).
            escape_action = "GANAR_ALTURA" if (consecutive_escapes - 1) % 2 == 0 else "PERDER_ALTURA"

            max_escape_alt = float(os.getenv("MAX_ESCAPE_ALT_M", "20.0"))
            current_alt = abs(float(telemetry.get("position", {}).get("z", 0.0)))
            exhausted = consecutive_escapes > max_escapes
            # El techo de altura solo fuerza el agotamiento si el proximo
            # intento seguiria subiendo -- si toca bajar (alternancia), estar
            # por encima del techo es irrelevante (bajar es, si acaso, la
            # correccion correcta).
            above_ceiling = escape_action == "GANAR_ALTURA" and current_alt > max_escape_alt

            if exhausted or above_ceiling:
                # ENCLAVAMIENTO + CAMBIO DE ESTRATEGIA. Antes esta rama
                # frenaba y ademas ponia `_consecutive_escapes = 0`: se
                # reseteaba a si misma, convirtiendo la red de seguridad en un
                # ciclo limite de periodo 3 (SUBIR, SUBIR, FRENAR, SUBIR, ...)
                # que en vuelo real duro hasta el final del log. Ahora el
                # enclavamiento persiste -- el escape vertical queda
                # descartado hasta que haya progreso medido -- y se cambia de
                # estrategia: un giro hacia el lado del waypoint, que es
                # ademas lo unico que corrige el rumbo congelado que el
                # ascenso/descenso dejaba atras. Los ciclos siguientes caen a
                # la deliberacion normal (SLM), que vuelve a tener voz en vez
                # de quedar cortocircuitada.
                state["_escape_locked"] = True
                if above_ceiling:
                    print(f"[Deliberativo] -> ALTURA MÁXIMA DE ESCAPE ALCANZADA: {current_alt:.1f}m > {max_escape_alt:.1f}m. Escape enclavado, girando para buscar corredor.")
                    reason = f"Altura máxima de escape alcanzada ({current_alt:.1f}m)."
                    state["flight_status"] = "escape_altitude_limit"
                else:
                    print(f"[Deliberativo] -> ESCAPE AGOTADO: {consecutive_escapes - 1} intentos verticales (GANAR_ALTURA/PERDER_ALTURA alternados) sin progreso horizontal. Enclavando el escape y cambiando de estrategia (giro).")
                    reason = f"Escape agotado tras {consecutive_escapes - 1} intentos verticales sin progreso."
                    state["flight_status"] = "escape_agotado"

                cmd = action_to_command("GIRAR_90", guidance=guidance, telemetry=telemetry)
                side = "izquierda" if cmd["yaw_rate"] < 0 else "derecha"
                cmd["rationale"] = f"{reason} Girando 90° hacia la {side} para buscar corredor; escape vertical descartado hasta que haya progreso."
                state["next_action"] = "GIRAR_90"
                state["velocity_command"] = cmd
                state["active_maneuver"] = "GIRAR_90"
                state["maneuver_cycles_left"] = max(1, round(ESCAPE_MANEUVER_DURATION_S * loop_hz))
                state["maneuver_command"] = cmd
                # Desvio persistente (2026-0827, ver CHANGELOG.md): mismo fix
                # que fsm.py -- sin esto, el guiado por corredor vuelve a
                # apuntar a la misma linea bloqueada apenas termina el giro
                # (confirmado en UE, dron trabado dentro de la copa de un
                # arbol). inject_corner ya estaba declarado en DroneState pero
                # ningun nodo lo producia.
                target_yaw = cmd.get("target_yaw")
                if target_yaw is not None:
                    state["inject_corner"] = compute_corner_waypoint(telemetry, float(target_yaw), guidance=guidance)
                return state

            print(f"[Deliberativo] -> ESCAPE VERTICAL ({consecutive_escapes}/{max_escapes}, {escape_action}): {stuck_cycles} ciclos sin progresar. Forzando {escape_action} sin consultar al LLM.")
            cmd = action_to_command(escape_action, guidance=guidance, telemetry=telemetry)
            verbo = "Subiendo" if escape_action == "GANAR_ALTURA" else "Bajando"
            cmd["rationale"] = f"Escape de deadlock ({consecutive_escapes}/{max_escapes}): {stuck_cycles} ciclos bloqueado. {verbo} para superar el obstáculo."
            state["next_action"] = escape_action
            state["velocity_command"] = cmd
            state["flight_status"] = "escape_altura" if escape_action == "GANAR_ALTURA" else "escape_descenso"
            state["active_maneuver"] = escape_action
            state["maneuver_cycles_left"] = max(1, round(ESCAPE_MANEUVER_DURATION_S * loop_hz))
            state["maneuver_command"] = cmd
            return state

        close_structural = field.is_blocked("centro") and field.sector_ttc("centro") <= SAFE_MARGIN_TTC_S

        pending_id = state.get("slm_request_id")
        result, age_ms, has_pending = service.poll()

        def _finalize(decision: Dict[str, Any], raw_response: str, latency_ms: float, is_fallback: bool, err: Optional[str], timed_out: bool) -> Dict[str, Any]:
            macro = decision.get("macro_action", "FRENAR")
            # Override de seguridad: nunca MANTENER_RUMBO con estructura bloqueada a corto TTC.
            if macro == "MANTENER_RUMBO" and close_structural:
                print("[Deliberativo] -> OVERRIDE DE SEGURIDAD: centro bloqueado con TTC bajo. Forzando evasión.")
                decision = _fallback_decision(field, guidance)
                if decision.get("macro_action") == "MANTENER_RUMBO":
                    decision = {"macro_action": "EVADIR_IZQUIERDA", "rationale": "Override crítico: evasión por defecto."}
                macro = decision["macro_action"]
                is_fallback = True

            cmd = _apply_maneuver_kinematics(decision, guidance, telemetry, close_structural)

            deliberations_list = state.setdefault("deliberations", [])
            entry_id = len(deliberations_list) + 1
            deliberations_list.append({
                "id": entry_id,
                "timestamp": time.time(),
                "arm": "slm",
                "model": LOCAL_LLM_MODEL_NAME,
                "vision_enabled": VLM_VISION_ENABLED,
                "system_prompt": SYSTEM_PROMPT,
                # Instrumentacion de auditoria (2026-0901): el prompt de
                # usuario efectivamente enviado, para poder reconstruir la
                # consulta completa junto con raw_response de abajo.
                "prompt": state.get("_pending_delib_prompt", ""),
                "raw_response": raw_response if not is_fallback else f"Fallback activado: {err or ('timeout' if timed_out else 'Formato JSON inválido')}",
                "macro_action": macro,
                "rationale": decision.get("rationale", ""),
                "is_fallback": is_fallback,
                "timeout": timed_out,
                "adherent": (not is_fallback) and not timed_out,
                "used_json_schema": decision.get("used_json_schema", False),
                "latency_ms": round(latency_ms, 1),
            })
            # Canal de una sola pasada hacia FlightLogger (ver graph.py): los
            # frames RAW nunca se guardan en `deliberations` (viviria toda la
            # mision, infla memoria) -- solo en este ciclo, consumido con
            # pop() por el llamador.
            state["_last_delib_frames"] = state.get("_pending_delib_frames") or []
            state["_pending_delib_prompt"] = None
            state["_pending_delib_frames"] = None

            state["next_action"] = macro
            state["velocity_command"] = cmd
            state["route"] = "deliberative"
            state["slm_request_id"] = None
            state["_deliberation_pending"] = False

            if macro in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA", "GANAR_ALTURA"):
                loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
                state["active_maneuver"] = macro
                state["maneuver_cycles_left"] = max(1, round(MANEUVER_DURATION_S * loop_hz))
                state["maneuver_command"] = cmd
            else:
                state["active_maneuver"] = None
                state["maneuver_cycles_left"] = 0
                state["maneuver_command"] = None
            return state

        if pending_id is not None:
            if result is not None and result.request_id == pending_id:
                is_fallback = result.parsed_decision is None
                decision = result.parsed_decision or _fallback_decision(field, guidance)
                return _finalize(decision, result.raw_response, result.latency_ms, is_fallback, result.error, timed_out=False)

            watchdog_ms = float(os.getenv("SLM_WATCHDOG_MS", "1500"))
            if age_ms > watchdog_ms:
                print(f"[Deliberativo] -> WATCHDOG: sin respuesta del SLM en {age_ms:.0f}ms. Aplicando fallback.")
                decision = _fallback_decision(field, guidance)
                return _finalize(decision, "", age_ms, is_fallback=True, err="timeout", timed_out=True)

            # Sigue pendiente y dentro del watchdog: frenar este ciclo sin re-encolar.
            cmd = action_to_command("FRENAR", guidance=guidance, telemetry=telemetry)
            cmd["rationale"] = f"Esperando respuesta del SLM ({age_ms:.0f}ms)."
            state["next_action"] = "FRENAR"
            state["velocity_command"] = cmd
            state["route"] = "deliberative"
            state["flight_status"] = "hover_slm"
            # Fix 1: frenar a proposito mientras se espera al SLM (dentro del
            # watchdog) NO es "sin progresar" -- el caller (runner.py/main.py)
            # se salta record_progress() mientras esta flag este activa, para
            # que el escape sincrono de arriba no descarte un pedido legitimo
            # antes de que el SLM tenga tiempo de responder.
            state["_deliberation_pending"] = True
            return state

        # No hay pedido pendiente: construir el prompt/imagenes y encolar uno nuevo.
        frame_history = state.get("frame_history") or []
        images_b64: Optional[List[str]] = None
        if VLM_VISION_ENABLED and frame_history:
            encoded = [enc for f in frame_history if (enc := _encode_frame_base64(f)) is not None]
            images_b64 = encoded or None

        recent_history = state.get("_delib_outcomes") or []
        prompt = _build_user_prompt(field, telemetry, guidance, stuck_cycles=stuck_cycles, recent_history=recent_history)
        request_id = service.request({"prompt": prompt, "images_b64": images_b64})
        state["slm_request_id"] = request_id
        # Instrumentacion de auditoria (2026-0901): recordar que se mando
        # (texto + frames RAW, cada uno con su timestamp REAL de captura,
        # ver frame_history_ts en graph.py) para adjuntarlo a la entrada de
        # deliberations[] cuando _finalize() resuelva el pedido, varios
        # ciclos despues.
        state["_pending_delib_prompt"] = prompt
        frame_history_ts = state.get("frame_history_ts") or []
        state["_pending_delib_frames"] = (
            list(zip(frame_history, frame_history_ts)) if VLM_VISION_ENABLED and frame_history else []
        )

        cmd = action_to_command("FRENAR", guidance=guidance, telemetry=telemetry)
        cmd["rationale"] = "Frenando: pedido de deliberación recién encolado."
        state["next_action"] = "FRENAR"
        state["velocity_command"] = cmd
        state["route"] = "deliberative"
        state["flight_status"] = "hover_slm"
        state["_deliberation_pending"] = True
        return state

    return deliberative_node
