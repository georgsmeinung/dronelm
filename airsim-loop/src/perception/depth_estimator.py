# Profundidad monocular ESTIMADA desde el RGB de la camara (2026-10-08).
#
# Una red chica (Depth Anything V2 Metric Outdoor Small, ~25 M parametros, metros) estima la profundidad
# a partir del mismo fotograma que ve el resto del grafo. No es el sensor de profundidad de AirSim, que
# sigue fuera del lazo (tests/test_no_depth_in_flight_path.py): equivale a una red a bordo de un dron
# sin sensor de profundidad. Decision del autor (2026-10-08) con la evidencia del banco v2
# (experiments/vlm_bench/seg_depth_probe.py): p5 estimado por sector contra la etiqueta, AUC 0.83 y
# exactitud balanceada 75 %; el VLM con la misma pregunta, AUC 0.53.
#
# El estadistico por sector es el mismo que el de la etiqueta del banco (labels.cell_stats): percentil 5
# de la profundidad en cada tercio del recorte cuadrado central -- lo mas cercano, sin pixeles sueltos.
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import numpy as np

DEPTH_MODEL = os.getenv("DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf")
# Un sector esta libre si su p5 estimado es >= DEPTH_FREE_M: la misma distancia que la sub-meta.
DEPTH_FREE_M = float(os.getenv("DEPTH_FREE_M", os.getenv("VLM_SUBGOAL_DIST_M", "15.0")))

GRID_COLS = "ABC"
GRID_ROWS = "123"
CELLS = [c + r for r in GRID_ROWS for c in GRID_COLS]


def sector_p5(depth: np.ndarray) -> Dict[str, float]:
    """p5 de la profundidad en cada sector de la grilla 3x3 del recorte cuadrado central (m)."""
    h, w = depth.shape[:2]
    s = min(h, w)
    x0, y0 = (w - s) // 2, (h - s) // 2
    sq = depth[y0:y0 + s, x0:x0 + s]
    out: Dict[str, float] = {}
    for ri, r in enumerate(GRID_ROWS):
        for ci, c in enumerate(GRID_COLS):
            cell = sq[ri * s // 3:(ri + 1) * s // 3, ci * s // 3:(ci + 1) * s // 3]
            cell = cell[np.isfinite(cell)]
            out[c + r] = round(float(np.percentile(cell, 5)), 2) if cell.size else float("nan")
    return out


class DepthEstimator:
    """Envoltorio de la red; carga perezosa (la primera llamada tarda unos segundos)."""

    def __init__(self, model_name: str = DEPTH_MODEL, device: Optional[str] = None) -> None:
        self.model_name = model_name
        self.device = device
        self._proc: Any = None
        self._model: Any = None

    def _load(self) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        self.device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._proc = AutoImageProcessor.from_pretrained(self.model_name)
        self._model = AutoModelForDepthEstimation.from_pretrained(self.model_name).to(self.device).eval()

    def estimate(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Profundidad (m) del tamano del fotograma. `frame_bgr`: convencion OpenCV, como rgb_image."""
        import torch

        if self._model is None:
            self._load()
        h, w = frame_bgr.shape[:2]
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        with torch.no_grad():
            inp = self._proc(images=rgb, return_tensors="pt").to(self.device)
            pred = self._model(**inp).predicted_depth
            pred = torch.nn.functional.interpolate(pred.unsqueeze(1), size=(h, w), mode="bilinear",
                                                   align_corners=False)
        return pred.squeeze().float().cpu().numpy()

    def sectors(self, frame_bgr: np.ndarray) -> Dict[str, Any]:
        t0 = time.time()
        p5 = sector_p5(self.estimate(frame_bgr))
        return {"p5": p5, "latency_ms": (time.time() - t0) * 1000.0}
