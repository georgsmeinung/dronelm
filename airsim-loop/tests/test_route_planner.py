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
        ans = "si" if approve() else "no"
        text = json.dumps({"respuesta": ans})
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

    planned, plan = rp.plan_route(manifest, out_dir=tmp_path, mv=_map(), query=_fake_query(approve), log=lambda s: None)
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
