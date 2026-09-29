"""Sonda de la camara externa FollowCam: existe, devuelve imagen y ¿cuanto cuesta? (2026-0929)

No arma, no despega y no mueve el dron: solo llama a simGetImages. NUNCA usa
simGetCameraInfo (en el plugin AirSim de CitySim, un nombre de camara inexistente
provoca EXCEPTION_ACCESS_VIOLATION en WorldSimApi::getCameraInfo y tumba Unreal).

Uso (con Unreal en Play y el vehiculo cargado):
    python experiments/probe_follow_cam.py [--n 40] [--out probe_follow]

Mide, sobre N capturas cada una: solo frontal, solo FollowCam y frontal+FollowCam en UNA
llamada (asi la pide el runner), e imprime media / p50 / p90 y el sobrecosto de sumar la
FollowCam. Guarda un PNG de cada camara para revisar encuadre y colores.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

try:  # misma config unica que el resto (config/.env): nombre de vehiculo, camara, IP
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / "config" / ".env")
except Exception:
    pass

try:  # mismo backend que src/hardware/airsim_client.py
    import cosysairsim as airsim  # type: ignore
except Exception:  # pragma: no cover
    import airsim  # type: ignore


def _timed(client, requests, vehicle, n):
    ms, last = [], None
    for _ in range(n):
        t = time.perf_counter()
        last = client.simGetImages(requests, vehicle_name=vehicle)
        ms.append((time.perf_counter() - t) * 1000.0)
    return ms, last


def _stats(ms):
    s = sorted(ms)
    return statistics.mean(ms), statistics.median(ms), s[min(len(s) - 1, int(0.9 * len(s)))]


def _save(resp, path):
    import cv2

    img = np.frombuffer(resp.image_data_uint8, dtype=np.uint8).reshape(resp.height, resp.width, 3)
    cv2.imwrite(str(path), np.ascontiguousarray(img[:, :, ::-1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default="probe_follow")
    ap.add_argument("--front", default=os.getenv("AIRSIM_CAMERA_NAME", "0"))
    ap.add_argument("--follow", default=os.getenv("AIRSIM_FOLLOW_CAMERA", "FollowCam") or "FollowCam")
    ap.add_argument("--vehicle", default=os.environ["AIRSIM_VEHICLE_NAME"])
    ap.add_argument("--ip", default=os.getenv("AIRSIM_IP", "127.0.0.1"))
    args = ap.parse_args()

    front = int(args.front) if str(args.front).isdigit() else args.front
    client = airsim.MultirotorClient(ip=args.ip, timeout_value=8)
    client.confirmConnection()

    # ANTES de cualquier llamada con vehicle_name: un vehiculo inexistente tumba Unreal
    # (el plugin desreferencia nullptr sin comprobar; crashes del 2026-0929).
    try:
        vehicles = list(client.listVehicles())
    except Exception as exc:
        print(f"No se pudo listar vehiculos ({exc}); abortando por seguridad.")
        return 2
    if args.vehicle not in vehicles:
        print(f"Vehiculo '{args.vehicle}' NO existe en la simulacion. Disponibles: {vehicles}.")
        print("Alinea AIRSIM_VEHICLE_NAME (config/.env) con airsim-settings/settings.json.")
        return 2
    scene = airsim.ImageType.Scene
    req_front = airsim.ImageRequest(front, scene, False, False)
    req_follow = airsim.ImageRequest(args.follow, scene, False, False)

    # Existencia: simGetImages lanza un error RPC (catchable) si la camara no existe.
    try:
        probe = client.simGetImages([req_follow], vehicle_name=args.vehicle)
    except Exception as exc:
        print(f"FollowCam '{args.follow}' NO disponible en el vehiculo '{args.vehicle}': {exc}")
        print("Si la agregaste a settings.json, reinicia el Editor de Unreal (no basta Stop/Play).")
        return 2
    if not probe or probe[0].width <= 0:
        print(f"FollowCam '{args.follow}' existe pero no devuelve imagen (revisa CaptureSettings ImageType 0).")
        return 3
    print(f"FollowCam OK: {probe[0].width}x{probe[0].height}, "
          f"{len(probe[0].image_data_uint8) / 1e6:.2f} MB por imagen (sin comprimir).")

    _timed(client, [req_front, req_follow], args.vehicle, 3)          # calentamiento
    ms_front, r_front = _timed(client, [req_front], args.vehicle, args.n)
    ms_follow, r_follow = _timed(client, [req_follow], args.vehicle, args.n)
    ms_both, r_both = _timed(client, [req_front, req_follow], args.vehicle, args.n)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _save(r_front[0], out / "front.png")
    _save(r_both[1], out / "follow.png")

    print(f"\n{'solicitud':<28}{'media ms':>10}{'p50':>9}{'p90':>9}")
    for name, ms in (("solo frontal", ms_front), ("solo FollowCam", ms_follow),
                     ("frontal + FollowCam (1 llamada)", ms_both)):
        m, p50, p90 = _stats(ms)
        print(f"{name:<32}{m:>6.1f}{p50:>9.1f}{p90:>9.1f}")
    delta = statistics.mean(ms_both) - statistics.mean(ms_front)
    period_ms = 1000.0 / float(os.getenv("LOOP_HZ", "5.0"))
    print(f"\nSobrecosto de agregar la FollowCam: +{delta:.1f} ms/ciclo "
          f"({100 * delta / period_ms:.0f}% del periodo de {period_ms:.0f} ms a LOOP_HZ={os.getenv('LOOP_HZ', '5.0')}).")
    print(f"PNG de referencia en {out.resolve()} (front.png, follow.png).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
