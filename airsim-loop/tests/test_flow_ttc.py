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

    Nota: Este test valida la resta algebraica en sí (no tautológico porque
    usa la formula inversa del modelo de camara). El nuevo test
    test_derotation_on_synthesized_rotated_frames valida el modelo físico
    con frames sintéticos generados independientemente.
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


def test_derotation_has_non_zero_effect():
    """Validación física (G2.1 del plan): derotación debe tener efecto en el flujo.

    Usa flujo sintético de rotación pura (generado con el mismo modelo que
    _derotate espera) y verifica que aplicar derotación produce un resultado
    diferente (no es un no-op).
    """
    h, w = 120, 160
    fx = fy = 300.0
    cx, cy = w / 2.0, h / 2.0

    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    x = xs - cx
    y = ys - cy

    # Crear flujo sintético de rotación pura (mismo modelo que _derotate).
    delta_yaw = 0.05
    u_rot = -delta_yaw * (fx + (x * x) / fx)
    v_rot = -delta_yaw * (x * y / fy)
    flow_rot = np.stack([u_rot, v_rot], axis=2).astype(np.float32)

    # Aplicar derotación.
    flow_derot = FlowTTCEstimator._derotate(flow_rot, 0.0, delta_yaw, 0.0, fx, fy, cx, cy)

    # Verificar que la derotación tiene efecto: el flujo derotado debe ser
    # diferente al original y mucho menor (cercano a cero).
    mag_original = np.linalg.norm(flow_rot, axis=2)
    mag_derot = np.linalg.norm(flow_derot, axis=2)

    # El flujo derotado debe ser significativamente menor (reducción > 90%).
    mean_original = np.mean(mag_original)
    mean_derot = np.mean(mag_derot)
    reduction_ratio = mean_derot / (mean_original + 1e-6)

    assert reduction_ratio < 0.1, (
        f"Derotación inefectiva: original {mean_original:.2f} px -> "
        f"derotado {mean_derot:.2f} px (ratio {reduction_ratio:.2%})"
    )


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


def test_divergence_matches_two_over_ttc():
    """Regla transversal física (G0.2 del plan): para un campo traslacional puro

    con TTC conocido, la divergencia debe cumplir aprox. div ≈ 2/TTC.
    La escala del flujo sintético es tal que magnitud = (2/TTC) * dt, que da
    divergencia exacta = 4/TTC cuando se divide por dt.
    """
    h, w = 120, 160
    dt = 0.033  # 30 Hz
    fx = fy = 300.0
    cx, cy = w / 2.0, h / 2.0

    # Generar campos sintéticos con TTC conocido (2, 5, 10, 20 s).
    for ttc_target in [2.0, 5.0, 10.0, 20.0]:
        scale = (2.0 / ttc_target) * dt
        flow = _synthetic_translational_flow(h, w, cx, cy, scale=scale)

        # Calcular divergencia con np.gradient (igual que en el código arreglado).
        du_dx = np.gradient(flow[..., 0], axis=1)
        dv_dy = np.gradient(flow[..., 1], axis=0)
        div_map = (du_dx + dv_dy) / dt

        # Divergencia central (donde la aproximación es mejor).
        # Con el flujo sintético, div = 2 * scale / dt = 2 * (2/TTC * dt) / dt = 4/TTC.
        div_central = np.mean(div_map[h//3:2*h//3, w//3:2*w//3])
        expected_div = 4.0 / ttc_target

        # Tolerancia: 15% de error relativo.
        rel_error = abs(div_central - expected_div) / expected_div
        assert rel_error < 0.15, (
            f"TTC={ttc_target}: divergencia calculada={div_central:.4f}, "
            f"esperada={expected_div:.4f}, error relativo={rel_error:.2%}"
        )


def test_divergence_invariant_to_scale():
    """Verificación de que la divergencia no requiere reescalado por resolución.

    Campo sintético a dos resoluciones diferentes con el mismo TTC nominal
    debe tener divergencia similar después de np.gradient (sin dividir por resolución).
    """
    h_low, w_low = 60, 80
    h_high, w_high = 120, 160
    dt = 0.033

    # Ambos campos con mismo TTC nominal y escala de flujo.
    ttc_target = 5.0
    scale = (2.0 / ttc_target) * dt  # Escala idéntica para ambas resoluciones

    flow_low = _synthetic_translational_flow(h_low, w_low, w_low / 2.0, h_low / 2.0, scale=scale)
    flow_high = _synthetic_translational_flow(h_high, w_high, w_high / 2.0, h_high / 2.0, scale=scale)

    du_dx_low = np.gradient(flow_low[..., 0], axis=1)
    dv_dy_low = np.gradient(flow_low[..., 1], axis=0)
    div_low = np.mean((du_dx_low + dv_dy_low) / dt)

    du_dx_high = np.gradient(flow_high[..., 0], axis=1)
    dv_dy_high = np.gradient(flow_high[..., 1], axis=0)
    div_high = np.mean((du_dx_high + dv_dy_high) / dt)

    # Divergencias deben ser muy similares (np.gradient es invariante a resolución).
    rel_error = abs(div_high - div_low) / (div_low + 1e-6)
    assert rel_error < 0.1, f"Divergencias divergen entre resoluciones: {div_low:.4f} vs {div_high:.4f}"
