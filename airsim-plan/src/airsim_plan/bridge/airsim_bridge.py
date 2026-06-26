"""Thin AirSim wrapper used ONLY for the pre-flight hand-off.

The tactical SLM (in ``airsim-loop``) already owns its own client; this
class only takes care of ``arm`` + ``takeoff`` so the planner can hand
authority over to the loop with a single call.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

try:
    import airsim  # type: ignore
except Exception:  # pragma: no cover
    airsim = None  # type: ignore

from ..config import Settings, get_settings


class BridgeError(RuntimeError):
    """Raised when the hand-off to AirSim cannot be completed."""


@dataclass
class AirSimBridge:
    """Arms the vehicle and takes off before the tactical loop starts."""

    settings: Optional[Settings] = None

    def __post_init__(self) -> None:
        self._settings: Settings = self.settings or get_settings()
        self._client: Any = None
        self._connected: bool = False

    # ------------------------------------------------------------------ #
    # Connection                                                        #
    # ------------------------------------------------------------------ #
    def connect(self) -> bool:
        if airsim is None:
            print("[AirSimBridge] cosys-airsim not installed; running in dry-run mode.")
            self._connected = False
            return False
        try:
            self._client = airsim.MultirotorClient(
                ip=self._settings.airsim_host,
                port=self._settings.airsim_port,
            )
            self._client.confirmConnection()
            self._client.enableApiControl(True, self._settings.airsim_vehicle_name)
            self._connected = True
            return True
        except Exception as exc:  # pragma: no cover - depends on simulator
            print(f"[AirSimBridge] connect() failed: {exc}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._client is None or not self._connected:
            return
        try:
            self._client.armDisarm(False, self._settings.airsim_vehicle_name)
            self._client.enableApiControl(False, self._settings.airsim_vehicle_name)
        except Exception:  # pragma: no cover
            pass
        self._connected = False

    # ------------------------------------------------------------------ #
    # Take-off hand-off                                                 #
    # ------------------------------------------------------------------ #
    def takeoff(self, altitude: Optional[float] = None) -> bool:
        """Arm + takeoff. ``altitude`` defaults to ``DEFAULT_TAKEOFF_ALT`` (NED)."""
        target_z = float(
            altitude if altitude is not None else self._settings.default_takeoff_alt
        )
        if not self._connected or self._client is None:
            print(
                f"[AirSimBridge][dry-run] takeoff to z={target_z} on "
                f"{self._settings.airsim_vehicle_name}."
            )
            return True
        try:
            self._client.armDisarm(True, self._settings.airsim_vehicle_name)
            self._client.takeoffAsync(
                vehicle_name=self._settings.airsim_vehicle_name
            ).join()
            # Move to requested altitude.
            self._client.moveToZAsync(
                target_z,
                1.0,
                vehicle_name=self._settings.airsim_vehicle_name,
            ).join()
            return True
        except Exception as exc:
            raise BridgeError(f"takeoff failed: {exc}") from exc

    def land(self) -> bool:
        if not self._connected or self._client is None:
            print("[AirSimBridge][dry-run] land.")
            return True
        try:
            self._client.landAsync(vehicle_name=self._settings.airsim_vehicle_name).join()
            return True
        except Exception as exc:
            raise BridgeError(f"land failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Handoff                                                           #
    # ------------------------------------------------------------------ #
    def hand_off(self, altitude: Optional[float] = None) -> bool:
        """Connect, arm, takeoff. Returns True when the drone is airborne."""
        if not self._connected:
            self.connect()
        return self.takeoff(altitude=altitude)
