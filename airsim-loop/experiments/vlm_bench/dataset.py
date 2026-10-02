"""Dataset del banco: muestras tomadas de las corridas que tienen los dos videos (frontal y FollowCam).

Cada muestra es una pose registrada en vuelo (x, y, z, yaw, pitch, roll), con la meta real activa en ese
ciclo. Hay tres clases de muestra:

  - strategic: cada consulta de la capa estrategica (ancla de `_vlm_strategic`), con la respuesta que dio
    el VLM en vuelo y la foto cruda que se le envio (photo-<ts>.png).
  - scan: cada barrido panoramico (las fotos de un deadlock que no son de la capa estrategica, agrupadas),
    con una entrada por rumbo.
  - trajectory: ciclos de vuelo (altitud >= MIN_ALT_M) sin consulta, de-duplicados por celda de pose
    (2 m, 2 m, 2 m, 20 deg): el dron trabado cientos de ciclos en el mismo lugar cuenta una sola vez.

De los videos se extraen, por muestra, el fotograma frontal (lo que registro el dron, con el HUD) y el de
la FollowCam (contexto para auditoria visual): el video tiene un cuadro por ciclo, cuadro = ciclo - 1.

Uso:
    python experiments/vlm_bench/dataset.py --runs ../airsim-runs/produccion --out ../airsim-runs/vlm_bench/v1
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import append_jsonl, read_jsonl  # noqa: E402

MIN_ALT_M = 4.5
DEDUP_XYZ_M = 2.0
DEDUP_YAW_DEG = 20.0
SCAN_GAP_S = 30.0
PHOTO_MATCH_TOL_S = 0.6

_PHOTO_RE = re.compile(r"photo-(\d{8}T\d{6}\.\d{3})Z(?:-\d+)?\.png$")


def find_runs(roots: Iterable[Path]) -> List[Path]:
    """Directorios de corrida con <stem>.jsonl, <stem>.webm y <stem>.follow.webm."""
    out = []
    for root in roots:
        for follow in sorted(Path(root).rglob("*.follow.webm")):
            stem = follow.name[: -len(".follow.webm")]
            d = follow.parent
            if (d / f"{stem}.webm").exists() and (d / f"{stem}.jsonl").exists():
                out.append(d / stem)
    return out


def photo_ts(name: str) -> Optional[float]:
    m = _PHOTO_RE.search(name)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%S.%f").replace(tzinfo=timezone.utc).timestamp()


def real_goal(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    wps = state.get("waypoints") or []
    idx = int(state.get("current_wp_index") or 0)
    for w in wps[idx:]:
        if isinstance(w, dict) and not w.get("is_temporary"):
            return {"label": w.get("label"), "x": float(w["x"]), "y": float(w["y"]), "z": float(w.get("z", -10.0))}
    return None


def _pose(rec: Dict[str, Any]) -> Dict[str, float]:
    p = rec.get("pos") or {}
    return {"x": float(p.get("x", 0.0)), "y": float(p.get("y", 0.0)), "z": float(p.get("z", 0.0)),
            "yaw_deg": float(rec.get("yaw_deg") or 0.0), "pitch_deg": float(rec.get("pitch_deg") or 0.0),
            "roll_deg": float(rec.get("roll_deg") or 0.0)}


def _tel_ts(rec: Dict[str, Any]) -> Optional[float]:
    t = ((rec.get("state") or {}).get("telemetry") or {}).get("timestamp")
    return float(t) if t is not None else None


def nearest_record(records: List[Dict[str, Any]], ts: float, tol_s: float = PHOTO_MATCH_TOL_S
                   ) -> Optional[Dict[str, Any]]:
    best, bd = None, None
    for r in records:
        t = _tel_ts(r)
        if t is None:
            continue
        d = abs(t - ts)
        if bd is None or d < bd:
            best, bd = r, d
    return best if bd is not None and bd <= tol_s else None


def pose_key(p: Dict[str, float]) -> Tuple[int, int, int, int]:
    return (int(math.floor(p["x"] / DEDUP_XYZ_M)), int(math.floor(p["y"] / DEDUP_XYZ_M)),
            int(math.floor(p["z"] / DEDUP_XYZ_M)), int(math.floor(((p["yaw_deg"] + 360.0) % 360.0) / DEDUP_YAW_DEG)))


def group_scans(ts_list: List[float], gap_s: float = SCAN_GAP_S) -> List[List[float]]:
    groups: List[List[float]] = []
    for t in sorted(ts_list):
        if groups and t - groups[-1][-1] <= gap_s:
            groups[-1].append(t)
        else:
            groups.append([t])
    return groups


def samples_for_run(stem_path: Path) -> List[Dict[str, Any]]:
    run_dir, stem = stem_path.parent, stem_path.name
    records = read_jsonl(run_dir / f"{stem}.jsonl")
    run_id = stem_path.relative_to(stem_path.parents[4]).as_posix() if len(stem_path.parents) > 4 else stem
    samples: List[Dict[str, Any]] = []
    used_cycles = set()

    def base(rec: Dict[str, Any], kind: str) -> Dict[str, Any]:
        return {"run": run_id, "run_dir": str(run_dir.resolve()), "stem": stem, "kind": kind, "cycle": int(rec["cycle"]),
                "t": rec.get("t"), "ts": _tel_ts(rec), "pose": _pose(rec), "goal": real_goal(rec.get("state") or {})}

    photos = {}
    for p in sorted(run_dir.glob("photo-*.png")):
        ts = photo_ts(p.name)
        if ts is not None:
            photos[round(ts, 3)] = p.name

    # 1) consultas estrategicas: una por ancla distinta
    seen_anchor = set()
    for rec in records:
        vs = (rec.get("state") or {}).get("_vlm_strategic")
        if not isinstance(vs, dict) or not isinstance(vs.get("anchor"), dict):
            continue
        a = vs["anchor"]
        key = round(float(a.get("ts", 0.0)), 3)
        if key in seen_anchor:
            continue
        seen_anchor.add(key)
        src = nearest_record(records, key) or rec
        s = base(src, "strategic")
        s["pose"].update({"x": float(a["x"]), "y": float(a["y"]), "yaw_deg": float(a["yaw_deg"])})
        s["ts"] = key
        s["photo"] = photos.pop(key, None)
        s["inflight"] = {"outcome": vs.get("outcome"), "goal_cell": vs.get("goal_cell"),
                         "sectores": (vs.get("parsed") or {}).get("sectores"), "latency_ms": vs.get("latency_ms")}
        s["id"] = f"{stem}_c{s['cycle']:04d}_st"
        samples.append(s)
        used_cycles.add(s["cycle"])

    # 2) barridos: el resto de las fotos, agrupadas por cercania en el tiempo
    for gi, group in enumerate(group_scans(list(photos.keys()))):
        scan_id = f"{stem}_scan{gi:02d}"
        for k, ts in enumerate(group):
            rec = nearest_record(records, ts)
            if rec is None:
                continue
            s = base(rec, "scan")
            s.update({"ts": ts, "photo": photos[ts], "scan_id": scan_id, "scan_img": k + 1,
                      "id": f"{scan_id}_img{k + 1}"})
            samples.append(s)
            used_cycles.add(s["cycle"])

    # 3) trayectoria: poses de vuelo sin consulta, de-duplicadas
    seen = set()
    for rec in records:
        if int(rec.get("cycle", 0)) in used_cycles or not rec.get("pos"):
            continue
        p = _pose(rec)
        if -p["z"] < MIN_ALT_M:
            continue
        k = pose_key(p)
        if k in seen:
            continue
        seen.add(k)
        s = base(rec, "trajectory")
        s["id"] = f"{stem}_c{s['cycle']:04d}_tr"
        samples.append(s)
    return samples


def extract_video_frames(stem_path: Path, samples: List[Dict[str, Any]], frames_dir: Path) -> None:
    """Guarda el cuadro frontal y el de FollowCam de cada muestra (cuadro = ciclo - 1)."""
    import cv2

    wanted = {}
    for s in samples:
        wanted.setdefault(s["cycle"] - 1, []).append(s)
    for suffix, tag in ((".webm", "onboard"), (".follow.webm", "follow")):
        cap = cv2.VideoCapture(str(stem_path.parent / f"{stem_path.name}{suffix}"))
        idx = 0
        last = max(wanted) if wanted else -1
        while idx <= last:
            ok, frame = cap.read()
            if not ok:
                break
            for s in wanted.get(idx, []):
                name = f"{s['id']}_{tag}.jpg"
                cv2.imwrite(str(frames_dir / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                s[f"{tag}_frame"] = name
            idx += 1
        cap.release()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True, help="raices donde buscar corridas")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-video", action="store_true", help="no extraer cuadros de los videos")
    args = ap.parse_args()

    out = Path(args.out)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    samples_path = out / "samples.jsonl"
    if samples_path.exists():
        samples_path.unlink()
    runs = find_runs([Path(r) for r in args.runs])
    print(f"[dataset] {len(runs)} corridas con los dos videos")
    total = {}
    for stem_path in runs:
        samples = samples_for_run(stem_path)
        if not args.no_video:
            extract_video_frames(stem_path, samples, frames_dir)
        for s in samples:
            append_jsonl(samples_path, s)
            total[s["kind"]] = total.get(s["kind"], 0) + 1
        print(f"[dataset] {stem_path.name}: {len(samples)} muestras")
    print(f"[dataset] total {sum(total.values())} {total} -> {samples_path}")


if __name__ == "__main__":
    main()
