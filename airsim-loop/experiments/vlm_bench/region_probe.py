"""Reconocimiento por region sobre la camara frontal: que hay en cada sector de la grilla? (2026-10-08)

El banco v2 mostro que el modelo no juzga distancias (grid_prod, centro_libre: AUC ~0.53, P(si) casi
constante aun a < 5 m de una pared), pero en el mapa cenital si reconoce que hay en un parche (AUC ~0.8).
Esta prueba lleva la pregunta de reconocimiento a la camara frontal: el recorte cuadrado de vuelo con un
cuadrado rojo sobre UN sector y la pregunta "que llena el cuadrado rojo?" con cinco clases. Una consulta
por sector (9 por muestra), sin grilla ni etiquetas dibujadas (evita el sesgo por posicion de grid_prod).

Modos: `marker` (la imagen completa con el cuadrado rojo) y `crop` (solo el recorte del sector, sin
marcador). 2026-10-08: con `marker` el modelo no ubica el cuadrado (en texto libre responde "A red square." o
"Nothing.") y contesta la primera opcion del enum ("wall" 88 %; con el enum invertido, "sky"); `crop` evita
la consigna de ubicar y es la forma viable en vuelo (pocos tokens de imagen por consulta).

Regla fijada antes de correr: abierto = sky + distant buildings + road; bloqueado = wall + trees.
P(abierto) se lee de los logprobs. La etiqueta de referencia es la del banco (cell_free: p5 >= 15 m).

Muestras: las mismas que las preguntas de una imagen de evaluate.py (validas, estratificadas por centro
libre, semilla 0). Sin AirSim.

Uso:
    python experiments/vlm_bench/region_probe.py ask --bench ../airsim-runs/vlm_bench/v2
    python experiments/vlm_bench/region_probe.py report --bench ../airsim-runs/vlm_bench/v2
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (LOCAL_LLM_MODEL_NAME, append_jsonl, choice_probs_at, encode_jpeg, image_part,  # noqa: E402
                    parse_json, query_vlm, read_jsonl, text_part, value_offsets)
from evaluate import ALIGN_MIN, load_images, stratified, valid  # noqa: E402
from questions import CELLS, vs  # noqa: E402

SYSTEM = "You see the front camera of a drone flying low in a city. Reply with JSON only."
PROMPT = "What fills the red square? wall (a building facade close to the drone), distant buildings, sky, road or trees."
PROMPT_CROP = ("This is one part of the camera image. What fills it? wall (a building facade close to the drone), "
               "distant buildings, sky, road or trees.")
CLASSES = ["wall", "distant buildings", "sky", "road", "trees"]   # iniciales distintas (logprobs)
OPEN = {"distant buildings", "sky", "road"}
SCHEMA = {"type": "json_schema", "json_schema": {"name": "region", "schema": {
    "type": "object", "properties": {"answer": {"type": "string", "enum": CLASSES}},
    "required": ["answer"], "additionalProperties": False}}}
IMAGE_PX = 384
RESULTS = "region_results.jsonl"


def region_image(img: Any, cell: str, size: int = IMAGE_PX) -> Any:
    """Recorte cuadrado de vuelo, reescalado, con un cuadrado rojo sobre el sector `cell`."""
    import cv2

    crop, side, _f = vs.square_crop(img)
    out = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA) if side != size else crop.copy()
    ci, ri = vs.GRID_COLS.index(cell[0]), vs.GRID_ROWS.index(cell[1])
    x0, y0 = ci * size // 3, ri * size // 3
    cv2.rectangle(out, (x0 + 1, y0 + 1), (x0 + size // 3 - 2, y0 + size // 3 - 2), (0, 0, 255), 2)
    return out


def region_crop(img: Any, cell: str) -> Any:
    """Solo el sector `cell` del recorte cuadrado de vuelo (un tercio de lado), a resolucion nativa."""
    crop, side, _f = vs.square_crop(img)
    ci, ri = vs.GRID_COLS.index(cell[0]), vs.GRID_ROWS.index(cell[1])
    t = side // 3
    return crop[ri * t:(ri + 1) * t, ci * t:(ci + 1) * t].copy()


def read_region(text: str, tokens: List[Any]) -> Dict[str, Any]:
    ans = (parse_json(text) or {}).get("answer")
    ans = ans if ans in CLASSES else None
    offs = value_offsets(text, "answer")
    probs = choice_probs_at(tokens, offs[0], CLASSES) if offs and tokens else None
    p_open = round(sum(probs[c] for c in OPEN), 4) if probs else None
    return {"answer": ans, "probs": probs, "p_open": p_open,
            "pred_open": None if ans is None else ans in OPEN}


def stage_ask(args) -> None:
    bench = Path(args.bench)
    samples = [s for s in read_jsonl(bench / "samples_gt.jsonl") if s.get("kind") != "scan" and valid(s, ALIGN_MIN)]
    chosen = stratified([s for s in samples if s["gt"].get("center_free") is not None],
                        lambda s: s["gt"]["center_free"], args.per_class, args.seed)
    out_path = bench / RESULTS
    done = ({(r["id"], r["cell"], r["model"], r.get("mode", "marker")) for r in read_jsonl(out_path)}
            if out_path.exists() else set())
    print(f"[region] modelo {LOCAL_LLM_MODEL_NAME}, modo {args.mode}; {len(chosen)} muestras x {len(CELLS)} sectores",
          flush=True)
    for k, s in enumerate(chosen):
        imgs = load_images(s, bench, "replay")
        if not imgs:
            continue
        for cell in CELLS:
            if (s["id"], cell, LOCAL_LLM_MODEL_NAME, args.mode) in done:
                continue
            if args.mode == "crop":
                b64, prompt = encode_jpeg(region_crop(imgs[0], cell)), PROMPT_CROP
            else:
                b64, prompt = encode_jpeg(region_image(imgs[0], cell), IMAGE_PX), PROMPT
            r = query_vlm(SYSTEM, [text_part(prompt), image_part(b64)], SCHEMA, max_tokens=24)
            cg = s["gt"]["cells"][cell]
            rec = {"id": s["id"], "run": s["run"], "cell": cell, "model": LOCAL_LLM_MODEL_NAME, "mode": args.mode,
                   "truth_open": bool(s["gt"]["cell_free"][cell]), "p5": cg["p5"], "free_frac": cg["free_frac"],
                   "latency_ms": round(r["latency_ms"], 1), "error": r["error"], "text": r["text"]}
            if not r["error"]:
                rec.update(read_region(r["text"], r["tokens"]))
            append_jsonl(out_path, rec)
        if (k + 1) % 20 == 0:
            print(f"[region] {k + 1}/{len(chosen)}", flush=True)
    print(f"[region] listo -> {out_path}")


# --------------------------------------------------------------------------- reporte
def auc(scores: List[float], pos: List[bool]) -> Optional[float]:
    p = [s for s, y in zip(scores, pos) if y]
    n = [s for s, y in zip(scores, pos) if not y]
    if not p or not n:
        return None
    return sum((a > b) + 0.5 * (a == b) for a in p for b in n) / (len(p) * len(n))


def balanced_accuracy(pred: List[bool], truth: List[bool]) -> Optional[float]:
    tp = [p for p, t in zip(pred, truth) if t]
    tn = [not p for p, t in zip(pred, truth) if not t]
    if not tp or not tn:
        return None
    return 0.5 * (np.mean(tp) + np.mean(tn))


def bootstrap_ci(rows: List[Dict[str, Any]], n_boot: int = 1000, seed: int = 0):
    """IC 95 % de la exactitud balanceada, remuestreando corridas (como report.py)."""
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["run"]].append(r)
    runs, rng, vals = list(by), random.Random(seed), []
    for _ in range(n_boot):
        pick = [r for run in (rng.choice(runs) for _ in runs) for r in by[run]]
        v = balanced_accuracy([r["pred_open"] for r in pick], [r["truth_open"] for r in pick])
        if v is not None:
            vals.append(v)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))) if vals else (None, None)


def _fmt(v: Optional[float], pct: bool = False) -> str:
    if v is None:
        return "-"
    return f"{100 * v:.0f} %" if pct else f"{v:.2f}"


def stage_report(args) -> str:
    bench = Path(args.bench)
    rows = [r for r in read_jsonl(bench / RESULTS) if not r.get("error") and r.get("answer") is not None]
    lines = []
    for model, mode in sorted({(r["model"], r.get("mode", "marker")) for r in rows}):
        g = [r for r in rows if r["model"] == model and r.get("mode", "marker") == mode]
        sc = [r for r in g if r.get("p_open") is not None]
        ba = balanced_accuracy([r["pred_open"] for r in g], [r["truth_open"] for r in g])
        lo, hi = bootstrap_ci(g)
        easy = [r for r in sc if r["p5"] < 5.0 or r["p5"] >= 40.0]
        lines += [f"## region_probe - {model} - modo {mode}", "",
                  f"Consultas: {len(g)} ({len({r['id'] for r in g})} muestras x 9 sectores); abiertos reales "
                  f"{_fmt(np.mean([r['truth_open'] for r in g]), True)}; latencia mediana "
                  f"{np.median([r['latency_ms'] for r in g]):.0f} ms.", "",
                  "| Medida | Valor |", "|---|---:|",
                  f"| Exactitud bal. (respuesta -> abierto) [IC 95 %] | {_fmt(ba, True)} [{_fmt(lo, True)}-{_fmt(hi, True)}] |",
                  f"| AUC P(abierto) | {_fmt(auc([r['p_open'] for r in sc], [r['truth_open'] for r in sc]))} |",
                  f"| AUC P(abierto), casos obvios (p5 < 5 m vs >= 40 m, n={len(easy)}) | "
                  f"{_fmt(auc([r['p_open'] for r in easy], [r['p5'] >= 40.0 for r in easy]))} |",
                  f"| Pasa (exactitud >= 65 % e IC sobre 50 %) | {'si' if ba and ba >= 0.65 and lo and lo > 0.5 else 'no'} |",
                  ""]
        lines += ["| Fila | AUC P(abierto) | Exactitud bal. | Respuestas |", "|---|---:|---:|---|"]
        for row in vs.GRID_ROWS:
            rr = [r for r in sc if r["cell"][1] == row]
            dist = ", ".join(f"{a} {c}" for a, c in Counter(r["answer"] for r in rr).most_common())
            lines.append(f"| {row} | {_fmt(auc([r['p_open'] for r in rr], [r['truth_open'] for r in rr]))} | "
                         f"{_fmt(balanced_accuracy([r['pred_open'] for r in rr], [r['truth_open'] for r in rr]), True)} | {dist} |")
        lines += ["", "| Clase respondida | n | Realmente abierto |", "|---|---:|---:|"]
        for c in CLASSES:
            rr = [r for r in g if r["answer"] == c]
            lines.append(f"| {c} | {len(rr)} | {_fmt(np.mean([r['truth_open'] for r in rr]) if rr else None, True)} |")
        lines.append("")
    text = "\n".join(lines)
    (bench / "region_report.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="stage", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--bench", required=True)
    a.add_argument("--per-class", type=int, default=60)
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--mode", choices=["marker", "crop"], default="crop")
    b = sub.add_parser("report")
    b.add_argument("--bench", required=True)
    args = ap.parse_args()
    {"ask": stage_ask, "report": stage_report}[args.stage](args)


if __name__ == "__main__":
    main()
