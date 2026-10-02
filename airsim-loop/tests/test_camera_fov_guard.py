"""FOV de la camara frontal: no volar si no es el que asume la percepcion (2026-10-02)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.hardware.airsim_client as ac


class _Fake:
    def __init__(self, fov, calls):
        self.fov, self.calls = fov, calls

    def confirmConnection(self):
        pass

    def listVehicles(self):
        return ["Drone1"]

    def simGetCameraInfo(self, *a, **k):
        return SimpleNamespace(fov=self.fov)

    def enableApiControl(self, *a, **k):
        self.calls.append("enableApiControl")

    def armDisarm(self, *a, **k):
        self.calls.append("armDisarm")

    def takeoffAsync(self, *a, **k):
        self.calls.append("takeoff")
        return SimpleNamespace(join=lambda: None)


def _client(monkeypatch, fov):
    calls = []
    monkeypatch.setattr(ac, "airsim", SimpleNamespace(MultirotorClient=lambda **kw: _Fake(fov, calls)))
    c = ac.AirSimClient()
    c.vehicle_name = "Drone1"
    return c, calls


def test_altered_fov_refuses_to_fly(monkeypatch):
    c, calls = _client(monkeypatch, 15.0)
    with pytest.raises(ac.CameraConfigError) as exc:
        c.connect()
    assert "15.0" in str(exc.value) and calls == [] and c._connected is False


def test_expected_fov_connects(monkeypatch):
    c, calls = _client(monkeypatch, ac.CAMERA_HFOV_DEG)
    assert c.connect() is True and "takeoff" in calls
