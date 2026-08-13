from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple, Any
from .detector import Detection

EMA_ALPHA = float(os.getenv("TTC_EMA_ALPHA", "0.4"))


class TTCEstimator:
    """Estimador de Tiempo de Colisión (TTC) no neuronal basado en la tasa de expansión de BB-w."""

    def __init__(self) -> None:
        self.prev_bb_widths: Dict[str, float] = {}
        self.prev_timestamp: Optional[float] = None
        self.ema_ttc: Optional[float] = None

    def estimate(
        self, detections: List[Detection], timestamp: Optional[float] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """Calcula el Tiempo de Colisión (TTC) mínimo entre las detecciones dentro del ROI.

        Returns:
            Tuple[float, Dict[str, Any]]:
                - min_ttc: tiempo estimado a la colisión en segundos (inf si no hay riesgo).
                - details: diccionario con métricas del cálculo.
        """
        now = timestamp if timestamp is not None else time.time()

        if not detections:
            self.prev_bb_widths.clear()
            self.prev_timestamp = now
            return float("inf"), {"detections_count": 0, "min_ttc": float("inf")}

        if self.prev_timestamp is None:
            dt = 0.1
        else:
            dt = max(0.001, now - self.prev_timestamp)

        min_ttc = float("inf")
        current_bb_widths: Dict[str, float] = {}
        details_list = []

        for i, det in enumerate(detections):
            if not det.bbox or len(det.bbox) != 4:
                continue

            x_min, y_min, x_max, y_max = det.bbox
            bb_w = max(1.0, float(x_max - x_min))
            # Identificador heurístico básico por objeto y posición aproximada
            cx = (x_min + x_max) / 2.0
            det_key = f"{det.object}_{int(cx / 50)}"
            current_bb_widths[det_key] = bb_w

            if det_key in self.prev_bb_widths:
                prev_w = self.prev_bb_widths[det_key]
                delta_w = bb_w - prev_w

                if delta_w > 0:
                    # Velocidad de expansión temporal (píxeles por segundo)
                    rate_w = delta_w / dt
                    # Fórmula de aproximación lineal del TTC basándose en expansión de BB-w
                    ttc = (2.0 * bb_w) / rate_w
                    if ttc < min_ttc:
                        min_ttc = ttc
                    details_list.append(
                        {
                            "key": det_key,
                            "bb_w": bb_w,
                            "delta_w": delta_w,
                            "rate_w": rate_w,
                            "ttc": ttc,
                        }
                    )

        # Suavizado EMA del TTC si existe un valor válido
        if min_ttc != float("inf"):
            if self.ema_ttc is None or self.ema_ttc == float("inf"):
                self.ema_ttc = min_ttc
            else:
                self.ema_ttc = EMA_ALPHA * min_ttc + (1 - EMA_ALPHA) * self.ema_ttc
            final_ttc = float(self.ema_ttc)
        else:
            self.ema_ttc = float("inf")
            final_ttc = float("inf")

        self.prev_bb_widths = current_bb_widths
        self.prev_timestamp = now

        return final_ttc, {
            "min_ttc": final_ttc,
            "raw_min_ttc": min_ttc,
            "details": details_list,
        }
