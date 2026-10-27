"""Lotes finales (cap. 10 Sec. 10.12.2): celdas alternadas del runner, guardas del lote y estadisticos (2026-10-15)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))

import analyze_lotes as al  # noqa: E402
import runner  # noqa: E402


# ---------------------------------------------------------------- runner

def test_parse_cells_defaults_strategy_and_rejects_bad_specs(monkeypatch):
    monkeypatch.setenv("DEADLOCK_STRATEGY", "depth")
    assert runner._parse_cells(["slm:depth", "fsm:blind", "reactive"]) == [
        ("slm", "depth"), ("fsm", "blind"), ("reactive", "depth")]
    for bad in (["slm:magic"], ["drone:depth"], ["slm:depth", "slm"]):
        with pytest.raises(ValueError):
            runner._parse_cells(bad)


def test_build_jobs_without_cells_keeps_historic_order():
    jobs = runner._build_jobs(["slm", "fsm"], ["depth"], [1, 2], None)
    assert jobs == [("slm", "depth", 1, None), ("slm", "depth", 2, None),
                    ("fsm", "depth", 1, None), ("fsm", "depth", 2, None)]


def test_build_jobs_with_cells_interleaves_and_rotates_per_seed():
    cells = [("slm", "depth"), ("fsm", "depth"), ("fsm", "blind"), ("reactive", "depth")]
    jobs = runner._build_jobs(["ignored"], ["ignored"], [1, 2, 3, 4, 5], None, cells)
    assert len(jobs) == 20
    # Cada semilla completa sus 4 celdas antes de pasar a la siguiente.
    for i, seed in enumerate([1, 2, 3, 4, 5]):
        block = jobs[4 * i: 4 * i + 4]
        assert {j[2] for j in block} == {seed}
        assert {(j[0], j[1]) for j in block} == set(cells)
    # La celda que abre cada semilla rota: ninguna va siempre primera.
    firsts = [(jobs[4 * i][0], jobs[4 * i][1]) for i in range(4)]
    assert firsts == cells
    # Solo las celdas pedidas: no aparecen slm x blind ni reactive x blind.
    assert ("slm", "blind") not in {(j[0], j[1]) for j in jobs}


def test_build_jobs_with_cells_and_sources():
    jobs = runner._build_jobs([], [], [7], ["depth", "off"], [("slm", "depth")])
    assert jobs == [("slm", "depth", 7, "depth"), ("slm", "depth", 7, "off")]


@pytest.mark.parametrize("version,ok", [("1a2b3c4d", True), ("1a2b3c4d-dirty", False), ("unknown", False), ("", False)])
def test_batch_only_starts_with_clean_tree(version, ok):
    assert runner._version_ok_for_batch(version) is ok


def _write_summary(root: Path, scenario: str, arm: str, cell: str, seed: int, **fields) -> Path:
    run = root / scenario / arm / cell / f"seed_{seed}_20261015T000000Z"
    run.mkdir(parents=True, exist_ok=True)
    path = run / f"seed_{seed}_20261015T000000Z.summary.json"
    path.write_text(json.dumps({"scenario": scenario, "arm": arm, "seed": seed, **fields}), encoding="utf-8")
    return path


def test_skip_existing_requires_same_version_and_enough_cycles(tmp_path):
    scen = "x/flightplans/townsim_ini.json"
    _write_summary(tmp_path, "townsim_ini", "fsm", "blind", 1, code_version="abc", cycles=900)
    _write_summary(tmp_path, "townsim_ini", "fsm", "blind", 2, code_version="old", cycles=900)
    _write_summary(tmp_path, "townsim_ini", "fsm", "blind", 3, code_version="abc", cycles=12)
    assert runner._has_valid_summary(str(tmp_path), scen, "fsm", "blind", 1, "abc")
    assert not runner._has_valid_summary(str(tmp_path), scen, "fsm", "blind", 2, "abc")
    assert not runner._has_valid_summary(str(tmp_path), scen, "fsm", "blind", 3, "abc")
    assert not runner._has_valid_summary(str(tmp_path), scen, "fsm", "depth", 1, "abc")


# ---------------------------------------------------------------- estadisticos

def test_wilson_matches_known_values_and_handles_extremes():
    lo, hi = al.wilson(5, 5)
    assert hi == 1.0 and lo == pytest.approx(0.566, abs=1e-3)
    lo, hi = al.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.278, abs=1e-3)


def test_newcombe_difference_interval():
    d, lo, hi = al.newcombe_diff(10, 10, 0, 10)
    # lo = 1 - sqrt((1 - 0.7225)^2 + 0.2775^2), con los IC de Wilson de 10/10 y 0/10.
    assert d == 1.0 and lo == pytest.approx(0.6075, abs=2e-3) and hi == pytest.approx(1.0)


def test_cliffs_delta_and_bootstrap_ci():
    assert al.cliffs_delta([3, 4, 5], [0, 1, 2]) == 1.0
    assert al.cliffs_delta([1, 1], [1, 1]) == 0.0
    lo, hi = al.cliffs_delta_ci([3, 4, 5, 6], [0, 1, 2, 3], n_boot=500)
    assert -1.0 <= lo <= hi <= 1.0 and hi == 1.0


def test_rank_permutation_minimum_p_by_k():
    # Separacion perfecta: p minimo = 2 / C(2K, K). Con K = 5 no pasa ninguna correccion de Bonferroni.
    assert al.rank_permutation_p([1] * 5, [0] * 5) == pytest.approx(2 / 252)  # empates dentro de cada celda
    assert al.rank_permutation_p(list(range(10, 15)), list(range(5))) == pytest.approx(2 / 252)
    assert al.rank_permutation_p(list(range(20, 30)), list(range(10))) == pytest.approx(2 / 184756)
    assert al.rank_permutation_p([0.5] * 4, [0.5] * 4) == 1.0


# ---------------------------------------------------------------- analisis completo

def test_filter_and_analyze_end_to_end(tmp_path):
    for seed in range(1, 6):
        _write_summary(tmp_path, "townsim_ini", "slm", "depth", seed, deadlock_strategy="depth",
                       code_version="abc", cycles=1000, success=True, duration_s=300.0,
                       path_length_m=110.0, min_obstacle_dist_m=2.0, collisions=0)
        _write_summary(tmp_path, "townsim_ini", "fsm", "blind", seed, deadlock_strategy="blind",
                       code_version="abc", cycles=4500, success=False, duration_s=900.0,
                       path_length_m=40.0, min_obstacle_dist_m=0.4, collisions=1)
    _write_summary(tmp_path, "townsim_ini", "fsm", "depth", 1, deadlock_strategy="depth",
                   code_version="abc-dirty", cycles=1000, success=True, duration_s=300.0, path_length_m=100.0)
    pil = tmp_path / "pilotos"
    _write_summary(pil, "townsim_ini", "slm", "depth", 99, deadlock_strategy="depth", code_version="abc", cycles=900)

    runs = al.load_runs(str(tmp_path))
    assert all(r["seed"] != 99 for r in runs)
    ref = al.reference_version(runs)
    assert ref == "abc"
    kept, dropped = al.filter_runs(runs, ref)
    assert len(kept) == 10 and len(dropped) == 1 and "dirty" in dropped[0][1]

    res = al.analyze(kept, {"townsim_ini": 100.0}, n_boot=200)
    assert res["lotes"] == ["D"] and res["family"] == 3
    (comp,) = [c for c in res["comparisons"] if c["comparacion"] == "i"]
    assert comp["metrica_primaria"] == "SPL" and comp["cliff"] == 1.0
    # Un solo lote: familia de 3 (alfa 0.0167) y el p minimo de K = 5 (0.0079) pasa; con 3 lotes
    # (alfa 0.0056) ya no pasaria.
    assert comp["p"] == pytest.approx(2 / 252) and comp["significativa"]
    assert comp["p_bonf"] == pytest.approx(3 * 2 / 252) and 2 / 252 > 0.05 / 9
    assert comp["exito_a"] == "5/5" and comp["exito_b"] == "0/5"
    md = al.report_md(res, ref, len(kept), dropped)
    assert "slm x depth vs fsm x blind" in md and "Corridas descartadas" in md
    assert math.isnan(al.cliffs_delta([], [1]))


def test_design_auto_picks_comparisons_by_cells():
    assert al.comparisons_for({"slm x depth", "fsm x depth", "fsm x blind", "reactive"}) == al.COMPARISONS_CELLS
    assert al.comparisons_for({"slm x depth", "fsm x depth", "reactive"}) == al.COMPARISONS_ARMS
    assert al.comparisons_for({"slm x depth", "fsm x depth", "reactive"}, "cells4") == al.COMPARISONS_CELLS


def test_three_arm_clear_lote_uses_mission_time(tmp_path):
    # Lote 1 (despejado, 3 brazos): metrica primaria = tiempo de las misiones exitosas.
    for seed, (slm_t, fsm_t, rea_t) in enumerate([(230, 160, 80), (240, 170, 82), (235, 165, 84)], start=2):
        for arm, t in (("slm", slm_t), ("fsm", fsm_t), ("reactive", rea_t)):
            _write_summary(tmp_path / "lote1_minisim_clear", "minisim_clear", arm, "depth", seed,
                           deadlock_strategy="depth", code_version="abc", cycles=1000, success=True,
                           duration_s=float(t), path_length_m=150.0, min_obstacle_dist_m=9.0)
    kept, dropped = al.filter_runs(al.load_runs(str(tmp_path)), "abc")
    res = al.analyze(kept, {"minisim_clear": 150.0}, n_boot=200, family=18)
    assert res["lotes"] == ["A"] and res["family"] == 18 and not dropped
    comps = {c["comparacion"]: c for c in res["comparisons"]}
    assert set(comps) == {"slm-fsm", "slm-reactive", "fsm-reactive"}
    assert comps["slm-reactive"]["metrica_primaria"].startswith("tiempo")
    assert comps["slm-reactive"]["cliff"] == 1.0  # slm mas lento en todas las semillas
    assert comps["slm-reactive"]["p"] == pytest.approx(2 / 20)  # K = 3: C(6, 3) = 20


# ---------------------------------------------------------------- entorno python

def test_python_env_check(tmp_path, monkeypatch):
    from src.logging import python_env as pe

    env = tmp_path / "airsimenv"
    env.mkdir()
    assert pe.check_python_env(prefix=str(env), env_dir=str(env))[0]
    assert pe.check_python_env(prefix=str(env) + "/", env_dir=str(env).upper())[0]  # mayusculas/barra final
    ok, msg = pe.check_python_env(prefix=str(tmp_path / "otro"), env_dir=str(env))
    assert not ok and "AIRSIM_ENV_DIR" in msg
    assert pe.check_python_env(prefix=str(tmp_path / "otro"), env_dir="")[0]  # sin definir: sin control
    monkeypatch.setenv("AIRSIM_ENV_DIR", '"D:/X/airsimenv"')
    assert pe.expected_env_dir() == "D:/X/airsimenv"


def test_env_file_declares_airsimenv_without_dotenv_escapes():
    from src.logging import python_env as pe

    # "\a" entre comillas dobles seria un escape de python-dotenv: el valor se escribe con "/".
    assert pe.expected_env_dir().replace("\\", "/").lower().endswith("tesismcd/airsimenv")
    assert "\a" not in pe.expected_env_dir()


def test_reference_version_is_per_lote(tmp_path):
    """2026-10-27: cada lote v4 tiene su code_version; una referencia global descartaria los demas lotes."""
    for seed in (1, 2, 3):
        _write_summary(tmp_path, "minisim_clear", "slm", "depth", seed, code_version="aaa", cycles=900)
        _write_summary(tmp_path, "townsim_ini", "slm", "depth", seed, code_version="bbb", cycles=900)
    _write_summary(tmp_path, "townsim_ini", "slm", "depth", 4, code_version="aaa", cycles=900)
    _write_summary(tmp_path, "townsim_ini", "slm", "depth", 5, code_version="bbb-dirty", cycles=900)
    # Lo descartado a mano no entra, aunque empate en cantidad con el lote valido.
    for seed in (1, 2, 3, 4):
        _write_summary(tmp_path / "descarte" / "lote1_viejo", "minisim_clear", "slm", "depth", seed,
                       code_version="old", cycles=900)
    runs = al.load_runs(str(tmp_path))
    assert all(r["code_version"] != "old" for r in runs)
    refs = al.reference_versions(runs)
    assert refs == {"minisim_clear": "aaa", "townsim_ini": "bbb"}
    kept, dropped = al.filter_runs(runs, refs)
    assert len(kept) == 6
    assert sorted(reason for _, reason in dropped) == ["code_version aaa != bbb", "code_version bbb-dirty"]
    # Una referencia global fija sigue disponible (--ref-version) y descarta el otro lote.
    kept_global, _ = al.filter_runs(runs, "aaa")
    assert {r["scenario"] for r in kept_global} == {"minisim_clear", "townsim_ini"} and len(kept_global) == 4
    assert "A `aaa`, D `bbb`" in al._ref_text(refs)


def test_distmin_drops_first_audit_sample(tmp_path):
    """2026-10-27: la primera muestra de la auditoria es un artefacto del arranque (0.003 m y luego 18.3 m)."""
    p = _write_summary(tmp_path, "townsim_clear", "slm", "depth", 31, code_version="aaa", cycles=900,
                       min_obstacle_dist_m=0.003)
    p.with_name(p.name.replace(".summary.json", ".distmin.ndjson")).write_text(
        "\n".join(json.dumps({"t": i, "dist_m": d}) for i, d in enumerate([0.003, 18.28, 20.36, 14.6])),
        encoding="utf-8")
    _write_summary(tmp_path, "townsim_clear", "slm", "depth", 37, code_version="aaa", cycles=900,
                   min_obstacle_dist_m=5.0)  # sin auditoria: queda el valor del summary
    by_seed = {r["seed"]: r for r in al.load_runs(str(tmp_path))}
    assert by_seed[31]["min_obstacle_dist_m"] == pytest.approx(14.6)
    assert by_seed[31]["min_obstacle_dist_m_raw"] == pytest.approx(0.003)
    assert by_seed[37]["min_obstacle_dist_m"] == 5.0 and "min_obstacle_dist_m_raw" not in by_seed[37]
