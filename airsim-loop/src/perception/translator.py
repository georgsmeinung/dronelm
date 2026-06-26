# Paso 2: Traduccion Pixeles-a-Palabras.
# Convierte las cajas delimitadoras de YOLO en conceptos textuales
# estructurados (tipo de objeto, sector del encuadre y proximidad).
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - python-dotenv es opcional
    pass

from .detector import Detection


# Anchura y altura nominal del frame de AirSim para la camara frontal "0".
# Se puede sobreescribir desde el entorno para escenarios personalizados.
DEFAULT_FRAME_WIDTH = int(os.getenv("DEFAULT_FRAME_WIDTH", "256"))
DEFAULT_FRAME_HEIGHT = int(os.getenv("DEFAULT_FRAME_HEIGHT", "144"))

# Banda central como porcentaje del ancho del frame. El resto se reparte
# simetricamente entre los sectores Izquierda y Derecha.
CENTER_BAND_RATIO = float(os.getenv("CENTER_BAND_RATIO", "0.34"))

# Escalas de proximidad (en metros) calibradas para el modo Drone de AirSim.
# Mas alla de FAR_THRESHOLD se considera "Lejos".
NEAR_THRESHOLD = float(os.getenv("PROXIMITY_NEAR_M", "3.0"))
FAR_THRESHOLD = float(os.getenv("PROXIMITY_FAR_M", "8.0"))

# Tipos de obstaculos que el Gatekeeper debe tratar con prioridad.
CRITICAL_CLASSES = {"tree", "person", "car", "truck", "bus", "building", "pole"}


@dataclass
class Obstacle:
    """Obstaculo textual listo para alimentar al Gatekeeper / al LLM."""

    object: str
    sector: str  # "Izquierda" | "Centro" | "Derecha"
    proximity: str  # "Inminente" | "Cerca" | "Lejos"
    distance_m: Optional[float]
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _classify_sector(cx: float, frame_width: int) -> str:
    """Devuelve el sector horizontal del encuadre segun la coordenada x."""
    center_band = frame_width * CENTER_BAND_RATIO
    half = center_band / 2.0
    left_bound = (frame_width / 2.0) - half
    right_bound = (frame_width / 2.0) + half
    if cx < left_bound:
        return "Izquierda"
    if cx > right_bound:
        return "Derecha"
    return "Centro"


def _classify_proximity(distance_m: Optional[float]) -> str:
    """Traduce una distancia en metros a un nivel cualitativo de proximidad."""
    if distance_m is None:
        return "Desconocida"
    if distance_m <= NEAR_THRESHOLD:
        return "Inminente"
    if distance_m <= FAR_THRESHOLD:
        return "Cerca"
    return "Lejos"


def _estimate_distance(
    detection: Detection, frame_height: int, threshold_m: float
) -> Optional[float]:
    """Heuristica simple: cuanto mayor es la caja, mas cerca esta el objeto.

    La altura del bounding box se normaliza por la altura del frame y se
    proyecta sobre ``threshold_m`` (la distancia a la que un objeto ocupa
    aproximadamente la mitad del frame). Es una estimacion grosera, util
    para clasificar cualitativamente, no para navegacion de precision.
    """
    if frame_height <= 0:
        return None
    _, y_min, _, y_max = detection.bbox
    box_height = max(1.0, float(y_max - y_min))
    coverage = min(1.0, box_height / float(frame_height))
    # coverage==1 -> distance ~ threshold_m * 0.25, coverage~0 -> >> threshold
    if coverage <= 0.0:
        return None
    distance = (threshold_m * 0.25) / coverage
    return float(distance)


def translate_detections(
    detections: List[Detection],
    frame_width: int = DEFAULT_FRAME_WIDTH,
    frame_height: int = DEFAULT_FRAME_HEIGHT,
    proximity_threshold_m: Optional[float] = None,
) -> List[Obstacle]:
    """Convierte detecciones YOLO en obstaculos textuales estructurados."""
    threshold = (
        proximity_threshold_m
        if proximity_threshold_m is not None
        else float(os.getenv("PROXIMITY_THRESHOLD_METERS", "5.0"))
    )
    obstacles: List[Obstacle] = []
    for det in detections:
        if det.bbox is None or len(det.bbox) != 4:
            continue
        x_min, y_min, x_max, y_max = det.bbox
        cx = (x_min + x_max) / 2.0
        sector = _classify_sector(cx, frame_width)
        distance = _estimate_distance(det, frame_height, threshold)
        proximity = _classify_proximity(distance)
        obstacles.append(
            Obstacle(
                object=str(det.object),
                sector=sector,
                proximity=proximity,
                distance_m=distance,
                confidence=float(det.confidence),
            )
        )
    # Orden priorizando: Centro > Cercania > confianza
    sector_weight = {"Centro": 0, "Izquierda": 1, "Derecha": 1}
    prox_weight = {"Inminente": 0, "Cerca": 1, "Lejos": 2, "Desconocida": 3}
    obstacles.sort(
        key=lambda o: (
            sector_weight.get(o.sector, 2),
            prox_weight.get(o.proximity, 4),
            -o.confidence,
        )
    )
    return obstacles


def obstacles_to_dicts(obstacles: List[Obstacle]) -> List[Dict[str, Any]]:
    return [o.to_dict() for o in obstacles]


def summarize_scene(obstacles: List[Obstacle]) -> str:
    """Genera un resumen textual corto, ideal como prompt para el SLM."""
    if not obstacles:
        return "Camino libre: no se detectaron obstaculos frente al dron."
    parts = []
    for o in obstacles:
        dist = (
            f"{o.distance_m:.1f}m"
            if o.distance_m is not None
            else "distancia desconocida"
        )
        parts.append(f"{o.object} {o.sector.lower()} ({o.proximity}, {dist})")
    return "Detecciones: " + "; ".join(parts) + "."
