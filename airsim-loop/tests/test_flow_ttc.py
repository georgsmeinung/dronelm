import numpy as np
import pytest

from src.perception.flow_ttc import FlowTTCEstimator


def _synthetic_translational_flow(h, w, foe_x, foe_y, scale=0.05):
    """Campo de flujo puramente traslacional: cada vector apunta desde el FOE,

    con magnitud proporcional a la distancia (aproximacion de looming).
    """
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = xs - foe_x
    dy = ys - foe_y
    flow = np.stack([dx * scale, dy * scale], axis=2).astype(np.float32)
    return flow


def test_foe_recovered_from_synthetic_translational_flow():
    h, w = 120, 160
    true_foe = (70.0, 55.0)
    flow = _synthetic_translational_flow(h, w, *true_foe)
    mag = np.linalg.norm(flow, axis=2)
    valid = mag > 0.35

    foe, confidence = FlowTTCEstimator._estimate_foe(flow, mag, valid, w / 2.0, h / 2.0)

    assert foe is not None
    assert confidence > 0.0
    assert abs(foe[0] - true_foe[0]) < 5.0
    assert abs(foe[1] - true_foe[1]) < 5.0


def test_derotation_cancels_pure_yaw_rotation():
    """Regresion del bug documentado en CHANGELOG 2026-0820: un giro de yaw

    puro (sin traslacion) no debe producir flujo traslacional residual tras
    la derotacion. En la version retirada (1/mean(|flow|)) cada giro
    desplomaba el TTC espuriamente y disparaba el freno de seguridad.
    """
    h, w = 120, 160
    fx = fy = 300.0
    cx, cy = w / 2.0, h / 2.0
    delta_yaw = 0.02  # radianes entre frames, giro pequeno tipico de un ciclo

    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    x = xs - cx
    y = ys - cy
    # Mismo modelo que _derotate: flujo inducido por rotacion pura en yaw (theta_y).
    u_rot = -delta_yaw * (fx + (x * x) / fx)
    v_rot = -delta_yaw * (x * y / fy)
    pure_rotation_flow = np.stack([u_rot, v_rot], axis=2).astype(np.float32)

    derot = FlowTTCEstimator._derotate(pure_rotation_flow, 0.0, delta_yaw, 0.0, fx, fy, cx, cy)

    assert np.max(np.abs(derot)) < 1e-3


def test_derotation_preserves_translational_signal():
    h, w = 120, 160
    fx = fy = 300.0
    cx, cy = w / 2.0, h / 2.0
    trans_flow = _synthetic_translational_flow(h, w, cx, cy, scale=0.05)

    derot = FlowTTCEstimator._derotate(trans_flow, 0.0, 0.0, 0.0, fx, fy, cx, cy)

    assert np.allclose(derot, trans_flow)


def test_estimate_returns_empty_field_without_previous_frame():
    est = FlowTTCEstimator()
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    telem = {"timestamp": 1.0, "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0}}
    field = est.estimate(frame, None, telem, None)
    assert field.source == "none"
    assert field.min_ttc() == float("inf")


def test_estimate_returns_degraded_field_on_nonpositive_dt():
    est = FlowTTCEstimator()
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    telem_prev = {"timestamp": 5.0, "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0}}
    telem_curr = {"timestamp": 5.0, "orientation": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0}}
    field = est.estimate(frame, frame, telem_curr, telem_prev)
    assert field.source == "degraded"
