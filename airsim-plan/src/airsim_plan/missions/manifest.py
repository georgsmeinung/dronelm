"""Mission Manifest schema (Pydantic) and persistence helpers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


MISSION_ID_RE = re.compile(r"^[A-Z0-9_]{3,32}$")


class Waypoint(BaseModel):
    """A 3D waypoint in the NED frame (z negative = altitude)."""

    x: float
    y: float
    z: float
    label: Optional[str] = None


class RulesOfEngagement(BaseModel):
    """Constraints injected into the tactical SLM (Step 3 of the pipeline)."""

    ignore_objects: List[str] = Field(default_factory=list)
    return_to_launch_battery_threshold: float = Field(ge=0.0, le=100.0)
    max_speed_mps: Optional[float] = Field(default=None, ge=0.0)
    min_altitude_m: Optional[float] = None
    notes: Optional[str] = None

    @field_validator("ignore_objects")
    @classmethod
    def _normalize_classes(cls, value: List[str]) -> List[str]:
        return [str(v).strip().lower() for v in value if str(v).strip()]


class MissionManifest(BaseModel):
    """The contract handed from the ground planner to ``airsim-loop``.

    This is the canonical Python representation; the JSON Schema lives in
    ``airsim_plan/schemas/manifest_schema.json`` for documentation /
    validation in other languages.
    """

    mission_id: str
    summary: Optional[str] = None
    waypoints: List[Waypoint] = Field(min_length=1)
    rules_of_engagement: RulesOfEngagement
    tactical_system_prompt: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Validators                                                        #
    # ------------------------------------------------------------------ #
    @field_validator("mission_id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        value = value.strip().upper()
        if not MISSION_ID_RE.match(value):
            raise ValueError(
                "mission_id must match ^[A-Z0-9_]{3,32}$ (got "
                f"{value!r})."
            )
        return value

    @model_validator(mode="after")
    def _enforce_unique_waypoints(self) -> "MissionManifest":
        coords = [(round(w.x, 3), round(w.y, 3), round(w.z, 3)) for w in self.waypoints]
        if len(coords) != len(set(coords)):
            raise ValueError("waypoints must be unique (rounded to 3 decimals).")
        return self

    # ------------------------------------------------------------------ #
    # I/O                                                               #
    # ------------------------------------------------------------------ #
    def to_json(self, *, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, raw: str | bytes) -> "MissionManifest":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return cls.model_validate_json(raw)

    @classmethod
    def from_dict(cls, data: dict) -> "MissionManifest":
        return cls.model_validate(data)


def save_manifest(manifest: MissionManifest, path: Path | str) -> Path:
    """Persist ``manifest`` to ``path`` (JSON, utf-8)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.to_json(indent=2) + "\n", encoding="utf-8")
    return target


def load_manifest(path: Path | str) -> MissionManifest:
    """Read a manifest JSON from disk and validate it."""
    source = Path(path)
    raw = source.read_text(encoding="utf-8")
    return MissionManifest.from_json(raw)
