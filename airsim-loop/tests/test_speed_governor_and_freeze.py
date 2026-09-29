"""Gobernador de velocidad y vigilante de congelamiento (2026-0929)."""
from __future__ import annotations

import src.navigation.speed_governor as sg
from src.navigation.freeze_watchdog import FreezeWatchdog, pick_recovery_pose
from src.navigation.speed_governor import SpeedGovernor


# ------------------------------------------------------------------ gobernador
def _run(gov, n, source="flow", bf=0.0, maneuver=False, action="MANTENER_RUMBO"):
    cap = None
    for _ in range(n):
        cap = gov.update(source, bf, maneuver, action)
    return cap


def test_no_cap_with_fresh_flow_evidence():
    assert _run(SpeedGovernor(), 20, "flow") is None


def test_cap_grows_stricter_without_flow_evidence():
    g = SpeedGovernor()
    assert _run(g, sg.GOV_MID_CYCLES - 1, "degraded") is None          # aun tolerable
    assert _run(g, 1, "degraded") == sg.GOV_MID_MPS                    # sin evidencia unos ciclos
    assert _run(g, sg.GOV_SLOW_CYCLES, "none") == sg.GOV_SLOW_MPS      # sin evidencia prolongada
    assert _run(g, 1, "flow") is None                                   # el flujo valido lo libera


def test_holdover_does_not_count_as_blind():
    g = SpeedGovernor()
    _run(g, 2, "degraded")
    assert _run(g, 10, "holdover") is None                              # ni suma ni resetea; no supera el umbral


def test_blocked_front_slows_then_releases():
    g = SpeedGovernor()
    assert _run(g, 1, "flow", action="GIRAR_90") == sg.GOV_SLOW_MPS
    assert _run(g, sg.GOV_BLOCK_MEMORY_CYCLES - 1, "flow") == sg.GOV_SLOW_MPS
    assert _run(g, 1, "flow") is None                                   # memoria agotada


def test_full_blocked_fraction_also_counts():
    g = SpeedGovernor()
    assert _run(g, 1, "flow", bf=1.0) == sg.GOV_SLOW_MPS


def test_ramp_after_maneuver_is_monotonic_up_to_cruise():
    g = SpeedGovernor()
    _run(g, 3, "flow", maneuver=True, action="EVADIR_IZQUIERDA")   # sin memoria de bloqueo: aisla la rampa
    caps = []
    for _ in range(sg.GOV_RAMP_CYCLES + 2):
        caps.append(g.update("flow", 0.0, False, "MANTENER_RUMBO"))
    seq = [c for c in caps if c is not None]
    assert seq and seq == sorted(seq)                                   # solo sube
    assert seq[0] < 2.0 and caps[-1] is None                            # arranca lento y termina libre


def test_disabled_governor_never_caps(monkeypatch):
    monkeypatch.setattr(sg, "GOV_ENABLED", False)
    assert _run(SpeedGovernor(), 30, "degraded", bf=1.0, action="GIRAR_90") is None


# ------------------------------------------------------------------ congelamiento
def _t(x=1.0, yaw=0.1, landed=1, source="airsim", noise=0.0):
    return {"position": {"x": x + noise, "y": 2.0, "z": -10.0},
            "orientation": {"yaw": yaw, "pitch": 0.0, "roll": 0.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "landed_state": landed, "source": source}


def test_frozen_after_n_identical_cycles():
    w = FreezeWatchdog(cycles=5)
    for _ in range(6):
        w.update(_t())
    assert w.frozen and w.count == 5


def test_any_real_motion_or_noise_resets_the_count():
    w = FreezeWatchdog(cycles=5)
    for _ in range(4):
        w.update(_t())
    w.update(_t(noise=1e-3))          # ruido de sensor de un vuelo real
    assert w.count == 0 and not w.frozen


def test_landed_and_non_airsim_telemetry_are_not_freezes():
    w = FreezeWatchdog(cycles=3)
    for _ in range(10):
        w.update(_t(landed=0))        # en el suelo: lo cubre la guarda de despegue
    assert not w.frozen
    for _ in range(10):
        w.update(_t(source="simulated"))
    assert not w.frozen


def test_pick_recovery_pose_prefers_last_moving_free_pose_before_the_freeze():
    hist = [(c, float(c), 0.0, -10.0, 90.0, 2.0 if c < 90 else 0.2) for c in range(1, 121)]
    # congelado desde c100; hay que quedarse >= 30 ciclos antes (c<=70) y en movimiento
    pose = pick_recovery_pose(hist, frozen_since=100, backoff=30, min_speed=0.8)
    assert pose == (70.0, 0.0, -10.0, 90.0)
    assert pick_recovery_pose(hist, frozen_since=20, backoff=30) is None    # no hay historia suficiente
    slow = [(c, float(c), 0.0, -10.0, 0.0, 0.1) for c in range(1, 60)]
    assert pick_recovery_pose(slow, frozen_since=50, backoff=10) == (40.0, 0.0, -10.0, 0.0)  # sin ninguna en movimiento
