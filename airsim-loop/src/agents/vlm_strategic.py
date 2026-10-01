# Capa estrategica del VLM, anclada a la pose de captura (2026-0930).
#
# Problema que resuelve: la inferencia del VLM tarda ~3-6 s (qwen2.5-vl-3b remoto). A 5 Hz eso
# son 15-30 ciclos: cuando la respuesta llega, el dron ya giro y avanzo varios metros. Cualquier
# respuesta expresada en el marco del CUERPO ("frente libre", "evadir a la izquierda") describe
# un frame que ya no existe -- por eso las respuestas tacticas por sector llegaban tarde y se
# terminaban ignorando o reinterpretando mal.
#
# Diseno: dos lazos desacoplados.
#   - Lazo rapido (5 Hz, sin cambios): guiado al waypoint + evasion por flujo optico. Es el unico
#     que comanda velocidades y el unico responsable de lo inminente.
#   - Lazo lento (este modulo, ~0.2-0.3 Hz): el VLM mira UN frame y responde una pregunta cuya
#     respuesta es valida en el MUNDO, no en el cuerpo: "por cual de estas columnas se puede volar
#     15 m hacia la meta". Cada columna tiene un rumbo absoluto calculado con el yaw DEL INSTANTE
#     DE CAPTURA, asi que la respuesta se convierte en una sub-meta (x, y, z) en coordenadas del
#     mundo que sigue siendo correcta aunque el dron haya girado mientras el modelo pensaba.
#
# Sincronizacion:
#   - El pedido guarda su "ancla": pose (x, y, z, yaw) y timestamp del frame enviado, y la etiqueta
#     del WP real al que apuntaba.
#   - Al llegar la respuesta se valida contra el presente: edad maxima, que el WP real no haya
#     cambiado, y que la sub-meta todavia quede por delante del dron (no ya superada).
#   - El dron nunca frena a esperar: el lazo rapido sigue volando. La sub-meta se inyecta al
#     tracker y el guiado normal la persigue.
#
# El VLM describe; este modulo solo traduce la descripcion a geometria. No hay reglas de
# trayectoria que reescriban lo que el modelo dijo.
from __future__ import annotations

import base64
import math
import os
import time
from typing import Any, Dict, Optional, Tuple

VLM_STRATEGIC_ENABLED = os.getenv("VLM_STRATEGIC_ENABLED", "true").lower() == "true"
# Periodo minimo entre consultas (s). Con ~4 s de latencia, 3 s deja siempre a lo sumo 1 en vuelo.
VLM_STRATEGIC_PERIOD_S = float(os.getenv("VLM_STRATEGIC_PERIOD_S", "3.0"))
# Edad maxima de una respuesta (desde la captura del frame) para aplicarla.
VLM_STRATEGIC_MAX_AGE_S = float(os.getenv("VLM_STRATEGIC_MAX_AGE_S", "10.0"))
# Gracia antes de dar por perdido un pedido que otro consumidor (escaneo profundo) piso en la cola.
VLM_STRATEGIC_LOST_GRACE_S = float(os.getenv("VLM_STRATEGIC_LOST_GRACE_S", "3.0"))
# Distancia de la sub-meta desde el punto de captura, a lo largo del rumbo de la columna elegida.
VLM_SUBGOAL_DIST_M = float(os.getenv("VLM_SUBGOAL_DIST_M", "15.0"))
# Si la sub-meta quedo a menos de esto del dron al llegar la respuesta, ya no aporta: se descarta.
VLM_SUBGOAL_MIN_AHEAD_M = float(os.getenv("VLM_SUBGOAL_MIN_AHEAD_M", "4.0"))
# Ascenso aplicado a la sub-meta cuando el modelo ve una estructura horizontal a la altura del dron.
VLM_CLIMB_M = float(os.getenv("VLM_CLIMB_M", "4.0"))
# Solo se consulta si la meta cae dentro del campo visual (con margen): si no, el guiado todavia
# esta girando hacia ella y el frame no muestra lo que importa.
VLM_STRATEGIC_MAX_GOAL_OFF_DEG = float(os.getenv("VLM_STRATEGIC_MAX_GOAL_OFF_DEG", "40.0"))
# No consultar por debajo de esta altitud (despegue).
VLM_STRATEGIC_MIN_ALT_M = float(os.getenv("VLM_STRATEGIC_MIN_ALT_M", os.getenv("SLM_MIN_ALT_M", "8.0")))
CAMERA_HFOV_DEG = float(os.getenv("CAMERA_HFOV_DEG", "90.0"))
VLM_COLUMNS = max(3, min(7, int(os.getenv("VLM_STRATEGIC_COLUMNS", "5"))))
VLM_STRATEGIC_IMAGE_MAX_SIZE = int(os.getenv("VLM_STRATEGIC_IMAGE_MAX_SIZE", os.getenv("VLM_IMAGE_MAX_SIZE", "384")))

COLUMN_LABELS = "ABCDEFG"[:VLM_COLUMNS]
COLUMN_STATES = ["libre", "bloqueada"]

SYSTEM_PROMPT_STRATEGIC = (
    "Sos el sistema de percepcion de un dron que vuela a unos 10 m de altura en una ciudad.\n"
    "Recibes la imagen de la camara frontal dividida en columnas verticales etiquetadas de "
    "izquierda a derecha. Una marca roja 'META' arriba indica la direccion del destino.\n"
    "NO decides acciones: describes lo que ves.\n\n"
    "Para cada columna indica si el dron puede volar recto por ella al menos 15 m A SU ALTURA:\n"
    "- 'libre': se ve calle, plaza, cielo o espacio abierto a la altura del dron.\n"
    "- 'bloqueada': hay un edificio, fachada, muro, arbol, puente, autopista elevada, cornisa, "
    "balcon o techo a la altura del dron dentro de esos 15 m.\n"
    "Ademas:\n"
    "- meta_bloqueada: true si algun obstaculo se interpone entre el dron y la META.\n"
    "- estructura_debajo: true si el dron esta por pasar por encima o a la altura de una "
    "superficie horizontal cercana (autopista elevada, puente, techo, cornisa).\n\n"
    "Responde UNICAMENTE con JSON con las claves 'columnas', 'meta_bloqueada' y 'estructura_debajo'."
)

RESPONSE_JSON_SCHEMA_STRATEGIC = {
    "type": "json_schema",
    "json_schema": {
        "name": "strategic_columns",
        "schema": {
            "type": "object",
            "properties": {
                "columnas": {
                    "type": "object",
                    "properties": {c: {"type": "string", "enum": COLUMN_STATES} for c in COLUMN_LABELS},
                    "required": list(COLUMN_LABELS),
                    "additionalProperties": False,
                },
                "meta_bloqueada": {"type": "boolean"},
                "estructura_debajo": {"type": "boolean"},
            },
            "required": ["columnas", "meta_bloqueada", "estructura_debajo"],
            "additionalProperties": False,
        },
    },
}


# --------------------------------------------------------------------------- geometria
def _norm_deg(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def column_centers_deg(hfov_deg: float = CAMERA_HFOV_DEG, n: int = VLM_COLUMNS) -> Dict[str, float]:
    """Angulo (respecto del eje optico, +derecha) del centro de cada columna, equiespaciado en angulo."""
    step = hfov_deg / n
    return {COLUMN_LABELS[i]: -hfov_deg / 2.0 + (i + 0.5) * step for i in range(n)}


def column_for_angle(rel_deg: float, hfov_deg: float = CAMERA_HFOV_DEG, n: int = VLM_COLUMNS) -> str:
    step = hfov_deg / n
    idx = int(math.floor((rel_deg + hfov_deg / 2.0) / step))
    return COLUMN_LABELS[max(0, min(n - 1, idx))]


def _angle_to_px(rel_deg: float, width: int, hfov_deg: float) -> int:
    """Proyeccion pinhole: columna de pixel para un angulo horizontal respecto del eje optico."""
    f = (width / 2.0) / math.tan(math.radians(hfov_deg / 2.0))
    return int(round(width / 2.0 + f * math.tan(math.radians(rel_deg))))


def bearing_to(pos: Dict[str, float], wp: Dict[str, Any]) -> float:
    return math.degrees(math.atan2(float(wp["y"]) - float(pos.get("y", 0.0)),
                                   float(wp["x"]) - float(pos.get("x", 0.0))))


def real_waypoint(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Primer WP de mision (no temporal) desde el indice activo."""
    wps = state.get("waypoints") or []
    idx = int(state.get("current_wp_index") or 0)
    for w in wps[idx:]:
        if not w.get("is_temporary"):
            return w
    return None


def current_target_is_real(state: Dict[str, Any]) -> bool:
    wps = state.get("waypoints") or []
    idx = int(state.get("current_wp_index") or 0)
    return idx < len(wps) and not wps[idx].get("is_temporary")


# --------------------------------------------------------------------------- imagen
def annotate_columns(frame: Any, goal_rel_deg: float, hfov_deg: float = CAMERA_HFOV_DEG,
                     n: int = VLM_COLUMNS, max_size: int = VLM_STRATEGIC_IMAGE_MAX_SIZE) -> Optional[str]:
    """Copia reescalada del frame con las columnas y la marca META dibujadas; JPEG base64.

    Nunca modifica el frame original (lo usa el flujo optico)."""
    if frame is None:
        return None
    try:
        # pyrefly: ignore [missing-import]
        import cv2

        h, w = frame.shape[:2]
        img = frame
        if max(h, w) > max_size:
            s = max_size / max(h, w)
            img = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        else:
            img = frame.copy()
        h, w = img.shape[:2]
        step = hfov_deg / n
        edges = [-hfov_deg / 2.0 + i * step for i in range(n + 1)]
        xs = [max(0, min(w - 1, _angle_to_px(a, w, hfov_deg))) for a in edges]
        for x in xs[1:-1]:
            cv2.line(img, (x, 0), (x, h - 1), (255, 255, 255), 1)
        scale = max(0.4, w / 640.0)
        for i in range(n):
            cx = (xs[i] + xs[i + 1]) // 2
            org = (cx - int(8 * scale), h - int(10 * scale))
            cv2.putText(img, COLUMN_LABELS[i], org, cv2.FONT_HERSHEY_SIMPLEX, 0.9 * scale, (0, 0, 0), 4)
            cv2.putText(img, COLUMN_LABELS[i], org, cv2.FONT_HERSHEY_SIMPLEX, 0.9 * scale, (255, 255, 255), 2)
        g = max(0.0, min(float(w - 1), float(_angle_to_px(max(-hfov_deg / 2, min(hfov_deg / 2, goal_rel_deg)), w, hfov_deg))))
        gx = int(g)
        tri = [(gx - int(9 * scale), 2), (gx + int(9 * scale), 2), (gx, int(18 * scale))]
        import numpy as _np
        cv2.fillPoly(img, [_np.array(tri, dtype=_np.int32)], (0, 0, 255))  # BGR: rojo
        cv2.putText(img, "META", (max(0, gx - int(20 * scale)), int(32 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5 * scale, (0, 0, 255), 2)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buf).decode("utf-8") if ok else None
    except Exception as exc:  # pragma: no cover - cv2 ausente
        print(f"[vlm_strategic] error anotando frame: {exc}")
        return None


# --------------------------------------------------------------------------- pedido
def build_request(state: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Arma (payload, ancla) o None si este frame no sirve para preguntar."""
    telem = state.get("telemetry") or {}
    pos = telem.get("position") or {}
    frame = state.get("rgb_image")
    wp = real_waypoint(state)
    if frame is None or wp is None or not pos:
        return None
    yaw_deg = math.degrees(float((telem.get("orientation") or {}).get("yaw", 0.0)))
    goal_bearing = bearing_to(pos, wp)
    goal_rel = _norm_deg(goal_bearing - yaw_deg)
    if abs(goal_rel) > VLM_STRATEGIC_MAX_GOAL_OFF_DEG:
        return None
    goal_col = column_for_angle(goal_rel)
    img = annotate_columns(frame, goal_rel)
    if img is None:
        return None
    dist = math.hypot(float(wp["x"]) - float(pos.get("x", 0.0)), float(wp["y"]) - float(pos.get("y", 0.0)))
    prompt = (
        f"Destino ({wp.get('label', 'WP')}): {dist:.0f} m, en la columna {goal_col} "
        f"(marca META). Altura del dron: {abs(float(pos.get('z', 0.0))):.0f} m.\n"
        f"Columnas: {', '.join(COLUMN_LABELS)} (izquierda a derecha).\n"
        "Describe cada columna y responde solo el JSON."
    )
    anchor = {
        "x": float(pos.get("x", 0.0)), "y": float(pos.get("y", 0.0)), "z": float(pos.get("z", 0.0)),
        "yaw_deg": yaw_deg, "ts": float(telem.get("timestamp") or time.time()), "sent_at": time.time(),
        "goal_rel_deg": goal_rel, "goal_col": goal_col, "wp_label": wp.get("label"), "wp_z": float(wp.get("z", -10.0)),
        "frame": frame,  # auditoria: el frame exacto que vio el modelo
    }
    payload = {
        "mode": "strategic",
        "prompt": prompt,
        "images_b64": [img],
        "image_labels": ["[Camara frontal con columnas]"],
    }
    return payload, anchor


# --------------------------------------------------------------------------- respuesta
def parse_strategic(data: Any) -> Optional[Dict[str, Any]]:
    """Normaliza la respuesta. None si no tiene el formato esperado."""
    if not isinstance(data, dict):
        return None
    cols = data.get("columnas")
    if not isinstance(cols, dict):
        return None
    out: Dict[str, str] = {}
    for c in COLUMN_LABELS:
        v = str(cols.get(c, "")).strip().lower()
        if v not in COLUMN_STATES:
            return None
        out[c] = v
    return {
        "columnas": out,
        "meta_bloqueada": bool(data.get("meta_bloqueada", False)),
        "estructura_debajo": bool(data.get("estructura_debajo", False)),
    }


def decide_subgoal(parsed: Dict[str, Any], anchor: Dict[str, Any], state: Dict[str, Any],
                   now: Optional[float] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """Traduce la descripcion del VLM a una sub-meta en coordenadas del mundo.

    Devuelve (sub_meta_o_None, motivo). El tracker la inserta tal cual
    (WaypointTracker.inject_corner_waypoint)."""
    now = time.time() if now is None else now
    age = now - float(anchor.get("sent_at", now))
    if age > VLM_STRATEGIC_MAX_AGE_S:
        return None, f"vencida ({age:.1f} s)"
    wp = real_waypoint(state)
    if wp is None or wp.get("label") != anchor.get("wp_label"):
        return None, "wp_cambio"

    cols = parsed["columnas"]
    goal_col = anchor["goal_col"]
    climb = bool(parsed.get("estructura_debajo"))
    centers = column_centers_deg()
    free = [c for c in COLUMN_LABELS if cols[c] == "libre"]

    if not climb and cols.get(goal_col) == "libre" and not parsed.get("meta_bloqueada"):
        return None, "directo_libre"
    if free:
        goal_rel = float(anchor["goal_rel_deg"])
        best = min(free, key=lambda c: (abs(centers[c] - goal_rel), abs(centers[c])))
        if best == goal_col and not climb:
            # Columna de la meta libre aunque el modelo marque meta_bloqueada: el camino directo es
            # lo que ya hace el guiado, no hay sub-meta que agregar.
            return None, "directo_libre"
        rel = centers[best]
        reason = f"columna {best} ({rel:+.0f} deg)" + (" + subir" if climb else "")
    elif climb:
        rel = float(anchor["goal_rel_deg"])
        best = goal_col
        reason = "sin columna libre: subir hacia la meta"
    else:
        return None, "sin_columna_libre"

    world = math.radians(float(anchor["yaw_deg"]) + rel)
    sx = float(anchor["x"]) + VLM_SUBGOAL_DIST_M * math.cos(world)
    sy = float(anchor["y"]) + VLM_SUBGOAL_DIST_M * math.sin(world)
    sz = float(anchor["wp_z"]) - (VLM_CLIMB_M if climb else 0.0)

    pos = (state.get("telemetry") or {}).get("position") or {}
    px, py = float(pos.get("x", anchor["x"])), float(pos.get("y", anchor["y"]))
    # Superada: el dron ya esta cerca o paso la sub-meta a lo largo del rumbo elegido mientras el
    # modelo pensaba.
    along = (px - float(anchor["x"])) * math.cos(world) + (py - float(anchor["y"])) * math.sin(world)
    if math.hypot(sx - px, sy - py) < VLM_SUBGOAL_MIN_AHEAD_M or along > VLM_SUBGOAL_DIST_M - VLM_SUBGOAL_MIN_AHEAD_M:
        return None, "superada"
    return {
        "x": round(sx, 2), "y": round(sy, 2), "z": round(sz, 2),
        "label": "VLM_SUBGOAL", "column": best,
    }, reason


class StrategicLayer:
    """Estado de proceso de la capa lenta: un pedido en vuelo a la vez, con su ancla."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self.req_id: Optional[int] = None
        self.anchor: Optional[Dict[str, Any]] = None
        self.payload: Optional[Dict[str, Any]] = None
        self.last_sent: float = 0.0
        self.last_outcome: Optional[Dict[str, Any]] = None

    def busy(self) -> bool:
        return self.req_id is not None

    def _clear(self) -> None:
        self.req_id, self.anchor, self.payload = None, None, None

    def expedite(self) -> None:
        """Permite consultar en este mismo ciclo, sin esperar el periodo (p. ej. el lazo rapido acaba
        de ver un muro de frente: ese frame es justo el que el VLM tiene que mirar)."""
        self.last_sent = 0.0

    def cancel(self, reason: str = "cancelado") -> None:
        """Descarta el pedido en vuelo (su respuesta, si llega, se ignora). Se usa al entrar en
        deadlock: el barrido profundo es mas nuevo y su sub-meta no debe ser pisada por esta."""
        if self.req_id is not None:
            self.last_outcome = {"outcome": reason}
        self._clear()
        self.last_sent = time.time()

    def tick(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Llamar una vez por ciclo. Devuelve el registro de auditoria si llego una respuesta."""
        if not VLM_STRATEGIC_ENABLED:
            return None
        if self.req_id is not None:
            return self._poll(state)
        self._maybe_send(state)
        return None

    def _maybe_send(self, state: Dict[str, Any]) -> None:
        now = time.time()
        if now - self.last_sent < VLM_STRATEGIC_PERIOD_S:
            return
        # El escaneo profundo usa el mismo servicio (una sola cola): no competir.
        if state.get("_scan_phase") is not None or state.get("_deep_scan_request_id") is not None:
            return
        alt = abs(float(((state.get("telemetry") or {}).get("position") or {}).get("z", 0.0)))
        if alt < VLM_STRATEGIC_MIN_ALT_M or not current_target_is_real(state):
            return
        built = build_request(state)
        if built is None:
            return
        self.payload, self.anchor = built
        self.req_id = self.service.request(self.payload)
        self.last_sent = now

    def _poll(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        getter = getattr(self.service, "get_result", None)
        result = getter(self.req_id) if callable(getter) else None
        age = time.time() - float((self.anchor or {}).get("sent_at", time.time()))
        if result is None:
            _latest, _svc_age, has_pending = self.service.poll()
            if age > VLM_STRATEGIC_MAX_AGE_S or (not has_pending and age > VLM_STRATEGIC_LOST_GRACE_S):
                self.last_outcome = {"outcome": "sin_respuesta", "age_s": round(age, 2)}
                self._clear()
            return None
        anchor, payload = self.anchor, self.payload
        self._clear()
        parsed = result.parsed_decision if isinstance(result.parsed_decision, dict) else None
        if parsed is not None and "columnas" not in parsed:
            parsed = None
        subgoal, reason = (None, "no_parseable") if parsed is None else decide_subgoal(parsed, anchor, state)
        if subgoal is not None:
            state["inject_corner"] = subgoal
            print(f"[vlm_strategic] sub-meta {reason} -> ({subgoal['x']:.1f},{subgoal['y']:.1f},{subgoal['z']:.1f}) "
                  f"[latencia {result.latency_ms:.0f} ms]")
        self.last_outcome = {
            "outcome": "subgoal" if subgoal else reason, "reason": reason,
            "latency_ms": round(float(result.latency_ms or 0.0), 1),
            "goal_col": anchor.get("goal_col"), "anchor": {k: anchor[k] for k in ("x", "y", "yaw_deg", "ts", "wp_label")},
            "parsed": parsed, "subgoal": subgoal,
        }
        return {
            "arm": "vlm_strategic", "prompt": payload.get("prompt", ""), "raw_response": result.raw_response or "",
            "parsed": parsed, "reason": reason, "subgoal": subgoal,
            "latency_ms": round(float(result.latency_ms or 0.0), 1), "timestamp": result.completed_at,
            "frame": anchor.get("frame"), "frame_ts": anchor.get("ts"),
        }
