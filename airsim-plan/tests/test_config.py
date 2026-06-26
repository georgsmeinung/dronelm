"""Tests for the Settings dataclass."""
from __future__ import annotations

import os

from airsim_plan.config import Settings, get_settings


def test_settings_defaults() -> None:
    s = Settings()
    assert s.lmstudio_base_url.startswith("http://")
    assert 0.0 <= s.planner_temperature <= 1.0
    assert isinstance(s.default_ignore_classes, list)


def test_settings_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("LMSTUDIO_MODEL", "custom-llm")
    monkeypatch.setenv("DEFAULT_TAKEOFF_ALT", "-25.5")
    monkeypatch.setenv("MISSION_DIR", "/tmp/whatever")
    s = Settings()
    assert s.lmstudio_model == "custom-llm"
    assert s.default_takeoff_alt == -25.5
    assert str(s.mission_dir) == "/tmp/whatever"


def test_get_settings_caches() -> None:
    a = get_settings()
    b = get_settings()
    assert a is b
