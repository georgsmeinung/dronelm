"""Smoke tests for the Typer CLI."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from airsim_plan.cli import app


runner = CliRunner()


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "airsim-plan" in result.stdout


def test_cli_validate_ok(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parent.parent / "examples" / "perimeter_north_01.json"
    target = tmp_path / "m.json"
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    result = runner.invoke(app, ["validate", str(target)])
    assert result.exit_code == 0, result.stdout


def test_cli_validate_bad() -> None:
    result = runner.invoke(app, ["validate", str(Path(__file__))])
    assert result.exit_code != 0


def test_cli_show(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parent.parent / "examples" / "perimeter_north_01.json"
    result = runner.invoke(app, ["show", str(src)])
    assert result.exit_code == 0, result.stdout
    assert "PERIMETER_NORTH_01" in result.stdout


def test_cli_prompt(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parent.parent / "examples" / "perimeter_north_01.json"
    # The example has no tactical_system_prompt because we didn't go through
    # the planner; the CLI should fail with exit code 2.
    result = runner.invoke(app, ["prompt", str(src)])
    assert result.exit_code == 2


def test_cli_dump_schema(tmp_path: Path) -> None:
    target = tmp_path / "schema.json"
    result = runner.invoke(app, ["dump-schema", "--out", str(target)])
    assert result.exit_code == 0
    assert target.exists()
    assert "mission_id" in target.read_text(encoding="utf-8")


def test_cli_run_requires_instruction_or_manifest() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2
