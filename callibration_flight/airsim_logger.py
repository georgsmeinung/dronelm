# logger.py  -- run this in a separate terminal
import cosysairsim as airsim
import time
import csv
from datetime import datetime

INTERVAL = 0.1          # 10 Hz
client = airsim.MultirotorClient()   # defaults to localhost:41451
client.confirmConnection()

# No enableApiControl() here!

csv_file = f"telemetry_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
with open(csv_file, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["time", "sim_t", "x", "y", "z", "vx", "vy", "vz", "yaw_deg"])

    print("Logging started (Ctrl+C to stop)")
    try:
        while True:
            start = time.time()
            state = client.getMultirotorState()

            pos = state.kinematics_estimated.position
            vel = state.kinematics_estimated.linear_velocity
            yaw = airsim.to_eularian_angles(state.kinematics_estimated.orientation)[2] * 180 / 3.14159

            """"
            writer.writerow([
                datetime.now().isoformat(),
                state.timestamp / 1e9,
                pos.x_val, pos.y_val, pos.z_val,
                vel.x_val, vel.y_val, vel.z_val,
                yaw
            ])
            f.flush()
            """ 
            print(
                f"time={datetime.now().isoformat()}, sim_t={state.timestamp / 1e9:.2f}, "
                f"pos=({pos.x_val:.2f}, {pos.y_val:.2f}, {pos.z_val:.2f}), "
                f"vel=({vel.x_val:.2f}, {vel.y_val:.2f}, {vel.z_val:.2f}), "
                f"yaw={yaw:.2f}"
            )

            dt = time.time() - start
            time.sleep(max(0.001, INTERVAL - dt))   # tight loop, still ~accurate rate

    except KeyboardInterrupt:
        print("\nLogging stopped")