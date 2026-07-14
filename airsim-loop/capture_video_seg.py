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
        # We'll initialise the writer after the first frame to know the resolution
        video_writer = "pending"

    print("[+] Starting real‑time capture. Press 'q' to quit.")
    try:
        while True:
            img, depth, telemetry = client.capture(return_depth=True)
            if img is None:
                print("[!] Received empty frame – skipping.")
                continue

            # ``img`` is a NumPy array in RGB order (as used by PIL). Convert to BGR for OpenCV.
            frame_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            # Run YOLO inference – results is a list with a single element for a single image
            results = yolo_model(
                frame_bgr,
                conf=0.1,      
                iou=0.9,      
                # imgsz=640,   
                max_det=400
                # retina_masks=True
            )
            # ``plot`` returns the annotated image as a NumPy array (BGR)
            annotated = results[0].plot(
                boxes=True,    # No box rectangles
                labels=True,   # No text labels
                conf=True      # No confidence numbers
            )

            # Draw distance overlay for each segmented object
            if depth is not None:
                h, w = depth.shape[:2]
                
                # Case 1: Instance Segmentation Model (like yolov8n-seg.pt)
                if hasattr(results[0], 'masks') and results[0].masks is not None:
                    classes = results[0].boxes.cls.cpu().numpy()
                    names = results[0].names
                    
                    for i, mask_obj in enumerate(results[0].masks.xy):
                        class_id = int(classes[i])
                        class_name = names[class_id]
                        
                        # Create blank binary mask
                        binary_mask = np.zeros((h, w), dtype=np.uint8)
                        pts = np.array(mask_obj, dtype=np.int32)
                        cv2.fillPoly(binary_mask, [pts], 255)
                        
                        # Extract depth pixels belonging ONLY to this segment
                        obstacle_depths = depth[binary_mask == 255]
                        
                        # Filter out invalid depth readings (0 represents no depth data)
                        valid_depths = obstacle_depths[obstacle_depths > 0]
                        
                        if len(valid_depths) > 0:
                            # Use median to avoid outlier noise
                            median_distance = np.median(valid_depths)
                            distance_meters = median_distance
                            
                            # Get the centroid of the mask for visual overlay positioning
                            M = cv2.moments(binary_mask)
                            if M["m00"] != 0:
                                cx = int(M["m10"] / M["m00"])
                                cy = int(M["m01"] / M["m00"])
                                
                                # Draw text overlay on the annotated frame
                                text = f"{class_name}: {distance_meters:.2f}m"
                                cv2.putText(annotated, text, (cx - 30, cy + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
                                cv2.putText(annotated, text, (cx - 30, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

                # Case 2: Semantic Segmentation Model (like yolo26n-sem.pt)
                elif hasattr(results[0], 'semantic_mask') and results[0].semantic_mask is not None:
                    sem_data = results[0].semantic_mask.data.cpu().numpy()
                    if sem_data.shape[:2] != (h, w):
                        sem_data = cv2.resize(sem_data, (w, h), interpolation=cv2.INTER_NEAREST)
                        
                    names = results[0].names
                    unique_classes = np.unique(sem_data)
                    
                    for class_id in unique_classes:
                        class_name = names.get(class_id, f"Class {class_id}")
                        # Skip background classes to avoid text clutter
                        if class_name.lower() in ("background", "bg", "void", "unlabeled", "background-unlabeled"):
                            continue
                            
                        # Create binary mask for this class
                        class_mask = (sem_data == class_id).astype(np.uint8) * 255
                        
                        # Find connected components (separate blobs of the same class)
                        contours, _ = cv2.findContours(class_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        
                        for contour in contours:
                            if cv2.contourArea(contour) < 150:
                                continue
                                
                            contour_mask = np.zeros((h, w), dtype=np.uint8)
                            cv2.drawContours(contour_mask, [contour], -1, 255, -1)
                            
                            obstacle_depths = depth[contour_mask == 255]
                            valid_depths = obstacle_depths[obstacle_depths > 0]
                            
                            if len(valid_depths) > 0:
                                median_distance = np.median(valid_depths)
                                distance_meters = median_distance
                                
                                M = cv2.moments(contour)
                                if M["m00"] != 0:
                                    cx = int(M["m10"] / M["m00"])
                                    cy = int(M["m01"] / M["m00"])
                                    
                                    text = f"{class_name}: {distance_meters:.2f}m"
                                    cv2.putText(annotated, text, (cx - 30, cy + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
                                    cv2.putText(annotated, text, (cx - 30, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

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
