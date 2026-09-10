#!/usr/bin/env python
"""
D2 — Captura del dataset para calibración ROC del canal de ocupación.
PLAN-DEUDA-TECNICA.md, Fase D2.

El dron realiza aproximaciones controladas a una pared en TownSim,
capturando pares (RGB + DepthPlanar) + ObstacleField en cada ciclo.
El dataset se guarda como .npz para análisis offline (notebook ROC).

IMPORTANTE — coordenadas: los defectos son un punto de partida, no garantizan
zona libre de árboles. Verificar en AirSim que el tramo start→wall esté
despejado antes de lanzar. Usar --start-x/y/z y --wall-x/y para ajustar.

Uso:
    cd callibration-flight
    python d2_occupancy_capture.py --start-x X --start-y Y --wall-x WX --wall-y WY
    python d2_occupancy_capture.py --speeds 0.5 1.0 --output-dir d2_dataset
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
from dotenv import load_dotenv

# ── Acceso a airsim-loop desde callibration-flight ──────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "airsim-loop"))

import cosysairsim as airsim  # type: ignore
from src.hardware.airsim_client import _state_to_telemetry, _quaternion_to_euler  # noqa: PLC2701
from src.perception.flow_ttc import FlowTTCEstimator
from src.perception.obstacle_field import BANDS, SECTORS

load_dotenv(_REPO_ROOT / "config" / ".env")

# ── Parámetros de entorno ────────────────────────────────────────────────────
LOOP_HZ    = float(os.getenv("LOOP_HZ", "5.0"))
FRAME_W    = int(os.getenv("DEFAULT_FRAME_WIDTH", "1080"))
FRAME_H    = int(os.getenv("DEFAULT_FRAME_HEIGHT", "720"))
CAMERA_ID  = int(os.getenv("AIRSIM_CAMERA_NAME", "0"))
VEHICLE    = os.getenv("AIRSIM_VEHICLE_NAME", "SimpleFlight")
AIRSIM_IP  = os.getenv("AIRSIM_IP", "127.0.0.1")
AIRSIM_PORT = int(os.getenv("AIRSIM_PORT", "41451"))

# Duración del comando de velocidad por pase (s); mayor que el tiempo máximo
# de cada aproximación (15 m / 0.5 m/s = 30 s) con margen amplio.
CMD_DURATION_S = 120.0

# Timeout máximo por pase: si en este tiempo no se alcanza min_dist
# (p.ej. el dron chocó con un árbol y quedó atascado), se aborta y
# se pasa a la siguiente velocidad sin perder los frames ya capturados.
MAX_PASS_TIME_S = 60.0

# Defectos — AJUSTAR según el tramo despejado que verifiques en AirSim.
# Los defectos anteriores (x=-120) caían en la zona arbolada de TownSim.
# Dejar en None para que el script pida las coordenadas si no se pasan por CLI.
DEFAULT_START_X = None
DEFAULT_START_Y = None
DEFAULT_START_Z =  -10.0
DEFAULT_WALL_X  = None
DEFAULT_WALL_Y  = None
DEFAULT_SPEEDS  = [0.5, 1.0, 2.0, 3.0]
DEFAULT_MIN_DIST = 2.0      # m — distancia a la pared para terminar el pase


# ── Argumentos ────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--start-x", type=float, default=DEFAULT_START_X, required=DEFAULT_START_X is None,
                   help="Coordenada X de inicio (NED, m). REQUERIDO si no hay defecto.")
    p.add_argument("--start-y", type=float, default=DEFAULT_START_Y, required=DEFAULT_START_Y is None,
                   help="Coordenada Y de inicio (NED, m). REQUERIDO si no hay defecto.")
    p.add_argument("--start-z", type=float, default=DEFAULT_START_Z,
                   help=f"Coordenada Z de inicio (NED, m). Defecto: {DEFAULT_START_Z}")
    p.add_argument("--wall-x",  type=float, default=DEFAULT_WALL_X, required=DEFAULT_WALL_X is None,
                   help="Coordenada X de la pared (NED, m). REQUERIDO si no hay defecto.")
    p.add_argument("--wall-y",  type=float, default=DEFAULT_WALL_Y, required=DEFAULT_WALL_Y is None,
                   help="Coordenada Y de la pared (NED, m). REQUERIDO si no hay defecto.")
    p.add_argument("--speeds", type=float, nargs="+", default=DEFAULT_SPEEDS, metavar="V",
                   help="Velocidades de aproximación en m/s.")
    p.add_argument("--min-dist", type=float, default=DEFAULT_MIN_DIST,
                   help="Distancia (m) a la pared para terminar cada pase.")
    p.add_argument("--output-dir", default="d2_dataset",
                   help="Directorio de salida para el .npz.")
    return p.parse_args()


# ── Utilidades de imagen ──────────────────────────────────────────────────────
def _depth_type():
    return getattr(airsim.ImageType, "DepthPlanar",
                   getattr(airsim.ImageType, "DepthPlanner", None))


def _decode_rgb(resp) -> Optional[np.ndarray]:
    if resp is None or resp.width == 0:
        return None
    raw = np.frombuffer(resp.image_data_uint8, dtype=np.uint8)
    img = raw.reshape(resp.height, resp.width, 3)
    return img[..., ::-1].copy()  # BGR → RGB


def _decode_depth(resp, tgt_h: int, tgt_w: int) -> Optional[np.ndarray]:
    if resp is None or resp.width == 0:
        return None
    depth = np.array(resp.image_data_float, dtype=np.float32).reshape(resp.height, resp.width)
    if depth.shape != (tgt_h, tgt_w):
        try:
            import cv2
            depth = cv2.resize(depth, (tgt_w, tgt_h), interpolation=cv2.INTER_NEAREST)
        except Exception:
            pass
    return depth


def _depth_zones(depth: Optional[np.ndarray], h: int, w: int) -> Dict[str, float]:
    """Media del depth map colapsada por sector (tres columnas de la imagen)."""
    sector_cols = {
        "izquierda": (0, w // 3),
        "centro":    (w // 3, 2 * w // 3),
        "derecha":   (2 * w // 3, w),
    }
    result: Dict[str, float] = {}
    for s, (c0, c1) in sector_cols.items():
        if depth is None:
            result[s] = float("inf")
            continue
        zone = depth[:, c0:c1]
        valid = zone[np.isfinite(zone) & (zone > 0)]
        result[s] = float(np.mean(valid)) if valid.size > 0 else float("inf")
    return result


# ── Orientación hacia la pared ────────────────────────────────────────────────
def _yaw_toward(dx: float, dy: float) -> float:
    """Yaw NED (rad) para apuntar la proa del dron hacia el vector (dx, dy)."""
    return math.atan2(dy, dx)


def _yaw_quaternion(yaw: float) -> airsim.Quaternionr:
    """Cuaternión de rotación pura sobre eje Z (yaw en NED)."""
    return airsim.Quaternionr(
        x_val=0.0,
        y_val=0.0,
        z_val=math.sin(yaw / 2.0),
        w_val=math.cos(yaw / 2.0),
    )


# ── Pase de aproximación ──────────────────────────────────────────────────────
def run_approach(
    client,
    estimator: FlowTTCEstimator,
    speed: float,
    start_x: float, start_y: float, start_z: float,
    wall_x: float,  wall_y: float,
    min_dist: float,
) -> List[Dict[str, Any]]:
    """Ejecuta un pase, devuelve lista de registros por frame."""
    records: List[Dict[str, Any]] = []

    # Orientación: el dron mira hacia la pared antes de volar
    dx = wall_x - start_x
    dy = wall_y - start_y
    yaw = _yaw_toward(dx, dy)
    q   = _yaw_quaternion(yaw)

    # Teleport + orientar
    pose = airsim.Pose(airsim.Vector3r(start_x, start_y, start_z), q)
    client.simSetVehiclePose(pose, ignore_collision=True, vehicle_name=VEHICLE)
    time.sleep(1.5)
    client.hoverAsync(vehicle_name=VEHICLE).join()

    # Comando de velocidad constante en frame del cuerpo:
    # vx = speed (frente = hacia la pared), vy = vz = 0.
    client.moveByVelocityBodyFrameAsync(
        speed, 0.0, 0.0,
        duration=CMD_DURATION_S,
        drivetrain=airsim.DrivetrainType.MaxDegreeOfFreedom,
        yaw_mode=airsim.YawMode(is_rate=False, yaw_or_rate=math.degrees(yaw)),
        vehicle_name=VEHICLE,
    )

    loop_dt = 1.0 / LOOP_HZ
    prev_rgb:   Optional[np.ndarray] = None
    prev_telem: Optional[Dict]       = None
    depth_img_type = _depth_type()
    t_pass_start = time.time()

    print(f"  V={speed} m/s | yaw={math.degrees(yaw):.1f}° | "
          f"inicio=({start_x},{start_y},{start_z}) → pared=({wall_x},{wall_y})"
          f" | timeout={MAX_PASS_TIME_S}s")

    try:
        while True:
            t0 = time.time()

            # ── Timeout por pase ─────────────────────────────────────────────
            if t0 - t_pass_start > MAX_PASS_TIME_S:
                print(f"  TIMEOUT ({MAX_PASS_TIME_S}s). Abortando pase.")
                break

            # ── Captura ──────────────────────────────────────────────────────
            responses = client.simGetImages(
                [
                    airsim.ImageRequest(CAMERA_ID, airsim.ImageType.Scene, False, False),
                    airsim.ImageRequest(CAMERA_ID, depth_img_type, True, False),
                ],
                vehicle_name=VEHICLE,
            )

            state = client.getMultirotorState(vehicle_name=VEHICLE)
            pos   = state.kinematics_estimated.position
            dist  = math.sqrt((pos.x_val - wall_x) ** 2 + (pos.y_val - wall_y) ** 2)

            # ── Detección de colisión ────────────────────────────────────────
            collision = getattr(state, "collision", None)
            if collision is not None and getattr(collision, "has_collided", False):
                obj = getattr(collision, "object_name", "?")
                print(f"  COLISIÓN con '{obj}'. Abortando pase ({len(records)} frames guardados).")
                break

            rgb    = _decode_rgb(responses[0] if responses else None)
            depth  = _decode_depth(responses[1] if len(responses) > 1 else None, FRAME_H, FRAME_W)
            telem  = _state_to_telemetry(state)

            # ── ObstacleField (flujo óptico, necesita par de frames) ─────────
            field      = estimator.estimate(rgb, prev_rgb, telem, prev_telem)
            field_dict = field.to_dict()

            # ── Ground truth por sector desde DepthPlanar ────────────────────
            gt_depth = _depth_zones(depth, FRAME_H, FRAME_W)

            records.append({
                "timestamp":           t0,
                "approach_speed_mps":  speed,
                "dist_to_wall_m":      dist,
                "pos_x": pos.x_val, "pos_y": pos.y_val, "pos_z": pos.z_val,
                "field_source":         field_dict["source"],
                "field_min_ttc_s":      field_dict.get("min_ttc_s") or float("nan"),
                "field_blocked_frac":   field_dict["blocked_fraction"],
                # Por sector: datos de percepción y ground truth
                **{f"occ_{s}":     field_dict["sectors"][s]["occupancy"]    for s in SECTORS},
                **{f"conf_{s}":    field_dict["sectors"][s]["confidence"]   for s in SECTORS},
                **{f"ttc_s_{s}":   field_dict["sectors"][s].get("ttc_s") or float("nan") for s in SECTORS},
                **{f"pred_blocked_{s}": field_dict["sectors"][s]["blocked"] for s in SECTORS},
                **{f"gt_depth_{s}": gt_depth[s]                             for s in SECTORS},
            })

            print(
                f"    dist={dist:5.1f}m  occ_cen={records[-1]['occ_centro']:.3f}"
                f"  conf_cen={records[-1]['conf_centro']:.3f}"
                f"  gt_depth_cen={records[-1]['gt_depth_centro']:6.1f}m"
                f"  src={field_dict['source']}"
            )

            prev_rgb   = rgb
            prev_telem = telem

            if dist < min_dist:
                print(f"  Distancia mínima alcanzada ({dist:.1f} m). Fin del pase.")
                break

            elapsed = time.time() - t0
            time.sleep(max(0.01, loop_dt - elapsed))

    except KeyboardInterrupt:
        print("\n  Interrumpido por el usuario.")
    finally:
        try:
            client.hoverAsync(vehicle_name=VEHICLE).join()
        except Exception:
            pass

    return records


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    args = _parse_args()

    client = airsim.MultirotorClient(ip=AIRSIM_IP, port=AIRSIM_PORT)
    client.confirmConnection()
    print(f"Conectado a AirSim en {AIRSIM_IP}:{AIRSIM_PORT}")

    client.enableApiControl(True, vehicle_name=VEHICLE)
    client.armDisarm(True, vehicle_name=VEHICLE)
    client.takeoffAsync(vehicle_name=VEHICLE).join()

    estimator   = FlowTTCEstimator()
    all_records: List[Dict[str, Any]] = []

    print(f"\nPared objetivo: ({args.wall_x}, {args.wall_y})")
    print(f"Velocidades: {args.speeds} m/s\n")

    for speed in args.speeds:
        print(f"\n{'='*60}")
        print(f"=== Pase a {speed} m/s ===")
        print(f"{'='*60}")
        try:
            records = run_approach(
                client=client,
                estimator=estimator,
                speed=speed,
                start_x=args.start_x,
                start_y=args.start_y,
                start_z=args.start_z,
                wall_x=args.wall_x,
                wall_y=args.wall_y,
                min_dist=args.min_dist,
            )
            all_records.extend(records)
            print(f"  {len(records)} frames capturados en este pase.")
        except Exception as exc:
            print(f"  ERROR en pase {speed} m/s: {exc}")
        time.sleep(2.0)

    # ── Guardar dataset ───────────────────────────────────────────────────────
    if not all_records:
        print("\nSin datos capturados. Saliendo.")
        return

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"d2_dataset_{ts}.npz"

    # Convertir a arrays numpy (object array para NaN/inf compatibles con np.savez)
    keys   = list(all_records[0].keys())
    arrays = {}
    for k in keys:
        col = [r[k] for r in all_records]
        try:
            arrays[k] = np.array(col, dtype=np.float64)
        except (ValueError, TypeError):
            arrays[k] = np.array(col, dtype=object)

    # Metadata del experimento como atributos del .npz
    arrays["_speeds"]    = np.array(args.speeds)
    arrays["_wall_pos"]  = np.array([args.wall_x, args.wall_y])
    arrays["_start_pos"] = np.array([args.start_x, args.start_y, args.start_z])

    np.savez_compressed(str(out_path), **arrays)
    print(f"\n{'='*60}")
    print(f"Dataset guardado: {out_path}")
    print(f"  {len(all_records)} frames  |  {len(args.speeds)} velocidades")
    print(f"  Columnas: {list(keys)}")

    try:
        client.armDisarm(False, vehicle_name=VEHICLE)
    except Exception:
        pass


if __name__ == "__main__":
    main()
