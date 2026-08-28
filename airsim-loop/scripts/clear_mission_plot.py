"""Borra los dibujos persistentes que dejo plot_mission_route.py en el viewport de UE.

Version standalone de `plot_mission_route.py --clear-only`, sin depender de
pasarle un archivo de mision que de todos modos no se usa para borrar. No
toca el estado del vehiculo (no arma, no despega).

Uso:
    python scripts/clear_mission_plot.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

try:
    import cosysairsim as airsim  # type: ignore
except Exception:  # pragma: no cover
    import airsim  # type: ignore

DEFAULT_IP = os.getenv("AIRSIM_IP", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("AIRSIM_PORT", "41451"))


def main() -> None:
    client = airsim.MultirotorClient(ip=DEFAULT_IP, port=DEFAULT_PORT)
    client.confirmConnection()
    print(f"[clear_mission_plot] Conectado a AirSim en {DEFAULT_IP}:{DEFAULT_PORT}")

    client.simFlushPersistentMarkers()
    print("[clear_mission_plot] Dibujos persistentes borrados (ruta, marcadores, etiquetas).")


if __name__ == "__main__":
    main()
