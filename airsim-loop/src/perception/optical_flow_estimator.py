from __future__ import annotations

import os
import cv2
import numpy as np
import math
from typing import Any, Tuple, Optional

class OpticalFlowEstimator:
    """Estimador de flujo óptico basado en Farnebäck.

    - `estimate(current_frame, prev_frame)` devuelve:
        * `estimated_ttc` (float) usando divergencia media del flujo en ROI central.
        * `flow_map` (np.ndarray) de forma (H, W, 2) con los vectores de desplazamiento.
    """

    def __init__(self, win_size: int = int(os.getenv("OPTICAL_FLOW_WINSIZE", "15")),
                 levels: int = int(os.getenv("OPTICAL_FLOW_LEVELS", "3")),
                 iterations: int = int(os.getenv("OPTICAL_FLOW_ITERATIONS", "3"))):
        self.win_size = win_size
        self.levels = levels
        self.iterations = iterations

    def _calc_foe(self, flow: np.ndarray) -> Tuple[float, float]:
        """Calcula una estimación aproximada del FOE como el promedio ponderado
        de los vectores en la zona central del flujo.
        """
        h, w, _ = flow.shape
        cx, cy = w // 2, h // 2
        roi_sz = int(min(w, h) * 0.4)  # 40% del frame central
        x0, y0 = cx - roi_sz // 2, cy - roi_sz // 2
        # Simplificación: devolvemos el centro del ROI como FOE.
        return float(cx), float(cy)

    def estimate(self, current_frame: Any, prev_frame: Optional[Any]) -> Tuple[float, np.ndarray]:
        """Calcula TTC basado en la divergencia del flujo óptico.
        Si no hay `prev_frame` disponible, devuelve TTC infinita.
        """
        if prev_frame is None:
            h, w = current_frame.shape[:2]
            empty_flow = np.zeros((h, w, 2), dtype=np.float32)
            return float('inf'), empty_flow

        # Convertir a gris
        gray_prev = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY) if len(prev_frame.shape) == 3 else prev_frame
        gray_cur = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY) if len(current_frame.shape) == 3 else current_frame

        flow = cv2.calcOpticalFlowFarneback(
            gray_prev, gray_cur,
            None,
            pyr_scale=0.5,
            levels=self.levels,
            winsize=self.win_size,
            iterations=self.iterations,
            poly_n=5,
            poly_sigma=1.2,
            flags=0,
        )
        # Magnitud del flujo
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        h, w = mag.shape
        # ROI central para medir divergencia
        cx, cy = w // 2, h // 2
        roi_sz = int(min(w, h) * 0.4)
        x0, y0 = cx - roi_sz // 2, cy - roi_sz // 2
        roi_mag = mag[y0:y0 + roi_sz, x0:x0 + roi_sz]
        # Divergencia media (evitando ceros)
        mean_div = np.mean(roi_mag) + 1e-6
        # TTC = 1 / mean divergence (escala arbitraria). Clamp a valores razonables.
        ttc = max(0.1, min(10.0, 1.0 / mean_div))
        return float(ttc), flow
