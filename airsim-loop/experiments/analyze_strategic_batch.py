"""Analisis del lote de fuentes de la capa estrategica (depth | vlm | off), 2026-10-08.

Pregunta: aporta la capa estrategica al avance de la mision, y cual fuente aporta mas? Celdas
`<out-dir>/<escenario>/<brazo>/strat_<fuente>__<deadlock>/seed_*` (experiments/runner.py
--strategic-sources).

Avance = waypoints DEL PLAN completados (el plan de ruta del escenario, `<out-dir>/<escenario>/route_plan/`).
No se usa `wp_index` del registro: cuenta tambien las sub-metas insertadas; y `summary_by_wp.csv` repite
etiquetas al insertar una sub-meta. Se toma, para cada corrida, el punto mas lejano del plan completado y el
tiempo en que se completo.

Regla de decision (fijada antes de correr el lote; ver CHANGELOG 2026-10-08 f):
  - Una fuente A "aporta mas" que B si la mediana del avance a T_REF segundos supera a la de B en al menos
    MIN_DIFF_WP waypoints del plan Y A supera a B en al menos MIN_SEEDS_WIN de las semillas emparejadas
    (misma semilla = mismo jitter de arranque).
  - Si ninguna diferencia cumple la regla, las fuentes se consideran equivalentes en avance y se decide por
    costo (latencia, VRAM) y seguridad (colisiones, DistMin).
  - El p-valor (Wilcoxon emparejado / Mann-Whitney) se informa como diagnostico: con 5 semillas el Wilcoxon
    exacto no puede bajar de 0.0625.

Uso:
    python experiments/analyze_strategic_batch.py --out-dir ../airsim-runs/lote_estrategico
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

T_REF_S = 400.0
T_MARKS_S = (150.0, 300.0, 400.0)
MIN_DIFF_WP = 2
MIN_SEEDS_WIN = 4
CELL_RE = re.compile(r"strat_(?P<src>[a-z]+)__(?P<dl>[a-z_]+)$")


def plan_labels(out_dir: Path, scenario: str) -> List[str]:
    p = out_dir / scenario / "route_plan" / f"{scenario}.json"
    return [w["label"] for w in json.loads(p.read_text(encoding="utf-8"))["waypoints"]]


def plan_progress(run_dir: Path, plan: List[str]) -> Dict[float, int]:
    """{t_completado: n} con n = waypoints del plan completados (el mas lejano) en cada momento."""
    p = next(run_dir.glob("*.summary_by_wp.csv"), None)
    if p is None:
        return {}
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    t, best, out = 0.0, -1, {}
    for i, r in enumerate(rows):
        t += float(r["duration_s"])
        if i < len(rows) - 1 and r["wp_label"] in plan:   # la ultima fila es el objetivo en curso
            k = plan.index(r["wp_label"])
            if k > best:
                best = k
                out[t] = k + 1
    return out


def reached_at(progress: Dict[float, int], t: float) -> int:
    return max([n for tt, n in progress.items() if tt <= t], default=0)


def strategic_latency_ms(run_dir: Path) -> Optional[float]:
    con = next(run_dir.glob("*.console.log"), None)
    if con is None:
        return None
    lat = [float(x) for x in re.findall(r"_strategic\] sub-meta .*?\[latencia (\d+) ms\]",
                                         con.read_text(encoding="utf-8", errors="ignore"))]
    return float(np.median(lat)) if lat else None


def collect(out_dir: Path) -> List[Dict[str, Any]]:
    runs = []
    for summ in sorted(out_dir.glob("*/*/strat_*__*/seed_*/*.summary.json")):
        run_dir = summ.parent
        cell = run_dir.parent.name
        m = CELL_RE.match(cell)
        scenario = run_dir.parents[2].name
        s = json.loads(summ.read_text(encoding="utf-8"))
        plan = plan_labels(out_dir, scenario)
        prog = plan_progress(run_dir, plan)
        runs.append({
            "scenario": scenario, "arm": run_dir.parents[1].name, "source": m["src"], "deadlock": m["dl"],
            "seed": int(s.get("seed", -1)), "run": run_dir.name, "plan_len": len(plan),
            "duration_s": s.get("duration_s"), "success": bool(s.get("success")), "collisions": s.get("collisions"),
            "dist_min_m": s.get("min_obstacle_dist_m"), "deadlocks": s.get("deadlock_events"),
            "path_m": s.get("path_length_m"), "lat_ms": strategic_latency_ms(run_dir),
            **{f"wp@{int(t)}": reached_at(prog, t) for t in T_MARKS_S},
            "wp_final": max(prog.values(), default=0),
        })
    return runs


def _pvalues(a: List[float], b: List[float], paired: bool) -> str:
    try:
        from scipy.stats import mannwhitneyu, wilcoxon
    except ImportError:
        return "scipy no disponible"
    out = []
    try:
        out.append(f"Mann-Whitney p={mannwhitneyu(a, b, alternative='two-sided').pvalue:.3f}")
    except ValueError:
        pass
    if paired and len(a) == len(b) and any(x != y for x, y in zip(a, b)):
        try:
            out.append(f"Wilcoxon emparejado p={wilcoxon(a, b).pvalue:.3f}")
        except ValueError:
            pass
    return ", ".join(out) or "-"


def report(runs: List[Dict[str, Any]]) -> str:
    key = f"wp@{int(T_REF_S)}"
    lines = []
    for scenario in sorted({r["scenario"] for r in runs}):
        rs = [r for r in runs if r["scenario"] == scenario]
        plan_len = rs[0]["plan_len"]
        by = defaultdict(list)
        for r in rs:
            by[r["source"]].append(r)
        lines += [f"## {scenario} (plan de {plan_len} waypoints)", "",
                  "| Fuente | n | Plan a 150 / 300 / 400 s (mediana) | Final (mediana) | Exito | Colisiones | "
                  "DistMin mediana | Deadlocks (mediana) | Latencia capa |", "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
        for src in sorted(by):
            g = by[src]
            med = lambda k: float(np.median([r[k] for r in g if r[k] is not None])) if any(r[k] is not None for r in g) else float("nan")
            marks = " / ".join(f"{med(f'wp@{int(t)}'):.1f}" for t in T_MARKS_S)
            lat = med("lat_ms")
            lines.append(f"| {src} | {len(g)} | {marks} | {med('wp_final'):.1f} | {sum(r['success'] for r in g)}/{len(g)} | "
                         f"{sum(r['collisions'] or 0 for r in g)} | {med('dist_min_m'):.2f} m | {med('deadlocks'):.0f} | "
                         f"{'-' if np.isnan(lat) else f'{lat:.0f} ms'} |")
        lines += ["", f"**Regla de decision** (avance del plan a {T_REF_S:.0f} s; diferencia de medianas >= {MIN_DIFF_WP} WP "
                  f"y gana en >= {MIN_SEEDS_WIN} semillas emparejadas):", ""]
        srcs = sorted(by)
        verdicts = []
        for i, a in enumerate(srcs):
            for b in srcs[i + 1:]:
                sa = {r["seed"]: r[key] for r in by[a]}
                sb = {r["seed"]: r[key] for r in by[b]}
                common = sorted(set(sa) & set(sb))
                wins_a = sum(sa[s] > sb[s] for s in common)
                wins_b = sum(sb[s] > sa[s] for s in common)
                diff = float(np.median(list(sa.values())) - np.median(list(sb.values())))
                if diff >= MIN_DIFF_WP and wins_a >= MIN_SEEDS_WIN:
                    v = f"**{a} aporta mas que {b}**"
                elif -diff >= MIN_DIFF_WP and wins_b >= MIN_SEEDS_WIN:
                    v = f"**{b} aporta mas que {a}**"
                else:
                    v = "equivalentes en avance"
                verdicts.append(v)
                pv = _pvalues([sa[s] for s in common], [sb[s] for s in common], paired=True)
                lines.append(f"- {a} vs {b}: diferencia de medianas {diff:+.1f} WP; gana {a} en {wins_a}, {b} en {wins_b} "
                             f"de {len(common)} semillas -> {v} ({pv})")
        lines += ["", "| Fuente | Semilla | Plan a 150/300/400 s | Final | Exito | Colisiones | DistMin | Deadlocks | Corrida |",
                  "|---|---:|---|---:|---|---:|---:|---:|---|"]
        for r in sorted(rs, key=lambda r: (r["source"], r["seed"])):
            lines.append(f"| {r['source']} | {r['seed']} | {r['wp@150']}/{r['wp@300']}/{r['wp@400']} | {r['wp_final']} | "
                         f"{'si' if r['success'] else 'no'} | {r['collisions']} | {r['dist_min_m']} | {r['deadlocks']} | {r['run']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    runs = collect(out_dir)
    if not runs:
        print(f"Sin corridas strat_*__* en {out_dir}")
        return
    text = report(runs)
    (out_dir / "strategic_batch_report.md").write_text(text + "\n", encoding="utf-8")
    (out_dir / "strategic_batch_runs.json").write_text(json.dumps(runs, indent=2), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
