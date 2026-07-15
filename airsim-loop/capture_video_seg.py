#!/usr/bin/env python3
"""Real-time video capture from AirSim with YOLOv8 inference.

This script continuously captures frames from the AirSim simulator, runs the
YOLOv8 segmentation model on each frame, draws the resulting masks onto the
frame, displays the annotated video stream, and optionally saves the output to
a video file.

Usage:
    python capture_video.py [model_path] [output_video_path]

    model_path          Path to a YOLOv8 model (e.g., "yolov8n-seg.pt").
                        If omitted, the default "yolov8n-seg.pt" will be used.
    output_video_path   Path to an output video file (e.g., "output.mp4").
                        If omitted, the video will not be saved.
"""

import os
import sys
import cv2
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Ensure the script directory is on the PYTHONPATH
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# Local imports – AirSim client wrapper
from src.hardware.airsim_client import AirSimClient

# YOLOv8 – ultralytics package
try:
    # pyrefly: ignore [missing-import]
    from ultralytics import YOLO
except ImportError:
    raise ImportError(
        "The 'ultralytics' package is required. Install it with 'pip install ultralytics'."
    )


def init_yolo(model_path: str = None) -> "YOLO":
    """Initialise the YOLOv8 model.

    Args:
        model_path: Optional path to a custom YOLOv8 model. If ``None`` the
            default pretrained "yolov8n-seg.pt" (nano‑segment) is loaded.
    """
    if model_path and os.path.isfile(model_path):
        print(f"[+] Loading YOLOv8 model from: {model_path}")
        return YOLO(model_path)
    else:
        # default_model = "weights/yolov8n-seg.pt"
        default_model = "weights/yolo26n-sem.pt" # Low latency semantic segmentation model, not a detect one
        print(f"[+] Loading default YOLO segmentation model: {default_model}")
        return YOLO(default_model)


def init_video_writer(frame_width: int, frame_height: int, output_path: str):
    """Create a ``cv2.VideoWriter`` instance.

    The codec used is ``mp4v`` which works with most MP4 players.
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    fps = 60  # Target frames‑per‑second; adjust if needed
    writer = cv2.VideoWriter(output_path, fourcc, fps, (frame_width, frame_height))
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open video writer for {output_path}")
    print(f"[+] Video writer initialized: {output_path} ({frame_width}x{frame_height}@{fps}fps)")
    return writer

# ---------------------------------------------------------------------------
# Collision detection configuration — growth-rate (looming) approach
# ---------------------------------------------------------------------------
# Classes to completely ignore (navigable surfaces, background)
IGNORE_CLASSES = frozenset({
    "sky", "road", "sidewalk", "terrain",
    "background", "bg", "void", "unlabeled", "background-unlabeled",
})

# Per-class growth-rate collision thresholds
#   min_growth_rate : minimum EMA-smoothed ROI occupancy growth (%/frame) to trigger
#   min_floor_pct   : minimum current ROI occupancy (%) to even consider (noise filter)
CLASS_CONFIGS = {
    # Small/narrow critical objects — low floor, sensitive growth rate
    "traffic light": {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "traffic sign":  {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "stop sign":     {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "pole":          {"min_growth_rate": 0.8, "min_floor_pct": 0.3},
    "fire hydrant":  {"min_growth_rate": 0.8, "min_floor_pct": 0.3},

    # People and riders
    "person":     {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "rider":      {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "bicycle":    {"min_growth_rate": 0.8, "min_floor_pct": 0.5},
    "motorcycle": {"min_growth_rate": 0.8, "min_floor_pct": 0.5},

    # Large static structures — higher thresholds (approach must be more aggressive)
    "building":   {"min_growth_rate": 1.5, "min_floor_pct": 2.0},
    "wall":       {"min_growth_rate": 1.5, "min_floor_pct": 2.0},
    "fence":      {"min_growth_rate": 1.2, "min_floor_pct": 1.5},
    "vegetation": {"min_growth_rate": 1.5, "min_floor_pct": 2.0},
    "tree":       {"min_growth_rate": 1.5, "min_floor_pct": 2.0},

    # Vehicles
    "car":   {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
    "truck": {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
    "bus":   {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
    "train": {"min_growth_rate": 1.0, "min_floor_pct": 1.0},
}

DEFAULT_CLASS_CONFIG = {"min_growth_rate": 1.0, "min_floor_pct": 0.5}

# EMA smoothing factor for growth rate (0 → full smoothing, 1 → no smoothing)
EMA_ALPHA = 0.4


def main():
    # Parse optional arguments
    model_path = sys.argv[1] if len(sys.argv) > 1 else None
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    # Initialise YOLO model
    yolo_model = init_yolo(model_path)

    # Initialise AirSim client
    client = AirSimClient()
    print("[+] Connecting to AirSim...")
    if not client.connect():
        print("[!] Could not connect to AirSim – exiting.")
        sys.exit(1)

    # Prepare optional video writer
    video_writer = None
    if output_path:
        video_writer = "pending"

    # Temporal state for growth-rate collision detection
    prev_class_roi_occupancy = {}   # class_lower -> ROI occupancy % from previous frame
    ema_growth_rates = {}           # class_lower -> EMA-smoothed growth rate (%/frame)

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
                conf=0.1,
                iou=0.9,
                max_det=400
            )

            annotated = frame_bgr.copy()
            h, w = frame_bgr.shape[:2]

            # Central ROI (Danger Zone) — center 40% of the screen
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

            # ── Case 1: Instance Segmentation (e.g. yolov8n-seg.pt) ──────
            if hasattr(results[0], 'masks') and results[0].masks is not None:
                classes_arr = results[0].boxes.cls.cpu().numpy()
                names = results[0].names

                # Phase A — aggregate per-class masks and compute ROI occupancy
                class_agg_masks = {}    # class_lower -> combined binary mask
                class_instances = {}    # class_lower -> [(binary_mask, class_name)]

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

                # Phase B — growth-rate collision detection per class
                for class_lower, agg_mask in class_agg_masks.items():
                    roi_slice = agg_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                    roi_area = int(np.sum(roi_slice == 255))
                    occ_pct = (roi_area / roi_total_pixels) * 100
                    current_class_roi_occupancy[class_lower] = occ_pct

                    # First time seeing this class — establish baseline, skip trigger
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

                # Phase C — render masks and danger labels
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

            # ── Case 2: Semantic Segmentation (e.g. yolo26n-sem.pt) ──────
            elif hasattr(results[0], 'semantic_mask') and results[0].semantic_mask is not None:
                sem_data = results[0].semantic_mask.data.cpu().numpy()
                if sem_data.shape[:2] != (h, w):
                    sem_data = cv2.resize(sem_data, (w, h), interpolation=cv2.INTER_NEAREST)

                names = results[0].names
                unique_classes = np.unique(sem_data)

                # Phase A — per-class ROI occupancy + growth-rate detection
                class_render_data = {}   # class_lower -> (class_name, contours, class_mask)

                for class_id in unique_classes:
                    class_name = names.get(class_id, f"Class {class_id}")
                    class_lower = class_name.lower()
                    if class_lower in IGNORE_CLASSES:
                        continue

                    class_mask = (sem_data == class_id).astype(np.uint8) * 255

                    # Aggregate ROI occupancy for the entire class
                    roi_slice = class_mask[dz_y1:dz_y2, dz_x1:dz_x2]
                    roi_area = int(np.sum(roi_slice == 255))
                    occ_pct = (roi_area / roi_total_pixels) * 100
                    current_class_roi_occupancy[class_lower] = occ_pct

                    contours, _ = cv2.findContours(
                        class_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    class_render_data[class_lower] = (class_name, contours, class_mask)

                    # First time seeing this class — establish baseline, skip trigger
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

                # Phase B — render contours and danger labels
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

            # Update temporal state for the next frame
            prev_class_roi_occupancy = current_class_roi_occupancy.copy()

            # Put global warning banner and command drone stop if danger detected
            if has_collision_danger:
                cv2.rectangle(annotated, (0, 0), (w, 35), (0, 0, 255), -1)
                cv2.putText(annotated, "PROBABLE COLLISION",
                            (int(w * 0.15), 24), cv2.FONT_HERSHEY_DUPLEX, 0.6,
                            (255, 255, 255), 1, cv2.LINE_AA)
                client.execute_velocity(0.0, 0.0, 0.0)

            # Initialise the video writer now that we know the size
            if video_writer == "pending":
                h, w = annotated.shape[:2]
                video_writer = init_video_writer(w, h, output_path)

            # Show the annotated frame
            cv2.imshow("AirSim + YOLOv8", annotated)
            if isinstance(video_writer, cv2.VideoWriter):
                video_writer.write(annotated)

            # Exit on 'q' key press
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[+] 'q' pressed – exiting loop.")
                break
    finally:
        # Clean‑up resources
        if isinstance(video_writer, cv2.VideoWriter):
            video_writer.release()
            print("[+] Video file saved and writer released.")
        cv2.destroyAllWindows()
        client.disconnect()
        print("[+] Disconnected from AirSim.")


if __name__ == "__main__":
    main()
