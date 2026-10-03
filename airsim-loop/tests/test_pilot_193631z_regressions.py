"""Regresiones del piloto v3 citysim_pilot seed 99 (2026-10-01 193631Z).

- Los dos barridos se perdieron porque max_tokens=160 cortaba el JSON antes de la llave final.
- La capa estrategica no consulto durante ~180 ciclos: el dron se deslizaba a lo largo de una fachada
  con la meta fuera de los +-40 deg del eje optico.
- La corrida tenia cambios sin commitear y quedo con el mismo code_version que la anterior.
"""
from __future__ import annotations

import math
import time
from types import SimpleNamespace

import numpy as np

import src.agents.vlm_client as vc
import src.agents.vlm_strategic as vs
from src.logging import code_version as cv


# --------------------------------------------------------------------------- max_tokens
class _FakeOpenAI:
    def __init__(self, content, finish):
        self._content, self._finish = content, finish
        self.kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._content),
                                                         finish_reason=self._finish)])


def _patch_openai(monkeypatch, content, finish):
    fake = _FakeOpenAI(content, finish)
    monkeypatch.setattr(vc, "OpenAI", lambda **kw: fake)
    return fake


def test_truncated_answer_is_reported_as_such(monkeypatch):
    raw = '{"rumbos": [{"img": 1, "tipo": "libre", "ok": true, "conf": 0.9}], "degradada": false'
    _patch_openai(monkeypatch, raw, "length")
    parsed, out_raw, _lat, err = vc._query_slm_impl({"mode": "deep_scan", "prompt": "p", "images_b64": []})
    assert parsed is None and err == vc.TRUNCATED_ERROR and out_raw == raw


def test_token_caps_leave_room_for_the_full_answers(monkeypatch):
    fake = _patch_openai(monkeypatch, '{"rumbos": [{"img": 1, "tipo": "libre", "ok": true, "conf": 0.9}], '
                                      '"degradada": false}', "stop")
    parsed, _raw, _lat, err = vc._query_slm_impl({"mode": "deep_scan", "prompt": "p", "images_b64": []})
    assert err is None and parsed is not None
    assert fake.kwargs["max_tokens"] >= 512
    assert vc._mode_spec("strategic")[3] >= 384


# --------------------------------------------------------------------------- meta fuera de cuadro
def _state(yaw_deg, no_progress=0, x=63.8, y=-111.4):
    wp = {"x": 67.7, "y": -145.0, "z": -10.0, "label": "WP_3"}
    return {
        "telemetry": {"position": {"x": x, "y": y, "z": -10.0},
                      "orientation": {"yaw": math.radians(yaw_deg)}, "timestamp": time.time()},
        "rgb_image": np.full((72, 108, 3), 100, dtype=np.uint8),
        "waypoints": [wp], "current_wp_index": 0, "_wp_no_progress_cycles": no_progress,
    }


def test_goal_out_of_view_is_only_queried_when_not_progressing():
    # NED (x norte, y este): la meta queda con rumbo ~-83 deg (oeste); el dron mira al sur (yaw 180), de
    # costado a la meta, a lo largo de la fachada.
    assert vs.build_request(_state(180.0, no_progress=0)) is None
    built = vs.build_request(_state(180.0, no_progress=vs.VLM_STUCK_QUERY_CYCLES))
    assert built is not None
    payload, anchor = built
    assert anchor["goal_cell"] is None and "outside the image" in payload["prompt"]


def test_goal_out_of_view_never_means_direct_path_free():
    st = _state(180.0, no_progress=vs.VLM_STUCK_QUERY_CYCLES)
    _p, anchor = vs.build_request(st)
    everything_free = {"sectores": {c: "libre" for c in vs.CELLS}}
    sub, why = vs.decide_subgoal(everything_free, anchor, st)
    assert sub is not None and why != "directo_libre"
    # La meta queda ~97 deg a la derecha del cuadro: el sector elegido es el de la columna derecha.
    assert anchor["goal_az_deg"] > 90.0 and sub["sector"].startswith("C")


# --------------------------------------------------------------------------- code_version
def test_code_version_marks_uncommitted_code(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        return "abc1234" if args[0] == "rev-parse" else " M airsim-loop/src/agents/graph.py"

    monkeypatch.setattr(cv, "_git", fake_git)
    assert cv.get_code_version() == "abc1234-dirty"
    assert calls[1][-3:] == cv.CODE_PATHS


def test_code_version_clean_tree(monkeypatch):
    monkeypatch.setattr(cv, "_git", lambda *a: "abc1234" if a[0] == "rev-parse" else "")
    assert cv.get_code_version() == "abc1234"
