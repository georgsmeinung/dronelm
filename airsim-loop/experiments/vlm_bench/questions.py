"""Catalogo de preguntas del banco.

Cada pregunta define: a que muestras aplica, como arma la imagen y el prompt, el esquema JSON (decodificacion
restringida, igual que en vuelo), la etiqueta verdadera y como leer la respuesta. Las opciones de cada
pregunta tienen iniciales distintas para poder leer su probabilidad en `top_logprobs` (common.choice_probs_at).

Preguntas:
  grid_prod         la pregunta de vuelo de la capa estrategica, tal cual (prompt, esquema, grilla, META)
  grid_perm         la misma, con las etiquetas de los sectores permutadas: separa escena de posicion
  centro_libre      "se puede avanzar recto 15 m?" (si/no), sobre el recorte cuadrado sin grilla
  borde_lateral     con obstaculo de frente: por que lado termina (izquierda/derecha/ninguno)
  borde_superior    con obstaculo de frente: se ve espacio libre por encima (si/no)
  direccion_abierta tercio con mas espacio libre a la altura del dron (izquierda/centro/derecha/ninguna)
  scan_prod         la pregunta de vuelo del barrido, con las imagenes de un barrido real
  scan_perm         la misma, con las imagenes en otro orden
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, encode_jpeg, image_part, text_part  # noqa: E402

sys.path.insert(0, str(ROOT))
from src.agents import vlm_strategic as vs  # noqa: E402
from src.agents.deep_scan import (  # noqa: E402
    DEEP_SCAN_IMAGE_MAX_SIZE, RESPONSE_JSON_SCHEMA_PANORAMA, SYSTEM_PROMPT_DEEP_SCAN,
)

CELLS = vs.CELLS


def _enum_schema(name: str, choices: List[str]) -> Dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": {
        "type": "object", "properties": {"respuesta": {"type": "string", "enum": choices}},
        "required": ["respuesta"], "additionalProperties": False}}}


SYSTEM_SHORT = (
    "Sos el sistema de percepcion de un dron que vuela a baja altura en un entorno urbano. Recibes la "
    "imagen de su camara frontal. El centro de la imagen es la direccion en la que avanza el dron, a su "
    "altura. Responde UNICAMENTE con JSON {\"respuesta\": <opcion>}."
)

SINGLE = {
    "centro_libre": {
        "choices": ["si", "no"], "positive": "si", "gt": "center_free",
        "prompt": "Puede el dron avanzar en linea recta hacia el centro de la imagen al menos 15 m sin chocar "
                  "con nada (edificio, fachada, vidrio, muro, arbol o vegetacion, puente o estructura elevada, "
                  "cornisa)? Opciones: si, no.",
    },
    "borde_lateral": {
        "choices": ["izquierda", "derecha", "ninguno"], "positive": None, "gt": "edge_side",
        "prompt": "Delante del dron hay un obstaculo. Por que lado termina el obstaculo, es decir, por donde "
                  "se ve espacio libre para rodearlo a la misma altura? Opciones: izquierda, derecha, "
                  "ninguno (no se ve donde termina).",
    },
    "borde_superior": {
        "choices": ["si", "no"], "positive": "si", "gt": "top_clear",
        "prompt": "Delante del dron hay un obstaculo. Se ve cielo o espacio libre justo por encima de el, "
                  "en la parte de arriba del centro de la imagen? Opciones: si, no.",
    },
    "direccion_abierta": {
        "choices": ["izquierda", "centro", "derecha", "ninguna"], "positive": None, "gt": "open_dir",
        "prompt": "En cual tercio de la imagen (izquierda, centro, derecha) hay mas espacio libre para volar "
                  "a la altura del dron, como una calle que se aleja? Si en ninguno hay al menos 15 m "
                  "libres, responde ninguna. Opciones: izquierda, centro, derecha, ninguna.",
    },
}


def goal_dir(sample: Dict[str, Any]) -> Optional[Dict[str, float]]:
    g, p = sample.get("goal"), sample["pose"]
    if not g:
        return None
    dist = math.hypot(g["x"] - p["x"], g["y"] - p["y"])
    az = vs._norm_deg(math.degrees(math.atan2(g["y"] - p["y"], g["x"] - p["x"])) - p["yaw_deg"])
    el = math.degrees(math.atan2(p["z"] - g["z"], max(dist, 1e-3)))
    return {"az": az, "el": el, "dist": dist}


def _grid_image(img, sample, size: int, labels: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Recorte cuadrado con grilla y META como en vuelo; `labels` = etiqueta dibujada en cada sector."""
    import base64

    import cv2

    gd = goal_dir(sample)
    if gd is None:
        return None
    crop, side, f = vs.square_crop(img)
    if labels is None:
        return vs.annotate_grid(crop, f, gd["az"], gd["el"], max_size=size)
    b64 = vs.annotate_grid(crop, f, gd["az"], gd["el"], max_size=size)
    # Redibuja las etiquetas permutadas sobre la imagen ya anotada (tapando las originales).
    arr = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
    out = arr.shape[0]
    scale = max(0.4, out / 640.0)
    for ci, c in enumerate(vs.GRID_COLS):
        for ri, r in enumerate(vs.GRID_ROWS):
            x0, y0 = ci * out // 3 + 1, ri * out // 3 + 1
            cv2.rectangle(arr, (x0, y0), (x0 + int(34 * scale), y0 + int(24 * scale)), (0, 0, 0), -1)
            org = (ci * out // 3 + int(4 * scale), ri * out // 3 + int(18 * scale))
            cv2.putText(arr, labels[c + r], org, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (255, 255, 255), 1)
    return encode_jpeg(arr, quality=80)


def perm_labels(sample_id: str) -> Dict[str, str]:
    """Permutacion fija por muestra: posicion fisica -> etiqueta dibujada (no la identidad)."""
    rng = random.Random(sample_id)
    lab = CELLS[:]
    while True:
        rng.shuffle(lab)
        if all(a != b for a, b in zip(CELLS, lab)):
            return dict(zip(CELLS, lab))


def grid_prompt(sample: Dict[str, Any], labels: Optional[Dict[str, str]] = None) -> str:
    gd = goal_dir(sample)
    crop_side, f = 720, vs._focal_px(1080)
    in_view = abs(gd["az"]) <= vs.crop_half_fov_deg(crop_side, f) and abs(gd["el"]) <= vs.crop_half_fov_deg(crop_side, f)
    if in_view:
        cell = vs.cell_for_direction(gd["az"], gd["el"], crop_side, f)
        where = f"en el sector {labels[cell] if labels else cell} (marca META)"
    else:
        lado = "izquierda" if gd["az"] < 0 else "derecha"
        where = f"fuera de la imagen, hacia la {lado} ({abs(gd['az']):.0f} grados; marca META en el borde)"
    if labels is None:
        rows = "Sectores: A1 B1 C1 (arriba), A2 B2 C2 (altura del dron), A3 B3 C3 (abajo)."
    else:
        rows = ("Las etiquetas de los sectores estan dibujadas en la esquina de cada uno. Fila de arriba: "
                + " ".join(labels[c + "1"] for c in "ABC") + "; fila del medio (altura del dron): "
                + " ".join(labels[c + "2"] for c in "ABC") + "; fila de abajo: "
                + " ".join(labels[c + "3"] for c in "ABC") + ".")
    return (f"Destino ({(sample.get('goal') or {}).get('label', 'WP')}): {gd['dist']:.0f} m, {where}. "
            f"Altura del dron: {abs(sample['pose']['z']):.0f} m.\n{rows}\nDescribe cada sector y responde solo el JSON.")


# --------------------------------------------------------------------------- interfaz comun
class Question:
    name: str
    kind: str = "single"          # single | grid | scan

    def applies(self, sample: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def build(self, sample: Dict[str, Any], images: List[Any], size: int) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class SingleQuestion(Question):
    def __init__(self, name: str) -> None:
        self.name = name
        self.spec = SINGLE[name]
        self.choices = self.spec["choices"]

    def truth(self, sample: Dict[str, Any]) -> Optional[str]:
        return sample["gt"].get(self.spec["gt"])

    def applies(self, sample: Dict[str, Any]) -> bool:
        return self.truth(sample) is not None

    def build(self, sample, images, size):
        crop, _side, _f = vs.square_crop(images[0])
        return {"system": SYSTEM_SHORT, "parts": [text_part(self.spec["prompt"]), image_part(encode_jpeg(crop, size))],
                "schema": _enum_schema(self.name, self.choices), "keys": ["respuesta"], "max_tokens": 32}


class GridQuestion(Question):
    kind = "grid"

    def __init__(self, permuted: bool) -> None:
        self.permuted = permuted
        self.name = "grid_perm" if permuted else "grid_prod"
        self.choices = vs.CELL_STATES

    def applies(self, sample):
        return goal_dir(sample) is not None

    def labels(self, sample) -> Optional[Dict[str, str]]:
        return perm_labels(sample["id"]) if self.permuted else None

    def build(self, sample, images, size):
        labels = self.labels(sample)
        b64 = _grid_image(images[0], sample, size, labels)
        if b64 is None:
            return None
        return {"system": vs.SYSTEM_PROMPT_STRATEGIC,
                "parts": [text_part(grid_prompt(sample, labels)), text_part("[Camara frontal, recorte cuadrado con grilla 3x3]:"),
                          image_part(b64)],
                "schema": vs.RESPONSE_JSON_SCHEMA_STRATEGIC, "keys": CELLS, "max_tokens": 384}

    def physical(self, sample, answers_by_label: Dict[str, str]) -> Dict[str, Optional[str]]:
        """Respuesta por posicion fisica (deshace la permutacion)."""
        labels = self.labels(sample) or {c: c for c in CELLS}
        return {pos: answers_by_label.get(lab) for pos, lab in labels.items()}


class ScanQuestion(Question):
    kind = "scan"

    def __init__(self, permuted: bool) -> None:
        self.permuted = permuted
        self.name = "scan_perm" if permuted else "scan_prod"

    def applies(self, sample):
        return sample.get("kind") == "scan_group"

    def order(self, sample) -> List[int]:
        n = len(sample["members"])
        idx = list(range(n))
        if self.permuted:
            rng = random.Random(sample["id"])
            while idx == list(range(n)) and n > 1:
                rng.shuffle(idx)
        return idx

    def build(self, sample, images, size):
        size = min(size, DEEP_SCAN_IMAGE_MAX_SIZE) if size <= 384 else size
        parts = [text_part(f"Barrido de {len(images)} rumbos a {abs(sample['pose']['z']):.0f} m de altura. "
                           "Describe cada imagen y responde solo el JSON.")]
        for k, i in enumerate(self.order(sample)):
            parts.append(text_part(f"[Imagen {k + 1}]:"))
            parts.append(image_part(encode_jpeg(images[i], size)))
        return {"system": SYSTEM_PROMPT_DEEP_SCAN, "parts": parts, "schema": RESPONSE_JSON_SCHEMA_PANORAMA,
                "keys": [], "max_tokens": 512}


def catalog() -> Dict[str, Question]:
    qs: List[Question] = [GridQuestion(False), GridQuestion(True)]
    qs += [SingleQuestion(n) for n in SINGLE]
    qs += [ScanQuestion(False), ScanQuestion(True)]
    return {q.name: q for q in qs}


QUESTION_NAMES: List[str] = [
    "grid_prod", "grid_perm", "centro_libre", "borde_lateral", "borde_superior", "direccion_abierta",
    "scan_prod", "scan_perm"]
