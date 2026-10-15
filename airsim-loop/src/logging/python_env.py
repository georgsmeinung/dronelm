# Entorno Python de los lotes (2026-10-15).
#
# Todas las corridas de un lote deben salir del mismo entorno conda (AIRSIM_ENV_DIR en config/.env): un
# lote lanzado con otro interprete (p. ej. el python del PATH) corre con otras versiones de numpy, OpenCV
# o torch -- o falla al importar airsim -- y sus corridas no son comparables con las del resto. Las corridas
# hijas del runner heredan sys.executable, asi que basta con controlar el proceso que lanza el lote.
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / "config" / ".env")
except ImportError:  # sin python-dotenv no es el entorno del proyecto: check_python_env lo rechaza igual
    pass


def expected_env_dir() -> str:
    return os.getenv("AIRSIM_ENV_DIR", "").strip().strip('"').strip("'")


def _same_dir(a: str, b: str) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def check_python_env(prefix: str | None = None, env_dir: str | None = None) -> tuple[bool, str]:
    """(ok, mensaje): ok si el interprete corre en AIRSIM_ENV_DIR, o si AIRSIM_ENV_DIR no esta definido."""
    prefix = sys.prefix if prefix is None else prefix
    env_dir = expected_env_dir() if env_dir is None else env_dir
    if not env_dir:
        return True, f"AIRSIM_ENV_DIR sin definir en config/.env: no se controla el entorno (python={sys.executable})"
    if _same_dir(prefix, env_dir):
        return True, f"entorno {env_dir}"
    return False, (f"el lote debe correr con el python de {env_dir} (AIRSIM_ENV_DIR en config/.env) y este proceso "
                   f"usa {sys.executable} (prefix {prefix}). Lanzar con {Path(env_dir) / 'python.exe'} o con "
                   f"experiments/run_lotes.ps1; --allow-any-python solo para pruebas.")
