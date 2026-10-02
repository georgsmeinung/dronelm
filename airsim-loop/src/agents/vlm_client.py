# Cliente del VLM local y servicio asincrono (2026-0930).
#
# Reemplaza la parte de infraestructura de deliberative.py (movido a legacy/deliberative_v2.py junto
# con el nodo deliberativo del grafo v1). Solo hay dos consumidores en el camino de vuelo:
#   - "strategic": capa estrategica anclada a pose (vlm_strategic.py), 1 imagen con grilla 3x3.
#   - "deep_scan": barrido panoramico en deadlock (deep_scan.py), N imagenes numeradas.
# Cada modo trae su propio system prompt, esquema JSON (decodificacion restringida) y parser.
# La consulta corre en el hilo de DeliberationService: el lazo de control nunca bloquea.
from __future__ import annotations

import base64
import json as _json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / "config" / ".env")
except Exception:  # pragma: no cover
    pass

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

from .deliberation_service import DeliberationService

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "ollama")
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")
VLM_USE_JSON_SCHEMA = os.getenv("VLM_USE_JSON_SCHEMA", "true").lower() == "true"
VLM_IMAGE_MAX_SIZE = int(os.getenv("VLM_IMAGE_MAX_SIZE", "384"))
# Timeouts del cliente HTTP: deben superar a los watchdogs del lado del llamador.
SLM_HTTP_TIMEOUT_S = float(os.getenv("SLM_HTTP_TIMEOUT_S", "15.0"))
SLM_DEEP_HTTP_TIMEOUT_S = float(os.getenv("SLM_DEEP_HTTP_TIMEOUT_S", "20.0"))

MODES = ("strategic", "deep_scan")


def _encode_frame_base64(frame: Any, max_size: int = VLM_IMAGE_MAX_SIZE) -> Optional[str]:
    if frame is None:
        return None
    try:
        # pyrefly: ignore [missing-import]
        import cv2

        h, w = frame.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return base64.b64encode(buffer).decode("utf-8") if ok else None
    except Exception as exc:
        print(f"[vlm_client] Error codificando frame a base64: {exc}")
        return None


def _extract_json_object(raw: str) -> str:
    """Primer objeto {...} del texto (tolera cercos ``` y texto alrededor)."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    m = re.search(r"\{[\s\S]*\}", cleaned)
    return m.group(0) if m else cleaned


# Tope de tokens por modo. Con decodificacion restringida la generacion termina sola al cerrar el
# esquema; el tope solo protege de una generacion desbocada (modo libre sin esquema). Tiene que sobrar:
# con 160 el barrido (JSON con indentacion, ~4 imagenes) se cortaba antes de la llave final en 5 de 12
# respuestas (pilotos v3 190842Z y 193631Z) y el barrido caia al escape vertical sin usar la respuesta.
VLM_MAX_TOKENS_STRATEGIC = int(os.getenv("VLM_MAX_TOKENS_STRATEGIC", "384"))
VLM_MAX_TOKENS_DEEP = int(os.getenv("VLM_MAX_TOKENS_DEEP", "512"))
TRUNCATED_ERROR = "respuesta_truncada"


def _mode_spec(mode: str) -> Tuple[str, Dict[str, Any], Any, int, float]:
    """(system_prompt, schema, parser, max_tokens, http_timeout) de cada modo."""
    if mode == "strategic":
        from .vlm_strategic import RESPONSE_JSON_SCHEMA_STRATEGIC, SYSTEM_PROMPT_STRATEGIC, parse_strategic

        return SYSTEM_PROMPT_STRATEGIC, RESPONSE_JSON_SCHEMA_STRATEGIC, parse_strategic, VLM_MAX_TOKENS_STRATEGIC, SLM_HTTP_TIMEOUT_S
    if mode == "deep_scan":
        from .deep_scan import RESPONSE_JSON_SCHEMA_PANORAMA, SYSTEM_PROMPT_DEEP_SCAN, parse_panorama_description

        return SYSTEM_PROMPT_DEEP_SCAN, RESPONSE_JSON_SCHEMA_PANORAMA, parse_panorama_description, VLM_MAX_TOKENS_DEEP, SLM_DEEP_HTTP_TIMEOUT_S
    raise ValueError(f"modo VLM desconocido: {mode!r} (validos: {MODES})")


def _query_slm_impl(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]:
    """Consulta al servidor compatible con OpenAI (LM Studio u Ollama).

    Devuelve (parsed_o_None, raw, latency_ms, error). Intenta primero con decodificacion restringida
    (json_schema); si el servidor no la soporta reintenta libre y el parser decide.
    """
    if OpenAI is None:
        return None, "", 0.0, "Libreria openai no instalada"
    system_prompt, schema, parser, max_tokens, timeout = _mode_spec(payload.get("mode", ""))
    images: List[str] = payload.get("images_b64") or []
    labels: List[str] = payload.get("image_labels") or []

    user_content: List[Dict[str, Any]] = [{"type": "text", "text": payload["prompt"]}]
    for i, img in enumerate(images):
        if i < len(labels):
            user_content.append({"type": "text", "text": f"{labels[i]}:"})
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}})

    t0 = time.time()
    try:
        client = OpenAI(base_url=LOCAL_LLM_URL, api_key=LOCAL_LLM_API_KEY)
        kwargs = dict(
            model=LOCAL_LLM_MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            temperature=0.2,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        raw, used_schema, finish = "", False, None
        if VLM_USE_JSON_SCHEMA:
            try:
                completion = client.chat.completions.create(response_format=schema, **kwargs)
                raw = completion.choices[0].message.content or ""
                finish = getattr(completion.choices[0], "finish_reason", None)
                used_schema = True
            except Exception:
                raw = ""
        if not raw:
            completion = client.chat.completions.create(**kwargs)
            raw = completion.choices[0].message.content or ""
            finish = getattr(completion.choices[0], "finish_reason", None)
        latency_ms = (time.time() - t0) * 1000.0
        if finish == "length":
            # Cortada por el tope de tokens: no es una respuesta del modelo, es una falla de la consulta.
            print(f"[vlm_client] respuesta truncada por max_tokens={max_tokens} ({len(raw)} caracteres).")
            return None, raw, latency_ms, TRUNCATED_ERROR
        try:
            data = _json.loads(_extract_json_object(raw))
        except Exception:
            data = None
        parsed = parser(data)
        if parsed is not None:
            parsed["used_json_schema"] = used_schema
        return parsed, raw, latency_ms, None
    except Exception as exc:
        latency_ms = (time.time() - t0) * 1000.0
        print(f"[vlm_client] VLM no disponible ({exc}).")
        return None, "", latency_ms, str(exc)


def make_deliberation_service() -> DeliberationService:
    """Servicio asincrono (un hilo worker, cola de 1) que ejecuta _query_slm_impl.

    La funcion se resuelve en cada llamada (no se captura) para que los tests puedan reemplazarla.
    """
    return DeliberationService(query_fn=lambda payload: _query_slm_impl(payload))
