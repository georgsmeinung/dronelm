import sys
import os
import time
import tempfile
import contextlib
import asyncio
import numpy as np
import cv2
import cosysairsim as airsim
from mcp.server.fastmcp import FastMCP

# --- FIX 1: Windows Event Loop Safety ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Logging Helper (Writes to stderr to allow JSON on stdout) ---
def log(msg):
    sys.stderr.write(f"[DroneMCP] {msg}\n")
    sys.stderr.flush()

# --- Protocol Protection ---
@contextlib.contextmanager
def suppress_stdout():
    """Redirects stdout to stderr to protect the MCP pipe."""
    original_stdout = sys.stdout
    try:
        sys.stdout = sys.stderr
        yield
    finally:
        sys.stdout = original_stdout

# Initialize MCP
mcp = FastMCP("Cosys-AirSim Drone Control")

# Global Client
client = None

# --- Core Logic (Synchronous) ---
# We define these as standard functions to be run in a thread later.

def _connect_to_airsim():
    """Connects to the drone. MUST be run in a thread/safe context."""
    global client
    log("Attempting to connect to AirSim...")
    try:
        with suppress_stdout():
            # Create client
            c = airsim.MultirotorClient()
            c.confirmConnection()
            c.enableApiControl(True)
            c.armDisarm(True)
            log("Connected successfully!")
            return c
    except Exception as e:
        log(f"Connection failed: {e}")
        return None

def _get_telemetry_sync():
    global client
    if not client: return "Not connected."
    
    with suppress_stdout():
        state = client.getMultirotorState()
        
    pos = state.kinematics_estimated.position
    orient = state.kinematics_estimated.orientation
    return (
        f"Position (NED): x={pos.x_val:.2f}, y={pos.y_val:.2f}, z={pos.z_val:.2f}\n"
        f"Orientation: w={orient.w_val:.2f}, x={orient.x_val:.2f}, y={orient.y_val:.2f}, z={orient.z_val:.2f}\n"
        f"Status: {state.landed_state}"
    )

def _action_sync(action_type, *args):
    global client
    if not client: 
        # Try one reconnect attempt
        client = _connect_to_airsim()
        if not client: return "Error: Could not connect to simulator."

    try:
        with suppress_stdout():
            if action_type == "takeoff":
                target_z = args[0]
                # Execute takeoff and move to altitude
                takeoff_future = client.takeoffAsync()
                takeoff_future.join()
                
                movez_future = client.moveToZAsync(target_z, 1)
                movez_future.join()
                return "Takeoff complete."
                
            elif action_type == "navigate":
                x, y, z, v = args
                move_future = client.moveToPositionAsync(x, y, z, v)
                move_future.join()
                return f"Moved to ({x}, {y}, {z})"
                
            elif action_type == "hover":
                hover_future = client.hoverAsync()
                hover_future.join()
                return "Hovering."
                
            elif action_type == "reset":
                client.reset()
                client.enableApiControl(False)
                return "Reset complete."
                
            elif action_type == "image":
                responses = client.simGetImages([airsim.ImageRequest("0", airsim.ImageType.Scene, False, False)])
                response = responses[0]
                tmp_dir = os.path.join(tempfile.gettempdir(), "airsim_drone")
                os.makedirs(tmp_dir, exist_ok=True)
                filename = os.path.join(tmp_dir, f"img_{int(time.time())}.png")
                img1d = np.frombuffer(response.image_data_uint8, dtype=np.uint8)
                img_rgb = img1d.reshape(response.height, response.width, 3)
                cv2.imwrite(filename, img_rgb)
                return f"Image saved: {filename}"
    except Exception as e:
        log(f"Action '{action_type}' failed with error: {e}")
        return f"Error executing {action_type}: {str(e)}"

# --- MCP Tools (Async Wrappers) ---
# These are async, but they immediately offload work to avoid blocking the loop.

@mcp.tool()
async def connect() -> str:
    """Manually attempts to connect/reconnect to the simulator."""
    global client
    client = await asyncio.to_thread(_connect_to_airsim)
    if client:
        return "Connected to AirSim."
    return "Failed to connect. Is AirSim running?"

@mcp.tool()
async def get_telemetry() -> str:
    """Get position and status."""
    return await asyncio.to_thread(_get_telemetry_sync)

@mcp.tool()
async def takeoff(altitude: float = -2.0) -> str:
    """Takeoff to altitude (meters, negative is Up)."""
    return await asyncio.to_thread(_action_sync, "takeoff", altitude)

@mcp.tool()
async def navigate_to(x: float, y: float, z: float, speed: float = 5.0) -> str:
    """Fly to NED coordinates."""
    return await asyncio.to_thread(_action_sync, "navigate", x, y, z, speed)

@mcp.tool()
async def hover() -> str:
    """Hover in place."""
    return await asyncio.to_thread(_action_sync, "hover")

@mcp.tool()
async def capture_image() -> str:
    """Take a picture."""
    return await asyncio.to_thread(_action_sync, "image")

@mcp.tool()
async def reset() -> str:
    """Reset simulation."""
    return await asyncio.to_thread(_action_sync, "reset")

if __name__ == "__main__":
    log("Server starting...")
    sys.stderr.flush()
    try:
        log("Running MCP server...")
        sys.stderr.flush()
        mcp.run()
    except BrokenPipeError:
        log("Client disconnected (broken pipe)")
    except KeyboardInterrupt:
        log("Server interrupted")
    except Exception as e:
        log(f"Fatal Error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)