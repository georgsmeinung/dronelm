# Construccion de sub-metas del VLM en coordenadas del mundo (2026-10-01).
#
# Una sola funcion para la capa estrategica (vlm_strategic.py) y el barrido (deep_scan.py): las dos
# describen una direccion -- rumbo absoluto y elevacion -- y esta funcion la convierte en un punto con
# las mismas reglas de distancia y altura. Antes cada capa tenia las suyas (15 m fijos y la altura del WP
# en el barrido; distancia acotada al WP y cambio de altura por elevacion en la estrategica).
from __future__ import annotations

import math
import os
from typing import Any, Dict

try:
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / "config" / ".env")
except Exception:
    pass

# Distancia horizontal maxima de la sub-meta desde el punto de referencia. Nunca mas lejos que el WP real:
# una sub-meta mas alla del WP lo saltea (piloto v3 seed 99 190842Z: sub-meta a 15 m con el WP a 6 m,
# dentro del edificio).
VLM_SUBGOAL_DIST_M = float(os.getenv("VLM_SUBGOAL_DIST_M", "15.0"))
# Si la sub-meta quedo a menos de esto del dron al aplicarla, ya no aporta.
VLM_SUBGOAL_MIN_AHEAD_M = float(os.getenv("VLM_SUBGOAL_MIN_AHEAD_M", "4.0"))
# Cambio maximo de altitud de una sub-meta respecto del punto de referencia.
VLM_MAX_DZ_M = float(os.getenv("VLM_MAX_DZ_M", "4.0"))
# Altitud minima de una sub-meta (por encima del piso optico).
VLM_SUBGOAL_MIN_ALT_M = float(os.getenv("VLM_SUBGOAL_MIN_ALT_M", "6.0"))


def subgoal_distance(wp_dist_xy: float) -> float:
    """Distancia horizontal de la sub-meta: VLM_SUBGOAL_DIST_M como maximo, nunca mas que el WP real."""
    return max(VLM_SUBGOAL_MIN_AHEAD_M + 1.0, min(VLM_SUBGOAL_DIST_M, float(wp_dist_xy)))


def build_subgoal(x: float, y: float, z: float, heading_deg: float, elevation_deg: float,
                  wp_dist_xy: float, label: str) -> Dict[str, Any]:
    """Sub-meta desde (x, y, z) en la direccion (rumbo absoluto, elevacion) dada.

    Distancia horizontal d = subgoal_distance(wp_dist_xy); cambio de altitud d*tan(elevacion), acotado a
    +-VLM_MAX_DZ_M y sin bajar de VLM_SUBGOAL_MIN_ALT_M. Elevacion 0: misma altitud que la referencia.
    NED: z negativo es arriba."""
    d = subgoal_distance(wp_dist_xy)
    rad = math.radians(heading_deg)
    dz_up = max(-VLM_MAX_DZ_M, min(VLM_MAX_DZ_M, d * math.tan(math.radians(elevation_deg))))
    return {
        "x": round(float(x) + d * math.cos(rad), 2),
        "y": round(float(y) + d * math.sin(rad), 2),
        "z": round(min(float(z) - dz_up, -VLM_SUBGOAL_MIN_ALT_M), 2),
        "label": label,
        "dist_m": round(d, 2),
    }
