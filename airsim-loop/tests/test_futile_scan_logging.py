"""Auditoria de escaneos fallidos y StallDetector.reset_freeze (2026-0928)."""
from src.agents.deep_scan import _record_failed_scan
from src.agents.stall_detector import StallDetector


def test_failed_scan_leaves_audit_entry_and_frames():
    state = {"_pending_delib_prompt": "P", "_pending_delib_frames": [("frame", 1.0)]}
    _record_failed_scan(state, "respuesta rara", "sin_accion_viable", 12.3)
    entry = state["deliberations"][-1]
    assert entry["id"] == 1
    assert entry["raw_response"] == "respuesta rara"
    assert entry["prompt"] == "P"
    assert entry["is_fallback"] is True and entry["adherent"] is False
    assert state["_last_delib_frames"] == [("frame", 1.0)]
    assert state["_pending_delib_frames"] is None


def test_failed_scan_watchdog_marks_timeout():
    state = {}
    _record_failed_scan(state, "", "watchdog", 9000.0)
    assert state["deliberations"][-1]["timeout"] is True
    assert state["_last_delib_frames"] == []


def test_reset_freeze_clears_counters():
    sd = StallDetector()
    sd._pos_freeze_cycles = 80
    sd._stopped_cycles = 40
    sd.reset_freeze()
    assert sd.pos_freeze_cycles == 0 and sd.stopped_cycles == 0
