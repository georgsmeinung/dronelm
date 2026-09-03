"""Tests for the AirSim bridge and LoopRunner (no real simulator)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from airsim_plan.bridge import AirSimBridge, LoopRunner, LoopRunnerError
from airsim_plan.bridge.loop_runner import LoopRunner as LR
from airsim_plan.missions import load_manifest


GOOD_MANIFEST = {
    "mission_id": "PERIMETER_NORTH_01",
    "summary": "x",
    "waypoints": [
        {"x": 0, "y": 50, "z": -10},
        {"x": 50, "y": 100, "z": -10},
    ],
}


from airsim_plan.bridge import BridgeError

def test_bridge_dry_run_takeoff() -> None:
    bridge = AirSimBridge()
    with pytest.raises(BridgeError):
        bridge.hand_off(altitude=-5.0)
    bridge.disconnect()


def test_bridge_initial_state_shape() -> None:
    manifest = load_manifest(
        Path(__file__).resolve().parent.parent / "missions" / "perimeter_north_01.json"
    )

    runner = LoopRunner(manifest)
    state = runner.build_initial_state()
    assert state["mission_id"] == "PERIMETER_NORTH_01"
    assert len(state["waypoints"]) == 7


def test_loop_runner_handles_missing_package(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = load_manifest(
        Path(__file__).resolve().parent.parent / "missions" / "perimeter_north_01.json"
    )
    runner = LoopRunner(manifest)

    # Forzar que falle el import.
    import builtins

    orig_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # noqa: ANN001
        if name == LR.LOOP_PACKAGE:
            raise ImportError("synthetic failure")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(LoopRunnerError):
        runner._run_in_process({"mission_id": manifest.mission_id})


def test_loop_runner_invokes_graph_then_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = load_manifest(
        Path(__file__).resolve().parent.parent / "missions" / "perimeter_north_01.json"
    )
    runner = LoopRunner(manifest)

    fake_module = MagicMock()
    fake_graph = MagicMock()

    calls = {"n": 0}

    def invoke(state):  # noqa: ANN001
        calls["n"] += 1
        # Primer llamado: mantener rumbo. Segundo llamado: RTL -> el loop debe salir.
        if calls["n"] == 2:
            return {
                "next_action": "RETURN_TO_LAUNCH",
                "velocity_command": {},
                "route": "deliberative",
            }
        return {
            "next_action": "MANTENER_RUMBO",
            "velocity_command": {},
            "route": "reactive",
        }

    fake_graph.invoke.side_effect = invoke
    fake_module.compile_workflow.return_value = fake_graph
    monkeypatch.setitem(__import__("sys").modules, LR.LOOP_PACKAGE, fake_module)

    # Reemplazar el bridge para no hablar de verdad con AirSim.
    bridge = MagicMock()
    bridge.hand_off.return_value = True
    bridge.land.return_value = True
    runner._bridge = bridge

    runner._run_in_process(
        {
            "mission_id": manifest.mission_id,
            "waypoints": [w.model_dump() for w in manifest.waypoints],
        }
    )
    assert calls["n"] == 2
    # El runner se corrió vía _run_in_process directamente, así que el bridge
    # solo se consulta a través del entrypoint explícito run(). Verificar que
    # el mock del grafo y del bridge quedaron intactos por lo demás.
    bridge.hand_off.assert_not_called()
    bridge.land.assert_not_called()


def test_loop_runner_run_calls_bridge_then_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = load_manifest(
        Path(__file__).resolve().parent.parent / "missions" / "perimeter_north_01.json"
    )
    runner = LoopRunner(manifest)

    fake_module = MagicMock()
    fake_graph = MagicMock()

    calls = {"n": 0}

    def invoke(state):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "next_action": "RETURN_TO_LAUNCH",
                "velocity_command": {},
                "route": "deliberative",
            }
        raise AssertionError("should not be called more than once")

    fake_graph.invoke.side_effect = invoke
    fake_module.compile_workflow.return_value = fake_graph
    monkeypatch.setitem(__import__("sys").modules, LR.LOOP_PACKAGE, fake_module)

    bridge = MagicMock()
    bridge.hand_off.return_value = True
    bridge.land.return_value = True
    runner._bridge = bridge

    runner.run()
    bridge.hand_off.assert_called_once()
    bridge.land.assert_called_once()
    assert calls["n"] == 1
