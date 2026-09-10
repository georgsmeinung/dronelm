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

# S4 (PLAN-SLAM): slam_assess es ahora el modo por defecto y único activo.
# deep_vlm y blind quedan como legado seleccionable vía variable de entorno
# (para el factorial de S6: comparar cap.11 deep_vlm vs slam_assess).
DEADLOCK_STRATEGY = os.getenv("DEADLOCK_STRATEGY", "slam_assess")  # "slam_assess" | "deep_vlm" | "blind" (legado)
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
    "RETROCEDER",
}

# S3 (PLAN-SLAM): prompt de slam_assess. Diferencia arquitectónica clave con
# deep_vlm: no hay rotación panorámica — se envía solo el frame frontal del
# ciclo actual MÁS el historial de trayectoria acumulado (texto de S2).
# El VLM razona sobre historia de intentos + vista actual, sin maniobra extra.
SYSTEM_PROMPT_SLAM_ASSESS = (
    "Sos el cerebro deliberativo de un dron autónomo en un atasco genuino.\n"
    "Se te provee el HISTORIAL DE TRAYECTORIA (qué acciones se intentaron, cuáles "
    "produjeron avance y cuáles terminaron en stall) más el frame frontal del ciclo actual.\n"
    "Usá el historial para identificar qué direcciones están cronicamente bloqueadas y "
    "cuáles no se han explorado. Elegí UNA macro-acción que resuelva el atasco.\n\n"
    "PRIORIDAD DE EXPLORACIÓN:\n"
    "1. Si el historial marca FRENTE como 'Zona probable de bloqueo' y hay zonas con "
    "'No explorado', DEBES elegir EVADIR hacia la zona no explorada — incluso si la imagen "
    "muestra vegetación, las laterales podrían estar despejadas y no se han intentado.\n"
    "2. Los escapes verticales (GANAR/PERDER_ALTURA) solo aplican cuando las zonas laterales "
    "también fueron intentadas y fallaron.\n"
    "3. RETROCEDER aplica cuando FRENTE y ambas laterales están bloqueadas — alejarse del "
    "obstáculo crea margen para que el siguiente EVADIR tenga espacio de maniobra.\n\n"
    "Valores permitidos para macro_action:\n"
    "- MANTENER_RUMBO: el frente está despejado según lo que ves ahora (falso atasco).\n"
    "- EVADIR_IZQUIERDA / EVADIR_DERECHA: esa dirección no fue intentada o tuvo menor tasa de stall.\n"
    "- RETROCEDER: el dron está pegado al obstáculo; retroceder 3-4m para ganar margen antes de evadir.\n"
    "- GANAR_ALTURA: el historial muestra bloqueo en todos los rumbos laterales; el obstáculo es sólido.\n"
    "- PERDER_ALTURA: el historial indica vegetación arriba y hay espacio libre abajo.\n"
    "- FRENAR: ninguna dirección del historial ni la vista actual ofrecen salida; esperar.\n\n"
    "Responde ÚNICAMENTE con un objeto JSON válido:\n"
    '{"macro_action": "<ACCION>", "rationale": "<explicación breve citando el historial>"}'
)

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
    # Inclinacion actual (2026-0903, mismo pedido que deliberative.py): el
    # barrido gira en el lugar por diseno (nunca traslacion, ver §0.3 del
    # plan), asi que no tiene sentido reportar velocidad horizontal aca --
    # pero el pitch/roll ayuda a distinguir un barrido estable de uno con
    # oscilacion fisica real (rafagas, choque leve con follaje).
    orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    pitch_deg = math.degrees(float(orient.get("pitch", 0.0))) if isinstance(orient, dict) else 0.0
    roll_deg = math.degrees(float(orient.get("roll", 0.0))) if isinstance(orient, dict) else 0.0
    return (
        f"{field.summary_text()}\n\n"
        f"ATASCO: {deadlock_cycles} ciclos sin progresar hacia el waypoint.\n"
        f"Escapes verticales ya intentados en este atasco: {consecutive_escapes}.\n"
        f"OBJETIVO Y ALTITUD:\n"
        f"- {wp_str}\n"
        f"- Altitud actual: {altitude:.1f}m (Cota maxima de escape: {max_escape_alt:.1f}m)\n"
        f"- Inclinacion actual: pitch={pitch_deg:+.1f}°, roll={roll_deg:+.1f}°.\n\n"
        "INSTRUCCION:\n"
        "Elegi la macro_action que mejor resuelva el atasco a partir del panorama mostrado.\n"
        "Responde SOLO con este JSON:\n"
        '{"macro_action": "<ACCION>", "rationale": "<motivo corto citando el rumbo>"}'
    )


def _lateral_first_override(
    decision: dict,
    trajectory: "Any | None",
    telemetry: dict,
) -> dict:
    """Override determinístico sobre la recomendación del VLM.

    Override 1 — RETROCEDER (independiente de la acción VLM):
      Si FRENTE + ambas laterales tienen >=70% stall con >=3 intentos cada una,
      el dron está rodeado: retroceder sin importar lo que diga el VLM.
      (El VLM puede ver algo que parece libre pero ya fue confirmado bloqueado.)

    Override 2 — lateral-first (solo cuando VLM sugiere escape vertical):
      Si el VLM recomendó GANAR/PERDER_ALTURA pero hay laterales sin explorar,
      forzar EVADIR antes de escalar verticalmente.
    """
    if trajectory is None:
        return decision

    orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    current_hdg = math.degrees(float(orient.get("yaw", 0.0)))
    stats = trajectory.zone_stats(current_hdg)

    frente_rate = stats["FRENTE"]["stall_rate"]
    izq = stats["IZQUIERDA"]
    der = stats["DERECHA"]

    frente_att = stats["FRENTE"]["attempts"]

    # Override 1a: FRENTE + ambas laterales confirmadas bloqueadas -> RETROCEDER.
    # Requiere >=3 intentos en cada lateral para no disparar antes de explorarlas.
    if (frente_rate >= 0.70
            and izq["attempts"] >= 3 and izq["stall_rate"] >= 0.70
            and der["attempts"] >= 3 and der["stall_rate"] >= 0.70):
        print(
            f"[slam_assess] retroceder-override-1a: 3 zonas bloqueadas "
            f"(frente={frente_rate:.0%}, izq={izq['stall_rate']:.0%} "
            f"[{izq['attempts']}int], der={der['stall_rate']:.0%} "
            f"[{der['attempts']}int]) -> RETROCEDER"
        )
        return {
            "macro_action": "RETROCEDER",
            "rationale": (
                f"FRENTE {frente_rate:.0%}, "
                f"IZQUIERDA {izq['stall_rate']:.0%} ({izq['attempts']} int), "
                f"DERECHA {der['stall_rate']:.0%} ({der['attempts']} int); "
                f"todas las direcciones bloqueadas — retroceder para ganar margen."
            ),
        }

    # Override 1b: drone físicamente inmovilizado dentro del obstáculo.
    # Señal: buffer saturado de stalls FRENTE (>=90%, >=20 eventos) y ningún
    # intento lateral. EVADIR se ejecutó pero el drone no pudo rotar (colisión
    # física), así que los eventos siguen en zona FRENTE y las laterales nunca
    # acumulan intentos. Datos de prueba visual (code_version=35367d3b):
    # c433–c463: FRENTE=30/30 stalls, IZQUIERDA=0, DERECHA=0, yaw Δ<4°.
    if (frente_rate >= 0.90 and frente_att >= 20
            and izq["attempts"] == 0 and der["attempts"] == 0):
        print(
            f"[slam_assess] retroceder-override-1b: drone inmovilizado "
            f"(frente={frente_rate:.0%} [{frente_att}int], "
            f"izq=0, der=0) -> RETROCEDER"
        )
        return {
            "macro_action": "RETROCEDER",
            "rationale": (
                f"FRENTE {frente_rate:.0%} stall ({frente_att} intentos), "
                f"sin intentos laterales — drone inmovilizado en el obstáculo; "
                f"retroceder para crear margen antes de evadir."
            ),
        }

    # Override 2: VLM sugiere escape vertical pero hay laterales sin explorar.
    macro = decision.get("macro_action", "")
    if macro not in ("PERDER_ALTURA", "GANAR_ALTURA"):
        return decision

    if frente_rate < 0.70:
        return decision

    izq_att = izq["attempts"]
    der_att = der["attempts"]
    if izq_att == 0 and der_att == 0:
        lateral = "EVADIR_IZQUIERDA"
    elif izq_att == 0:
        lateral = "EVADIR_IZQUIERDA"
    elif der_att == 0:
        lateral = "EVADIR_DERECHA"
    else:
        return decision  # ambas intentadas con stall moderado — el VLM tiene mejor criterio visual

    print(
        f"[slam_assess] lateral-first override: {macro} -> {lateral} "
        f"(FRENTE={frente_rate:.0%} stall, "
        f"izq={izq_att} intentos, der={der_att} intentos)"
    )
    return {
        "macro_action": lateral,
        "rationale": (
            f"FRENTE bloqueado ({frente_rate:.0%} stall); "
            f"exploración lateral forzada hacia zona no intentada."
        ),
    }


def _slam_assess_cycle(
    state: Dict[str, Any],
    service: DeliberationService,
    field: Any,
    telemetry: Dict[str, Any],
    guidance: Dict[str, Any],
    arm: str,
    deadlock_cycles: int,
    consecutive_escapes: int,
    trajectory: "Any | None",
) -> bool:
    """Escape de deadlock basado en historial de trayectoria (S3 PLAN-SLAM).

    Sin rotación panorámica: solo el frame frontal del ciclo actual más el
    contexto textual de FlightTrajectory. Se activa en el mismo ciclo en que
    se detecta el deadlock — latencia de activación mínima.

    Devuelve True si este ciclo queda resuelto por slam_assess.
    Devuelve False si el VLM no responde o la respuesta no es válida.
    """
    state["_deliberation_pending"] = True

    def _hover_cmd(rationale: str) -> Dict[str, Any]:
        cmd = action_to_command("FRENAR", guidance=guidance, telemetry=telemetry)
        cmd["rationale"] = rationale
        return cmd

    pending_id = state.get("_deep_scan_request_id")

    if pending_id is None:
        # Construir contexto de trayectoria
        orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
        current_yaw_deg = math.degrees(float(orient.get("yaw", 0.0)))

        from .spatial_history import SLAM_CONTEXT_MAX_EVENTS
        min_events = int(os.getenv("SLAM_MIN_EVENTS_FOR_CONTEXT", "5"))

        if trajectory is not None and len(trajectory) >= min_events:
            traj_text = trajectory.trajectory_context_text(
                current_heading_deg=current_yaw_deg,
                max_events=SLAM_CONTEXT_MAX_EVENTS,
            )
        else:
            traj_text = "HISTORIAL DE TRAYECTORIA: sin datos suficientes aún (primeros ciclos de vuelo)."

        prompt = _build_deep_scan_prompt(field, telemetry, guidance, deadlock_cycles, consecutive_escapes)
        full_prompt = f"{traj_text}\n\n{prompt}"

        frame = state.get("rgb_image")
        encoded = _encode_frame_base64(frame)
        capture_ts = float(telemetry.get("timestamp") or time.time())

        request_id = service.request(
            {
                "mode": "slam_assess",
                "prompt": full_prompt,
                "images_b64": [encoded] if encoded else None,
                "image_labels": ["[Rumbo actual (frame frontal)]"] if encoded else None,
            }
        )
        state["_deep_scan_request_id"] = request_id
        state["_pending_delib_prompt"] = full_prompt
        state["_pending_delib_frames"] = [(frame, capture_ts)] if frame is not None else []
        state["next_action"] = "ESCANEO"
        state["velocity_command"] = _hover_cmd(
            f"slam_assess ({arm}): deadlock {deadlock_cycles} ciclos, consultando VLM con historial."
        )
        state["flight_status"] = "escaneo_profundo_vlm"
        return True

    result, age_ms, _has_pending = service.poll()
    if result is not None and result.request_id == pending_id:
        decision = result.parsed_decision
        clear_scan_state(state)
        if decision is not None and decision.get("macro_action") in PROMPT_ACTIONS:
            decision = _lateral_first_override(decision, trajectory, telemetry)
            _apply_scan_resolution(
                state, decision, result.raw_response, result.latency_ms,
                guidance, telemetry, arm, deadlock_cycles, trajectory,
            )
            # Sobrescribir strategy en _deadlock_event para el log
            if state.get("_deadlock_event"):
                state["_deadlock_event"]["strategy"] = "slam_assess"
            return True
        print(f"[slam_assess] ({arm}) respuesta sin acción viable. Cae al escape sincrónico.")
        state["_deadlock_event"] = {
            "strategy": "slam_assess", "arm": arm,
            "resolved_by_scan": False, "cycles_to_resolve": None,
            "fell_back_to_blind": True,
        }
        return False

    if age_ms > SLM_DEEP_WATCHDOG_MS:
        print(f"[slam_assess] WATCHDOG ({arm}): sin respuesta en {age_ms:.0f}ms. Cae al escape sincrónico.")
        clear_scan_state(state)
        state["_deadlock_event"] = {
            "strategy": "slam_assess", "arm": arm,
            "resolved_by_scan": False, "cycles_to_resolve": None,
            "fell_back_to_blind": True,
        }
        return False

    state["next_action"] = "ESCANEO"
    state["velocity_command"] = _hover_cmd(
        f"slam_assess ({arm}): esperando respuesta del VLM ({age_ms:.0f}ms)."
    )
    state["flight_status"] = "escaneo_profundo_vlm"
    return True


def deep_scan_cycle(
    state: Dict[str, Any],
    service: DeliberationService,
    field: Any,
    telemetry: Dict[str, Any],
    guidance: Dict[str, Any],
    arm: str,
    deadlock_cycles: int,
    consecutive_escapes: int,
    trajectory: "Any | None" = None,
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

    # S3/S4 (PLAN-SLAM): modo slam_assess — sin rotación panorámica, frame
    # frontal + historial de trayectoria. Delega en _slam_assess_cycle().
    if DEADLOCK_STRATEGY == "slam_assess":
        return _slam_assess_cycle(
            state, service, field, telemetry, guidance, arm,
            deadlock_cycles, consecutive_escapes, trajectory,
        )

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
    trajectory: "Any | None" = None,
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

    loop_hz = float(os.getenv("LOOP_HZ", "5.0"))
    if macro in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA", "GANAR_ALTURA", "PERDER_ALTURA"):
        # Duración adaptativa: ≥70% stall FRENTE → 3× (aggressive); ≥50% → 2×; <50% → 1×.
        # RETROCEDER maneja el caso extremo (ambas laterales bloqueadas), por lo que
        # el tope aqui baja a 3× — suficiente con vx agresivo (1.2 m/s, radio 4.58m).
        duration_multiplier = 1.0
        aggressive_evasion = False
        if trajectory is not None:
            orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
            current_hdg = math.degrees(float(orient.get("yaw", 0.0)))
            stall_rate = trajectory.frente_stall_rate(current_hdg)
            if stall_rate >= 0.70:
                aggressive_evasion = True
                duration_multiplier = 3.0
            elif stall_rate >= 0.50:
                duration_multiplier = 2.0
        if aggressive_evasion and macro in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA"):
            cmd = action_to_command(macro, guidance=guidance, telemetry=telemetry, aggressive=True)
            cmd["rationale"] = decision.get("rationale", "")
            state["velocity_command"] = cmd
        duration_s = DEEP_SCAN_MANEUVER_DURATION_S * duration_multiplier
        state["active_maneuver"] = macro
        state["maneuver_cycles_left"] = max(1, round(duration_s * loop_hz))
        state["maneuver_command"] = cmd
    elif macro == "RETROCEDER":
        # Duración fija: crear distancia suficiente del obstáculo para que el
        # siguiente EVADIR tenga margen de arco. No depende de la tasa de stall.
        duration_s = DEEP_SCAN_MANEUVER_DURATION_S * 1.5  # 2.0 × 1.5 = 3s → ~3.6m a 1.2 m/s
        state["active_maneuver"] = macro
        state["maneuver_cycles_left"] = max(1, round(duration_s * loop_hz))
        state["maneuver_command"] = cmd

        # Inyectar corner waypoint lateral para que al terminar RETROCEDER el
        # guiado no apunte de vuelta al árbol bloqueado (mismo mecanismo que
        # GIRAR_90 en deliberative.py y fsm.py).
        #
        # Jerarquía de señales para elegir la dirección lateral:
        #   1. Trayectoria: lateral con stall_rate menor (si alguna tiene intentos).
        #   2. Campo óptico: lateral con TTC mayor (más despejada según flow).
        #   3. Fallback: lateral que acorta el error de rumbo al WP.
        # El corner sigue sujeto al reactive/evasive normal mientras el drone
        # navega hacia él, así que no se requiere que el punto esté 100% libre.
        orient_r = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
        current_hdg_r = math.degrees(float(orient_r.get("yaw", 0.0)))

        turn_sign: float
        if trajectory is not None:
            stats_r = trajectory.zone_stats(current_hdg_r)
            izq_r = stats_r["IZQUIERDA"]
            der_r = stats_r["DERECHA"]
            if izq_r["attempts"] > 0 or der_r["attempts"] > 0:
                # Señal 1: trayectoria — lateral con menor stall rate
                if izq_r["stall_rate"] <= der_r["stall_rate"]:
                    turn_sign = -1.0  # IZQUIERDA menos bloqueada
                else:
                    turn_sign = 1.0   # DERECHA menos bloqueada
            else:
                # Señal 2: campo óptico — lateral con mayor TTC
                _field = state.get("obstacle_field")
                ttc_izq = (_field.sector_ttc("izquierda") or 0.0) if _field is not None else 0.0
                ttc_der = (_field.sector_ttc("derecha") or 0.0) if _field is not None else 0.0
                if ttc_izq != ttc_der:
                    turn_sign = -1.0 if ttc_izq >= ttc_der else 1.0
                else:
                    # Señal 3: acortar error de rumbo al WP
                    turn_sign = -1.0 if float(guidance.get("bearing_err_deg", 0.0)) < 0.0 else 1.0
        else:
            _field = state.get("obstacle_field")
            ttc_izq = (_field.sector_ttc("izquierda") or 0.0) if _field is not None else 0.0
            ttc_der = (_field.sector_ttc("derecha") or 0.0) if _field is not None else 0.0
            if ttc_izq != ttc_der:
                turn_sign = -1.0 if ttc_izq >= ttc_der else 1.0
            else:
                turn_sign = -1.0 if float(guidance.get("bearing_err_deg", 0.0)) < 0.0 else 1.0

        from .action_map import compute_corner_waypoint, _manhattan_snap_yaw
        lateral_yaw = _manhattan_snap_yaw(current_hdg_r, 90.0 * turn_sign)
        side_name = "IZQUIERDA" if turn_sign < 0 else "DERECHA"
        print(f"[slam_assess] retroceder-corner: rumbo lateral {lateral_yaw:.0f}° ({side_name}) inyectado como corner.")
        state["inject_corner"] = compute_corner_waypoint(
            telemetry, lateral_yaw, guidance=guidance,
            offset_m=float(os.getenv("CORNER_OFFSET_M", "12.0")),
        )
    else:
        state["active_maneuver"] = None
        state["maneuver_cycles_left"] = 0
        state["maneuver_command"] = None
