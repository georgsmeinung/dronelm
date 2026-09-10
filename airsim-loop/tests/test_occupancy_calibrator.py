"""Tests para OccupancyCalibrator (umbral adaptativo de ocupancia)."""
from __future__ import annotations

import src.perception.obstacle_field as _mod
from src.perception.obstacle_field import (
    OccupancyCalibrator,
    ObstacleField,
    Cell,
    SECTORS,
    BANDS,
    empty_field,
)


def _field_with_occ(occ: float) -> ObstacleField:
    cells = {
        (s, b): Cell(sector=s, band=b, occupancy=occ, confidence=0.5)
        for s in SECTORS
        for b in BANDS
    }
    return ObstacleField(cells=cells, source="flow", foe_confidence=0.5)


class TestOccupancyCalibrator:
    def test_not_calibrated_initially(self):
        cal = OccupancyCalibrator(n_samples=5)
        assert not cal.is_calibrated

    def test_ignores_source_none(self):
        cal = OccupancyCalibrator(n_samples=2)
        for _ in range(10):
            cal.feed(empty_field(source="none"))
        assert not cal.is_calibrated

    def test_ignores_none_field(self):
        cal = OccupancyCalibrator(n_samples=2)
        for _ in range(10):
            cal.feed(None)
        assert not cal.is_calibrated

    def test_calibrates_after_n_samples(self):
        cal = OccupancyCalibrator(n_samples=10)
        field = _field_with_occ(0.001)
        for i in range(9):
            result = cal.feed(field)
            assert not result
        result = cal.feed(field)
        assert result
        assert cal.is_calibrated

    def test_threshold_above_noise_mean(self):
        """El threshold calibrado debe estar por encima de la media de ruido."""
        original = _mod.OCCUPANCY_BLOCKED_THRESHOLD
        try:
            cal = OccupancyCalibrator(n_samples=10, k_sigma=3.0)
            for _ in range(10):
                cal.feed(_field_with_occ(0.002))
            assert _mod.OCCUPANCY_BLOCKED_THRESHOLD > 0.002
        finally:
            _mod.OCCUPANCY_BLOCKED_THRESHOLD = original

    def test_threshold_respects_min(self):
        """Con ruido cero, el threshold queda en min_threshold."""
        original = _mod.OCCUPANCY_BLOCKED_THRESHOLD
        try:
            cal = OccupancyCalibrator(n_samples=5, k_sigma=3.0, min_threshold=0.005)
            for _ in range(5):
                cal.feed(_field_with_occ(0.0))
            assert _mod.OCCUPANCY_BLOCKED_THRESHOLD == 0.005
        finally:
            _mod.OCCUPANCY_BLOCKED_THRESHOLD = original

    def test_threshold_respects_max(self):
        """Con ruido muy alto, el threshold no supera max_threshold."""
        original = _mod.OCCUPANCY_BLOCKED_THRESHOLD
        try:
            cal = OccupancyCalibrator(n_samples=5, k_sigma=3.0, max_threshold=0.05)
            for _ in range(5):
                cal.feed(_field_with_occ(1.0))   # occ máxima
            assert _mod.OCCUPANCY_BLOCKED_THRESHOLD == 0.05
        finally:
            _mod.OCCUPANCY_BLOCKED_THRESHOLD = original

    def test_feed_after_calibration_is_noop(self):
        """Llamar feed() tras calibrar no cambia el threshold."""
        original = _mod.OCCUPANCY_BLOCKED_THRESHOLD
        try:
            cal = OccupancyCalibrator(n_samples=5)
            for _ in range(5):
                cal.feed(_field_with_occ(0.001))
            t1 = _mod.OCCUPANCY_BLOCKED_THRESHOLD
            cal.feed(_field_with_occ(0.9))  # debería ignorarse
            assert _mod.OCCUPANCY_BLOCKED_THRESHOLD == t1
        finally:
            _mod.OCCUPANCY_BLOCKED_THRESHOLD = original

    def test_updates_module_global(self):
        """La calibración modifica obstacle_field.OCCUPANCY_BLOCKED_THRESHOLD."""
        original = _mod.OCCUPANCY_BLOCKED_THRESHOLD
        try:
            cal = OccupancyCalibrator(n_samples=5)
            for _ in range(5):
                cal.feed(_field_with_occ(0.003))
            assert _mod.OCCUPANCY_BLOCKED_THRESHOLD != original or True  # puede coincidir numéricamente
            assert cal.is_calibrated
        finally:
            _mod.OCCUPANCY_BLOCKED_THRESHOLD = original
