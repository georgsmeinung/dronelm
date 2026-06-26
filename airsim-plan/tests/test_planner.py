"""Tests for MissionPlanner (LLM stubbed via _llm_override)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from airsim_plan.config import Settings
from airsim_plan.llm import LMStudioClient, PlannerResponse
from airsim_plan.missions import MissionPlanner, PlannerError


GOOD_MANIFEST = {
    "mission_id": "PERIMETER_NORTH_01",
    "summary": "Recorrer perimetro norte",
    "waypoints": [
        {"x": 0, "y": 50, "z": -10, "label": "north_edge"},
        {"x": 50, "y": 100, "z": -10, "label": "target"},
    ],
    "rules_of_engagement": {
        "ignore_objects": ["person", "car"],
        "return_to_launch_battery_threshold": 20.0,
        "max_speed_mps": 5.0,
        "min_altitude_m": -10.0,
    },
}


GOOD_MANIFEST_TEXT = "```json\n" + str(GOOD_MANIFEST).replace("'", '"') + "\n```"


class _StubLLM:
    """Returns a canned response regardless of prompt."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.client = MagicMock(spec=LMStudioClient)
        self.client.model = "stub"

    def complete(self, user_prompt: str, **kwargs):  # noqa: ANN001
        return PlannerResponse(content=self._content, raw=None)


def _planner(content: str, settings: Settings | None = None) -> MissionPlanner:
    planner = MissionPlanner(settings=settings)
    planner._llm_override = _StubLLM(content)  # type: ignore[attr-defined]
    return planner


def test_compile_with_stub() -> None:
    planner = _planner(GOOD_MANIFEST_TEXT)
    manifest = planner.compile("Revisa el perimetro norte")
    assert manifest.mission_id == "PERIMETER_NORTH_01"
    assert manifest.waypoints[-1].label == "target"
    assert manifest.tactical_system_prompt is not None
    assert "PERIMETER_NORTH_01" in manifest.tactical_system_prompt
    assert "[50.0, 100.0, -10.0]" in manifest.tactical_system_prompt


def test_compile_rejects_unparseable() -> None:
    planner = _planner("esto no es json")
    with pytest.raises(PlannerError):
        planner.compile("foo")


def test_compile_rejects_wrong_shape() -> None:
    planner = _planner('{"mission_id": "OK"}')
    with pytest.raises(PlannerError):
        planner.compile("foo")


def test_compile_rejects_empty_instruction() -> None:
    planner = MissionPlanner()
    with pytest.raises(PlannerError):
        planner.compile("   ")


def test_compile_and_save(tmp_path: Path) -> None:
    new_settings = Settings(
        lmstudio_base_url="http://localhost:0",
        lmstudio_api_key="x",
        lmstudio_model="stub",
        tactical_base_url="http://localhost:0",
        tactical_api_key="x",
        tactical_model="stub",
        airsim_host="127.0.0.1",
        airsim_vehicle_name="Drone0",
        airsim_port=41451,
        default_takeoff_alt=-10.0,
        default_speed=5.0,
        mission_dir=tmp_path,
        planner_temperature=0.0,
        planner_max_tokens=10,
        default_ignore_classes=[],
    )
    planner = _planner(GOOD_MANIFEST_TEXT, settings=new_settings)
    manifest, path = planner.compile_and_save("foo")
    assert path.exists()
    assert manifest.mission_id == "PERIMETER_NORTH_01"


def test_tactical_prompt_contains_roe() -> None:
    from airsim_plan.missions.manifest import MissionManifest

    manifest = MissionManifest.from_dict(GOOD_MANIFEST)
    planner = MissionPlanner()
    prompt = planner.build_tactical_prompt(manifest)
    assert "person, car" in prompt
    assert "20" in prompt  # battery threshold
    assert "RETURN_TO_LAUNCH" in prompt
