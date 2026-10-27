"""Analisis de los lotes finales de la tesis (cap. 10 Sec. 10.12.2; lanzados con experiments/run_lotes.ps1).

Por lote (escenario) y celda (brazo x estrategia de atasco):
- tasa de exito con IC de Wilson 95 %;
- SPL, tiempo de mision (solo corridas exitosas) y distancia minima al obstaculo: mediana [p25, p75].

Comparaciones planificadas, tres por lote (diseno v4, 2026-10-15):
- Lotes con la celda fsm x blind (obstruccion, Sec. 10.12.2):
  (i)   slm x depth  vs  fsm x blind   -- sistema completo frente a una FSM sin barrido
  (ii)  fsm x depth  vs  fsm x blind   -- aporte del barrido con profundidad
  (iii) slm x depth  vs  fsm x depth   -- aporte de la capa estrategica y la politica del brazo slm
- Lotes de 3 brazos (despejados, Sec. 10.5.3 y 10.7.3): slm-fsm, slm-reactive, fsm-reactive.
Con --design auto (por defecto) cada lote usa el juego que corresponde a sus celdas.
Metrica primaria (Sec. 10.7): SPL en los escenarios con obstruccion (D, E, F) y tiempo de mision de las
corridas exitosas en los de control (A, B, C). Para cada comparacion: delta de Cliff con IC bootstrap
(remuestreo de corridas dentro de cada celda) y prueba de permutacion exacta sobre los rangos (equivale a
Mann-Whitney exacto y admite empates, frecuentes en SPL por las corridas fallidas con SPL = 0).
Bonferroni sobre la familia primaria: 3 comparaciones x lotes analizados.
Secundarias, sin correccion y rotuladas como tales: exito (Fisher exacto y diferencia de tasas con IC de
Newcombe) y distancia minima al obstaculo.

Descartes (Sec. 10.12.2): code_version distinto del de referencia de su lote, sufijo '-dirty', menos de 50
ciclos, o semilla fuera de --seeds. Los pilotos (pilotos/) y las corridas descartadas a mano (descarte/,
motivo en DESCARTE.md) no entran.

Version de referencia por lote (2026-10-27): cada lote se corre de una vez con un solo code_version, pero los
seis lotes v4 tienen versiones distintas (el codigo de vuelo es identico desde b0332e1a; cambian el runner y
el lanzador). La referencia es la version limpia mas frecuente dentro de cada escenario; --ref-version la
fija para todos.

DistMin sin la primera muestra (2026-10-27): la primera muestra de la auditoria (`.distmin.ndjson`) es un
artefacto del arranque (0.003 m en townsim_clear slm semilla 31, seguida de 18.3 m; cap. 11 Sec. 11.6.2).
Si el archivo existe, `min_obstacle_dist_m` se recalcula sin ella; el valor del summary queda en
`min_obstacle_dist_m_raw`.

Uso (desde airsim-loop/):
    python experiments/analyze_lotes.py ../airsim-runs/produccion/v4 --family 18
    python experiments/analyze_lotes.py ../airsim-runs/produccion/v4 --ref-version 1a2b3c4d --seeds 2 3 5
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import fisher_exact, norm, permutation_test, rankdata

from analyze import load_optimal_lengths, spl

LOTES = {
    "minisim_clear": "A", "townsim_clear": "B", "citysim_clear": "C",
    "townsim_ini": "D", "townsim_calib_cruce_frontal": "E", "citysim_pilot": "F",
}
OBSTRUCTED = {"D", "E", "F"}
CELL_ORDER = ["slm x depth", "fsm x depth", "fsm x blind", "reactive"]
COMPARISONS_CELLS = [
    ("i", "slm x depth", "fsm x blind"),
    ("ii", "fsm x depth", "fsm x blind"),
    ("iii", "slm x depth", "fsm x depth"),
]
COMPARISONS_ARMS = [
    ("slm-fsm", "slm x depth", "fsm x depth"),
    ("slm-reactive", "slm x depth", "reactive"),
    ("fsm-reactive", "fsm x depth", "reactive"),
]
DESIGNS = ("auto", "cells4", "arms3")


def comparisons_for(cells_present, design: str = "auto") -> list[tuple[str, str, str]]:
    """Juego de comparaciones de un lote: el de 4 celdas si el lote tiene fsm x blind, si no el de 3 brazos."""
    if design == "cells4" or (design == "auto" and "fsm x blind" in cells_present):
        return COMPARISONS_CELLS
    return COMPARISONS_ARMS
MIN_VALID_CYCLES = 50
ALPHA = 0.05
DISTMIN_SKIP_FIRST = 1


# ---------------------------------------------------------------- estadisticos

def wilson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """IC de Wilson para una proporcion (no colapsa en 0/n ni n/n, a diferencia del de Wald)."""
    if n == 0:
        return (float("nan"), float("nan"))
    z = norm.ppf(0.5 + conf / 2)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_diff(k1: int, n1: int, k2: int, n2: int, conf: float = 0.95) -> tuple[float, float, float]:
    """Diferencia de proporciones p1 - p2 con IC de Newcombe (metodo 10, a partir de los IC de Wilson)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, conf)
    l2, u2 = wilson(k2, n2, conf)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def cliffs_delta(x, y) -> float:
    """P(X > Y) - P(X < Y), en [-1, 1]."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) == 0 or len(y) == 0:
        return float("nan")
    return float(np.sign(x[:, None] - y[None, :]).mean())


def cliffs_delta_ci(x, y, n_boot: int = 5000, conf: float = 0.95, seed: int = 0) -> tuple[float, float]:
    """IC percentil por bootstrap: se remuestrean corridas dentro de cada celda."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2 or len(y) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    xb = x[rng.integers(0, len(x), (n_boot, len(x)))]
    yb = y[rng.integers(0, len(y), (n_boot, len(y)))]
    deltas = np.sign(xb[:, :, None] - yb[:, None, :]).mean(axis=(1, 2))
    a = (1 - conf) / 2
    return (float(np.quantile(deltas, a)), float(np.quantile(deltas, 1 - a)))


def rank_permutation_p(x, y) -> float:
    """p bilateral de la prueba de permutacion exacta sobre la diferencia de rangos medios.

    Es Mann-Whitney exacto con rangos medios para los empates: con K = 5 por celda hay 252
    particiones y el p minimo posible es 2/252 = 0.0079; con K = 10, 2/184756.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) == 0 or len(y) == 0:
        return float("nan")
    ranks = rankdata(np.concatenate([x, y]))
    rx, ry = ranks[: len(x)], ranks[len(x):]
    if np.all(ranks == ranks[0]):
        return 1.0

    def stat(a, b, axis):
        return np.mean(a, axis=axis) - np.mean(b, axis=axis)

    res = permutation_test((rx, ry), stat, permutation_type="independent", vectorized=True,
                           n_resamples=np.inf, alternative="two-sided")
    return float(min(1.0, res.pvalue))


# ---------------------------------------------------------------- datos

def cell_label(run: dict) -> str:
    arm = run.get("arm")
    return "reactive" if arm == "reactive" else f"{arm} x {run.get('deadlock_strategy')}"


def distmin_without_first(summary_path: Path, skip: int = DISTMIN_SKIP_FIRST) -> float | None:
    """Minimo de la auditoria de DistMin sin las primeras `skip` muestras; None si no hay datos."""
    path = summary_path.with_name(summary_path.name.replace(".summary.json", ".distmin.ndjson"))
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    values = []
    for line in lines[skip:]:
        try:
            d = json.loads(line).get("dist_m")
        except (ValueError, AttributeError):
            continue
        if d is not None:
            values.append(float(d))
    return min(values) if values else None


def load_runs(root: str) -> list[dict]:
    runs = []
    for path in glob.glob(str(Path(root) / "**" / "*.summary.json"), recursive=True):
        p = Path(path)
        if {"pilotos", "descarte"} & set(p.relative_to(root).parts):
            continue
        try:
            run = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        run["_path"] = p.relative_to(root).as_posix()
        recomputed = distmin_without_first(p)
        if recomputed is not None:
            run["min_obstacle_dist_m_raw"] = run.get("min_obstacle_dist_m")
            run["min_obstacle_dist_m"] = recomputed
        runs.append(run)
    return runs


def _clean(version) -> bool:
    return bool(version) and not str(version).endswith("-dirty") and version != "unknown"


def reference_version(runs: list[dict]) -> str | None:
    """La version limpia mas frecuente; None si no hay ninguna."""
    clean = Counter(r.get("code_version") for r in runs if _clean(r.get("code_version")))
    return clean.most_common(1)[0][0] if clean else None


def reference_versions(runs: list[dict]) -> dict[str, str | None]:
    """Version de referencia por lote: la limpia mas frecuente dentro de cada escenario."""
    return {s: reference_version([r for r in runs if r.get("scenario") == s])
            for s in sorted({r.get("scenario") for r in runs if r.get("scenario") in LOTES})}


def filter_runs(runs: list[dict], ref_version: str | dict | None,
                seeds=None) -> tuple[list[dict], list[tuple[dict, str]]]:
    """`ref_version`: una version para todos los lotes, o {escenario: version} (una por lote)."""
    kept, dropped = [], []
    for r in runs:
        version = str(r.get("code_version"))
        ref = ref_version.get(r.get("scenario")) if isinstance(ref_version, dict) else ref_version
        if r.get("scenario") not in LOTES:
            reason = f"escenario fuera de los lotes ({r.get('scenario')})"
        elif version.endswith("-dirty"):
            reason = f"code_version {version}"
        elif ref and version != ref:
            reason = f"code_version {version} != {ref}"
        elif int(r.get("cycles") or 0) < MIN_VALID_CYCLES:
            reason = f"{r.get('cycles')} ciclos (< {MIN_VALID_CYCLES}, falla de infraestructura)"
        elif seeds is not None and r.get("seed") not in seeds:
            reason = f"semilla {r.get('seed')} fuera de --seeds"
        else:
            kept.append(r)
            continue
        dropped.append((r, reason))
    return kept, dropped


def primary_values(runs: list[dict], lote: str, optimal: dict) -> tuple[str, list[float]]:
    if lote in OBSTRUCTED:
        return "SPL", [v for v in (spl(r, optimal) for r in runs) if not math.isnan(v)]
    return "tiempo de mision exitosa (s)", [float(r["duration_s"]) for r in runs if r.get("success")]


def _q(values) -> str:
    if not values:
        return "-"
    a = np.asarray(values, float)
    return f"{np.median(a):.2f} [{np.quantile(a, .25):.2f}, {np.quantile(a, .75):.2f}]"


def _p(p: float) -> str:
    return "-" if p is None or math.isnan(p) else (f"{p:.2e}" if p < 1e-3 else f"{p:.4f}")


# ---------------------------------------------------------------- analisis

def analyze(runs: list[dict], optimal: dict, n_boot: int = 5000, family: int | None = None,
            design: str = "auto") -> dict:
    """`family`: tamano de la familia de Bonferroni declarada; por defecto, 3 x lotes presentes."""
    lotes = sorted({LOTES[r["scenario"]] for r in runs})
    family = family or 3 * len(lotes)
    alpha_corr = ALPHA / family if family else float("nan")
    cells, comps = [], []
    for lote in lotes:
        lote_runs = [r for r in runs if LOTES[r["scenario"]] == lote]
        by_cell = {c: [r for r in lote_runs if cell_label(r) == c] for c in CELL_ORDER}
        for c in CELL_ORDER + sorted({cell_label(r) for r in lote_runs} - set(CELL_ORDER)):
            rs = by_cell.get(c) or [r for r in lote_runs if cell_label(r) == c]
            if not rs:
                continue
            k, n = sum(1 for r in rs if r.get("success")), len(rs)
            lo, hi = wilson(k, n)
            cells.append({
                "lote": lote, "escenario": rs[0]["scenario"], "celda": c, "n": n, "exitos": k,
                "tasa": k / n, "wilson_lo": lo, "wilson_hi": hi,
                "spl": _q([spl(r, optimal) for r in rs if not math.isnan(spl(r, optimal))]),
                "tiempo_exito_s": _q([r["duration_s"] for r in rs if r.get("success")]),
                "dist_min_m": _q([r["min_obstacle_dist_m"] for r in rs if r.get("min_obstacle_dist_m") is not None]),
                "colisiones": sum(int(r.get("collisions") or 0) for r in rs),
                "semillas": sorted(r.get("seed") for r in rs),
            })
        for cid, a, b in comparisons_for({cell_label(r) for r in lote_runs}, design):
            ra, rb = by_cell.get(a, []), by_cell.get(b, [])
            if not ra or not rb:
                continue
            metric, xa = primary_values(ra, lote, optimal)
            _, xb = primary_values(rb, lote, optimal)
            p = rank_permutation_p(xa, xb)
            d = cliffs_delta(xa, xb)
            dlo, dhi = cliffs_delta_ci(xa, xb, n_boot)
            ka, kb = sum(1 for r in ra if r.get("success")), sum(1 for r in rb if r.get("success"))
            diff, diff_lo, diff_hi = newcombe_diff(ka, len(ra), kb, len(rb))
            da = [r["min_obstacle_dist_m"] for r in ra if r.get("min_obstacle_dist_m") is not None]
            db = [r["min_obstacle_dist_m"] for r in rb if r.get("min_obstacle_dist_m") is not None]
            comps.append({
                "lote": lote, "comparacion": cid, "a": a, "b": b, "metrica_primaria": metric,
                "n_a": len(xa), "n_b": len(xb), "cliff": d, "cliff_lo": dlo, "cliff_hi": dhi,
                "p": p, "p_bonf": min(1.0, p * family) if not math.isnan(p) else p,
                "significativa": (not math.isnan(p)) and p < alpha_corr,
                "exito_a": f"{ka}/{len(ra)}", "exito_b": f"{kb}/{len(rb)}",
                "dif_exito": diff, "dif_exito_lo": diff_lo, "dif_exito_hi": diff_hi,
                "p_fisher": float(fisher_exact([[ka, len(ra) - ka], [kb, len(rb) - kb]])[1]),
                "cliff_dist_min": cliffs_delta(da, db), "p_dist_min": rank_permutation_p(da, db),
            })
    return {"lotes": lotes, "family": family, "alpha_corr": alpha_corr, "cells": cells, "comparisons": comps}


def _ref_text(ref_version) -> str:
    if isinstance(ref_version, dict):
        return ", ".join(f"{LOTES[s]} `{v}`" for s, v in sorted(ref_version.items(), key=lambda kv: LOTES[kv[0]]))
    return f"`{ref_version}`"


def report_md(res: dict, ref_version, n_kept: int, dropped) -> str:
    lines = ["# Lotes finales: analisis", "",
             f"- code_version de referencia (por lote): {_ref_text(ref_version)}",
             f"- DistMin sin las primeras {DISTMIN_SKIP_FIRST} muestras de la auditoria (artefacto del arranque)",
             f"- Corridas validas: {n_kept}; descartadas: {len(dropped)}",
             f"- Familia primaria: {res['family']} comparaciones (3 por lote; lotes presentes: {', '.join(res['lotes'])}); "
             f"alfa corregido (Bonferroni) = {res['alpha_corr']:.4f}",
             "- Metrica primaria: SPL (D, E, F); tiempo de las misiones exitosas (A, B, C).",
             "- Delta de Cliff > 0: la primera celda tiene valores mayores (mejor en SPL; peor en tiempo).",
             "", "## Por celda", "",
             "| Lote | Escenario | Celda | n | Exito | IC Wilson 95 % | SPL med [p25, p75] | Tiempo exito (s) | Dist. min (m) | Colisiones |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for c in res["cells"]:
        lines.append(f"| {c['lote']} | `{c['escenario']}` | {c['celda']} | {c['n']} | {c['exitos']}/{c['n']} "
                     f"| [{c['wilson_lo']:.2f}, {c['wilson_hi']:.2f}] | {c['spl']} | {c['tiempo_exito_s']} "
                     f"| {c['dist_min_m']} | {c['colisiones']} |")
    lines += ["", "## Comparaciones planificadas (metrica primaria)", "",
              "| Lote | Comp. | A vs B | Metrica | n A / n B | Delta de Cliff [IC 95 %] | p (permutacion exacta) | p Bonferroni | Significativa |",
              "|---|---|---|---|---|---|---|---|---|"]
    for c in res["comparisons"]:
        lines.append(f"| {c['lote']} | {c['comparacion']} | {c['a']} vs {c['b']} | {c['metrica_primaria']} "
                     f"| {c['n_a']} / {c['n_b']} | {c['cliff']:+.2f} [{c['cliff_lo']:+.2f}, {c['cliff_hi']:+.2f}] "
                     f"| {_p(c['p'])} | {_p(c['p_bonf'])} | {'si' if c['significativa'] else 'no'} |")
    lines += ["", "## Secundarias (sin correccion)", "",
              "| Lote | Comp. | Exito A / B | Dif. de tasas [IC Newcombe 95 %] | p Fisher | Cliff dist. min | p dist. min |",
              "|---|---|---|---|---|---|---|"]
    for c in res["comparisons"]:
        lines.append(f"| {c['lote']} | {c['comparacion']} | {c['exito_a']} / {c['exito_b']} "
                     f"| {c['dif_exito']:+.2f} [{c['dif_exito_lo']:+.2f}, {c['dif_exito_hi']:+.2f}] "
                     f"| {_p(c['p_fisher'])} | {c['cliff_dist_min']:+.2f} | {_p(c['p_dist_min'])} |")
    if dropped:
        lines += ["", "## Corridas descartadas", "", "| Corrida | Motivo |", "|---|---|"]
        for r, reason in dropped:
            lines.append(f"| `{r['_path']}` | {reason} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Analisis de los lotes finales (cap. 10 Sec. 10.12.2)")
    parser.add_argument("root", help="Directorio de los lotes (p. ej. ../airsim-runs/lotes_final)")
    parser.add_argument("--ref-version", default=None,
                        help="code_version de referencia para todos los lotes; por defecto, la version limpia mas "
                             "frecuente de cada lote")
    parser.add_argument("--seeds", nargs="+", type=int, default=None)
    parser.add_argument("--missions-dir", default=str(Path(__file__).resolve().parents[2] / "airsim-plan" / "missions" / "flightplans"))
    parser.add_argument("--n-boot", type=int, default=5000)
    parser.add_argument("--design", choices=DESIGNS, default="auto",
                        help="Comparaciones por lote: auto (4 celdas si hay fsm x blind, si no 3 brazos), cells4 o arms3")
    parser.add_argument("--family", type=int, default=None,
                        help="Tamano de la familia de Bonferroni declarada (p. ej. 18 = 3 x 6 lotes aunque se analice "
                             "un subconjunto); por defecto, 3 x lotes presentes")
    parser.add_argument("--out", default=None, help="Directorio de salida (por defecto, root)")
    args = parser.parse_args()

    runs = load_runs(args.root)
    ref = args.ref_version or reference_versions(runs)
    for scen in sorted({r.get("scenario") for r in runs if r.get("scenario") in LOTES}):
        versions = Counter(str(r.get("code_version")) for r in runs if r.get("scenario") == scen)
        if len(versions) > 1:
            print(f"[lotes] AVISO: varias code_version en {scen}: {dict(versions)}")
    kept, dropped = filter_runs(runs, ref, set(args.seeds) if args.seeds else None)
    res = analyze(kept, load_optimal_lengths(args.missions_dir), args.n_boot, args.family, args.design)

    out = Path(args.out or args.root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "analisis_lotes.md").write_text(report_md(res, ref, len(kept), dropped), encoding="utf-8")
    for name, rows in (("analisis_lotes_celdas.csv", res["cells"]), ("analisis_lotes_comparaciones.csv", res["comparisons"])):
        if rows:
            with open(out / name, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    print(f"[lotes] {len(kept)} corridas validas, {len(dropped)} descartadas; reporte en {out / 'analisis_lotes.md'}")


if __name__ == "__main__":
    main()
