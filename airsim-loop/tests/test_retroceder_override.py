# Tests para _lateral_first_override() en slam_assess (deep_scan.py).
#
# Cubre Override 1a (3 zonas bloqueadas con intentos confirmados),
# Override 1b (drone inmovilizado: buffer saturado de stalls FRENTE sin
# ningún intento lateral — escenario confirmado con code_version=35367d3b),
# Override 1c (gap 1a/1b: pocos intentos laterales pero todos con stall —
# diagnosticado seed_1 c1267-1315: izq=2 stall 100%, der=0),
# y Override 2 (VLM vertical pero laterales no exploradas).
from __future__ import annotations

import math

import pytest

from src.agents.deep_scan import _lateral_first_override
from src.agents.spatial_history import FlightTrajectory, TrajectoryEvent


def _event(heading_deg: float, stall: bool) -> TrajectoryEvent:
    return TrajectoryEvent(
        timestamp=0.0,
        position=(0.0, 0.0, 0.0),
        heading_deg=heading_deg,
        action_taken="MANTENER_RUMBO",
        delta_wp_m=0.4 if stall else -0.4,
        stall=stall,
        flow_had_evidence=True,
    )


def _traj_frente_stalls(n: int, stall_count: int, heading: float = 0.0) -> FlightTrajectory:
    t = FlightTrajectory(max_size=100)
    for i in range(n):
        t.record(_event(heading_deg=heading, stall=(i < stall_count)))
    return t


def _telemetry(yaw_deg: float = 0.0) -> dict:
    return {"orientation": {"pitch": 0.0, "roll": 0.0, "yaw": math.radians(yaw_deg)}}


# ── Override 1b ───────────────────────────────────────────────────────────────

def test_override_1b_fires_when_drone_immobilized():
    """Buffer saturado de stalls FRENTE (>=90%, >=20) sin intentos laterales -> RETROCEDER."""
    traj = _traj_frente_stalls(n=30, stall_count=30)  # 100% stall FRENTE, 30 intentos
    decision = {"macro_action": "PERDER_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    assert result["macro_action"] == "RETROCEDER"


def test_override_1b_not_fires_with_insufficient_events():
    """Menos de 20 intentos FRENTE: Override 1b no dispara (aun no saturado)."""
    traj = _traj_frente_stalls(n=15, stall_count=15)  # 100% stall pero solo 15 eventos
    decision = {"macro_action": "PERDER_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    # Sin laterales exploradas, Override 2 debería haber disparado EVADIR_IZQUIERDA
    assert result["macro_action"] != "RETROCEDER"


def test_override_1b_not_fires_when_stall_rate_low():
    """Stall rate <90% en FRENTE: Override 1b no dispara."""
    # 20 eventos: 17 stalls (85%) → debajo del umbral del 90%
    traj = _traj_frente_stalls(n=20, stall_count=17)
    decision = {"macro_action": "GANAR_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    assert result["macro_action"] != "RETROCEDER"


def test_override_1b_not_fires_when_laterals_have_attempts():
    """Si hay intentos laterales, Override 1b no aplica (no es el escenario de inmovilización)."""
    traj = FlightTrajectory(max_size=100)
    # 25 stalls FRENTE (100%)
    for _ in range(25):
        traj.record(_event(0.0, stall=True))
    # 2 intentos IZQUIERDA
    for _ in range(2):
        traj.record(_event(-90.0, stall=False))
    decision = {"macro_action": "GANAR_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    assert result["macro_action"] != "RETROCEDER"


# ── Override 1c ───────────────────────────────────────────────────────────────

def test_override_1c_fires_izq_stalled_der_zero():
    """FRENTE>=90%/>=20 + izq=2 intentos (100% stall) + der=0 -> RETROCEDER.
    Caso exacto de seed_1 c1267-1315 donde 1a falló (izq<3) y 1b falló (izq≠0)."""
    traj = FlightTrajectory(max_size=100)
    for _ in range(25):
        traj.record(_event(0.0, stall=True))    # FRENTE: 25 stalls (100%)
    for _ in range(2):
        traj.record(_event(-90.0, stall=True))  # IZQUIERDA: 2 intentos, todos stall
    decision = {"macro_action": "GANAR_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    assert result["macro_action"] == "RETROCEDER"


def test_override_1c_not_fires_when_izq_not_stalled():
    """izq=2 intentos con éxito (stall=False): Override 1c no dispara (hay dirección libre)."""
    traj = FlightTrajectory(max_size=100)
    for _ in range(25):
        traj.record(_event(0.0, stall=True))
    for _ in range(2):
        traj.record(_event(-90.0, stall=False))  # IZQUIERDA: 2 intentos sin stall
    decision = {"macro_action": "GANAR_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    assert result["macro_action"] != "RETROCEDER"


# ── Override 1a ───────────────────────────────────────────────────────────────

def test_override_1a_fires_all_three_zones_blocked():
    """FRENTE>=70% + IZQUIERDA>=70% (>=3 int) + DERECHA>=70% (>=3 int) -> RETROCEDER."""
    traj = FlightTrajectory(max_size=100)
    for _ in range(8):
        traj.record(_event(0.0, stall=True))    # FRENTE stalls
    for _ in range(2):
        traj.record(_event(0.0, stall=False))   # FRENTE ok
    for _ in range(4):
        traj.record(_event(-90.0, stall=True))  # IZQUIERDA stalls (4 int, 100%)
    for _ in range(4):
        traj.record(_event(90.0, stall=True))   # DERECHA stalls (4 int, 100%)
    decision = {"macro_action": "MANTENER_RUMBO", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    assert result["macro_action"] == "RETROCEDER"


# ── Override 2 ────────────────────────────────────────────────────────────────

def test_override_2_forces_evadir_izquierda_when_vlm_says_vertical():
    """VLM=GANAR_ALTURA + FRENTE bloqueado + laterales no exploradas -> EVADIR_IZQUIERDA."""
    traj = _traj_frente_stalls(n=10, stall_count=8)  # 80% stall FRENTE
    decision = {"macro_action": "GANAR_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, traj, _telemetry(0.0))
    assert result["macro_action"] == "EVADIR_IZQUIERDA"


def test_no_override_when_trajectory_is_none():
    """Sin trayectoria disponible: la decisión del VLM pasa sin modificación."""
    decision = {"macro_action": "GANAR_ALTURA", "rationale": "VLM"}
    result = _lateral_first_override(decision, None, _telemetry(0.0))
    assert result["macro_action"] == "GANAR_ALTURA"


# ── Fix 14: zona ATRÁS en zone_stats ─────────────────────────────────────────

def test_atras_zone_detects_rear_stalls():
    """zone_stats registra stalls ATRÁS cuando el drone se mueve 180° del heading.
    Fix 14 usa esta zona para reducir el factor RETROCEDER y evitar colisión trasera."""
    traj = FlightTrajectory(max_size=100)
    heading = 0.0  # drone apunta al norte
    # Movimientos hacia ATRÁS (≥150° del heading=0): heading ≈ 180°
    for _ in range(3):
        traj.record(TrajectoryEvent(
            timestamp=0.0, position=(0.0, 0.0, 0.0),
            heading_deg=180.0, action_taken="RETROCEDER",
            delta_wp_m=0.1, stall=True, flow_had_evidence=True,
        ))
    stats = traj.zone_stats(heading)
    atras = stats["ATRÁS"]
    assert atras["attempts"] == 3
    assert atras["stall_rate"] == pytest.approx(1.0)


def test_atras_zone_clear_when_no_rear_stalls():
    """zone_stats ATRÁS muestra 0 intentos si nunca hubo movimiento hacia atrás.
    Fix 14 NO reduce el factor RETROCEDER en este caso."""
    traj = FlightTrajectory(max_size=100)
    for _ in range(5):
        traj.record(_event(0.0, stall=True))  # solo FRENTE
    stats = traj.zone_stats(0.0)
    assert stats["ATRÁS"]["attempts"] == 0
