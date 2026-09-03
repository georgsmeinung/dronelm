#!/usr/bin/env python3
"""Captura de video en tiempo real desde AirSim con inferencia YOLOv8.

Este script captura frames de forma continua desde el simulador AirSim, corre
el modelo de segmentación YOLOv8 sobre cada frame, dibuja las máscaras
resultantes sobre el frame, muestra el video anotado y opcionalmente guarda
la salida en un archivo de video.

Uso:
    python capture_video.py [model_path] [output_video_path]

    model_path        Ruta a un modelo YOLOv8 (por ej., "yolov8n-seg.pt").
                       Si se omite, se usa el default "yolov8n-seg.pt".
    output_video_path Ruta a un archivo de video de salida (por ej., "output.mp4").
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
            ``None`` se carga el default preentrenado "yolov8n-seg.pt"
            (nano-segment).
    """
    if model_path and os.path.isfile(model_path):
        print(f"[+] Loading YOLOv8 model from: {model_path}")
        return YOLO(model_path)
    else:
        default_model = "yolov8n-seg.pt"
        print(f"[+] Loading default YOLOv8 model: {default_model}")
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


def main():
    # Parsea los argumentos opcionales
    model_path = sys.argv[1] if len(sys.argv) > 1 else None
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    # Inicializa el modelo YOLO
    yolo_model = init_yolo(model_path)

    # Inicializa el cliente de AirSim
    client = AirSimClient()
    print("[+] Connecting to AirSim...")
    if not client.connect():
        print("[!] Could not connect to AirSim – exiting.")
        sys.exit(1)

    # Prepara el video writer opcional
    video_writer = None
    if output_path:
        # Inicializamos el writer recién después del primer frame, para conocer la resolución
        video_writer = "pending"

    print("[+] Starting real‑time capture. Press 'q' to quit.")
    try:
        while True:
            img, telemetry = client.capture()
            if img is None:
                print("[!] Received empty frame – skipping.")
                continue

            # ``img`` es un array de NumPy en orden RGB (como usa PIL). Se convierte a BGR para OpenCV.
            frame_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            # Corre la inferencia de YOLO – results es una lista con un único elemento para una sola imagen
            results = yolo_model(frame_bgr)
            # ``plot`` devuelve la imagen anotada como array de NumPy (BGR)
            annotated = results[0].plot()

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
