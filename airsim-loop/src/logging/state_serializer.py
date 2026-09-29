"""Serializacion del DroneState completo para auditoria (2026-0929).

Cada fila de CSV/JSONL incluye el DroneState de ese ciclo (columna
`state_json` / clave `state`), para reconstruir despues que paso en cada
corrida sin depender de que alguien haya previsto la columna. Sirve igual para
los tres brazos (slm / fsm / reactive): no asume claves, recorre lo que haya.

Reglas: imagenes y buffers de frames NO se guardan (solo su forma/cantidad --
los PNG de auditoria ya cubren eso); `deliberations` (crece sin limite) se
resume a cantidad + ultima entrada sin prompts; floats no finitos pasan a
string ("inf", "nan") para que el resultado sea JSON valido y el visor pueda
usar JSON.parse.
"""
from __future__ import annotations

import math
from typing import Any, Dict

_MAX_DEPTH = 6
_MAX_LIST = 40
_MAX_STR = 600
# Claves cuyo contenido es imagen/buffer: se reemplaza por un resumen.
_HEAVY_KEYS = {
    "rgb_image", "prev_image", "frame_history", "frame_history_ts",
    "_scan_frames", "_pending_delib_frames", "_last_delib_frames",
}
# Entradas de deliberacion: estos campos ya viven en slm_prompt/slm_raw_response.
_DELIB_DROP = {"prompt", "system_prompt", "raw_response", "raw"}


def _summarize_heavy(v: Any) -> Any:
    shape = getattr(v, "shape", None)
    if shape is not None:
        return f"<{type(v).__name__} shape={tuple(shape)}>"
    if isinstance(v, (list, tuple)):
        return f"<{len(v)} items>"
    return None if v is None else f"<{type(v).__name__}>"


def _clean(v: Any, depth: int = 0) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        if isinstance(v, str) and len(v) > _MAX_STR:
            return v[:_MAX_STR] + f"...(+{len(v) - _MAX_STR})"
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else ("nan" if math.isnan(v) else ("inf" if v > 0 else "-inf"))
    if depth >= _MAX_DEPTH:
        return f"<{type(v).__name__}>"
    to_dict = getattr(v, "to_dict", None)
    if callable(to_dict):
        try:
            return _clean(to_dict(), depth + 1)
        except Exception:
            pass
    shape = getattr(v, "shape", None)
    if shape is not None:  # ndarray / tensor
        if getattr(v, "size", 1000) <= 16:
            try:
                return _clean(v.tolist(), depth + 1)
            except Exception:
                pass
        return f"<{type(v).__name__} shape={tuple(shape)}>"
    if hasattr(v, "item") and not isinstance(v, (list, tuple, dict)):  # numpy escalar
        try:
            return _clean(v.item(), depth + 1)
        except Exception:
            pass
    if isinstance(v, dict):
        return {str(k): _clean(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        items = list(v)
        out = [_clean(x, depth + 1) for x in items[:_MAX_LIST]]
        if len(items) > _MAX_LIST:
            out.append(f"...(+{len(items) - _MAX_LIST})")
        return out
    return repr(v)[:200]


def serialize_drone_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve una copia JSON-segura del DroneState (sin imagenes)."""
    out: Dict[str, Any] = {}
    for k, v in (state or {}).items():
        if k in _HEAVY_KEYS:
            out[k] = _summarize_heavy(v)
        elif k == "deliberations":
            dl = v or []
            last = dl[-1] if dl else None
            out[k] = {
                "count": len(dl),
                "last": _clean({kk: vv for kk, vv in last.items() if kk not in _DELIB_DROP})
                if isinstance(last, dict) else None,
            }
        elif k == "last_deliberation" and isinstance(v, dict):
            out[k] = _clean({kk: vv for kk, vv in v.items() if kk not in _DELIB_DROP})
        else:
            out[k] = _clean(v)
    return out


# Listas de escalares de hasta este largo se expanden en columnas `path.0`, `path.1`...
_FLAT_LIST_MAX = 6
# Listas de dicts (p. ej. waypoints) de hasta este largo: `path.<i>.<campo>`.
_FLAT_DICTLIST_MAX = 16


def flatten_state(snapshot: Dict[str, Any], prefix: str = "state") -> Dict[str, Any]:
    """Aplana un snapshot (salida de serialize_drone_state) a {`prefix.ruta.a.campo`: escalar}.

    Dicts -> claves con punto; listas cortas de escalares o de dicts -> `.0`, `.1`, ...;
    listas mas largas -> un unico JSON compacto en esa columna (mantiene acotado el
    ancho del CSV). Pensado para analisis en planilla/pandas.
    """
    import json

    out: Dict[str, Any] = {}

    def _walk(v: Any, path: str) -> None:
        if isinstance(v, dict):
            if not v:
                return
            for k, x in v.items():
                _walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            scalars = all(not isinstance(x, (dict, list)) for x in v)
            dicts = all(isinstance(x, dict) for x in v)
            if v and ((scalars and len(v) <= _FLAT_LIST_MAX) or (dicts and len(v) <= _FLAT_DICTLIST_MAX)):
                for i, x in enumerate(v):
                    _walk(x, f"{path}.{i}")
            elif v:
                out[path] = json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)
        else:
            out[path] = v

    for k, v in (snapshot or {}).items():
        _walk(v, f"{prefix}.{k}")
    return out
