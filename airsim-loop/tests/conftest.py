"""Fixtures comunes de los tests."""
from __future__ import annotations

import pytest


class _StubDepthEstimator:
    """Sin red real: los tests no cargan Depth Anything ni usan la GPU. Todo libre por defecto."""

    def __init__(self, *a, **k):
        pass

    def sectors(self, frame):
        from src.perception.depth_estimator import CELLS

        return {"p5": {c: 100.0 for c in CELLS}, "latency_ms": 0.0}


@pytest.fixture(autouse=True)
def _no_real_depth_network(monkeypatch):
    monkeypatch.setattr("src.agents.depth_client.DepthEstimator", _StubDepthEstimator)
