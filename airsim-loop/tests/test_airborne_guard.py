"""El dron debe estar volando al empezar: rearmar si un reset diferido lo desarma (2026-0929)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import src.hardware.airsim_client as ac


class _Sim:
    """Simulador falso: `landed_states` es la secuencia de landed_state que devuelve getMultirotorState."""

    def __init__(self, landed_states, takeoff_fixes=True):
        self.states, self.calls, self.takeoff_fixes = list(landed_states), [], takeoff_fixes
        self.late_reset_once = False
        self.current = self.states.pop(0) if self.states else 1

    def getMultirotorState(self, vehicle_name=""):
        ls = self.current
        return SimpleNamespace(landed_state=ls)

    def enableApiControl(self, *a, **k):
        self.calls.append("enable")

    def armDisarm(self, *a, **k):
        self.calls.append("arm")

    def takeoffAsync(self, *a, **k):
        self.calls.append("takeoff")

        def _join():
            if self.late_reset_once:          # el reset diferido de Unreal deshace el primer despegue
                self.late_reset_once = False
                self.current = 0
            elif self.takeoff_fixes:
                self.current = 1
        return SimpleNamespace(join=_join)


def _client(sim):
    c = ac.AirSimClient()
    c._connected, c._client = True, sim
    return c


def test_airborne_client_is_left_alone():
    sim = _Sim([1])
    assert _client(sim).ensure_airborne(settle_s=0) is True
    assert sim.calls == []                       # ya volaba: no se toca


def test_landed_client_is_rearmed_and_takes_off_again():
    sim = _Sim([0])                              # desarmado / posado
    assert _client(sim).ensure_airborne(settle_s=0) is True
    assert sim.calls == ["enable", "arm", "takeoff"]


def test_gives_up_after_the_configured_attempts():
    sim = _Sim([0], takeoff_fixes=False)         # el despegue no surte efecto
    assert _client(sim).ensure_airborne(attempts=2, settle_s=0) is False
    assert sim.calls.count("takeoff") == 2


def test_unknown_landed_state_does_not_block():
    sim = _Sim([1])
    sim.getMultirotorState = lambda vehicle_name="": SimpleNamespace()   # el servidor no informa el campo
    assert _client(sim).ensure_airborne(settle_s=0) is True


def test_reset_verifies_flight_after_its_takeoff(monkeypatch):
    sim = _Sim([1])
    sim.late_reset_once = True                   # tras reset+takeoff el dron queda posado (reset diferido)
    sim.reset = lambda: sim.calls.append("reset")
    c = _client(sim)
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)
    assert c.reset() is True
    assert sim.calls[0] == "reset" and sim.calls.count("takeoff") == 2   # el suyo + el rearmado
    assert sim.current == 1                                              # y termina volando


def test_console_tee_writes_to_file_and_restores_streams(tmp_path):
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "experiments"))
    import runner

    out0, err0 = sys.stdout, sys.stderr
    restore = runner._tee_console(tmp_path / "c.log")
    print("hola consola")
    restore()
    assert sys.stdout is out0 and sys.stderr is err0
    assert "hola consola" in (tmp_path / "c.log").read_text(encoding="utf-8")
