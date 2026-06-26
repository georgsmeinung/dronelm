"""Centralized configuration via env vars (.env loaded lazily)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings for the planner.

    Values are pulled from environment variables (loaded from a local
    ``.env`` if present). The class is immutable so the same instance
    can be safely shared across modules.
    """

    # LM Studio / OpenAI-compatible ground planner
    lmstudio_base_url: str = field(
        default_factory=lambda: os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    )
    lmstudio_api_key: str = field(
        default_factory=lambda: os.getenv("LMSTUDIO_API_KEY", "lm-studio")
    )
    lmstudio_model: str = field(
        default_factory=lambda: os.getenv("LMSTUDIO_MODEL", "llama-3-8b-instruct")
    )

    # Tactical SLM (Phi-3) — only used to compose prompts handed to
    # airsim-loop; the actual call happens there.
    tactical_base_url: str = field(
        default_factory=lambda: os.getenv("TACTICAL_BASE_URL", "http://localhost:1234/v1")
    )
    tactical_api_key: str = field(
        default_factory=lambda: os.getenv("TACTICAL_API_KEY", "lm-studio")
    )
    tactical_model: str = field(
        default_factory=lambda: os.getenv("TACTICAL_MODEL", "phi-3-mini-4k-instruct")
    )

    # AirSim (used only for the takeoff hand-off)
    airsim_host: str = field(default_factory=lambda: os.getenv("AIRSIM_HOST", "127.0.0.1"))
    airsim_vehicle_name: str = field(
        default_factory=lambda: os.getenv("AIRSIM_VEHICLE_NAME", "Drone0")
    )
    airsim_port: int = field(
        default_factory=lambda: int(os.getenv("AIRSIM_PORT", "41451"))
    )

    # Mission defaults
    default_takeoff_alt: float = field(
        default_factory=lambda: float(os.getenv("DEFAULT_TAKEOFF_ALT", "-10.0"))
    )
    default_speed: float = field(
        default_factory=lambda: float(os.getenv("DEFAULT_SPEED", "5.0"))
    )

    # Where compiled manifests land (relative to CWD unless absolute).
    mission_dir: Path = field(
        default_factory=lambda: Path(os.getenv("MISSION_DIR", "missions")).expanduser()
    )

    # LLM sampling
    planner_temperature: float = field(
        default_factory=lambda: float(os.getenv("PLANNER_TEMPERATURE", "0.2"))
    )
    planner_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("PLANNER_MAX_TOKENS", "800"))
    )

    # Optional classes that are always considered non-hostile (ROE hints).
    default_ignore_classes: List[str] = field(
        default_factory=lambda: _csv(os.getenv("DEFAULT_IGNORE_CLASSES", "person,car"))
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Cached so that ``.env`` is only parsed once per process.
    """
    return Settings()
