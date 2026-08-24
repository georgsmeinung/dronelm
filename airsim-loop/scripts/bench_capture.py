"""F0.0: mide el techo real de simGetImages/getMultirotorState sobre la

conexion real (Mac -> Windows u otro host remoto), para elegir LOOP_HZ y la
resolucion del pipeline de percepcion con evidencia en lugar de un default.

Uso:
    python scripts/bench_capture.py --samples 200

No requiere ningun cambio de codigo del lazo: se conecta directo con
AirSimClient. Requiere que AirSim este corriendo y sea alcanzable segun
AIRSIM_IP/AIRSIM_PORT en el .env.

Salida: tabla p50/p95 (ms) por combinacion de resolucion x con/sin depth,
en texto y como CSV en airsim-loop/scripts/bench_capture_results.csv.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from src.hardware.airsim_client import AirSimClient

RESOLUTIONS = [(1080, 720), (640, 480), (320, 240)]


def _percentile(values, pct):
    if not values:
        return float("nan")
    values = sorted(values)
    k = (len(values) - 1) * (pct / 100.0)
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def bench_one(client: AirSimClient, width: int, height: int, return_depth: bool, samples: int):
    client.frame_width = width
    client.frame_height = height

    timings = []
    for i in range(samples):
        t0 = time.time()
        client.capture(return_depth=return_depth)
        timings.append((time.time() - t0) * 1000.0)

    return {
        "width": width, "height": height, "return_depth": return_depth,
        "samples": len(timings),
        "p50_ms": round(_percentile(timings, 50), 1),
        "p95_ms": round(_percentile(timings, 95), 1),
        "max_ms": round(max(timings), 1) if timings else float("nan"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=200)
    args = parser.parse_args()

    client = AirSimClient()
    if not client.connect():
        print("[bench] No se pudo conectar a AirSim (revisar AIRSIM_IP/AIRSIM_PORT en .env). Abortando.")
        return

    results = []
    try:
        for width, height in RESOLUTIONS:
            for return_depth in (False, True):
                print(f"[bench] {width}x{height} depth={return_depth} ({args.samples} muestras)...")
                r = bench_one(client, width, height, return_depth, args.samples)
                if r:
                    results.append(r)
                    hz = 1000.0 / r["p95_ms"] if r["p95_ms"] else float("nan")
                    print(f"  p50={r['p50_ms']}ms p95={r['p95_ms']}ms max={r['max_ms']}ms -> Hz sostenible (p95) ~{hz:.2f}")
    finally:
        client.disconnect()

    out_csv = Path(__file__).resolve().parent / "bench_capture_results.csv"
    if results:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        print(f"\n[bench] Resultados guardados en {out_csv}")
    else:
        print("\n[bench] No se obtuvo ningun resultado: revisar conectividad con AirSim (AIRSIM_IP/AIRSIM_PORT en .env).")


if __name__ == "__main__":
    main()
