#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno del archivo .env
load_dotenv()

# Asegurar que el directorio del script esté en el PYTHONPATH
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

from src.hardware.airsim_client import AirSimClient
from PIL import Image

def main():
    # Ruta de destino predeterminada o la provista por argumento
    input_path = sys.argv[1] if len(sys.argv) > 1 else "imagen.jpg"
    
    # Insertar el timestamp en el nombre del archivo
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    dir_name, file_name = os.path.split(input_path)
    base_name, ext = os.path.splitext(file_name)
    if not base_name:
        base_name = "imagen"
    if not ext:
        ext = ".jpg"
        
    target_path = os.path.join(dir_name, f"{base_name}_{timestamp}{ext}")
    
    print("Inicializando AirSimClient...")
    c = AirSimClient()
    
    print(f"Intentando conectar a AirSim en {c.ip}:{c.port}...")
    print(f"  - Vehículo: {c.vehicle_name}")
    print(f"  - Cámara: {c.camera_name}")
    print(f"  - Resolución objetivo: {c.frame_width}x{c.frame_height}")
    
    connected = c.connect()
    if not connected:
        print("\n[!] ADVERTENCIA: No se pudo conectar al simulador AirSim.")
        print("    Se generará un fotograma simulado/sintético con fines de prueba.")
    else:
        print("\n[+] Conexión con AirSim establecida de forma exitosa.")

    print("\nCapturando fotograma...")
    img, telemetry = c.capture()
    
    if img is None:
        print("[-] ERROR: La captura devolvió None.")
        sys.exit(1)
        
    print(f"[+] Fotograma capturado con dimensiones (H, W, C): {img.shape}")
    print(f"[+] Telemetría recibida: {telemetry}")
    
    # Intentar guardar y mostrar el fotograma
    try:
        pil_img = Image.fromarray(img)
        # Asegurar que el directorio de salida exista
        output_dir = os.path.dirname(target_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        pil_img.save(target_path)
        print(f"\n[+] Imagen guardada en: {os.path.abspath(target_path)}")
        
        print("[+] Abriendo la imagen usando el visor predeterminado del sistema para validación visual...")
        pil_img.show()
    except Exception as e:
        print(f"[-] ERROR al guardar o mostrar la imagen: {e}")
        sys.exit(1)

    # Desconexión limpia del cliente de AirSim
    if connected:
        try:
            c.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    main()
