"""Verdad de terreno del banco: reubica el dron en cada pose registrada y captura RGB + profundidad.

Herramienta de laboratorio, fuera del lazo de vuelo (misma categoria que la calibracion del TTC): es el
unico lugar del banco que lee la profundidad del simulador. Por muestra:

  1. Teletransporta el vehiculo (ignore_collision) a la pose registrada -- posicion y actitud completas
     (yaw, pitch, roll): el fotograma reproduce lo que vio la camara en vuelo.
  2. Espera a que UE cargue la zona: el escenario se carga por zonas alrededor del punto de vista y, tras
     un salto largo, la primera captura puede salir sin edificios. Se repite la captura hasta que la
     grilla de profundidad (p5 por sector) deja de cambiar entre dos capturas seguidas.
  3. Guarda el RGB (`replay/<id>.jpg`), la profundidad reducida por minimo 4x4 (`replay/<id>_depth.npz`)
     y las etiquetas (labels.labels_from_depth) en `samples_gt.jsonl`.
  4. Alineacion: correlacion entre el RGB reproducido y lo que registro el dron (la foto cruda si la hay;
     si no, el cuadro del video frontal sin el HUD). Una correlacion baja marca una muestra cuya pose no
     se reprodujo bien (p. ej. el dron atravesando una fachada) y queda fuera de la evaluacion.

Uso:
    python experiments/vlm_bench/ground_truth.py --bench ../airsim-runs/vlm_bench/v1
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import append_jsonl, read_jsonl  # noqa: E402
from labels import labels_from_depth, pool_min  # noqa: E402

VEHICLE = os.environ["AIRSIM_VEHICLE_NAME"]
CAMERA = os.getenv("AIRSIM_CAMERA_NAME", "0")
HUD_FRAC = 52.0 / 432.0          # banda superior del video frontal con el HUD (flight_overlay)
LONG_JUMP_M = 30.0
LONG_JUMP_WAIT_S = 1.5
STABLE_TOL_M = 0.5
MAX_ROUNDS = 8


def _quat(roll_deg: float, pitch_deg: float, yaw_deg: float):
    import cosysairsim as airsim

    return airsim.euler_to_quaternion(math.radians(roll_deg), math.radians(pitch_deg), math.radians(yaw_deg))


def _grab(client) -> Tuple[np.ndarray, np.ndarray]:
    import cosysairsim as airsim

    depth_type = getattr(airsim.ImageType, "DepthPlanar", getattr(airsim.ImageType, "DepthPlanner", None))
    r = client.simGetImages([airsim.ImageRequest(CAMERA, airsim.ImageType.Scene, False, False),
                             airsim.ImageRequest(CAMERA, depth_type, True, False)], vehicle_name=VEHICLE)
    img = np.frombuffer(r[0].image_data_uint8, np.uint8).reshape(r[0].height, r[0].width, 3)
    depth = np.array(r[1].image_data_float, np.float32).reshape(r[1].height, r[1].width)
    return np.ascontiguousarray(img[:, :, ::-1]), depth


def _signature(depth: np.ndarray) -> np.ndarray:
    lab = labels_from_depth(depth)
    return np.array([min(v["p5"], 100.0) for v in lab["cells"].values()], np.float32)


def capture_at(client, pose: Dict[str, float], wait_s: float) -> Tuple[np.ndarray, np.ndarray, int, bool]:
    import cosysairsim as airsim

    p = airsim.Pose(airsim.Vector3r(pose["x"], pose["y"], pose["z"]),
                    _quat(pose.get("roll_deg", 0.0), pose.get("pitch_deg", 0.0), pose["yaw_deg"]))

    def put() -> None:
        client.simSetVehiclePose(p, True, vehicle_name=VEHICLE)

    put()
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(0.25)
        put()
    time.sleep(0.15)
    put()
    img, depth = _grab(client)
    sig = _signature(depth)
    for k in range(1, MAX_ROUNDS + 1):
        time.sleep(0.4)
        put()
        time.sleep(0.1)
        img2, depth2 = _grab(client)
        sig2 = _signature(depth2)
        if float(np.max(np.abs(sig2 - sig))) <= STABLE_TOL_M:
            return img2, depth2, k, True
        img, depth, sig = img2, depth2, sig2
    return img, depth, MAX_ROUNDS, False


def recorded_view(sample: Dict[str, Any], bench: Path) -> Optional[np.ndarray]:
    """Lo que registro el dron: la foto cruda si existe; si no, el cuadro del video frontal sin el HUD."""
    import cv2

    if sample.get("photo"):
        img = cv2.imread(str(Path(sample["run_dir"]) / sample["photo"]))
        if img is not None:
            return img
    if sample.get("onboard_frame"):
        img = cv2.imread(str(bench / "frames" / sample["onboard_frame"]))
        if img is not None:
            return img[int(round(img.shape[0] * HUD_FRAC)):]
    return None


def alignment(replay: np.ndarray, recorded: Optional[np.ndarray], hud_cut: bool) -> Optional[float]:
    """Correlacion normalizada en gris a baja resolucion (se recorta lo mismo que le falta al video)."""
    import cv2

    if recorded is None:
        return None
    r = replay[int(round(replay.shape[0] * HUD_FRAC)):] if hud_cut else replay
    a = cv2.resize(cv2.cvtColor(r, cv2.COLOR_BGR2GRAY), (96, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(cv2.cvtColor(recorded, cv2.COLOR_BGR2GRAY), (96, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    a, b = a - a.mean(), b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return round(float((a * b).sum() / den), 3) if den > 0 else None


def main() -> None:
    import cv2
    import cosysairsim as airsim

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--trajectory", type=int, default=900,
                    help="muestras de trayectoria a reproducir (al azar, semilla fija; 0 = todas). Las "
                         "estrategicas y las de barrido se reproducen siempre.")
    args = ap.parse_args()

    bench = Path(args.bench)
    (bench / "replay").mkdir(exist_ok=True)
    out_path = bench / "samples_gt.jsonl"
    done = {r["id"] for r in read_jsonl(out_path)}
    samples = read_jsonl(bench / "samples.jsonl")
    if args.trajectory:
        traj = [s["id"] for s in samples if s["kind"] == "trajectory"]
        keep = set(random.Random(0).sample(traj, min(args.trajectory, len(traj))))
        samples = [s for s in samples if s["kind"] != "trajectory" or s["id"] in keep]
    samples = [s for s in samples if s["id"] not in done]   # orden del archivo: por corrida y ciclo
    if args.limit:
        samples = samples[: args.limit]
    print(f"[gt] {len(samples)} muestras pendientes ({len(done)} ya hechas)")

    client = airsim.MultirotorClient(timeout_value=30)
    client.confirmConnection()
    fov = float(client.simGetCameraInfo(CAMERA, vehicle_name=VEHICLE).fov)
    expected = float(os.getenv("CAMERA_HFOV_DEG", "90.0"))
    if abs(fov - expected) > 0.5:
        raise SystemExit(f"[gt] la camara tiene FOV {fov:.1f} y el vuelo usa {expected:.1f}: las reproducciones "
                         "no serian comparables con lo que vio el dron. Restaurar el FOV antes de seguir.")
    orig_pose = client.simGetVehiclePose(vehicle_name=VEHICLE)
    last_xy = None
    try:
        for i, s in enumerate(samples):
            pose = s["pose"]
            jump = math.inf if last_xy is None else math.hypot(pose["x"] - last_xy[0], pose["y"] - last_xy[1])
            img, depth, rounds, stable = capture_at(client, pose, LONG_JUMP_WAIT_S if jump > LONG_JUMP_M else 0.0)
            last_xy = (pose["x"], pose["y"])
            cv2.imwrite(str(bench / "replay" / f"{s['id']}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            np.savez_compressed(bench / "replay" / f"{s['id']}_depth.npz", depth=pool_min(depth).astype(np.float16))
            rec_view = recorded_view(s, bench)
            s["gt"] = labels_from_depth(depth)
            s["replay"] = {"rgb": f"replay/{s['id']}.jpg", "rounds": rounds, "stable": stable,
                           "align_ncc": alignment(img, rec_view, hud_cut=not s.get("photo")),
                           "align_source": "photo" if s.get("photo") else ("video" if rec_view is not None else None)}
            append_jsonl(out_path, s)
            if (i + 1) % 25 == 0:
                print(f"[gt] {i + 1}/{len(samples)}", flush=True)
    finally:
        client.simSetVehiclePose(orig_pose, True, vehicle_name=VEHICLE)
    print(f"[gt] listo -> {out_path}")


if __name__ == "__main__":
    main()
