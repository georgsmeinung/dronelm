"""Planificacion de ruta con el VLM sobre el mapa cenital (src/planning/route_planner.py)."""
from __future__ import annotations

import json

import numpy as np

from src.planning import route_planner as rp


def _map(size=400, scale=2.0):
    return rp.MapView(np.full((size, size, 3), 128, np.uint8), scale, {"x": 0, "y": 0}, "fake.png")


def test_map_convention_north_up_east_right():
    mv = _map()
    assert mv.to_px(0, 0) == (200.0, 200.0)
    assert mv.to_px(10, 0) == (200.0, 180.0)      # norte -> arriba
    assert mv.to_px(0, 10) == (220.0, 200.0)      # este -> derecha


def test_candidates_cover_straight_l_shapes_and_detours():
    c = {x["name"]: x for x in rp.leg_candidates((0.0, 0.0), (40.0, 30.0), detours=[25.0])}
    assert set(c) == {"directo", "L_norte_sur_primero", "L_este_oeste_primero", "desvio_izq_25m", "desvio_der_25m"}
    assert c["L_norte_sur_primero"]["points"][1] == (40.0, 0.0)
    assert c["directo"]["length_m"] == 50.0


def test_left_detour_is_on_the_left_of_the_advance():
    c = {x["name"]: x for x in rp.leg_candidates((0.0, 0.0), (100.0, 0.0), detours=[25.0])}
    assert c["desvio_izq_25m"]["points"][1] == (0.0, -25.0)     # avanzando al norte, izquierda = oeste
    assert c["desvio_der_25m"]["points"][1] == (0.0, 25.0)
    assert "L_norte_sur_primero" not in c                       # tramo alineado: la L no existe


def test_choose_prefers_highest_approved_then_shortest():
    cands = [{"name": "directo", "answer": "no", "p_si": 0.2, "length_m": 50},
             {"name": "a", "answer": "si", "p_si": 0.81, "length_m": 90},
             {"name": "b", "answer": "si", "p_si": 0.84, "length_m": 120}]
    best, why = rp.choose(cands)
    assert best["name"] == "a" and why == "aprobada"            # 0.81 esta a menos de 0.05 de 0.84
    best, why = rp.choose([dict(c, answer="no") for c in cands])
    assert best["name"] == "directo" and why == "ninguna_aprobada"


def _fake_query(approve):
    def q(img, alt_m=10.0):
        ans = "yes" if approve() else "no"
        text = json.dumps({"answer": ans})
        return {"text": text, "tokens": [], "latency_ms": 1.0}
    return q


def test_plan_inserts_vias_before_the_rerouted_waypoint(tmp_path):
    manifest = {"map": "fake.png", "start_pose": {"x": 0.0, "y": 0.0, "z": -10.0},
                "waypoints": [{"x": 0.0, "y": -50.0, "z": -10.0, "label": "WP_1"},
                              {"x": 60.0, "y": -50.0, "z": -10.0, "label": "WP_2"}]}
    calls = {"n": 0}

    def approve():   # aprueba solo la 2da candidata de cada tramo (el primer desvio / la primera L)
        calls["n"] += 1
        return calls["n"] in (2, 8)

    planned, plan = rp.plan_route(manifest, out_dir=tmp_path, mv=_map(), query=_fake_query(approve), log=lambda s: None,
                                   judge="image")
    labels = [w["label"] for w in planned["waypoints"]]
    assert labels[-1] == "WP_2" and labels.count("WP_1") == 1
    assert all(w["planned_via"] for w in planned["waypoints"] if w["label"].startswith("VIA_"))
    assert planned["route_plan"]["vias"] == sum(len(l["vias"]) for l in plan["legs"]) > 0
    assert (tmp_path / "plan.json").exists() and any(tmp_path.glob("leg00_WP_1_*.jpg"))
    # replanificar un manifiesto ya planificado ignora los VIA anteriores
    assert [b["label"] for _a, b in rp.legs(planned)] == ["WP_1", "WP_2"]


def test_plan_key_changes_with_waypoints_but_not_with_vias():
    m = {"map": "x.png", "waypoints": [{"x": 1.0, "y": 2.0, "z": -10.0, "label": "WP_1"}]}
    k = rp.plan_key(m)
    with_via = dict(m, waypoints=[{"x": 0.5, "y": 1.0, "z": -10, "label": "VIA_WP_1_1", "planned_via": True}] + m["waypoints"])
    assert rp.plan_key(with_via) == k
    assert rp.plan_key(dict(m, waypoints=[{"x": 9.0, "y": 2.0, "z": -10.0, "label": "WP_1"}])) != k


def test_planner_model_falls_back_to_flight_model(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_MODEL_NAME", "vuelo")
    monkeypatch.delenv("ROUTE_LLM_MODEL_NAME", raising=False)
    assert rp.model_name() == "vuelo"
    m = {"map": "x.png", "waypoints": [{"x": 1.0, "y": 2.0, "z": -10.0, "label": "WP_1"}]}
    k = rp.plan_key(m)
    monkeypatch.setenv("ROUTE_LLM_MODEL_NAME", "plan")
    assert rp.model_name() == "plan"
    assert rp.plan_key(m) != k       # cambiar el modelo del planificador invalida el plan guardado


def test_read_judgement_translates_english_answer():
    j = rp.read_judgement({"text": json.dumps({"answer": "yes"}), "tokens": []})
    assert j["answer"] == "si" and j["p_si"] == 1.0
    assert rp.read_judgement({"text": json.dumps({"answer": "no"}), "tokens": []})["answer"] == "no"
    assert rp.read_judgement({"text": "", "tokens": []})["answer"] is None


def test_corridor_render_puts_start_at_bottom_and_end_at_top():
    mv = _map(size=400, scale=2.0)
    for pts in ([(0.0, 0.0), (0.0, -50.0)], [(0.0, 0.0), (40.0, 0.0)], [(0.0, 0.0), (-30.0, 30.0)]):
        img = rp.render_corridor(mv, pts, size=336)
        assert img.shape == (336, 336, 3)
        green = np.argwhere((img[:, :, 1] > 150) & (img[:, :, 0] < 60) & (img[:, :, 2] < 60))
        blue = np.argwhere((img[:, :, 0] > 200) & (img[:, :, 1] < 120) & (img[:, :, 2] < 60))
        assert green[:, 0].mean() > blue[:, 0].mean() + 50          # inicio abajo, destino arriba
        assert abs(green[:, 1].mean() - blue[:, 1].mean()) < 5      # sobre la misma vertical
    # fuera del pasillo el mapa queda oscurecido
    assert img[5, 5].max() < 128 * 0.5


def test_patch_judge_scores_by_mean_street_probability_and_reroutes(tmp_path):
    # Mapa sintetico: la recta x=0 cruza un "edificio"; el parche se clasifica por el color de su centro.
    mv = _map(size=400, scale=2.0)
    u0, v0 = mv.to_px(-20.0, -10.0)
    u1, v1 = mv.to_px(-40.0, 10.0)
    mv.image[int(v0):int(v1), int(u0):int(u1)] = 255          # bloque blanco = edificio
    manifest = {"map": "fake.png", "start_pose": {"x": 0.0, "y": 0.0, "z": -10.0},
                "waypoints": [{"x": -60.0, "y": 0.0, "z": -10.0, "label": "WP_1"}]}

    def patch_query(img):
        c = img[img.shape[0] // 2 - 5:img.shape[0] // 2 + 5, img.shape[1] // 2 - 5:img.shape[1] // 2 + 5]
        ans = "building" if c.mean() > 200 else "street"
        return {"text": json.dumps({"answer": ans}), "tokens": [], "latency_ms": 1.0}

    planned, plan = rp.plan_route(manifest, out_dir=tmp_path, mv=mv, log=lambda s: None, judge="patches",
                                  patch_query=patch_query)
    leg = plan["legs"][0]
    by = {c["name"]: c for c in leg["candidates"]}
    assert by["directo"]["p_si"] < 1.0 and any(p["answer"] == "building" for p in by["directo"]["patches"])
    assert leg["chosen"] != "directo" and leg["reason"] == "mejor_puntaje"
    assert planned["route_plan"]["judge"] == "patches" and planned["route_plan"]["vias"] > 0


def test_patch_judge_keeps_straight_line_on_tie():
    cands = [{"name": "directo", "length_m": 50.0, "judge": "patches", "p_si": 0.60},
             {"name": "desvio_izq_25m", "length_m": 100.0, "judge": "patches", "p_si": 0.63}]
    best, reason = rp.choose(cands)
    assert best["name"] == "directo" and reason == "mejor_puntaje"


def test_patch_cache_avoids_repeated_queries():
    mv = _map()
    calls = {"n": 0}

    def q(img):
        calls["n"] += 1
        return {"text": json.dumps({"answer": "street"}), "tokens": [], "latency_ms": 1.0}

    cache = {}
    pts = [(0.0, 0.0), (0.0, -32.0)]
    a = rp.judge_patches(mv, pts, q, cache)
    n1 = calls["n"]
    b = rp.judge_patches(mv, pts, q, cache)
    assert calls["n"] == n1 and a["p_si"] == b["p_si"] == 1.0
