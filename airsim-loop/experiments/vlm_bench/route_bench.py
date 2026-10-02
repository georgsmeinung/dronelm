"""Calibracion del planificador de ruta: el juicio del VLM sobre el mapa contra la geometria de AirSim.

Para cada tramo de las misiones dadas se generan las mismas rutas candidatas que usa el planificador
(src/planning/route_planner.py) y, para cada una:

  - Verdad de terreno (AirSim, fuera de vuelo): se recorre la ruta cada STEP_M metros a la altura del
    tramo, mirando en la direccion de avance, y se captura la profundidad. La ruta es "libre" si en ningun
    punto hay un obstaculo en la ventana central de la imagen (+-WINDOW_FRAC del ancho y alto) a menos de
    CLEAR_M (un paso y medio), y si la camara nunca queda dentro de la geometria. Antes de cada tramo se
    espera a que UE cargue la zona (el escenario se carga por zonas alrededor del punto de vista).
  - Juicio del VLM: la misma imagen, prompt y esquema que usa el planificador; respuesta y P(si).

Salida: <bench>/routes.jsonl (una linea por candidata). report.py agrega las metricas: exactitud
balanceada y AUC del juicio, y si la ruta que elegiria el planificador es realmente libre, contra la recta.

Uso:
    python experiments/vlm_bench/route_bench.py --bench ../airsim-runs/vlm_bench/v1 \
        --missions ../airsim-plan/missions/flightplans/citysim_pilot.json ../airsim-plan/missions/flightplans/citysim_clear.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, read_jsonl  # noqa: E402

sys.path.insert(0, str(ROOT))
from src.planning import route_planner as rp  # noqa: E402

VEHICLE = os.environ["AIRSIM_VEHICLE_NAME"]
CAMERA = os.getenv("AIRSIM_CAMERA_NAME", "0")
STEP_M = 4.0
CLEAR_M = 1.5 * STEP_M
WINDOW_FRAC = 0.12
INSIDE_M = 1.0
LEG_WARM_S = 2.5


def sample_route(points: Sequence[Tuple[float, float]], step: float = STEP_M) -> List[Tuple[float, float, float]]:
    """Puntos cada `step` metros a lo largo de la poligonal, con el rumbo del segmento (deg)."""
    out: List[Tuple[float, float, float]] = []
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            continue
        yaw = math.degrees(math.atan2(dy, dx))
        n = max(1, int(math.ceil(d / step)))
        for k in range(n):
            t = k / n
            out.append((a[0] + dx * t, a[1] + dy * t, yaw))
    return out


def window_clearance(depth: np.ndarray, frac: float = WINDOW_FRAC) -> Tuple[float, float]:
    """(p5, p50) de la profundidad en la ventana central."""
    h, w = depth.shape[:2]
    win = depth[int(h * (0.5 - frac)):int(h * (0.5 + frac)), int(w * (0.5 - frac)):int(w * (0.5 + frac))]
    return float(np.percentile(win, 5)), float(np.percentile(win, 50))


def route_truth(client, points, z: float) -> Dict[str, Any]:
    import cosysairsim as airsim

    depth_type = getattr(airsim.ImageType, "DepthPlanar", getattr(airsim.ImageType, "DepthPlanner", None))
    req = [airsim.ImageRequest(CAMERA, depth_type, True, False)]
    blocked_at = None
    min_p5 = math.inf
    samples = sample_route(points)
    for i, (x, y, yaw) in enumerate(samples):
        pose = airsim.Pose(airsim.Vector3r(x, y, z), airsim.euler_to_quaternion(0, 0, math.radians(yaw)))
        client.simSetVehiclePose(pose, True, vehicle_name=VEHICLE)
        time.sleep(0.12)
        client.simSetVehiclePose(pose, True, vehicle_name=VEHICLE)
        r = client.simGetImages(req, vehicle_name=VEHICLE)[0]
        d = np.array(r.image_data_float, np.float32).reshape(r.height, r.width)
        p5, p50 = window_clearance(d)
        min_p5 = min(min_p5, p5)
        if p50 < INSIDE_M or p5 < CLEAR_M:
            blocked_at = {"i": i, "x": round(x, 1), "y": round(y, 1), "p5": round(p5, 2), "inside": p50 < INSIDE_M}
            break
    return {"clear": blocked_at is None, "blocked_at": blocked_at, "points_checked": len(samples) if blocked_at is None
            else blocked_at["i"] + 1, "min_p5": round(min_p5, 2)}


def warm_leg(client, a: Tuple[float, float], b: Tuple[float, float], z: float) -> None:
    """Hace que UE cargue la zona del tramo: recorre sus extremos y su centro a la altura del tramo."""
    import cosysairsim as airsim

    for x, y in (a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), b):
        t0 = time.time()
        while time.time() - t0 < LEG_WARM_S:
            client.simSetVehiclePose(airsim.Pose(airsim.Vector3r(x, y, z), airsim.euler_to_quaternion(0, 0, 0)),
                                     True, vehicle_name=VEHICLE)
            time.sleep(0.25)


def main() -> None:
    import cosysairsim as airsim
    import cv2

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", required=True)
    ap.add_argument("--missions", nargs="+", required=True)
    args = ap.parse_args()

    bench = Path(args.bench)
    img_dir = bench / "routes"
    img_dir.mkdir(parents=True, exist_ok=True)
    out_path = bench / "routes.jsonl"
    done = {(r["mission"], r["leg"], r["candidate"]) for r in read_jsonl(out_path)}

    client = airsim.MultirotorClient(timeout_value=30)
    client.confirmConnection()
    orig = client.simGetVehiclePose(vehicle_name=VEHICLE)
    try:
        for mpath in args.missions:
            manifest = json.loads(Path(mpath).read_text(encoding="utf-8"))
            mission = Path(mpath).stem
            mv = rp.MapView.load(manifest["map"])
            for li, (a, b) in enumerate(rp.legs(manifest)):
                A, B = (float(a["x"]), float(a["y"])), (float(b["x"]), float(b["y"]))
                z = float(b.get("z", -10.0))
                leg = f"{li:02d}_{a['label']}->{b['label']}"
                cands = rp.leg_candidates(A, B)
                window = rp.leg_window(cands)
                warmed = False
                for c in cands:
                    if (mission, leg, c["name"]) in done:
                        continue
                    if not warmed:
                        warm_leg(client, A, B, z)
                        warmed = True
                    img = rp.render_candidate(mv, c["points"], window)
                    name = f"{mission}_{li:02d}_{c['name']}.jpg"
                    cv2.imwrite(str(img_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
                    judge = rp.read_judgement(rp.default_query(img, alt_m=abs(z)))
                    truth = route_truth(client, c["points"], z)
                    rec = {"mission": mission, "leg": leg, "candidate": c["name"], "points": c["points"],
                           "length_m": c["length_m"], "z": z, "image": f"routes/{name}", "model": rp.model_name(),
                           **judge, **truth}
                    append_jsonl(out_path, rec)
                    print(f"[routes] {mission} {leg} {c['name']}: vlm={judge['answer']}/{judge['p_si']} "
                          f"real={'libre' if truth['clear'] else 'bloqueada'}", flush=True)
    finally:
        client.simSetVehiclePose(orig, True, vehicle_name=VEHICLE)


if __name__ == "__main__":
    main()
