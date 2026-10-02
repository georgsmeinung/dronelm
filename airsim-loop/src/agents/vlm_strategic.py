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
#   - Lazo lento (este modulo, ~0.2-0.3 Hz): el VLM mira UN frame dividido en una grilla de 3x3
#     (los tercios de la composicion fotografica) y dice que sectores estan libres. Cada sector tiene
#     una direccion -- rumbo y elevacion -- calculada con la pose DEL INSTANTE DE CAPTURA, asi que la
#     respuesta se convierte en una sub-meta (x, y, z) en coordenadas del mundo que sigue siendo
#     correcta aunque el dron haya girado mientras el modelo pensaba. A diferencia de columnas (un
#     solo eje), la grilla tambien dice si conviene pasar por arriba o por abajo (2026-1001).
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
from .subgoal import (  # noqa: E402  reglas de distancia y altura comunes con el barrido
    VLM_MAX_DZ_M, VLM_SUBGOAL_DIST_M, VLM_SUBGOAL_MIN_AHEAD_M, VLM_SUBGOAL_MIN_ALT_M, build_subgoal,
)

# Cerca del WP real no se consulta al VLM ni se barre: el guiado directo alcanza y el rumbo a la meta
# desde tan cerca es casi ruido.
VLM_NEAR_WP_M = float(os.getenv("VLM_NEAR_WP_M", "8.0"))
# Solo se consulta si la meta cae dentro del campo visual (con margen): si no, el guiado todavia
# esta girando hacia ella y el frame no muestra lo que importa.
VLM_STRATEGIC_MAX_GOAL_OFF_DEG = float(os.getenv("VLM_STRATEGIC_MAX_GOAL_OFF_DEG", "40.0"))
# Excepcion: si el dron lleva este numero de ciclos sin acercarse a su objetivo, se consulta igual con la
# meta fuera de cuadro -- conviene mirar hacia donde esta el dron. Piloto v3 193631Z: el dron se deslizo
# ~180 ciclos a lo largo de una fachada mirando de costado a la meta y la capa no consulto ni una vez.
VLM_STUCK_QUERY_CYCLES = int(os.getenv("VLM_STUCK_QUERY_CYCLES", "15"))
# No consultar por debajo de esta altitud (despegue).
VLM_STRATEGIC_MIN_ALT_M = float(os.getenv("VLM_STRATEGIC_MIN_ALT_M", os.getenv("SLM_MIN_ALT_M", "8.0")))
CAMERA_HFOV_DEG = float(os.getenv("CAMERA_HFOV_DEG", "90.0"))
VLM_STRATEGIC_IMAGE_MAX_SIZE = int(os.getenv("VLM_STRATEGIC_IMAGE_MAX_SIZE", os.getenv("VLM_IMAGE_MAX_SIZE", "384")))

# Grilla de 3x3 por tercios de un RECORTE CUADRADO del centro del frame (se cortan los dos costados del
# ancho). Columnas A (izquierda), B (centro), C (derecha); filas 1 (arriba), 2 (medio, la altura del
# dron), 3 (abajo). Sector "B2" = de frente, a la misma altura. Con el recorte cuadrado los sectores
# laterales y los verticales quedan a la misma distancia angular del centro (~24 deg en un frame 3:2 de
# 90 deg): sobre el frame completo los laterales quedaban a 33.7 deg y los verticales a 24, y un rodeo
# por arriba o por abajo ganaba siempre a uno por el costado por la forma del cuadro, no por la escena.
GRID_COLS = "ABC"
GRID_ROWS = "123"
CELLS = [c + r for r in GRID_ROWS for c in GRID_COLS]
CELL_STATES = ["libre", "bloqueado"]
# Desempate entre sectores igual de cerca de la meta: la fila del medio, despues arriba (el suelo esta
# abajo), despues abajo.
_ROW_PREF = {"2": 0, "1": 1, "3": 2}

SYSTEM_PROMPT_STRATEGIC = (
    "Sos el sistema de percepcion de un dron que vuela a baja altura en un entorno urbano.\n"
    "Recibes la imagen de la camara frontal dividida en una grilla de 3x3 sectores, como la grilla de "
    "tercios de una foto. Columnas A, B, C (izquierda a derecha); filas 1, 2, 3 (arriba, medio, abajo). "
    "La fila 2 es la altura del dron; la fila 1 es pasar por arriba; la fila 3, por abajo. "
    "Una marca roja 'META' indica la direccion del destino.\n"
    "NO decides acciones: describes lo que ves.\n\n"
    "Para cada sector indica si el dron puede volar en esa direccion al menos 15 m sin chocar:\n"
    "- 'libre': se ve cielo, calle, plaza o espacio abierto en ese sector.\n"
    "- 'bloqueado': hay un edificio, fachada, vidrio, muro, arbol o vegetacion, puente o estructura elevada, cornisa, "
    "balcon, techo o el interior de un edificio en ese sector, a menos de 15 m.\n\n"
    "Responde UNICAMENTE con JSON con la clave 'sectores' y los nueve sectores A1..C3."
)

RESPONSE_JSON_SCHEMA_STRATEGIC = {
    "type": "json_schema",
    "json_schema": {
        "name": "strategic_grid",
        "schema": {
            "type": "object",
            "properties": {
                "sectores": {
                    "type": "object",
                    "properties": {c: {"type": "string", "enum": CELL_STATES} for c in CELLS},
                    "required": list(CELLS),
                    "additionalProperties": False,
                },
            },
            "required": ["sectores"],
            "additionalProperties": False,
        },
    },
}


# --------------------------------------------------------------------------- geometria
def _norm_deg(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def _focal_px(width: int, hfov_deg: float = CAMERA_HFOV_DEG) -> float:
    return (width / 2.0) / math.tan(math.radians(hfov_deg / 2.0))


def square_crop(frame: Any) -> Tuple[Any, int, float]:
    """(recorte cuadrado central, lado en px, focal en px). La focal es la del frame completo: el recorte
    no cambia la optica, solo el campo visual (90 deg de ancho -> ~67 deg en un frame 3:2)."""
    h, w = frame.shape[:2]
    side = min(h, w)
    x0, y0 = (w - side) // 2, (h - side) // 2
    return frame[y0:y0 + side, x0:x0 + side], side, _focal_px(w)


def crop_half_fov_deg(side: int, f: float) -> float:
    return math.degrees(math.atan((side / 2.0) / f))


def cell_centers_deg(side: int, f: float) -> Dict[str, Tuple[float, float]]:
    """(azimut, elevacion) del centro de cada sector respecto del eje optico (+derecha, +arriba).

    Los sectores son tercios del recorte cuadrado (pinhole, pixeles cuadrados), no tercios de angulo."""
    out: Dict[str, Tuple[float, float]] = {}
    for ci, c in enumerate(GRID_COLS):
        az = math.degrees(math.atan(((ci + 0.5) * side / 3.0 - side / 2.0) / f))
        for ri, r in enumerate(GRID_ROWS):
            el = math.degrees(math.atan((side / 2.0 - (ri + 0.5) * side / 3.0) / f))
            out[c + r] = (az, el)
    return out


def direction_to_px(az_deg: float, el_deg: float, side: int, f: float) -> Tuple[float, float]:
    return (side / 2.0 + f * math.tan(math.radians(az_deg)),
            side / 2.0 - f * math.tan(math.radians(el_deg)))


def cell_for_direction(az_deg: float, el_deg: float, side: int, f: float) -> str:
    px, py = direction_to_px(az_deg, el_deg, side, f)
    ci = max(0, min(2, int(px // (side / 3.0))))
    ri = max(0, min(2, int(py // (side / 3.0))))
    return GRID_COLS[ci] + GRID_ROWS[ri]


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


def dist_xy_to_real_wp(state: Dict[str, Any]) -> Optional[float]:
    wp = real_waypoint(state)
    pos = (state.get("telemetry") or {}).get("position") or {}
    if wp is None or not pos:
        return None
    return math.hypot(float(wp["x"]) - float(pos.get("x", 0.0)), float(wp["y"]) - float(pos.get("y", 0.0)))


# --------------------------------------------------------------------------- imagen
def annotate_grid(crop: Any, f: float, goal_az_deg: float, goal_el_deg: float,
                  max_size: int = VLM_STRATEGIC_IMAGE_MAX_SIZE) -> Optional[str]:
    """Copia reescalada del recorte cuadrado con la grilla 3x3, las etiquetas y la marca META; JPEG base64.

    Nunca modifica el frame original (lo usa el flujo optico)."""
    if crop is None:
        return None
    try:
        # pyrefly: ignore [missing-import]
        import cv2

        side = crop.shape[0]
        out = min(max_size, side)
        img = cv2.resize(crop, (out, out), interpolation=cv2.INTER_AREA) if out != side else crop.copy()
        fs = f * out / float(side)
        for k in (1, 2):
            cv2.line(img, (k * out // 3, 0), (k * out // 3, out - 1), (255, 255, 255), 1)
            cv2.line(img, (0, k * out // 3), (out - 1, k * out // 3), (255, 255, 255), 1)
        scale = max(0.4, out / 640.0)
        for ci, c in enumerate(GRID_COLS):
            for ri, r in enumerate(GRID_ROWS):
                org = (ci * out // 3 + int(4 * scale), ri * out // 3 + int(18 * scale))
                cv2.putText(img, c + r, org, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (0, 0, 0), 3)
                cv2.putText(img, c + r, org, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (255, 255, 255), 1)
        gx, gy = direction_to_px(goal_az_deg, goal_el_deg, out, fs)
        gx, gy = int(max(6, min(out - 7, gx))), int(max(6, min(out - 7, gy)))
        r = int(7 * scale)
        cv2.circle(img, (gx, gy), r, (0, 0, 255), 2)  # BGR: rojo
        cv2.line(img, (gx - r, gy), (gx + r, gy), (0, 0, 255), 1)
        cv2.line(img, (gx, gy - r), (gx, gy + r), (0, 0, 255), 1)
        cv2.putText(img, "META", (max(0, gx - int(18 * scale)), max(10, gy - r - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45 * scale, (0, 0, 255), 2)
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
    dist = math.hypot(float(wp["x"]) - float(pos.get("x", 0.0)), float(wp["y"]) - float(pos.get("y", 0.0)))
    if dist < VLM_NEAR_WP_M:
        return None
    yaw_deg = math.degrees(float((telem.get("orientation") or {}).get("yaw", 0.0)))
    goal_az = _norm_deg(bearing_to(pos, wp) - yaw_deg)
    # NED: z negativo es arriba. Elevacion > 0 si la meta esta por encima del dron.
    goal_el = math.degrees(math.atan2(float(pos.get("z", 0.0)) - float(wp.get("z", -10.0)), max(dist, 1e-3)))
    crop, side, f = square_crop(frame)
    half = crop_half_fov_deg(side, f)
    in_view = abs(goal_az) <= min(VLM_STRATEGIC_MAX_GOAL_OFF_DEG, half) and abs(goal_el) <= half
    if not in_view and int(state.get("_wp_no_progress_cycles") or 0) < VLM_STUCK_QUERY_CYCLES:
        return None
    # Meta fuera del recorte: no hay sector de la meta (nunca "camino directo libre"); la marca queda en
    # el borde del lado de la meta y la sub-meta sale del sector libre mas cercano a su direccion.
    goal_cell = cell_for_direction(goal_az, goal_el, side, f) if in_view else None
    img = annotate_grid(crop, f, goal_az, goal_el)
    if img is None:
        return None
    if goal_cell is not None:
        where = f"en el sector {goal_cell} (marca META)"
    else:
        lado = "izquierda" if goal_az < 0 else "derecha"
        where = f"fuera de la imagen, hacia la {lado} ({abs(goal_az):.0f} grados; marca META en el borde)"
    prompt = (
        f"Destino ({wp.get('label', 'WP')}): {dist:.0f} m, {where}. "
        f"Altura del dron: {abs(float(pos.get('z', 0.0))):.0f} m.\n"
        "Sectores: A1 B1 C1 (arriba), A2 B2 C2 (altura del dron), A3 B3 C3 (abajo).\n"
        "Describe cada sector y responde solo el JSON."
    )
    anchor = {
        "x": float(pos.get("x", 0.0)), "y": float(pos.get("y", 0.0)), "z": float(pos.get("z", 0.0)),
        "yaw_deg": yaw_deg, "ts": float(telem.get("timestamp") or time.time()), "sent_at": time.time(),
        "goal_az_deg": goal_az, "goal_el_deg": goal_el, "goal_cell": goal_cell, "crop_side": side, "focal_px": f,
        "wp_label": wp.get("label"), "wp_dist_xy": dist,
        "frame": crop,  # auditoria: el recorte que vio el modelo (sin la grilla dibujada)
    }
    payload = {
        "mode": "strategic",
        "prompt": prompt,
        "images_b64": [img],
        "image_labels": ["[Camara frontal, recorte cuadrado con grilla 3x3]"],
    }
    return payload, anchor


# --------------------------------------------------------------------------- respuesta
def parse_strategic(data: Any) -> Optional[Dict[str, Any]]:
    """Normaliza la respuesta. None si no tiene el formato esperado (nunca un valor por defecto)."""
    if not isinstance(data, dict):
        return None
    cells = data.get("sectores")
    if not isinstance(cells, dict):
        return None
    out: Dict[str, str] = {}
    for c in CELLS:
        v = str(cells.get(c, "")).strip().lower()
        if v not in CELL_STATES:
            return None
        out[c] = v
    return {"sectores": out}


def decide_subgoal(parsed: Dict[str, Any], anchor: Dict[str, Any], state: Dict[str, Any],
                   now: Optional[float] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """Traduce la descripcion del VLM a una sub-meta en coordenadas del mundo.

    Devuelve (sub_meta_o_None, motivo). Motivo "directo_libre": el sector de la meta esta libre, el
    guiado directo alcanza (y una sub-meta pendiente sobra). El tracker inserta la sub-meta tal cual
    (WaypointTracker.inject_corner_waypoint)."""
    now = time.time() if now is None else now
    age = now - float(anchor.get("sent_at", now))
    if age > VLM_STRATEGIC_MAX_AGE_S:
        return None, f"vencida ({age:.1f} s)"
    wp = real_waypoint(state)
    if wp is None or wp.get("label") != anchor.get("wp_label"):
        return None, "wp_cambio"

    cells = parsed["sectores"]
    goal_cell = anchor.get("goal_cell")
    if goal_cell is not None and cells.get(goal_cell) == "libre":
        return None, "directo_libre"
    free = [c for c in CELLS if cells[c] == "libre"]
    if not free:
        return None, "sin_sector_libre"

    centers = cell_centers_deg(int(anchor["crop_side"]), float(anchor["focal_px"]))
    gaz, gel = float(anchor["goal_az_deg"]), float(anchor["goal_el_deg"])
    best = min(free, key=lambda c: (math.hypot(centers[c][0] - gaz, centers[c][1] - gel), _ROW_PREF[c[1]]))
    az, el = centers[best]
    sub = build_subgoal(anchor["x"], anchor["y"], anchor["z"], float(anchor["yaw_deg"]) + az, el,
                        float(anchor.get("wp_dist_xy", VLM_SUBGOAL_DIST_M)), "VLM_SUBGOAL")
    d = sub.pop("dist_m")
    world = math.radians(float(anchor["yaw_deg"]) + az)

    pos = (state.get("telemetry") or {}).get("position") or {}
    px, py = float(pos.get("x", anchor["x"])), float(pos.get("y", anchor["y"]))
    # Superada: el dron ya esta cerca o paso la sub-meta a lo largo del rumbo elegido mientras el
    # modelo pensaba.
    along = (px - float(anchor["x"])) * math.cos(world) + (py - float(anchor["y"])) * math.sin(world)
    if math.hypot(sub["x"] - px, sub["y"] - py) < VLM_SUBGOAL_MIN_AHEAD_M or along > d - VLM_SUBGOAL_MIN_AHEAD_M:
        return None, "superada"
    sub["sector"] = best
    return sub, f"sector {best} ({az:+.0f} deg, {el:+.0f} deg, {d:.0f} m)"


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
        # Con una sub-meta activa tambien se consulta (re-planificacion): la pregunta es siempre sobre
        # el WP real, y una respuesta nueva reemplaza a la sub-meta vieja. Si la capa quedara muda
        # hasta el deadlock, una sub-meta mala no tendria como corregirse.
        alt = abs(float(((state.get("telemetry") or {}).get("position") or {}).get("z", 0.0)))
        if alt < VLM_STRATEGIC_MIN_ALT_M:
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
        if parsed is not None and "sectores" not in parsed:
            parsed = None
        subgoal, reason = ((None, getattr(result, "error", None) or "no_parseable") if parsed is None
                           else decide_subgoal(parsed, anchor, state))
        if reason == "directo_libre" and not current_target_is_real(state):
            state["_clear_subgoals"] = True   # el camino directo al WP esta libre: el desvio sobra
        if subgoal is not None:
            state["inject_corner"] = subgoal
            print(f"[vlm_strategic] sub-meta {reason} -> ({subgoal['x']:.1f},{subgoal['y']:.1f},{subgoal['z']:.1f}) "
                  f"[latencia {result.latency_ms:.0f} ms]")
        self.last_outcome = {
            "outcome": "subgoal" if subgoal else reason, "reason": reason,
            "latency_ms": round(float(result.latency_ms or 0.0), 1),
            "goal_cell": anchor.get("goal_cell"), "anchor": {k: anchor[k] for k in ("x", "y", "yaw_deg", "ts", "wp_label")},
            "parsed": parsed, "subgoal": subgoal,
        }
        return {
            "arm": "vlm_strategic", "prompt": payload.get("prompt", ""), "raw_response": result.raw_response or "",
            "parsed": parsed, "reason": reason, "subgoal": subgoal,
            "latency_ms": round(float(result.latency_ms or 0.0), 1), "timestamp": result.completed_at,
            "frame": anchor.get("frame"), "frame_ts": anchor.get("ts"),
        }
