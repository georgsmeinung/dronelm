# Paso 2: Traduccion Pixeles-a-Palabras.
# Convierte las cajas delimitadoras de YOLO en conceptos textuales
# estructurados (tipo de objeto, sector del encuadre y proximidad).
from __future__ import annotations

import math
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

# Tipos de obstaculos clasificados por jerarquia de riesgo en navegacion urbana
STRUCTURAL_CLASSES = {"building", "wall", "house", "roof", "tower", "bridge", "structure"}
ELEVATED_CLASSES = {"pole", "tree", "vegetation", "fence", "traffic light", "traffic sign"}
GROUND_CLASSES = {"person", "bicycle", "motorcycle", "car", "truck", "bus", "train", "animal"}
CRITICAL_CLASSES = STRUCTURAL_CLASSES | ELEVATED_CLASSES | GROUND_CLASSES


@dataclass
class Obstacle:
    """Obstaculo textual listo para alimentar al Gatekeeper / al LLM."""

    object: str
    sector: str  # "Izquierda" | "Centro" | "Derecha"
    proximity: str  # "Inminente" | "Cerca" | "Lejos"
    distance_m: Optional[float]
    confidence: float
    category: str = "general"  # "structural" | "elevated" | "ground" | "general"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get_obstacle_category(obj_name: str) -> str:
    obj_lower = str(obj_name).lower().strip()
    if obj_lower in STRUCTURAL_CLASSES:
        return "structural"
    if obj_lower in ELEVATED_CLASSES:
        return "elevated"
    if obj_lower in GROUND_CLASSES:
        return "ground"
    return "general"


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


# Escala de tamaño físico nominal relativo por clase para estimación monocular
CLASS_DISTANCE_SCALE = {
    "building": 1.4,
    "wall": 1.3,
    "house": 1.4,
    "fence": 1.0,
    "vegetation": 1.1,
    "tree": 1.1,
    "truck": 1.1,
    "bus": 1.1,
    "train": 1.2,
    "car": 1.0,
    "person": 0.8,
    "pole": 0.9,
    "traffic light": 0.8,
    "traffic sign": 0.8,
}


def _estimate_distance(
    detection: Detection,
    frame_width: int,
    frame_height: int,
    threshold_m: float,
) -> Optional[float]:
    """Heuristica monocular pura basada en ocupacion de area 2D, ancho relativo y tipo de clase."""
    if frame_height <= 0 or frame_width <= 0:
        return None
    if detection.bbox is None or len(detection.bbox) != 4:
        return None
    x_min, y_min, x_max, y_max = detection.bbox
    box_w = max(1.0, float(x_max - x_min))
    box_h = max(1.0, float(y_max - y_min))

    area_ratio = min(1.0, (box_w * box_h) / float(frame_width * frame_height))
    width_ratio = min(1.0, box_w / float(frame_width))
    height_ratio = min(1.0, box_h / float(frame_height))

    if area_ratio <= 0.0:
        return None

    obj_type = str(detection.object).lower()
    category = _get_obstacle_category(obj_type)

    # 1. ESTRUCTURAS MASIVAS (Edificios, Muros, Casas, Puentes)
    # Discriminación geométrica: distingue paredes frontales de edificios lejanos y fachadas laterales
    if category == "structural":
        bottom_contact = min(1.0, max(0.0, float(y_max) / float(frame_height)))
        effective_occupancy = area_ratio * (0.7 + 0.6 * bottom_contact)

        # Si el área es masiva y cubre predominantemente el campo central (pared/fachada bloqueante real)
        if area_ratio >= 0.55 and effective_occupancy >= 0.50:
            # Bloqueo frontal o proximidad inminente (<= 2.5m)
            return float(NEAR_THRESHOLD * 0.75)  # ~2.2m
        elif area_ratio >= 0.20 and effective_occupancy >= 0.20:
            # Proximidad media y maniobra de rodeo / fachada lateral (3.5m - 8.0m)
            t = (effective_occupancy - 0.20) / (0.50 - 0.20)
            dist = FAR_THRESHOLD - t * (FAR_THRESHOLD - (NEAR_THRESHOLD + 0.5))
            return float(dist)
        else:
            # Skyline, edificio de fondo o estructura lejana (> 8.0m)
            dist = (threshold_m * 2.0 * CLASS_DISTANCE_SCALE.get(obj_type, 1.3)) / max(0.05, math.sqrt(max(area_ratio, 0.05)))
            return float(max(FAR_THRESHOLD + 1.0, dist))

    # 2. OBSTÁCULOS ELEVADOS (Postes, Árboles, Vallas, Semáforos)
    if category == "elevated":
        visual_occupancy = max(area_ratio * 1.5, height_ratio)
        if visual_occupancy >= 0.70:
            return float(NEAR_THRESHOLD * 0.8)  # ~2.4m -> Inminente
        elif visual_occupancy >= 0.25:
            t = (visual_occupancy - 0.25) / (0.70 - 0.25)
            dist = FAR_THRESHOLD - t * (FAR_THRESHOLD - NEAR_THRESHOLD)
            return float(dist)  # -> Cerca (3.0m - 8.0m)
        else:
            dist = (threshold_m * 0.60 * CLASS_DISTANCE_SCALE.get(obj_type, 1.0)) / max(0.05, visual_occupancy)
            return float(max(FAR_THRESHOLD + 0.5, dist))

    # 3. OBJETOS DE SUELO / VEHÍCULOS (Autos, Peatones, Camiones)
    visual_occupancy = max(area_ratio, height_ratio)
    if visual_occupancy >= 0.50:
        return float(NEAR_THRESHOLD * 0.8)  # -> Inminente
    elif visual_occupancy >= 0.15:
        t = (visual_occupancy - 0.15) / (0.50 - 0.15)
        dist = FAR_THRESHOLD - t * (FAR_THRESHOLD - NEAR_THRESHOLD)
        return float(dist)  # -> Cerca (3.0m - 8.0m)
    else:
        dist = (threshold_m * 0.45 * CLASS_DISTANCE_SCALE.get(obj_type, 1.0)) / max(0.05, visual_occupancy)
        return float(max(FAR_THRESHOLD + 0.5, dist))


def translate_detections(
    detections: List[Detection],
    frame_width: int = DEFAULT_FRAME_WIDTH,
    frame_height: int = DEFAULT_FRAME_HEIGHT,
    proximity_threshold_m: Optional[float] = None,
) -> List[Obstacle]:
    """Convierte detecciones YOLO en obstaculos textuales estructurados y priorizados."""
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
        distance = _estimate_distance(det, frame_width, frame_height, threshold)
        proximity = _classify_proximity(distance)
        category = _get_obstacle_category(str(det.object))
        obstacles.append(
            Obstacle(
                object=str(det.object),
                sector=sector,
                proximity=proximity,
                distance_m=distance,
                confidence=float(det.confidence),
                category=category,
            )
        )

    # Orden de criticidad: Estructurales > Inminente/Cerca > Centro
    cat_weight = {"structural": 0, "elevated": 1, "ground": 2, "general": 3}
    prox_weight = {"Inminente": 0, "Cerca": 1, "Lejos": 2, "Desconocida": 3}
    sector_weight = {"Centro": 0, "Izquierda": 1, "Derecha": 1}

    obstacles.sort(
        key=lambda o: (
            cat_weight.get(o.category, 3),
            prox_weight.get(o.proximity, 3),
            sector_weight.get(o.sector, 2),
            float(o.distance_m if o.distance_m is not None else 999.0),
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
