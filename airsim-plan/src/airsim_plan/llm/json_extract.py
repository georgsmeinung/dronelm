"""Helpers para forzar la salida del SLM a un JSON bien formado.

Los modelos de lenguaje locales chicos (en especial Llama-3-8B servido por
LM Studio) suelen envolver el JSON en fences ``` o agregar un preámbulo
corto. Estos helpers prueban un par de estrategias de extracción robustas
antes de darse por vencidos.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional


# Lo ideal sería un regex *balanceado*, pero el ``re`` de Python no soporta
# patrones recursivos. El truco que usamos acá es greedy-con-solapamiento:
# buscar cada llave de apertura y escanear hacia adelante, contando llaves
# anidadas, hasta encontrar un substring balanceado que ``json.loads``
# acepte. Barato y suficientemente bueno para salidas de modelo de pocos KB.
_OPEN_BRACE = re.compile(r"\{")
_CLOSE_BRACE = re.compile(r"\}")


def _balanced_objects(text: str) -> List[str]:
    """Genera substrings candidatos a objeto JSON siguiendo la profundidad de llaves."""
    out: List[str] = []
    depth = 0
    start: Optional[int] = None
    for idx, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    out.append(text[start : idx + 1])
                    start = None
    return out


def _strip_code_fence(text: str) -> str:
    """Saca un fence ```json ...``` inicial si está presente."""
    fence = re.match(r"\s*```(?:json|JSON)?\s*([\s\S]*?)```\s*$", text.strip())
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _first_parsable_object(text: str) -> Optional[str]:
    """Devuelve el primer substring balanceado que ``json.loads`` acepta."""
    for candidate in _balanced_objects(text):
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return None


def extract_json_object(text: str) -> Optional[dict]:
    """Extracción best-effort de un objeto JSON a partir de la salida cruda del modelo."""
    if not text:
        return None
    cleaned = _strip_code_fence(text)
    candidate = _first_parsable_object(cleaned)
    if candidate is None:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# Huella estructural mínima de nuestro Manifest.
_MANIFEST_KEYS = {"mission_id", "waypoints"}


def looks_like_manifest(payload: Any) -> bool:
    """Devuelve ``True`` cuando ``payload`` tiene la forma de nivel superior de un manifest."""
    if not isinstance(payload, dict):
        return False
    return _MANIFEST_KEYS.issubset(payload.keys())
