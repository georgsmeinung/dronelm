# Paso 3: Estimador de TTC por flujo optico (F1.2 del plan de mejoras).
#
# Sustituye a `1.0 / mean(|flow|)` (optical_flow_estimator.py, retirado a
# legacy/): ese estimador no tenia unidades (frames, no segundos), confundia
# magnitud con divergencia (se disparaba con cada giro de yaw) y usaba un FOE
# stub fijo en el centro de la imagen. Este modulo:
#   1. Usa dt real de telemetria, nunca el periodo nominal del lazo.
#   2. Compensa el flujo inducido por la rotacion propia del dron (derotacion)
#      antes de estimar nada, usando pitch/roll/yaw de la telemetria.
#   3. Estima el FOE (Focus of Expansion) por minimos cuadrados ponderados
#      sobre el flujo ya traslacional, con un paso de recorte de outliers.
#   4. Calcula TTC por pixel en segundos: TTC = |p - FOE| * dt / |v_trans|.
#   5. Agrega por celda (sector x banda) con percentil 20 y confianza =
#      fraccion de pixeles validos.
#
# Sin evidencia suficiente (dron en hover, giro puro, flujo bajo el piso de
# ruido) el campo resultante tiene confianza 0 y TTC = inf: no hay clamp
# cosmetico que esconda la falta de senal.
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from .obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field

FLOW_ALGORITHM = os.getenv("FLOW_ALGORITHM", "dis").lower()  # "dis" | "farneback"
FLOW_DOWNSCALE_WIDTH = int(os.getenv("FLOW_DOWNSCALE_WIDTH", "320"))

CAMERA_FX = float(os.getenv("CAMERA_FX", "554.0"))
CAMERA_FY = float(os.getenv("CAMERA_FY", "554.0"))

# Piso de ruido del flujo, en pixeles (a la resolucion de FLOW_DOWNSCALE_WIDTH).
# Por debajo de este modulo, un vector se considera ruido de estimacion, no
# evidencia de movimiento traslacional.
FLOW_NOISE_FLOOR_PX = float(os.getenv("FLOW_NOISE_FLOOR_PX", "0.35"))

# Fraccion minima de pixeles validos en toda la imagen para intentar
# estimar el FOE. Si no se alcanza, no hay evidencia traslacional (hover /
# giro puro) y el campo se devuelve con confianza 0.
MIN_VALID_FRACTION_FOR_FOE = float(os.getenv("MIN_VALID_FRACTION_FOR_FOE", "0.01"))

# Umbral de residuo (en radianes, angulo entre el vector y la recta al FOE
# estimado) para el paso de recorte de outliers tipo RANSAC-lite.
FOE_OUTLIER_ANGLE_RAD = float(os.getenv("FOE_OUTLIER_ANGLE_RAD", "0.35"))

TTC_AGGREGATION_PERCENTILE = float(os.getenv("TTC_AGGREGATION_PERCENTILE", "20"))


def _create_flow_backend():
    if FLOW_ALGORITHM == "dis":
        try:
            return cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        except Exception:
            pass
    return None  # Fallback a Farneback via calcOpticalFlowFarneback


class FlowTTCEstimator:
    """Encapsula el backend de flujo optico + la logica de derotacion/FOE/TTC.

    Se instancia UNA vez en `_build_nodes()` (no por frame): mantiene el
    backend de OpenCV entre llamadas para evitar el costo de recrearlo.
    """

    def __init__(self) -> None:
        self._backend = _create_flow_backend()

    # ------------------------------------------------------------------ #
    # Flujo optico crudo                                                  #
    # ------------------------------------------------------------------ #
    def _compute_flow(self, gray_prev: np.ndarray, gray_cur: np.ndarray) -> np.ndarray:
        if self._backend is not None:
            return self._backend.calc(gray_prev, gray_cur, None)
        return cv2.calcOpticalFlowFarneback(
            gray_prev, gray_cur, None,
            pyr_scale=0.5, levels=3, winsize=15, iterations=3,
            poly_n=5, poly_sigma=1.2, flags=0,
        )

    # ------------------------------------------------------------------ #
    # Derotacion                                                          #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _derotate(
        flow: np.ndarray,
        delta_pitch: float,
        delta_yaw: float,
        delta_roll: float,
        fx: float,
        fy: float,
        cx: float,
        cy: float,
    ) -> np.ndarray:
        """Resta el flujo inducido por la rotacion propia del dron entre frames.

        Mapeo aproximado camara-cuerpo (camara alineada con el eje frontal del
        dron): theta_x ~ pitch (rota columnas -> flujo vertical), theta_y ~
        yaw (rota filas -> flujo horizontal), theta_z ~ roll (giro sobre el
        eje optico).
        """
        h, w = flow.shape[:2]
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        x = xs - cx
        y = ys - cy

        theta_x, theta_y, theta_z = delta_pitch, delta_yaw, delta_roll

        u_rot = (theta_x * x * y / fx) - theta_y * (fx + (x * x) / fx) + theta_z * y
        v_rot = theta_x * (fy + (y * y) / fy) - theta_y * (x * y / fy) - theta_z * x

        derot = flow.copy()
        derot[..., 0] -= u_rot
        derot[..., 1] -= v_rot
        return derot

    # ------------------------------------------------------------------ #
    # FOE por minimos cuadrados ponderados (con un recorte de outliers)   #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _estimate_foe(
        flow_trans: np.ndarray, mag: np.ndarray, valid: np.ndarray, cx: float, cy: float
    ) -> Tuple[Optional[Tuple[float, float]], float]:
        h, w = flow_trans.shape[:2]
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)

        idx = np.where(valid)
        if idx[0].size < 50:
            return None, 0.0

        px = xs[idx]
        py = ys[idx]
        vx = flow_trans[..., 0][idx]
        vy = flow_trans[..., 1][idx]
        vm = mag[idx]

        def solve(px_, py_, vx_, vy_, vm_):
            # Normal al vector de flujo: n = (-vy, vx) / |v|
            nx = -vy_ / vm_
            ny = vx_ / vm_
            w_ = vm_  # ponderar por magnitud: vectores mas largos son mas confiables
            # Sistema normal 2x2: sum(w * n n^T) FOE = sum(w * n * (n . p))
            A11 = np.sum(w_ * nx * nx)
            A12 = np.sum(w_ * nx * ny)
            A22 = np.sum(w_ * ny * ny)
            b1 = np.sum(w_ * nx * (nx * px_ + ny * py_))
            b2 = np.sum(w_ * ny * (nx * px_ + ny * py_))
            A = np.array([[A11, A12], [A12, A22]], dtype=np.float64)
            b = np.array([b1, b2], dtype=np.float64)
            det = np.linalg.det(A)
            if abs(det) < 1e-6:
                return None
            sol = np.linalg.solve(A, b)
            return float(sol[0]), float(sol[1])

        foe = solve(px, py, vx, vy, vm)
        if foe is None:
            return None, 0.0

        # Recorte de outliers tipo RANSAC-lite: un vector es consistente con el
        # FOE si el angulo entre su direccion y la recta (p -> FOE) es chico.
        dpx = foe[0] - px
        dpy = foe[1] - py
        line_norm = np.hypot(dpx, dpy) + 1e-6
        v_norm = vm + 1e-6
        cos_angle = (dpx * vx + dpy * vy) / (line_norm * v_norm)
        cos_angle = np.clip(cos_angle, -1.0, 1.0)
        angle = np.arccos(cos_angle)
        inliers = angle < FOE_OUTLIER_ANGLE_RAD

        if np.count_nonzero(inliers) < 30:
            confidence = float(np.count_nonzero(valid)) / float(h * w)
            return foe, min(confidence, 0.3)

        foe_refined = solve(px[inliers], py[inliers], vx[inliers], vy[inliers], vm[inliers])
        if foe_refined is None:
            foe_refined = foe

        confidence = float(np.count_nonzero(inliers)) / float(h * w)
        return foe_refined, min(confidence * 3.0, 1.0)

    # ------------------------------------------------------------------ #
    # API principal                                                       #
    # ------------------------------------------------------------------ #
    def estimate(
        self,
        curr_frame: Optional[np.ndarray],
        prev_frame: Optional[np.ndarray],
        telemetry_curr: Dict[str, Any],
        telemetry_prev: Optional[Dict[str, Any]],
    ) -> ObstacleField:
        ts_curr = float(telemetry_curr.get("timestamp", 0.0)) if telemetry_curr else 0.0

        if prev_frame is None or curr_frame is None or not telemetry_prev:
            return empty_field(source="none", timestamp=ts_curr)

        ts_prev = float(telemetry_prev.get("timestamp", 0.0))
        dt = ts_curr - ts_prev
        if dt <= 1e-3:
            return empty_field(source="degraded", timestamp=ts_curr)

        gray_prev = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY) if prev_frame.ndim == 3 else prev_frame
        gray_cur = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY) if curr_frame.ndim == 3 else curr_frame

        h0, w0 = gray_cur.shape[:2]
        scale = min(1.0, FLOW_DOWNSCALE_WIDTH / float(w0))
        if scale < 1.0:
            new_w, new_h = int(w0 * scale), int(h0 * scale)
            gray_prev_s = cv2.resize(gray_prev, (new_w, new_h), interpolation=cv2.INTER_AREA)
            gray_cur_s = cv2.resize(gray_cur, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            gray_prev_s, gray_cur_s = gray_prev, gray_cur

        h, w = gray_cur_s.shape[:2]
        fx = CAMERA_FX * scale
        fy = CAMERA_FY * scale
        cx, cy = w / 2.0, h / 2.0

        flow = self._compute_flow(gray_prev_s, gray_cur_s)

        orient_curr = telemetry_curr.get("orientation", {}) or {}
        orient_prev = telemetry_prev.get("orientation", {}) or {}
        delta_pitch = float(orient_curr.get("pitch", 0.0)) - float(orient_prev.get("pitch", 0.0))
        delta_yaw = float(orient_curr.get("yaw", 0.0)) - float(orient_prev.get("yaw", 0.0))
        delta_roll = float(orient_curr.get("roll", 0.0)) - float(orient_prev.get("roll", 0.0))
        # Envolver saltos de +-pi en el yaw (cruce del limite -180/180).
        delta_yaw = (delta_yaw + np.pi) % (2 * np.pi) - np.pi

        flow_trans = self._derotate(flow, delta_pitch, delta_yaw, delta_roll, fx, fy, cx, cy)

        mag = np.linalg.norm(flow_trans, axis=2)
        valid = mag > FLOW_NOISE_FLOOR_PX

        valid_fraction = float(np.count_nonzero(valid)) / float(h * w)
        if valid_fraction < MIN_VALID_FRACTION_FOR_FOE:
            return empty_field(source="flow", timestamp=ts_curr)

        foe, foe_confidence = self._estimate_foe(flow_trans, mag, valid, cx, cy)
        if foe is None or foe_confidence <= 0.0:
            return ObstacleField(
                cells={(s, b): Cell(sector=s, band=b) for s in SECTORS for b in BANDS},
                dt_s=dt, timestamp=ts_curr, source="flow", foe=None, foe_confidence=0.0,
            )

        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        dist_to_foe = np.hypot(xs - foe[0], ys - foe[1])
        with np.errstate(divide="ignore", invalid="ignore"):
            ttc_map = np.where(valid, dist_to_foe * dt / np.maximum(mag, 1e-6), np.inf)

        # Divergencia (Sobel) del campo traslacional: verificacion independiente del TTC.
        du_dx = cv2.Sobel(flow_trans[..., 0], cv2.CV_32F, 1, 0, ksize=3)
        dv_dy = cv2.Sobel(flow_trans[..., 1], cv2.CV_32F, 0, 1, ksize=3)
        divergence_map = (du_dx + dv_dy) / dt

        cells: Dict[Tuple[str, str], Cell] = {}
        col_edges = [0, w // 3, 2 * w // 3, w]
        row_edges = [0, h // 3, 2 * h // 3, h]
        for si, sector in enumerate(SECTORS):
            for bi, band in enumerate(BANDS):
                x0, x1 = col_edges[si], col_edges[si + 1]
                y0, y1 = row_edges[bi], row_edges[bi + 1]
                cell_valid = valid[y0:y1, x0:x1]
                n_valid = int(np.count_nonzero(cell_valid))
                n_total = cell_valid.size
                confidence = n_valid / n_total if n_total else 0.0

                if n_valid < 5:
                    cells[(sector, band)] = Cell(sector=sector, band=band, confidence=confidence)
                    continue

                cell_ttc = ttc_map[y0:y1, x0:x1][cell_valid]
                cell_ttc_finite = cell_ttc[np.isfinite(cell_ttc)]
                ttc_val = (
                    float(np.percentile(cell_ttc_finite, TTC_AGGREGATION_PERCENTILE))
                    if cell_ttc_finite.size > 0 else float("inf")
                )
                cell_div = float(np.mean(divergence_map[y0:y1, x0:x1][cell_valid]))
                cell_occ = float(np.clip(cell_div * 0.5, 0.0, 1.0)) if cell_div > 0 else 0.0

                cells[(sector, band)] = Cell(
                    sector=sector, band=band,
                    occupancy=cell_occ, ttc_s=max(0.0, ttc_val),
                    divergence=cell_div, confidence=confidence * foe_confidence,
                )

        return ObstacleField(cells=cells, dt_s=dt, timestamp=ts_curr, source="flow", foe=foe, foe_confidence=foe_confidence)
