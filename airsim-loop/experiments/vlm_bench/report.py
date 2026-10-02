"""Metricas del banco -> report.md y metrics.json.

El banco mide CAPACIDAD GENERALISTA del VLM, no ajusta nada: los prompts son fijos e independientes del
escenario, la respuesta se lee tal como sale (la etiqueta), y una pregunta solo se considera apta para el
vuelo si pasa en TODOS los entornos medidos con el mismo prompt. Criterio de pase por entorno: exactitud
balanceada >= PASS_MIN y el limite inferior de su intervalo de confianza del 95 % por encima del azar. El
intervalo se obtiene por bootstrap por corrida (se re-muestrean corridas enteras: las vistas de una misma
corrida no son independientes). El AUC y la exactitud con umbral calibrado se informan SOLO como
diagnostico ("la probabilidad tiene informacion aunque la etiqueta no"); no son configuracion de vuelo.

Por pregunta y resolucion:
  - exactitud y exactitud balanceada (promedio de la sensibilidad por clase: la referencia de azar es
    1/k con k clases, y contestar siempre lo mismo da exactamente 1/k);
  - distribucion de respuestas y la participacion de la respuesta mas frecuente ("constante" si >= 90 %);
  - matriz de confusion;
  - binarias con probabilidad: AUC (Mann-Whitney) y exactitud balanceada con un umbral calibrado por
    validacion cruzada dejando una corrida afuera (el umbral se elige sin mirar la corrida evaluada);
  - grilla: las mismas metricas por sector y agrupadas, tasa de "libre" por posicion contra la real, y
    acuerdo entre la pregunta normal y la permutada en la misma muestra (si el modelo mirara la escena,
    la respuesta por posicion fisica no deberia cambiar al cambiar las etiquetas);
  - barrido: por imagen, frecuencia del patron mas comun y acuerdo con el orden permutado.

Uso:
    python experiments/vlm_bench/report.py --bench ../airsim-runs/vlm_bench/v1
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_jsonl  # noqa: E402
from evaluate import ALIGN_MIN, scan_groups, valid  # noqa: E402
from questions import CELLS, SINGLE  # noqa: E402

CONSTANT_SHARE = 0.9
PASS_MIN = 0.65
BOOTSTRAP_N = 2000


# --------------------------------------------------------------------------- metricas basicas
def balanced_accuracy(truth: Sequence[Any], pred: Sequence[Any]) -> Optional[float]:
    by: Dict[Any, List[bool]] = defaultdict(list)
    for t, p in zip(truth, pred):
        by[t].append(t == p)
    if not by:
        return None
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def accuracy(truth: Sequence[Any], pred: Sequence[Any]) -> Optional[float]:
    return sum(t == p for t, p in zip(truth, pred)) / len(truth) if truth else None


def auc(scores: Sequence[float], positives: Sequence[bool]) -> Optional[float]:
    """AUC por rangos (Mann-Whitney), con empates promediados."""
    pairs = sorted(zip(scores, positives))
    n_pos = sum(positives)
    n_neg = len(positives) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2.0 + 1.0
        i = j + 1
    r_pos = sum(r for r, (_s, p) in zip(ranks, pairs) if p)
    return (r_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def cluster_bootstrap_ci(rows: List[Tuple[str, Any, Any]], n: int = BOOTSTRAP_N, seed: int = 0
                         ) -> Tuple[Optional[float], Optional[float]]:
    """IC 95 % de la exactitud balanceada re-muestreando conglomerados (rows: conglomerado, verdad, respuesta)."""
    import random

    by: Dict[str, List[Tuple[Any, Any]]] = defaultdict(list)
    for c, t, p in rows:
        by[c].append((t, p))
    keys = sorted(by)
    if not keys:
        return None, None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        pick = [rng.choice(keys) for _ in keys]
        t = [x for k in pick for x, _ in by[k]]
        p = [y for k in pick for _, y in by[k]]
        if len(set(t)) < 2:
            continue                       # una sola clase: la exactitud balanceada no esta definida
        vals.append(balanced_accuracy(t, p))
    if len(vals) < n // 2:
        return None, None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def verdict(m: Dict[str, Any]) -> Dict[str, Any]:
    """Pasa si la exactitud balanceada >= PASS_MIN y el IC inferior supera el azar."""
    ba, lo, chance = m.get("balanced_accuracy"), m.get("ci_low"), m.get("chance", 0.5)
    m["passes"] = bool(ba is not None and lo is not None and ba >= PASS_MIN and lo > chance)
    return m


def best_threshold(scores: Sequence[float], positives: Sequence[bool]) -> float:
    cands = sorted(set(scores)) + [1.01]
    best, best_ba = 0.5, -1.0
    for th in cands:
        ba = balanced_accuracy(positives, [s >= th for s in scores]) or 0.0
        if ba > best_ba:
            best, best_ba = th, ba
    return best


def loro_calibrated(rows: List[Tuple[str, float, bool]]) -> Optional[float]:
    """Exactitud balanceada con umbral elegido dejando afuera la corrida evaluada (rows: run, p, positivo)."""
    runs = sorted({r for r, _p, _y in rows})
    if len(runs) < 2:
        return None
    truth, pred = [], []
    for run in runs:
        train = [(p, y) for r, p, y in rows if r != run]
        test = [(p, y) for r, p, y in rows if r == run]
        if not train or not test:
            continue
        th = best_threshold([p for p, _ in train], [y for _, y in train])
        truth += [y for _, y in test]
        pred += [p >= th for p, _ in test]
    return balanced_accuracy(truth, pred)


def answer_stats(answers: Sequence[Any]) -> Dict[str, Any]:
    c = Counter(str(a) for a in answers)
    top, n = (c.most_common(1)[0] if c else (None, 0))
    share = n / len(answers) if answers else None
    return {"distribution": dict(c), "top_answer": top, "top_share": share,
            "constant": bool(share is not None and share >= CONSTANT_SHARE)}


def confusion(truth: Sequence[Any], pred: Sequence[Any]) -> Dict[str, Dict[str, int]]:
    m: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t, p in zip(truth, pred):
        m[str(t)][str(p)] += 1
    return {k: dict(v) for k, v in m.items()}


# --------------------------------------------------------------------------- por tipo de pregunta
def single_metrics(rows: List[Dict[str, Any]], qname: str) -> Dict[str, Any]:
    spec = SINGLE[qname]
    ok = [r for r in rows if not r.get("error") and r.get("answer") is not None]
    truth = [r["truth"] for r in ok]
    pred = [r["answer"] for r in ok]
    lo, hi = cluster_bootstrap_ci([(r["run"], r["truth"], r["answer"]) for r in ok])
    out: Dict[str, Any] = {"n": len(ok), "errors": len(rows) - len(ok), "classes": len(set(truth)),
                           "ci_low": lo, "ci_high": hi,
                           "accuracy": accuracy(truth, pred), "balanced_accuracy": balanced_accuracy(truth, pred),
                           "chance": 1.0 / max(1, len(set(truth))), "answers": answer_stats(pred),
                           "truth_distribution": dict(Counter(truth)), "confusion": confusion(truth, pred)}
    with_p = [r for r in ok if r.get("probs")]
    if with_p:
        arg = [max(r["probs"], key=r["probs"].get) for r in with_p]
        out["prob_argmax_balanced_accuracy"] = balanced_accuracy([r["truth"] for r in with_p], arg)
        if spec["positive"]:
            pos = spec["positive"]
            sc = [r["probs"][pos] for r in with_p]
            y = [r["truth"] == pos for r in with_p]
            out["auc"] = auc(sc, y)
            out["loro_calibrated_balanced_accuracy"] = loro_calibrated([(r["run"], r["probs"][pos], r["truth"] == pos)
                                                                        for r in with_p])
    out["latency_ms_mean"] = _mean([r["latency_ms"] for r in rows])
    return verdict(out)


def grid_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if not r.get("error") and isinstance(r.get("answer"), dict)
          and all(r["answer"].get(c) in ("libre", "bloqueado") for c in CELLS)]
    truth = [r["truth"][c] for r in ok for c in CELLS]
    pred = [r["answer"][c] for r in ok for c in CELLS]
    per_cell = {}
    for c in CELLS:
        t = [r["truth"][c] for r in ok]
        p = [r["answer"][c] for r in ok]
        per_cell[c] = {"balanced_accuracy": balanced_accuracy(t, p),
                       "answer_libre_rate": _mean([a == "libre" for a in p]),
                       "truth_libre_rate": _mean([a == "libre" for a in t])}
    lo, hi = cluster_bootstrap_ci([(r["run"], r["truth"][c], r["answer"][c]) for r in ok for c in CELLS])
    out: Dict[str, Any] = {"n": len(ok), "errors": len(rows) - len(ok), "accuracy": accuracy(truth, pred),
                           "balanced_accuracy": balanced_accuracy(truth, pred), "chance": 0.5,
                           "ci_low": lo, "ci_high": hi,
                           "answers": answer_stats(pred), "per_cell": per_cell,
                           "latency_ms_mean": _mean([r["latency_ms"] for r in rows])}
    sc, y, runs = [], [], []
    for r in ok:
        for c in CELLS:
            p = (r.get("probs") or {}).get(c)
            if p:
                sc.append(p["libre"])
                y.append(r["truth"][c] == "libre")
                runs.append(r["run"])
    if sc:
        out["auc"] = auc(sc, y)
        out["loro_calibrated_balanced_accuracy"] = loro_calibrated(list(zip(runs, sc, y)))
    # Patrones de respuesta: cuantas respuestas distintas da a escenas distintas.
    pats = Counter(tuple(r["answer"][c] == "libre" for c in CELLS) for r in ok)
    out["distinct_patterns"] = len(pats)
    out["top_pattern_share"] = (pats.most_common(1)[0][1] / len(ok)) if ok else None
    return verdict(out)


def grid_permutation(prod: List[Dict[str, Any]], perm: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Acuerdo por posicion fisica entre la grilla normal y la permutada en la misma muestra."""
    by_id = {(r["id"], r["size"]): r for r in prod if isinstance(r.get("answer"), dict)}
    agree, n, truth_agree_prod, truth_agree_perm = 0, 0, 0, 0
    for r in perm:
        a = by_id.get((r["id"], r["size"]))
        if a is None or not isinstance(r.get("answer"), dict):
            continue
        for c in CELLS:
            if r["answer"].get(c) is None or a["answer"].get(c) is None:
                continue
            n += 1
            agree += r["answer"][c] == a["answer"][c]
            truth_agree_prod += a["answer"][c] == a["truth"][c]
            truth_agree_perm += r["answer"][c] == r["truth"][c]
    return {"cells": n, "agreement": agree / n if n else None,
            "accuracy_prod": truth_agree_prod / n if n else None, "accuracy_perm": truth_agree_perm / n if n else None}


def scan_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if not r.get("error") and isinstance(r.get("answer"), list)
          and all(isinstance(a, bool) for a in r["answer"])]
    truth = [t for r in ok for t in r["truth"]]
    pred = [a for r in ok for a in r["answer"]]
    pats = Counter(tuple(r["answer"]) for r in ok)
    lo, hi = cluster_bootstrap_ci([(r["run"], t, a) for r in ok for t, a in zip(r["truth"], r["answer"])])
    out = {"n_scans": len(ok), "n_images": len(pred), "errors": len(rows) - len(ok), "ci_low": lo, "ci_high": hi,
           "accuracy": accuracy(truth, pred), "balanced_accuracy": balanced_accuracy(truth, pred), "chance": 0.5,
           "answers": answer_stats(pred), "top_pattern": str(pats.most_common(1)[0][0]) if pats else None,
           "top_pattern_share": (pats.most_common(1)[0][1] / len(ok)) if ok else None,
           "degradada_true_rate": _mean([r.get("degradada") is True for r in ok]),
           "latency_ms_mean": _mean([r["latency_ms"] for r in rows])}
    sc = [(r["run"], p, t) for r in ok for p, t in zip(r.get("probs") or [], r["truth"]) if p is not None]
    if sc:
        out["auc"] = auc([p for _r, p, _t in sc], [t for _r, _p, t in sc])
        out["loro_calibrated_balanced_accuracy"] = loro_calibrated(sc)
    return verdict(out)


def scan_permutation(prod, perm) -> Dict[str, Any]:
    by_id = {(r["id"], r["size"]): r for r in prod if isinstance(r.get("answer"), list)}
    agree, n = 0, 0
    for r in perm:
        a = by_id.get((r["id"], r["size"]))
        if a is None or not isinstance(r.get("answer"), list):
            continue
        for x, y in zip(a["answer"], r["answer"]):
            if isinstance(x, bool) and isinstance(y, bool):
                n += 1
                agree += x == y
    return {"images": n, "agreement": agree / n if n else None}


def route_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Juicio del VLM sobre rutas dibujadas en el mapa, contra la geometria de AirSim (route_bench.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.planning.route_planner import choose

    ok = [r for r in rows if r.get("answer") in ("si", "no")]
    truth = ["si" if r["clear"] else "no" for r in ok]
    pred = [r["answer"] for r in ok]
    lo, hi = cluster_bootstrap_ci([(r["mission"] + "/" + r["leg"], t, p) for r, t, p in zip(ok, truth, pred)])
    out: Dict[str, Any] = {"n": len(ok), "errors": len(rows) - len(ok), "accuracy": accuracy(truth, pred),
                           "balanced_accuracy": balanced_accuracy(truth, pred), "chance": 0.5,
                           "ci_low": lo, "ci_high": hi,
                           "answers": answer_stats(pred), "truth_distribution": dict(Counter(truth)),
                           "confusion": confusion(truth, pred)}
    with_p = [r for r in ok if r.get("p_si") is not None]
    if with_p:
        out["auc"] = auc([r["p_si"] for r in with_p], [r["clear"] for r in with_p])
        out["loro_calibrated_balanced_accuracy"] = loro_calibrated(
            [(r["mission"], r["p_si"], r["clear"]) for r in with_p])
    legs: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        legs[(r["mission"], r["leg"])].append(r)
    per_leg = []
    for (mission, leg), cs in sorted(legs.items()):
        if not any(c["candidate"] == "directo" for c in cs):
            continue
        best, why = choose([{"name": c["candidate"], "answer": c.get("answer"), "p_si": c.get("p_si"),
                             "length_m": c["length_m"]} for c in cs])
        chosen = next(c for c in cs if c["candidate"] == best["name"])
        direct = next(c for c in cs if c["candidate"] == "directo")
        per_leg.append({"mission": mission, "leg": leg, "chosen": best["name"], "reason": why,
                        "chosen_clear": chosen["clear"], "direct_clear": direct["clear"],
                        "any_clear": any(c["clear"] for c in cs)})
    out["legs"] = per_leg
    out["plan_clear_rate"] = _mean([l["chosen_clear"] for l in per_leg])
    out["direct_clear_rate"] = _mean([l["direct_clear"] for l in per_leg])
    out["solvable_rate"] = _mean([l["any_clear"] for l in per_leg])
    return verdict(out)


def _mean(xs: Sequence[Any]) -> Optional[float]:
    xs = [float(x) for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# --------------------------------------------------------------------------- informe
def dataset_summary(samples: List[Dict[str, Any]], align_min: float) -> Dict[str, Any]:
    kinds = Counter(s["kind"] for s in samples)
    inside = sum(bool(s["gt"]["inside"]) for s in samples)
    unstable = sum(not (s.get("replay") or {}).get("stable") for s in samples)
    misaligned = sum(1 for s in samples if (s.get("replay") or {}).get("align_ncc") is not None
                     and s["replay"]["align_ncc"] < align_min)
    ncc = [s["replay"]["align_ncc"] for s in samples if (s.get("replay") or {}).get("align_ncc") is not None]
    return {"samples": len(samples), "by_kind": dict(kinds), "runs": len({s["run"] for s in samples}),
            "inside_geometry": inside, "unstable": unstable, "misaligned": misaligned,
            "valid": sum(valid(s, align_min) for s in samples), "align_ncc_median": _median(ncc),
            "center_free_rate": _mean([s["gt"]["center_free"] == "si" for s in samples if not s["gt"]["inside"]])}


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def _f(x: Any, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{100 * x:.0f} %" if pct else (f"{x:.2f}" if isinstance(x, float) else str(x))


def build(bench: Path, align_min: float = ALIGN_MIN) -> Dict[str, Any]:
    samples = read_jsonl(bench / "samples_gt.jsonl")
    results = read_jsonl(bench / "results.jsonl")
    routes = read_jsonl(bench / "routes.jsonl")
    by: Dict[Tuple[str, int, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        by[(r["question"], r["size"], r["source"])].append(r)
    metrics: Dict[str, Any] = {"dataset": dataset_summary(samples, align_min),
                               "scans": len(scan_groups(samples)), "questions": {}}
    for (q, size, src), rows in sorted(by.items()):
        key = f"{q}@{size}/{src}"
        if q in SINGLE:
            metrics["questions"][key] = single_metrics(rows, q)
        elif q.startswith("grid"):
            metrics["questions"][key] = grid_metrics(rows)
        else:
            metrics["questions"][key] = scan_metrics(rows)
    if routes:
        metrics["questions"]["ruta_mapa@672/mapa"] = route_metrics(routes)
    for size, src in {(s, src) for (_q, s, src) in by}:
        if by.get(("grid_prod", size, src)) and by.get(("grid_perm", size, src)):
            metrics["questions"][f"grid_perm@{size}/{src}"]["permutation"] = grid_permutation(
                by[("grid_prod", size, src)], by[("grid_perm", size, src)])
        if by.get(("scan_prod", size, src)) and by.get(("scan_perm", size, src)):
            metrics["questions"][f"scan_perm@{size}/{src}"]["permutation"] = scan_permutation(
                by[("scan_prod", size, src)], by[("scan_perm", size, src)])
    return metrics


def to_markdown(m: Dict[str, Any]) -> str:
    d = m["dataset"]
    lines = ["# Banco de prueba del VLM", "",
             f"Muestras: {d['samples']} de {d['runs']} corridas ({d['by_kind']}); barridos: {m['scans']}.",
             f"Validas: {d['valid']} — fuera: camara dentro de la geometria {d['inside_geometry']}, "
             f"captura inestable {d['unstable']}, pose mal reproducida {d['misaligned']} "
             f"(correlacion mediana {_f(d['align_ncc_median'])}). Centro libre en {_f(d['center_free_rate'], True)}.", "",
             f"Criterio de pase: exactitud balanceada de la respuesta tal como sale >= {PASS_MIN:.2f} y limite "
             "inferior del IC 95 % (bootstrap por corrida) por encima del azar. AUC y exactitud con umbral "
             "calibrado: solo diagnostico, no configuracion de vuelo.", "",
             "| Pregunta | n | Exactitud bal. [IC 95 %] | Azar | Pasa | Respuesta mas frecuente | Constante | "
             "AUC (diag.) | Con umbral calibrado (diag.) | Latencia (ms) |",
             "|---|---:|---|---:|:---:|---|:---:|---:|---:|---:|"]
    for k, q in m["questions"].items():
        n = q.get("n", q.get("n_images"))
        top = q["answers"]
        lines.append(f"| `{k}` | {n} | {_f(q['balanced_accuracy'], True)} [{_f(q.get('ci_low'), True)}-"
                     f"{_f(q.get('ci_high'), True)}] | {_f(q['chance'], True)} | {'si' if q.get('passes') else 'no'} | "
                     f"{top['top_answer']} ({_f(top['top_share'], True)}) | {'si' if top['constant'] else 'no'} | "
                     f"{_f(q.get('auc'))} | {_f(q.get('loro_calibrated_balanced_accuracy'), True)} | "
                     f"{_f(q.get('latency_ms_mean'))} |")
    for k, q in m["questions"].items():
        if "permutation" in q:
            p = q["permutation"]
            lines += ["", f"**{k}** — acuerdo con el orden normal: {_f(p.get('agreement'), True)}"
                      + (f" (exactitud normal {_f(p.get('accuracy_prod'), True)}, permutada {_f(p.get('accuracy_perm'), True)})"
                         if "accuracy_prod" in p else "")]
        if "per_cell" in q:
            lines += ["", f"**{k}** — por sector (tasa de 'libre' respondida / real; exactitud bal.):", "",
                      "| | A | B | C |", "|---|---|---|---|"]
            for r in "123":
                cells = [q["per_cell"][c + r] for c in "ABC"]
                lines.append(f"| {r} | " + " | ".join(
                    f"{_f(c['answer_libre_rate'], True)} / {_f(c['truth_libre_rate'], True)}; {_f(c['balanced_accuracy'], True)}"
                    for c in cells) + " |")
            lines.append(f"\nPatrones distintos: {q['distinct_patterns']}; el mas frecuente: {_f(q['top_pattern_share'], True)}.")
        if "legs" in q:
            lines += ["", f"**{k}** — tramos con la ruta elegida realmente libre: {_f(q['plan_clear_rate'], True)} "
                      f"(recta libre: {_f(q['direct_clear_rate'], True)}; con alguna candidata libre: "
                      f"{_f(q['solvable_rate'], True)}).", "",
                      "| Mision | Tramo | Elegida | Libre | Recta libre | Alguna libre |", "|---|---|---|:---:|:---:|:---:|"]
            for l in q["legs"]:
                yn = lambda v: "si" if v else "no"  # noqa: E731
                lines.append(f"| {l['mission']} | {l['leg']} | {l['chosen']} | {yn(l['chosen_clear'])} | "
                             f"{yn(l['direct_clear'])} | {yn(l['any_clear'])} |")
        if "top_pattern" in q:
            lines.append(f"\n**{k}** — patron mas frecuente {q['top_pattern']} ({_f(q['top_pattern_share'], True)}); "
                         f"degradada=true en {_f(q['degradada_true_rate'], True)}.")
    return "\n".join(lines) + "\n"


def cross_environment(envs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Pregunta -> resultado por entorno y si pasa en TODOS (la unica condicion para llevarla al vuelo)."""
    keys = sorted({k for m in envs.values() for k in m["questions"]})
    out = {}
    for k in keys:
        per = {e: m["questions"].get(k) for e, m in envs.items()}
        out[k] = {"per_env": {e: (None if q is None else {"balanced_accuracy": q.get("balanced_accuracy"),
                                                          "ci_low": q.get("ci_low"), "ci_high": q.get("ci_high"),
                                                          "passes": q.get("passes")}) for e, q in per.items()},
                  "passes_all": all(q is not None and q.get("passes") for q in per.values())}
    return out


def cross_markdown(cross: Dict[str, Any], names: List[str]) -> str:
    lines = ["# Banco de prueba del VLM: comparacion entre entornos", "",
             "Una pregunta es apta para el vuelo solo si pasa en todos los entornos con el mismo prompt.", "",
             "| Pregunta | " + " | ".join(names) + " | Pasa en todos |", "|---|" + "---|" * len(names) + ":---:|"]
    for k, v in cross.items():
        cells = []
        for e in names:
            q = v["per_env"].get(e)
            cells.append("-" if q is None else f"{_f(q['balanced_accuracy'], True)} [{_f(q['ci_low'], True)}-"
                                               f"{_f(q['ci_high'], True)}] {'pasa' if q['passes'] else 'no'}")
        lines.append(f"| `{k}` | " + " | ".join(cells) + f" | {'si' if v['passes_all'] else 'no'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", nargs="+", required=True,
                    help="uno o mas bancos; con varios, nombre=ruta (p. ej. citysim=.../v1 townsim=.../t1)")
    ap.add_argument("--out", default=None, help="con varios bancos: archivo del reporte comparativo")
    ap.add_argument("--align-min", type=float, default=ALIGN_MIN)
    args = ap.parse_args()
    envs: Dict[str, Dict[str, Any]] = {}
    paths = []
    for spec in args.bench:
        name, path = spec.split("=", 1) if "=" in spec else (Path(spec).name, spec)
        bench = Path(path)
        paths.append(bench)
        m = build(bench, args.align_min)
        (bench / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        (bench / "report.md").write_text(to_markdown(m), encoding="utf-8")
        envs[name] = m
        print(to_markdown(m))
    if len(envs) > 1:
        cross = cross_environment(envs)
        md = cross_markdown(cross, list(envs))
        out = Path(args.out) if args.out else paths[0].parent / "cross_report.md"
        out.write_text(md, encoding="utf-8")
        out.with_suffix(".json").write_text(json.dumps(cross, indent=2, ensure_ascii=False), encoding="utf-8")
        print(md)


if __name__ == "__main__":
    main()
