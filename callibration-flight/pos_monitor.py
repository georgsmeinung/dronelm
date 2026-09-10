"""Monitor de posición en tiempo real — correr mientras se vuela manualmente.

Imprime x, y, z, yaw y velocidad a 5 Hz. Útil para identificar coordenadas
de inicio y pared antes de lanzar d2_occupancy_capture.py.

Uso:
    python pos_monitor.py
    python pos_monitor.py --hz 10
"""
import argparse
import math
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / "config" / ".env")

import cosysairsim as airsim  # type: ignore

VEHICLE = os.getenv("AIRSIM_VEHICLE_NAME", "SimpleFlight")
IP      = os.getenv("AIRSIM_IP", "127.0.0.1")
PORT    = int(os.getenv("AIRSIM_PORT", "41451"))


def _yaw_from_quat(q) -> float:
    w, x, y, z = q.w_val, q.x_val, q.y_val, q.z_val
    return math.degrees(math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hz", type=float, default=5.0)
    args = p.parse_args()

    client = airsim.MultirotorClient(ip=IP, port=PORT)
    client.confirmConnection()
    print(f"Conectado a {IP}:{PORT}  |  Ctrl+C para salir\n")
    print(f"{'X':>8}  {'Y':>8}  {'Z':>8}  {'Yaw°':>7}  {'Speed':>6}  Colisión")
    print("-" * 60)

    dt = 1.0 / args.hz
    prev_pos = None
    while True:
        t0 = time.time()
        try:
            state = client.getMultirotorState(vehicle_name=VEHICLE)
            pos = state.kinematics_estimated.position
            vel = state.kinematics_estimated.linear_velocity
            ori = state.kinematics_estimated.orientation
            yaw = _yaw_from_quat(ori)
            speed = math.sqrt(vel.x_val**2 + vel.y_val**2)
            collision = getattr(state, "collision", None)
            col_str = f"  ← COLISIÓN: {getattr(collision, 'object_name', '?')}" \
                      if collision and getattr(collision, "has_collided", False) else ""

            # Marca cuando el dron está muy quieto (posible punto de referencia)
            still = ""
            if prev_pos:
                moved = math.sqrt(
                    (pos.x_val - prev_pos[0])**2 + (pos.y_val - prev_pos[1])**2
                )
                if moved < 0.1 and speed < 0.1:
                    still = "  ← QUIETO"

            print(
                f"{pos.x_val:8.2f}  {pos.y_val:8.2f}  {pos.z_val:8.2f}"
                f"  {yaw:7.1f}°  {speed:5.2f}m/s{col_str}{still}"
            )
            prev_pos = (pos.x_val, pos.y_val, pos.z_val)
        except Exception as e:
            print(f"  Error: {e}")

        elapsed = time.time() - t0
        time.sleep(max(0.01, dt - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitor detenido.")
