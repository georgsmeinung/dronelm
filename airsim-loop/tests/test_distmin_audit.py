"""Auditoria DistMin (src/logging/distmin_audit.py): hilo de muestreo y consolidacion en finalize_run."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from src.logging import distmin_audit as da
from src.logging import finalize_run as fr


def test_central_p5_uses_only_the_central_third():
    depth = np.full((9, 9), 50.0, dtype=np.float32)
    depth[0, 0] = 0.5          # borde: no cuenta
    depth[4, 4] = 2.0          # centro
    assert 2.0 <= da.central_p5(depth) < 50.0
    depth[3:6, 3:6] = np.inf   # sin datos validos en el centro
    assert da.central_p5(depth) is None


def _run_dir(tmp_path: Path, samples=None) -> Path:
    d = tmp_path / "seed_1_x"
    d.mkdir()
    (d / "seed_1_x.jsonl").write_text(json.dumps({"cycle": 1, "pos": {}, "state": {}}) + "\n", encoding="utf-8")
    (d / "seed_1_x.summary.json").write_text(json.dumps({"success": True, "min_obstacle_dist_m": None}),
                                             encoding="utf-8")
    if samples is not None:
        txt = "".join(json.dumps(s) + "\n" for s in samples) + '{"t": 9, "dist_'  # ultima linea truncada
        (d / "seed_1_x.distmin.ndjson").write_text(txt, encoding="utf-8")
    return d


def test_finalize_consolidates_thread_samples_into_summary(tmp_path):
    d = _run_dir(tmp_path, [{"t": 1.0, "dist_m": 8.2}, {"t": 2.0, "dist_m": 3.1}, {"t": 3.0, "dist_m": 5.0}])
    rep = fr.finalize_run(str(d), log=lambda *_: None)
    summary = json.loads((d / "seed_1_x.summary.json").read_text(encoding="utf-8"))
    assert summary["success"] is True
    assert summary["min_obstacle_dist_m"] == 3.1 and summary["min_obstacle_dist_t"] == 2.0
    assert summary["min_obstacle_dist_source"] == da.SOURCE and summary["min_obstacle_dist_samples"] == 3
    assert rep["distmin"].startswith("3.1")
    assert fr.finalize_run(str(d), log=lambda *_: None)["distmin"] == "ok"   # idempotente


def test_finalize_without_samples_leaves_distmin_empty(tmp_path):
    d = _run_dir(tmp_path)
    assert fr.finalize_run(str(d), log=lambda *_: None)["distmin"] == "sin_muestras"
    summary = json.loads((d / "seed_1_x.summary.json").read_text(encoding="utf-8"))
    assert summary["min_obstacle_dist_m"] is None


def test_interrupted_run_with_samples_needs_finalize(tmp_path):
    d = _run_dir(tmp_path, [{"t": 1.0, "dist_m": 4.0}])
    assert fr.needs_finalize(str(d))


class _FakeRpc:
    def __init__(self, dist):
        self.dist = dist
        self.calls = 0

    def confirmConnection(self):
        pass

    def simGetImages(self, requests, vehicle_name=""):
        self.calls += 1
        img = np.full((9, 9), self.dist, dtype=np.float32)
        return [SimpleNamespace(width=9, height=9, image_data_float=img.ravel().tolist(),
                                camera_position=SimpleNamespace(x_val=1.0, y_val=2.0, z_val=-10.0))]


def test_tracker_thread_samples_with_its_own_client(tmp_path, monkeypatch):
    import src.hardware.airsim_client as ac

    rpc = _FakeRpc(6.5)
    fake_airsim = SimpleNamespace(
        MultirotorClient=lambda **kw: rpc,
        ImageType=SimpleNamespace(DepthPlanar=2),
        ImageRequest=lambda *a: ("req",) + a,
    )
    monkeypatch.setattr(ac, "airsim", fake_airsim)
    run = tmp_path / "r.jsonl"
    tracker = da.DistMinTracker(run, "127.0.0.1", 41451, "Drone1", "0", period_s=0.2)
    tracker.start()
    time.sleep(0.5)
    tracker.stop()
    samples = [json.loads(l) for l in da.samples_path(run).read_text(encoding="utf-8").splitlines()]
    assert len(samples) >= 2 and all(s["dist_m"] == 6.5 for s in samples)
    assert samples[0]["x"] == 1.0 and not tracker.is_alive()


def test_tracker_not_started_without_simulator(tmp_path):
    assert da.start_tracker(tmp_path / "r.jsonl", SimpleNamespace(_client=None)) is None
