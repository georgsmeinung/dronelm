"""Prueba de percepcion del mapa cenital: distingue el VLM un parche de calle de uno de techo? (2026-10-02)

Antes de cualquier forma de preguntar por una RUTA, se mide si el modelo reconoce lo que hay en un lugar
del mapa. Si no distingue ni un parche de calle de uno de edificio, ninguna pregunta sobre la ruta lo
arregla.

Etapas:
  label  (AirSim, herramienta de laboratorio fuera del lazo de vuelo; como ground_truth.py): sortea centros
         de parche en la zona de la mision, pone la camara mirando hacia abajo a WARM_ALT_M sobre cada uno y
         lee la profundidad planar. Altura de la superficie = altura de la camara - profundidad. Etiqueta de
         referencia del parche (cuadrado central de PATCH_M):
           ground  si menos del 10 % de los pixeles esta a mas de RAISED_M sobre el suelo
           raised  si mas del 70 % lo esta (edificio, autopista elevada, arboles altos)
           mixed   en otro caso (no se usa)
         El suelo es el percentil 10 de las medianas de altura de todos los parches.
  ask    (sin AirSim): recorta el mapa cenital alrededor de cada parche (CONTEXT_M de lado, cuadrado rojo
         en los PATCH_M centrales) y hace tres preguntas con cada modelo:
           yesno   "is the area inside the red square at street level?" yes/no
           pair    "street or building?", en los dos ordenes (mide sesgo por posicion)
           multi   street / building / trees / parking / elevated road
         Lee la respuesta y la probabilidad (logprobs) de "a nivel de calle".

Uso:
    python experiments/vlm_bench/map_probe.py label --n 160
    python experiments/vlm_bench/map_probe.py ask --models liquidai/lfm2.5-vl-1.6b qwen/qwen2.5-vl-3b
    python experiments/vlm_bench/map_probe.py report
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DEFAULT_BENCH_DIR, ROOT, append_jsonl, choice_probs_at, encode_jpeg, image_part,  # noqa: E402
                    parse_json, query_vlm, read_jsonl, text_part, value_offsets)

sys.path.insert(0, str(ROOT))
from src.planning import route_planner as rp  # noqa: E402

OUT = DEFAULT_BENCH_DIR / "map_probe"
MISSION = ROOT.parent / "airsim-plan" / "missions" / "flightplans" / "citysim_pilot.json"
PATCH_M = rp.ROUTE_PATCH_M
CONTEXT_M = rp.ROUTE_PATCH_CONTEXT_M
WARM_ALT_M = 40.0
RAISED_M = 3.0
AREA_MARGIN_M = 100.0
IMAGE_PX = rp.ROUTE_PATCH_PX

# La pregunta de cinco clases es la del planificador (route_planner.PATCH_*).
SYSTEM = rp.PATCH_SYSTEM
MULTI = rp.PATCH_CLASSES
GROUND_CLASSES = rp.PATCH_GROUND


def _schema(name: str, choices: List[str]) -> Dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": {
        "type": "object", "properties": {"answer": {"type": "string", "enum": choices}},
        "required": ["answer"], "additionalProperties": False}}}


QUESTIONS = {
    "yesno": ("Is the area inside the red square at street level (street, parking or open ground), not a "
              "building, trees or an elevated road? yes or no.", ["yes", "no"], {"yes"}),
    "pair_sb": ("What is inside the red square: street or building?", ["street", "building"], {"street"}),
    "pair_bs": ("What is inside the red square: building or street?", ["building", "street"], {"street"}),
    "multi": (rp.PATCH_PROMPT, MULTI, GROUND_CLASSES),
}


# --------------------------------------------------------------------------- etapa label (AirSim)
def stage_label(args) -> None:
    try:
        import cosysairsim as airsim  # type: ignore
    except Exception:  # pragma: no cover
        import airsim  # type: ignore

    vehicle = os.environ["AIRSIM_VEHICLE_NAME"]
    camera = os.getenv("AIRSIM_CAMERA_NAME", "0")
    flight_fov = float(os.getenv("CAMERA_HFOV_DEG", "90.0"))
    manifest = json.loads(MISSION.read_text(encoding="utf-8"))
    pts = [(0.0, 0.0)] + [(float(w["x"]), float(w["y"])) for w in manifest["waypoints"]]
    x0, x1 = min(p[0] for p in pts) - AREA_MARGIN_M, max(p[0] for p in pts) + AREA_MARGIN_M
    y0, y1 = min(p[1] for p in pts) - AREA_MARGIN_M, max(p[1] for p in pts) + AREA_MARGIN_M
    rng = random.Random(args.seed)
    centers = [(round(rng.uniform(x0, x1), 1), round(rng.uniform(y0, y1), 1)) for _ in range(args.n)]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "photos").mkdir(exist_ok=True)
    raw_path = OUT / "patches_raw.jsonl"
    done = {(r["x"], r["y"]) for r in read_jsonl(raw_path)} if raw_path.exists() else set()
    depth_type = getattr(airsim.ImageType, "DepthPlanar", getattr(airsim.ImageType, "DepthPlanner", None))
    req = [airsim.ImageRequest(camera, airsim.ImageType.Scene, False, False),
           airsim.ImageRequest(camera, depth_type, True, False)]

    client = airsim.MultirotorClient(timeout_value=30)
    client.confirmConnection()
    orig = client.simGetVehiclePose(vehicle_name=vehicle)
    fov = math.degrees(2 * math.atan(PATCH_M / 2 / WARM_ALT_M))
    client.simSetCameraPose(camera, airsim.Pose(airsim.Vector3r(0, 0, 0), airsim.euler_to_quaternion(0, math.radians(-90), 0)),
                            vehicle_name=vehicle)
    client.simSetCameraFov(camera, fov, vehicle_name=vehicle)

    def hold(x, y, seconds):
        pose = airsim.Pose(airsim.Vector3r(x, y, -WARM_ALT_M), airsim.euler_to_quaternion(0, 0, 0))
        t0 = time.time()
        while True:
            client.simSetVehiclePose(pose, True, vehicle_name=vehicle)
            if time.time() - t0 >= seconds:
                return
            time.sleep(0.25)

    try:
        for i, (x, y) in enumerate(centers):
            if (x, y) in done:
                continue
            hold(x, y, 2.0)
            prev = None
            for _ in range(6):
                r = client.simGetImages(req, vehicle_name=vehicle)
                depth = np.array(r[1].image_data_float, np.float32).reshape(r[1].height, r[1].width)
                height = WARM_ALT_M - depth            # altura de la superficie respecto de z = 0 (NED)
                med = float(np.median(height))
                if prev is not None and abs(med - prev) < 0.1:
                    break
                prev = med
                hold(x, y, 0.75)
            img = np.frombuffer(r[0].image_data_uint8, np.uint8).reshape(r[0].height, r[0].width, 3)[:, :, ::-1]
            import cv2

            photo = f"photos/p{i:03d}.jpg"
            cv2.imwrite(str(OUT / photo), np.ascontiguousarray(img), [cv2.IMWRITE_JPEG_QUALITY, 88])
            small = cv2.resize(height, (32, 32), interpolation=cv2.INTER_AREA)
            append_jsonl(raw_path, {"id": f"p{i:03d}", "x": x, "y": y, "photo": photo,
                                    "height_p10": round(float(np.percentile(height, 10)), 2),
                                    "height_p50": round(med, 2), "height_p90": round(float(np.percentile(height, 90)), 2),
                                    "heights_32": np.round(small, 1).tolist()})
            print(f"[label] {i + 1}/{len(centers)} ({x:.0f}, {y:.0f}) mediana {med:.1f} m", flush=True)
    finally:
        client.simSetCameraPose(camera, airsim.Pose(airsim.Vector3r(0, 0, 0), airsim.euler_to_quaternion(0, 0, 0)),
                                vehicle_name=vehicle)
        client.simSetCameraFov(camera, flight_fov, vehicle_name=vehicle)
        client.simSetVehiclePose(orig, True, vehicle_name=vehicle)

    rows = read_jsonl(raw_path)
    ground = float(np.percentile([r["height_p50"] for r in rows], 10))
    labeled = []
    for r in rows:
        frac = float(np.mean(np.array(r["heights_32"]) > ground + RAISED_M))
        label = "ground" if frac < 0.10 else "raised" if frac > 0.70 else "mixed"
        labeled.append({**{k: v for k, v in r.items() if k != "heights_32"}, "raised_frac": round(frac, 3),
                        "ground_z": round(ground, 2), "label": label})
    (OUT / "patches.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labeled), encoding="utf-8")
    from collections import Counter

    print(f"[label] suelo {ground:.1f} m; etiquetas {dict(Counter(r['label'] for r in labeled))}")


# --------------------------------------------------------------------------- etapa ask (VLM)
def map_crop(mv: "rp.MapView", x: float, y: float) -> Any:
    """El mismo recorte que usa el planificador (route_planner.patch_crop)."""
    return rp.patch_crop(mv, x, y, size=IMAGE_PX, context_m=CONTEXT_M, patch_m=PATCH_M)


def ask_one(img, qname: str, model: str) -> Dict[str, Any]:
    prompt, choices, ground = QUESTIONS[qname]
    r = query_vlm(SYSTEM, [text_part(prompt), image_part(encode_jpeg(img, IMAGE_PX))], _schema(qname, choices),
                  max_tokens=16, model=model)
    ans = (parse_json(r["text"]) or {}).get("answer")
    offs = value_offsets(r["text"], "answer")
    probs = choice_probs_at(r["tokens"], offs[0], choices) if offs and r["tokens"] else None
    p_ground = sum(probs[c] for c in choices if c in ground) if probs else None
    return {"answer": ans, "p_ground": None if p_ground is None else round(p_ground, 4),
            "pred_ground": None if ans is None else ans in ground, "latency_ms": round(r["latency_ms"], 1),
            "error": r["error"]}


def stage_ask(args) -> None:
    rows = [r for r in read_jsonl(OUT / "patches.jsonl") if r["label"] in ("ground", "raised")]
    rng = random.Random(args.seed)
    by = {lab: [r for r in rows if r["label"] == lab] for lab in ("ground", "raised")}
    k = min(args.per_class, *(len(v) for v in by.values()))
    sample = rng.sample(by["ground"], k) + rng.sample(by["raised"], k)
    manifest = json.loads(MISSION.read_text(encoding="utf-8"))
    mv = rp.MapView.load(manifest["map"])
    import cv2

    (OUT / "crops").mkdir(parents=True, exist_ok=True)
    res_path = OUT / "answers.jsonl"
    done = {(r["model"], r["id"], r["question"]) for r in read_jsonl(res_path)} if res_path.exists() else set()
    print(f"[ask] {k} parches por clase")
    for model in args.models:
        for s in sample:
            img = map_crop(mv, s["x"], s["y"])
            cv2.imwrite(str(OUT / "crops" / f"{s['id']}.jpg"), img)
            for q in QUESTIONS:
                if (model, s["id"], q) in done:
                    continue
                a = ask_one(img, q, model)
                append_jsonl(res_path, {"model": model, "id": s["id"], "question": q, "label": s["label"], **a})
        print(f"[ask] {model} listo", flush=True)


# --------------------------------------------------------------------------- reporte
def _auc(scores: List[float], pos: List[bool]) -> Optional[float]:
    p = [s for s, y in zip(scores, pos) if y]
    n = [s for s, y in zip(scores, pos) if not y]
    if not p or not n:
        return None
    wins = sum((a > b) + 0.5 * (a == b) for a in p for b in n)
    return wins / (len(p) * len(n))


def stage_report(args) -> None:
    from collections import Counter, defaultdict

    rows = read_jsonl(OUT / "answers.jsonl")
    groups = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["question"])].append(r)
    lines = ["| Modelo | Pregunta | n | Exactitud bal. | AUC P(calle) | Respuestas |", "|---|---|---:|---:|---:|---|"]
    for (model, q), g in sorted(groups.items()):
        ok = [r for r in g if r["pred_ground"] is not None]
        tpr = np.mean([r["pred_ground"] for r in ok if r["label"] == "ground"]) if ok else float("nan")
        tnr = np.mean([not r["pred_ground"] for r in ok if r["label"] == "raised"]) if ok else float("nan")
        sc = [r for r in g if r["p_ground"] is not None]
        auc = _auc([r["p_ground"] for r in sc], [r["label"] == "ground" for r in sc])
        dist = ", ".join(f"{a} {c}" for a, c in Counter(r["answer"] for r in g).most_common())
        lines.append(f"| {model.split('/')[-1]} | {q} | {len(g)} | {0.5 * (tpr + tnr):.2f} | "
                     f"{'-' if auc is None else f'{auc:.2f}'} | {dist} |")
    # consistencia del par en los dos ordenes
    lines += ["", "| Modelo | Par: misma respuesta en los dos ordenes |", "|---|---:|"]
    for model in sorted({r["model"] for r in rows}):
        a = {r["id"]: r["answer"] for r in rows if r["model"] == model and r["question"] == "pair_sb"}
        b = {r["id"]: r["answer"] for r in rows if r["model"] == model and r["question"] == "pair_bs"}
        common = [i for i in a if i in b]
        same = np.mean([a[i] == b[i] for i in common]) if common else float("nan")
        lines.append(f"| {model.split('/')[-1]} | {same:.2f} ({len(common)}) |")
    text = "\n".join(lines)
    (OUT / "report.md").write_text(text + "\n", encoding="utf-8")
    print(text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="stage", required=True)
    a = sub.add_parser("label")
    a.add_argument("--n", type=int, default=160)
    a.add_argument("--seed", type=int, default=0)
    b = sub.add_parser("ask")
    b.add_argument("--models", nargs="+", default=[os.getenv("LOCAL_LLM_MODEL_NAME", "phi3")])
    b.add_argument("--per-class", type=int, default=30)
    b.add_argument("--seed", type=int, default=0)
    sub.add_parser("report")
    args = ap.parse_args()
    {"label": stage_label, "ask": stage_ask, "report": stage_report}[args.stage](args)


if __name__ == "__main__":
    main()
