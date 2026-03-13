import json
import logging
import sys
import os

# Set up logging to a file for debugging, since stdout is used for MCP messages
# and LM studio treats stderr as errors.
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_drone.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler(sys.stderr) # Keep stderr but only for Warnings/Errors if needed, though we set fastmcp to WARNING below.
    ]
)
logger = logging.getLogger(__name__)

# Redirect standard output to devnull to prevent any random prints (from Airsim) 
# from corrupting the MCP stdio JSON-RPC transport.
class StreamToLogger(object):
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    @property
    def buffer(self):
        return sys.__stdout__.buffer

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

sys.stdout = StreamToLogger(logger, logging.DEBUG)

import numpy as np
import cosysairsim as airsim
from mcp.server.fastmcp import FastMCP
from airsim_functions.orbit import OrbitNavigator

# Configuration
TIMEOUT = 1200  # 20 mins

# Initialize the server
# Suppress INFO logs since LM Studio interprets any stderr output as an [ERROR]
mcp = FastMCP("AirSimDroneController")
mcp.logger.setLevel(logging.WARNING) if hasattr(mcp, 'logger') else None

import asyncio
import concurrent.futures

class DroneController:
    def __init__(self,
                 maxmin_velocity: float = 10,
                 drive_type: airsim.DrivetrainType = airsim.DrivetrainType.ForwardOnly):
        logger.info("Initializing DroneController...")
        self.DriveType = drive_type
        self.maxmin_vel = maxmin_velocity
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        
        # Initialize client inside the drone thread to ensure isolation of tornado loops
        self.executor.submit(self._init_drone_sync).result()

    def _init_drone_sync(self):
        try:
            logger.info("Connecting to AirSim MultirotorClient in dedicated thread...")
            self.client = airsim.MultirotorClient()
            self.confirm_connection()
            logger.info("DroneController initialization complete.")
        except Exception as e:
            logger.error(f"Failed to initialize AirSim client: {e}")

    def confirm_connection(self):
        logger.info("Confirming connection...")
        self.client.confirmConnection()
        logger.info("Enabling API control...")
        self.client.enableApiControl(True)
        logger.info("Connection confirmed and API control enabled.")

    def run_in_drone_thread(self, func, *args, **kwargs):
        """Helper to run a synchronous function in the dedicated drone thread."""
        return self.executor.submit(func, *args, **kwargs).result()

    def _takeoff_sync(self) -> str:
        state = self.client.getMultirotorState()
        if state.landed_state == airsim.LandedState.Landed:
            self.client.takeoffAsync().join()
            return "Taking off..."
        else:
            self.client.hoverAsync().join()
            return "Already in air, hovering."

    def takeoff(self) -> str:
        return self.run_in_drone_thread(self._takeoff_sync)

    def _arm_sync(self) -> str:
        self.client.armDisarm(True)
        return "Armed"
        
    def arm(self) -> str:
        return self.run_in_drone_thread(self._arm_sync)

    def _disarm_sync(self) -> str:
        self.client.armDisarm(False)
        return "Disarmed"
        
    def disarm(self) -> str:
         return self.run_in_drone_thread(self._disarm_sync)

    def _move_to_position_sync(self, x: float, y: float, z: float, velocity: float) -> str:
        self.client.enableApiControl(True)
        self.client.moveToPositionAsync(
            x=x, y=y, z=z, velocity=velocity, 
            drivetrain=airsim.DrivetrainType.ForwardOnly,
            yaw_mode=airsim.YawMode(False, 0)
        ).join()
        self.client.hoverAsync().join()
        return f"Moved to ({x}, {y}, {z}) at velocity {velocity}"

    def move_to_position(self, x: float, y: float, z: float, velocity: float) -> str:
        return self.run_in_drone_thread(self._move_to_position_sync, x, y, z, velocity)

    def _move_on_path_sync(self, path_points: list[dict], velocity: float) -> str:
        self.client.enableApiControl(True)
        path = []
        for pt in path_points:
             point = airsim.Vector3r(float(pt['x']), float(pt['y']), float(pt['z']))
             path.append(point)
        try:
            self.client.moveOnPathAsync(
                path, float(velocity), TIMEOUT,
                airsim.DrivetrainType.ForwardOnly, airsim.YawMode(False, 0),
                20, 1
            ).join()
        except Exception as e:
            return f"moveOnPath threw exception: {str(e)}"
        
        self.client.hoverAsync().join()
        return "Path moved successfully."

    def move_on_path(self, path_points: list[dict], velocity: float) -> str:
        return self.run_in_drone_thread(self._move_on_path_sync, path_points, velocity)

    def _home_sync(self) -> str:
        self.client.goHomeAsync()
        self.client.armDisarm(False)
        return "Returned to home and disarmed."

    def home(self) -> str:
         return self.run_in_drone_thread(self._home_sync)

    def _stop_sync(self) -> str:
        self.client.goHomeAsync()
        self.client.armDisarm(False)
        self.client.reset()
        return "Stopped and reset."
        
    def stop(self) -> str:
        return self.run_in_drone_thread(self._stop_sync)

    def look_at(self, target_pos, current_pos):
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]
        angle = np.arctan2(dy, dx) * 180 / np.math.pi
        return angle

    def _orbit_sync(self, speed: float, iterations: int, target_x: float, target_y: float) -> str:
        for i in range(iterations):
            current_pos = self.client.getMultirotorState().kinematics_estimated.position
            look_at_point = np.array([target_x, target_y])
            current_pos_np = np.array([current_pos.x_val, current_pos.y_val])
            angle = self.look_at(look_at_point, np.array([1, 0]))
            l = look_at_point - current_pos_np
            radius = float(np.linalg.norm(l))
            
            self.client.enableApiControl(True)
            self.client.rotateToYawAsync(angle, 20, 0).join()
            
            nav = OrbitNavigator(self.client,
                                 radius=radius,
                                 altitude=float(current_pos.z_val),
                                 speed=speed,
                                 iterations=1,
                                 center=l)
            nav.start()
            self.client.moveToPositionAsync(
                current_pos.x_val, current_pos.y_val, current_pos.z_val - radius, speed, 10
            ).join()
        return f"Completed {iterations} orbit(s) around ({target_x}, {target_y})."

    def orbit(self, speed: float, iterations: int, target_x: float, target_y: float) -> str:
         return self.run_in_drone_thread(self._orbit_sync, speed, iterations, target_x, target_y)

    def _get_state_sync(self) -> str:
        state = self.client.getMultirotorState()
        pos = state.kinematics_estimated.position
        vel = state.kinematics_estimated.linear_velocity
        
        info = {
            "landed_state": str(state.landed_state),
            "position": {"x": pos.x_val, "y": pos.y_val, "z": pos.z_val},
            "velocity": {"x": vel.x_val, "y": vel.y_val, "z": vel.z_val}
        }
        return json.dumps(info, indent=2)

    def get_state(self) -> str:
        return self.run_in_drone_thread(self._get_state_sync)

    def _reset_sync(self) -> str:
        self.client.reset()
        return "Simulation reset."

    def reset(self) -> str:
         return self.run_in_drone_thread(self._reset_sync)

# Instantiate drone controller globally
drone = DroneController()

@mcp.tool()
def drone_takeoff() -> str:
    """Takeoff the drone. Needs to be armed first."""
    return drone.takeoff()

@mcp.tool()
def drone_arm() -> str:
    """Arm the drone propellers."""
    return drone.arm()

@mcp.tool()
def drone_disarm() -> str:
    """Disarm the drone propellers."""
    return drone.disarm()

@mcp.tool()
def drone_move_to_position(x: float, y: float, z: float, velocity: float) -> str:
    """Move the drone to a specific (x, y, z) coordinate with a given velocity."""
    return drone.move_to_position(x, y, z, velocity)

@mcp.tool()
def drone_move_on_path(path_points: str, velocity: float) -> str:
    """
    Move the drone on a path.
    path_points should be a JSON-encoded string of a list of dictionaries with x, y, z coordinates.
    Example: '[{"x": 10, "y": 10, "z": -10}, {"x": 20, "y": 20, "z": -10}]'
    """
    try:
         points = json.loads(path_points)
         return drone.move_on_path(points, velocity)
    except Exception as e:
         return f"Error parsing path_points: {e}"

@mcp.tool()
def drone_go_home() -> str:
    """Return the drone back to its home position and disarm."""
    return drone.home()

@mcp.tool()
def drone_stop() -> str:
    """Stop the drone, return home, and reset."""
    return drone.stop()

@mcp.tool()
def drone_orbit(speed: float, iterations: int, target_x: float, target_y: float) -> str:
    """Make the drone orbit around a specific (target_x, target_y) coordinate."""
    return drone.orbit(speed, iterations, target_x, target_y)

@mcp.tool()
def drone_get_state() -> str:
    """Get the current state (position, velocity, landed state) of the drone."""
    return drone.get_state()

@mcp.tool()
def drone_reset() -> str:
    """Reset the AirSim simulation environment."""
    return drone.reset()

if __name__ == '__main__':
    # Start the FastMCP server with stdio transport by default
    mcp.run(transport='stdio')

