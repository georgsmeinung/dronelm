# Servicio de profundidad estimada con la misma interfaz que el del VLM (2026-10-08).
#
# La capa estrategica (vlm_strategic.StrategicLayer) y el barrido de deadlock (deep_scan.deep_scan_cycle)
# hablan con un servicio asincronico: request(payload) -> id, get_result(id), poll(). Este modulo arma ese
# mismo servicio (DeliberationService, un hilo propio) con una funcion de consulta que corre la red de
# profundidad en vez del VLM, y devuelve las MISMAS estructuras que el VLM:
#   - modo "strategic": {"sectores": {celda: "libre"|"bloqueado"}} -> vlm_strategic.decide_subgoal
#   - modo "deep_scan": {"views": [{"img", "view", "free"}]}         -> deep_scan.panorama_to_subgoal
# Asi la traduccion a sub-metas en marco mundo, anclada a la pose del fotograma, no cambia.
#
# La red corre en el hilo del servicio, nunca en el lazo (~80 ms por fotograma con la GPU compartida;
# el periodo del lazo es ~0.2 s). Los pedidos llevan el fotograma crudo ("frames"), no JPEG en base64.
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple

from .deliberation_service import DeliberationService
from src.perception.depth_estimator import CELLS, DEPTH_FREE_M, DepthEstimator

# Sector del fotograma que decide si un rumbo del barrido es transitable: el centro (B2), hacia donde
# volaria el dron en linea recta. Es la etiqueta `center_free` del banco.
SCAN_SECTOR = "B2"


def depth_to_decision(payload: Dict[str, Any], p5_by_frame: list) -> Dict[str, Any]:
    """Respuesta con la forma de la del VLM a partir del p5 estimado por sector de cada fotograma."""
    if payload.get("mode") == "deep_scan":
        return {"views": [{"img": i + 1, "view": "open" if p5[SCAN_SECTOR] >= DEPTH_FREE_M else "wall",
                           "free": bool(p5[SCAN_SECTOR] >= DEPTH_FREE_M)} for i, p5 in enumerate(p5_by_frame)]}
    p5 = p5_by_frame[0]
    return {"sectores": {c: ("libre" if p5[c] >= DEPTH_FREE_M else "bloqueado") for c in CELLS}}


def make_depth_query(estimator: Any):
    """query_fn para DeliberationService: (parsed, raw, latency_ms, error)."""

    def _query(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]:
        t0 = time.time()
        frames = [f for f in (payload.get("frames") or []) if f is not None]
        if not frames:
            return None, "", 0.0, "sin_fotograma"
        try:
            p5s = [estimator.sectors(f)["p5"] for f in frames]
        except Exception as exc:  # la red fallo: el llamador cae a su camino de falla (como un timeout)
            return None, "", (time.time() - t0) * 1000.0, f"profundidad: {exc}"
        raw = json.dumps({"p5_m": p5s})
        return depth_to_decision(payload, p5s), raw, (time.time() - t0) * 1000.0, None

    return _query


def make_depth_service(estimator: Any = None, warmup: bool = True) -> DeliberationService:
    """Servicio de profundidad. `warmup` carga la red en su hilo al crear el servicio (unos segundos),
    para que la primera consulta en vuelo no pague la carga."""
    est = estimator or DepthEstimator()
    svc = DeliberationService(query_fn=make_depth_query(est))
    svc.kind = "depth"  # type: ignore[attr-defined]  deep_scan arma pedidos con fotogramas crudos
    if warmup:
        import numpy as np

        svc.request({"mode": "strategic", "frames": [np.zeros((72, 108, 3), dtype=np.uint8)]})
    return svc
