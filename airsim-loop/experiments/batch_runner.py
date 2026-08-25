"""G4: Corrida de Tesis - Batch runner para 3 brazos × 3 escenarios × N semillas.

Ejecuta un experimento factorial: cada combinación de brazo, escenario y semilla se
corre en un subproceso separado. Agrupa resultados por escenario para análisis.

Uso:
    python experiments/batch_runner.py \
        --scenarios missions/manhattan_a.json missions/manhattan_b.json missions/manhattan_c.json \
        --arms slm fsm reactive \
        --seeds 1 2 3 4 5 \
        --out-dir runs/tesis \
        --max-cycles 2000 \
        --max-seconds 300

Salida:
    runs/tesis/manhattan_a/{slm,fsm,reactive}/seed_*.jsonl
    runs/tesis/manhattan_b/{slm,fsm,reactive}/seed_*.jsonl
    runs/tesis/manhattan_c/{slm,fsm,reactive}/seed_*.jsonl
    runs/tesis/RESULTS_SUMMARY.json (tabla de resultados por combinación)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_experiment(
    scenario_path: str, arm: str, seed: int, out_dir: str, max_cycles: int, max_seconds: float
) -> tuple[bool, Dict[str, Any]]:
    """Ejecuta una corrida individual del runner.py en subproceso.

    Returns:
        (success, summary_dict)
    """
    # Detectar si estamos en Windows y usar el ejecutable del venv correctamente
    import platform
    project_root = Path(__file__).resolve().parent.parent
    if platform.system() == "Windows":
        python_exe = str(project_root / ".venv" / "Scripts" / "python.exe")
    else:
        python_exe = str(project_root / ".venv" / "bin" / "python")

    runner_path = str(Path(__file__).resolve().parent / "runner.py")
    cmd = [
        python_exe,
        runner_path,
        "--_single",
        "--scenario", scenario_path,
        "--arm", arm,
        "--seed", str(seed),
        "--out-dir", out_dir,
        "--max-cycles", str(max_cycles),
        "--max-seconds", str(max_seconds),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=max_seconds + 60.0)
        if result.returncode == 0:
            # Parsear el summary.json generado
            scenario_name = Path(scenario_path).stem
            summary_path = Path(out_dir) / scenario_name / arm / f"seed_{seed}.summary.json"
            if summary_path.exists():
                with open(summary_path, "r") as f:
                    summary = json.load(f)
                return True, summary
            return False, {"error": "No summary.json found"}
        else:
            return False, {"error": result.stderr or f"Exit code {result.returncode}"}
    except subprocess.TimeoutExpired:
        return False, {"error": "Timeout"}
    except Exception as e:
        return False, {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="G4: Corrida de Tesis")
    parser.add_argument("--scenarios", nargs="+", required=True)
    parser.add_argument("--arms", nargs="+", default=["slm", "fsm", "reactive"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument("--out-dir", default="runs/tesis")
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args()

    out_dir_path = Path(args.out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    print(f"[G4] Iniciando corrida de tesis")
    print(f"  Escenarios: {len(args.scenarios)}")
    print(f"  Brazos: {len(args.arms)} ({', '.join(args.arms)})")
    print(f"  Semillas: {len(args.seeds)} ({args.seeds[0]}-{args.seeds[-1]})")
    print(f"  Total: {len(args.scenarios) * len(args.arms) * len(args.seeds)} corridas")
    print()

    results = []
    total = len(args.scenarios) * len(args.arms) * len(args.seeds)
    current = 0

    for scenario_path in args.scenarios:
        for arm in args.arms:
            for seed in args.seeds:
                current += 1
                scenario_name = Path(scenario_path).stem
                print(f"[{current}/{total}] {scenario_name} × {arm} × seed={seed}...", end=" ", flush=True)

                t_start = time.time()
                success, summary = run_experiment(
                    scenario_path, arm, seed, args.out_dir, args.max_cycles, args.max_seconds
                )
                elapsed = time.time() - t_start

                if success:
                    print(f"✓ ({elapsed:.1f}s, cycles={summary.get('cycles', '?')}, success={summary.get('success', False)})")
                    results.append({
                        "scenario": scenario_name,
                        "arm": arm,
                        "seed": seed,
                        "success": success,
                        "elapsed_s": round(elapsed, 2),
                        **{k: v for k, v in summary.items() if k not in ["scenario", "seed", "arm"]},
                    })
                else:
                    print(f"✗ ({summary.get('error', 'Unknown error')})")
                    results.append({
                        "scenario": scenario_name,
                        "arm": arm,
                        "seed": seed,
                        "success": False,
                        "error": summary.get("error", "Unknown"),
                    })

    # Guardar resultados consolidados
    results_summary_path = out_dir_path / "RESULTS_SUMMARY.json"
    with open(results_summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print()
    print(f"[G4] Corrida completada. Resultados en {results_summary_path}")

    # Imprimir tabla de resultados
    print("\n=== TABLA DE RESULTADOS ===\n")
    print(f"{'Escenario':<15} {'Brazo':<10} {'Semillas Éxito':<15} {'Tasa Éxito':<12} {'Promedio Ciclos':<15}")
    print("-" * 70)

    for scenario in sorted(set(r["scenario"] for r in results)):
        for arm in args.arms:
            arm_results = [r for r in results if r["scenario"] == scenario and r["arm"] == arm]
            success_count = sum(1 for r in arm_results if r.get("success", False))
            avg_cycles = round(sum(r.get("cycles", 0) for r in arm_results if r.get("success")) / max(success_count, 1), 0)
            success_rate = success_count / len(arm_results) * 100 if arm_results else 0
            print(f"{scenario:<15} {arm:<10} {success_count}/{len(arm_results):<13} {success_rate:>5.1f}%        {avg_cycles:>6.0f} ciclos")


if __name__ == "__main__":
    main()
