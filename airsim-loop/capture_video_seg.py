#!/usr/bin/env python3
"""Captura de video en tiempo real desde AirSim con inferencia YOLOv8.

Este script captura frames de forma continua desde el simulador AirSim, corre
el modelo de segmentación YOLOv8 sobre cada frame, dibuja las máscaras
resultantes sobre el frame, muestra el video anotado y opcionalmente guarda
la salida en un archivo de video.

Uso:
    python capture_video.py [model_path] [output_video_path]

    model_path          Ruta a un modelo YOLOv8 (por ej., "yolov8n-seg.pt").
                        Si se omite, se usa el default "yolov8n-seg.pt".
    output_video_path   Ruta a un archivo de video de salida (por ej., "output.mp4").
                        Si se omite, el video no se guarda.
"""

import os
import sys
import cv2
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

# Carga las variables de entorno desde .env si existe
load_dotenv()

# Asegura que el directorio del script esté en el PYTHONPATH
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# Imports locales – wrapper del cliente de AirSim
from src.hardware.airsim_client import AirSimClient

# YOLOv8 – paquete ultralytics
try:
    # pyrefly: ignore [missing-import]
    from ultralytics import YOLO
except ImportError:
    raise ImportError(
        "The 'ultralytics' package is required. Install it with 'pip install ultralytics'."
    )


def init_yolo(model_path: str = None) -> "YOLO":
    """Inicializa el modelo YOLOv8.

    Args:
        model_path: Ruta opcional a un modelo YOLOv8 personalizado. Si es
            ``None`` se carga el default preentrenado "yolo26n-sem.pt".
    """
    if model_path and os.path.isfile(model_path):
        print(f"[+] Loading YOLOv8 model from: {model_path}")
        return YOLO(model_path)
    else:
        # Verifica si ya existe el engine de TensorRT optimizado, para evitar exportarlo en cada corrida
        default_engine = "weights/yolo26n-sem.engine"
        if os.path.isfile(default_engine):
            print(f"[+] Loading default TensorRT engine: {default_engine}")
            return YOLO(default_engine)

        default_model = "weights/yolo26n-sem.pt"
        print(f"[+] Loading default YOLO segmentation model: {default_model}")
        return YOLO(default_model)



def init_video_writer(frame_width: int, frame_height: int, output_path: str):
    """Crea una instancia de ``cv2.VideoWriter``.

    El códec utilizado es ``mp4v``, que funciona con la mayoría de los
    reproductores de MP4.
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    fps = 60  # FPS objetivo; ajustar si hace falta
    writer = cv2.VideoWriter(output_path, fourcc, fps, (frame_width, frame_height))
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open video writer for {output_path}")
    print(f"[+] Video writer initialized: {output_path} ({frame_width}x{frame_height}@{fps}fps)")
    return writer

# ---------------------------------------------------------------------------
# Configuración de detección de colisiones — enfoque de tasa de crecimiento (looming)
# ---------------------------------------------------------------------------
# Clases a ignorar por completo (superficies navegables, fondo)
IGNORE_CLASSES = frozenset({
    "sky", "road", "sidewalk", "terrain",
    "background", "bg", "void", "unlabeled", "background-unlabeled",
})

# Umbrales de colisión por tasa de crecimiento, por clase
#   min_growth_rate : crecimiento mínimo de ocupación del ROI, suavizado con EMA (%/frame), para disparar
#   min_floor_pct   : ocupación actual mínima del ROI (%) para siquiera considerarla (filtro de ruido)
CLASS_CONFIGS = {
    # Objetos críticos chicos/angostos — piso bajo, tasa de crecimiento sensible
    "traffic light": {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "traffic sign":  {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "stop sign":     {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "pole":          {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "fire hydrant":  {"min_growth_rate": 0.8, "min_floor_pct": 0.3},

    # Personas y ciclistas/motociclistas
    "person":     {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "rider":      {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "bicycle":    {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "motorcycle": {"min_growth_rate": 0.8, "min_floor_pct": 0.5},

    # Estructuras estáticas grandes — umbrales más altos (el acercamiento debe ser más agresivo)
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

# Factor de suavizado EMA para la tasa de crecimiento (0 → suavizado total, 1 → sin suavizado)
EMA_ALPHA = 0.4


def main():
    # Parsea los argumentos opcionales
    model_path = sys.argv[1] if len(sys.argv) > 1 else None
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    # Inicializa el modelo YOLO
    yolo_model = init_yolo(model_path)

    # Exporta a TensorRT solo si se cargó un modelo de PyTorch y todavía no existe el engine correspondiente
    model_name = getattr(yolo_model, "ckpt_path", "") or ""
    if isinstance(model_name, str) and model_name.endswith(".pt"):
        engine_path = model_name.replace(".pt", ".engine")
        if not os.path.isfile(engine_path):
            print(f"[+] Exporting model to TensorRT engine: {engine_path} (this may take a few minutes...)")
            yolo_model.export(format='engine', half=True, imgsz=640, device=0)

        # Reinicializa el modelo para usar el engine recién exportado
        if os.path.isfile(engine_path):
            print(f"[+] Loading optimized TensorRT engine: {engine_path}")
            yolo_model = YOLO(engine_path)


    # Inicializa el cliente de AirSim
    client = AirSimClient()
    print("[+] Connecting to AirSim...")
    if not client.connect():
        print("[!] Could not connect to AirSim – exiting.")
        sys.exit(1)

    # Prepara el video writer opcional
    video_writer = None
    if output_path:
        video_writer = "pending"

    # Estado temporal para la detección de colisiones por tasa de crecimiento
    prev_class_roi_occupancy = {}   # class_lower -> % de ocupación del ROI del frame anterior
    ema_growth_rates = {}           # class_lower -> tasa de crecimiento suavizada con EMA (%/frame)

    print("[+] Starting real‑time capture. Press 'q' to quit.")
    try:
        while True:
            # pyrefly: ignore [bad-unpacking]
            img, telemetry = client.capture(return_depth=False)
            if img is None:
                print("[!] Received empty frame – skipping.")
                continue

            frame_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            results = yolo_model(
                frame_bgr,
                device=0,
                imgsz=640,      # Redimensiona internamente al estándar de 640px
                conf=0.25,      # Filtra temprano las boxes de baja confianza (ruido)
                iou=0.45,       # Umbral estándar de NMS para suprimir duplicados
                max_det=100     # Limita la cantidad máxima de detecciones a procesar
            )

            annotated = frame_bgr.copy()
            h, w = frame_bgr.shape[:2]

            # ROI central (zona de peligro) — 40% central de la pantalla
            dz_x1 = int(w * 0.3)
            dz_x2 = int(w * 0.7)
            dz_y1 = int(h * 0.3)
            dz_y2 = int(h * 0.7)
            roi_total_pixels = (dz_x2 - dz_x1) * (dz_y2 - dz_y1)

            cv2.rectangle(annotated, (dz_x1, dz_y1), (dz_x2, dz_y2),
                          (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(annotated, "Central ROI", (dz_x1 + 5, dz_y1 + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)

            has_collision_danger = False
            current_class_roi_occupancy = {}
            dangerous_classes = set()

            # ── Caso 1: Segmentación de instancias (por ej. yolov8n-seg.pt) ──────
            if hasattr(results[0], 'masks') and results[0].masks is not None:
                classes_arr = results[0].boxes.cls.cpu().numpy()
                names = results[0].names

                # Fase A — agrega las máscaras por clase y calcula la ocupación del ROI
                class_agg_masks = {}    # class_lower -> máscara binaria combinada
                class_instances = {}    # class_lower -> [(máscara_binaria, nombre_clase)]

                for i, mask_obj in enumerate(results[0].masks.xy):
                    class_id = int(classes_arr[i])
                    class_name = names[class_id]
                    class_lower = class_name.lower()
                    if class_lower in IGNORE_CLASSES:
                        continue

                    binary_mask = np.zeros((h, w), dtype=np.uint8)
                    pts = np.array(mask_obj, dtype=np.int32)
                    cv2.fillPoly(binary_mask, [pts], 255)

                    if class_lower not in class_agg_masks:
                        class_agg_masks[class_lower] = np.zeros((h, w), dtype=np.uint8)
                        class_instances[class_lower] = []
                    class_agg_masks[class_lower] = cv2.bitwise_or(
                        class_agg_masks[class_lower], binary_mask)
                    class_instances[class_lower].append((binary_mask, class_name))

                # Fase B — detección de colisión por tasa de crecimiento, por clase
                for class_lower, agg_mask in class_agg_masks.items():
                    roi_slice = agg_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                    roi_area = int(np.sum(roi_slice == 255))
                    occ_pct = (roi_area / roi_total_pixels) * 100
                    current_class_roi_occupancy[class_lower] = occ_pct

                    # Primera vez que se ve esta clase — establece la línea base, no dispara
                    if class_lower not in prev_class_roi_occupancy:
                        ema_growth_rates.pop(class_lower, None)
                        continue

                    delta = occ_pct - prev_class_roi_occupancy.get(class_lower, 0.0)
                    prev_ema = ema_growth_rates.get(class_lower, 0.0)
                    smoothed = EMA_ALPHA * delta + (1 - EMA_ALPHA) * prev_ema
                    ema_growth_rates[class_lower] = smoothed

                    cfg = CLASS_CONFIGS.get(class_lower, DEFAULT_CLASS_CONFIG)
                    if (smoothed >= cfg.get("min_growth_rate", 1.0)
                            and occ_pct >= cfg.get("min_floor_pct", 0.5)):
                        dangerous_classes.add(class_lower)
                        has_collision_danger = True

                # Fase C — renderiza las máscaras y las etiquetas de peligro
                for class_lower, instances in class_instances.items():
                    is_danger = class_lower in dangerous_classes
                    color = (0, 0, 255) if is_danger else (0, 255, 0)

                    for binary_mask, _cname in instances:
                        mask_idx = (binary_mask == 255)
                        color_img = np.full_like(annotated, color)
                        blended = cv2.addWeighted(annotated, 0.6, color_img, 0.4, 0)
                        annotated[mask_idx] = blended[mask_idx]

                    if is_danger:
                        agg_roi = np.zeros((h, w), dtype=np.uint8)
                        agg_roi[dz_y1:dz_y2, dz_x1:dz_x2] = \
                            class_agg_masks[class_lower][dz_y1:dz_y2, dz_x1:dz_x2]
                        M = cv2.moments(agg_roi)
                        cx = int(M["m10"] / M["m00"]) if M["m00"] > 0 else (dz_x1 + dz_x2) // 2
                        cy = int(M["m01"] / M["m00"]) if M["m00"] > 0 else (dz_y1 + dz_y2) // 2
                        growth = ema_growth_rates.get(class_lower, 0.0)
                        label = instances[0][1]
                        text = f"Collision ({label}) +{growth:.1f}%/f"
                        cv2.putText(annotated, text, (cx - 80, cy + 1),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
                        cv2.putText(annotated, text, (cx - 80, cy),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)

            # ── Caso 2: Segmentación semántica (por ej. yolo26n-sem.pt) ──────
            elif hasattr(results[0], 'semantic_mask') and results[0].semantic_mask is not None:
                sem_data = results[0].semantic_mask.data.cpu().numpy()
                if sem_data.shape[:2] != (h, w):
                    sem_data = cv2.resize(sem_data, (w, h), interpolation=cv2.INTER_NEAREST)

                names = results[0].names
                unique_classes = np.unique(sem_data)

                # Fase A — ocupación del ROI por clase + detección por tasa de crecimiento
                class_render_data = {}   # class_lower -> (nombre_clase, contornos, máscara_clase)

                for class_id in unique_classes:
                    class_name = names.get(class_id, f"Class {class_id}")
                    class_lower = class_name.lower()
                    if class_lower in IGNORE_CLASSES:
                        continue

                    class_mask = (sem_data == class_id).astype(np.uint8) * 255

                    # Agrega la ocupación del ROI para la clase completa
                    roi_slice = class_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                    roi_area = int(np.sum(roi_slice == 255))
                    occ_pct = (roi_area / roi_total_pixels) * 100
                    current_class_roi_occupancy[class_lower] = occ_pct

                    contours, _ = cv2.findContours(
                        class_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    class_render_data[class_lower] = (class_name, contours, class_mask)

                    # Primera vez que se ve esta clase — establece la línea base, no dispara
                    if class_lower not in prev_class_roi_occupancy:
                        ema_growth_rates.pop(class_lower, None)
                        continue

                    delta = occ_pct - prev_class_roi_occupancy.get(class_lower, 0.0)
                    prev_ema = ema_growth_rates.get(class_lower, 0.0)
                    smoothed = EMA_ALPHA * delta + (1 - EMA_ALPHA) * prev_ema
                    ema_growth_rates[class_lower] = smoothed

                    cfg = CLASS_CONFIGS.get(class_lower, DEFAULT_CLASS_CONFIG)
                    if (smoothed >= cfg.get("min_growth_rate", 1.0)
                            and occ_pct >= cfg.get("min_floor_pct", 0.5)):
                        dangerous_classes.add(class_lower)
                        has_collision_danger = True

                # Fase B — renderiza los contornos y las etiquetas de peligro
                for class_lower, (class_name, contours, class_mask) in class_render_data.items():
                    is_danger = class_lower in dangerous_classes
                    color = (0, 0, 255) if is_danger else (0, 255, 0)

                    for contour in contours:
                        if cv2.contourArea(contour) < 150:
                            continue
                        contour_mask = np.zeros((h, w), dtype=np.uint8)
                        cv2.drawContours(contour_mask, [contour], -1, 255, -1)
                        mask_idx = (contour_mask == 255)
                        color_img = np.full_like(annotated, color)
                        blended = cv2.addWeighted(annotated, 0.6, color_img, 0.4, 0)
                        annotated[mask_idx] = blended[mask_idx]

                    if is_danger:
                        roi_mask = np.zeros((h, w), dtype=np.uint8)
                        roi_mask[dz_y1:dz_y2, dz_x1:dz_x2] = \
                            class_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                        M = cv2.moments(roi_mask)
                        cx = int(M["m10"] / M["m00"]) if M["m00"] > 0 else (dz_x1 + dz_x2) // 2
                        cy = int(M["m01"] / M["m00"]) if M["m00"] > 0 else (dz_y1 + dz_y2) // 2
                        growth = ema_growth_rates.get(class_lower, 0.0)
                        text = f"Collision ({class_name}) +{growth:.1f}%/f"
                        cv2.putText(annotated, text, (cx - 80, cy + 1),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
                        cv2.putText(annotated, text, (cx - 80, cy),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)

            # Actualiza el estado temporal para el próximo frame
            prev_class_roi_occupancy = current_class_roi_occupancy.copy()

            # Muestra el banner de advertencia global y ordena detener el drone si se detecta peligro
            if has_collision_danger:
                cv2.rectangle(annotated, (0, 0), (w, 35), (0, 0, 255), -1)
                cv2.putText(annotated, "PROBABLE COLLISION",
                            (int(w * 0.15), 24), cv2.FONT_HERSHEY_DUPLEX, 0.6,
                            (255, 255, 255), 1, cv2.LINE_AA)
                client.execute_velocity(0.0, 0.0, 0.0)

            # Inicializa el video writer ahora que ya conocemos el tamaño
            if video_writer == "pending":
                h, w = annotated.shape[:2]
                video_writer = init_video_writer(w, h, output_path)

            # Muestra el frame anotado
            cv2.imshow("AirSim + YOLOv8", annotated)
            if isinstance(video_writer, cv2.VideoWriter):
                video_writer.write(annotated)

            # Sale al presionar la tecla 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[+] 'q' pressed – exiting loop.")
                break
    finally:
        # Libera los recursos
        if isinstance(video_writer, cv2.VideoWriter):
            video_writer.release()
            print("[+] Video file saved and writer released.")
        cv2.destroyAllWindows()
        client.disconnect()
        print("[+] Disconnected from AirSim.")


if __name__ == "__main__":
    main()
