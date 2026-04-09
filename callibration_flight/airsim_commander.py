import cosysairsim as airsim
import time
import subprocess
import os
import sys
import re

def main():
    # 1. Start airsim_logger.py as a subprocess
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logger_path = os.path.join(script_dir, "airsim_logger.py")
    path_file = os.path.join(script_dir, "calibration_path.txt")

    print(f"Starting logger: {logger_path}")
    # Using sys.executable to ensure we use the same python environment
    logger_proc = subprocess.Popen([sys.executable, logger_path], cwd=script_dir)

    # Give the logger a moment to start and connect
    time.sleep(2)

    # 2. Connect to AirSim
    client = airsim.MultirotorClient()
    client.confirmConnection()
    client.enableApiControl(True)
    client.armDisarm(True)

    # 3. Read and execute commands from calibration_path.txt
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
            # Logger should stop automatically on reset due to its internal logic
            break
        
        else:
            print(f"Unknown command: {cmd}")

    print("Commander finished.")
    # In case reset wasn't the last command or didn't stop the logger
    time.sleep(1)
    if logger_proc.poll() is None:
        print("Stopping logger process...")
        logger_proc.terminate()

if __name__ == "__main__":
    main()
