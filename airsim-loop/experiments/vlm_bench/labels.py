"""Verdad de terreno a partir de la profundidad planar de la camara frontal (funciones puras).

Todas las etiquetas usan la misma geometria que ve el VLM en vuelo: el recorte cuadrado central del
frame y su grilla de 3x3 por tercios (vlm_strategic.square_crop). "Libre" = el percentil 5 de la
profundidad del sector (lo mas cercano, sin los pixeles sueltos) esta a FREE_M o mas: la misma distancia
de 15 m que se le pide juzgar al modelo y que usa la sub-meta.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import numpy as np

FREE_M = float(os.getenv("BENCH_FREE_M", os.getenv("VLM_SUBGOAL_DIST_M", "15.0")))
INSIDE_M = float(os.getenv("BENCH_INSIDE_M", "1.0"))       # camara dentro de la geometria
GAP_STRIPS = 27                                           # franjas verticales del frame completo
GRID_COLS, GRID_ROWS = "ABC", "123"
CELLS = [c + r for r in GRID_ROWS for c in GRID_COLS]


def _p(a: np.ndarray, q: float) -> float:
    a = a[np.isfinite(a)]
    return float(np.percentile(a, q)) if a.size else float("nan")


def square(depth: np.ndarray) -> np.ndarray:
    h, w = depth.shape[:2]
    s = min(h, w)
    x0, y0 = (w - s) // 2, (h - s) // 2
    return depth[y0:y0 + s, x0:x0 + s]


def cell_stats(depth: np.ndarray, free_m: float = FREE_M) -> Dict[str, Dict[str, float]]:
    sq = square(depth)
    s = sq.shape[0]
    out: Dict[str, Dict[str, float]] = {}
    for ri, r in enumerate(GRID_ROWS):
        for ci, c in enumerate(GRID_COLS):
            cell = sq[ri * s // 3:(ri + 1) * s // 3, ci * s // 3:(ci + 1) * s // 3]
            out[c + r] = {"p5": round(_p(cell, 5), 2), "p50": round(_p(cell, 50), 2),
                          "free_frac": round(float(np.mean(cell >= free_m)), 3)}
    return out


def strip_p5(depth: np.ndarray, n: int = GAP_STRIPS) -> List[float]:
    """p5 de profundidad de n franjas verticales del tercio medio (altura del dron) del frame COMPLETO."""
    h, w = depth.shape[:2]
    band = depth[h // 3:2 * h // 3]
    return [round(_p(band[:, i * w // n:(i + 1) * w // n], 5), 2) for i in range(n)]


def labels_from_depth(depth: np.ndarray, free_m: float = FREE_M) -> Dict[str, Any]:
    cells = cell_stats(depth, free_m)
    free = {c: bool(cells[c]["p5"] >= free_m) for c in CELLS}
    h, w = depth.shape[:2]
    center_p50 = cells["B2"]["p50"]
    inside = bool(np.isfinite(center_p50) and center_p50 < INSIDE_M)

    strips = strip_p5(depth)
    n = len(strips)
    mid = (n - 1) / 2.0
    free_idx = [i for i, d in enumerate(strips) if d >= free_m]
    # Por donde rodear el obstaculo de frente: el lado del hueco libre mas cercano al centro.
    if free[("B2")]:
        edge_side: Optional[str] = None
    elif not free_idx:
        edge_side = "ninguno"
    else:
        left = [mid - i for i in free_idx if i < mid]
        right = [i - mid for i in free_idx if i > mid]
        if left and (not right or min(left) < min(right)):
            edge_side = "izquierda"
        elif right and (not left or min(right) < min(left)):
            edge_side = "derecha"
        else:
            edge_side = "izquierda" if len(left) >= len(right) else "derecha"

    # Si hay obstaculo de frente: se ve espacio libre por encima de el (sector B1 mayormente libre)?
    top_clear = None if free["B2"] else ("si" if cells["B1"]["free_frac"] >= 0.5 else "no")

    # Direccion mas abierta a la altura del dron: tercio (del frame completo) con mayor mediana.
    band = depth[h // 3:2 * h // 3]
    thirds = {"izquierda": _p(band[:, :w // 3], 50), "centro": _p(band[:, w // 3:2 * w // 3], 50),
              "derecha": _p(band[:, 2 * w // 3:], 50)}
    best = max(thirds, key=lambda k: thirds[k] if np.isfinite(thirds[k]) else -1)
    open_dir = best if thirds[best] >= free_m else "ninguna"

    return {
        "free_m": free_m, "cells": cells, "cell_free": free, "center_free": "si" if free["B2"] else "no",
        "edge_side": edge_side, "top_clear": top_clear, "open_dir": open_dir,
        "thirds_p50": {k: round(v, 2) for k, v in thirds.items()}, "strips_p5": strips,
        "inside": inside, "min_p5": round(min(c["p5"] for c in cells.values()), 2),
    }


def pool_min(depth: np.ndarray, k: int = 4) -> np.ndarray:
    """Reduccion por minimo en bloques de k x k (conservadora: no borra obstaculos finos)."""
    h, w = depth.shape[:2]
    h2, w2 = h // k * k, w // k * k
    return depth[:h2, :w2].reshape(h2 // k, k, w2 // k, k).min(axis=(1, 3))
