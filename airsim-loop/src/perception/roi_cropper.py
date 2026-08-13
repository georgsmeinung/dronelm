from __future__ import annotations

import os
import math
from typing import Tuple
import numpy as np

DEFAULT_CAMERA_FOV_DIAGONAL = float(os.getenv("CAMERA_FOV_DIAGONAL", "90.0"))
DEFAULT_ROI_DIAGONAL = float(os.getenv("ROI_DIAGONAL", "62.0"))


def crop_roi_62(
    image: np.ndarray,
    fov_diagonal_deg: float = DEFAULT_CAMERA_FOV_DIAGONAL,
    roi_diagonal_deg: float = DEFAULT_ROI_DIAGONAL,
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """Recorta la imagen a un campo de visión diagonal especificado (ej. 62°).

    Returns:
        Tuple[np.ndarray, Tuple[int, int, int, int]]:
            - roi_image: sub-imagen recortada.
            - bbox_offset: (x_offset, y_offset, roi_width, roi_height)
    """
    if image is None or image.size == 0:
        return image, (0, 0, 0, 0)

    h, w = image.shape[:2]

    # Relación de aspecto del marco
    aspect_ratio = w / float(h)

    # Cálculo trigonométrico exacto del factor de escala del ROI
    fov_rad = math.radians(fov_diagonal_deg)
    roi_rad = math.radians(roi_diagonal_deg)

    # Ancho angular normalizado o escala basada en tangentes para la proyección de la cámara
    scale = math.tan(roi_rad / 2.0) / math.tan(fov_rad / 2.0)
    scale = max(0.1, min(1.0, scale))

    roi_w = int(w * scale)
    roi_h = int(h * scale)

    x_offset = (w - roi_w) // 2
    y_offset = (h - roi_h) // 2

    roi_image = image[y_offset : y_offset + roi_h, x_offset : x_offset + roi_w]
    return roi_image, (x_offset, y_offset, roi_w, roi_h)
