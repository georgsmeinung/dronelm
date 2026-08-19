from __future__ import annotations

import math
import os
import time
from typing import Dict, List, Optional, Tuple, Any
from .detector import Detection

EMA_ALPHA = float(os.getenv("TTC_EMA_ALPHA", "0.4"))


def _compute_iou(bbox1: List[float], bbox2: List[float]) -> float:
    """Calcula la intersección sobre unión (IoU) entre dos bounding boxes."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h

    area1 = max(1.0, (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1]))
    area2 = max(1.0, (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1]))
    union_area = area1 + area2 - inter_area
    if union_area <= 0.0:
        return 0.0
    return float(inter_area / union_area)


class TTCEstimator:
    """Estimador de Tiempo de Colisión (TTC) no neuronal basado en la tasa de expansión de BB-w."""

    def __init__(self) -> None:
        self.prev_tracks: List[Dict[str, Any]] = []
        self.prev_timestamp: Optional[float] = None
        self.ema_ttc: Optional[float] = None

    def estimate(
        self, detections: List[Detection], timestamp: Optional[float] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """Calcula el Tiempo de Colisión (TTC) mínimo entre las detecciones asociadas temporalmente.

        Returns:
            Tuple[float, Dict[str, Any]]:
                - min_ttc: tiempo estimado a la colisión en segundos (inf si no hay riesgo).
                - details: diccionario con métricas del cálculo.
        """
        now = timestamp if timestamp is not None else time.time()

        if not detections:
            self.prev_tracks.clear()
            self.prev_timestamp = now
            return float("inf"), {"detections_count": 0, "min_ttc": float("inf")}

        if self.prev_timestamp is None:
            dt = 0.1
        else:
            dt = max(0.001, now - self.prev_timestamp)

        min_ttc = float("inf")
        current_tracks: List[Dict[str, Any]] = []
        details_list = []
        used_prev_indices = set()

        for det in detections:
            if not det.bbox or len(det.bbox) != 4:
                continue

            x_min, y_min, x_max, y_max = det.bbox
            bb_w = max(1.0, float(x_max - x_min))
            cx = (x_min + x_max) / 2.0
            cy = (y_min + y_max) / 2.0

            cur_track = {
                "object": str(det.object),
                "bbox": [float(v) for v in det.bbox],
                "bb_w": bb_w,
                "cx": cx,
                "cy": cy,
            }
            current_tracks.append(cur_track)

            # Asociación con las cajas del fotograma anterior
            best_prev_idx = -1
            best_score = -1.0

            for p_idx, prev in enumerate(self.prev_tracks):
                if p_idx in used_prev_indices:
                    continue
                if prev["object"] != det.object:
                    continue

                iou = _compute_iou(det.bbox, prev["bbox"])
                dist_c = math.hypot(cx - prev["cx"], cy - prev["cy"])

                # Puntuación combinada (preferir alto IoU o cercanía espacial)
                if iou > 0.05:
                    score = 100.0 + iou
                elif dist_c < 250.0:
                    score = max(0.0, 50.0 - dist_c * 0.2)
                else:
                    score = -1.0

                if score > best_score:
                    best_score = score
                    best_prev_idx = p_idx

            if best_prev_idx >= 0:
                used_prev_indices.add(best_prev_idx)
                prev_match = self.prev_tracks[best_prev_idx]
                prev_w = prev_match["bb_w"]
                delta_w = bb_w - prev_w

                if delta_w > 0.5:
                    rate_w = delta_w / dt
                    # Fórmula de aproximación lineal del TTC basándose en expansión de BB-w
                    ttc = (2.0 * bb_w) / rate_w
                    if ttc < min_ttc:
                        min_ttc = ttc
                    details_list.append(
                        {
                            "object": det.object,
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

        self.prev_tracks = current_tracks
        self.prev_timestamp = now

        return final_ttc, {
            "min_ttc": final_ttc,
            "raw_min_ttc": min_ttc,
            "details": details_list,
        }
