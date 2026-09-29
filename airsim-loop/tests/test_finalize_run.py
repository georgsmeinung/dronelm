"""Reparacion de corridas interrumpidas (2026-0929)."""
from __future__ import annotations

import csv
import json

import numpy as np

from src.logging import FlightLogger, FlightVideoRecorder
from src.logging.finalize_run import finalize_run, needs_finalize


def _state(c):
    return {
        "telemetry": {"position": {"x": c * 0.1, "y": 0.0, "z": -6.0}, "velocity": {"vx": 0.5, "vy": 0, "vz": 0},
                      "orientation": {"yaw": 0.0}, "collision": {"has_collided": False, "object_name": ""}},
        "waypoint_guidance": {"distance": 30.0 - c}, "obstacle_field": None, "route": "reactive",
        "next_action": "MANTENER_RUMBO", "current_wp_index": 0, "deliberations": [],
        "rgb_image": np.full((48, 64, 3), c * 5, dtype=np.uint8),
    }


def _make_interrupted_run(tmp_path, n=25):
    """Corrida cortada: sin close() del logger, .csv.tmp a medias y .webm truncado."""
    out = tmp_path / "run" / "run.jsonl"
    lg = FlightLogger(str(out), scenario="S", seed=1, arm="slm")
    vr = FlightVideoRecorder(str(out.with_suffix(".webm")), (64, 48), 5.0, scale=1.0)
    for c in range(1, n + 1):
        st = _state(c)
        lg.log_cycle(st, latency_ms={"graph": 100.0})
        vr.write_frame(st["rgb_image"])
    vr.close()
    lg._fh.close()
    lg._csv_fh.close()          # sin _write_flat_csv: solo el CSV de streaming
    # .csv.tmp parcial (corte durante el reemplazo) y video sin indice (truncado)
    out.with_suffix(".csv.tmp").write_text("t,cycle\n0.1,1\n", encoding="utf-8")
    data = out.with_suffix(".webm").read_bytes()
    out.with_suffix(".webm").write_bytes(data[: int(len(data) * 0.7)])
    return out


def test_finalize_rebuilds_csv_video_and_viewer(tmp_path):
    out = _make_interrupted_run(tmp_path)
    assert needs_finalize(str(out.parent))
    rep = finalize_run(str(out.parent), log=lambda *_: None)

    rows = list(csv.DictReader(open(out.with_suffix(".csv"), encoding="utf-8")))
    assert len(rows) == 25
    assert rows[3]["state.telemetry.position.z"] == "-6.0"
    assert rows[3]["state.waypoint_guidance.distance"] == "26.0"
    assert rows[3]["latency_graph_ms"] == "100.0"          # columnas fijas del streaming se conservan
    assert not out.with_suffix(".csv.tmp").exists()
    assert rep["csv"].startswith("reconstruido")

    assert out.with_suffix(".viewer.html").exists()
    html = out.with_suffix(".viewer.html").read_text(encoding="utf-8")
    assert '"_state"' in html                               # arbol de estado embebido desde el JSONL
    assert not needs_finalize(str(out.parent))              # ya esta completa


def test_finalize_is_idempotent_and_skips_complete_runs(tmp_path):
    out = _make_interrupted_run(tmp_path)
    finalize_run(str(out.parent), log=lambda *_: None)
    before = out.with_suffix(".csv").read_bytes()
    rep = finalize_run(str(out.parent), log=lambda *_: None)
    assert rep["csv"] == "ok" and rep["viewer"] == "ok"
    assert out.with_suffix(".csv").read_bytes() == before


def test_finalize_tolerates_truncated_last_jsonl_line(tmp_path):
    out = _make_interrupted_run(tmp_path, n=10)
    with open(out, "a", encoding="utf-8") as fh:
        fh.write('{"cycle": 11, "t": 2.0, "sta')          # linea cortada por el kill
    finalize_run(str(out.parent), log=lambda *_: None)
    rows = list(csv.DictReader(open(out.with_suffix(".csv"), encoding="utf-8")))
    assert len(rows) == 10
    json.loads(out.read_text(encoding="utf-8").splitlines()[0])
