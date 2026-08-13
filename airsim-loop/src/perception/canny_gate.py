from __future__ import annotations

import os
from typing import Optional, Tuple
import cv2
import numpy as np

CANNY_LOW = int(os.getenv("CANNY_LOW", "50"))
CANNY_HIGH = int(os.getenv("CANNY_HIGH", "150"))
DEFAULT_XOR_THRESHOLD = float(os.getenv("CANNY_XOR_THRESHOLD", "0.02"))


class CannyGate:
    """Filtro de bordes XOR (Canny) para pre-filtrado ultra rápido."""

    def __init__(self, xor_threshold: float = DEFAULT_XOR_THRESHOLD) -> None:
        self.xor_threshold = xor_threshold
        self.prev_edges: Optional[np.ndarray] = None

    def evaluate(self, frame: np.ndarray) -> Tuple[float, np.ndarray, bool]:
        """Evalúa el cambio de bordes en relación al fotograma anterior.

        Returns:
            Tuple[float, np.ndarray, bool]:
                - change_ratio: proporción de píxeles que cambiaron.
                - current_edges: mapa de bordes Canny del frame actual.
                - has_significant_change: True si supera el umbral.
        """
        if frame is None or frame.size == 0:
            return 1.0, np.array([]), True

        # Escala de grises
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Extracción de bordes
        edges = cv2.Canny(gray, CANNY_LOW, CANNY_HIGH)

        if self.prev_edges is None or self.prev_edges.shape != edges.shape:
            self.prev_edges = edges
            return 1.0, edges, True

        # Operación XOR binaria entre fotograma actual y anterior
        xor_result = cv2.bitwise_xor(self.prev_edges, edges)
        total_pixels = edges.shape[0] * edges.shape[1]
        changed_pixels = np.count_nonzero(xor_result)
        change_ratio = float(changed_pixels / total_pixels)

        # Actualizar estado para el siguiente frame
        self.prev_edges = edges

        has_significant_change = change_ratio >= self.xor_threshold
        return change_ratio, edges, has_significant_change
