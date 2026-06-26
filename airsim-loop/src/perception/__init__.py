"""Modulo de percepcion: detector (YOLO) + traductor pixeles-a-palabras."""
from .detector import Detection, YoloDetector
from .translator import (
    Obstacle,
    obstacles_to_dicts,
    summarize_scene,
    translate_detections,
)

__all__ = [
    "Detection",
    "Obstacle",
    "YoloDetector",
    "obstacles_to_dicts",
    "summarize_scene",
    "translate_detections",
]
