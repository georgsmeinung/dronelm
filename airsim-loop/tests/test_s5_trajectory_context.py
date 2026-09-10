# S5 (PLAN-SLAM): prueba unitaria de trajectory_context_text() con datos sintéticos.
#
# Valida que la función genere contexto correcto en los escenarios que
# importan para slam_assess: zona bloqueada identificada, zona abierta
# identificada, sin datos, y con pocas muestras.
#
# Esta prueba es estática (no lee logs, no requiere AirSim) y corre junto
# al resto del suite con pytest.
from __future__ import annotations

import math

import pytest

from src.agents.spatial_history import FlightTrajectory, TrajectoryEvent

# ─── helpers ─────────────────────────────────────────────────────────────────

def _event(heading_deg: float, stall: bool, action: str = "MANTENER_RUMBO") -> TrajectoryEvent:
    return TrajectoryEvent(
        timestamp=0.0,
        position=(0.0, 0.0, 0.0),
        heading_deg=heading_deg,
        action_taken=action,
        delta_wp_m=0.3 if stall else -0.3,
        stall=stall,
        flow_had_evidence=True,
    )


def _fill_traj(events) -> FlightTrajectory:
    t = FlightTrajectory(max_size=100)
    for ev in events:
        t.record(ev)
    return t


# ─── tests ───────────────────────────────────────────────────────────────────

def test_empty_trajectory_returns_no_data_message():
    t = FlightTrajectory()
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "sin datos" in text.lower()


def test_single_event_returns_data():
    t = _fill_traj([_event(0.0, stall=False)])
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "sin datos" not in text.lower()
    assert "FRENTE" in text


def test_frente_blocked_when_high_stall_rate():
    """Si >70% de intentos FRENTE terminan en stall → 'Zona probable de bloqueo'."""
    events = [_event(heading_deg=0.0, stall=True) for _ in range(8)]
    events += [_event(heading_deg=0.0, stall=False) for _ in range(2)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "FRENTE" in text
    assert "Zona probable de bloqueo" in text


def test_frente_clear_when_no_stalls():
    """Si 0 stalls en FRENTE → 'Sin stalls registrados'."""
    events = [_event(heading_deg=0.0, stall=False) for _ in range(10)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "FRENTE" in text
    assert "Sin stalls registrados" in text
    assert "Zona probable de bloqueo" not in text


def test_zone_assignment_izquierda():
    """Eventos con heading 90° a la izquierda del rumbo actual van a IZQUIERDA."""
    # rumbo actual = 0°, heading del evento = -90° → rel = -90° → IZQUIERDA
    events = [_event(heading_deg=-90.0, stall=True) for _ in range(8)]
    events += [_event(heading_deg=-90.0, stall=False) for _ in range(2)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "IZQUIERDA" in text
    assert "Zona probable de bloqueo" in text


def test_zone_assignment_derecha():
    """Eventos con heading 90° a la derecha del rumbo actual van a DERECHA."""
    # rumbo actual = 0°, heading del evento = +90° → rel = +90° → DERECHA
    events = [_event(heading_deg=90.0, stall=True) for _ in range(8)]
    events += [_event(heading_deg=90.0, stall=False) for _ in range(2)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "DERECHA" in text
    assert "Zona probable de bloqueo" in text


def test_stall_count_summary_line():
    """La línea de resumen reporta los ciclos en stall acumulados."""
    events = [_event(0.0, stall=True) for _ in range(5)]
    events += [_event(0.0, stall=False) for _ in range(5)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "Ciclos en stall acumulados: 5" in text


def test_max_events_cap():
    """max_events limita los eventos usados para el resumen."""
    events = [_event(0.0, stall=True) for _ in range(50)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=0.0, max_events=10)
    assert "últimos 10 ciclos" in text


def test_relative_zone_wraps_correctly():
    """El cálculo de zona relativa envuelve correctamente cruzando ±180°."""
    # rumbo actual = 170°, heading evento = -170° (190°).
    # Diferencia relativa = (-170 - 170 + 180) % 360 - 180 = (-160+180)%360-180 = 20° → FRENTE
    events = [_event(heading_deg=-170.0, stall=True) for _ in range(8)]
    events += [_event(heading_deg=-170.0, stall=False) for _ in range(2)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=170.0)
    assert "FRENTE" in text
    assert "Zona probable de bloqueo" in text


def test_unexplored_zone_marked_correctly():
    """Zona con 0 intentos aparece como 'No explorado'."""
    events = [_event(heading_deg=0.0, stall=False) for _ in range(5)]
    t = _fill_traj(events)
    text = t.trajectory_context_text(current_heading_deg=0.0)
    assert "No explorado" in text


def test_frente_stall_rate_high():
    """frente_stall_rate() devuelve la tasa correcta con mayoría de stalls."""
    events = [_event(0.0, stall=True) for _ in range(7)]
    events += [_event(0.0, stall=False) for _ in range(3)]
    t = _fill_traj(events)
    rate = t.frente_stall_rate(current_heading_deg=0.0)
    assert abs(rate - 0.7) < 1e-9


def test_zone_stats_returns_correct_attempts_and_rate():
    """zone_stats() devuelve intentos y tasa correctos por zona."""
    events = [_event(0.0, stall=True) for _ in range(7)]    # FRENTE, stall
    events += [_event(0.0, stall=False) for _ in range(3)]  # FRENTE, ok
    events += [_event(-90.0, stall=False) for _ in range(5)]  # IZQUIERDA
    t = _fill_traj(events)
    stats = t.zone_stats(current_heading_deg=0.0)
    assert stats["FRENTE"]["attempts"] == 10
    assert abs(stats["FRENTE"]["stall_rate"] - 0.7) < 1e-9
    assert stats["IZQUIERDA"]["attempts"] == 5
    assert stats["DERECHA"]["attempts"] == 0


def test_frente_stall_rate_no_events():
    """frente_stall_rate() devuelve 0.0 sin eventos en FRENTE."""
    events = [_event(90.0, stall=True) for _ in range(5)]  # todos en DERECHA
    t = _fill_traj(events)
    rate = t.frente_stall_rate(current_heading_deg=0.0)
    assert rate == 0.0
