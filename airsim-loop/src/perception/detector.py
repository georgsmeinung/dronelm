# Paso 2: Inferencia matemática con YOLOv8.
# Detecta objetos en una imagen y devuelve una lista estructurada de
# Detecciones con coordenadas en pixeles e implementa detección de colisión por tasa de crecimiento (looming).
from __future__ import annotations

import cv2
import numpy as np
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


@dataclass
class CollisionResult:
    """Resultado del analisis de colision basado en tasa de crecimiento (looming)."""

    has_collision_danger: bool
    dangerous_classes: List[str]
    growth_rates: dict[str, float]
    occupancies: dict[str, float]

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Configuración del algoritmo de colisión por tasa de crecimiento (looming)
# ---------------------------------------------------------------------------
IGNORE_CLASSES = frozenset({
    "sky", "road", "sidewalk", "terrain",
    "background", "bg", "void", "unlabeled", "background-unlabeled",
})

CLASS_CONFIGS = {
    # Objetos pequeños/críticos — floor bajo, muy sensibles
    "traffic light": {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "traffic sign":  {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "stop sign":     {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "pole":          {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "fire hydrant":  {"min_growth_rate": 0.8, "min_floor_pct": 0.3},

    # Personas y vehículos ligeros
    "person":     {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "rider":      {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "bicycle":    {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "motorcycle": {"min_growth_rate": 0.8, "min_floor_pct": 0.5},

    # Estructuras grandes — umbral de aproximación más agresivo
    "building":   {"min_growth_rate": 1.5, "min_floor_pct": 2.0},
    "wall":       {"min_growth_rate": 1.5, "min_floor_pct": 2.0},
    "fence":      {"min_growth_rate": 1.2, "min_floor_pct": 1.5},
    "vegetation": {"min_growth_rate": 1.5, "min_floor_pct": 2.0},
    "tree":       {"min_growth_rate": 1.5, "min_floor_pct": 2.0},

    # Vehículos
    "car":   {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
    "truck": {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
    "bus":   {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
    "train": {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
}

DEFAULT_CLASS_CONFIG = {"min_growth_rate": 1.0, "min_floor_pct": 0.5}
EMA_ALPHA = 0.4


class YoloDetector:
    """Envoltorio ligero alrededor de Ultralytics YOLOv8 con detección de colisión integrada."""

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

        # Estado temporal para la detección de colisiones
        self.prev_class_roi_occupancy: dict[str, float] = {}
        self.ema_growth_rates: dict[str, float] = {}
        self.last_collision_result = CollisionResult(
            has_collision_danger=False,
            dangerous_classes=[],
            growth_rates={},
            occupancies={}
        )

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
        """Ejecuta la inferencia sobre una imagen y realiza el análisis de colisiones por looming."""
        if image is None:
            return []
        model = self._ensure_model()
        
        # Ejecutamos con conf=min(confidence_threshold, 0.1) para capturar objetos incipientes para colisiones
        conf_inference = min(self.confidence_threshold, 0.1)
        results = model.predict(
            source=image,
            conf=conf_inference,
            device=self.device,
            verbose=False,
        )

        detections: List[Detection] = []
        
        # 1. Extraer detecciones estándar y pseudo-detecciones semánticas (filtrando por confidence_threshold)
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            
            # Cajas delimitadoras tradicionales (detección/segmentación de instancias)
            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    cls_id = int(box.cls.item()) if box.cls is not None else -1
                    label = names.get(cls_id, str(cls_id))
                    conf = float(box.conf.item()) if box.conf is not None else 0.0
                    
                    # Filtramos por el confidence_threshold del usuario para el retorno
                    if conf >= self.confidence_threshold:
                        xyxy = box.xyxy[0].tolist() if box.xyxy is not None else [0, 0, 0, 0]
                        detections.append(
                            Detection(object=label, confidence=conf, bbox=[float(v) for v in xyxy])
                        )
            
            # Fallback compatible con modelos puramente de segmentación semántica
            elif hasattr(result, 'semantic_mask') and result.semantic_mask is not None:
                sem_data = result.semantic_mask.data.cpu().numpy()
                h_orig, w_orig = result.orig_shape if hasattr(result, "orig_shape") else sem_data.shape[:2]
                if sem_data.shape[:2] != (h_orig, w_orig):
                    sem_data = cv2.resize(sem_data, (w_orig, h_orig), interpolation=cv2.INTER_NEAREST)
                
                unique_classes = np.unique(sem_data)
                for class_id in unique_classes:
                    class_name = names.get(class_id, f"Class {class_id}")
                    class_lower = class_name.lower()
                    if class_lower in IGNORE_CLASSES:
                        continue
                    
                    class_mask = (sem_data == class_id).astype(np.uint8) * 255
                    contours, _ = cv2.findContours(class_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for contour in contours:
                        if cv2.contourArea(contour) < 150:
                            continue
                        x_b, y_b, w_b, h_b = cv2.boundingRect(contour)
                        detections.append(
                            Detection(
                                object=class_name,
                                confidence=1.0,  # Sin confianza por caja, asignamos 1.0
                                bbox=[float(x_b), float(y_b), float(x_b + w_b), float(y_b + h_b)]
                            )
                        )

        # 2. Análisis temporal de colisiones por tasa de crecimiento (looming)
        has_collision_danger = False
        current_class_roi_occupancy = {}
        dangerous_classes = set()

        for result in results:
            h, w = result.orig_shape if hasattr(result, "orig_shape") else (144, 256)
            
            # ROI Central (zona crítica): 40% central de la pantalla
            dz_x1 = int(w * 0.3)
            dz_x2 = int(w * 0.7)
            dz_y1 = int(h * 0.3)
            dz_y2 = int(h * 0.7)
            roi_total_pixels = (dz_x2 - dz_x1) * (dz_y2 - dz_y1)

            names = getattr(result, "names", {}) or {}

            # Caso A: Segmentación de Instancias (e.g. yolov8n-seg.pt)
            if hasattr(result, 'masks') and result.masks is not None:
                classes_arr = result.boxes.cls.cpu().numpy() if (result.boxes is not None and result.boxes.cls is not None) else []
                
                class_agg_masks = {}
                for i, mask_obj in enumerate(result.masks.xy):
                    class_id = int(classes_arr[i])
                    class_name = names.get(class_id, str(class_id))
                    class_lower = class_name.lower()
                    if class_lower in IGNORE_CLASSES:
                        continue

                    binary_mask = np.zeros((h, w), dtype=np.uint8)
                    pts = np.array(mask_obj, dtype=np.int32)
                    cv2.fillPoly(binary_mask, [pts], 255)

                    if class_lower not in class_agg_masks:
                        class_agg_masks[class_lower] = np.zeros((h, w), dtype=np.uint8)
                    class_agg_masks[class_lower] = cv2.bitwise_or(
                        class_agg_masks[class_lower], binary_mask)

                # Detección por tasa de crecimiento en máscaras agregadas
                for class_lower, agg_mask in class_agg_masks.items():
                    roi_slice = agg_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                    roi_area = int(np.sum(roi_slice == 255))
                    occ_pct = (roi_area / roi_total_pixels) * 100
                    current_class_roi_occupancy[class_lower] = occ_pct

                    if class_lower not in self.prev_class_roi_occupancy:
                        self.ema_growth_rates.pop(class_lower, None)
                        continue

                    delta = occ_pct - self.prev_class_roi_occupancy.get(class_lower, 0.0)
                    prev_ema = self.ema_growth_rates.get(class_lower, 0.0)
                    smoothed = EMA_ALPHA * delta + (1 - EMA_ALPHA) * prev_ema
                    self.ema_growth_rates[class_lower] = smoothed

                    cfg = CLASS_CONFIGS.get(class_lower, DEFAULT_CLASS_CONFIG)
                    if (smoothed >= cfg.get("min_growth_rate", 1.0)
                            and occ_pct >= cfg.get("min_floor_pct", 0.5)):
                        dangerous_classes.add(class_lower)
                        has_collision_danger = True

            # Caso B: Segmentación Semántica (e.g. yolo26n-sem.pt)
            elif hasattr(result, 'semantic_mask') and result.semantic_mask is not None:
                sem_data = result.semantic_mask.data.cpu().numpy()
                if sem_data.shape[:2] != (h, w):
                    sem_data = cv2.resize(sem_data, (w, h), interpolation=cv2.INTER_NEAREST)

                unique_classes = np.unique(sem_data)
                for class_id in unique_classes:
                    class_name = names.get(class_id, f"Class {class_id}")
                    class_lower = class_name.lower()
                    if class_lower in IGNORE_CLASSES:
                        continue

                    class_mask = (sem_data == class_id).astype(np.uint8) * 255
                    roi_slice = class_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                    roi_area = int(np.sum(roi_slice == 255))
                    occ_pct = (roi_area / roi_total_pixels) * 100
                    current_class_roi_occupancy[class_lower] = occ_pct

                    if class_lower not in self.prev_class_roi_occupancy:
                        self.ema_growth_rates.pop(class_lower, None)
                        continue

                    delta = occ_pct - self.prev_class_roi_occupancy.get(class_lower, 0.0)
                    prev_ema = self.ema_growth_rates.get(class_lower, 0.0)
                    smoothed = EMA_ALPHA * delta + (1 - EMA_ALPHA) * prev_ema
                    self.ema_growth_rates[class_lower] = smoothed

                    cfg = CLASS_CONFIGS.get(class_lower, DEFAULT_CLASS_CONFIG)
                    if (smoothed >= cfg.get("min_growth_rate", 1.0)
                            and occ_pct >= cfg.get("min_floor_pct", 0.5)):
                        dangerous_classes.add(class_lower)
                        has_collision_danger = True

            # Caso C: Detección 2D tradicional (Cajas delimitadoras / Bounding boxes)
            elif result.boxes is not None and len(result.boxes) > 0:
                class_agg_masks = {}
                for box in result.boxes:
                    cls_id = int(box.cls.item()) if box.cls is not None else -1
                    class_name = names.get(cls_id, str(cls_id))
                    class_lower = class_name.lower()
                    if class_lower in IGNORE_CLASSES:
                        continue
                    xyxy = box.xyxy[0].tolist() if box.xyxy is not None else [0, 0, 0, 0]
                    x1_b, y1_b, x2_b, y2_b = map(int, xyxy)
                    
                    binary_mask = np.zeros((h, w), dtype=np.uint8)
                    cv2.rectangle(binary_mask, (x1_b, y1_b), (x2_b, y2_b), 255, -1)
                    
                    if class_lower not in class_agg_masks:
                        class_agg_masks[class_lower] = np.zeros((h, w), dtype=np.uint8)
                    class_agg_masks[class_lower] = cv2.bitwise_or(
                        class_agg_masks[class_lower], binary_mask)

                # Detección por tasa de crecimiento en pseudo-máscaras de cajas
                for class_lower, agg_mask in class_agg_masks.items():
                    roi_slice = agg_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                    roi_area = int(np.sum(roi_slice == 255))
                    occ_pct = (roi_area / roi_total_pixels) * 100
                    current_class_roi_occupancy[class_lower] = occ_pct

                    if class_lower not in self.prev_class_roi_occupancy:
                        self.ema_growth_rates.pop(class_lower, None)
                        continue

                    delta = occ_pct - self.prev_class_roi_occupancy.get(class_lower, 0.0)
                    prev_ema = self.ema_growth_rates.get(class_lower, 0.0)
                    smoothed = EMA_ALPHA * delta + (1 - EMA_ALPHA) * prev_ema
                    self.ema_growth_rates[class_lower] = smoothed

                    cfg = CLASS_CONFIGS.get(class_lower, DEFAULT_CLASS_CONFIG)
                    if (smoothed >= cfg.get("min_growth_rate", 1.0)
                            and occ_pct >= cfg.get("min_floor_pct", 0.5)):
                        dangerous_classes.add(class_lower)
                        has_collision_danger = True

        # Actualizar estado anterior e instancia
        self.prev_class_roi_occupancy = current_class_roi_occupancy.copy()
        self.last_collision_result = CollisionResult(
            has_collision_danger=has_collision_danger,
            dangerous_classes=list(dangerous_classes),
            growth_rates={cls: float(self.ema_growth_rates.get(cls, 0.0)) for cls in dangerous_classes},
            occupancies={cls: float(current_class_roi_occupancy.get(cls, 0.0)) for cls in current_class_roi_occupancy}
        )

        return detections
