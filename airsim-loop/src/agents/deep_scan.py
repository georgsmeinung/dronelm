# Barrido panoramico + VLM ante un deadlock (DEADLOCK_STRATEGY=deep_vlm, default).
#
# El dron gira en el lugar a SCAN_HEADING_COUNT_DEEP rumbos, captura un frame por rumbo (el que
# capture_node ya produjo; nunca vuelve a capturar ni pide profundidad) y hace UNA consulta al VLM.
# El modelo describe cada imagen (tipo de obstaculo, transitable o no); el codigo conoce el rumbo
# absoluto medido de cada imagen y elige, entre las transitables, la mas cercana a la meta: la
# decision es una sub-meta en coordenadas del mundo (panorama_to_subgoal).
#
# 2026-0930: se movio a legacy/deep_scan_v2.py todo lo que no aportaba segun la evidencia de las
# corridas: slam_assess, scene_to_action, los overrides de trayectoria (1a/1b/1c/2/3) y los Fix
# M/L/L2/11/12/14/17. DEADLOCK_STRATEGY=blind se resuelve en graph.py sin consultar al VLM.
from __future__ import annotations

import base64
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .subgoal import VLM_SUBGOAL_DIST_M, build_subgoal  # reglas comunes con la capa estrategica
from .action_map import action_to_command
from .deliberation_service import DeliberationService

# "deep_vlm" (barrido + VLM) | "blind" (sin VLM: escape determinista en graph.py).
DEADLOCK_STRATEGY = os.getenv("DEADLOCK_STRATEGY", "deep_vlm")
if DEADLOCK_STRATEGY not in ("deep_vlm", "blind"):
    raise ValueError(
        f"DEADLOCK_STRATEGY={DEADLOCK_STRATEGY!r} no soportada: usar deep_vlm o blind "
        "(slam_assess esta en src/agents/legacy/deep_scan_v2.py)."
    )
SCAN_HEADING_COUNT_DEEP = int(os.getenv("SCAN_HEADING_COUNT_DEEP", "4"))
# Cerca del WP real (m) no se barre: mismo umbral que la capa estrategica (vlm_strategic.VLM_NEAR_WP_M).
VLM_NEAR_WP_M = float(os.getenv("VLM_NEAR_WP_M", "8.0"))
# Seleccion de salida en deadlock (2026-10-01). Un deadlock es evidencia de que el rumbo que el dron
# intentaba no funciona: entre los rumbos que el VLM marco transitables se descartan (1) los que caen a
# menos de SCAN_FAILED_SECTOR_DEG del rumbo que fallo y (2) los ya probados en deadlocks anteriores a
# menos de SCAN_REPEAT_RADIUS_M, para el mismo WP. Con deadlocks repetidos en la zona se elige el rumbo
# libre mas distinto de los ya probados (exploracion), no el mas cercano a la meta. El modelo sigue
# decidiendo que esta libre; esto solo elige entre sus opciones con lo que el dron ya comprobo.
SCAN_FAILED_SECTOR_DEG = float(os.getenv("SCAN_FAILED_SECTOR_DEG", "45.0"))
SCAN_REPEAT_RADIUS_M = float(os.getenv("SCAN_REPEAT_RADIUS_M", "10.0"))
SCAN_HISTORY_MAX = int(os.getenv("SCAN_HISTORY_MAX", "12"))
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
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")

# Tipos de obstaculo reconocidos por el VLM (rediseno 2026-0929).
# El VLM ahora describe la escena en lugar de elegir acciones.
OBSTACLE_TIPOS = ["libre", "fachada", "muro", "vegetacion", "interior", "indeterminado"]

# Schema JSON para descripcion panoramica (deep_vlm: N rumbos con imagen por rumbo).
# 2026-0930: cada entrada se identifica por el NUMERO de imagen ("img", 1..N), no por un angulo.
# Antes el modelo devolvia "deg" a veces absoluto (copiando la etiqueta "[Rumbo -53 deg]") y a veces
# relativo, y el parser lo interpretaba siempre como relativo: "el camino a la meta esta libre" se
# convertia en EVADIR_IZQUIERDA. El rumbo real de cada imagen lo conoce el codigo, no el modelo.
_SECTOR_SCHEMA_ITEM = {
    "type": "object",
    "properties": {
        "img":  {"type": "integer", "minimum": 1},
        "tipo": {"type": "string", "enum": OBSTACLE_TIPOS},
        "ok":   {"type": "boolean"},
        "conf": {"type": "number"},
    },
    "required": ["img", "tipo", "ok"],
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

# Prompt panoramico para deep_vlm — N rumbos, una imagen por rumbo.
# 2026-0930: el ejemplo ya no trae valores concretos ("ok": true, "conf": 0.9): el modelo 3B los
# copiaba (52 de 53 respuestas sectoriales decian "frente transitable", incluso a 0.1 m de un muro).
SYSTEM_PROMPT_DEEP_SCAN = (
    "Sos el sistema de percepcion semantica de un dron autonomo que vuela a baja altura en un entorno urbano.\n"
    "Se te muestran varias imagenes numeradas, tomadas girando en el lugar, cada una hacia un rumbo "
    "distinto (NO son fotogramas consecutivos en el tiempo).\n"
    "Describe lo que ves en cada imagen. NO decides acciones.\n\n"
    "Para CADA imagen genera exactamente una entrada en 'rumbos', en el mismo orden, con:\n"
    "- img: el numero de la imagen (1, 2, ...)\n"
    "- tipo: la superficie u obstaculo predominante A LA ALTURA DEL DRON en los proximos 15 m\n"
    "- ok: true SOLO si el dron puede volar recto en esa direccion 15 m sin chocar; false si hay "
    "edificio, muro, fachada, arbol o vegetacion, puente o estructura elevada, cornisa o techo cerca\n"
    "- conf: certeza de 0.0 a 1.0\n\n"
    "Tipos validos:\n"
    "- 'libre': calle, plaza, cielo, espacio abierto a la altura del dron\n"
    "- 'fachada': superficie plana (vidrio, metal, hormigon liso, reflectante)\n"
    "- 'muro': superficie con textura (ladrillo, roca, hormigon rugoso), guardarrail, baranda\n"
    "- 'vegetacion': arboles, ramas, follaje, setos\n"
    "- 'interior': imagen oscura o uniforme sin informacion util\n"
    "- 'indeterminado': no se puede determinar con la imagen disponible\n\n"
    "degradada: true si la mayoria de las imagenes son oscuras o uniformes.\n\n"
    "Responde UNICAMENTE con JSON: {\"rumbos\": [{\"img\": <n>, \"tipo\": <tipo>, \"ok\": <bool>, "
    "\"conf\": <0-1>}, ...], \"degradada\": <bool>}"
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
            "vision_enabled": True,
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
        img = r.get("img")
        try:
            img = int(img) if img is not None else None
        except (TypeError, ValueError):
            img = None
        normalized.append({
            "img": img,
            "relativo_deg": float(deg or 0.0),
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


def assign_panorama_entries(rumbos: List[Dict[str, Any]], n_images: int) -> List[Optional[Dict[str, Any]]]:
    """Asigna cada entrada del modelo a una imagen (indice 0..n-1).

    Por "img" si el modelo lo dio y es valido; si no, por orden. Entradas de mas (el modelo a veces
    inventa rumbos que no se le mostraron) se descartan; imagenes sin entrada quedan en None."""
    out: List[Optional[Dict[str, Any]]] = [None] * max(0, n_images)
    pending: List[Dict[str, Any]] = []
    for r in rumbos:
        img = r.get("img")
        if isinstance(img, int) and 1 <= img <= n_images and out[img - 1] is None:
            out[img - 1] = r
        else:
            pending.append(r)
    for r in pending:
        for i in range(n_images):
            if out[i] is None:
                out[i] = r
                break
    return out


def panorama_to_subgoal(
    rumbos: List[Dict[str, Any]],
    headings_world_deg: List[float],
    telem: Dict[str, Any],
    goal_bearing_deg: Optional[float],
    goal_dist_m: Optional[float] = None,
    failed_heading_deg: Optional[float] = None,
    tried_headings_deg: Optional[List[float]] = None,
    log: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """Traduce la descripcion panoramica del VLM a una decision en marco MUNDO (2026-0930).

    Cada imagen tiene un rumbo absoluto conocido (el que tenia el dron al capturarla). Entre los
    rumbos que el modelo marco transitables se elige el mas cercano al rumbo absoluto hacia la meta
    y se fija una sub-meta en esa direccion con las mismas reglas que la capa estrategica
    (subgoal.build_subgoal): VLM_SUBGOAL_DIST_M como maximo, nunca mas lejos que el WP real, a la altitud
    actual (las imagenes del barrido no describen filas: elevacion 0).
    El guiado normal la persigue; no se emiten maniobras relativas al cuerpo, que dejarian de ser
    validas en cuanto el dron gira (tras el barrido el dron mira al ULTIMO rumbo, no al primero).

    Sin rumbo transitable: GANAR_ALTURA (o PERDER_ALTURA si todo es vegetacion) -- es la unica
    lectura posible de "todo bloqueado a esta altura".

    Salida de deadlock: se descartan los transitables a menos de SCAN_FAILED_SECTOR_DEG del rumbo que
    fallo (`failed_heading_deg`) o de un rumbo ya probado en la zona (`tried_headings_deg`). Si quedan,
    sin historia se elige el mas cercano a la meta; con historia, el mas distinto de lo ya probado. Si
    todos los transitables estaban descartados: GANAR_ALTURA. `log` (opcional) recibe la seleccion
    completa para auditoria.

    Returns (macro_action, sub_meta_o_None, motivo).
    """
    assigned = assign_panorama_entries(rumbos, len(headings_world_deg))
    # Una entrada transitable tiene que ser coherente: ok=true con tipo distinto de "libre" (p. ej.
    # "interior" o "fachada") se contradice a si misma y no se usa. Piloto v3 seed 99 190842Z: la
    # camara quedo dentro del edificio, el modelo marco el interior de una oficina como transitable y
    # el barrido mando al dron contra la fachada.
    transitable = [
        (headings_world_deg[i], e) for i, e in enumerate(assigned)
        if e is not None and e.get("transitable", False) and e.get("tipo") == "libre"
    ]
    if not transitable:
        tipos = {e.get("tipo", "indeterminado") for e in assigned if e is not None}
        if tipos and "vegetacion" in tipos and tipos <= {"vegetacion", "indeterminado"}:
            return "PERDER_ALTURA", None, "todo vegetacion"
        return "GANAR_ALTURA", None, "ningun rumbo transitable"

    ref = goal_bearing_deg if goal_bearing_deg is not None else headings_world_deg[0]
    tried = [float(t) for t in (tried_headings_deg or [])]

    def _ang(a: float, b: float) -> float:
        return abs(_normalize_deg(a - b))

    remaining, excluded = [], []
    for h, e in transitable:
        if failed_heading_deg is not None and _ang(h, failed_heading_deg) <= SCAN_FAILED_SECTOR_DEG:
            excluded.append({"heading_deg": round(h, 1), "reason": "rumbo_fallido"})
        elif any(_ang(h, t) <= SCAN_FAILED_SECTOR_DEG for t in tried):
            excluded.append({"heading_deg": round(h, 1), "reason": "ya_probado"})
        else:
            remaining.append((h, e))
    if log is not None:
        log.update({
            "candidates_deg": [round(h, 1) for h, _e in transitable],
            "excluded": excluded,
            "failed_heading_deg": None if failed_heading_deg is None else round(failed_heading_deg, 1),
            "tried_headings_deg": [round(t, 1) for t in tried],
            "goal_bearing_deg": round(ref, 1),
        })
    if not remaining:
        if log is not None:
            log.update({"mode": "sin_rumbo_nuevo", "chosen_heading_deg": None})
        return "GANAR_ALTURA", None, "solo rumbos fallidos o ya probados"
    if tried:
        # Deadlock repetido en la zona: explorar el rumbo libre mas distinto de lo ya probado.
        avoid = tried + ([failed_heading_deg] if failed_heading_deg is not None else [])
        heading, _entry = max(remaining, key=lambda t: (min(_ang(t[0], a) for a in avoid), -_ang(t[0], ref)))
        mode = "exploracion"
    else:
        heading, _entry = min(remaining, key=lambda t: _ang(t[0], ref))
        mode = "hacia_meta"
    if log is not None:
        log.update({"mode": mode, "chosen_heading_deg": round(heading, 1)})
    pos = (telem or {}).get("position", {}) if isinstance(telem, dict) else {}
    corner = build_subgoal(float(pos.get("x", 0.0)), float(pos.get("y", 0.0)), float(pos.get("z", -10.0)),
                           heading, 0.0, goal_dist_m if goal_dist_m is not None else VLM_SUBGOAL_DIST_M,
                           "VLM_SCAN_GOAL")
    corner.pop("dist_m", None)
    return "MANTENER_RUMBO", corner, f"rumbo {heading:.0f} deg ({mode}; meta {ref:.0f} deg)"


def _angle_to_target(pos: Dict[str, Any], target: Optional[Dict[str, Any]]) -> Optional[float]:
    if not target or not pos:
        return None
    dx = float(target.get("x", 0.0)) - float(pos.get("x", 0.0))
    dy = float(target.get("y", 0.0)) - float(pos.get("y", 0.0))
    if math.hypot(dx, dy) < 0.5:
        return None
    return math.degrees(math.atan2(dy, dx))


def nearby_tried_headings(state: Dict[str, Any], pos: Dict[str, Any], wp_label: Any) -> List[float]:
    """Rumbos fallidos y elegidos en deadlocks anteriores a menos de SCAN_REPEAT_RADIUS_M, mismo WP."""
    out: List[float] = []
    for h in state.get("_deadlock_history") or []:
        if h.get("wp_label") != wp_label:
            continue
        if math.hypot(float(h["x"]) - float(pos.get("x", 0.0)), float(h["y"]) - float(pos.get("y", 0.0))) > SCAN_REPEAT_RADIUS_M:
            continue
        out += [float(v) for v in (h.get("failed_heading_deg"), h.get("chosen_heading_deg")) if v is not None]
    return out


def record_deadlock(state: Dict[str, Any], pos: Dict[str, Any], wp_label: Any,
                    failed_heading: Optional[float], chosen_heading: Optional[float], outcome: str) -> None:
    hist = list(state.get("_deadlock_history") or [])
    hist.append({
        "t": round(time.time(), 2), "x": round(float(pos.get("x", 0.0)), 2), "y": round(float(pos.get("y", 0.0)), 2),
        "wp_label": wp_label, "outcome": outcome,
        "failed_heading_deg": None if failed_heading is None else round(failed_heading, 1),
        "chosen_heading_deg": None if chosen_heading is None else round(chosen_heading, 1),
    })
    state["_deadlock_history"] = hist[-SCAN_HISTORY_MAX:]


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


def _real_goal(state: Dict[str, Any], guidance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """WP de mision (no temporal) al que se quiere llegar; si no hay, el objetivo del guiado."""
    wps = state.get("waypoints") or []
    idx = int(state.get("current_wp_index") or 0)
    for w in wps[idx:]:
        if isinstance(w, dict) and not w.get("is_temporary"):
            return w
    tw = (guidance or {}).get("target_wp") if isinstance(guidance, dict) else None
    return tw if isinstance(tw, dict) else None


def _build_panorama_prompt(
    headings_world_deg: List[float],
    start_yaw_deg: float,
    goal_bearing_deg: Optional[float],
    goal: Optional[Dict[str, Any]],
    telemetry: Dict[str, Any],
    deadlock_cycles: int,
) -> str:
    """Prompt del barrido (2026-0930): solo hechos, sin sugerir acciones.

    Antes el prompt decia "Prioriza EVADIR_IZQUIERDA, EVADIR_DERECHA o GANAR_ALTURA" aunque el
    sistema le pide al modelo que NO decida acciones."""
    pos = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
    altitude = abs(float(pos.get("z", 0.0))) if isinstance(pos, dict) else 0.0
    lines = [
        f"El dron lleva {deadlock_cycles} ciclos sin avanzar hacia su destino y giro en el lugar "
        f"para mirar {len(headings_world_deg)} direcciones. Altura: {altitude:.0f} m.",
        "Imagenes (angulo respecto de la direccion en la que venia volando, + = derecha):",
    ]
    goal_img = None
    if goal_bearing_deg is not None and headings_world_deg:
        goal_img = min(range(len(headings_world_deg)),
                       key=lambda i: abs(_normalize_deg(headings_world_deg[i] - goal_bearing_deg)))
    for i, h in enumerate(headings_world_deg):
        rel = _normalize_deg(h - start_yaw_deg)
        tags = []
        if i == 0:
            tags.append("direccion en la que no pudo avanzar")
        if i == goal_img:
            tags.append("la mas cercana a la direccion del destino")
        lines.append(f"- Imagen {i + 1}: {rel:+.0f} deg" + (f" ({'; '.join(tags)})" if tags else ""))
    if goal is not None and goal_bearing_deg is not None:
        dist = math.hypot(float(goal.get("x", 0.0)) - float(pos.get("x", 0.0)),
                          float(goal.get("y", 0.0)) - float(pos.get("y", 0.0)))
        lines.append(f"Destino ({goal.get('label', 'WP')}) a {dist:.0f} m.")
    lines.append("Describe cada imagen y responde solo el JSON.")
    return "\n".join(lines)


def deep_scan_cycle(
    state: Dict[str, Any],
    service: DeliberationService,
    field: Any,
    telemetry: Dict[str, Any],
    guidance: Dict[str, Any],
    arm: str,
    deadlock_cycles: int,
    consecutive_escapes: int = 0,
    trajectory: "Any | None" = None,  # sin uso desde 2026-0930; se acepta por compatibilidad (fsm.py)
) -> bool:
    """Ejecuta un paso del escaneo profundo (H2.2).

    Debe llamarse SOLO cuando ya se determino que hay atasco duro sin
    corredor (misma condicion que dispara el escape sincronico existente).

    Devuelve True si el ciclo quedo totalmente resuelto por esta funcion (el
    llamador debe retornar `state` tal cual). Devuelve False cuando el
    escaneo fallo (timeout, formato invalido o rotacion imposible): el
    llamador cae al escape sincronico existente en el mismo ciclo.

    2026-0930 (deep_vlm): sin reglas que reescriban al VLM. Se quitaron el retroceso ciego previo
    al barrido (Fix M), la esquina perpendicular post-retroceso (Fix 17), la escalada a RETROCEDER
    por oscilacion/repeticion (Fix L/L2) y los overrides de trayectoria 1a/1b/1c. La respuesta se
    interpreta en marco MUNDO (panorama_to_subgoal): cada imagen tiene su rumbo absoluto.
    """
    state["route"] = "deliberative" if arm == "slm" else "fsm"

    orient = telemetry.get("orientation", {}) if isinstance(telemetry, dict) else {}
    current_yaw_deg = math.degrees(float(orient.get("yaw", 0.0)))

    phase = state.get("_scan_phase")
    if phase is None:
        # Cerca del WP real no se barre: el rumbo a la meta desde tan cerca es casi ruido y una
        # sub-meta la saltearia. El llamador cae al escape determinista.
        goal0 = _real_goal(state, guidance)
        pos0 = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
        if goal0 is not None and pos0 and math.hypot(
                float(goal0.get("x", 0.0)) - float(pos0.get("x", 0.0)),
                float(goal0.get("y", 0.0)) - float(pos0.get("y", 0.0))) < VLM_NEAR_WP_M:
            state["_deadlock_event"] = {
                "strategy": "deep_vlm", "arm": arm, "resolved_by_scan": False,
                "cycles_to_resolve": None, "fell_back_to_blind": True, "reason": "cerca_del_wp",
            }
            return False
        state["_scan_phase"] = "rotando"
        # Rumbo que el dron intentaba al quedar trabado: hacia su objetivo activo (sub-meta o WP).
        tgt = (guidance or {}).get("target_wp") if isinstance(guidance, dict) else None
        state["_scan_failed_heading_deg"] = _angle_to_target(pos0, tgt)
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

    # Congela evasion_stuck_cycles mientras dura el barrido (ver _deliberation_pending en
    # main.py/runner.py): el dron gira en el lugar a proposito, no es "no progresar".
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
            # Timeout de rotacion: si el drone no puede girar (trabado en una malla), abandonar el
            # barrido y caer al escape sincronico.
            rot_stall = int(state.get("_scan_rot_stall") or 0) + 1
            state["_scan_rot_stall"] = rot_stall
            if rot_stall > SCAN_ROT_TIMEOUT_CYCLES:
                print(
                    f"[deep_scan] ({arm}) timeout de rotacion: yaw_err={yaw_err:.0f}° "
                    f"sin corregir en {rot_stall} ciclos. Cae al escape sincronico."
                )
                _g = _real_goal(state, guidance)
                record_deadlock(state, telemetry.get("position", {}) if isinstance(telemetry, dict) else {},
                                _g.get("label") if _g else None, state.get("_scan_failed_heading_deg"), None,
                                "falla_rotacion")
                clear_scan_state(state)
                state["_deadlock_event"] = {
                    "strategy": "deep_vlm",
                    "arm": arm,
                    "resolved_by_scan": False,
                    "cycles_to_resolve": None,
                    "fell_back_to_blind": True,
                }
                return False
            # Giro puro en el lugar hacia un rumbo absoluto (yaw_rate=0 + target_yaw absoluto:
            # AirSimClient.execute_velocity usa YawMode is_rate=False).
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

        # Capturar el frame de ESTE ciclo (el que capture_node ya produjo; nunca se vuelve a
        # llamar a capture() aca). Se guarda el rumbo REAL medido, no el objetivo del giro.
        capture_ts = float(telemetry.get("timestamp") or time.time())
        frames = list(state.get("_scan_frames") or [])
        frames.append((round(current_yaw_deg, 1), state.get("rgb_image"), capture_ts))
        state["_scan_frames"] = frames
        next_index = heading_index + 1
        state["_scan_heading_index"] = next_index
        state["_scan_phase"] = "rotando" if next_index < SCAN_HEADING_COUNT_DEEP else "capturado"
        return True

    if phase == "capturado":
        pending_id = state.get("_deep_scan_request_id")
        goal = _real_goal(state, guidance)
        pos = telemetry.get("position", {}) if isinstance(telemetry, dict) else {}
        goal_bearing = (
            math.degrees(math.atan2(float(goal.get("y", 0.0)) - float(pos.get("y", 0.0)),
                                    float(goal.get("x", 0.0)) - float(pos.get("x", 0.0))))
            if goal is not None else None
        )

        if pending_id is None:
            frames: List[Any] = (state.get("_scan_frames") or [])[:MAX_DEEP_SCAN_IMAGES]
            images_b64: List[str] = []
            labels: List[str] = []
            headings: List[float] = []
            for heading, frame, _capture_ts in frames:
                encoded = _encode_frame_base64(frame, max_size=DEEP_SCAN_IMAGE_MAX_SIZE)
                if encoded is None:
                    continue
                images_b64.append(encoded)
                headings.append(float(heading))
                labels.append(f"[Imagen {len(images_b64)}]")
            state["_scan_frames"] = [f for f in frames if f[1] is not None][: len(headings)]

            prompt = _build_panorama_prompt(headings, start_yaw, goal_bearing, goal, telemetry, deadlock_cycles)
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
            headings = [float(h) for h, _f, _t in (state.get("_scan_frames") or [])]
            failed_heading = state.get("_scan_failed_heading_deg")
            wp_label = goal.get("label") if goal is not None else None
            tried = nearby_tried_headings(state, pos, wp_label)
            clear_scan_state(state)

            pano = parse_panorama_description(decision)
            corner = None
            selection: Dict[str, Any] = {}
            # `degradada` no se usa para decidir: en los pilotos v3 el modelo la marco true en las 19
            # respuestas completas, incluidas imagenes nitidas de calle abierta. Como regla de falla
            # descartaba el 100 % de los barridos (piloto 232026Z: 8 de 8). Se registra para auditoria.
            if pano is not None and headings:
                goal_dist = (math.hypot(float(goal.get("x", 0.0)) - float(pos.get("x", 0.0)),
                                        float(goal.get("y", 0.0)) - float(pos.get("y", 0.0)))
                             if goal is not None else None)
                macro, corner, why = panorama_to_subgoal(
                    pano["rumbos"], headings, telemetry, goal_bearing, goal_dist_m=goal_dist,
                    failed_heading_deg=failed_heading, tried_headings_deg=tried, log=selection,
                )
                selection["degradada"] = bool(pano["imagen_degradada_global"])
                record_deadlock(state, pos, wp_label, failed_heading, selection.get("chosen_heading_deg"),
                                "subgoal" if corner else macro)
                nav_decision = {
                    "macro_action": macro,
                    "rationale": f"VLM panorama: {why}",
                    "used_json_schema": (decision or {}).get("used_json_schema", False),
                }
                print(f"[deep_vlm] panorama VLM -> {macro} ({why})")
            else:
                why_fail = getattr(result, "error", None) or "sin_formato_valido"
                record_deadlock(state, pos, wp_label, failed_heading, None, f"falla_{why_fail}")
                print(f"[deep_scan] ({arm}) respuesta no utilizable ({why_fail}). Cae al escape sincronico.")
                _record_failed_scan(state, result.raw_response, why_fail, result.latency_ms)
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
                guidance, telemetry, arm, deadlock_cycles,
            )
            if corner:
                state["inject_corner"] = corner
            if state.get("_deadlock_event") is not None:
                if corner:
                    state["_deadlock_event"]["vlm_subgoal"] = corner
                state["_deadlock_event"]["scan_selection"] = selection
            print(f"[deep_vlm] seleccion: {selection}")
            return True

        if lost or age_ms > SLM_DEEP_WATCHDOG_MS:
            print(f"[deep_scan] WATCHDOG ({arm}): {'pedido perdido' if lost else 'sin respuesta del VLM'} en {age_ms:.0f}ms. Cae al escape sincronico.")
            record_deadlock(state, pos, goal.get("label") if goal is not None else None,
                            state.get("_scan_failed_heading_deg"), None, "falla_" + ("perdido" if lost else "watchdog"))
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
) -> None:
    """Aplica tal cual la decision de un escaneo resuelto y deja el rastro de auditoria."""
    macro = decision["macro_action"]
    cmd = action_to_command(macro, guidance=guidance, telemetry=telemetry)
    cmd["rationale"] = decision.get("rationale", "")

    deliberations_list = state.setdefault("deliberations", [])
    deliberations_list.append(
        {
            "id": len(deliberations_list) + 1,
            "timestamp": time.time(),
            "arm": f"{arm}_deep_scan",
            "model": LOCAL_LLM_MODEL_NAME,
            "vision_enabled": True,
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
    # Reinicia el contador de atasco del tracker a traves del lazo (runner/main): el escaneo
    # resuelto no debe re-disparar de inmediato.
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
