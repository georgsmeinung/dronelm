"""Verificación de conectividad y respuesta del servidor SLM (OpenAI-compatible).

Utiliza la configuración definida en airsim-loop/.env (con fallback a airsim-poc/.env
o variables de entorno ya cargadas).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.error
import urllib.request

# 1. Cargar variables de entorno desde airsim-loop/.env
BASE_DIR = Path(__file__).resolve().parent.parent
LOOP_ENV = BASE_DIR / "airsim-loop" / ".env"
POC_ENV = Path(__file__).resolve().parent / ".env"


def load_env_file(path: Path) -> None:
    """Carga variables desde un archivo .env sin requerir dependencias externas."""
    if not path.is_file():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    # No sobreescribir si ya fue fijado explícitamente en el entorno del proceso
                    if key not in os.environ:
                        os.environ[key] = val
    except Exception as e:
        print(f"Advertencia: no se pudo leer {path}: {e}")


# Cargar dotenv con python-dotenv si está disponible, o con el parser ligero
try:
    from dotenv import load_dotenv

    if LOOP_ENV.exists():
        load_dotenv(dotenv_path=LOOP_ENV)
    elif POC_ENV.exists():
        load_dotenv(dotenv_path=POC_ENV)
    else:
        load_dotenv()
except ImportError:
    if LOOP_ENV.exists():
        load_env_file(LOOP_ENV)
    elif POC_ENV.exists():
        load_env_file(POC_ENV)


# Configuración del LLM
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:1234/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "not-needed-for-local")
LOCAL_LLM_MODEL_NAME = os.getenv("LOCAL_LLM_MODEL_NAME", "qwen/qwen2.5-vl-3b")


def test_with_openai_client() -> Optional[Dict[str, Any]]:
    """Intenta hacer la petición usando el paquete oficial `openai`."""
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=LOCAL_LLM_URL,
            api_key=LOCAL_LLM_API_KEY,
            timeout=10.0,
        )
        t0 = time.perf_counter()
        completion = client.chat.completions.create(
            model=LOCAL_LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a concise drone assistant."},
                {"role": "user", "content": "Ping test: responde con exactamente 'PONG' y tu estado."},
            ],
            max_tokens=50,
            temperature=0.1,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        content = completion.choices[0].message.content or ""
        return {
            "method": "openai SDK",
            "status": "OK",
            "latency_ms": latency_ms,
            "response": content.strip(),
            "raw": completion.model_dump() if hasattr(completion, "model_dump") else str(completion),
        }
    except ImportError:
        return None
    except Exception as e:
        return {
            "method": "openai SDK",
            "status": "ERROR",
            "error": str(e),
        }


def test_with_urllib() -> Dict[str, Any]:
    """Fallback usando urllib (sin dependencias adicionales)."""
    endpoint = f"{LOCAL_LLM_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": LOCAL_LLM_MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You are a concise drone assistant."},
            {"role": "user", "content": "Ping test: responde con exactamente 'PONG' y tu estado."},
        ],
        "max_tokens": 50,
        "temperature": 0.1,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LOCAL_LLM_API_KEY}",
    }

    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10.0) as response:
            latency_ms = (time.perf_counter() - t0) * 1000
            body = response.read().decode("utf-8")
            parsed = json.loads(body)
            choices = parsed.get("choices", [])
            content = choices[0]["message"]["content"] if choices else ""
            return {
                "method": "urllib (REST)",
                "status": "OK",
                "code": response.status,
                "latency_ms": latency_ms,
                "response": content.strip(),
                "raw": parsed,
            }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        return {
            "method": "urllib (REST)",
            "status": "ERROR",
            "code": e.code,
            "error": f"HTTP {e.code}: {e.reason}",
            "details": err_body,
        }
    except urllib.error.URLError as e:
        return {
            "method": "urllib (REST)",
            "status": "ERROR",
            "error": f"URLError: {e.reason}",
        }
    except Exception as e:
        return {
            "method": "urllib (REST)",
            "status": "ERROR",
            "error": str(e),
        }


def main():
    print("=" * 60)
    print(" Verificación del Servidor SLM (OpenAI-compatible API)")
    print("=" * 60)
    print(f" Archivo .env usado: {LOOP_ENV if LOOP_ENV.exists() else POC_ENV}")
    print(f" Endpoint Base URL : {LOCAL_LLM_URL}")
    print(f" Modelo Solicitado : {LOCAL_LLM_MODEL_NAME}")
    print(f" API Key           : {'*' * len(LOCAL_LLM_API_KEY) if LOCAL_LLM_API_KEY else '(none)'}")
    print("-" * 60)

    print("Enviando solicitud de prueba...")
    res = test_with_openai_client()
    if res is None:
        print("[INFO] Paquete 'openai' no instalado en este entorno, usando fallback urllib...")
        res = test_with_urllib()

    print("-" * 60)
    if res.get("status") == "OK":
        print(" [ÉXITO] El servidor SLM respondió correctamente.")
        print(f" Método utilizado : {res.get('method')}")
        print(f" Latencia         : {res.get('latency_ms', 0):.1f} ms")
        print(f" Respuesta del SLM:\n   {res.get('response')}")
    else:
        print(" [FALLO] No se pudo obtener respuesta del servidor SLM.")
        print(f" Método utilizado : {res.get('method')}")
        print(f" Error            : {res.get('error')}")
        if "details" in res:
            print(f" Detalles         : {res.get('details')}")
        print("\nSugerencias:")
        print(" 1. Verifica que el servidor (LM Studio, Ollama, vLLM, etc.) esté en ejecución.")
        print(f" 2. Comprueba que el host y puerto ({LOCAL_LLM_URL}) sean accesibles desde esta máquina.")
        print(f" 3. Comprueba que el modelo '{LOCAL_LLM_MODEL_NAME}' esté cargado.")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
