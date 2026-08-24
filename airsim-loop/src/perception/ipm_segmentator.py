import os
import cv2
import numpy as np
from typing import Tuple, Any

# Optional: use scikit-image if available for SLIC segmentation
try:
    from skimage.segmentation import slic
    from skimage.color import rgb2lab
except ImportError:
    slic = None
    rgb2lab = None

class IPMSegmentator:
    """Segmentador basado en Inverse Perspective Mapping (IPM) y superpíxeles.

    La función principal `segment` toma el frame actual, el frame anterior y la telemetría
    del dron (que incluye la altitud Z). Calcula una homografía que proyecta el plano del
    suelo a una vista ortogonal, resta los frames para resaltar obstáculos 3‑D y luego
    genera superpíxeles (SLIC) para obtener una máscara binaria del obstáculo.
    """

    def __init__(self):
        # Parámetros configurable vía .env (se leen cuando se llama segment)
        self.fov_deg = float(os.getenv("CAMERA_FOV_DEG", "90"))
        self.fx = float(os.getenv("CAMERA_FX", "554.0"))
        self.fy = float(os.getenv("CAMERA_FY", "554.0"))
        self.cx = float(os.getenv("CAMERA_CX", "540.0"))
        self.cy = float(os.getenv("CAMERA_CY", "360.0"))
        self.slic_segments = int(os.getenv("SLIC_N_SEGMENTS", "200"))
        self.slic_compactness = float(os.getenv("SLIC_COMPACTNESS", "10.0"))

    def _compute_homography(self, altitude: float) -> np.ndarray:
        """Calcula la matriz de homografía que lleva la imagen a una vista de plano.
        Asume que la cámara está orientada hacia abajo con un ángulo pequeño.
        """
        # Punto del plano Z=0 (suelo) a escala real usando la distancia focal
        # Simplificación: asumimos que la cámara está apuntando horizontalmente.
        # La homografía típica para IPM: H = K * [R|t] * [I|0]^{-1}
        # Aquí usamos una aproximación basada en la altitud y la distancia focal.
        K = np.array([[self.fx, 0, self.cx], [0, self.fy, self.cy], [0, 0, 1]])
        # Rotación de cámara (asumimos pitch=0, roll=0, yaw=0) → identidad
        R = np.eye(3)
        t = np.array([[0], [0], [-altitude]])  # cámara a altura positiva Z
        # Matriz de proyección simplificada
        H = K @ (R - t @ np.array([[0, 0, 1]]))
        # Normalizamos
        H = H / H[2, 2]
        return H

    def _apply_ipm(self, image: np.ndarray, H: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        return cv2.warpPerspective(image, H, (w, h), flags=cv2.INTER_LINEAR)

    def _segment_superpixels(self, diff: np.ndarray) -> np.ndarray:
        """Aplica SLIC sobre la diferencia de frames para obtener etiquetas."""
        if slic is None:
            # Fallback simple: k‑means on Lab colors
            lab = cv2.cvtColor(diff, cv2.COLOR_BGR2LAB)
            reshaped = lab.reshape(-1, 3).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
            _, labels, _ = cv2.kmeans(reshaped, self.slic_segments, None, criteria, 1, cv2.KMEANS_PP_CENTERS)
            return labels.reshape(diff.shape[:2])
        else:
            # Convert to Lab for mejor segmentación
            lab = rgb2lab(diff) if rgb2lab else cv2.cvtColor(diff, cv2.COLOR_BGR2LAB)
            segments = slic(lab, n_segments=self.slic_segments, compactness=self.slic_compactness, start_label=1)
            return segments

    def segment(self, image: np.ndarray, prev_frame: np.ndarray | None, telemetry: dict) -> Tuple[np.ndarray, float, np.ndarray]:
        """Genera la máscara de obstáculo y el overlay.

        Returns
        -------
        mask: np.ndarray (uint8) binaria donde 1 indica posible obstáculo.
        occlusion_ratio: float porcentaje de píxeles en máscara.
        annotated: np.ndarray imagen original con overlay rojo semitransparente.
        """
        # Altitud en metros (negativa en AirSim telemetry)
        altitude = abs(telemetry.get("position", {}).get("z", 10.0))
        H = self._compute_homography(altitude)
        ipm_cur = self._apply_ipm(image, H)
        if prev_frame is None:
            diff = np.zeros_like(ipm_cur)
        else:
            ipm_prev = self._apply_ipm(prev_frame, H)
            diff = cv2.absdiff(ipm_cur, ipm_prev)
        # Resaltar cambios (obstáculos)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
        # Superpíxeles para agrupar regiones
        segments = self._segment_superpixels(diff)
        # Media de intensidad por segmento
        mask = np.zeros_like(thresh, dtype=np.uint8)
        for seg_id in np.unique(segments):
            seg_mask = (segments == seg_id)
            if np.mean(thresh[seg_mask]) > 127:
                mask[seg_mask] = 255
        occlusion_ratio = (np.count_nonzero(mask) / mask.size) * 100.0
        # Overlay rojo semitransparente
        overlay = image.copy()
        red_layer = np.zeros_like(image)
        red_layer[:] = (0, 0, 255)
        alpha = 0.4
        mask_3c = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        overlay = np.where(mask_3c == 255, cv2.addWeighted(image, 1 - alpha, red_layer, alpha, 0), image)
        return mask, occlusion_ratio, overlay
