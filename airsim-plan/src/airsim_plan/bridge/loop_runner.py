"""Hands the compiled manifest to ``airsim-loop``.

``airsim-loop`` is a separate Python package with its own graph, but it
exports ``compile_workflow`` and ``DroneState``. We invoke it in-process
if importable, otherwise we fall back to ``python -m`` as a subprocess.

The :class:`LoopRunner` centralises three things:

* AirSim pre-flight (delegated to :class:`AirSimBridge`).
* Pre-prompt injection (Step 3 of the pipeline).
* Running the tactical loop until ``RETURN_TO_LAUNCH`` or KeyboardInterrupt.
"""
from __future__ import annotations

import importlib
import runpy
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import Settings, get_settings
from ..missions.manifest import MissionManifest
from .airsim_bridge import AirSimBridge, BridgeError


class LoopRunnerError(RuntimeError):
    """Raised when the tactical loop cannot be launched."""


class LoopRunner:
    """Coordinates AirSim pre-flight + invocation of ``airsim-loop``."""

    LOOP_PACKAGE = "airsim_loop"

    def __init__(
        self,
        manifest: MissionManifest,
        *,
        bridge: Optional[AirSimBridge] = None,
        settings: Optional[Settings] = None,
        loop_path: Optional[Path] = None,
        loop_hz: float = 0.5,
    ) -> None:
        self._manifest = manifest
        self._settings = settings or get_settings()
        self._bridge = bridge or AirSimBridge(settings=self._settings)
        self._loop_path = loop_path  # if None we use in-process import
        self._loop_hz = max(loop_hz, 0.05)

    # ------------------------------------------------------------------ #
    # Properties                                                        #
    # ------------------------------------------------------------------ #
    @property
    def manifest(self) -> MissionManifest:
        return self._manifest

    @property
    def bridge(self) -> AirSimBridge:
        return self._bridge

    # ------------------------------------------------------------------ #
    # Pre-prompt injection                                              #
    # ------------------------------------------------------------------ #
    def build_initial_state(self) -> Dict[str, Any]:
        """Build the initial ``DroneState`` injected into ``airsim-loop``."""
        return {
            "mission_id": self._manifest.mission_id,
            "waypoints": [w.model_dump() for w in self._manifest.waypoints],
            "rules_of_engagement": self._manifest.rules_of_engagement.model_dump(),
            "tactical_system_prompt": self._manifest.tactical_system_prompt,
        }

    # ------------------------------------------------------------------ #
    # Public API                                                        #
    # ------------------------------------------------------------------ #
    def run(self, *, takeoff_altitude: Optional[float] = None) -> None:
        """Take off + drive the tactical loop until interrupted."""
        try:
            self._bridge.hand_off(altitude=takeoff_altitude)
        except BridgeError as exc:
            raise LoopRunnerError(str(exc)) from exc

        initial_state = self.build_initial_state()
        try:
            if self._loop_path is not None:
                self._run_as_subprocess(initial_state)
            else:
                self._run_in_process(initial_state)
        finally:
            try:
                self._bridge.land()
            except BridgeError:  # pragma: no cover
                pass
            self._bridge.disconnect()

    # ------------------------------------------------------------------ #
    # In-process execution                                              #
    # ------------------------------------------------------------------ #
    def _run_in_process(self, initial_state: Dict[str, Any]) -> None:
        try:
            loop_module = importlib.import_module(self.LOOP_PACKAGE)
        except Exception as exc:
            raise LoopRunnerError(
                f"Could not import {self.LOOP_PACKAGE!r} in-process "
                f"({exc}). Pass `loop_path` to fall back to subprocess."
            ) from exc

        if not hasattr(loop_module, "compile_workflow"):
            raise LoopRunnerError(
                f"{self.LOOP_PACKAGE!r} does not expose compile_workflow()."
            )

        graph = loop_module.compile_workflow()
        sleep_s = 1.0 / self._loop_hz
        print(
            f"[LoopRunner] Entering tactical loop "
            f"(mission={self._manifest.mission_id}, hz={self._loop_hz})."
        )
        try:
            while True:
                t0 = time.time()
                try:
                    state = graph.invoke(dict(initial_state))
                except Exception as exc:  # pragma: no cover - graph runtime
                    print(f"[LoopRunner] graph.invoke failed: {exc}")
                    time.sleep(sleep_s)
                    continue
                action = state.get("next_action", "")
                if action == "RETURN_TO_LAUNCH":
                    print("[LoopRunner] RETURN_TO_LAUNCH received. Stopping loop.")
                    break
                elapsed = time.time() - t0
                time.sleep(max(0.0, sleep_s - elapsed))
        except KeyboardInterrupt:
            print("\n[LoopRunner] KeyboardInterrupt — stopping loop.")

    # ------------------------------------------------------------------ #
    # Subprocess fallback                                               #
    # ------------------------------------------------------------------ #
    def _run_as_subprocess(self, initial_state: Dict[str, Any]) -> None:
        script = Path(self._loop_path).resolve()
        if not script.exists():
            raise LoopRunnerError(f"loop script not found: {script}")
        # We piggy-back on runpy so the user can run their existing
        # `python airsim-loop/main.py` flow but with env vars set.
        env_path = self._settings.mission_dir / f"{self._manifest.mission_id}.preloop.json"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(
            self._manifest.to_json(indent=2), encoding="utf-8"
        )
        previous = {
            "AIRSIM_PLAN_MANIFEST": str(env_path),
            "AIRSIM_PLAN_TACTICAL_PROMPT": self._manifest.tactical_system_prompt or "",
        }
        try:
            sys.argv = [str(script)]
            with __import__("contextlib").redirect_stdout(sys.stdout):
                runpy.run_path(str(script), run_name="__main__", init_globals=previous)
        except SystemExit as exc:  # pragma: no cover - delegated
            if exc.code not in (None, 0):
                raise LoopRunnerError(f"loop exited with code {exc.code}") from exc
