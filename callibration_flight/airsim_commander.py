import argparse
import cosysairsim as airsim
import os
import re
import subprocess
import sys
import time
from dotenv import load_dotenv

TIMEOUT = 1200  # 20 mins


def parse_arguments():
    parser = argparse.ArgumentParser(description="Run AirSim calibration commands.")
    parser.add_argument(
        "--path-file",
        required=True,
        help="Path to the file that contains the mission commands. Example: --path-file D:\\TesisMCD\\dronelm\\callibration_flight\\simulated_telemetry\\flights\\20260627\\calibration_path_20260627_drone2.txt",
    )
    parser.add_argument(
        "--trace-color",
        help="Hex color for the trace line, for example #ff0000 or ff0000.",
    )
    parser.add_argument(
        "--trace-width",
        type=float,
        default=5.0,
        help="Width of the trace line when trace color is enabled (default: 5).",
    )
    return parser.parse_args()


def hex_to_rgba(color_hex):
    color = color_hex.strip().lstrip("#")
    if len(color) != 6:
        raise ValueError(f"Invalid hex color '{color_hex}'. Expected format: #RRGGBB or RRGGBB")

    red = int(color[0:2], 16) / 255.0
    green = int(color[2:4], 16) / 255.0
    blue = int(color[4:6], 16) / 255.0
    return [red, green, blue, 1.0]


def set_trace_line(client, trace_color, trace_width):
    if not trace_color:
        return

    rgba = hex_to_rgba(trace_color)
    client.simSetTraceLine(rgba, trace_width)
    print(f"Trace line enabled with color {trace_color} and width {trace_width}")

def main():
    args = parse_arguments()

    # Iniciar airsim_logger.py como un proceso separado
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logger_path = os.path.join(script_dir, "airsim_logger.py")
    path_file = args.path_file

    print(f"Starting logger: {logger_path}")
    # Uso de sys.executable para asegurar que se use el mismo entorno de python
    logger_proc = subprocess.Popen([sys.executable, logger_path], cwd=script_dir)

    # Le da al logger un momento para iniciar y conectarse
    time.sleep(2)

    # Conectarse a AirSim y preparar el dron para recibir comandos
    load_dotenv()
    airsim_ip = os.getenv("AIRSIM_IP", "")
    if airsim_ip:
        client = airsim.MultirotorClient(ip=airsim_ip)
    else:
        client = airsim.MultirotorClient()
    client.confirmConnection()
    client.enableApiControl(True)
    client.armDisarm(True)
    set_trace_line(client, args.trace_color, args.trace_width)

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
        if not cmd:
            continue

        if cmd.startswith("#"):
            continue

        print(f"Executing command: {cmd}")

        if cmd.startswith("moveOnPath("):
            match = re.match(r"moveOnPath\((.*)\)", cmd)
            if match:
                args = ["moveOnPath"] + [arg.strip() for arg in match.group(1).split(",") if arg.strip()]
                print("MoveOnPath received")
                if len(args) % 3 != 2:
                    print("Move needs 3 args per position args")
                    continue

                client.enableApiControl(True)
                iterations = (len(args) - 2) / 3
                path = []
                for i in range(int(iterations)):
                    point = airsim.Vector3r(
                        float(args[(i * 3) + 1]),
                        float(args[(i * 3) + 2]),
                        float(args[(i * 3) + 3]),
                    )
                    path.append(point)

                try:
                    client.moveOnPathAsync(
                        path,
                        float(args[-1]),
                        TIMEOUT,
                        airsim.DrivetrainType.ForwardOnly,
                        airsim.YawMode(False, 0),
                        20,
                        1,
                    ).join()
                except Exception as e:
                    print(f"moveOnPath threw exception: {e}")

                client.hoverAsync().join()
                print("Path moved!")
            else:
                print(f"Invalid moveOnPath command format: {cmd}")
            continue

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
