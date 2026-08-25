"""G4: Análisis de Resultados de Tesis.

Lee los JSONL de corridas y RESULTS_SUMMARY.json para generar tablas comparativas,
estadísticas por brazo, y métricas de desempeño.

Uso:
    python experiments/analyze_tesis_results.py runs/tesis/
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_summary(summary_path: str) -> List[Dict[str, Any]]:
    """Carga RESULTS_SUMMARY.json."""
    with open(summary_path, "r") as f:
        return json.load(f)


def analyze_by_arm(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Análisis agregado por brazo."""
    by_arm = defaultdict(list)
    for r in results:
        if r.get("success"):
            by_arm[r["arm"]].append(r)

    print("\n=== ANÁLISIS POR BRAZO ===\n")
    print(f"{'Brazo':<10} {'Corridas Éxito':<15} {'Ciclos Promedio':<15} {'Duración Promedio (s)':<20} {'Colisiones':<12}")
    print("-" * 75)

    arm_stats = {}
    for arm in sorted(by_arm.keys()):
        arm_results = by_arm[arm]
        n = len(arm_results)
        avg_cycles = statistics.mean(r.get("cycles", 0) for r in arm_results)
        avg_duration = statistics.mean(r.get("duration_s", 0) for r in arm_results)
        total_collisions = sum(r.get("collisions", 0) for r in arm_results)

        print(f"{arm:<10} {n:<15} {avg_cycles:>12.0f}        {avg_duration:>15.2f}        {total_collisions:>10}")

        arm_stats[arm] = {
            "n_success": n,
            "avg_cycles": avg_cycles,
            "avg_duration_s": avg_duration,
            "total_collisions": total_collisions,
            "avg_collisions": total_collisions / n if n > 0 else 0,
        }

    return arm_stats


def analyze_by_scenario(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Análisis agregado por escenario."""
    by_scenario = defaultdict(lambda: defaultdict(list))
    for r in results:
        if r.get("success"):
            by_scenario[r["scenario"]][r["arm"]].append(r)

    print("\n=== ANÁLISIS POR ESCENARIO ===\n")

    scenario_stats = {}
    for scenario in sorted(by_scenario.keys()):
        print(f"Escenario: {scenario}")
        print(f"  {'Brazo':<10} {'Corridas':<10} {'Ciclos Promedio':<15} {'Distancia (m)':<15}")
        print(f"  " + "-" * 50)

        scenario_stats[scenario] = {}
        for arm in sorted(by_scenario[scenario].keys()):
            arm_results = by_scenario[scenario][arm]
            n = len(arm_results)
            avg_cycles = statistics.mean(r.get("cycles", 0) for r in arm_results)
            avg_distance = statistics.mean(r.get("path_length_m", 0) for r in arm_results)

            print(f"  {arm:<10} {n:<10} {avg_cycles:>12.0f}        {avg_distance:>10.2f}")

            scenario_stats[scenario][arm] = {
                "n_success": n,
                "avg_cycles": avg_cycles,
                "avg_distance_m": avg_distance,
            }

        print()

    return scenario_stats


def success_rates(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Tasa de éxito por brazo."""
    by_arm = defaultdict(lambda: {"success": 0, "total": 0})
    for r in results:
        arm = r["arm"]
        by_arm[arm]["total"] += 1
        if r.get("success"):
            by_arm[arm]["success"] += 1

    print("\n=== TASA DE ÉXITO ===\n")
    rates = {}
    for arm in sorted(by_arm.keys()):
        total = by_arm[arm]["total"]
        success = by_arm[arm]["success"]
        rate = success / total * 100 if total > 0 else 0
        rates[arm] = rate
        print(f"{arm:<10}: {success}/{total} ({rate:>5.1f}%)")

    return rates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", help="Directorio con RESULTS_SUMMARY.json")
    args = parser.parse_args()

    results_path = Path(args.results_dir) / "RESULTS_SUMMARY.json"
    if not results_path.exists():
        print(f"Error: {results_path} no encontrado")
        sys.exit(1)

    results = load_summary(str(results_path))
    print(f"Cargados {len(results)} resultados de corridas\n")

    # Análisis
    rates = success_rates(results)
    arm_stats = analyze_by_arm(results)
    scenario_stats = analyze_by_scenario(results)

    # Guardar análisis
    analysis = {
        "total_runs": len(results),
        "success_rates": rates,
        "arm_stats": arm_stats,
        "scenario_stats": scenario_stats,
    }
    analysis_path = Path(args.results_dir) / "ANALYSIS.json"
    with open(analysis_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)

    print(f"\n✓ Análisis guardado en {analysis_path}")


if __name__ == "__main__":
    main()
