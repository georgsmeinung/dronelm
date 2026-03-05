import asyncio
import string
from typing import List

import cosysairsim as airsim
from mcp.server.fastmcp import FastMCP

# TIMEOUT used by move_on_path
TIMEOUT = 1200

# Global drone instance (recommended for MCP stability with LM Studio)
drone = airsim.MultirotorClient()
drone.confirmConnection()
drone.enableApiControl(True)

# Optional: segmentation setup (from original script)
def setup_segmentation():
    def change_color(name: str, id: int):
        drone.simSetSegmentationObjectID(name + "[\\w]*", id, True)

    def set_bg_color(color_id: int):
        for letter in string.ascii_lowercase:
            change_color(letter, color_id)

    set_bg_color(0)           # background
    change_color("segment_gate", 100)

setup_segmentation()

# MCP Server
mcp = FastMCP(
    name="drone-control"
)

@mcp.tool()
async def arm() -> str:
    """Arm the drone motors."""
    drone.armDisarm(True)
    return "Drone armed"

@mcp.tool()
async def disarm() -> str:
    """Disarm the drone motors."""
    drone.armDisarm(False)
    return "Drone disarmed"

@mcp.tool()
async def takeoff() -> str:
    """Take off (or hover if already in air)."""
    state = drone.getMultirotorState()
    if state.landed_state == airsim.LandedState.Landed:
        drone.takeoffAsync().join()
        return "Takeoff completed"
    drone.hoverAsync().join()
    return "Hovering"

@mcp.tool()
async def move_to_position(x: float, y: float, z: float, velocity: float = 5.0) -> str:
    """Move to absolute position (NED coordinates)."""
    drone.moveToPositionAsync(
        x=x, y=y, z=z, velocity=velocity,
        drivetrain=airsim.DrivetrainType.ForwardOnly,
        yaw_mode=airsim.YawMode(False, 0)
    ).join()
    drone.hoverAsync().join()
    return f"Moved to ({x:.2f}, {y:.2f}, {z:.2f})"

@mcp.tool()
async def move_on_path(path: List[List[float]], velocity: float = 5.0) -> str:
    """Fly through a sequence of waypoints: [[x1,y1,z1], [x2,y2,z2], ...]"""
    airsim_path = [airsim.Vector3r(p[0], p[1], p[2]) for p in path]
    drone.moveOnPathAsync(
        airsim_path, velocity, TIMEOUT,
        airsim.DrivetrainType.ForwardOnly, airsim.YawMode(False, 0)
    ).join()
    drone.hoverAsync().join()
    return f"Path with {len(path)} waypoints completed"

@mcp.tool()
async def home() -> str:
    """Return to home position and disarm."""
    drone.goHomeAsync().join()
    drone.armDisarm(False)
    return "Returned home"

@mcp.tool()
async def stop() -> str:
    """Emergency stop: go home, disarm and reset simulation."""
    drone.goHomeAsync()
    drone.armDisarm(False)
    drone.reset()
    return "Emergency stop executed"

@mcp.tool()
async def reset() -> str:
    """Reset the entire AirSim simulation."""
    drone.reset()
    return "Simulation reset"

@mcp.tool()
async def get_state() -> str:
    """Return current position, velocity and landed state."""
    state = drone.getMultirotorState()
    pos = state.kinematics_estimated.position
    vel = state.kinematics_estimated.linear_velocity
    return (f"Position:  ({pos.x_val:.2f}, {pos.y_val:.2f}, {pos.z_val:.2f})\n"
            f"Velocity:  ({vel.x_val:.2f}, {vel.y_val:.2f}, {vel.z_val:.2f})\n"
            f"Landed:    {state.landed_state.name}")

if __name__ == "__main__":
    print("AirSim Drone MCP Server started (LM Studio ready)")
    print("Connect via mcp.json -> command: python")
    mcp.run()