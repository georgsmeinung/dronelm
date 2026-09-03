# Fase H2 (PLAN-MEJORAS-3): escaneo espacial profundo en atasco duro.
#
# Compartido entre el brazo SLM (deliberative.py) y el brazo FSM (fsm.py):
# ambos comparten el mismo mecanismo raiz de escape sincronico por atasco
# ("mismo fix que fsm.py", ver deliberative.py). DEADLOCK_STRATEGY selecciona
# si, antes de forzar el escape ciego (GANAR_ALTURA/PERDER_ALTURA alternado),
# se intenta un barrido de rumbos + una unica consulta al VLM con el panorama
# completo (H3.1: factorial AGENT_ARM x DEADLOCK_STRATEGY).
#
# Corre DENTRO del mismo StateGraph/lazo, nunca en un loop aparte (H2.2):
# reutiliza el frame que capture_node ya produjo este ciclo (nunca llama a
# capture() de nuevo) y reemite su propio velocity_command cada ciclo via
# motor_node, igual que cualquier otro nodo de politica. La vigilancia del
# gatekeeper rapido (policy_router) nunca se apaga mientras dura el barrido:
# sin traslacion, FlowTTCEstimator no produce evidencia (foe_confidence=0),
# asi que has_open_corridor() da False y el router sigue enrutando hacia el
# nodo que llama a esta funcion -- ver PLAN-MEJORAS-3.md §0.3.
#
# Principio rector (PLAN-MEJORAS-3.md §0): exclusion total de profundidad.
# Este modulo NUNCA pide el canal de profundidad al simulador -- reutiliza
# unicamente el frame RGB que ya esta en el DroneState.
from __future__ import annotations

import base64
import math
import os
import time
from typing import Any, Dict, List, Optional

from .action_map import action_to_command
from .deliberation_service import DeliberationService

# Default deep_vlm (2026-0903, pedido explicito): coherente con el resto de
# H2/H3 -- el escape ciego sigue existiendo como red de seguridad final (ver
# deep_scan_cycle) para cuando el escaneo profundo expira o no resuelve, asi
# que subir el default no reduce la robustez, solo la usa como primera
# opcion en vez de la ultima.
DEADLOCK_STRATEGY = os.getenv("DEADLOCK_STRATEGY", "deep_vlm")  # "blind" | "deep_vlm"
SCAN_HEADING_COUNT_DEEP = int(os.getenv("SCAN_HEADING_COUNT_DEEP", "4"))
SCAN_SETTLE_CYCLES_DEEP = int(os.getenv("SCAN_SETTLE_CYCLES_DEEP", "2"))
SCAN_YAW_TOLERANCE_DEG = float(os.getenv("SCAN_YAW_TOLERANCE_DEG", "5.0"))
SLM_DEEP_WATCHDOG_MS = float(os.getenv("SLM_DEEP_WATCHDOG_MS", "12000"))
MAX_DEEP_SCAN_IMAGES = int(os.getenv("MAX_DEEP_SCAN_IMAGES", "5"))
DEEP_SCAN_MANEUVER_DURATION_S = float(os.getenv("MANEUVER_DURATION_S", "1.0"))
VLM_IMAGE_MAX_SIZE = int(os.getenv("VLM_IMAGE_MAX_SIZE", "384"))
# Espejo deliberado de deliberative.LOCAL_LLM_MODEL_NAME/VLM_VISION_ENABLED
# (mismo motivo que _encode_frame_base64 arriba: evita el import circular).
# Antes faltaban en la entrada de deliberations[] de este modulo, asi que la
# auditoria en consola mostraba "SLM TEXTO" en vez de "VLM VISION DIRECTA"
# para las decisiones del escaneo profundo (2026-0901, bug cosmetico).
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")
VLM_VISION_ENABLED = os.getenv("VLM_VISION_ENABLED", "true").lower() == "true"

# Mismo vocabulario que deliberative.PROMPT_ACTIONS (H2.3): el escaneo
# profundo no introduce una macro-accion nueva, elige entre las existentes.
PROMPT_ACTIONS = {
    "MANTENER_RUMBO",
    "EVADIR_IZQUIERDA",
    "EVADIR_DERECHA",
    "GANAR_ALTURA",
    "PERDER_ALTURA",
    "FRENAR",
}

SYSTEM_PROMPT_DEEP_SCAN = (
    "Sos el cerebro deliberativo de un dron autonomo en un atasco genuino: los intentos previos de "
    "avanzar no progresaron y no hay corredor visible desde el rumbo actual.\n"
    "Se te muestran varias imagenes tomadas girando en el lugar, cada una hacia un rumbo distinto "
    "(NO son fotogramas consecutivos en el tiempo -- son direcciones distintas vistas desde el mismo "
    "punto). La primera imagen corresponde al rumbo que viene fallando.\n"
    "Evalua el panorama completo (los rumbos mostrados, no solo el frente) y elegi UNA macro-accion "
    "para resolver el atasco.\n\n"
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: el rumbo que viene fallando en realidad esta despejado (falso atasco).\n"
    "- EVADIR_IZQUIERDA / EVADIR_DERECHA: hay una calle o pasaje despejado en alguno de los rumbos "
    "mostrados a la izquierda o derecha del rumbo actual.\n"
    "- GANAR_ALTURA: todos los rumbos muestran estructuras (edificios/paredes) -- sobrevolar.\n"
    "- PERDER_ALTURA: el bloqueo es vegetacion (arboles/ramas) y se ve espacio despejado mas abajo.\n"
    "- FRENAR: ningun rumbo del panorama ofrece una salida clara; mejor esperar a la proxima deliberacion.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicacion breve citando el rumbo elegido>"}'
)


def _normalize_deg(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _encode_frame_base64(frame: Any, max_size: int = VLM_IMAGE_MAX_SIZE) -> Optional[str]:
    """Codifica un frame RGB ya capturado a JPEG base64.

    Espejo deliberado de deliberative._encode_frame_base64: evita el import
    circular deep_scan <-> deliberative (ambos son importados por fsm.py).
    """
    if frame is None:
        return None
    try:
        # pyrefly: ignore [missing-import]
        import cv2

        h, w = frame.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not success:
            return None
        return base64.b64encode(buffer).decode("utf-8")
    except Exception as exc:
        print(f"[deep_scan] Error codificando frame a base64: {exc}")
        return None


def clear_scan_state(state: Dict[str, Any]) -> None:
    state["_scan_phase"] = None
    state["_scan_heading_index"] = 0
    state["_scan_frames"] = []
    state["_scan_start_yaw_deg"] = None
    state["_scan_settle_left"] = 0
    state["_deep_scan_request_id"] = None


def _build_deep_scan_prompt(
    field: Any,
    telemetry: Dict[str, Any],
    guidance: Dict[str, Any],
    deadlock_cycles: int,
    consecutive_escapes: int,
) -> str:
    pos = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    altitude = abs(float(pos.get("z", 0.0))) if isinstance(pos, dict) else 0.0

    wp_str = "Meta: Frente (0m)"
    if guidance and guidance.get("target_wp"):
        wp = guidance["target_wp"]
        label = wp.get("label", "WP")
        dist = guidance.get("distance", 0.0)
        err = guidance.get("bearing_err_deg", 0.0)
        direction = "Izquierda" if err < -10.0 else "Derecha" if err > 10.0 else "Frente"
        wp_str = f"Meta ({label}): {dist:.1f}m hacia {direction} ({err:+.0f}°)"

    max_escape_alt = float(os.getenv("MAX_ESCAPE_ALT_M", "20.0"))
    return (
        f"{field.summary_text()}\n\n"
        f"ATASCO: {deadlock_cycles} ciclos sin progresar hacia el waypoint.\n"
        f"Escapes verticales ya intentados en este atasco: {consecutive_escapes}.\n"
        f"OBJETIVO Y ALTITUD:\n"
        f"- {wp_str}\n"
        f"- Altitud actual: {altitude:.1f}m (Cota maxima de escape: {max_escape_alt:.1f}m)\n\n"
        "INSTRUCCION:\n"
        "Elegi la macro_action que mejor resuelva el atasco a partir del panorama mostrado.\n"
        "Responde SOLO con este JSON:\n"
        '{"macro_action": "<ACCION>", "rationale": "<motivo corto citando el rumbo>"}'
    )


def deep_scan_cycle(
    state: Dict[str, Any],
    service: DeliberationService,
    field: Any,
    telemetry: Dict[str, Any],
    guidance: Dict[str, Any],
    arm: str,
    deadlock_cycles: int,
    consecutive_escapes: int,
) -> bool:
    """Ejecuta un paso del escaneo profundo (H2.2).

    Debe llamarse SOLO cuando ya se determino que hay atasco duro sin
    corredor (misma condicion que dispara el escape sincronico existente).

    Devuelve True si el ciclo quedo totalmente resuelto por esta funcion (el
    llamador debe retornar `state` tal cual). Devuelve False cuando el
    escaneo fallo (timeout, formato invalido o accion no viable): el
    llamador debe caer al escape sincronico existente en el mismo ciclo, sin
    cambios en esa rama (H2.2).
    """
    state["route"] = "deliberative" if arm == "slm" else "fsm"

    orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    current_yaw_deg = math.degrees(float(orient.get("yaw", 0.0)))

    phase = state.get("_scan_phase")
    if phase is None:
        state["_scan_phase"] = "rotando"
        state["_scan_heading_index"] = 0
        state["_scan_frames"] = []
        state["_scan_start_yaw_deg"] = current_yaw_deg
        state["_scan_settle_left"] = 0
        state["_deep_scan_request_id"] = None
        state["active_maneuver"] = None
        state["maneuver_cycles_left"] = 0
        state["maneuver_command"] = None
        phase = "rotando"

    # Congela evasion_stuck_cycles mientras dura el barrido (mismo mecanismo
    # que ya usa el brazo SLM para no descartar un pedido pendiente al SLM,
    # ver _deliberation_pending en deliberative.py/main.py): sin esto,
    # main.py seguiria acumulando/reseteando progreso durante el barrido y
    # policy_router podria dejar de enrutar aca a mitad de un rumbo (la
    # ausencia de traslacion durante el giro ya deja sin evidencia a
    # has_open_corridor(), pero congelar el contador es lo que evita que
    # record_progress() lo resetee por casualidad).
    state["_deliberation_pending"] = True

    start_yaw = float(
        state.get("_scan_start_yaw_deg") if state.get("_scan_start_yaw_deg") is not None else current_yaw_deg
    )
    heading_index = int(state.get("_scan_heading_index", 0))
    step = 360.0 / max(1, SCAN_HEADING_COUNT_DEEP)
    target_heading = _normalize_deg(start_yaw + heading_index * step)

    def _hover_cmd(rationale: str) -> Dict[str, Any]:
        cmd = action_to_command("FRENAR", guidance=guidance, telemetry=telemetry)
        cmd["rationale"] = rationale
        return cmd

    if phase == "rotando":
        yaw_err = _normalize_deg(target_heading - current_yaw_deg)
        if abs(yaw_err) <= SCAN_YAW_TOLERANCE_DEG:
            state["_scan_phase"] = "asentando"
            state["_scan_settle_left"] = SCAN_SETTLE_CYCLES_DEEP
            cmd = _hover_cmd(f"Escaneo profundo ({arm}): rumbo {target_heading:.0f}° alcanzado, asentando.")
        else:
            # Giro puro en el lugar hacia un rumbo absoluto (mismo mecanismo
            # que action_map.GIRAR_90/EVADIR_*: yaw_rate=0 + target_yaw
            # absoluto hace que AirSimClient.execute_velocity use YawMode
            # is_rate=False, ver src/hardware/airsim_client.py).
            cmd = {
                "macro_action": "ESCANEO",
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "yaw_rate": 0.0,
                "target_yaw": target_heading,
                "rationale": (
                    f"Escaneo profundo ({arm}): girando a rumbo {target_heading:.0f}° "
                    f"({heading_index + 1}/{SCAN_HEADING_COUNT_DEEP})."
                ),
            }
        state["next_action"] = "ESCANEO"
        state["velocity_command"] = cmd
        state["flight_status"] = "escaneo_profundo"
        return True

    if phase == "asentando":
        settle_left = int(state.get("_scan_settle_left", 0)) - 1
        state["next_action"] = "ESCANEO"
        state["velocity_command"] = _hover_cmd(
            f"Escaneo profundo ({arm}): asentando en rumbo {target_heading:.0f}°."
        )
        state["flight_status"] = "escaneo_profundo"
        if settle_left > 0:
            state["_scan_settle_left"] = settle_left
            return True

        # Asentamiento completo: capturar el frame de ESTE ciclo (el que
        # capture_node ya produjo antes de policy_router -- nunca se llama a
        # capture() de nuevo aca, ver principio rector §0 del plan). Se
        # guarda tambien el timestamp REAL de captura (reloj del simulador,
        # no el instante en que el VLM termine de contestar el barrido
        # completo, que puede ser varios segundos/rumbos despues) -- 2026-0901.
        capture_ts = float(telemetry.get("timestamp") or time.time())
        frames = list(state.get("_scan_frames") or [])
        frames.append((round(target_heading, 1), state.get("rgb_image"), capture_ts))
        state["_scan_frames"] = frames
        next_index = heading_index + 1
        state["_scan_heading_index"] = next_index
        state["_scan_phase"] = "rotando" if next_index < SCAN_HEADING_COUNT_DEEP else "capturado"
        return True

    if phase == "capturado":
        pending_id = state.get("_deep_scan_request_id")

        if pending_id is None:
            frames: List[Any] = (state.get("_scan_frames") or [])[:MAX_DEEP_SCAN_IMAGES]
            images_b64: List[str] = []
            labels: List[str] = []
            for i, (heading, frame, _capture_ts) in enumerate(frames):
                encoded = _encode_frame_base64(frame)
                if encoded is None:
                    continue
                images_b64.append(encoded)
                suffix = " (rumbo actual, el que viene fallando)" if i == 0 else ""
                labels.append(f"[Rumbo {heading:.0f}°]{suffix}")

            prompt = _build_deep_scan_prompt(field, telemetry, guidance, deadlock_cycles, consecutive_escapes)
            request_id = service.request(
                {
                    "mode": "deep_scan",
                    "prompt": prompt,
                    "images_b64": images_b64 or None,
                    "image_labels": labels or None,
                }
            )
            state["_deep_scan_request_id"] = request_id
            # Instrumentacion de auditoria (2026-0901): mismo mecanismo que
            # deliberative.py -- recordar prompt + frames RAW para adjuntarlos
            # cuando _apply_scan_resolution() resuelva el pedido.
            state["_pending_delib_prompt"] = prompt
            state["_pending_delib_frames"] = [(frame, capture_ts) for _heading, frame, capture_ts in frames]
            state["next_action"] = "ESCANEO"
            state["velocity_command"] = _hover_cmd(
                f"Escaneo profundo ({arm}): panorama capturado, consultando al VLM."
            )
            state["flight_status"] = "escaneo_profundo_vlm"
            return True

        result, age_ms, _has_pending = service.poll()
        if result is not None and result.request_id == pending_id:
            decision = result.parsed_decision
            clear_scan_state(state)
            if decision is not None and decision.get("macro_action") in PROMPT_ACTIONS:
                _apply_scan_resolution(
                    state, decision, result.raw_response, result.latency_ms, guidance, telemetry, arm, deadlock_cycles
                )
                return True
            print(f"[deep_scan] ({arm}) respuesta sin accion viable. Cae al escape sincronico.")
            state["_deadlock_event"] = {
                "strategy": "deep_vlm",
                "arm": arm,
                "resolved_by_scan": False,
                "cycles_to_resolve": None,
                "fell_back_to_blind": True,
            }
            return False

        if age_ms > SLM_DEEP_WATCHDOG_MS:
            print(f"[deep_scan] WATCHDOG ({arm}): sin respuesta del VLM en {age_ms:.0f}ms. Cae al escape sincronico.")
            clear_scan_state(state)
            state["_deadlock_event"] = {
                "strategy": "deep_vlm",
                "arm": arm,
                "resolved_by_scan": False,
                "cycles_to_resolve": None,
                "fell_back_to_blind": True,
            }
            return False

        state["next_action"] = "ESCANEO"
        state["velocity_command"] = _hover_cmd(
            f"Escaneo profundo ({arm}): esperando respuesta del VLM ({age_ms:.0f}ms)."
        )
        state["flight_status"] = "escaneo_profundo_vlm"
        return True

    return False


def _apply_scan_resolution(
    state: Dict[str, Any],
    decision: Dict[str, Any],
    raw_response: str,
    latency_ms: float,
    guidance: Dict[str, Any],
    telemetry: Dict[str, Any],
    arm: str,
    deadlock_cycles: int,
) -> None:
    macro = decision["macro_action"]
    cmd = action_to_command(macro, guidance=guidance, telemetry=telemetry)
    cmd["rationale"] = decision.get("rationale", "")

    deliberations_list = state.setdefault("deliberations", [])
    entry_id = len(deliberations_list) + 1
    deliberations_list.append(
        {
            "id": entry_id,
            "timestamp": time.time(),
            "arm": f"{arm}_deep_scan",
            "model": LOCAL_LLM_MODEL_NAME,
            "vision_enabled": VLM_VISION_ENABLED,
            "system_prompt": SYSTEM_PROMPT_DEEP_SCAN,
            "prompt": state.get("_pending_delib_prompt", ""),
            "raw_response": raw_response,
            "macro_action": macro,
            "rationale": decision.get("rationale", ""),
            "is_fallback": False,
            "timeout": False,
            "adherent": True,
            "used_json_schema": decision.get("used_json_schema", False),
            "latency_ms": round(latency_ms, 1),
        }
    )
    state["_last_delib_frames"] = state.get("_pending_delib_frames") or []
    state["_pending_delib_prompt"] = None
    state["_pending_delib_frames"] = None

    state["next_action"] = macro
    state["velocity_command"] = cmd
    state["flight_status"] = "escaneo_profundo_resuelto"
    state["_deadlock_event"] = {
        "strategy": "deep_vlm",
        "arm": arm,
        "resolved_by_scan": True,
        "cycles_to_resolve": deadlock_cycles,
        "fell_back_to_blind": False,
    }
    state["_deadlock_cycles"] = 0
    # Igual que el escape sincronico existente: pedir el reseteo del contador
    # de atasco a traves del lazo (WaypointTracker.reset_progress(), ver
    # main.py) -- el escaneo resuelto no debe re-disparar de inmediato.
    state["_escape_reset"] = True
    state["evasion_stuck_cycles"] = 0
    state["_deliberation_pending"] = False

    if macro in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA", "GANAR_ALTURA", "PERDER_ALTURA"):
        loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
        state["active_maneuver"] = macro
        state["maneuver_cycles_left"] = max(1, round(DEEP_SCAN_MANEUVER_DURATION_S * loop_hz))
        state["maneuver_command"] = cmd
    else:
        state["active_maneuver"] = None
        state["maneuver_cycles_left"] = 0
        state["maneuver_command"] = None
