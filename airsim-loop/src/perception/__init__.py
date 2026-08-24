"""Modulo de percepcion: gating de bordes, flujo optico + TTC, contrato de escena."""
from .canny_gate import CannyGate
from .flow_ttc import FlowTTCEstimator
from .obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field

__all__ = [
    "CannyGate",
    "FlowTTCEstimator",
    "ObstacleField",
    "Cell",
    "SECTORS",
    "BANDS",
    "empty_field",
]
