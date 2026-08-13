"""Modulo de percepcion: detector (YOLO) + traductor pixeles-a-palabras + filtros geometricos/TTC."""
from .canny_gate import CannyGate
from .detector import Detection, CollisionResult, YoloDetector
from .roi_cropper import crop_roi_62
from .translator import (
    Obstacle,
    obstacles_to_dicts,
    summarize_scene,
    translate_detections,
)
from .ttc_estimator import TTCEstimator

__all__ = [
    "CannyGate",
    "Detection",
    "CollisionResult",
    "Obstacle",
    "YoloDetector",
    "crop_roi_62",
    "obstacles_to_dicts",
    "summarize_scene",
    "translate_detections",
    "TTCEstimator",
]

