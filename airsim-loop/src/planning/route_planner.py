"""Planificacion de ruta con el VLM sobre el mapa cenital, antes del vuelo (2026-10-02).

Problema: el manifiesto une los waypoints en linea recta, y en una ciudad la recta suele cruzar una
manzana (citysim_pilot, tramo WP_2 -> WP_3). En vuelo, el VLM solo ve lo que tiene delante a 10 m de altura
y tiene que adivinar por donde rodear un edificio cuyo final no ve. Desde arriba, en cambio, la pregunta es
facil y es del tipo que un VLM responde bien: reconocer si una linea dibujada va por la calle o por encima
de los edificios. No requiere estimar distancias ni geometria en primera persona.

Procedimiento (una sola vez por mision, antes de despegar; la mision espera el resultado):
  1. Para cada tramo A -> B del manifiesto (incluido el spawn -> primer WP) se generan rutas candidatas
     puramente geometricas, sin mirar el mapa: la recta; las dos en L (primero norte-sur o primero
     este-oeste); y desvios paralelos a +-ROUTE_DETOURS_M a cada lado.
  2. Cada candidata se dibuja sobre el recorte del mapa cenital que la contiene (linea roja, inicio verde,
     destino azul) y se le pregunta al VLM si la linea va en todo su recorrido sobre calles o espacios
     abiertos, sin pasar sobre edificios (si/no, decodificacion restringida, temperatura 0). La
     probabilidad de "si" se lee de los logprobs.
  3. Entre las candidatas que el VLM aprobo se elige la de mayor probabilidad (a menos de
     ROUTE_TIE_EPS, la mas corta). Si no aprobo ninguna queda la recta: el lazo de vuelo resuelve como
     siempre. Los vertices intermedios de la elegida se insertan como waypoints `VIA_<WP>_<k>` antes de B,
     con `planned_via: true` y la altura de B.

El VLM evalua; el codigo solo genera las opciones y toma la mejor segun el propio modelo. El plan completo
(candidatas, respuesta y probabilidad de cada una, elegida y motivo) y las imagenes que vio el modelo
quedan en el directorio del plan. El plan se cachea por contenido (waypoints, mapa, modelo, prompt): todas
las corridas de un lote vuelan el mismo plan.

El mapa tiene que estar registrado con el mundo de AirSim: centro de la imagen = `ned_offset`, arriba =
norte (+x), derecha = este (+y), `scale` px/m (airsim-plan/missions/maps/map_scales.json;
citysim_ortho.png se construye con airsim-plan/scripts/capture_ortho_map.py).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / "config" / ".env")
except Exception:  # pragma: no cover
    pass

from .vlm_logprobs import choice_probs_at, tokens_to_dicts, value_offsets

MAPS_DIR = Path(__file__).resolve().parents[3] / "airsim-plan" / "missions" / "maps"
ROUTE_DETOURS_M = [float(v) for v in os.getenv("ROUTE_DETOURS_M", "25,50").split(",") if v.strip()]
ROUTE_MIN_SIDE_M = float(os.getenv("ROUTE_MIN_SIDE_M", "10.0"))
ROUTE_MARGIN_M = float(os.getenv("ROUTE_MARGIN_M", "25.0"))
ROUTE_IMAGE_PX = int(os.getenv("ROUTE_IMAGE_PX", "672"))
ROUTE_TIE_EPS = float(os.getenv("ROUTE_TIE_EPS", "0.05"))
ROUTE_HTTP_TIMEOUT_S = float(os.getenv("ROUTE_HTTP_TIMEOUT_S", "60"))
# Dibujo de cada candidata: 'corridor' (pasillo de ROUTE_CORRIDOR_M de ancho, recorte propio rotado de
# inicio abajo a destino arriba, resto del mapa oscurecido) o 'line' (linea roja sobre el recorte comun
# del tramo, norte arriba; version anterior, para comparar en el banco).
ROUTE_RENDER = os.getenv("ROUTE_RENDER", "corridor")
ROUTE_CORRIDOR_M = float(os.getenv("ROUTE_CORRIDOR_M", "10.0"))
PLANNER_VERSION = "3"

CHOICES = ["si", "no"]                     # valores internos (plan, registros, banco)
# 2026-10-02: el modelo responde en ingles; read_judgement traduce a CHOICES.
ANSWERS = ["yes", "no"]
ANSWER_TO_CHOICE = dict(zip(ANSWERS, CHOICES))
_PROMPTS = {
    "line": (
        "You see a top-down city map, north up. A red line goes from the green dot (start) to the blue dot "
        "(end). Answer yes only if the whole line runs over streets or open ground, never over a building, "
        "trees or an elevated road. Reply with JSON only.",
        "Drone altitude {alt:.0f} m. Can it follow the red line? yes or no.",
    ),
    "corridor": (
        "You see a top-down city map. The bright strip outlined in red is a drone path from the green dot "
        "(bottom) to the blue dot; the rest is darkened. Answer yes only if the whole strip covers street or "
        "open ground, with no building, trees or elevated road inside it. Reply with JSON only.",
        "Drone altitude {alt:.0f} m. Is the whole bright strip street or open ground? yes or no.",
    ),
}
SYSTEM_PROMPT_ROUTE, USER_PROMPT_ROUTE = _PROMPTS.get(ROUTE_RENDER, _PROMPTS["corridor"])
# La altura del tramo va en el mensaje de cada consulta (no hay una altura fija en el prompt de sistema).
RESPONSE_JSON_SCHEMA_ROUTE = {"type": "json_schema", "json_schema": {"name": "route_check", "schema": {
    "type": "object", "properties": {"answer": {"type": "string", "enum": ANSWERS}},
    "required": ["answer"], "additionalProperties": False}}}

Point = Tuple[float, float]


# --------------------------------------------------------------------------- mapa
class MapView:
    """Mapa cenital registrado en NED (convencion de WebDCS)."""

    def __init__(self, image: Any, scale: float, ned_offset: Dict[str, float], name: str = "") -> None:
        self.image, self.scale, self.name = image, float(scale), name
        self.ox, self.oy = float(ned_offset.get("x", 0.0)), float(ned_offset.get("y", 0.0))
        self.h, self.w = image.shape[:2]

    @classmethod
    def load(cls, map_name: str, maps_dir: Path = MAPS_DIR) -> "MapView":
        import cv2

        scales = json.loads((maps_dir / "map_scales.json").read_text(encoding="utf-8"))
        cfg = scales.get(map_name)
        if cfg is None:
            raise KeyError(f"{map_name} no esta en map_scales.json")
        img = cv2.imread(str(maps_dir / map_name))
        if img is None:
            raise FileNotFoundError(maps_dir / map_name)
        return cls(img, cfg["scale"], cfg.get("ned_offset") or {}, map_name)

    def to_px(self, x: float, y: float) -> Tuple[float, float]:
        return self.w / 2.0 + (y - self.oy) * self.scale, self.h / 2.0 - (x - self.ox) * self.scale


# --------------------------------------------------------------------------- candidatas
def path_length(points: Sequence[Point]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def leg_candidates(a: Point, b: Point, detours: Sequence[float] = ROUTE_DETOURS_M,
                   min_side: float = ROUTE_MIN_SIDE_M) -> List[Dict[str, Any]]:
    """Rutas geometricas A -> B: recta, dos en L y desvios paralelos. Sin mirar el mapa."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    cands: List[Dict[str, Any]] = [{"name": "directo", "points": [a, b]}]
    if abs(dx) >= min_side and abs(dy) >= min_side:
        cands.append({"name": "L_norte_sur_primero", "points": [a, (b[0], a[1]), b]})
        cands.append({"name": "L_este_oeste_primero", "points": [a, (a[0], b[1]), b]})
    if d >= min_side:
        nx, ny = dy / d, -dx / d             # normal a la izquierda del avance (NED visto desde arriba:
        #                                      x norte, y este; avanzando al norte, la izquierda es el oeste)
        for off in detours:
            for sign, side in ((1.0, "izq"), (-1.0, "der")):
                o = sign * off
                cands.append({"name": f"desvio_{side}_{off:.0f}m",
                              "points": [a, (a[0] + nx * o, a[1] + ny * o), (b[0] + nx * o, b[1] + ny * o), b]})
    for c in cands:
        c["points"] = [(round(p[0], 2), round(p[1], 2)) for p in c["points"]]
        c["length_m"] = round(path_length(c["points"]), 1)
    return cands


def leg_window(cands: Sequence[Dict[str, Any]], margin: float = ROUTE_MARGIN_M) -> Tuple[float, float, float]:
    """Ventana cuadrada (centro x, centro y, semilado) que contiene todas las candidatas del tramo: todas
    se dibujan sobre el mismo recorte, a la misma escala."""
    xs = [p[0] for c in cands for p in c["points"]]
    ys = [p[1] for c in cands for p in c["points"]]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2.0 + margin
    return cx, cy, half


def render_candidate(mv: MapView, points: Sequence[Point], window: Tuple[float, float, float],
                     size: int = ROUTE_IMAGE_PX) -> Any:
    import cv2
    import numpy as np

    cx, cy, half = window
    u0, v0 = mv.to_px(cx + half, cy - half)        # esquina noroeste
    side_px = 2.0 * half * mv.scale
    k = size / side_px
    # Transformacion afin mapa -> imagen de salida (recorte + escala); fuera del mapa queda negro.
    M = np.float32([[k, 0, -u0 * k], [0, k, -v0 * k]])
    img = cv2.warpAffine(mv.image, M, (size, size), flags=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    to_img = lambda p: (int(round((mv.to_px(*p)[0] - u0) * k)), int(round((mv.to_px(*p)[1] - v0) * k)))  # noqa: E731
    pts = [to_img(p) for p in points]
    th = max(2, size // 160)
    cv2.polylines(img, [np.int32(pts)], False, (0, 0, 0), th + 3, cv2.LINE_AA)
    cv2.polylines(img, [np.int32(pts)], False, (0, 0, 255), th, cv2.LINE_AA)
    r = max(6, size // 60)
    cv2.circle(img, pts[0], r, (0, 200, 0), -1)
    cv2.circle(img, pts[0], r, (0, 0, 0), 2)
    cv2.circle(img, pts[-1], r, (255, 80, 0), -1)
    cv2.circle(img, pts[-1], r, (0, 0, 0), 2)
    return img


def render_corridor(mv: MapView, points: Sequence[Point], size: int = ROUTE_IMAGE_PX,
                    corridor_m: float = ROUTE_CORRIDOR_M, margin_m: float = ROUTE_MARGIN_M) -> Any:
    """La candidata como pasillo del ancho que necesita el dron, sobre su propio recorte (2026-10-02).

    El recorte se rota para que la ruta vaya de abajo (inicio) hacia arriba (destino) y se acerca a la
    candidata; fuera del pasillo el mapa se oscurece. El modelo juzga que hay DEBAJO del pasillo, no si
    una linea fina roza un techo."""
    import cv2
    import numpy as np

    P = np.float64([mv.to_px(*p) for p in points])
    d = P[-1] - P[0]
    phi = (-math.pi / 2 - math.atan2(d[1], d[0])) if np.hypot(*d) > 1e-6 else 0.0
    R = np.array([[math.cos(phi), -math.sin(phi)], [math.sin(phi), math.cos(phi)]])
    Q = P @ R.T
    lo, hi = Q.min(axis=0), Q.max(axis=0)
    side = max(hi[0] - lo[0], hi[1] - lo[1]) + 2.0 * (margin_m + corridor_m / 2.0) * mv.scale
    k = size / side
    c = (lo + hi) / 2.0
    M = np.hstack([k * R, (np.float64([size / 2.0, size / 2.0]) - k * c).reshape(2, 1)]).astype(np.float32)
    img = cv2.warpAffine(mv.image, M, (size, size), flags=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    pts = np.int32(np.round(P @ (k * R).T + (size / 2.0 - k * c)))
    mask = np.zeros((size, size), np.uint8)
    cv2.polylines(mask, [pts], False, 255, max(2, int(round(corridor_m * mv.scale * k))), cv2.LINE_AA)
    out = (img.astype(np.float32) * 0.3).astype(np.uint8)
    out[mask > 0] = img[mask > 0]
    contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, (0, 0, 255), max(1, size // 336), cv2.LINE_AA)
    r = max(5, size // 80)
    for p, color in ((tuple(pts[0]), (0, 200, 0)), (tuple(pts[-1]), (255, 80, 0))):
        cv2.circle(out, p, r, color, -1)
        cv2.circle(out, p, r, (0, 0, 0), 2)
    return out


def render(mv: MapView, points: Sequence[Point], cands: Sequence[Dict[str, Any]], mode: str = ROUTE_RENDER) -> Any:
    """Imagen de una candidata segun ROUTE_RENDER: 'corridor' (pasillo, recorte propio) o 'line'."""
    if mode == "line":
        return render_candidate(mv, points, leg_window(cands))
    return render_corridor(mv, points)


# --------------------------------------------------------------------------- VLM
QueryFn = Callable[..., Dict[str, Any]]


def default_query(img: Any, alt_m: float = 10.0) -> Dict[str, Any]:
    """Consulta real al VLM (LM Studio/Ollama, API OpenAI) con logprobs. Devuelve text, tokens, latency_ms."""
    import base64

    import cv2
    from openai import OpenAI

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    b64 = base64.b64encode(buf).decode("utf-8")
    client = OpenAI(base_url=os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1"),
                    api_key=os.getenv("LOCAL_LLM_API_KEY", "ollama"))
    t0 = time.time()
    r = client.chat.completions.create(
        model=model_name(),
        messages=[{"role": "system", "content": SYSTEM_PROMPT_ROUTE},
                  {"role": "user", "content": [{"type": "text", "text": USER_PROMPT_ROUTE.format(alt=alt_m)},
                                               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        response_format=RESPONSE_JSON_SCHEMA_ROUTE, temperature=0.0, max_tokens=32,
        logprobs=True, top_logprobs=10, timeout=ROUTE_HTTP_TIMEOUT_S,
    )
    ch = r.choices[0]
    return {"text": ch.message.content or "", "latency_ms": (time.time() - t0) * 1000.0,
            "tokens": tokens_to_dicts(ch.logprobs.content) if ch.logprobs is not None else []}


def model_name() -> str:
    """Modelo del planificador: ROUTE_LLM_MODEL_NAME; si no esta, el mismo del vuelo."""
    return os.getenv("ROUTE_LLM_MODEL_NAME") or os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")


def read_judgement(resp: Dict[str, Any]) -> Dict[str, Any]:
    text = resp.get("text") or ""
    try:
        import re

        m = re.search(r"\{[\s\S]*\}", text)
        answer = json.loads(m.group(0)).get("answer") if m else None
    except ValueError:
        answer = None
    answer = ANSWER_TO_CHOICE.get(answer)
    offs = value_offsets(text, "answer")
    probs = choice_probs_at(resp.get("tokens") or [], offs[0], ANSWERS) if offs else None
    p_si = probs["yes"] if probs else (1.0 if answer == "si" else 0.0 if answer == "no" else None)
    return {"answer": answer if answer in CHOICES else None, "p_si": None if p_si is None else round(p_si, 4),
            "latency_ms": round(float(resp.get("latency_ms") or 0.0), 1)}


# --------------------------------------------------------------------------- juicio por parches (2026-10-02)
# Las preguntas por la ruta entera (si/no, con linea o con pasillo) quedaron en sesgo puro con los dos
# modelos. La unica forma de preguntar con senal fue clasificar un parche del mapa en cinco clases
# (experiments/vlm_bench/map_probe.py: LFM2.5-VL-1.6B, exactitud balanceada 0.72, AUC 0.80). Cada
# candidata se muestrea cada ROUTE_PATCH_STEP_M; el VLM clasifica el parche de ROUTE_PATCH_M centrado en
# cada punto y la candidata se puntua con la P(calle) media (street + parking, de los logprobs). No hay
# umbral: se comparan las candidatas del tramo entre si.
ROUTE_JUDGE = os.getenv("ROUTE_JUDGE", "patches")          # patches | image
ROUTE_PATCH_STEP_M = float(os.getenv("ROUTE_PATCH_STEP_M", "8.0"))
ROUTE_PATCH_M = float(os.getenv("ROUTE_PATCH_M", "16.0"))
ROUTE_PATCH_CONTEXT_M = float(os.getenv("ROUTE_PATCH_CONTEXT_M", "48.0"))
ROUTE_PATCH_PX = int(os.getenv("ROUTE_PATCH_PX", "336"))
PATCH_SYSTEM = "You see a top-down city map. Reply with JSON only."
PATCH_PROMPT = "What is inside the red square? street, building, trees, parking or elevated road."
PATCH_CLASSES = ["street", "building", "trees", "parking", "elevated road"]
PATCH_GROUND = {"street", "parking"}
RESPONSE_JSON_SCHEMA_PATCH = {"type": "json_schema", "json_schema": {"name": "map_patch", "schema": {
    "type": "object", "properties": {"answer": {"type": "string", "enum": PATCH_CLASSES}},
    "required": ["answer"], "additionalProperties": False}}}


def patch_points(points: Sequence[Point], step: float = ROUTE_PATCH_STEP_M) -> List[Point]:
    """Puntos cada `step` metros a lo largo de la poligonal, incluidos los extremos."""
    out: List[Point] = []
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) // step))
        out += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n)]
    return out + [tuple(points[-1])]


def patch_crop(mv: MapView, x: float, y: float, size: int = ROUTE_PATCH_PX,
               context_m: float = ROUTE_PATCH_CONTEXT_M, patch_m: float = ROUTE_PATCH_M) -> Any:
    """Recorte de context_m de lado, norte arriba, con un cuadrado rojo en los patch_m centrales."""
    import cv2
    import numpy as np

    u, v = mv.to_px(x, y)
    half = context_m / 2 * mv.scale
    k = size / (2 * half)
    M = np.float32([[k, 0, -(u - half) * k], [0, k, -(v - half) * k]])
    img = cv2.warpAffine(mv.image, M, (size, size), flags=cv2.INTER_CUBIC)
    s, c = patch_m / context_m * size / 2, size / 2
    cv2.rectangle(img, (int(c - s), int(c - s)), (int(c + s), int(c + s)), (0, 0, 255), 2)
    return img


def default_patch_query(img: Any) -> Dict[str, Any]:
    """Clasificacion de un parche del mapa (cinco clases) con logprobs."""
    import base64

    import cv2
    from openai import OpenAI

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    b64 = base64.b64encode(buf).decode("utf-8")
    client = OpenAI(base_url=os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1"),
                    api_key=os.getenv("LOCAL_LLM_API_KEY", "ollama"))
    t0 = time.time()
    r = client.chat.completions.create(
        model=model_name(),
        messages=[{"role": "system", "content": PATCH_SYSTEM},
                  {"role": "user", "content": [{"type": "text", "text": PATCH_PROMPT},
                                               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        response_format=RESPONSE_JSON_SCHEMA_PATCH, temperature=0.0, max_tokens=16,
        logprobs=True, top_logprobs=10, timeout=ROUTE_HTTP_TIMEOUT_S,
    )
    ch = r.choices[0]
    return {"text": ch.message.content or "", "latency_ms": (time.time() - t0) * 1000.0,
            "tokens": tokens_to_dicts(ch.logprobs.content) if ch.logprobs is not None else []}


def read_patch(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Clase respondida y P(calle) = P(street) + P(parking); sin logprobs, 1/0 segun la clase."""
    text = resp.get("text") or ""
    try:
        import re

        m = re.search(r"\{[\s\S]*\}", text)
        answer = json.loads(m.group(0)).get("answer") if m else None
    except ValueError:
        answer = None
    answer = answer if answer in PATCH_CLASSES else None
    offs = value_offsets(text, "answer")
    probs = choice_probs_at(resp.get("tokens") or [], offs[0], PATCH_CLASSES) if offs else None
    if probs:
        p = sum(probs[c] for c in PATCH_GROUND)
    else:
        p = None if answer is None else float(answer in PATCH_GROUND)
    return {"answer": answer, "p_ground": None if p is None else round(p, 4)}


def judge_patches(mv: MapView, points: Sequence[Point], patch_query: Optional[QueryFn] = None,
                  cache: Optional[Dict[Tuple[float, float], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Puntua una candidata: P(calle) media de sus parches (p_si, para usar la misma eleccion).

    `cache` (por plan): las candidatas de un tramo comparten inicio, final y tramos, y los tramos
    consecutivos comparten waypoints; un parche ya clasificado no se vuelve a consultar."""
    patch_query = patch_query or default_patch_query
    cache = {} if cache is None else cache
    patches, t0 = [], time.time()
    for x, y in patch_points(points):
        key = (round(x, 1), round(y, 1))
        if key not in cache:
            try:
                cache[key] = read_patch(patch_query(patch_crop(mv, x, y)))
            except Exception as exc:
                cache[key] = {"answer": None, "p_ground": None, "error": str(exc)}
        patches.append({"x": key[0], "y": key[1], **cache[key]})
    ps = [p["p_ground"] for p in patches if p["p_ground"] is not None]
    return {"judge": "patches", "answer": None, "p_si": round(sum(ps) / len(ps), 4) if ps else None,
            "p_min": round(min(ps), 4) if ps else None, "patches": patches,
            "latency_ms": round((time.time() - t0) * 1000.0, 1)}


def judge_candidate(mv: MapView, c: Dict[str, Any], cands: Sequence[Dict[str, Any]], alt_m: float,
                    judge: str = ROUTE_JUDGE, query: Optional[QueryFn] = None,
                    patch_query: Optional[QueryFn] = None,
                    cache: Optional[Dict[Tuple[float, float], Dict[str, Any]]] = None) -> Tuple[Any, Dict[str, Any]]:
    """(imagen de la candidata para auditoria, juicio). 'patches' o 'image' (pregunta si/no por la ruta)."""
    img = render(mv, c["points"], cands)
    if judge == "patches":
        return img, judge_patches(mv, c["points"], patch_query, cache)
    return img, {"judge": "image", **read_judgement((query or default_query)(img, alt_m=alt_m))}


def choose(cands: Sequence[Dict[str, Any]], tie_eps: float = ROUTE_TIE_EPS) -> Tuple[Dict[str, Any], str]:
    """La de mayor puntaje; a menos de tie_eps de la mejor, la mas corta (la recta, si empata).

    Juicio 'image': solo cuentan las aprobadas (respuesta 'si'). Juicio 'patches': todas las puntuadas
    (la puntuacion es relativa, no hay respuesta absoluta)."""
    scored = [c for c in cands if c.get("p_si") is not None
              and (c.get("judge") == "patches" or c.get("answer") == "si")]
    if not scored:
        return next(c for c in cands if c["name"] == "directo"), "ninguna_aprobada"
    top = max(c["p_si"] for c in scored)
    near = [c for c in scored if c["p_si"] >= top - tie_eps]
    best = min(near, key=lambda c: c["length_m"])
    return best, "mejor_puntaje" if best.get("judge") == "patches" else "aprobada"


# --------------------------------------------------------------------------- mision
def legs(manifest: Dict[str, Any]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    wps = [w for w in manifest.get("waypoints") or [] if not w.get("planned_via")]
    sp = manifest.get("start_pose")
    start = {"x": sp["x"], "y": sp["y"], "z": sp.get("z", -10.0), "label": "START"} if sp else None
    seq = ([start] if start else []) + wps
    return list(zip(seq, seq[1:]))


def plan_key(manifest: Dict[str, Any]) -> str:
    payload = json.dumps({"wps": [(w["x"], w["y"], w.get("z"), w.get("label")) for w in manifest.get("waypoints") or []
                                  if not w.get("planned_via")],
                          "start": manifest.get("start_pose"), "map": manifest.get("map"), "model": model_name(),
                          "system": SYSTEM_PROMPT_ROUTE, "user": USER_PROMPT_ROUTE, "detours": ROUTE_DETOURS_M,
                          "size": ROUTE_IMAGE_PX, "render": ROUTE_RENDER,
                          "corridor": ROUTE_CORRIDOR_M, "judge": ROUTE_JUDGE,
                          "patch": [ROUTE_PATCH_STEP_M, ROUTE_PATCH_M, ROUTE_PATCH_CONTEXT_M, ROUTE_PATCH_PX,
                                    PATCH_SYSTEM, PATCH_PROMPT],
                          "v": PLANNER_VERSION}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def plan_route(manifest: Dict[str, Any], out_dir: Optional[Path] = None, mv: Optional[MapView] = None,
               query: Optional[QueryFn] = None, log: Callable[[str], None] = print,
               judge: str = ROUTE_JUDGE, patch_query: Optional[QueryFn] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Devuelve (manifiesto con los VIA insertados, plan). Guarda imagenes y plan.json en out_dir."""
    import cv2

    if not manifest.get("map"):
        raise ValueError("el manifiesto no declara 'map': no hay mapa sobre el cual planificar")
    mv = mv or MapView.load(manifest["map"])
    if out_dir is not None:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    plan: Dict[str, Any] = {"version": PLANNER_VERSION, "key": plan_key(manifest), "model": model_name(),
                            "judge": judge, "map": manifest["map"], "legs": []}
    vias_before: Dict[str, List[Dict[str, Any]]] = {}
    patch_cache: Dict[Tuple[float, float], Dict[str, Any]] = {}
    t0 = time.time()
    for li, (a, b) in enumerate(legs(manifest)):
        A, B = (float(a["x"]), float(a["y"])), (float(b["x"]), float(b["y"]))
        cands = leg_candidates(A, B)
        for c in cands:
            try:
                img, verdict = judge_candidate(mv, c, cands, abs(float(b.get("z", -10.0))), judge=judge,
                                               query=query, patch_query=patch_query, cache=patch_cache)
                c.update(verdict)
            except Exception as exc:
                img = None
                c.update({"judge": judge, "answer": None, "p_si": None, "error": str(exc)})
            if out_dir is not None and img is not None:
                c["image"] = f"leg{li:02d}_{b['label']}_{c['name']}.jpg"
                cv2.imwrite(str(Path(out_dir) / c["image"]), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        best, reason = choose(cands)
        vias = [{"x": p[0], "y": p[1], "z": float(b.get("z", -10.0)), "label": f"VIA_{b['label']}_{k + 1}",
                 "planned_via": True} for k, p in enumerate(best["points"][1:-1])]
        vias_before[b["label"]] = vias
        plan["legs"].append({"from": a["label"], "to": b["label"], "chosen": best["name"], "reason": reason,
                             "vias": vias, "candidates": cands})
        log(f"[route_plan] {a['label']} -> {b['label']}: {best['name']} ({reason}; "
            + ", ".join(f"{c['name']}={c.get('answer') or 'P'}/{c.get('p_si')}" for c in cands) + ")")
    plan["elapsed_s"] = round(time.time() - t0, 1)
    planned = dict(manifest)
    new_wps: List[Dict[str, Any]] = []
    for w in manifest.get("waypoints") or []:
        if w.get("planned_via"):
            continue
        new_wps += vias_before.get(w.get("label"), [])
        new_wps.append(w)
    planned["waypoints"] = new_wps
    planned["route_plan"] = {"mode": "vlm", "judge": judge, "key": plan["key"], "model": plan["model"], "map": plan["map"],
                             "vias": sum(len(l["vias"]) for l in plan["legs"]),
                             "legs_rerouted": sum(1 for l in plan["legs"] if l["chosen"] != "directo")}
    if out_dir is not None:
        (Path(out_dir) / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return planned, plan


def plan_scenario(scenario_path: str, out_root: str, log: Callable[[str], None] = print) -> str:
    """Planifica un escenario (con cache) y devuelve la ruta del manifiesto planificado.

    El manifiesto planificado conserva el nombre del original (el runner usa el nombre como escenario) y
    queda en <out_root>/<escenario>/route_plan/. Si ya existe uno con la misma clave, se reutiliza."""
    manifest = json.loads(Path(scenario_path).read_text(encoding="utf-8"))
    stem = Path(scenario_path).stem
    out_dir = Path(out_root) / stem / "route_plan"
    planned_path = out_dir / f"{stem}.json"
    key = plan_key(manifest)
    if planned_path.exists():
        try:
            prev = json.loads(planned_path.read_text(encoding="utf-8"))
            if (prev.get("route_plan") or {}).get("key") == key:
                log(f"[route_plan] {stem}: plan {key} ya calculado, se reutiliza ({planned_path})")
                return str(planned_path)
        except ValueError:
            pass
    log(f"[route_plan] {stem}: planificando con {model_name()} sobre {manifest.get('map')}...")
    planned, plan = plan_route(manifest, out_dir=out_dir, log=log)
    planned_path.write_text(json.dumps(planned, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"[route_plan] {stem}: {planned['route_plan']['legs_rerouted']} tramo(s) desviados, "
        f"{planned['route_plan']['vias']} punto(s) de paso, {plan['elapsed_s']} s -> {planned_path}")
    return str(planned_path)
