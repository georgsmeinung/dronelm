"""F1.3: recolecta un dataset TTC-estimado vs TTC-real (por canal depth) para

validar/calibrar FlowTTCEstimator. Requiere AirSim corriendo.

Cubre los 3 escenarios que pide el plan (a ejecutar por separado, moviendo al
dron manualmente o con un manifiesto simple antes de correr el script):
    (a) aproximacion frontal a un edificio
    (b) vuelo recto por un canon urbano
    (c) giros de yaw sin aproximacion (el caso que antes disparaba frenos falsos)

Uso:
    python experiments/collect_ttc_dataset.py --scenario approach --out runs/ttc/approach.jsonl --duration 30
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

import numpy as np

from src.hardware.airsim_client import AirSimClient
from src.perception.flow_ttc import FlowTTCEstimator
from src.perception.obstacle_field import BANDS, SECTORS


def _v_closing(telemetry: dict) -> float:
    """Componente de la velocidad del cuerpo sobre el eje optico (forward)."""
    vel = telemetry.get("velocity", {}) or {}
    # Aproximacion: en body frame ForwardOnly, vx ya es aproximadamente la
    # componente de avance frontal reportada por AirSim en NED. Se usa la
    # norma horizontal como proxy conservador de la velocidad de cierre.
    vx = float(vel.get("vx", 0.0))
    vy = float(vel.get("vy", 0.0))
    return (vx * vx + vy * vy) ** 0.5


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, choices=["approach", "canyon", "yaw_only"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--hz", type=float, default=5.0)
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = AirSimClient(loop_hz=args.hz)
    if not client.connect():
        print("[collect_ttc_dataset] No se pudo conectar a AirSim. Abortando.")
        return

    estimator = FlowTTCEstimator()
    prev_frame, prev_telem, prev_depth = None, None, None
    sleep_s = 1.0 / args.hz
    t_end = time.time() + args.duration

    n_written = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        while time.time() < t_end:
            t0 = time.time()
            frame, depth, telemetry = client.capture(return_depth=True)
            if frame is None or depth is None:
                time.sleep(sleep_s)
                continue

            field = estimator.estimate(frame, prev_frame, telemetry, prev_telem)

            if prev_telem is not None:
                dt = float(telemetry.get("timestamp", 0.0)) - float(prev_telem.get("timestamp", 0.0))
                v_closing = _v_closing(telemetry)
                orient = telemetry.get("orientation", {}) or {}
                prev_orient = prev_telem.get("orientation", {}) or {}
                yaw_rate = 0.0
                if dt > 1e-3:
                    dyaw = float(orient.get("yaw", 0.0)) - float(prev_orient.get("yaw", 0.0))
                    dyaw = (dyaw + np.pi) % (2 * np.pi) - np.pi
                    yaw_rate = dyaw / dt

                h, w = depth.shape[:2]
                col_edges = [0, w // 3, 2 * w // 3, w]
                row_edges = [0, h // 3, 2 * h // 3, h]
                for si, sector in enumerate(SECTORS):
                    for bi, band in enumerate(BANDS):
                        x0, x1 = col_edges[si], col_edges[si + 1]
                        y0, y1 = row_edges[bi], row_edges[bi + 1]
                        depth_cell = depth[y0:y1, x0:x1]
                        z = float(np.percentile(depth_cell, 20))
                        ttc_gt = z / max(v_closing, 1e-3)

                        cell = field.cells.get((sector, band))
                        record = {
                            "t": telemetry.get("timestamp"),
                            "scenario": args.scenario,
                            "sector": sector, "band": band,
                            "ttc_est_s": None if (cell is None or cell.ttc_s == float("inf")) else cell.ttc_s,
                            "ttc_gt_s": ttc_gt,
                            "divergence": cell.divergence if cell else None,
                            "occupancy": cell.occupancy if cell else None,
                            "confidence": cell.confidence if cell else 0.0,
                            "dt_s": dt,
                            "speed_mps": v_closing,
                            "yaw_rate_rad_s": yaw_rate,
                            "algorithm": "dis" if estimator._backend is not None else "farneback",
                        }
                        fh.write(json.dumps(record) + "\n")
                        n_written += 1

            prev_frame, prev_telem, prev_depth = frame, telemetry, depth
            elapsed = time.time() - t0
            time.sleep(max(0.0, sleep_s - elapsed))

    client.disconnect()
    print(f"[collect_ttc_dataset] {n_written} registros escritos en {out_path}")


if __name__ == "__main__":
    main()
