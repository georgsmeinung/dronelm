"""Utilidades comunes del banco: consulta al VLM con logprobs y lectura de la probabilidad por opcion."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]          # airsim-loop/
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT.parent / "config" / ".env")
except Exception:  # pragma: no cover
    pass

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "ollama")
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")
BENCH_HTTP_TIMEOUT_S = float(os.getenv("BENCH_HTTP_TIMEOUT_S", "60"))
DEFAULT_BENCH_DIR = ROOT.parent / "airsim-runs" / "vlm_bench"


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not Path(path).exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # linea truncada por un corte (la etapa se reanuda y la vuelve a hacer)
    return out


def append_jsonl(path: Path, rec: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def encode_jpeg(img: Any, max_size: Optional[int] = None, quality: int = 85) -> str:
    import cv2

    if max_size:
        h, w = img.shape[:2]
        if max(h, w) != max_size:
            s = max_size / float(max(h, w))
            img = cv2.resize(img, (int(round(w * s)), int(round(h * s))),
                             interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("no se pudo codificar la imagen")
    return base64.b64encode(buf).decode("utf-8")


# --------------------------------------------------------------------------- logprobs
# La misma lectura que usa el planificador de ruta (src/planning/vlm_logprobs.py).
from src.planning.vlm_logprobs import choice_probs_at, tokens_to_dicts, value_offsets  # noqa: E402,F401


# --------------------------------------------------------------------------- consulta
def query_vlm(system_prompt: str, user_parts: List[Dict[str, Any]], schema: Dict[str, Any],
              max_tokens: int = 384, temperature: float = 0.0, top_logprobs: int = 10,
              model: Optional[str] = None) -> Dict[str, Any]:
    """Una consulta con decodificacion restringida y logprobs. Devuelve dict con text, tokens, latency_ms,
    finish_reason y error (None si fue bien)."""
    from openai import OpenAI

    client = OpenAI(base_url=LOCAL_LLM_URL, api_key=LOCAL_LLM_API_KEY)
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=model or LOCAL_LLM_MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_parts}],
            response_format=schema, temperature=temperature, max_tokens=max_tokens,
            logprobs=True, top_logprobs=top_logprobs, timeout=BENCH_HTTP_TIMEOUT_S,
        )
        ch = r.choices[0]
        toks = tokens_to_dicts(ch.logprobs.content) if ch.logprobs is not None else []
        return {"text": ch.message.content or "", "tokens": toks, "latency_ms": (time.time() - t0) * 1000.0,
                "finish_reason": ch.finish_reason, "error": None}
    except Exception as exc:
        return {"text": "", "tokens": [], "latency_ms": (time.time() - t0) * 1000.0,
                "finish_reason": None, "error": str(exc)}


def image_part(b64: str) -> Dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def text_part(s: str) -> Dict[str, Any]:
    return {"type": "text", "text": s}


def parse_json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", text or "")
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None
