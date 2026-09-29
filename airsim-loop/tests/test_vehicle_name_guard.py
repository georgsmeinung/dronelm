"""Nombre de vehiculo: fallar claro en vez de tumbar Unreal (2026-0929)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.hardware.airsim_client as ac


class _FakeMultirotor:
    def __init__(self, vehicles, calls):
        self._vehicles, self.calls = vehicles, calls

    def confirmConnection(self):
        pass

    def listVehicles(self):
        return self._vehicles

    def enableApiControl(self, *a, **k):
        self.calls.append("enableApiControl")

    def armDisarm(self, *a, **k):
        self.calls.append("armDisarm")

    def takeoffAsync(self, *a, **k):
        self.calls.append("takeoff")
        return SimpleNamespace(join=lambda: None)


def _client(monkeypatch, vehicles, vehicle_name):
    calls = []
    monkeypatch.setattr(ac, "airsim", SimpleNamespace(MultirotorClient=lambda **kw: _FakeMultirotor(vehicles, calls)))
    c = ac.AirSimClient()
    c.vehicle_name = vehicle_name
    return c, calls


def test_connect_fails_clearly_when_vehicle_does_not_exist(monkeypatch):
    c, calls = _client(monkeypatch, ["Drone1"], "SimpleFlight")
    with pytest.raises(ac.VehicleNotFoundError) as exc:
        c.connect()
    assert "SimpleFlight" in str(exc.value) and "Drone1" in str(exc.value)
    assert calls == []                      # no se envio ningun comando con el nombre invalido
    assert c._connected is False


def test_connect_ok_when_vehicle_exists(monkeypatch):
    c, calls = _client(monkeypatch, ["Drone1"], "Drone1")
    assert c.connect() is True
    assert "enableApiControl" in calls


def test_connect_skips_check_when_server_lists_nothing(monkeypatch):
    c, _ = _client(monkeypatch, [], "Drone1")
    assert c.connect() is True


def test_env_vehicle_name_matches_settings_json():
    """config/.env y airsim-settings/settings.json deben nombrar al mismo vehiculo."""
    root = Path(__file__).resolve().parents[2]
    env_file, settings_file = root / "config" / ".env", root / "airsim-settings" / "settings.json"
    if not (env_file.exists() and settings_file.exists()):
        pytest.skip("faltan config/.env o airsim-settings/settings.json")
    m = re.search(r'^\s*AIRSIM_VEHICLE_NAME\s*=\s*"?([^"\r\n#]+)"?', env_file.read_text(encoding="utf-8"), re.M)
    assert m, "AIRSIM_VEHICLE_NAME no esta en config/.env"
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    vehicles = list((settings.get("Vehicles") or {}).keys()) or ["SimpleFlight"]   # AirSim: sin bloque Vehicles -> SimpleFlight
    assert m.group(1).strip() in vehicles, (
        f"config/.env AIRSIM_VEHICLE_NAME={m.group(1).strip()!r} no esta en settings.json {vehicles}"
    )


def test_no_hardcoded_vehicle_name_fallback_anywhere():
    """config/.env es la unica fuente del nombre de vehiculo: ningun script lo repite como literal."""
    root = Path(__file__).resolve().parents[2]
    pat = re.compile(r"getenv\(\s*[\"']AIRSIM_VEHICLE_NAME[\"']\s*,\s*[\"']")
    offenders = []
    for sub in ("airsim-loop", "airsim-plan", "callibration-flight", "airsim-cmd", "airsim-mcp", "airsim-poc", "airsim-kc"):
        base = root / sub
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            if any(part in ("airsim-runs", "node_modules", ".venv", "__pycache__") for part in f.parts):
                continue
            try:
                if pat.search(f.read_text(encoding="utf-8")):
                    offenders.append(str(f.relative_to(root)))
            except OSError:
                pass
    assert offenders == [], f"nombre de vehiculo con valor por defecto en codigo: {offenders}"
