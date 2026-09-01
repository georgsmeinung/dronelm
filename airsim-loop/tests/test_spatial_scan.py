# Fase H1 (PLAN-MEJORAS-3): escaneo espacial inicial.
from __future__ import annotations

import math
import time

import numpy as np
import pytest

import src.agents.spatial_scan as spatial_scan_mod


class _StubAirSimClient:
    """Mismo patron que _StubAirSimClient de test_graph_integration.py:
    interfaz capture/execute_velocity/get_telemetry, sin AirSim real."""

    def __init__(self):
        self.yaw_deg = 0.0
        self.capture_calls = []
        self.velocity_calls = []

    def get_telemetry(self):
        return {
            "position": {"x": 0.0, "y": 0.0, "z": -10.0},
            "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": math.radians(self.yaw_deg)},
        }

    def execute_velocity(self, vx, vy, vz, yaw_rate=0.0, target_yaw=None):
        self.velocity_calls.append((vx, vy, vz, yaw_rate, target_yaw))
        # Simula el giro instantaneo (los tests no ejercitan la dinamica real).
        if target_yaw is not None:
            self.yaw_deg = target_yaw
        return True

    def capture(self, return_depth=False):
        self.capture_calls.append({"return_depth": return_depth})
        frame = np.random.randint(0, 255, size=(60, 80, 3), dtype=np.uint8)
        return frame, self.get_telemetry()


def test_initial_scan_never_requests_depth(monkeypatch):
    monkeypatch.setenv("SCAN_HEADING_COUNT", "4")
    monkeypatch.setattr(spatial_scan_mod, "SCAN_HEADING_COUNT", 4)
    monkeypatch.setattr(spatial_scan_mod, "INITIAL_SCAN_SETTLE_S", 0.0)
    monkeypatch.setattr(
        spatial_scan_mod,
        "_query_scan_vlm_with_watchdog",
        lambda frames: {"available": False, "reason": "stub", "headings": [], "recommended_heading_deg": None, "notes": "", "raw_response": "", "latency_ms": 0.0},
    )

    client = _StubAirSimClient()
    spatial_scan_mod.run_initial_scan(client)

    assert client.capture_calls, "el escaneo inicial debe capturar al menos un frame"
    assert all(call["return_depth"] is False for call in client.capture_calls)


def test_initial_scan_labels_images_by_heading_not_by_time(monkeypatch):
    """Invariante F2.1/H1.2: las etiquetas deben ser por rumbo ([Rumbo XXX°]),
    nunca por fotograma temporal (t-N) -- el eje de este barrido es espacial,
    no temporal."""
    monkeypatch.setattr(spatial_scan_mod, "SCAN_HEADING_COUNT", 3)
    monkeypatch.setattr(spatial_scan_mod, "INITIAL_SCAN_SETTLE_S", 0.0)

    captured_prompts = {}

    def _fake_query(frames):
        images_b64 = []
        labels = []
        for heading, frame in frames:
            labels.append(f"[Rumbo {heading:.0f}°]")
            images_b64.append("fake_b64")
        captured_prompts["labels"] = labels
        return {
            "available": True, "reason": None, "headings": [], "recommended_heading_deg": 0.0,
            "notes": "", "raw_response": "{}", "latency_ms": 1.0,
        }

    monkeypatch.setattr(spatial_scan_mod, "_query_scan_vlm_with_watchdog", _fake_query)

    client = _StubAirSimClient()
    spatial_scan_mod.run_initial_scan(client)

    labels = captured_prompts["labels"]
    assert len(labels) == 3
    for label in labels:
        assert label.startswith("[Rumbo ")
        assert "t-" not in label
        assert "Fotograma" not in label


def test_initial_scan_vlm_timeout_does_not_block_mission_start(monkeypatch):
    """H1.3.3: un timeout del VLM no debe bloquear el retorno de la funcion
    mas alla de INITIAL_SCAN_TIMEOUT_MS, y la mision debe poder seguir sin
    contexto (available=False)."""
    monkeypatch.setattr(spatial_scan_mod, "SCAN_HEADING_COUNT", 2)
    monkeypatch.setattr(spatial_scan_mod, "INITIAL_SCAN_SETTLE_S", 0.0)
    monkeypatch.setattr(spatial_scan_mod, "INITIAL_SCAN_TIMEOUT_MS", 300.0)

    def _slow_query(frames):
        time.sleep(5.0)  # mucho mas lento que el watchdog de 300ms
        return None, "", "no deberia llegar aca"

    monkeypatch.setattr(spatial_scan_mod, "_query_scan_vlm_impl", _slow_query)

    client = _StubAirSimClient()
    t0 = time.time()
    result = spatial_scan_mod.run_initial_scan(client)
    elapsed_s = time.time() - t0

    assert result["available"] is False
    assert result["reason"] == "timeout"
    # Margen generoso sobre el watchdog para tolerar jitter del scheduler,
    # pero muy por debajo de los 5s que tardaria la consulta lenta.
    assert elapsed_s < 2.0


def test_initial_scan_survives_vlm_unavailable(monkeypatch):
    """Un VLM caido (openai no instalado / servidor no responde) nunca debe
    impedir que la mision arranque: run_initial_scan no debe lanzar."""
    monkeypatch.setattr(spatial_scan_mod, "SCAN_HEADING_COUNT", 2)
    monkeypatch.setattr(spatial_scan_mod, "INITIAL_SCAN_SETTLE_S", 0.0)
    monkeypatch.setattr(spatial_scan_mod, "OpenAI", None)

    client = _StubAirSimClient()
    result = spatial_scan_mod.run_initial_scan(client)
    assert result["available"] is False
