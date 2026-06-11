import cosysairsim as airsim
import time
import subprocess
import os
import sys
import re

def main():
    # Iniciar airsim_logger.py como un proceso separado
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logger_path = os.path.join(script_dir, "airsim_logger.py")
    path_file = os.path.join(script_dir, "calibration_path_20260610_drone2.txt")

    print(f"Starting logger: {logger_path}")
    # Uso de sys.executable para asegurar que se use el mismo entorno de python
    logger_proc = subprocess.Popen([sys.executable, logger_path], cwd=script_dir)

    # Le da al logger un momento para iniciar y conectarse
    time.sleep(2)

    # Conectarse a AirSim y preparar el dron para recibir comandos
    client = airsim.MultirotorClient()
    client.confirmConnection()
    client.enableApiControl(True)
    client.armDisarm(True)

    # Leer y ejecutar comandos desde calibration_path.txt
    if not os.path.exists(path_file):
        print(f"Error: {path_file} not found.")
        logger_proc.terminate()
        return

    print(f"Reading commands from {path_file}")
    with open(path_file, "r") as f:
        commands = f.readlines()

    for cmd in commands:
        cmd = cmd.strip()
        if not cmd or cmd.startswith("#"):
            continue

        print(f"Executing command: {cmd}")

        if cmd == "takeoff":
            client.takeoffAsync().join()
        
        elif cmd.startswith("move"):
            # Parse move(x,y,z,v)            
            match = re.match(r"move\(([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)\)", cmd)
            if match:
                x, y, z, v = map(float, match.groups())
                print(f"Moving to position: x={x}, y={y}, z={z} at velocity={v}")
                client.moveToPositionAsync(x, y, z, v).join()
                client.hoverAsync().join()
            else:
                print(f"Invalid move command format: {cmd}")

        elif cmd == "reset":
            print("Resetting simulation...")
            client.reset()
            # El Logger detectará el reset y se detendrá
            break
        
        else:
            print(f"Unknown command: {cmd}")

    print("Commander finished.")
    # En caso de que reset no fuera el último comando o no detuviera el logger
    time.sleep(1)
    if logger_proc.poll() is None:
        print("Stopping logger process...")
        logger_proc.terminate()

if __name__ == "__main__":
    main()
