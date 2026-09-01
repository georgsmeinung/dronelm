# Fase H1 (PLAN-MEJORAS-3): escaneo espacial inicial (pre-vuelo).
#
# Barrido de yaw en el lugar (nunca traslacion) inmediatamente despues del
# despegue, antes de que main.py entre al `while True` del lazo tactico.
# Produce un panorama -- N imagenes RGB en N rumbos distintos, mismo punto --
# y una sola llamada al VLM que devuelve un contexto cualitativo. Es
# ADVISORY, no safety-critical: el ObstacleField por ciclo sigue siendo la
# unica autoridad de seguridad una vez que el dron se mueve.
#
# NO es un nodo del StateGraph -- es una funcion de una sola vez, llamada
# desde main.py entre airsim_client.connect() y la construccion de
# drone_state/entrada al lazo. Llamada bloqueante (no via DeliberationService):
# el dron esta en hover y no hay lazo en tiempo real compitiendo todavia.
# Watchdog propio y generoso: si el VLM falla o expira, la mision arranca
# igual sin contexto inicial -- un VLM caido nunca debe impedir el despegue.
#
# Principio rector (PLAN-MEJORAS-3.md §0): exclusion total de profundidad.
# Este modulo NUNCA pide el canal de profundidad al simulador.
from __future__ import annotations

import json as _json
import math
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

from .deep_scan import _encode_frame_base64, _normalize_deg

LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "ollama")
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")

SCAN_HEADING_COUNT = int(os.getenv("SCAN_HEADING_COUNT", "6"))
INITIAL_SCAN_TIMEOUT_MS = float(os.getenv("INITIAL_SCAN_TIMEOUT_MS", "15000"))
INITIAL_SCAN_SETTLE_S = float(os.getenv("INITIAL_SCAN_SETTLE_S", "1.0"))
INITIAL_SCAN_YAW_TOLERANCE_DEG = float(os.getenv("INITIAL_SCAN_YAW_TOLERANCE_DEG", "5.0"))
INITIAL_SCAN_ROTATE_TIMEOUT_S = float(os.getenv("INITIAL_SCAN_ROTATE_TIMEOUT_S", "4.0"))

SYSTEM_PROMPT_SPATIAL_SCAN = (
    "Sos el modulo de contexto espacial de un dron autonomo, consultado UNA sola vez justo despues del "
    "despegue y antes de iniciar el vuelo hacia los waypoints de la mision.\n"
    "Se te muestran varias imagenes tomadas girando en el lugar (sin trasladarse), cada una hacia un "
    "rumbo distinto -- NO son fotogramas consecutivos en el tiempo, son direcciones distintas vistas "
    "desde el mismo punto.\n"
    "Tu evaluacion es orientativa (advisory): sesga el rumbo inicial de despegue y sirve de chequeo de "
    "cordura contra el plan de mision, pero la seguridad del vuelo la sigue garantizando la percepcion "
    "por ciclo una vez en marcha, no vos.\n\n"
    "Responde UNICAMENTE con un objeto JSON valido, sin texto adicional ni numeros de distancia en "
    "metros -- solo un juicio cualitativo por rumbo."
)


def _build_scan_prompt(labels: List[str]) -> str:
    return (
        f"Panorama de {len(labels)} rumbos capturados girando en el lugar antes de iniciar el vuelo.\n"
        "Para cada rumbo indicado, evalua si el camino se ve DESPEJADO, BLOQUEADO o INCIERTO (evidencia "
        "insuficiente). Luego recomenda con cual rumbo conviene arrancar la mision.\n\n"
        "Responde UNICAMENTE con este JSON:\n"
        '{"headings": [{"heading_deg": <numero>, "assessment": "despejado"|"bloqueado"|"incierto"}, ...], '
        '"recommended_heading_deg": <numero o null>, "notes": "<observacion breve>"}'
    )


def _parse_scan_response(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None
    candidate = match.group(0)
    try:
        data = _json.loads(candidate)
    except Exception:
        try:
            data = _json.loads(candidate.replace("'", '"'))
        except Exception:
            return None
    return data if isinstance(data, dict) else None


def _rotate_to_heading(
    airsim_client: Any,
    target_heading_deg: float,
    tolerance_deg: float = INITIAL_SCAN_YAW_TOLERANCE_DEG,
    timeout_s: float = INITIAL_SCAN_ROTATE_TIMEOUT_S,
) -> bool:
    """Gira en el lugar hasta encarar `target_heading_deg` (rumbo absoluto,
    grados), o hasta agotar `timeout_s`. No traslada (vx=vy=vz=0)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        telemetry = airsim_client.get_telemetry()
        orient = (telemetry or {}).get("orientation", {}) or {}
        current_yaw_deg = math.degrees(float(orient.get("yaw", 0.0)))
        yaw_err = _normalize_deg(target_heading_deg - current_yaw_deg)
        if abs(yaw_err) <= tolerance_deg:
            return True
        airsim_client.execute_velocity(0.0, 0.0, 0.0, yaw_rate=0.0, target_yaw=target_heading_deg)
        time.sleep(0.1)
    return False


def _query_scan_vlm_impl(frames: List[Tuple[float, Any]]) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """Consulta bloqueante al VLM con el panorama. Corre en un hilo aparte
    (ver `_query_scan_vlm_with_watchdog`): nunca se llama directamente desde
    `run_initial_scan`."""
    if OpenAI is None:
        return None, "", "Libreria openai no instalada"

    images_b64: List[str] = []
    labels: List[str] = []
    for heading, frame in frames:
        encoded = _encode_frame_base64(frame)
        if encoded is None:
            continue
        images_b64.append(encoded)
        labels.append(f"[Rumbo {heading:.0f}°]")

    if not images_b64:
        return None, "", "Sin frames validos para el escaneo inicial"

    try:
        client = OpenAI(base_url=LOCAL_LLM_URL, api_key=LOCAL_LLM_API_KEY)
        user_content: List[Dict[str, Any]] = [{"type": "text", "text": _build_scan_prompt(labels)}]
        for label, img_b64 in zip(labels, images_b64):
            user_content.append({"type": "text", "text": f"{label}:"})
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})

        completion = client.chat.completions.create(
            model=LOCAL_LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_SPATIAL_SCAN},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=400,
            timeout=max(1.0, INITIAL_SCAN_TIMEOUT_MS / 1000.0),
        )
        raw = completion.choices[0].message.content or ""
        return _parse_scan_response(raw), raw, None
    except Exception as exc:
        return None, "", str(exc)


def _query_scan_vlm_with_watchdog(frames: List[Tuple[float, Any]]) -> Dict[str, Any]:
    """Corre `_query_scan_vlm_impl` en un hilo con watchdog propio
    (INITIAL_SCAN_TIMEOUT_MS): si el VLM no responde a tiempo, el hilo queda
    abandonado (daemon) y esta funcion devuelve igual -- la mision nunca
    espera mas alla del watchdog."""
    holder: Dict[str, Any] = {}

    def _worker() -> None:
        parsed, raw, err = _query_scan_vlm_impl(frames)
        holder["parsed"] = parsed
        holder["raw"] = raw
        holder["err"] = err

    thread = threading.Thread(target=_worker, name="InitialScanVLM", daemon=True)
    t0 = time.time()
    thread.start()
    thread.join(timeout=max(0.1, INITIAL_SCAN_TIMEOUT_MS / 1000.0))
    latency_ms = (time.time() - t0) * 1000.0

    if thread.is_alive():
        return {
            "available": False,
            "reason": "timeout",
            "headings": [],
            "recommended_heading_deg": None,
            "notes": "",
            "raw_response": "",
            "latency_ms": round(latency_ms, 1),
        }

    parsed = holder.get("parsed")
    raw = holder.get("raw", "") or ""
    err = holder.get("err")
    if parsed is None:
        return {
            "available": False,
            "reason": err or "Formato de respuesta invalido",
            "headings": [],
            "recommended_heading_deg": None,
            "notes": "",
            "raw_response": raw,
            "latency_ms": round(latency_ms, 1),
        }

    return {
        "available": True,
        "reason": None,
        "headings": parsed.get("headings", []),
        "recommended_heading_deg": parsed.get("recommended_heading_deg"),
        "notes": parsed.get("notes", ""),
        "raw_response": raw,
        "latency_ms": round(latency_ms, 1),
    }


def run_initial_scan(airsim_client: Any) -> Dict[str, Any]:
    """Ejecuta el barrido inicial de rumbos y devuelve el contexto espacial.

    Nunca lanza: cualquier falla (VLM caido, timeout, formato invalido)
    devuelve `{"available": False, "reason": ...}` en vez de propagar la
    excepcion -- la mision debe poder arrancar igual (H1.2).
    """
    print(f"[EscaneoInicial] Iniciando barrido de {SCAN_HEADING_COUNT} rumbos...")
    try:
        telemetry = airsim_client.get_telemetry()
        orient = (telemetry or {}).get("orientation", {}) or {}
        start_yaw_deg = math.degrees(float(orient.get("yaw", 0.0)))
        step = 360.0 / max(1, SCAN_HEADING_COUNT)

        frames: List[Tuple[float, Any]] = []
        for i in range(SCAN_HEADING_COUNT):
            heading = _normalize_deg(start_yaw_deg + i * step)
            _rotate_to_heading(airsim_client, heading)
            time.sleep(INITIAL_SCAN_SETTLE_S)
            # Sin pedir profundidad (principio rector §0 del plan): el escaneo
            # inicial no tiene pase libre por ocurrir antes del movimiento.
            image, _telem = airsim_client.capture()
            frames.append((round(heading, 1), image))

        result = _query_scan_vlm_with_watchdog(frames)
    except Exception as exc:  # pragma: no cover - defensivo, ver docstring
        result = {
            "available": False,
            "reason": str(exc),
            "headings": [],
            "recommended_heading_deg": None,
            "notes": "",
            "raw_response": "",
            "latency_ms": 0.0,
        }

    if result.get("available"):
        print(
            f"[EscaneoInicial] Contexto disponible ({result.get('latency_ms', 0.0):.0f}ms). "
            f"Rumbo recomendado: {result.get('recommended_heading_deg')}. {result.get('notes', '')}"
        )
    else:
        print(f"[EscaneoInicial] Sin contexto ({result.get('reason')}). La mision arranca sin sesgo inicial.")
    return result
