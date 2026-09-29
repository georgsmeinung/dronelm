# Cierre / reparacion de una corrida interrumpida (2026-0929).
#
# FlightLogger.close() y el cierre de video/visor corren al final de la corrida.
# Si el proceso muere antes (kill, segundo Ctrl+C, crash), quedan:
#   - un .csv de streaming SIN las columnas `state.*` (el aplanado se escribe en
#     close()) y, a veces, un .csv.tmp a medio escribir;
#   - un .webm sin indice ("File ended prematurely": no se puede hacer seek);
#   - ningun .viewer.html.
# El JSONL se escribe y se vacia ciclo a ciclo y conserva el estado anidado, asi que
# alcanza para reconstruir todo. Este modulo lo hace de forma idempotente.
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state_serializer import flatten_state

# Columnas minimas si no hay ningun CSV base (solo el JSONL).
_FALLBACK_COLUMNS = [
    "t", "cycle", "arm", "scenario", "seed", "route", "action", "wp_index", "dist_to_wp_m",
    "degraded", "pos_x", "pos_y", "pos_z", "vel_x", "vel_y", "vel_z", "yaw_deg", "pitch_deg",
    "roll_deg", "has_collided", "min_obstacle_dist_m",
]


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                break  # ultima linea truncada por el corte
    return out


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []


def _needs_csv(csv_path: Path, n_records: int) -> bool:
    rows = _read_csv(csv_path)
    if len(rows) < n_records or not rows:
        return True
    return not any(k.startswith("state.") for k in rows[0])


def rebuild_flat_csv(stem_path: Path, records: List[Dict[str, Any]]) -> int:
    """Reescribe `<stem>.csv` = columnas fijas del CSV de streaming + `state.*` del JSONL."""
    csv_path = stem_path.with_suffix(".csv")
    tmp_path = stem_path.with_suffix(".csv.tmp")

    # Base: el CSV con mas filas SIN contar sus columnas state.* (se recalculan).
    candidates = [_read_csv(csv_path), _read_csv(tmp_path)]
    base = max(candidates, key=len)
    fixed_cols: List[str] = []
    by_cycle: Dict[str, Dict[str, Any]] = {}
    if base:
        fixed_cols = [c for c in base[0].keys() if not c.startswith("state.")]
        for row in base:
            by_cycle[str(row.get("cycle"))] = {k: v for k, v in row.items() if not k.startswith("state.")}
    else:
        fixed_cols = list(_FALLBACK_COLUMNS)

    merged: List[Dict[str, Any]] = []
    extra: Dict[str, None] = {}
    for rec in records:
        key = str(rec.get("cycle"))
        row = dict(by_cycle.get(key) or {})
        if not row:  # sin CSV base para este ciclo: minimo desde el JSONL
            pos, vel = rec.get("pos") or {}, rec.get("vel") or {}
            row = {
                "t": rec.get("t"), "cycle": rec.get("cycle"), "arm": rec.get("arm"),
                "scenario": rec.get("scenario"), "seed": rec.get("seed"), "route": rec.get("route"),
                "action": rec.get("action"), "wp_index": rec.get("wp_index"),
                "dist_to_wp_m": rec.get("dist_to_wp_m"), "degraded": rec.get("degraded"),
                "pos_x": pos.get("x"), "pos_y": pos.get("y"), "pos_z": pos.get("z"),
                "vel_x": vel.get("vx"), "vel_y": vel.get("vy"), "vel_z": vel.get("vz"),
                "yaw_deg": rec.get("yaw_deg"), "pitch_deg": rec.get("pitch_deg"),
                "roll_deg": rec.get("roll_deg"),
                "has_collided": (rec.get("collision") or {}).get("has_collided"),
                "min_obstacle_dist_m": rec.get("min_obstacle_dist_m"),
            }
            for c in row:
                if c not in fixed_cols:
                    fixed_cols.append(c)
        flat = flatten_state(rec["state"]) if isinstance(rec.get("state"), dict) else {}
        for k in flat:
            extra.setdefault(k, None)
        row.update(flat)
        merged.append(row)

    cols = fixed_cols + sorted(extra)
    out_tmp = stem_path.with_suffix(".csv.rebuild")
    with open(out_tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)
    os.replace(out_tmp, csv_path)
    if tmp_path.exists():
        tmp_path.unlink()
    return len(merged)


def _video_frame_count(path: Path) -> int:
    """Frames que se pueden leer secuencialmente (el indice del contenedor puede faltar)."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    return n


def _video_is_finalized(path: Path) -> bool:
    import cv2

    cap = cv2.VideoCapture(str(path))
    count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return count > 0


def repair_video(video_path: Path, fps_hint: float = 5.0) -> int:
    """Recodifica un .webm sin indice a uno valido. Devuelve los frames escritos.

    El original se conserva como `<stem>.partial.webm`.
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or fps_hint
    ok, frame = cap.read()
    if not ok:
        cap.release()
        return 0
    h, w = frame.shape[:2]
    fixed = video_path.with_name(video_path.stem + ".repaired.webm")
    writer = cv2.VideoWriter(str(fixed), cv2.VideoWriter_fourcc(*"VP80"), max(1.0, fps), (w, h))
    n = 0
    while ok:
        writer.write(frame)
        n += 1
        ok, frame = cap.read()
    writer.release()
    cap.release()
    if n == 0 or not fixed.exists():
        return 0
    partial = video_path.with_name(video_path.stem + ".partial.webm")
    if partial.exists():
        partial.unlink()
    os.replace(video_path, partial)
    os.replace(fixed, video_path)
    return n


def finalize_run(run_dir: str, force: bool = False, log=print) -> Dict[str, Any]:
    """Deja una corrida con CSV aplanado, video valido y viewer.html. Idempotente.

    Solo toca lo que esta incompleto (salvo force=True). Devuelve un reporte.
    """
    from .flight_viewer import write_viewer_html

    d = Path(run_dir)
    report: Dict[str, Any] = {"run_dir": str(d), "csv": "ok", "video": "ok", "viewer": "ok"}
    jsonls = sorted(d.glob("*.jsonl"))
    if not jsonls:
        report.update(csv="sin_jsonl", video="-", viewer="-")
        return report
    jsonl = jsonls[0]
    records = _read_jsonl(jsonl)

    csv_path = jsonl.with_suffix(".csv")
    if force or _needs_csv(csv_path, len(records)) or jsonl.with_suffix(".csv.tmp").exists():
        n = rebuild_flat_csv(jsonl, records)
        report["csv"] = f"reconstruido ({n} filas)"
        log(f"[finalize] {d.name}: CSV aplanado reconstruido ({n} filas).")

    video = jsonl.with_suffix(".webm")
    n_frames = 0
    if video.exists():
        if force or not _video_is_finalized(video):
            n_frames = repair_video(video)
            report["video"] = f"reparado ({n_frames} frames)" if n_frames else "irrecuperable"
            log(f"[finalize] {d.name}: video {report['video']}.")
        else:
            n_frames = 1
    else:
        report["video"] = "sin_video"

    # Video de la camara externa (FollowCam), si la corrida lo grabo.
    follow = jsonl.with_name(jsonl.stem + ".follow.webm")
    follow_name = None
    report["follow"] = "-"
    if follow.exists():
        follow_ok = _video_is_finalized(follow)
        if force or not follow_ok:
            nf = repair_video(follow)
            report["follow"] = f"reparado ({nf} frames)" if nf else "irrecuperable"
            log(f"[finalize] {d.name}: FollowCam {report['follow']}.")
            follow_ok = nf > 0
        else:
            report["follow"] = "ok"
        follow_name = follow.name if follow_ok else None

    viewer = jsonl.with_suffix(".viewer.html")
    if n_frames > 0 and (force or not viewer.exists() or report["csv"] != "ok" or report["video"] != "ok"
                         or report["follow"] not in ("-", "ok")):
        write_viewer_html(str(viewer), video_filename=video.name, csv_path=str(csv_path), jsonl_path=str(jsonl),
                          follow_video_filename=follow_name)
        report["viewer"] = "generado"
        log(f"[finalize] {d.name}: viewer.html generado.")
    elif n_frames == 0:
        report["viewer"] = "sin_video"
    return report


def needs_finalize(run_dir: str) -> bool:
    """True si la corrida tiene artefactos incompletos (barato: no decodifica video)."""
    d = Path(run_dir)
    jsonls = sorted(d.glob("*.jsonl"))
    if not jsonls:
        return False
    j = jsonls[0]
    if j.with_suffix(".csv.tmp").exists() or (j.with_suffix(".webm").exists() and not j.with_suffix(".viewer.html").exists()):
        return True
    header = ""
    try:
        with open(j.with_suffix(".csv"), encoding="utf-8") as fh:
            header = fh.readline()
    except OSError:
        return True
    return "state." not in header


def find_runs(root: str) -> List[str]:
    """Directorios de corrida (con .jsonl) bajo `root`."""
    return sorted({str(p.parent) for p in Path(root).rglob("*.jsonl")})
