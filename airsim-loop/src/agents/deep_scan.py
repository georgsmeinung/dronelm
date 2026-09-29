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
from typing import Any, Dict, List, Optional, Tuple

from .action_map import action_to_command, compute_corner_waypoint
from .deliberation_service import DeliberationService

# S4 (PLAN-SLAM): slam_assess es ahora el modo por defecto y único activo.
# deep_vlm y blind quedan como legado seleccionable vía variable de entorno
# (para el factorial de S6: comparar cap.11 deep_vlm vs slam_assess).
DEADLOCK_STRATEGY = os.getenv("DEADLOCK_STRATEGY", "slam_assess")  # "slam_assess" | "deep_vlm" | "blind" (legado)
SCAN_HEADING_COUNT_DEEP = int(os.getenv("SCAN_HEADING_COUNT_DEEP", "4"))
SCAN_SETTLE_CYCLES_DEEP = int(os.getenv("SCAN_SETTLE_CYCLES_DEEP", "2"))
SCAN_YAW_TOLERANCE_DEG = float(os.getenv("SCAN_YAW_TOLERANCE_DEG", "5.0"))
# Timeout de rotacion en fase "rotando": si el drone no alcanza el rumbo target en
# SCAN_ROT_TIMEOUT_CYCLES ciclos, el barrido se abandona y cae al escape sincronico.
# Captura el caso de drone embebido en malla de arbol donde AirSim no puede rotar.
# 10 ciclos = 2s a 5Hz: suficiente para una rotacion libre de 90deg; si falla = mesh.
SCAN_ROT_TIMEOUT_CYCLES = int(os.getenv("SCAN_ROT_TIMEOUT_CYCLES", "10"))
SLM_DEEP_WATCHDOG_MS = float(os.getenv("SLM_DEEP_WATCHDOG_MS", "12000"))
MAX_DEEP_SCAN_IMAGES = int(os.getenv("MAX_DEEP_SCAN_IMAGES", "5"))
DEEP_SCAN_MANEUVER_DURATION_S = float(os.getenv("MANEUVER_DURATION_S", "1.0"))
VLM_IMAGE_MAX_SIZE = int(os.getenv("VLM_IMAGE_MAX_SIZE", "384"))
# Tamaño máximo de imagen para el scan panorámico (independiente del tactico).
# Menor que VLM_IMAGE_MAX_SIZE: en el scan se usan 4 imagenes simultaneas;
# reducir de 384 a 256 px ahorra ~500 vision tokens (~1s prefill en qwen2.5-vl-3b).
DEEP_SCAN_IMAGE_MAX_SIZE = int(os.getenv("DEEP_SCAN_IMAGE_MAX_SIZE", "256"))
# Espejo deliberado de deliberative.LOCAL_LLM_MODEL_NAME/VLM_VISION_ENABLED
# (mismo motivo que _encode_frame_base64 arriba: evita el import circular).
# Antes faltaban en la entrada de deliberations[] de este modulo, asi que la
# auditoria en consola mostraba "SLM TEXTO" en vez de "VLM VISION DIRECTA"
# para las decisiones del escaneo profundo (2026-0901, bug cosmetico).
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")
VLM_VISION_ENABLED = os.getenv("VLM_VISION_ENABLED", "true").lower() == "true"

# Vocabulario de acciones (solo para backward compat y el escape sincronico).
# El redesign VLM (2026-0929) ya no usa este enum como salida del modelo;
# se mantiene para el path de fallback cuando el VLM retorna el formato viejo.
PROMPT_ACTIONS = {
    "MANTENER_RUMBO",
    "EVADIR_IZQUIERDA",
    "EVADIR_DERECHA",
    "GANAR_ALTURA",
    "PERDER_ALTURA",
    "FRENAR",
    "RETROCEDER",
}

# Tipos de obstaculo reconocidos por el VLM (rediseno 2026-0929).
# El VLM ahora describe la escena en lugar de elegir acciones.
OBSTACLE_TIPOS = ["libre", "fachada", "muro", "vegetacion", "interior", "indeterminado"]

# Schema JSON para descripcion panoramica (deep_vlm: N rumbos con imagen por rumbo).
# Campos compactos (2026-0929): deg/ok/conf en lugar de relativo_deg/transitable/confianza.
# Ahorra ~40 tokens de salida vs nombres largos (×4 entradas); rationale opcional
# para no forzar al modelo a generar texto libre innecesario (~20 tokens adicionales).
_SECTOR_SCHEMA_ITEM = {
    "type": "object",
    "properties": {
        "deg":  {"type": "number"},
        "tipo": {"type": "string", "enum": OBSTACLE_TIPOS},
        "ok":   {"type": "boolean"},
        "conf": {"type": "number"},
    },
    "required": ["deg", "tipo", "ok"],
    "additionalProperties": False,
}
RESPONSE_JSON_SCHEMA_PANORAMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "panorama_description",
        "schema": {
            "type": "object",
            "properties": {
                "rumbos":    {"type": "array", "items": _SECTOR_SCHEMA_ITEM},
                "degradada": {"type": "boolean"},
                "r":         {"type": "string"},
            },
            "required": ["rumbos", "degradada"],
            "additionalProperties": False,
        },
    },
}

# Schema JSON para descripcion de escena de un solo frame (slam_assess / tactico).
_SINGLE_SECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": OBSTACLE_TIPOS},
        "ok":   {"type": "boolean"},
        "conf": {"type": "number"},
    },
    "required": ["tipo", "ok"],
    "additionalProperties": False,
}
RESPONSE_JSON_SCHEMA_SCENE = {
    "type": "json_schema",
    "json_schema": {
        "name": "scene_description",
        "schema": {
            "type": "object",
            "properties": {
                "sectores": {
                    "type": "object",
                    "properties": {
                        "frente":    _SINGLE_SECTOR_SCHEMA,
                        "izquierda": _SINGLE_SECTOR_SCHEMA,
                        "derecha":   _SINGLE_SECTOR_SCHEMA,
                    },
                    "required": ["frente", "izquierda", "derecha"],
                    "additionalProperties": False,
                },
                "degradada": {"type": "boolean"},
                "r":         {"type": "string"},
            },
            "required": ["sectores", "degradada"],
            "additionalProperties": False,
        },
    },
}

# S3 (PLAN-SLAM): prompt de slam_assess — frame frontal + historial de
# trayectoria como contexto. Rediseno 2026-0929: el VLM ya no elige acciones
# sino que describe la escena; la capa de navegacion decide a partir de la
# descripcion + las estadisticas de trayectoria.
SYSTEM_PROMPT_SLAM_ASSESS = (
    "Sos el sistema de percepcion semantica de un dron autonomo en un atasco.\n"
    "Recibes el frame frontal del ciclo actual (y el historial de trayectoria como contexto).\n"
    "Describe lo que ves en cada sector de la imagen. NO decides acciones.\n\n"
    "Para cada sector (frente, izquierda, derecha) indica:\n"
    "- tipo: la superficie u obstaculo predominante que ves\n"
    "- ok: si el dron puede avanzar en esa direccion sin colisionar\n"
    "- conf: certeza en la descripcion (0.0-1.0)\n\n"
    "Tipos validos:\n"
    "- 'libre': espacio abierto, calle, cielo, sin obstaculos visibles en los proximos 10m\n"
    "- 'fachada': superficie plana (vidrio, metal, hormigon liso, reflectante)\n"
    "- 'muro': superficie con textura (ladrillo, roca, hormigon rugoso)\n"
    "- 'vegetacion': arboles, ramas, follaje, setos\n"
    "- 'interior': imagen oscura o uniforme sin informacion util\n"
    "- 'indeterminado': no se puede determinar con la imagen disponible\n\n"
    "degradada: true si la imagen en general es muy oscura, uniforme o carece de informacion visual.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido:\n"
    '{"sectores": {"frente": {"tipo": "...", "ok": true, "conf": 0.9}, '
    '"izquierda": {...}, "derecha": {...}}, "degradada": false}'
)

# Prompt panoramico para deep_vlm — N rumbos, una imagen por rumbo.
# Rediseno 2026-0929: descripcion por rumbo en lugar de eleccion de accion.
SYSTEM_PROMPT_DEEP_SCAN = (
    "Sos el sistema de percepcion semantica de un dron autonomo en un atasco.\n"
    "Se te muestran varias imagenes tomadas girando en el lugar, cada una hacia un rumbo distinto\n"
    "(NO son fotogramas consecutivos en el tiempo -- son direcciones distintas vistas desde el mismo punto).\n"
    "Describe lo que ves en cada rumbo. NO decides acciones.\n\n"
    "Para cada imagen (identificada por su etiqueta de rumbo), genera una entrada en 'rumbos' con:\n"
    "- deg: el angulo relativo al rumbo original (0=frente actual, positivo=derecha, negativo=izquierda)\n"
    "- tipo: la superficie u obstaculo predominante que ves en ese rumbo\n"
    "- ok: si el dron puede avanzar en ese rumbo sin colisionar\n"
    "- conf: certeza en la descripcion (0.0-1.0)\n\n"
    "Tipos validos:\n"
    "- 'libre': espacio abierto, calle, cielo, sin obstaculos visibles en los proximos 10m\n"
    "- 'fachada': superficie plana (vidrio, metal, hormigon liso, reflectante)\n"
    "- 'muro': superficie con textura (ladrillo, roca, hormigon rugoso)\n"
    "- 'vegetacion': arboles, ramas, follaje, setos\n"
    "- 'interior': imagen oscura o uniforme sin informacion util\n"
    "- 'indeterminado': no se puede determinar con la imagen disponible\n\n"
    "degradada: true si la mayoria de las imagenes son oscuras o uniformes.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido:\n"
    '{"rumbos": [{"deg": 0, "tipo": "...", "ok": true, "conf": 0.9}, ...], "degradada": false}'
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


def _record_failed_scan(state: Dict[str, Any], raw_response: str, reason: str, latency_ms: float = 0.0) -> None:
    """Deja rastro auditable de un escaneo que no resolvio (2026-0928).

    Antes, un escaneo fallido (respuesta sin accion viable, watchdog) no
    escribia ninguna entrada en deliberations[] ni exponia los frames, y el
    log quedaba sin raw_response/frame_paths justo en los casos a auditar.
    """
    deliberations_list = state.setdefault("deliberations", [])
    deliberations_list.append(
        {
            "id": len(deliberations_list) + 1,
            "timestamp": time.time(),
            "arm": "deep_scan_failed",
            "model": LOCAL_LLM_MODEL_NAME,
            "vision_enabled": VLM_VISION_ENABLED,
            "system_prompt": SYSTEM_PROMPT_DEEP_SCAN,
            "prompt": state.get("_pending_delib_prompt", "") or "",
            "raw_response": raw_response or "",
            "macro_action": None,
            "rationale": reason,
            "is_fallback": True,
            "timeout": reason in ("watchdog", "perdido"),
            "adherent": False,
            "used_json_schema": False,
            "latency_ms": round(latency_ms, 1),
        }
    )
    state["_last_delib_frames"] = state.get("_pending_delib_frames") or []
    state["_pending_delib_prompt"] = None
    state["_pending_delib_frames"] = None


# --------------------------------------------------------------------------- #
# Redesign VLM 2026-0929: VLM como interprete de escena, no oraculo de accion #
# --------------------------------------------------------------------------- #

def parse_scene_description(decision: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extrae y normaliza la descripcion de escena (schema sectores) del VLM.

    Acepta nombres de campos largos (transitable/confianza/imagen_degradada) y
    compactos (ok/conf/degradada) — ambos producen el mismo dict normalizado.
    Retorna None si la respuesta no tiene el formato esperado.
    """
    if not isinstance(decision, dict):
        return None
    sectores = decision.get("sectores")
    if not isinstance(sectores, dict):
        return None
    if not all(k in sectores for k in ("frente", "izquierda", "derecha")):
        return None
    for key in ("frente", "izquierda", "derecha"):
        s = sectores.get(key)
        if not isinstance(s, dict):
            sectores[key] = {"tipo": "indeterminado", "transitable": False, "confianza": 0.5}
        else:
            if s.get("tipo") not in OBSTACLE_TIPOS:
                s["tipo"] = "indeterminado"
            # compact: ok → transitable
            transitable = s.get("transitable", s.get("ok", False))
            s["transitable"] = bool(transitable)
            # compact: conf → confianza
            confianza = s.get("confianza", s.get("conf", 0.5))
            s["confianza"] = float(confianza)
    # compact: degradada → imagen_degradada
    degradada = decision.get("imagen_degradada", decision.get("degradada", False))
    return {
        "sectores": sectores,
        "imagen_degradada": bool(degradada),
        "rationale": str(decision.get("rationale", decision.get("r", ""))),
    }


def parse_panorama_description(decision: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extrae y normaliza la descripcion panoramica (schema rumbos) del VLM.

    Acepta nombres de campos largos (relativo_deg/transitable/confianza/
    imagen_degradada_global) y compactos (deg/ok/conf/degradada).
    """
    if not isinstance(decision, dict):
        return None
    rumbos_raw = decision.get("rumbos")
    if not isinstance(rumbos_raw, list) or len(rumbos_raw) == 0:
        return None
    normalized = []
    for r in rumbos_raw:
        if not isinstance(r, dict):
            continue
        tipo = r.get("tipo", "indeterminado")
        if tipo not in OBSTACLE_TIPOS:
            tipo = "indeterminado"
        # compact: deg → relativo_deg
        deg = r.get("relativo_deg", r.get("deg", 0.0))
        # compact: ok → transitable
        transitable = r.get("transitable", r.get("ok", False))
        # compact: conf → confianza
        confianza = r.get("confianza", r.get("conf", 0.5))
        normalized.append({
            "relativo_deg": float(deg),
            "tipo": tipo,
            "transitable": bool(transitable),
            "confianza": float(confianza),
        })
    if not normalized:
        return None
    # compact: degradada → imagen_degradada_global
    degradada = decision.get("imagen_degradada_global", decision.get("degradada", False))
    return {
        "rumbos": normalized,
        "imagen_degradada_global": bool(degradada),
        "rationale": str(decision.get("rationale", decision.get("r", ""))),
    }


def scene_to_action(
    scene: Dict[str, Any],
    guidance: Dict[str, Any],
    telem: Dict[str, Any],
    trajectory: "Any | None" = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Decide macro-accion e inject_corner a partir de descripcion de escena.

    Usada por slam_assess (via _slam_assess_cycle) y por el tactico deliberativo
    (via deliberative._finalize). Incluye los overrides de trayectoria 1a/1b/1c
    que antes estaban en _apply_trajectory_overrides.

    Returns (macro_action, corner_o_None).
    """

    sectores = scene.get("sectores", {})
    frente = sectores.get("frente", {})
    izq_s = sectores.get("izquierda", {})
    der_s = sectores.get("derecha", {})
    degradada = scene.get("imagen_degradada", False)

    frente_trans = bool(frente.get("transitable", True))
    izq_trans = bool(izq_s.get("transitable", False))
    der_trans = bool(der_s.get("transitable", False))
    frente_tipo = frente.get("tipo", "indeterminado")

    bearing_err = float((guidance or {}).get("bearing_err_deg", 0.0)) if isinstance(guidance, dict) else 0.0

    # Trajectory overrides (1a/1b/1c): antes de usar la vision, verificar si
    # la historia de intentos ya demuestra bloqueo en todas las direcciones.
    if trajectory is not None:
        orient = telem.get("orientation", {}) if isinstance(telem, dict) else {}
        current_hdg = math.degrees(float(orient.get("yaw", 0.0)))
        stats = trajectory.zone_stats(current_hdg)
        f_rate = stats["FRENTE"]["stall_rate"]
        f_att = stats["FRENTE"]["attempts"]
        izq_t = stats["IZQUIERDA"]
        der_t = stats["DERECHA"]

        if (f_rate >= 0.70 and izq_t["attempts"] >= 3 and izq_t["stall_rate"] >= 0.70
                and der_t["attempts"] >= 3 and der_t["stall_rate"] >= 0.70):
            print(
                f"[scene_to_action] override-1a -> RETROCEDER "
                f"(f={f_rate:.0%} izq={izq_t['stall_rate']:.0%}[{izq_t['attempts']}] "
                f"der={der_t['stall_rate']:.0%}[{der_t['attempts']}])"
            )
            return "RETROCEDER", None

        if (f_rate >= 0.90 and f_att >= 20
                and izq_t["attempts"] == 0 and der_t["attempts"] == 0):
            print(f"[scene_to_action] override-1b -> RETROCEDER (inmovilizado)")
            return "RETROCEDER", None

        if (f_rate >= 0.90 and f_att >= 20
                and (izq_t["attempts"] == 0 or izq_t["stall_rate"] >= 0.70)
                and (der_t["attempts"] == 0 or der_t["stall_rate"] >= 0.70)):
            print(f"[scene_to_action] override-1c -> RETROCEDER (laterales fallidas)")
            return "RETROCEDER", None

    # Imagen degradada sin datos visuales utiles
    if degradada:
        # Confiar en trayectoria para elegir lateral no explorado
        if trajectory is not None:
            orient = telem.get("orientation", {}) if isinstance(telem, dict) else {}
            current_hdg = math.degrees(float(orient.get("yaw", 0.0)))
            stats = trajectory.zone_stats(current_hdg)
            if stats["IZQUIERDA"]["attempts"] == 0:
                return "EVADIR_IZQUIERDA", None
            if stats["DERECHA"]["attempts"] == 0:
                return "EVADIR_DERECHA", None
        return "GANAR_ALTURA", None

    # Frente transitable -> mantener rumbo
    if frente_trans:
        return "MANTENER_RUMBO", None

    # Frente bloqueado: elegir lateral abierto
    prefer_right = bearing_err > 0
    if izq_trans and der_trans:
        side = "EVADIR_DERECHA" if prefer_right else "EVADIR_IZQUIERDA"
        side_sign = 1.0 if side == "EVADIR_DERECHA" else -1.0
    elif der_trans:
        side = "EVADIR_DERECHA"
        side_sign = 1.0
    elif izq_trans:
        side = "EVADIR_IZQUIERDA"
        side_sign = -1.0
    else:
        # Todos bloqueados visualmente: decidir por tipo de obstaculo
        tipos = {frente_tipo, izq_s.get("tipo", "indeterminado"), der_s.get("tipo", "indeterminado")}
        if "vegetacion" in tipos and tipos <= {"vegetacion", "indeterminado", "libre"}:
            return "PERDER_ALTURA", None
        return "GANAR_ALTURA", None

    # Generar corner en la direccion de evasion
    try:
        orient_t = telem.get("orientation", {}) if isinstance(telem, dict) else {}
        hdg = math.degrees(float(orient_t.get("yaw", 0.0)))
        corner = compute_corner_waypoint(
            telem, hdg + side_sign * 90.0, guidance=guidance,
            offset_m=float(os.getenv("CORNER_OFFSET_M", "12.0")),
        )
    except Exception:
        corner = None
    return side, corner


def panorama_to_action(
    rumbos: List[Dict[str, Any]],
    trajectory: "Any | None",
    guidance: Dict[str, Any],
    telem: Dict[str, Any],
    post_retroceder: bool = False,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Decide macro-accion e inject_corner a partir de descripcion panoramica.

    post_retroceder=True omite los overrides de trayectoria (Fix N): el scan
    post-retroceso ve una vista fresca y sus stats acumuladas no deben forzar
    de nuevo RETROCEDER.

    Returns (macro_action, corner_o_None).
    """
    # Trajectory overrides (1a/1b/1c): si todas las zonas estan bloqueadas
    if trajectory is not None and not post_retroceder:
        orient = telem.get("orientation", {}) if isinstance(telem, dict) else {}
        current_hdg = math.degrees(float(orient.get("yaw", 0.0)))
        stats = trajectory.zone_stats(current_hdg)
        f_rate = stats["FRENTE"]["stall_rate"]
        f_att = stats["FRENTE"]["attempts"]
        izq_t = stats["IZQUIERDA"]
        der_t = stats["DERECHA"]

        if (f_rate >= 0.70 and izq_t["attempts"] >= 3 and izq_t["stall_rate"] >= 0.70
                and der_t["attempts"] >= 3 and der_t["stall_rate"] >= 0.70):
            print(
                f"[panorama_to_action] override-1a -> RETROCEDER "
                f"(f={f_rate:.0%} izq={izq_t['stall_rate']:.0%}[{izq_t['attempts']}] "
                f"der={der_t['stall_rate']:.0%}[{der_t['attempts']}])"
            )
            return "RETROCEDER", None
        if (f_rate >= 0.90 and f_att >= 20
                and izq_t["attempts"] == 0 and der_t["attempts"] == 0):
            print(f"[panorama_to_action] override-1b -> RETROCEDER (inmovilizado)")
            return "RETROCEDER", None
        if (f_rate >= 0.90 and f_att >= 20
                and (izq_t["attempts"] == 0 or izq_t["stall_rate"] >= 0.70)
                and (der_t["attempts"] == 0 or der_t["stall_rate"] >= 0.70)):
            print(f"[panorama_to_action] override-1c -> RETROCEDER (laterales fallidas)")
            return "RETROCEDER", None

    if not rumbos:
        return "FRENAR", None

    bearing_err = float((guidance or {}).get("bearing_err_deg", 0.0)) if isinstance(guidance, dict) else 0.0
    transitable = [r for r in rumbos if r.get("transitable", False)]

    if not transitable:
        tipos = {r.get("tipo", "indeterminado") for r in rumbos}
        if "vegetacion" in tipos and tipos <= {"vegetacion", "indeterminado"}:
            return "PERDER_ALTURA", None
        return "GANAR_ALTURA", None

    def _angular_dist(r: Dict[str, Any]) -> float:
        rel = float(r.get("relativo_deg", 0.0))
        return abs((rel - bearing_err + 180.0) % 360.0 - 180.0)

    best = min(transitable, key=_angular_dist)
    rel_deg = float(best.get("relativo_deg", 0.0))

    if abs(rel_deg) <= 30.0:
        return "MANTENER_RUMBO", None

    orient_t = telem.get("orientation", {}) if isinstance(telem, dict) else {}
    hdg = math.degrees(float(orient_t.get("yaw", 0.0)))
    side_sign = 1.0 if rel_deg > 0 else -1.0
    macro = "EVADIR_DERECHA" if rel_deg > 0 else "EVADIR_IZQUIERDA"
    try:
        corner = compute_corner_waypoint(
            telem, hdg + side_sign * 90.0, guidance=guidance,
            offset_m=float(os.getenv("CORNER_OFFSET_M", "12.0")),
        )
    except Exception:
        corner = None
    return macro, corner


def clear_scan_state(state: Dict[str, Any]) -> None:
    state["_scan_phase"] = None
    state["_scan_heading_index"] = 0
    state["_scan_frames"] = []
    state["_scan_start_yaw_deg"] = None
    state["_scan_settle_left"] = 0
    state["_scan_rot_stall"] = 0
    state["_deep_scan_request_id"] = None
    state["_deep_scan_request_ts"] = None
    state["_scan_started_ts"] = None


# Un pedido de escaneo que ya no esta pendiente en el servicio ni tiene
# resultado (lo piso otro pedido) se da por perdido tras esta gracia.
SCAN_LOST_GRACE_MS = float(os.getenv("SCAN_LOST_GRACE_MS", "3000"))


def _scan_poll(state: Dict[str, Any], service: Any, pending_id: Any):
    """(result_del_pedido | None, edad_ms_real, perdido).

    La edad se mide desde que se envio el pedido (`_deep_scan_request_ts`), no
    desde el pedido pendiente del servicio: si otro pedido lo reemplazo, la edad
    del servicio es 0 y el watchdog nunca vencia.
    """
    latest, svc_age_ms, has_pending = service.poll()
    getter = getattr(service, "get_result", None)
    result = getter(pending_id) if callable(getter) else latest
    if result is not None and result.request_id != pending_id:
        result = None
    ts = state.get("_deep_scan_request_ts")
    age_ms = (time.time() - float(ts)) * 1000.0 if ts else svc_age_ms
    lost = result is None and not has_pending and age_ms > SCAN_LOST_GRACE_MS
    return result, age_ms, lost


def _build_deep_scan_prompt(
    field: Any,
    telemetry: Dict[str, Any],
    guidance: Dict[str, Any],
    deadlock_cycles: int,
    consecutive_escapes: int,
    imu_jitter_level: str = "normal",
    imu_contact: bool = False,
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
    orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    pitch_deg = math.degrees(float(orient.get("pitch", 0.0))) if isinstance(orient, dict) else 0.0
    roll_deg = math.degrees(float(orient.get("roll", 0.0))) if isinstance(orient, dict) else 0.0

    # Señal IMU: contacto físico o vibración elevada pueden confirmar obstáculo
    # invisible al flujo óptico (árbol UE5, malla convexa que no genera OF).
    if imu_contact:
        imu_line = (
            "- IMU: CONTACTO FÍSICO DETECTADO — el sensor de aceleración registró "
            "un impacto. El flujo óptico puede NO detectar este obstáculo."
        )
    elif imu_jitter_level not in ("normal", ""):
        imu_line = f"- IMU: vibración {imu_jitter_level} — posible contacto leve con obstáculo."
    else:
        imu_line = "- IMU: normal."

    # Advertencia de obstáculo invisible: cuando hay atasco confirmado pero el
    # flujo óptico ve corredor libre, la causa más probable es una malla de
    # colisión convexa invisible (árbol UE5, cartel, etc.).
    # MANTENER_RUMBO en ese estado empuja al drone contra la malla repetidamente.
    if deadlock_cycles >= 3:
        invisible_warning = (
            "\nATENCION — POSIBLE OBSTÁCULO INVISIBLE AL SENSOR ÓPTICO:\n"
            f"El tracker lleva {deadlock_cycles} ciclos confirmando atasco (avance < 0.5m/ciclo).\n"
            "Si el historial de FRENTE muestra \"con progreso\" o \"sin stalls\", ese progreso\n"
            "es MARGINAL — firma típica de colisión con malla convexa (árbol UE5) que el\n"
            "flujo óptico no puede detectar porque no genera movimiento aparente en imagen.\n"
            "MANTENER_RUMBO en FRENTE refuerza el bloqueo físico.\n"
            "Prioriza EVADIR_IZQUIERDA, EVADIR_DERECHA o GANAR_ALTURA.\n"
        )
    else:
        invisible_warning = ""

    instruccion = (
        "INSTRUCCION:\n"
        f"Hay {deadlock_cycles} ciclos de atasco confirmado. "
        "Describe cada sector/rumbo con su tipo de obstaculo y si el dron puede avanzar.\n"
        "La capa de navegacion decidira la accion a partir de tu descripcion.\n"
        "Responde SOLO con este JSON (sin texto adicional):\n"
        '{"rumbos": [{"deg": 0, "tipo": "...", "ok": true, "conf": 0.9}, ...], "degradada": false}'
    )

    return (
        f"{field.summary_text()}\n\n"
        f"ATASCO: {deadlock_cycles} ciclos sin progresar hacia el waypoint.\n"
        f"Escapes verticales ya intentados en este atasco: {consecutive_escapes}.\n"
        f"OBJETIVO Y ALTITUD:\n"
        f"- {wp_str}\n"
        f"- Altitud actual: {altitude:.1f}m (Cota maxima de escape: {max_escape_alt:.1f}m)\n"
        f"- Inclinacion actual: pitch={pitch_deg:+.1f}°, roll={roll_deg:+.1f}°.\n"
        f"{imu_line}\n"
        f"{invisible_warning}\n"
        f"{instruccion}"
    )


def _apply_trajectory_overrides(
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

    # Override 1c: gap entre 1a y 1b — pocos intentos laterales pero todos con stall.
    # Caso típico: izq=1-2 intentos (100% stall) + der=0 → 1a falla (izq<3),
    # 1b falla (izq≠0). Diagnosticado en seed_1 c1267-1315 donde EVADIR_IZQUIERDA
    # se probó 2 veces (posición sin cambio) y DERECHA nunca se exploró.
    # Mismos umbrales de FRENTE que 1b (>=90%, >=20 eventos) para no disparar
    # prematuramente; la diferencia es que permite laterales intentadas-y-fallidas.
    if (frente_rate >= 0.90 and frente_att >= 20
            and (izq["attempts"] == 0 or izq["stall_rate"] >= 0.70)
            and (der["attempts"] == 0 or der["stall_rate"] >= 0.70)):
        print(
            f"[slam_assess] retroceder-override-1c: FRENTE saturado + laterales sin salida "
            f"(frente={frente_rate:.0%} [{frente_att}int], "
            f"izq={izq['attempts']}int={izq['stall_rate']:.0%}stall, "
            f"der={der['attempts']}int={der['stall_rate']:.0%}stall) -> RETROCEDER"
        )
        return {
            "macro_action": "RETROCEDER",
            "rationale": (
                f"FRENTE {frente_rate:.0%} stall ({frente_att} intentos); "
                f"IZQUIERDA {izq['attempts']} int/{izq['stall_rate']:.0%} stall, "
                f"DERECHA {der['attempts']} int/{der['stall_rate']:.0%} stall — "
                f"intentos laterales fallidos; retroceder para crear margen."
            ),
        }

    # Override 3: progreso frontal marginal con >=3 intentos.
    # Aplica cuando el VLM recomienda MANTENER_RUMBO, EVADIR_IZQUIERDA o
    # EVADIR_DERECHA sin rotacion real (izq_att==0, der_att==0).
    # El caso EVADIR_* sin rotacion es tan inutil como MANTENER_RUMBO: el
    # drone estrafa lateralmente pero no gira, sus eventos permanecen en
    # zona FRENTE, izq_att/der_att quedan en 0 y el bloqueo no se resuelve.
    #
    # Sub-rama 3a — firma de TECHO (autopista elevada, estructura horizontal):
    #   Altitud <= CEILING_ALT_MAX_M (default 7.5m) + laterales sin explorar.
    #   Umbral 7.5m cubre el crucero tipico de 6m bajo autopista elevada.
    #   Se usa altitud en vez de stall_rate porque EVADIR estrafa sin rotar,
    #   inflando frente_stall_rate a 0.40-1.00 incluso bajo un techo.
    #   PERDER_ALTURA libera la estructura sin requerir rotacion.
    #
    # Sub-rama 3b — firma de MURO/ARBOL (obstáculo frontal, altitud alta):
    #   Explorar laterales por rotacion; si ambas fallidas -> GIRAR_90.
    pos_tel = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    current_alt_m = abs(float(pos_tel.get("z", 0.0))) if isinstance(pos_tel, dict) else 0.0

    macro = decision.get("macro_action", "")
    if macro in ("MANTENER_RUMBO", "EVADIR_IZQUIERDA", "EVADIR_DERECHA"):
        frente_stats = stats["FRENTE"]
        frente_att3 = frente_stats["attempts"]
        _MARGINAL3 = float(os.getenv("SLAM_MARGINAL_PROGRESS_M", "0.28"))
        if frente_att3 >= 3 and frente_stats.get("avg_prog", _MARGINAL3) < _MARGINAL3:
            izq_att3 = izq["attempts"]
            der_att3 = der["attempts"]
            frente_stall3 = frente_stats.get("stall_rate", 0.0)
            _CEILING_ALT_MAX = float(os.getenv("SLAM_CEILING_ALT_MAX_M", "7.5"))
            avg_p3 = frente_stats.get("avg_prog", 0.0)

            # 3a: techo — altitud dentro del rango + laterales sin rotar -> bajar
            if current_alt_m <= _CEILING_ALT_MAX and izq_att3 == 0 and der_att3 == 0:
                override3 = "PERDER_ALTURA"
                reason3 = (
                    f"alt={current_alt_m:.1f}m <= {_CEILING_ALT_MAX:.1f}m "
                    f"con avance {avg_p3:.2f}m/ciclo (stall={frente_stall3:.0%}) "
                    f"— firma de techo; bajar para liberar."
                )
            # 3b: muro/arbol — explorar laterales por rotacion
            elif izq_att3 == 0:
                override3 = "EVADIR_IZQUIERDA"
                reason3 = f"avance {avg_p3:.2f}m/ciclo < {_MARGINAL3:.2f}m — lateral izq sin explorar."
            elif der_att3 == 0:
                override3 = "EVADIR_DERECHA"
                reason3 = f"avance {avg_p3:.2f}m/ciclo < {_MARGINAL3:.2f}m — lateral der sin explorar."
            else:
                override3 = "GIRAR_90"
                reason3 = f"avance {avg_p3:.2f}m/ciclo < {_MARGINAL3:.2f}m — laterales agotadas; girar."

            print(
                f"[slam_assess] override-3({'techo' if override3 == 'PERDER_ALTURA' else 'muro'}): "
                f"VLM recomendo {macro} pero FRENTE avg_prog={avg_p3:.2f}m/ciclo "
                f"(stall={frente_stall3:.0%}, alt={current_alt_m:.1f}m, izq={izq_att3}, der={der_att3}) -> {override3}"
            )
            return {
                "macro_action": override3,
                "rationale": (
                    f"{macro} rechazado: FRENTE {frente_att3} intentos, {reason3}"
                ),
            }

    # Override 2: VLM sugiere escape vertical pero hay laterales sin explorar.
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
        # Pre-scan Overrides 1b/1c: drone bloqueado sin salida (FRENTE saturado,
        # laterales inexploradas o fallidas). Evaluar ANTES de enviar al VLM para
        # no quedar en ESCANEO infinito si el VLM cuelga.
        # Excepción: si _post_retroceder_corner_pending está activo, el RETROCEDER
        # ya se ejecutó; dejar correr el VLM para que elija la dirección del corner.
        if trajectory is not None and not state.get("_post_retroceder_corner_pending"):
            orient_pre = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
            yaw_pre = math.degrees(float(orient_pre.get("yaw", 0.0)))
            _dummy_decision = {"macro_action": "MANTENER_RUMBO", "rationale": "pre-scan"}
            _pre_override = _apply_trajectory_overrides(_dummy_decision, trajectory, telemetry)
            if _pre_override.get("macro_action") == "RETROCEDER":
                print(f"[slam_assess] pre-scan override: RETROCEDER directo (sin VLM), "
                      f"drone bloqueado yaw={yaw_pre:.0f}°.")
                clear_scan_state(state)
                _apply_scan_resolution(
                    state, _pre_override, "pre-scan-override", 0.0,
                    guidance, telemetry, arm, deadlock_cycles, trajectory,
                )
                return True

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

        imu_jitter = str(state.get("imu_jitter_level") or "normal")
        imu_contact = bool(state.get("imu_contact_event"))
        prompt = _build_deep_scan_prompt(
            field, telemetry, guidance, deadlock_cycles, consecutive_escapes,
            imu_jitter_level=imu_jitter, imu_contact=imu_contact,
        )
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
        state["_deep_scan_request_ts"] = time.time()
        state["_pending_delib_prompt"] = full_prompt
        state["_pending_delib_frames"] = [(frame, capture_ts)] if frame is not None else []
        state["next_action"] = "ESCANEO"
        state["velocity_command"] = _hover_cmd(
            f"slam_assess ({arm}): deadlock {deadlock_cycles} ciclos, consultando VLM con historial."
        )
        state["flight_status"] = "escaneo_profundo_vlm"
        return True

    result, age_ms, lost = _scan_poll(state, service, pending_id)
    if result is not None and result.request_id == pending_id:
        decision = result.parsed_decision
        clear_scan_state(state)

        # Rediseno 2026-0929: intentar parsear como descripcion de escena primero.
        # Backward compat: si falla, intentar macro_action del formato viejo.
        scene = parse_scene_description(decision)
        if scene is not None:
            macro, corner = scene_to_action(scene, guidance, telemetry, trajectory)
            nav_decision = {
                "macro_action": macro,
                "rationale": scene.get("rationale", ""),
                "used_json_schema": (decision or {}).get("used_json_schema", False),
            }
            print(f"[slam_assess] escena VLM -> nav decide: {macro} ({scene.get('rationale','')[:60]})")
        elif decision is not None and decision.get("macro_action") in PROMPT_ACTIONS:
            original_macro = decision.get("macro_action")
            nav_decision = _apply_trajectory_overrides(decision, trajectory, telemetry)
            if nav_decision.get("macro_action") != original_macro:
                print(f"[slam_assess] compat-override: {original_macro} -> {nav_decision.get('macro_action')}")
            macro = nav_decision.get("macro_action", "FRENAR")
            corner = None
        else:
            print(f"[slam_assess] ({arm}) respuesta sin accion viable. Cae al escape sincronico.")
            _record_failed_scan(state, result.raw_response, "sin_accion_viable", result.latency_ms)
            state["_deadlock_event"] = {
                "strategy": "slam_assess", "arm": arm,
                "resolved_by_scan": False, "cycles_to_resolve": None,
                "fell_back_to_blind": True,
            }
            return False

        _apply_scan_resolution(
            state, nav_decision, result.raw_response, result.latency_ms,
            guidance, telemetry, arm, deadlock_cycles, trajectory,
        )
        if state.get("_deadlock_event"):
            state["_deadlock_event"]["strategy"] = "slam_assess"

        # Aplicar corner de navegacion (antes de Fix 17 para que Fix 17 lo pueda sobrescribir)
        if corner and not state.get("inject_corner"):
            state["inject_corner"] = corner

        # Fix 17: corner post-RETROCEDER usando bearing al WP como referencia,
        # perpendicular al path, en el lado OPUESTO a la recomendacion de navegacion.
        # (Invariante confirmado seed_1: bearing_to_wp estable geometricamente.)
        _had_retro = bool(state.pop("_post_retroceder_corner_pending", False))
        macro_post = state.get("next_action", "")
        if _had_retro and macro_post not in ("RETROCEDER", "GANAR_ALTURA", "PERDER_ALTURA"):
            orient_pc = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
            hdg_pc = math.degrees(float(orient_pc.get("yaw", 0.0)))
            bearing_err_pc = float(
                (guidance or {}).get("bearing_err_deg", 0.0)
            ) if isinstance(guidance, dict) else 0.0
            bearing_to_wp = hdg_pc + bearing_err_pc
            _sign = 1.0 if macro_post == "EVADIR_IZQUIERDA" else -1.0
            corner_yaw = bearing_to_wp + _sign * 90.0
            state["inject_corner"] = compute_corner_waypoint(
                telemetry, corner_yaw, guidance=guidance,
                offset_m=float(os.getenv("CORNER_OFFSET_M", "12.0")),
            )
            side = "DER(opp-IZQ)" if _sign > 0 else "IZQ(opp-DER)"
            print(
                f"[slam_assess] retroceder-corner fix17: "
                f"hdg={hdg_pc:.0f} bear_err={bearing_err_pc:.0f} "
                f"bearing_to_wp={bearing_to_wp:.0f}{_sign:+.0f}x90"
                f"={corner_yaw:.0f} ({side}) nav={macro_post}."
            )

        return True

    if lost or age_ms > SLM_DEEP_WATCHDOG_MS:
        print(f"[slam_assess] WATCHDOG ({arm}): {'pedido perdido' if lost else 'sin respuesta'} en {age_ms:.0f}ms. Cae al escape sincrónico.")
        clear_scan_state(state)
        _record_failed_scan(state, "", "perdido" if lost else "watchdog", age_ms)
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
        # Fix M (retroceder-first): antes de iniciar el barrido panoramico de
        # 40+ ciclos, el drone retrocede para alejarse del obstaculo. Si el
        # barrido empieza EN la fachada, el drone hace hover durante ~8s contra
        # el muro -> deriva fisicamente y choca (min_obstacle_dist < 0.30m).
        # El retroceso da: distancia segura + vista despejada para el VLM.
        # Solo aplica al primer scan (no post-retroceder, no slam_assess).
        # El post-retroceso scan ya ve la cara del edificio desde atras ->
        # VLM elige un corredor lateral -> inject_corner lo convierte en WP.
        if not state.get("_post_retroceder_corner_pending"):
            loop_hz_m = float(os.getenv("LOOP_HZ", "5.0"))
            _retro_factor_m = float(os.getenv("RETROCEDER_DURATION_FACTOR", "2.5"))
            duration_s_m = DEEP_SCAN_MANEUVER_DURATION_S * _retro_factor_m
            cmd_m = action_to_command("RETROCEDER", guidance=guidance, telemetry=telemetry)
            cmd_m["rationale"] = (
                "Fix M: retrocediendo antes del escaneo panoramico "
                "para evitar deriva contra la fachada durante el barrido."
            )
            state["next_action"] = "RETROCEDER"
            state["velocity_command"] = cmd_m
            state["active_maneuver"] = "RETROCEDER"
            state["maneuver_cycles_left"] = max(1, round(duration_s_m * loop_hz_m))
            state["maneuver_command"] = cmd_m
            state["_post_retroceder_corner_pending"] = True
            state["_escape_reset"] = True
            state["evasion_stuck_cycles"] = 0
            state["_deliberation_pending"] = False
            state["flight_status"] = "retroceder_pre_scan"
            print(
                f"[deep_vlm] Fix M: RETROCEDER pre-scan "
                f"({duration_s_m:.0f}s) antes de iniciar barrido panoramico."
            )
            return True

        # Post-retroceder: iniciar el barrido
        state["_scan_phase"] = "rotando"
        state["_scan_started_ts"] = time.time()
        state["_scan_heading_index"] = 0
        state["_scan_frames"] = []
        state["_scan_start_yaw_deg"] = current_yaw_deg
        state["_scan_settle_left"] = 0
        state["_scan_rot_stall"] = 0
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
            state["_scan_rot_stall"] = 0
            cmd = _hover_cmd(f"Escaneo profundo ({arm}): rumbo {target_heading:.0f}° alcanzado, asentando.")
        else:
            # Timeout de rotacion: si el drone no puede girar (malla de arbol),
            # abandonar el barrido y caer al escape sincronico (GANAR_ALTURA).
            rot_stall = int(state.get("_scan_rot_stall") or 0) + 1
            state["_scan_rot_stall"] = rot_stall
            if rot_stall > SCAN_ROT_TIMEOUT_CYCLES:
                print(
                    f"[deep_scan] ({arm}) timeout de rotacion: yaw_err={yaw_err:.0f}° "
                    f"sin corregir en {rot_stall} ciclos. Cae al escape sincronico."
                )
                clear_scan_state(state)
                state["_deadlock_event"] = {
                    "strategy": "deep_vlm",
                    "arm": arm,
                    "resolved_by_scan": False,
                    "cycles_to_resolve": None,
                    "fell_back_to_blind": True,
                }
                return False
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
                    f"({heading_index + 1}/{SCAN_HEADING_COUNT_DEEP}, intento {rot_stall}/{SCAN_ROT_TIMEOUT_CYCLES})."
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
                encoded = _encode_frame_base64(frame, max_size=DEEP_SCAN_IMAGE_MAX_SIZE)
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
            state["_deep_scan_request_ts"] = time.time()
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

        result, age_ms, lost = _scan_poll(state, service, pending_id)
        if result is not None and result.request_id == pending_id:
            decision = result.parsed_decision
            clear_scan_state(state)
            _had_retro_pending = bool(state.get("_post_retroceder_corner_pending", False))

            # Rediseno 2026-0929: intentar parsear como descripcion panoramica primero.
            pano = parse_panorama_description(decision)
            if pano is not None:
                macro, corner = panorama_to_action(
                    pano["rumbos"], trajectory, guidance, telemetry,
                    post_retroceder=_had_retro_pending,  # Fix N
                )
                # Romper loop RETROCEDER: si panorama tambien da RETROCEDER, forzar GANAR_ALTURA.
                if _had_retro_pending and macro == "RETROCEDER":
                    print("[deep_vlm] post-RETROCEDER nav insiste en RETROCEDER - forzando GANAR_ALTURA.")
                    macro = "GANAR_ALTURA"
                    corner = None
                nav_decision = {
                    "macro_action": macro,
                    "rationale": pano.get("rationale", ""),
                    "used_json_schema": (decision or {}).get("used_json_schema", False),
                }
                print(f"[deep_vlm] panorama VLM -> nav decide: {macro} ({pano.get('rationale','')[:60]})")
            elif decision is not None and decision.get("macro_action") in PROMPT_ACTIONS:
                # Backward compat: VLM retorno formato viejo con macro_action.
                if _had_retro_pending and decision.get("macro_action") == "RETROCEDER":
                    print("[deep_vlm] compat: post-RETROCEDER insiste en RETROCEDER - forzando GANAR_ALTURA.")
                    decision = {"macro_action": "GANAR_ALTURA",
                                "rationale": "Esquina cerrada; subir para superar obstaculos."}
                if not _had_retro_pending:
                    original_macro = decision.get("macro_action")
                    decision = _apply_trajectory_overrides(decision, trajectory, telemetry)
                    if decision.get("macro_action") != original_macro:
                        print(f"[deep_vlm] compat-override: {original_macro} -> {decision.get('macro_action')}")
                nav_decision = decision
                macro = nav_decision.get("macro_action", "FRENAR")
                corner = None
            else:
                print(f"[deep_scan] ({arm}) respuesta sin accion viable. Cae al escape sincronico.")
                _record_failed_scan(state, result.raw_response, "sin_accion_viable", result.latency_ms)
                state["_deadlock_event"] = {
                    "strategy": "deep_vlm",
                    "arm": arm,
                    "resolved_by_scan": False,
                    "cycles_to_resolve": None,
                    "fell_back_to_blind": True,
                }
                return False

            _apply_scan_resolution(
                state, nav_decision, result.raw_response, result.latency_ms,
                guidance, telemetry, arm, deadlock_cycles, trajectory,
            )
            if corner and not state.get("inject_corner"):
                state["inject_corner"] = corner

            # Fix 17: corner post-RETROCEDER usando bearing al WP como referencia,
            # perpendicular al path, en el lado OPUESTO a la recomendacion de navegacion.
            macro_post = state.get("next_action", "")
            state.pop("_post_retroceder_corner_pending", None)
            if _had_retro_pending and macro_post not in ("RETROCEDER", "GANAR_ALTURA", "PERDER_ALTURA"):
                orient_pc = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
                hdg_pc = math.degrees(float(orient_pc.get("yaw", 0.0)))
                bearing_err_pc = float(
                    (guidance or {}).get("bearing_err_deg", 0.0)
                ) if isinstance(guidance, dict) else 0.0
                bearing_to_wp = hdg_pc + bearing_err_pc
                _sign = 1.0 if macro_post == "EVADIR_IZQUIERDA" else -1.0
                corner_yaw = bearing_to_wp + _sign * 90.0
                state["inject_corner"] = compute_corner_waypoint(
                    telemetry, corner_yaw, guidance=guidance,
                    offset_m=float(os.getenv("CORNER_OFFSET_M", "12.0")),
                )
                print(
                    f"[deep_vlm] retroceder-corner fix17: "
                    f"hdg={hdg_pc:.0f} bear_err={bearing_err_pc:.0f} "
                    f"bearing_to_wp={bearing_to_wp:.0f}{_sign:+.0f}x90"
                    f"={corner_yaw:.0f} nav={macro_post}."
                )
            return True

        if lost or age_ms > SLM_DEEP_WATCHDOG_MS:
            print(f"[deep_scan] WATCHDOG ({arm}): {'pedido perdido' if lost else 'sin respuesta del VLM'} en {age_ms:.0f}ms. Cae al escape sincronico.")
            clear_scan_state(state)
            _record_failed_scan(state, "", "perdido" if lost else "watchdog", age_ms)
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
        "vlm_macro": macro,
        "vlm_rationale": str(decision.get("rationale", ""))[:300],
        "vlm_raw_response": (raw_response or "")[:2000],
    }
    state["_deadlock_cycles"] = 0
    # Igual que el escape sincronico existente: pedir el reseteo del contador
    # de atasco a traves del lazo (WaypointTracker.reset_progress(), ver
    # main.py) -- el escaneo resuelto no debe re-disparar de inmediato.
    state["_escape_reset"] = True
    state["evasion_stuck_cycles"] = 0
    state["_deliberation_pending"] = False

    loop_hz = float(os.getenv("LOOP_HZ", "5.0"))

    # Fix L/L2: deteccion de loops EVADIR sin progreso en deep_vlm mode.
    #
    # Fix L  — oscilacion: VLM alterna DER->IZQ->DER (o viceversa) sin
    #   producir avance neto. Cuando el lado recomendado es OPUESTO al ultimo
    #   despachado, escalamos a RETROCEDER.
    # Fix L2 — mismo lado repetido: VLM recomienda IZQ->IZQ->IZQ (o DER x3)
    #   sin producir avance al WP. Cuando el mismo lado se repite >=LIMIT veces
    #   consecutivas, tambien escalamos a RETROCEDER.
    #
    # Ambos caminos caen en RETROCEDER -> _post_retroceder_corner_pending=True
    # -> scan post-retroceso ve vista despejada -> produce inject_corner.
    _EVADIR_REPEAT_LIMIT = int(os.getenv("SCAN_EVADIR_REPEAT_LIMIT", "2"))

    def _escalate_retroceder(reason: str) -> None:
        nonlocal macro, decision, cmd
        print(f"[deep_vlm] Fix L/L2: {reason}; escalando a RETROCEDER.")
        macro = "RETROCEDER"
        decision = {
            "macro_action": "RETROCEDER",
            "rationale": reason + ". Retrocediendo para salir del canton.",
        }
        cmd = action_to_command(macro, guidance=guidance, telemetry=telemetry)
        cmd["rationale"] = decision["rationale"]
        state["velocity_command"] = cmd
        state["next_action"] = macro
        state.pop("_scan_last_evadir_dir", None)
        state.pop("_scan_evadir_count", None)

    if macro in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA"):
        last_dir = state.get("_scan_last_evadir_dir")
        opposite = "EVADIR_IZQUIERDA" if macro == "EVADIR_DERECHA" else "EVADIR_DERECHA"
        if last_dir == opposite:
            # Fix L: oscilacion lateral
            _escalate_retroceder(
                "oscilacion " + last_dir + " -> " + macro + " (deep_vlm)"
            )
        elif last_dir == macro:
            # Fix L2: mismo lado repetido
            count = int(state.get("_scan_evadir_count", 0)) + 1
            if count >= _EVADIR_REPEAT_LIMIT:
                _escalate_retroceder(
                    macro + " repetido " + str(count + 1) + "x sin progreso"
                )
            else:
                state["_scan_evadir_count"] = count
        else:
            # Primera vez o cambio de lado sin oscilacion (caso nuevo)
            state["_scan_last_evadir_dir"] = macro
            state["_scan_evadir_count"] = 0
    else:
        state.pop("_scan_last_evadir_dir", None)
        state.pop("_scan_evadir_count", None)

    if macro in ("EVADIR_DERECHA", "EVADIR_IZQUIERDA", "GANAR_ALTURA", "PERDER_ALTURA"):
        # Duracion adaptativa: >=70% stall FRENTE -> 2x; >=50% -> 1.5x; <50% -> 1x.
        # Fix O: se elimino aggressive=True (vx=1.2m/s) para evitar que el drone
        # estrafe a alta velocidad junto a fachadas con molduras/escaleras de incendio
        # en pasillos urbanos estrechos. La velocidad estandar (0.8m/s) es suficiente
        # para el EVADIR post-scan dado que inject_corner guia la salida real.
        # El tope baja a 2x (antes 3x) por el mismo motivo de seguridad en corridors.
        duration_multiplier = 1.0
        if trajectory is not None:
            orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
            current_hdg = math.degrees(float(orient.get("yaw", 0.0)))
            stall_rate = trajectory.frente_stall_rate(current_hdg)
            if stall_rate >= 0.70:
                duration_multiplier = 2.0
            elif stall_rate >= 0.50:
                duration_multiplier = 1.5
        duration_s = DEEP_SCAN_MANEUVER_DURATION_S * duration_multiplier
        state["active_maneuver"] = macro
        state["maneuver_cycles_left"] = max(1, round(duration_s * loop_hz))
        state["maneuver_command"] = cmd
    elif macro == "RETROCEDER":
        # Fix 12: duración aumentada para salir de la collision mesh "burbuja".
        # Con factor 1.5: 2.0×1.5=3s → ~3m a 1.2m/s — insuficiente para meshes
        # de 4-5m de radio (diagnosticado seed_1: c529-c1186, retroceso promedio 3m,
        # drone volvía al mismo árbol en todos los casos). Factor 2.5: 5s → ~6m.
        _retro_factor = float(os.getenv("RETROCEDER_DURATION_FACTOR", "2.5"))
        # Fix 14: RETROCEDER adaptativo — si la trayectoria registra stalls en la
        # zona ATRÁS (≥2 intentos, ≥70% stall), hay un árbol detrás confirmado por
        # el buffer de vuelo. En ese caso reducir el factor para no colisionar por
        # retroceso ciego (collision mesh "burbuja" puede existir en ambas dirs).
        if trajectory is not None:
            orient_r = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
            hdg_r = math.degrees(float(orient_r.get("yaw", 0.0)))
            atras = trajectory.zone_stats(hdg_r).get("ATRÁS", {"attempts": 0, "stall_rate": 0.0})
            if atras["attempts"] >= 2 and atras["stall_rate"] >= 0.70:
                _retro_factor = min(_retro_factor, 1.5)
                print(
                    f"[slam_assess] retroceder-fix14: ATRÁS bloqueado "
                    f"({atras['stall_rate']:.0%} stall, {atras['attempts']} int) "
                    f"-> factor reducido a {_retro_factor} para evitar colision trasera."
                )
        duration_s = DEEP_SCAN_MANEUVER_DURATION_S * _retro_factor  # nominal 2.0×2.5=5s → ~6m
        state["active_maneuver"] = macro
        state["maneuver_cycles_left"] = max(1, round(duration_s * loop_hz))
        state["maneuver_command"] = cmd

        # Fix 11: no inyectar el corner a ciegas al dispatchar RETROCEDER.
        # El corner 90° fijo podía llevar el drone a otro árbol (diagnosticado
        # seed_1 c929→c1067). En cambio, marcar pendiente y esperar al scan
        # VLM post-RETROCEDER: ese scan verá la vista despejada tras el retroceso
        # y elegirá una dirección limpia hacia el WP (ver _slam_assess_cycle).
        state["_post_retroceder_corner_pending"] = True
        print("[slam_assess] retroceder-corner: corner diferido al scan post-RETROCEDER.")
    else:
        state["active_maneuver"] = None
        state["maneuver_cycles_left"] = 0
        state["maneuver_command"] = None
