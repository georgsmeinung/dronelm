"""D3 — Validación de derotación con yaw agresivo (PLAN-DEUDA-TECNICA.md).

El dron hovea a distancia fija de una pared y aplica yaw rotacional a tasas
crecientes. Mide foe_confidence y field_source por frame para determinar en
qué yaw_rate la derotación de flujo óptico deja de ser confiable.

Uso:
    python d3_derotation_capture.py --wall-x 61 --wall-y -42 --hover-z -7
    python d3_derotation_capture.py --wall-x 61 --wall-y -42 --hover-z -7 \\
        --hover-dist 5.0 --yaw-rates 0 0.3 0.5 0.8 1.0 --frames-per-rate 50
"""
import argparse
import math
import os
import sys
import time
from math import atan2, degrees, sin, cos
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "airsim-loop"))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / "config" / ".env")

import cosysairsim as airsim  # type: ignore
from cosysairsim import Quaternionr, DrivetrainType, YawMode  # type: ignore
import numpy as np

from src.hardware.airsim_client import _state_to_telemetry, _quaternion_to_euler
from src.perception.flow_ttc import FlowTTCEstimator
from src.perception.obstacle_field import SECTORS, BANDS

VEHICLE = os.getenv("AIRSIM_VEHICLE_NAME", "SimpleFlight")
IP      = os.getenv("AIRSIM_IP", "127.0.0.1")
PORT    = int(os.getenv("AIRSIM_PORT", "41451"))

DEFAULT_YAW_RATES    = [0.0, 0.3, 0.5, 0.8, 1.0]  # rad/s
DEFAULT_FRAMES       = 50
DEFAULT_HOVER_DIST_M = 5.0
SETTLE_FRAMES        = 5   # frames descartados al inicio de cada tasa (settling)


def _quaternion_yaw(yaw_rad: float) -> Quaternionr:
    return Quaternionr(x_val=0.0, y_val=0.0, z_val=sin(yaw_rad / 2), w_val=cos(yaw_rad / 2))


def connect(ip: str, port: int) -> airsim.MultirotorClient:
    client = airsim.MultirotorClient(ip=ip, port=port)
    client.confirmConnection()
    client.enableApiControl(True, vehicle_name=VEHICLE)
    print(f"Conectado a AirSim en {ip}:{port}")
    return client


def teleport(client, x: float, y: float, z: float, yaw_rad: float):
    pose = airsim.Pose(
        airsim.Vector3r(x, y, z),
        _quaternion_yaw(yaw_rad),
    )
    client.simSetVehiclePose(pose, ignore_collision=True, vehicle_name=VEHICLE)
    time.sleep(0.5)


def hover_with_yaw(client, yaw_rate_dps: float, duration_s: float):
    """Aplica yaw rotacional mientras mantiene posición."""
    client.moveByVelocityBodyFrameAsync(
        0, 0, 0,
        duration=duration_s,
        drivetrain=DrivetrainType.MaxDegreeOfFreedom,
        yaw_mode=YawMode(is_rate=True, yaw_or_rate=yaw_rate_dps),
        vehicle_name=VEHICLE,
    )


def capture_frame(client):
    """Retorna (rgb_array, depth_array, telemetry_dict)."""
    req = [
        airsim.ImageRequest("0", airsim.ImageType.Scene, False, False),
        airsim.ImageRequest("0", airsim.ImageType.DepthPlanar, True, False),
    ]
    responses = client.simGetImages(req, vehicle_name=VEHICLE)
    rgb_resp, dep_resp = responses[0], responses[1]

    # RGB
    rgb = np.frombuffer(rgb_resp.image_data_uint8, dtype=np.uint8)
    rgb = rgb.reshape(rgb_resp.height, rgb_resp.width, 3)

    # Depth
    depth = np.array(dep_resp.image_data_float, dtype=np.float32)
    depth = depth.reshape(dep_resp.height, dep_resp.width)

    state = client.getMultirotorState(vehicle_name=VEHICLE)
    telem = _state_to_telemetry(state)

    return rgb, depth, telem, state


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--wall-x",      type=float, required=True)
    p.add_argument("--wall-y",      type=float, required=True)
    p.add_argument("--hover-z",     type=float, default=-7.0)
    p.add_argument("--hover-dist",  type=float, default=DEFAULT_HOVER_DIST_M,
                   help="Distancia (m) a la pared durante el hover")
    p.add_argument("--yaw-rates",   type=float, nargs="+", default=DEFAULT_YAW_RATES,
                   help="Tasas de yaw a probar (rad/s)")
    p.add_argument("--frames-per-rate", type=int, default=DEFAULT_FRAMES)
    p.add_argument("--output-dir",  type=str, default="d3_dataset")
    args = p.parse_args()

    # ── Posición de hover: a hover_dist metros antes de la pared ────────────
    # La pared está en wall_y; nos aproximamos desde -Y (yaw=90°)
    wall_y   = args.wall_y
    hover_y  = wall_y - args.hover_dist
    hover_x  = args.wall_x
    hover_z  = args.hover_z
    wall_yaw_rad = atan2(wall_y - hover_y, args.wall_x - hover_x)  # ≈ pi/2
    wall_yaw_deg = degrees(wall_yaw_rad)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nPared: ({args.wall_x}, {wall_y})  Hover: ({hover_x:.1f}, {hover_y:.1f}, {hover_z})  Yaw={wall_yaw_deg:.1f}°")
    print(f"Distancia a pared: {args.hover_dist} m")
    print(f"Tasas yaw (rad/s): {args.yaw_rates}")
    print(f"Frames por tasa  : {args.frames_per_rate} (+ {SETTLE_FRAMES} settling descartados)\n")

    try:
        from src.perception.flow_ttc import FLOW_MAX_ROTATION_DEG as _fmrd
        flow_max_dps = _fmrd * 5.0   # deg/frame * Hz → deg/s
        print(f"FLOW_MAX_ROTATION_DEG={_fmrd}° → umbral teórico ≈ {flow_max_dps:.1f}°/s = {math.radians(flow_max_dps):.3f} rad/s")
    except (ImportError, AttributeError):
        flow_max_dps = None

    client = connect(IP, PORT)
    estimator = FlowTTCEstimator()

    # ── Buffers de resultado ─────────────────────────────────────────────────
    records = {
        "yaw_rate_target_radps": [],
        "yaw_rate_target_dps": [],
        "actual_yaw_rate_dps": [],
        "foe_confidence": [],
        "field_source": [],
        "occ_centro": [],
        "conf_centro": [],
        "ttc_s_centro": [],
        "is_blocked_centro": [],
        "pos_x": [], "pos_y": [], "pos_z": [],
        "yaw_deg": [],
        "frame_idx": [],
    }

    prev_rgb, prev_telem = None, None
    prev_yaw_deg = None

    for yaw_rate_radps in args.yaw_rates:
        yaw_rate_dps = degrees(yaw_rate_radps)

        print("=" * 60)
        print(f"=== Yaw rate: {yaw_rate_radps} rad/s ({yaw_rate_dps:.1f}°/s) ===")
        print("=" * 60)

        # Teleportar al inicio con orientación hacia la pared
        teleport(client, hover_x, hover_y, hover_z, wall_yaw_rad)
        estimator = FlowTTCEstimator()  # reset entre tasas
        prev_rgb, prev_telem = None, None
        prev_yaw_deg = None

        total_frames = SETTLE_FRAMES + args.frames_per_rate
        # Lanzar movimiento (duration generosa; lo interrumpimos con teleport al
        # inicio de la siguiente tasa)
        hover_with_yaw(client, yaw_rate_dps, duration_s=float(total_frames) * 0.25)

        captured = 0
        for frame_i in range(total_frames):
            t0 = time.time()

            rgb, depth, telem, state = capture_frame(client)

            # Yaw actual
            orient = state.kinematics_estimated.orientation
            _, _, cur_yaw_rad = _quaternion_to_euler(orient)
            cur_yaw_deg = degrees(cur_yaw_rad)

            # Yaw rate medido
            if prev_yaw_deg is not None:
                delta = cur_yaw_deg - prev_yaw_deg
                # Normalizar al rango [-180, 180]
                delta = (delta + 180) % 360 - 180
                actual_yaw_rate_dps = abs(delta) / 0.2   # dt ≈ 0.2s a 5Hz
            else:
                actual_yaw_rate_dps = 0.0
            prev_yaw_deg = cur_yaw_deg

            # ObstacleField
            field = estimator.estimate(rgb, prev_rgb, telem, prev_telem)

            pos = state.kinematics_estimated.position
            skip = frame_i < SETTLE_FRAMES

            if not skip:
                records["yaw_rate_target_radps"].append(yaw_rate_radps)
                records["yaw_rate_target_dps"].append(yaw_rate_dps)
                records["actual_yaw_rate_dps"].append(actual_yaw_rate_dps)
                records["foe_confidence"].append(field.foe_confidence)
                records["field_source"].append(field.source)
                records["occ_centro"].append(field.sector_occupancy("centro"))
                records["conf_centro"].append(field.sector_confidence("centro"))
                ttc = field.sector_ttc("centro")
                records["ttc_s_centro"].append(ttc if ttc != float("inf") else 9999.0)
                records["is_blocked_centro"].append(float(field.is_blocked("centro")))
                records["pos_x"].append(pos.x_val)
                records["pos_y"].append(pos.y_val)
                records["pos_z"].append(pos.z_val)
                records["yaw_deg"].append(cur_yaw_deg)
                records["frame_idx"].append(captured)
                captured += 1

                prefix = "  [SETTLING]" if False else ""
                print(
                    f"  {prefix}f={captured:3d}  yaw_actual={actual_yaw_rate_dps:5.1f}°/s"
                    f"  foe_conf={field.foe_confidence:.3f}"
                    f"  src={field.source:<8s}"
                    f"  occ_cen={field.sector_occupancy('centro'):.3f}"
                    f"  blocked={'SI' if field.is_blocked('centro') else 'no'}"
                )
            else:
                print(f"  [settling {frame_i+1}/{SETTLE_FRAMES}] yaw={cur_yaw_deg:.1f}°")

            prev_rgb   = rgb
            prev_telem = telem

            elapsed = time.time() - t0
            time.sleep(max(0.01, 0.2 - elapsed))   # ~5Hz

        print(f"  → {captured} frames capturados\n")

    # ── Guardar NPZ ──────────────────────────────────────────────────────────
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"d3_dataset_{ts}.npz"

    # field_source es string → object array
    str_arr = np.array(records["field_source"], dtype=object)
    numeric = {k: np.array(v, dtype=np.float32)
               for k, v in records.items() if k != "field_source"}
    np.savez_compressed(str(out_path), field_source=str_arr, **numeric)

    total = len(records["yaw_rate_target_radps"])
    print(f"\nDataset guardado: {out_path}")
    print(f"  {total} frames  |  {len(args.yaw_rates)} tasas de yaw")
    print(f"  Columnas: {list(records.keys())}")

    # ── Resumen por tasa ─────────────────────────────────────────────────────
    yaw_rates_arr    = np.array(records["yaw_rate_target_radps"])
    foe_conf_arr     = np.array(records["foe_confidence"])
    src_arr          = np.array(records["field_source"])
    blocked_arr      = np.array(records["is_blocked_centro"])

    print("\n── Resumen por yaw rate ──")
    print(f"  {'yaw(rad/s)':>10}  {'yaw(°/s)':>8}  {'foe_conf_mean':>13}  "
          f"{'foe_conf_min':>12}  {'src=flow%':>9}  {'blocked%':>8}")
    print(f"  {'-'*70}")
    for yr in args.yaw_rates:
        mask = np.abs(yaw_rates_arr - yr) < 0.01
        if not mask.any():
            continue
        fc   = foe_conf_arr[mask]
        srcs = src_arr[mask]
        blk  = blocked_arr[mask]
        pct_flow    = 100 * (srcs == "flow").sum() / len(srcs)
        pct_blocked = 100 * blk.mean()
        print(f"  {yr:>10.2f}  {degrees(yr):>8.1f}  {fc.mean():>13.4f}  "
              f"{fc.min():>12.4f}  {pct_flow:>9.1f}%  {pct_blocked:>8.1f}%")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido por usuario.")
