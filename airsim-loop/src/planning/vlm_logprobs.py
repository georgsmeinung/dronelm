"""Probabilidad de cada opcion de un enum, leida de los logprobs del VLM (funciones puras).

Con decodificacion restringida (json_schema), `top_logprobs` es la distribucion del modelo ANTES de la
gramatica (p. ej. 'S', 's', 'Si', 'No', 'no' para un enum si/no). Se toma el token que cubre el primer
caracter del valor y se asigna cada alternativa a la opcion cuyo nombre empieza con lo que esa alternativa
escribe desde ahi (sin distinguir mayusculas). Las opciones deben tener iniciales distintas.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _tok_text(t: Any) -> str:
    return t["token"] if isinstance(t, dict) else t.token


def _tok_top(t: Any) -> List[Tuple[str, float]]:
    top = t.get("top_logprobs") if isinstance(t, dict) else getattr(t, "top_logprobs", None)
    return [(a["token"], a["logprob"]) if isinstance(a, dict) else (a.token, a.logprob) for a in (top or [])]


def choice_probs_at(tokens: Sequence[Any], offset: int, choices: Sequence[str]) -> Optional[Dict[str, float]]:
    """Probabilidad normalizada de cada opcion en la posicion `offset` del texto. None si no hay masa."""
    pos = 0
    for tok in tokens:
        text = _tok_text(tok)
        start, end = pos, pos + len(text)
        pos = end
        if end <= offset:
            continue
        cut = offset - start
        if cut < 0:
            return None
        mass = {c: 0.0 for c in choices}
        for alt, lp in _tok_top(tok):
            frag = alt[cut:].lstrip('"').strip().lower() if len(alt) > cut else ""
            if not frag:
                continue
            for c in choices:
                cl = c.lower()
                if cl.startswith(frag) or frag.startswith(cl):
                    mass[c] += math.exp(lp)
                    break
        total = sum(mass.values())
        return {c: m / total for c, m in mass.items()} if total > 0 else None
    return None


def value_offsets(text: str, key: str, quoted: bool = True) -> List[int]:
    """Offsets del primer caracter de cada valor de `key` en el JSON generado (string, o literal con
    quoted=False)."""
    pat = r'"%s"\s*:\s*"' if quoted else r'"%s"\s*:\s*'
    return [m.end() for m in re.finditer(pat % re.escape(key), text)]


def tokens_to_dicts(logprobs_content: Any) -> List[Dict[str, Any]]:
    """choices[0].logprobs.content del SDK de OpenAI -> lista de dicts serializable."""
    return [{"token": t.token, "logprob": t.logprob,
             "top_logprobs": [{"token": a.token, "logprob": a.logprob} for a in (t.top_logprobs or [])]}
            for t in (logprobs_content or [])]
