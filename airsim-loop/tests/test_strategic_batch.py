"""Lote de fuentes de la capa estrategica: celdas del runner y medida del avance del plan (2026-10-08)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))

import analyze_strategic_batch as asb  # noqa: E402
import runner  # noqa: E402


def test_cell_names_keep_old_layout_without_strategic_source():
    assert runner._cell("depth", None) == "depth"
    cell = runner._cell("depth", "off")
    m = asb.CELL_RE.match(cell)
    assert cell == "strat_off__depth" and m["src"] == "off" and m["dl"] == "depth"
    assert asb.CELL_RE.match(runner._cell("deep_vlm", "vlm"))["dl"] == "deep_vlm"


def test_plan_progress_ignores_subgoals_repeats_and_the_current_target(tmp_path):
    plan = ["WP_0", "VIA_1", "WP_1", "WP_2"]
    (tmp_path / "x.summary_by_wp.csv").write_text(
        "wp_index,wp_label,cycles,duration_s\n"
        "0,WP_0,10,20\n"
        "1,VLM_SUBGOAL,5,10\n"     # sub-meta insertada: no es avance
        "1,VIA_1,5,10\n"
        "2,VIA_1,5,10\n"           # etiqueta repetida tras la sub-meta
        "2,WP_1,5,10\n"
        "3,WP_2,50,100\n",          # ultima fila: objetivo en curso, no completado
        encoding="utf-8")
    prog = asb.plan_progress(tmp_path, plan)
    assert prog == {20.0: 1, 40.0: 2, 60.0: 3}
    assert asb.reached_at(prog, 39.0) == 1 and asb.reached_at(prog, 400.0) == 3
