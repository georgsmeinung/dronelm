"""Mapa cenital registrado en NED, armado con capturas de AirSim (2026-10-02).

El mapa anterior de CitySim (`citymap.png`, 3.8 px/m, "origen = spawn") no estaba registrado con el
mundo de AirSim: superponiendo las trayectorias voladas de los pilotos, el dron cruzaba manzanas enteras
a 10 m de altura y el spawn caia sobre una azotea, cuando el video lo muestra en medio de una calle. La
imagen esta ademas rotada 90 grados respecto del norte NED. Este script reemplaza ese mapa por uno
construido con el propio simulador, de modo que el registro es exacto por construccion:

  - El dron se teletransporta (ignore_collision) a una grilla de puntos a `--alt` metros, con la camara
    frontal apuntando 90 grados hacia abajo y un campo visual estrecho (`--fov`): casi ortografica, el
    paralaje de un edificio de 100 m en el borde del recorte usado es de unos pocos metros.
  - Carga del mundo: UE carga el escenario por zonas alrededor del punto de vista y desde 1000 m no carga
    la zona de abajo. Antes de cada toma el dron baja a 40 m para forzar la carga, sube y captura; la
    toma se acepta cuando la fraccion de edificios medida con profundidad deja de subir (ver _shot).
  - Orientacion: con yaw 0 y la camara hacia abajo, arriba de la imagen = norte (+x NED) y derecha = este
    (+y NED). El script lo verifica: desplaza el dron +20 m al norte y +20 m al este y mide el
    corrimiento de la imagen (correlacion de fase); de ahi sale tambien la escala real en px/m.
  - De cada toma se usa solo el rectangulo central (un paso de grilla), y se pega en el lienzo de salida
    a `--px-per-m`. El centro del lienzo es el origen NED (0, 0): `map_scales.json` lleva
    `ned_offset = (0, 0)`, la misma convencion de WebDCS (centro de la imagen = ned_offset; arriba =
    norte; derecha = este).

Al terminar se restauran la pose de la camara, su campo visual y la pose del vehiculo. No arma ni
despega. Requiere AirSim corriendo con la escena del mapa.

Uso:
    python scripts/capture_ortho_map.py --out missions/maps/citysim_ortho.png --half-x 400 --half-y 500
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / "config" / ".env")
except Exception:  # pragma: no cover
    pass

import cv2  # noqa: E402

try:
    import cosysairsim as airsim  # type: ignore
except Exception:  # pragma: no cover
    import airsim  # type: ignore

VEHICLE = os.environ["AIRSIM_VEHICLE_NAME"]
CAMERA = os.getenv("AIRSIM_CAMERA_NAME", "0")


# Carga del mundo (streaming de UE): el escenario se carga por zonas alrededor del punto de vista. Desde
# `--alt` (1000 m) la zona de abajo NUNCA se carga: la imagen muestra solo calles y bases vacias, y esta
# quieta, asi que un chequeo de estabilidad por color la aceptaria (ademas el agua animada nunca se
# estabiliza). Medido 2026-10-02 en (-500, 300): a 1000 m, 5 % de pixeles de edificio sin cambio en 9 s;
# bajando a 40 m, 35 % al segundo y 47 % estable desde los 3 s. Procedimiento de cada toma:
#   1. precarga: el dron baja a WARM_ALT_M sobre el centro de la toma y se mantiene WARM_S;
#   2. sube a `--alt` y captura color + profundidad enseguida (UE todavia no descargo la zona);
#   3. repite (precarga corta + captura) hasta que la fraccion de pixeles de edificio -- medida con la
#      PROFUNDIDAD, que no cambia con la animacion del agua -- deja de subir entre dos capturas.
WARM_ALT_M = 40.0
WARM_S = 2.0
REWARM_S = 1.0
UP_SETTLE_S = 0.3
LOADED_TOL = 0.005           # cambio maximo de la fraccion de edificio entre dos capturas
MAX_ROUNDS = 6
UNSTABLE: list = []


def _put(client, x: float, y: float, z: float) -> None:
    pose = airsim.Pose(airsim.Vector3r(float(x), float(y), float(z)), airsim.euler_to_quaternion(0, 0, 0))
    client.simSetVehiclePose(pose, True, vehicle_name=VEHICLE)


def _hold(client, x: float, y: float, z: float, seconds: float) -> None:
    """Mantiene la pose (el vehiculo cae por gravedad si no se la vuelve a fijar)."""
    t0 = time.time()
    while True:
        _put(client, x, y, z)
        if time.time() - t0 >= seconds:
            return
        time.sleep(0.25)


def _grab(client):
    depth_type = getattr(airsim.ImageType, "DepthPlanar", getattr(airsim.ImageType, "DepthPlanner", None))
    r = client.simGetImages([airsim.ImageRequest(CAMERA, airsim.ImageType.Scene, False, False),
                             airsim.ImageRequest(CAMERA, depth_type, True, False)], vehicle_name=VEHICLE)
    img = np.frombuffer(r[0].image_data_uint8, np.uint8).reshape(r[0].height, r[0].width, 3)
    depth = np.array(r[1].image_data_float, np.float32).reshape(r[1].height, r[1].width)
    return np.ascontiguousarray(img[:, :, ::-1]), depth  # RGB -> BGR


def _built_fraction(depth: np.ndarray, alt: float) -> float:
    """Fraccion de pixeles a mas de 15 m por encima del suelo (edificios, autopista)."""
    return float(np.mean(depth < alt - 15.0))


def _shot(client, x: float, y: float, alt: float, settle_s: float = 0.0) -> np.ndarray:
    _hold(client, x, y, -WARM_ALT_M, WARM_S)
    prev = None
    for _ in range(MAX_ROUNDS):
        _hold(client, x, y, -alt, UP_SETTLE_S)
        img, depth = _grab(client)
        frac = _built_fraction(depth, alt)
        if prev is not None and frac - prev <= LOADED_TOL:
            return img
        prev = frac
        _hold(client, x, y, -WARM_ALT_M, REWARM_S)
    UNSTABLE.append([round(float(x), 1), round(float(y), 1)])
    print(f"[ortho] toma sin estabilizar en ({x:.0f}, {y:.0f})", flush=True)
    return img


def _calibrate(client, alt: float, settle_s: float) -> float:
    """px/m de la toma y verificacion de orientacion (norte arriba, este a la derecha)."""
    g = [np.float32(cv2.cvtColor(_shot(client, x, y, alt, settle_s), cv2.COLOR_BGR2GRAY))
         for x, y in ((0.0, 0.0), (20.0, 0.0), (0.0, 20.0))]
    (nx, ny), _ = cv2.phaseCorrelate(g[0], g[1])
    (ex, ey), _ = cv2.phaseCorrelate(g[0], g[2])
    # Dron al norte -> el suelo se corre hacia abajo (dy > 0); dron al este -> hacia la izquierda (dx < 0).
    if not (ny > 0 and abs(nx) < 0.1 * ny and ex < 0 and abs(ey) < 0.1 * abs(ex)):
        raise RuntimeError(f"orientacion inesperada: norte=({nx:.1f},{ny:.1f}) este=({ex:.1f},{ey:.1f})")
    return (ny + abs(ex)) / 2.0 / 20.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--half-x", type=float, default=400.0, help="semiextension norte-sur (m)")
    ap.add_argument("--half-y", type=float, default=500.0, help="semiextension este-oeste (m)")
    ap.add_argument("--alt", type=float, default=1000.0)
    ap.add_argument("--fov", type=float, default=10.0)
    ap.add_argument("--px-per-m", type=float, default=4.0)
    ap.add_argument("--settle-s", type=float, default=1.2)
    args = ap.parse_args()

    client = airsim.MultirotorClient(timeout_value=30)
    client.confirmConnection()
    orig_pose = client.simGetVehiclePose(vehicle_name=VEHICLE)
    # Se restaura SIEMPRE el FOV de la percepcion (CAMERA_HFOV_DEG), no el valor leido al arrancar: si
    # una captura anterior se interrumpio sin restaurar, el valor leido ya estaria alterado.
    flight_fov = float(os.getenv("CAMERA_HFOV_DEG", "90.0"))
    down = airsim.Pose(airsim.Vector3r(0, 0, 0), airsim.euler_to_quaternion(0, math.radians(-90), 0))
    client.simSetCameraPose(CAMERA, down, vehicle_name=VEHICLE)
    client.simSetCameraFov(CAMERA, args.fov, vehicle_name=VEHICLE)
    try:
        tile_ppm = _calibrate(client, args.alt, args.settle_s)
        probe = _shot(client, 0.0, 0.0, args.alt, args.settle_s)
        th, tw = probe.shape[:2]
        # Paso de grilla: la mitad central de la toma (menos paralaje en los bordes).
        step_y = 0.5 * tw / tile_ppm
        step_x = 0.5 * th / tile_ppm
        ppm = args.px_per_m
        W, H = int(round(2 * args.half_y * ppm)), int(round(2 * args.half_x * ppm))
        canvas = np.zeros((H, W, 3), np.uint8)
        xs = np.arange(-args.half_x + step_x / 2, args.half_x + step_x / 2, step_x)
        ys = np.arange(-args.half_y + step_y / 2, args.half_y + step_y / 2, step_y)
        print(f"[ortho] toma {tw}x{th} a {tile_ppm:.3f} px/m; grilla {len(xs)}x{len(ys)} = {len(xs) * len(ys)} tomas")
        scale = ppm / tile_ppm
        n = 0
        for x in xs:
            for y in ys:
                img = _shot(client, x, y, args.alt, args.settle_s)
                small = cv2.resize(img, (int(round(tw * scale)), int(round(th * scale))), interpolation=cv2.INTER_AREA)
                sh, sw = small.shape[:2]
                # rectangulo central de un paso (+2 px de solape) alrededor del centro de la toma
                hw, hh = int(math.ceil(step_y * ppm / 2)) + 2, int(math.ceil(step_x * ppm / 2)) + 2
                cu, cv_ = W / 2 + y * ppm, H / 2 - x * ppm          # centro de la toma en el lienzo
                for_u0, for_v0 = int(round(cu - hw)), int(round(cv_ - hh))
                src_u0, src_v0 = int(round(sw / 2 - hw)), int(round(sh / 2 - hh))
                u0, v0 = max(0, for_u0), max(0, for_v0)
                u1, v1 = min(W, for_u0 + 2 * hw), min(H, for_v0 + 2 * hh)
                if u1 > u0 and v1 > v0:
                    canvas[v0:v1, u0:u1] = small[src_v0 + (v0 - for_v0):src_v0 + (v1 - for_v0),
                                                 src_u0 + (u0 - for_u0):src_u0 + (u1 - for_u0)]
                n += 1
                if n % 20 == 0:
                    print(f"[ortho] {n}/{len(xs) * len(ys)}", flush=True)
    finally:
        client.simSetCameraPose(CAMERA, airsim.Pose(airsim.Vector3r(0, 0, 0), airsim.euler_to_quaternion(0, 0, 0)),
                                vehicle_name=VEHICLE)
        client.simSetCameraFov(CAMERA, flight_fov, vehicle_name=VEHICLE)
        client.simSetVehiclePose(orig_pose, True, vehicle_name=VEHICLE)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), canvas)
    meta = {
        "scale": ppm, "ned_offset": {"x": 0, "y": 0},
        "extent_m": {"x": [-args.half_x, args.half_x], "y": [-args.half_y, args.half_y]},
        "capture": {"alt_m": args.alt, "fov_deg": args.fov, "tile_px_per_m": round(tile_ppm, 4),
                    "tiles": n, "unstable_tiles": UNSTABLE, "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "convention": "centro de la imagen = ned_offset; arriba = norte (+x); derecha = este (+y)",
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[ortho] {out} ({W}x{H}, {ppm} px/m)")


if __name__ == "__main__":
    main()
