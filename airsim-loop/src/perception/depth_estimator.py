# V4-VLM-REFINEMENT: Estimación monocular de profundidad (Depth Anything V2 Metric).
#
# Arquitectura: mismo patrón productor/consumidor que DeliberationService.
# request() encola el frame RGB; poll() devuelve el último resultado sin
# bloquear el lazo de control (200 ms/ciclo a 5 Hz).
#
# Activación condicional (ver graph.py/perception_node): solo se dispara cuando
# el flujo óptico reporta corredor libre (bf < umbral) y el drone comanda
# movimiento frontal. Si el flujo óptico ya detectó un obstáculo, maneja la
# evasión sin necesidad de profundidad.
#
# Diferencia con sensor LiDAR/depth de AirSim: la entrada es solo RGB — el
# mismo frame que usa el flujo óptico. La profundidad es INFERIDA por un modelo
# aprendido, como lo haría un drone real con cámara monocular y cómputo embarcado.
# La API de profundidad de AirSim (imagen tipo planar/depth) NO se invoca.
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DEPTH_MODEL_ID = os.getenv(
    "DEPTH_MODEL_ID",
    "depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf",
)
# Sector de la imagen que representa el camino frontal del drone.
# Ignorar el 15 % superior (cielo) y el 15 % inferior (suelo a baja altura).
# Usar el 60 % central del ancho (excluir bordes laterales menos relevantes).
DEPTH_SECTOR_TOP    = float(os.getenv("DEPTH_SECTOR_TOP",    "0.15"))
DEPTH_SECTOR_BOTTOM = float(os.getenv("DEPTH_SECTOR_BOTTOM", "0.85"))
DEPTH_SECTOR_LEFT   = float(os.getenv("DEPTH_SECTOR_LEFT",   "0.20"))
DEPTH_SECTOR_RIGHT  = float(os.getenv("DEPTH_SECTOR_RIGHT",  "0.80"))
# Percentil robusto: 5 % es más resistente que el mínimo puro a píxeles ruidosos,
# pero aún captura obstáculos reales que cubren una fracción pequeña del sector.
DEPTH_PERCENTILE    = int(os.getenv("DEPTH_PERCENTILE", "5"))
# E2 (Zona 2): clasificación de textura de profundidad para inferir tipo de obstáculo.
# CV (std/mean) alto → profundidad irregular → follaje con huecos.
# far_fraction alto → muchos píxeles lejanos mezclados con los cercanos → misma firma.
# Umbral CV calibrado en renders UE5: pared ~0.10–0.25, árbol ~0.55–1.5.
_DEPTH_CV_THRESHOLD          = float(os.getenv("DEPTH_CV_THRESHOLD",          "0.55"))
_DEPTH_FAR_FRACTION_THRESHOLD = float(os.getenv("DEPTH_FAR_FRACTION_THRESHOLD", "0.30"))
# Razón near/far: píxel "lejano" = más de N× la profundidad mínima del sector.
_DEPTH_FAR_RATIO             = float(os.getenv("DEPTH_FAR_RATIO",             "3.0"))


class DepthEstimator:
    """Servicio de estimación de profundidad monocular en hilo background.

    Usa Depth Anything V2 Metric (ViT-S Outdoor) vía HuggingFace transformers.
    El modelo se carga una sola vez en el hilo worker al iniciarse. Las llamadas
    a request() / poll() son seguras desde el hilo del lazo de control.
    """

    def __init__(self) -> None:
        # Cola maxsize=1: un request nuevo descarta el pendiente anterior.
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._result: Optional[Tuple[float, str, float]] = None  # (min_depth_m, obstacle_type, submitted_at)
        self._ready = threading.Event()  # señaliza que el modelo está cargado
        self._thread = threading.Thread(target=self._worker, name="DepthEstimator", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def request(self, rgb_ndarray: np.ndarray) -> None:
        """Encola un frame RGB para inferencia. Si ya hay uno pendiente, lo reemplaza."""
        if rgb_ndarray is None:
            return
        payload = (rgb_ndarray.copy(), time.time())
        # Vaciar la cola antes de insertar (drop del request anterior).
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            pass

    def poll(self) -> Tuple[Optional[float], Optional[str], float]:
        """Devuelve (min_depth_m, obstacle_type, age_ms). Nones si aún no hay resultado."""
        with self._lock:
            if self._result is None:
                return None, None, 0.0
            min_depth, obstacle_type, submitted_at = self._result
            age_ms = (time.time() - submitted_at) * 1000.0
            return min_depth, obstacle_type, age_ms

    def is_ready(self) -> bool:
        """True cuando el modelo ya terminó de cargarse."""
        return self._ready.is_set()

    def stop(self) -> None:
        """Señaliza al worker que termine limpiamente."""
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=5.0)

    # ------------------------------------------------------------------
    # Worker interno
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        try:
            pipe = self._load_model()
        except Exception as exc:
            logger.error("DepthEstimator: error cargando modelo — %s", exc)
            self._ready.set()  # señalizar igualmente para no bloquear el lazo
            return

        self._ready.set()
        logger.info("DepthEstimator: modelo listo (%s)", DEPTH_MODEL_ID)

        while True:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:  # señal de parada
                break

            rgb_ndarray, submitted_at = item
            try:
                min_depth, obstacle_type = self._infer(pipe, rgb_ndarray)
                with self._lock:
                    self._result = (min_depth, obstacle_type, submitted_at)
            except Exception as exc:
                logger.warning("DepthEstimator: error en inferencia — %s", exc)

    def _load_model(self):
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        device = "cuda" if _cuda_available() else "cpu"
        logger.info("DepthEstimator: cargando %s en %s…", DEPTH_MODEL_ID, device)
        processor = AutoImageProcessor.from_pretrained(DEPTH_MODEL_ID)
        model = AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL_ID)
        model = model.to(device).eval()
        return (processor, model, device)

    def _infer(self, pipe, rgb_ndarray: np.ndarray) -> Tuple[float, str]:
        import torch
        from PIL import Image

        processor, model, device = pipe
        img = Image.fromarray(rgb_ndarray)
        inputs = processor(images=img, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)
            predicted_depth = outputs.predicted_depth  # (1, H, W), metros

        depth_np = predicted_depth.squeeze().cpu().numpy()
        min_depth = _min_forward_depth(depth_np)
        obstacle_type = _classify_depth_texture(depth_np)
        return min_depth, obstacle_type


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _classify_depth_texture(depth_map: np.ndarray) -> str:
    """Infiere el tipo de obstáculo frontal a partir de la textura del mapa de profundidad.

    Métricas sobre el sector frontal (mismo recorte que _min_forward_depth):
      - CV (std/mean): uniformidad de la profundidad. Pared → bajo; follaje → alto.
      - far_fraction: fracción de píxeles más de N× más lejanos que el percentil-5.
        Follaje → alto (huecos entre ramas que ven el fondo); pared → bajo.

    Retorna "follaje" o "superficie plana". "desconocido" si no hay suficientes datos.
    """
    h, w = depth_map.shape
    y0 = int(h * DEPTH_SECTOR_TOP)
    y1 = int(h * DEPTH_SECTOR_BOTTOM)
    x0 = int(w * DEPTH_SECTOR_LEFT)
    x1 = int(w * DEPTH_SECTOR_RIGHT)
    sector = depth_map[y0:y1, x0:x1]
    valid = sector[sector > 0.1]
    if len(valid) < 10:
        return "desconocido"
    mean_d = float(np.mean(valid))
    std_d = float(np.std(valid))
    cv = std_d / mean_d if mean_d > 0.0 else 0.0
    near = float(np.percentile(valid, DEPTH_PERCENTILE))
    far_fraction = float(np.mean(valid > near * _DEPTH_FAR_RATIO)) if near > 0.5 else 0.0
    if cv > _DEPTH_CV_THRESHOLD or far_fraction > _DEPTH_FAR_FRACTION_THRESHOLD:
        return "follaje"
    return "superficie plana"


def _min_forward_depth(depth_map: np.ndarray) -> float:
    """Percentil robusto del sector frontal del mapa de profundidad."""
    h, w = depth_map.shape
    y0 = int(h * DEPTH_SECTOR_TOP)
    y1 = int(h * DEPTH_SECTOR_BOTTOM)
    x0 = int(w * DEPTH_SECTOR_LEFT)
    x1 = int(w * DEPTH_SECTOR_RIGHT)
    sector = depth_map[y0:y1, x0:x1]
    valid = sector[sector > 0.1]
    if len(valid) == 0:
        return float("inf")
    return float(np.percentile(valid, DEPTH_PERCENTILE))
