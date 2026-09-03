"""Tests de validación del schema de MissionManifest."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from airsim_plan.missions.manifest import (
    MissionManifest,
    Waypoint,
    load_manifest,
    save_manifest,
)


def _good_payload() -> dict:
    return {
        "mission_id": "PERIMETER_NORTH_01",
        "summary": "Perimetro norte",
        "waypoints": [
            {"x": 0, "y": 50, "z": -10, "label": "north_edge"},
            {"x": 50, "y": 100, "z": -10, "label": "target"},
        ],
    }


def test_basic_roundtrip() -> None:
    payload = _good_payload()
    manifest = MissionManifest.from_dict(payload)
    assert manifest.mission_id == "PERIMETER_NORTH_01"
    assert len(manifest.waypoints) == 2


def test_mission_id_uppercased() -> None:
    payload = _good_payload()
    payload["mission_id"] = "perimeter_north_01"
    manifest = MissionManifest.from_dict(payload)
    assert manifest.mission_id == "PERIMETER_NORTH_01"


@pytest.mark.parametrize("bad_id", ["AB", "has space", "lower_case_with_dots!"])
def test_invalid_mission_id(bad_id: str) -> None:
    payload = _good_payload()
    payload["mission_id"] = bad_id
    with pytest.raises(Exception):
        MissionManifest.from_dict(payload)


def test_empty_waypoints_rejected() -> None:
    payload = _good_payload()
    payload["waypoints"] = []
    with pytest.raises(Exception):
        MissionManifest.from_dict(payload)


def test_duplicate_waypoints_rejected() -> None:
    payload = _good_payload()
    payload["waypoints"] = [
        {"x": 1, "y": 1, "z": -10},
        {"x": 1, "y": 1, "z": -10},
    ]
    with pytest.raises(Exception):
        MissionManifest.from_dict(payload)


def test_save_and_load(tmp_path: Path) -> None:
    manifest = MissionManifest.from_dict(_good_payload())
    target = tmp_path / "m.json"
    save_manifest(manifest, target)
    assert target.exists()
    reloaded = load_manifest(target)
    assert reloaded.mission_id == manifest.mission_id
    assert reloaded.waypoints[0].x == 0


def test_against_bundled_json_schema() -> None:
    """El modelo Pydantic debe aceptar lo que documenta el JSON Schema."""
    schema_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "airsim_plan"
        / "schemas"
        / "manifest_schema.json"
    )
    assert schema_path.exists(), "bundled JSON Schema is missing"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "mission_id" in schema["required"]
    # El manifest debe poder cargarse como JSON y pasar la validación.
    manifest = MissionManifest.from_dict(_good_payload())
    decoded = json.loads(manifest.to_json())
    for key in schema["required"]:
        assert key in decoded, f"required field {key!r} missing"
