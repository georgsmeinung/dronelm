# Paso 2: Inferencia matemática con YOLOv8.
# Detecta objetos en una imagen y devuelve una lista estructurada de
# detecciones con coordenadas en pixeles.
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, List, Optional

try:
    from ultralytics import YOLO  # type: ignore
except Exception:  # pragma: no cover - the dependency is optional at import time
    YOLO = None  # type: ignore


@dataclass
class Detection:
    """Caja delimitadora de un objeto detectado por YOLOv8."""

    object: str
    confidence: float
    bbox: List[float]  # [x_min, y_min, x_max, y_max] en pixeles

    def to_dict(self) -> dict:
        return asdict(self)


class YoloDetector:
    """Envoltorio ligero alrededor de Ultralytics YOLOv8."""

    def __init__(
        self,
        weights_path: str = "weights/yolov8n.pt",
        confidence_threshold: float = 0.35,
        device: Optional[str] = None,
    ) -> None:
        self.weights_path = weights_path
        self.confidence_threshold = confidence_threshold
        self.device = device
        self._model: Optional[Any] = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        if YOLO is None:
            raise RuntimeError(
                "ultralytics no esta instalado. Ejecuta "
                "`pip install ultralytics` para habilitar la deteccion."
            )
        self._model = YOLO(self.weights_path)
        return self._model

    def detect(self, image: Any) -> List[Detection]:
        """Ejecuta la inferencia sobre una imagen (numpy array o ruta)."""
        if image is None:
            return []
        model = self._ensure_model()
        results = model.predict(
            source=image,
            conf=self.confidence_threshold,
            device=self.device,
            verbose=False,
        )
        detections: List[Detection] = []
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls.item()) if box.cls is not None else -1
                label = names.get(cls_id, str(cls_id))
                conf = float(box.conf.item()) if box.conf is not None else 0.0
                xyxy = box.xyxy[0].tolist() if box.xyxy is not None else [0, 0, 0, 0]
                detections.append(
                    Detection(object=label, confidence=conf, bbox=[float(v) for v in xyxy])
                )
        return detections
