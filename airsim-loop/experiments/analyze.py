"""F3.3: agrega los summary.json de experiments/runner.py y produce la tabla

comparativa SLM vs FSM vs reactivo (objetivo especifico del plan de tesis).

Uso:
    python experiments/analyze.py runs/
    python experiments/analyze.py runs/ --missions-dir missions/
"""
from __future__ import annotations

import argparse
import glob
import json
import math
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


def load_optimal_lengths(missions_dir: str) -> dict:
    """Longitud optima por escenario: suma de distancias entre waypoints

    consecutivos del manifiesto (sin obstaculos, no es un camino real
    volable, pero es la referencia estandar para SPL). Clave = stem del
    archivo del manifiesto, que es el mismo "scenario" que usa runner.py.
    """
    lengths = {}
    for path in glob.glob(str(Path(missions_dir) / "*.json")):
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        wps = manifest.get("waypoints", [])
        total = 0.0
        for i in range(1, len(wps)):
            a, b = wps[i - 1], wps[i]
            total += math.dist(
                (a.get("x", 0.0), a.get("y", 0.0), a.get("z", 0.0)),
                (b.get("x", 0.0), b.get("y", 0.0), b.get("z", 0.0)),
            )
        lengths[Path(path).stem] = total
    return lengths


def spl(run: dict, optimal_lengths: dict) -> float:
    """Success weighted by Path Length (SPL), definicion estandar de

    navegacion (Anderson et al. 2018): 0 si la corrida no tuvo exito;
    L_optima / max(L_recorrida, L_optima) si lo tuvo. Penaliza tanto no
    llegar como llegar dando vueltas de mas. NaN si no hay manifiesto para
    el escenario de esta corrida.
    """
    l_opt = optimal_lengths.get(run.get("scenario"))
    if not l_opt:
        return float("nan")
    if not run.get("success"):
        return 0.0
    l_actual = max(float(run.get("path_length_m", 0.0)), 1e-6)
    return l_opt / max(l_actual, l_opt)


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
    parser = argparse.ArgumentParser()
    parser.add_argument("runs_dir", nargs="?", default="runs")
    parser.add_argument("--missions-dir", default="missions", help="para calcular SPL (F3.3)")
    args = parser.parse_args()

    rows = load_summaries(args.runs_dir)
    if not rows:
        print(f"Sin resumenes en {args.runs_dir}. Correr antes experiments/runner.py.")
        return

    optimal_lengths = load_optimal_lengths(args.missions_dir)

    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    print(f"{'Arm':<10} {'N':<4} {'Exito':<8} {'Colisiones/mision':<18} {'DistMin p5 (m)':<16} {'SPL':<8} {'SLM inv/mision':<14} {'Fallback%':<10} {'Timeout%':<10}")
    for arm, runs in sorted(by_arm.items()):
        n = len(runs)
        success_rate = sum(1 for r in runs if r.get("success")) / n
        collisions = np.mean([r.get("collisions", 0) for r in runs])
        min_dists = [r["min_obstacle_dist_m"] for r in runs if r.get("min_obstacle_dist_m") is not None]
        dist_p5 = np.percentile(min_dists, 5) if min_dists else float("nan")
        spl_values = [spl(r, optimal_lengths) for r in runs]
        spl_values = [v for v in spl_values if v == v]  # descarta NaN (escenario sin manifiesto)
        spl_str = f"{np.mean(spl_values):.2f}" if spl_values else "N/D"
        slm_inv = np.mean([r.get("slm_invocations") or 0 for r in runs])
        fb_rates = [r["slm_fallback_rate"] for r in runs if r.get("slm_fallback_rate") is not None]
        to_rates = [r["slm_timeout_rate"] for r in runs if r.get("slm_timeout_rate") is not None]
        fb_pct = f"{np.mean(fb_rates)*100:.0f}%" if fb_rates else "N/D"
        to_pct = f"{np.mean(to_rates)*100:.0f}%" if to_rates else "N/D"
        print(f"{arm:<10} {n:<4} {success_rate*100:>6.0f}% {collisions:<18.2f} {dist_p5:<16.2f} {spl_str:<8} {slm_inv:<14.1f} {fb_pct:<10} {to_pct:<10}")

    print("\nLatencia total por ciclo (ms), p50/p95, por (arma, ruta):")
    by_arm_route = load_cycles_for_latency(args.runs_dir)
    for (arm, route), lats in sorted(by_arm_route.items()):
        if not lats:
            continue
        p50, p95 = np.percentile(lats, 50), np.percentile(lats, 95)
        print(f"  {arm:<10} {route or '(vacio)':<14} N={len(lats):<6} p50={p50:.1f}ms p95={p95:.1f}ms")

    # H3.3 (PLAN-MEJORAS-3): tabla de resolucion de atascos desagregada por
    # AGENT_ARM x DEADLOCK_STRATEGY. deadlock_strategy default a "blind" para
    # corridas de antes de H3 (summary.json sin ese campo).
    by_arm_strategy = defaultdict(list)
    for r in rows:
        by_arm_strategy[(r["arm"], r.get("deadlock_strategy", "blind"))].append(r)
    if any(strategy == "deep_vlm" for _arm, strategy in by_arm_strategy):
        print(f"\n{'Arm':<10} {'Estrategia':<10} {'N':<4} {'Atascos':<9} {'Tasa resol. escaneo':<20} {'Ciclos prom. resol.':<20} {'Tasa fallback':<14}")
        for (arm, strategy), runs in sorted(by_arm_strategy.items()):
            n = len(runs)
            deadlock_events = sum(r.get("deadlock_events") or 0 for r in runs)
            res_rates = [r["deep_scan_resolution_rate"] for r in runs if r.get("deep_scan_resolution_rate") is not None]
            res_str = f"{np.mean(res_rates)*100:.0f}%" if res_rates else "N/D"
            cycles = [r["deep_scan_avg_cycles_to_resolve"] for r in runs if r.get("deep_scan_avg_cycles_to_resolve") is not None]
            cycles_str = f"{np.mean(cycles):.1f}" if cycles else "N/D"
            fb_rates = [r["deep_scan_fallback_rate"] for r in runs if r.get("deep_scan_fallback_rate") is not None]
            fb_str = f"{np.mean(fb_rates)*100:.0f}%" if fb_rates else "N/D"
            print(f"{arm:<10} {strategy:<10} {n:<4} {deadlock_events:<9} {res_str:<20} {cycles_str:<20} {fb_str:<14}")

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
