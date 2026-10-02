"""Banco de prueba offline del VLM (experiments/vlm_bench): funciones puras."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments" / "vlm_bench"))

import common  # noqa: E402
import dataset  # noqa: E402
import labels  # noqa: E402
import report  # noqa: E402
from questions import CELLS, GridQuestion, perm_labels  # noqa: E402

FREE = labels.FREE_M


def _depth(fill=100.0):
    return np.full((720, 1080), fill, np.float32)


# --------------------------------------------------------------------------- etiquetas
def test_open_scene_is_free_everywhere():
    g = labels.labels_from_depth(_depth())
    assert all(g["cell_free"].values()) and g["center_free"] == "si"
    assert g["edge_side"] is None and g["top_clear"] is None and not g["inside"]


def test_wall_ahead_with_gap_on_the_right():
    d = _depth(5.0)
    d[:, 900:] = 100.0                      # hueco libre en el borde derecho del frame completo
    g = labels.labels_from_depth(d)
    assert g["center_free"] == "no" and g["edge_side"] == "derecha"
    assert g["top_clear"] == "no" and g["open_dir"] == "derecha"


def test_low_obstacle_with_sky_above():
    d = _depth(100.0)
    d[300:, :] = 6.0                        # muro bajo: del centro hacia abajo
    g = labels.labels_from_depth(d)
    assert g["center_free"] == "no" and g["top_clear"] == "si" and g["edge_side"] == "ninguno"


def test_camera_inside_geometry_is_flagged():
    assert labels.labels_from_depth(_depth(0.3))["inside"]


def test_cells_follow_the_square_crop():
    d = _depth(100.0)
    d[:, :180] = 2.0                        # franja que el recorte cuadrado descarta
    g = labels.labels_from_depth(d)
    assert all(g["cell_free"].values())


def test_min_pool_keeps_thin_obstacles():
    d = _depth(100.0)
    d[10, 10] = 1.0
    assert labels.pool_min(d).min() == 1.0


# --------------------------------------------------------------------------- logprobs
# Secuencia real de LM Studio (qwen2.5-vl-3b, json_schema con enum si/no): top_logprobs es la
# distribucion previa a la gramatica.
_TOKENS = [
    {"token": '{\n', "logprob": -0.01, "top_logprobs": []},
    {"token": ' ', "logprob": -0.03, "top_logprobs": []},
    {"token": ' "', "logprob": 0.0, "top_logprobs": []},
    {"token": 'respuesta', "logprob": -1.8, "top_logprobs": []},
    {"token": '":', "logprob": -0.02, "top_logprobs": []},
    {"token": ' "', "logprob": -0.05, "top_logprobs": []},
    {"token": 's', "logprob": -2.04, "top_logprobs": [
        {"token": "s", "logprob": -2.04}, {"token": "S", "logprob": -0.77}, {"token": "No", "logprob": -2.03},
        {"token": "no", "logprob": -2.75}, {"token": "Si", "logprob": -3.24}]},
    {"token": 'i', "logprob": -10.5, "top_logprobs": []},
    {"token": '"\n', "logprob": -0.3, "top_logprobs": []},
    {"token": '}\n', "logprob": 0.0, "top_logprobs": []},
]


def test_choice_probs_read_the_pre_grammar_distribution():
    text = "".join(t["token"] for t in _TOKENS)
    off = common.value_offsets(text, "respuesta")[0]
    p = common.choice_probs_at(_TOKENS, off, ["si", "no"])
    expected = (math.exp(-2.04) + math.exp(-0.77) + math.exp(-3.24))
    expected /= expected + math.exp(-2.03) + math.exp(-2.75)
    assert abs(p["si"] - expected) < 1e-9 and abs(p["si"] + p["no"] - 1.0) < 1e-9


def test_choice_probs_inside_a_merged_token():
    toks = [{"token": '{"ok": tr', "logprob": -0.1, "top_logprobs": [
                {"token": '{"ok": tr', "logprob": -0.4}, {"token": '{"ok": fa', "logprob": -1.2}]},
            {"token": 'ue}', "logprob": 0.0, "top_logprobs": []}]
    text = '{"ok": true}'
    off = common.value_offsets(text, "ok", quoted=False)[0]
    p = common.choice_probs_at(toks, off, ["true", "false"])
    assert p["true"] > p["false"] and abs(sum(p.values()) - 1) < 1e-9


# --------------------------------------------------------------------------- dataset
def test_photo_timestamp_matches_the_telemetry_clock():
    assert abs(dataset.photo_ts("photo-20261002T021506.369Z.png") - 1790907306.369) < 1e-3
    assert dataset.photo_ts("photo-20261002T021506.369Z-1.png") is not None
    assert dataset.photo_ts("otro.png") is None


def test_nearest_record_respects_tolerance():
    recs = [{"cycle": i, "state": {"telemetry": {"timestamp": 100.0 + i * 0.2}}} for i in range(10)]
    assert dataset.nearest_record(recs, 100.41)["cycle"] == 2
    assert dataset.nearest_record(recs, 120.0) is None


def test_scan_photos_are_grouped_by_time_gap():
    assert dataset.group_scans([0.0, 2.0, 4.5, 100.0, 102.0]) == [[0.0, 2.0, 4.5], [100.0, 102.0]]


def test_pose_key_deduplicates_a_stuck_drone():
    a = {"x": 10.1, "y": -5.2, "z": -10.0, "yaw_deg": 91.0}
    b = {"x": 10.9, "y": -5.9, "z": -9.6, "yaw_deg": 95.0}
    c = dict(a, yaw_deg=130.0)
    assert dataset.pose_key(a) == dataset.pose_key(b) != dataset.pose_key(c)


# --------------------------------------------------------------------------- preguntas
def test_permuted_grid_moves_every_label_and_maps_back():
    lab = perm_labels("muestra_1")
    assert sorted(lab.values()) == sorted(CELLS) and all(k != v for k, v in lab.items())
    q = GridQuestion(permuted=True)
    answers_by_label = {lab[pos]: ("libre" if pos == "C2" else "bloqueado") for pos in CELLS}
    phys = q.physical({"id": "muestra_1"}, answers_by_label)
    assert phys["C2"] == "libre" and sum(v == "libre" for v in phys.values()) == 1


# --------------------------------------------------------------------------- metricas
def test_constant_answer_scores_chance_in_balanced_accuracy():
    truth = ["si"] * 30 + ["no"] * 70
    assert report.balanced_accuracy(truth, ["no"] * 100) == 0.5
    assert report.answer_stats(["no"] * 100)["constant"]


def test_auc_perfect_random_and_ties():
    assert report.auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert report.auc([0.5, 0.5, 0.5, 0.5], [True, False, True, False]) == 0.5


def test_loro_threshold_is_chosen_without_the_held_out_run():
    rows = [(f"r{k}", p, p > 0.7) for k in range(3) for p in (0.6, 0.65, 0.75, 0.8)]
    assert report.loro_calibrated(rows) == 1.0


# --------------------------------------------------------------------------- rutas
def test_route_sampling_follows_each_segment_heading():
    import os

    os.environ.setdefault("AIRSIM_VEHICLE_NAME", "Drone1")
    import route_bench

    pts = route_bench.sample_route([(0.0, 0.0), (8.0, 0.0), (8.0, 8.0)], step=4.0)
    assert [(round(x), round(y), round(h)) for x, y, h in pts] == [(0, 0, 0), (4, 0, 0), (8, 0, 90), (8, 4, 90)]
    d = np.full((720, 1080), 50.0, np.float32)
    d[300:420, 500:580] = 3.0
    assert route_bench.window_clearance(d)[0] == 3.0


def test_route_metrics_score_the_plan_against_the_straight_line():
    rows = [{"mission": "m", "leg": "00", "candidate": "directo", "length_m": 50, "answer": "si", "p_si": 0.6, "clear": False},
            {"mission": "m", "leg": "00", "candidate": "desvio_izq_25m", "length_m": 90, "answer": "si", "p_si": 0.9, "clear": True},
            {"mission": "m", "leg": "01", "candidate": "directo", "length_m": 40, "answer": "no", "p_si": 0.2, "clear": True}]
    m = report.route_metrics(rows)
    assert m["plan_clear_rate"] == 1.0 and m["direct_clear_rate"] == 0.5
    assert m["legs"][1]["reason"] == "ninguna_aprobada"


# --------------------------------------------------------------------------- criterio generalista
def test_bootstrap_ci_and_verdict():
    good = [(f"r{k}", t, t) for k in range(6) for t in ("si", "no") * 10]          # siempre acierta
    lo, hi = report.cluster_bootstrap_ci(good, n=300)
    assert lo == hi == 1.0
    assert report.verdict({"balanced_accuracy": 1.0, "ci_low": lo, "chance": 0.5})["passes"]
    const = [(f"r{k}", t, "no") for k in range(6) for t in ("si", "no") * 10]      # respuesta constante
    lo, _hi = report.cluster_bootstrap_ci(const, n=300)
    assert lo == 0.5
    assert not report.verdict({"balanced_accuracy": 0.5, "ci_low": lo, "chance": 0.5})["passes"]


def _env(ok):
    return {"questions": {"centro_libre@384/replay": {"balanced_accuracy": 0.8, "ci_low": 0.7,
                                                      "ci_high": 0.9, "passes": ok}}}


def test_a_question_must_pass_in_every_environment():
    k = "centro_libre@384/replay"
    assert report.cross_environment({"citysim": _env(True), "townsim": _env(False)})[k]["passes_all"] is False
    assert report.cross_environment({"citysim": _env(True), "townsim": _env(True)})[k]["passes_all"] is True
