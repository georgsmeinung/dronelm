"""F3.3: agrega los summary.json de experiments/runner.py y produce la tabla

comparativa SLM vs FSM vs reactivo (objetivo especifico del plan de tesis).

Uso:
    python experiments/analyze.py runs/
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    from scipy.stats import mannwhitneyu
except Exception:
    mannwhitneyu = None


def load_summaries(runs_dir: str):
    rows = []
    for path in glob.glob(str(Path(runs_dir) / "**" / "*.summary.json"), recursive=True):
        with open(path, "r", encoding="utf-8") as f:
            rows.append(json.load(f))
    return rows


def load_cycles_for_latency(runs_dir: str):
    """Latencia p50/p95 por rama (keep_going/evasive/deliberative/fsm), agrupada por arm."""
    by_arm_route = defaultdict(list)
    for path in glob.glob(str(Path(runs_dir) / "**" / "*.jsonl"), recursive=True):
        if path.endswith(".summary.json"):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                key = (rec.get("arm"), rec.get("route"))
                lat = rec.get("latency_ms", {}) or {}
                total = sum(v for v in lat.values() if isinstance(v, (int, float)))
                by_arm_route[key].append(total)
    return by_arm_route


def main():
    runs_dir = sys.argv[1] if len(sys.argv) > 1 else "runs"
    rows = load_summaries(runs_dir)
    if not rows:
        print(f"Sin resumenes en {runs_dir}. Correr antes experiments/runner.py.")
        return

    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    print(f"{'Arm':<10} {'N':<4} {'Exito':<8} {'Colisiones/mision':<18} {'DistMin p5 (m)':<16} {'Long/Óptima':<12} {'SLM inv/mision':<14} {'Fallback%':<10} {'Timeout%':<10}")
    for arm, runs in sorted(by_arm.items()):
        n = len(runs)
        success_rate = sum(1 for r in runs if r.get("success")) / n
        collisions = np.mean([r.get("collisions", 0) for r in runs])
        min_dists = [r["min_obstacle_dist_m"] for r in runs if r.get("min_obstacle_dist_m") is not None]
        dist_p5 = np.percentile(min_dists, 5) if min_dists else float("nan")
        path_lengths = [r.get("path_length_m", 0.0) for r in runs]
        slm_inv = np.mean([r.get("slm_invocations") or 0 for r in runs])
        fb_rates = [r["slm_fallback_rate"] for r in runs if r.get("slm_fallback_rate") is not None]
        to_rates = [r["slm_timeout_rate"] for r in runs if r.get("slm_timeout_rate") is not None]
        fb_pct = f"{np.mean(fb_rates)*100:.0f}%" if fb_rates else "N/D"
        to_pct = f"{np.mean(to_rates)*100:.0f}%" if to_rates else "N/D"
        print(f"{arm:<10} {n:<4} {success_rate*100:>6.0f}% {collisions:<18.2f} {dist_p5:<16.2f} {'N/D':<12} {slm_inv:<14.1f} {fb_pct:<10} {to_pct:<10}")

    print("\nLatencia total por ciclo (ms), p50/p95, por (arma, ruta):")
    by_arm_route = load_cycles_for_latency(runs_dir)
    for (arm, route), lats in sorted(by_arm_route.items()):
        if not lats:
            continue
        p50, p95 = np.percentile(lats, 50), np.percentile(lats, 95)
        print(f"  {arm:<10} {route or '(vacio)':<14} N={len(lats):<6} p50={p50:.1f}ms p95={p95:.1f}ms")

    if mannwhitneyu is not None and "slm" in by_arm and "fsm" in by_arm:
        slm_success = [1 if r.get("success") else 0 for r in by_arm["slm"]]
        fsm_success = [1 if r.get("success") else 0 for r in by_arm["fsm"]]
        if len(set(slm_success)) > 1 or len(set(fsm_success)) > 1:
            stat, p = mannwhitneyu(slm_success, fsm_success, alternative="two-sided")
            print(f"\nMann-Whitney U (exito SLM vs FSM, por semilla): U={stat:.1f} p={p:.4f}")
    elif mannwhitneyu is None:
        print("\n(scipy no instalado: se omite el test de Mann-Whitney U entre brazos)")


if __name__ == "__main__":
    main()
