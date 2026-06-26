"""airsim-plan: Ground-station Mission Planner.

Two-brain architecture:

    NL instruction --> MissionPlanner (LLM, ground) --> Manifest JSON
                                                         |
                            +-----------------------------+
                            |
                            v
                    airsim-loop (tactical SLM in LangGraph)
                                 |
                                 v
                              AirSim

This package only ships the ground side: NL -> structured Manifest,
manifest validation, persistence, and the handoff (takeoff + invoke
the in-flight tactical loop).
"""

from .config import Settings, get_settings
from .missions.manifest import (
    MissionManifest,
    RulesOfEngagement,
    Waypoint,
    load_manifest,
    save_manifest,
)
from .missions.planner import MissionPlanner

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "get_settings",
    "MissionManifest",
    "RulesOfEngagement",
    "Waypoint",
    "load_manifest",
    "save_manifest",
    "MissionPlanner",
]
