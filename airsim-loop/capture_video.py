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
        default_model = "weights/yolo26n.pt"
        print(f"[+] Loading default YOLO26 model: {default_model}")
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
            img, telemetry = client.capture()
            if img is None:
                print("[!] Received empty frame – skipping.")
                continue

            # ``img`` is a NumPy array in RGB order (as used by PIL). Convert to BGR for OpenCV.
            frame_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            # Run YOLO inference – results is a list with a single element for a single image
            results = yolo_model(frame_bgr)
            # ``plot`` returns the annotated image as a NumPy array (BGR)
            annotated = results[0].plot()

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
