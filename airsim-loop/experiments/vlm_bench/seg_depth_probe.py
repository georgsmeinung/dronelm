"""Percepcion rapida por sector contra la etiqueta del banco: segmentacion y profundidad monocular (2026-10-08).

El VLM no aporta un juicio de espacio libre en la camara frontal (banco v2: grilla AUC 0.53, recortes 0.62).
Antes de repartir roles (percepcion rapida para "por donde", VLM para "hacia donde") se mide si dos redes
chicas que solo ven el RGB lo hacen mejor, con la misma geometria y el mismo estadistico que la etiqueta:

  - seg:   yolo26n-sem (Cityscapes, 19 clases). Por sector: fraccion de pixeles de obstaculo y de cielo.
  - depth: Depth Anything V2 Metric Outdoor Small (metros). Por sector: p5 de la profundidad estimada
           (labels.cell_stats, la misma funcion que arma la etiqueta con la profundidad del simulador).

Reglas fijadas antes de correr (exactitud balanceada):
  - depth: libre si p5 estimado >= FREE_M (15 m), igual que la etiqueta.
  - seg:   libre si la fraccion de obstaculo < 5 % (analogo del p5).
Para el AUC: depth -> p5 estimado; seg -> 1 - fraccion de obstaculo (y cielo, diagnostico).

Herramienta de laboratorio: solo lee las imagenes RGB reproducidas y las etiquetas ya calculadas
(samples_gt.jsonl); no lee la profundidad del simulador ni usa AirSim.

Uso:
    python experiments/vlm_bench/seg_depth_probe.py run --bench ../airsim-runs/vlm_bench/v2
    python experiments/vlm_bench/seg_depth_probe.py report --bench ../airsim-runs/vlm_bench/v2
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, read_jsonl  # noqa: E402
from evaluate import ALIGN_MIN, stratified, valid  # noqa: E402
from labels import FREE_M, cell_stats, square  # noqa: E402
from questions import CELLS  # noqa: E402
from region_probe import auc, balanced_accuracy, bootstrap_ci  # noqa: E402

SEG_WEIGHTS = ROOT / "weights" / "yolo26n-sem.pt"
DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf"
OBSTACLE = {"building", "wall", "fence", "pole", "traffic light", "traffic sign", "vegetation", "person", "rider",
            "car", "truck", "bus", "train", "motorcycle", "bicycle"}
OBST_MAX_FRAC = 0.05
RESULTS = "seg_depth_results.jsonl"


def cell_fractions(mask: np.ndarray, names: Dict[int, str]) -> Dict[str, Dict[str, float]]:
    """Fraccion de obstaculo y de cielo por sector del recorte cuadrado (tercios, como la etiqueta)."""
    sq = square(mask)
    obst_ids = [i for i, n in names.items() if n in OBSTACLE]
    sky_ids = [i for i, n in names.items() if n == "sky"]
    h, w = sq.shape
    out: Dict[str, Dict[str, float]] = {}
    for ci, c in enumerate("ABC"):
        for ri, r in enumerate("123"):
            cell = sq[ri * h // 3:(ri + 1) * h // 3, ci * w // 3:(ci + 1) * w // 3]
            out[c + r] = {"obst": round(float(np.isin(cell, obst_ids).mean()), 4),
                          "sky": round(float(np.isin(cell, sky_ids).mean()), 4)}
    return out


def stage_run(args) -> None:
    import cv2
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    from ultralytics import YOLO

    bench = Path(args.bench)
    samples = [s for s in read_jsonl(bench / "samples_gt.jsonl")
               if (s.get("kind") == "scan") == args.scan and valid(s, ALIGN_MIN)]
    out_path = bench / RESULTS
    done = {r["id"] for r in read_jsonl(out_path)} if out_path.exists() else set()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    seg = YOLO(str(SEG_WEIGHTS))
    names = {int(k): v for k, v in seg.names.items()}
    proc = AutoImageProcessor.from_pretrained(DEPTH_MODEL)
    dmodel = AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL).to(dev).eval()
    print(f"[seg_depth] {len(samples)} muestras validas ({dev})", flush=True)
    for k, s in enumerate(samples):
        if s["id"] in done:
            continue
        img = cv2.imread(str(bench / s["replay"]["rgb"]))
        if img is None:
            continue
        h, w = img.shape[:2]
        t0 = time.time()
        r = seg(img, verbose=False)[0]
        mask = r.semantic_mask
        mask = mask.data if hasattr(mask, "data") else mask
        mask = mask.cpu().numpy() if hasattr(mask, "cpu") else np.asarray(mask)
        mask = cv2.resize(np.squeeze(mask).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
        t_seg = (time.time() - t0) * 1000.0
        t0 = time.time()
        with torch.no_grad():
            inp = proc(images=cv2.cvtColor(img, cv2.COLOR_BGR2RGB), return_tensors="pt").to(dev)
            pred = dmodel(**inp).predicted_depth
            pred = torch.nn.functional.interpolate(pred.unsqueeze(1), size=(h, w), mode="bilinear",
                                                   align_corners=False).squeeze().cpu().numpy()
        t_depth = (time.time() - t0) * 1000.0
        fr, ds = cell_fractions(mask, names), cell_stats(pred.astype(np.float32))
        rec = {"id": s["id"], "run": s["run"], "kind": s.get("kind"), "ms_seg": round(t_seg, 1), "ms_depth": round(t_depth, 1),
               "cells": {c: {"truth_open": bool(s["gt"]["cell_free"][c]), "p5": s["gt"]["cells"][c]["p5"],
                             "obst": fr[c]["obst"], "sky": fr[c]["sky"], "d_p5": ds[c]["p5"]} for c in CELLS}}
        append_jsonl(out_path, rec)
        if (k + 1) % 100 == 0:
            print(f"[seg_depth] {k + 1}/{len(samples)}", flush=True)
    print(f"[seg_depth] listo -> {out_path}")


def _rows(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"run": r["run"], "id": r["id"], "cell": c, **v} for r in recs for c, v in r["cells"].items()]


def _block(rows: List[Dict[str, Any]], title: str) -> List[str]:
    truth = [r["truth_open"] for r in rows]
    easy = [r for r in rows if r["p5"] < 5.0 or r["p5"] >= 40.0]
    lines = [f"### {title}", "", f"Sectores: {len(rows)} ({len({r['id'] for r in rows})} muestras); abiertos reales "
             f"{100 * np.mean(truth):.0f} %.", "",
             "| Senal | Exactitud bal. [IC 95 %] | AUC | AUC casos obvios | AUC fila 1 / 2 / 3 |", "|---|---|---:|---:|---|"]
    for name, score, pred in (
            ("depth: p5 estimado (libre >= 15 m)", lambda r: r["d_p5"], lambda r: r["d_p5"] >= FREE_M),
            ("seg: 1 - obstaculo (libre < 5 %)", lambda r: 1.0 - r["obst"], lambda r: r["obst"] < OBST_MAX_FRAC),
            ("seg: cielo (diag.)", lambda r: r["sky"], None)):
        a = auc([score(r) for r in rows], truth)
        ae = auc([score(r) for r in easy], [r["p5"] >= 40.0 for r in easy])
        by_row = " / ".join(
            f"{auc([score(r) for r in rows if r['cell'][1] == k], [r['truth_open'] for r in rows if r['cell'][1] == k]) or 0:.2f}"
            for k in "123")
        if pred is not None:
            for r in rows:
                r["pred_open"] = pred(r)
            ba = balanced_accuracy([r["pred_open"] for r in rows], truth)
            lo, hi = bootstrap_ci(rows)
            acc = f"{100 * ba:.0f} % [{100 * lo:.0f}-{100 * hi:.0f}]"
        else:
            acc = "-"
        lines.append(f"| {name} | {acc} | {a:.2f} | {ae:.2f} | {by_row} |")
    return lines + [""]


def stage_report(args) -> str:
    bench = Path(args.bench)
    recs = read_jsonl(bench / RESULTS)
    lines = ["## seg_depth_probe", "",
             f"Latencia mediana por imagen 1080x720 (GPU, compartida con Ollama): seg "
             f"{np.median([r['ms_seg'] for r in recs]):.0f} ms, depth {np.median([r['ms_depth'] for r in recs]):.0f} ms.", ""]
    singles = [r for r in recs if r.get("kind") != "scan"]
    lines += _block(_rows(singles), "Todas las muestras validas")
    # Las mismas 120 muestras que las preguntas del VLM (comparacion directa con grid_prod y region_probe).
    samples = [s for s in read_jsonl(bench / "samples_gt.jsonl") if s.get("kind") != "scan" and valid(s, ALIGN_MIN)]
    vlm_ids = {s["id"] for s in stratified([s for s in samples if s["gt"].get("center_free") is not None],
                                           lambda s: s["gt"]["center_free"], 60, 0)}
    lines += _block(_rows([r for r in singles if r["id"] in vlm_ids]), "Las 120 muestras de las preguntas del VLM")
    scans = [r for r in recs if r.get("kind") == "scan"]
    if scans:
        # Imagenes de barridos reales: la decision del barrido usa el sector central (B2).
        b2 = [{"run": r["run"], "id": r["id"], "cell": "B2", **r["cells"]["B2"]} for r in scans]
        lines += _block(b2, "Imagenes de barridos de deadlock (sector central B2, el que decide el rumbo)")
    text = "\n".join(lines)
    (bench / "seg_depth_report.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="stage", required=True)
    for name in ("run", "report"):
        sp = sub.add_parser(name)
        sp.add_argument("--bench", required=True)
        if name == "run":
            sp.add_argument("--scan", action="store_true", help="imagenes de barridos (kind=scan) en vez de las demas")
    args = ap.parse_args()
    {"run": stage_run, "report": stage_report}[args.stage](args)


if __name__ == "__main__":
    main()
