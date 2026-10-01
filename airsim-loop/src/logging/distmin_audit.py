# Auditoria de la distancia minima a obstaculos (DistMin), 2026-0930.
#
# El lazo de vuelo (main.py, experiments/runner.py, src/agents, src/perception, src/navigation)
# NUNCA lee el canal de profundidad del simulador (tests/test_no_depth_in_flight_path.py). DistMin
# la mide un HILO AISLADO, con su propia conexion RPC a AirSim, que muestrea DepthPlanar de la camara
# frontal cada DISTMIN_TRACK_PERIOD_S y escribe cada muestra en `<stem>.distmin.ndjson`. El hilo no
# comparte ningun objeto con el grafo ni con el DroneState: no hay camino por el que una muestra
# vuelva al control. finalize_run() consolida el archivo en el summary.json al cerrar la corrida.
#
# Definicion (identica a la del lote base, G3.1): percentil 5 del tercio central de la imagen de
# profundidad; la corrida reporta el minimo de las muestras.
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

DISTMIN_TRACK_ENABLED = os.getenv("DISTMIN_TRACK_ENABLED", "true").lower() == "true"
# 1 s = una muestra cada 5 ciclos a 5 Hz, el mismo muestreo que la medicion del lote base.
DISTMIN_TRACK_PERIOD_S = float(os.getenv("DISTMIN_TRACK_PERIOD_S", "1.0"))

SOURCE = "in_flight_thread"


def central_p5(depth: Optional[np.ndarray]) -> Optional[float]:
    """Percentil 5 del tercio central de una imagen de profundidad (m). None si no hay datos validos."""
    if depth is None or depth.ndim != 2 or depth.size == 0:
        return None
    h, w = depth.shape
    center = depth[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
    center = center[np.isfinite(center) & (center > 0.0)]
    if center.size == 0:
        return None
    return float(np.percentile(center, 5))


def samples_path(jsonl_path: Path) -> Path:
    return jsonl_path.with_name(jsonl_path.stem + ".distmin.ndjson")


class DistMinTracker(threading.Thread):
    """Hilo de auditoria: conexion RPC propia, solo escribe en `<stem>.distmin.ndjson`."""

    def __init__(self, run_jsonl_path: Path, ip: str, port: int, vehicle_name: str, camera_name: str,
                 period_s: float = DISTMIN_TRACK_PERIOD_S, timeout_s: float = 8.0) -> None:
        super().__init__(name="distmin-tracker", daemon=True)
        self._out = samples_path(Path(run_jsonl_path))
        self._ip, self._port, self._timeout = ip, int(port), timeout_s
        self._vehicle = vehicle_name
        self._camera = int(camera_name) if str(camera_name).isdigit() else camera_name
        self._period = max(0.2, float(period_s))
        self._stop_evt = threading.Event()
        self.n_samples = 0
        self.n_errors = 0

    def stop(self, timeout_s: float = 10.0) -> None:
        self._stop_evt.set()
        self.join(timeout=timeout_s)

    def run(self) -> None:
        try:
            # El cliente se crea DENTRO del hilo: msgpack-rpc usa un event loop por cliente y no es
            # seguro compartirlo con el cliente del lazo.
            from src.hardware.airsim_client import airsim  # type: ignore

            rpc = airsim.MultirotorClient(ip=self._ip, port=self._port, timeout_value=int(self._timeout))
            rpc.confirmConnection()
            depth_type = getattr(airsim.ImageType, "DepthPlanar", getattr(airsim.ImageType, "DepthPlanner", None))
            request = airsim.ImageRequest(self._camera, depth_type, True, False)
        except Exception as exc:
            print(f"[distmin] hilo sin conexion a AirSim: {exc}")
            return
        with open(self._out, "a", encoding="utf-8") as fh:
            while not self._stop_evt.is_set():
                t0 = time.time()
                try:
                    resp = rpc.simGetImages([request], vehicle_name=self._vehicle)
                    r = resp[0] if resp else None
                    d = None
                    if r is not None and r.width > 0 and r.height > 0:
                        d = central_p5(np.array(r.image_data_float, dtype=np.float32).reshape(r.height, r.width))
                    if d is not None:
                        cp = r.camera_position
                        fh.write(json.dumps({"t": round(t0, 3), "dist_m": round(d, 3),
                                             "x": round(cp.x_val, 2), "y": round(cp.y_val, 2),
                                             "z": round(cp.z_val, 2)}) + "\n")
                        fh.flush()
                        self.n_samples += 1
                except Exception:
                    self.n_errors += 1
                self._stop_evt.wait(max(0.0, self._period - (time.time() - t0)))


def start_tracker(run_jsonl_path: Path, client: Any) -> Optional[DistMinTracker]:
    """Arranca el hilo con los datos de conexion del cliente del lazo (no comparte el cliente)."""
    if not DISTMIN_TRACK_ENABLED or getattr(client, "_client", None) is None:
        return None
    tracker = DistMinTracker(run_jsonl_path, client.ip, client.port, client.vehicle_name, client.camera_name,
                             timeout_s=getattr(client, "timeout_seconds", 8.0))
    tracker.start()
    return tracker


def _read_samples(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    break  # ultima linea truncada por un corte
    except OSError:
        pass
    return out


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    dists = [float(s["dist_m"]) for s in samples if s.get("dist_m") is not None]
    i = int(np.argmin(dists)) if dists else None
    return {
        "min_obstacle_dist_m": dists[i] if dists else None,
        "min_obstacle_dist_t": samples[i]["t"] if dists else None,
        "min_obstacle_dist_source": SOURCE,
        "min_obstacle_dist_samples": len(dists),
    }


def distmin_done(summary_path: Path) -> bool:
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return summary.get("min_obstacle_dist_source") == SOURCE


def consolidate(run_jsonl_path: Path, force: bool = False) -> Optional[Dict[str, Any]]:
    """Vuelca `<stem>.distmin.ndjson` en `<stem>.summary.json`. None si no hay muestras o ya estaba."""
    run_jsonl_path = Path(run_jsonl_path)
    summary_path = run_jsonl_path.with_name(run_jsonl_path.stem + ".summary.json")
    if not force and distmin_done(summary_path):
        return None
    samples = _read_samples(samples_path(run_jsonl_path))
    if not samples:
        return None
    result = summarize(samples)
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = {}
    summary.update(result)
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return result
