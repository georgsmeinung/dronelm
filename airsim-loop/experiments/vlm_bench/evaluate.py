"""Hace las preguntas del catalogo al VLM sobre las muestras con etiqueta de referencia.

Seleccion: solo muestras validas (camara fuera de la geometria, captura estable y, si hay con que
compararla, pose bien reproducida: correlacion >= --align-min). Para cada pregunta se toman hasta
--per-class muestras por clase verdadera (estratificado, semilla fija), asi una pregunta no se aprueba
contestando siempre la clase mayoritaria. Los barridos se evaluan todos.

Cada consulta va con decodificacion restringida (el esquema de la pregunta) y temperatura 0, y guarda la
probabilidad de cada opcion leida de los logprobs. Reanudable: lo ya hecho en results.jsonl no se repite.

Uso:
    python experiments/vlm_bench/evaluate.py --bench ../airsim-runs/vlm_bench/v1 --sizes 384 672
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LOCAL_LLM_MODEL_NAME, append_jsonl, choice_probs_at, parse_json, query_vlm, read_jsonl, value_offsets  # noqa: E402
from questions import CELLS, QUESTION_NAMES, GridQuestion, ScanQuestion, SingleQuestion, catalog  # noqa: E402

ALIGN_MIN = 0.5


def valid(s: Dict[str, Any], align_min: float = ALIGN_MIN) -> bool:
    rp = s.get("replay") or {}
    if s["gt"].get("inside") or not rp.get("stable"):
        return False
    a = rp.get("align_ncc")
    return a is None or a >= align_min


def scan_groups(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        if s.get("kind") == "scan":
            by[s["scan_id"]].append(s)
    out = []
    for sid, members in by.items():
        members.sort(key=lambda m: m["scan_img"])
        if len(members) < 2:
            continue
        out.append({"id": sid, "kind": "scan_group", "run": members[0]["run"], "pose": members[0]["pose"],
                    "goal": members[0].get("goal"), "members": [m["id"] for m in members],
                    "member_samples": members,
                    "gt": {"img_free": [m["gt"]["center_free"] for m in members],
                           "inside": any(m["gt"]["inside"] for m in members)},
                    "replay": {"stable": all(m["replay"]["stable"] for m in members), "align_ncc": None}})
    return out


def stratified(samples: List[Dict[str, Any]], key, per_class: int, seed: int = 0) -> List[Dict[str, Any]]:
    by: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        by[key(s)].append(s)
    rng = random.Random(seed)
    out = []
    for k in sorted(by, key=str):
        group = sorted(by[k], key=lambda s: s["id"])
        rng.shuffle(group)
        out += group[:per_class]
    return out


def load_images(sample: Dict[str, Any], bench: Path, source: str) -> Optional[List[Any]]:
    import cv2

    members = sample.get("member_samples") or [sample]
    imgs = []
    for m in members:
        if source == "photo":
            if not m.get("photo"):
                return None
            img = cv2.imread(str(Path(m["run_dir"]) / m["photo"]))
        else:
            img = cv2.imread(str(bench / m["replay"]["rgb"]))
        if img is None:
            return None
        imgs.append(img)
    return imgs


def read_answer(q, sample: Dict[str, Any], text: str, tokens: List[Any]) -> Dict[str, Any]:
    data = parse_json(text)
    if isinstance(q, SingleQuestion):
        ans = (data or {}).get("respuesta")
        offs = value_offsets(text, "respuesta")
        probs = choice_probs_at(tokens, offs[0], q.choices) if offs and tokens else None
        return {"answer": ans, "probs": probs, "truth": q.truth(sample)}
    if isinstance(q, GridQuestion):
        sect = (data or {}).get("sectores") or {}
        probs_by_label = {}
        for lab in CELLS:
            offs = value_offsets(text, lab)
            probs_by_label[lab] = choice_probs_at(tokens, offs[0], q.choices) if offs and tokens else None
        labels = q.labels(sample) or {c: c for c in CELLS}
        return {"answer": q.physical(sample, sect),
                "probs": {pos: probs_by_label.get(lab) for pos, lab in labels.items()},
                "truth": {c: ("libre" if sample["gt"]["cell_free"][c] else "bloqueado") for c in CELLS}}
    # barrido
    rumbos = (data or {}).get("rumbos") or []
    order = q.order(sample)
    offs = value_offsets(text, "ok", quoted=False)
    n = len(sample["members"])
    ok_by_member: List[Optional[bool]] = [None] * n
    p_by_member: List[Optional[float]] = [None] * n
    for k, member_idx in enumerate(order):
        if k < len(rumbos) and isinstance(rumbos[k], dict):
            ok_by_member[member_idx] = rumbos[k].get("ok")
        if k < len(offs) and tokens:
            pr = choice_probs_at(tokens, offs[k], ["true", "false"])
            p_by_member[member_idx] = pr["true"] if pr else None
    return {"answer": ok_by_member, "probs": p_by_member, "truth": [v == "si" for v in sample["gt"]["img_free"]],
            "degradada": (data or {}).get("degradada")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", required=True)
    ap.add_argument("--questions", nargs="+", default=QUESTION_NAMES, choices=QUESTION_NAMES)
    ap.add_argument("--sizes", nargs="+", type=int, default=[384])
    ap.add_argument("--source", choices=["replay", "photo"], default="replay")
    ap.add_argument("--per-class", type=int, default=60)
    ap.add_argument("--align-min", type=float, default=ALIGN_MIN)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    bench = Path(args.bench)
    all_samples = read_jsonl(bench / "samples_gt.jsonl")
    singles = [s for s in all_samples if s.get("kind") != "scan" and valid(s, args.align_min)]
    groups = [g for g in scan_groups(all_samples) if valid(g, args.align_min)]
    if args.source == "photo":
        singles = [s for s in singles if s.get("photo")]
    out_path = bench / "results.jsonl"
    done = {(r["question"], r["id"], r["size"], r["source"]) for r in read_jsonl(out_path)}
    cat = catalog()
    print(f"[eval] modelo {LOCAL_LLM_MODEL_NAME}; {len(singles)} muestras validas, {len(groups)} barridos "
          f"(de {len(all_samples)} con etiqueta de referencia)")

    for qname in args.questions:
        q = cat[qname]
        if isinstance(q, ScanQuestion):
            chosen = groups
        elif isinstance(q, GridQuestion):
            chosen = stratified([s for s in singles if q.applies(s)], lambda s: s["gt"]["center_free"],
                                args.per_class, args.seed)
        else:
            chosen = stratified([s for s in singles if q.applies(s)], q.truth, args.per_class, args.seed)
        print(f"[eval] {qname}: {len(chosen)} muestras", flush=True)
        for size in args.sizes:
            for s in chosen:
                key = (qname, s["id"], size, args.source)
                if key in done:
                    continue
                imgs = load_images(s, bench, args.source)
                req = q.build(s, imgs, size) if imgs else None
                if req is None:
                    continue
                r = query_vlm(req["system"], req["parts"], req["schema"], max_tokens=req["max_tokens"])
                rec = {"question": qname, "id": s["id"], "run": s["run"], "kind": s.get("kind"), "size": size,
                       "source": args.source, "model": LOCAL_LLM_MODEL_NAME, "latency_ms": round(r["latency_ms"], 1),
                       "error": r["error"], "finish_reason": r["finish_reason"], "text": r["text"]}
                if not r["error"]:
                    rec.update(read_answer(q, s, r["text"], r["tokens"]))
                append_jsonl(out_path, rec)
    print(f"[eval] listo -> {out_path}")


if __name__ == "__main__":
    main()
