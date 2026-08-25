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

from src.navigation.waypoint_tracker import GUIDANCE_SMOOTHING_ALPHA
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


SAFE_STOP_DIST_M = 4.0   # engancha el freno si el centro de la escena esta mas cerca que esto
SAFE_RESUME_DIST_M = 4.5  # solo vuelve a avanzar por encima de esto (histeresis, evita bang-bang)
YAW_ONLY_AMPLITUDE_RAD_S = 0.6
YAW_ONLY_PERIOD_S = 4.0


class ScriptedPilot:
    """Piloteo scripteado por escenario (F1.3: no requiere piloto manual).

    El freno de seguridad usa histeresis (engancha bajo SAFE_STOP_DIST_M,
    libera solo por encima de SAFE_RESUME_DIST_M) en lugar de un unico
    umbral: con un solo umbral, ruido de +-unos cm en la lectura de
    profundidad cerca del borde alterna vx entre forward_speed y 0 cada
    ciclo (bang-bang), lo que en el controlador de AirSim se ve como
    cabeceo (pitch) rapido -- el dron acelera y frena en seco 5 veces por
    segundo. Con dos umbrales, una vez que frena se queda frenado hasta
    alejarse con margen real.
    """

    def __init__(self) -> None:
        self.braking = False
        # Suavizado exponencial (EMA) del vx de approach/canyon: sin esto,
        # el toggle de self.braking (incluso con histeresis) sigue siendo un
        # salto instantaneo forward_speed<->0 que el controlador de AirSim
        # persigue como cabeceo. Mismo alpha que WaypointTracker
        # (GUIDANCE_SMOOTHING_ALPHA), por consistencia. No se aplica al
        # yaw_rate de yaw_only: ese ya es una senoidal continua por
        # construccion, no tiene el salto discontinuo que el EMA ataca.
        self._smoothed_vx: float | None = None

    def command(self, scenario: str, forward_speed: float, t_elapsed: float, min_center_depth: float) -> tuple:
        """Devuelve (vx, vy, vz, yaw_rate) en marco Body Frame."""
        if scenario == "yaw_only":
            import math

            yaw_rate = YAW_ONLY_AMPLITUDE_RAD_S * math.sin(2 * math.pi * t_elapsed / YAW_ONLY_PERIOD_S)
            return 0.0, 0.0, 0.0, yaw_rate

        # approach / canyon: avance recto constante, con freno de seguridad con histeresis.
        if not self.braking and min_center_depth < SAFE_STOP_DIST_M:
            self.braking = True
        elif self.braking and min_center_depth > SAFE_RESUME_DIST_M:
            self.braking = False

        target_vx = 0.0 if self.braking else forward_speed
        if self._smoothed_vx is None:
            self._smoothed_vx = target_vx
        else:
            self._smoothed_vx = GUIDANCE_SMOOTHING_ALPHA * target_vx + (1.0 - GUIDANCE_SMOOTHING_ALPHA) * self._smoothed_vx
        return self._smoothed_vx, 0.0, 0.0, 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, choices=["approach", "canyon", "yaw_only"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--hz", type=float, default=5.0)
    parser.add_argument("--forward-speed", type=float, default=3.0, help="m/s en approach/canyon")
    parser.add_argument("--no-pilot", action="store_true", help="no comandar el dron (piloteo manual externo)")
    parser.add_argument("--start-pose", type=float, nargs=4, default=None, metavar=("X", "Y", "Z", "YAW_DEG"),
                         help="teletransporta el dron antes de empezar, p.ej. para ubicarlo en un canon urbano")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = AirSimClient(loop_hz=args.hz)
    if not client.connect():
        print("[collect_ttc_dataset] No se pudo conectar a AirSim. Abortando.")
        return
    # Limpia colision/velocidad/estado del controlador interno que pudiera
    # haber quedado de una invocacion anterior del script en el mismo
    # proceso de AirSim (los 3 escenarios se corren como invocaciones
    # separadas contra el mismo simulador de larga duracion).
    client.reset()

    if args.start_pose is not None:
        x, y, z, yaw_deg = args.start_pose
        client.set_vehicle_pose(x, y, z, yaw_deg=yaw_deg)

    estimator = FlowTTCEstimator()
    pilot = ScriptedPilot()
    prev_frame, prev_telem, prev_depth = None, None, None
    sleep_s = 1.0 / args.hz
    t_start = time.time()
    t_end = t_start + args.duration

    n_written = 0
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            while time.time() < t_end:
                t0 = time.time()
                frame, depth, telemetry = client.capture(return_depth=True)
                if frame is None or depth is None:
                    time.sleep(sleep_s)
                    continue

                if not args.no_pilot:
                    h, w = depth.shape[:2]
                    center = depth[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
                    min_center_depth = float(np.percentile(center, 5)) if center.size else float("inf")
                    vx, vy, vz, yaw_rate = pilot.command(
                        args.scenario, args.forward_speed, t0 - t_start, min_center_depth
                    )
                    client.execute_velocity(vx, vy, vz, yaw_rate=yaw_rate)

                field = estimator.estimate(frame, prev_frame, telemetry, prev_telem)

                if prev_telem is not None:
                    dt = float(telemetry.get("timestamp", 0.0)) - float(prev_telem.get("timestamp", 0.0))
                    v_closing = _v_closing(telemetry)
                    orient = telemetry.get("orientation", {}) or {}
                    prev_orient = prev_telem.get("orientation", {}) or {}
                    yaw_rate_meas = 0.0
                    if dt > 1e-3:
                        dyaw = float(orient.get("yaw", 0.0)) - float(prev_orient.get("yaw", 0.0))
                        dyaw = (dyaw + np.pi) % (2 * np.pi) - np.pi
                        yaw_rate_meas = dyaw / dt

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
                                "yaw_rate_rad_s": yaw_rate_meas,
                                "algorithm": "dis" if estimator._backend is not None else "farneback",
                            }
                            fh.write(json.dumps(record) + "\n")
                            n_written += 1

                prev_frame, prev_telem, prev_depth = frame, telemetry, depth
                elapsed = time.time() - t0
                time.sleep(max(0.0, sleep_s - elapsed))
    finally:
        if not args.no_pilot:
            try:
                client.execute_velocity(0.0, 0.0, 0.0, yaw_rate=0.0)
                time.sleep(0.5)
            except Exception:
                pass
        client.land()
        client.disconnect()

    print(f"[collect_ttc_dataset] {n_written} registros escritos en {out_path}")


if __name__ == "__main__":
    main()
