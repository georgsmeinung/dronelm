# AirSim Terminal Drone Control
---
This is an updated version forked from https://github.com/Zartris/Airsim-terminal-drone-control for using the new library `cosysairsim` from https://github.com/Cosys-Lab/Cosys-AirSim

## Available Scripts

### 1. **simple_control.py** (Original)
Basic terminal controller with minimal UI formatting.

### 2. **advanced_control.py** (Recommended) ⭐
Enhanced terminal controller with:
- **Rich Terminal UI** - Colored output with formatted headers and sections
- **Status Icons** - Success (✓), Error (✗), Info (ℹ), Warning (⚠) messages
- **Formatted Tables** - Command reference displayed as organized tables
- **Real-time Telemetry** - Inline telemetry display during keyboard control
- **Command History** - Built-in command history tracking
- **Echo Fix** - Clean keyboard control mode exit with no echo artifacts
- **Better Error Messages** - Informative feedback for invalid commands

**Start with:** `python advanced_control.py`

### Comparison

| Feature | simple_control.py | advanced_control.py |
|---------|------------------|-------------------|
| Basic Commands | ✓ | ✓ |
| Colored Output | ✗ | ✓ |
| Formatted Headers | ✗ | ✓ |
| Status Icons | ✗ | ✓ |
| Command Table | ✗ | ✓ |
| Keyboard Echo Fix | Partial | ✓ Full |
| Command History | ✗ | ✓ |
| Real-time UI | ✗ | ✓ |

## Commands

All commands are case insensitive:

- **arm** - Arm the drone motors
- **disarm** - Disarm the drone motors
- **takeoff** - Take off from ground
- **home** - Return to home position and disarm
- **reset** - Reset the simulation
- **stop** - Stop all operations and reset
- **state** - Display drone telemetry (position, velocity, IMU, GPS, etc.)
- **kc** - Enter keyboard control mode
- **move** `<x> <y> <z> <velocity>` - Move to absolute position
- **moveonpath** `<x1> <y1> <z1> ... <xn> <yn> <zn> <velocity>` - Follow waypoints
- **inspect** `<speed> <iterations> [x] [y]` - Orbit around target
- **help** - Display all available commands
- **clear** - Clear terminal screen

## Installation

```bash
pip install cosys airsim pynput
```

**Library Notes:**
- Using `pynput` over `keyboard` because Linux users don't need to run as sudo
- Custom wrapper (`KeyController.py`) handles multiple simultaneous key presses

## Keyboard Control Mode

### Entering Keyboard Control

```bash
[HH:MM:SS] › kc
```

**Prerequisites:**
- Drone must be armed: `arm`
- Drone should be in the air: `takeoff`

### Keyboard Bindings

| Key | Action |
|-----|--------|
| **W** | Forward (+ X-axis) |
| **S** | Backward (- X-axis) |
| **D** | Right (+ Y-axis) |
| **A** | Left (- Y-axis) |
| **Z** | Up (- Z-axis) |
| **X** | Down (+ Z-axis) |
| **E** | Turn Right |
| **Q** | Turn Left |
| **H** | Hover (stabilize) |
| **T** | Exit keyboard control mode |

### Control Information

- **Coordinate System:** World space (independent of drone orientation)
- **Smooth Motion:** Velocity decreases gradually when keys are released
- **Real-time Telemetry:** Displays velocity and position while in control
- **Clean Exit:** Pressing 't' exits with no echo artifacts (advanced_control.py)

### Example Session (advanced_control.py)

```
[23:29:30] › arm
✓ Drone armed

[23:29:32] › takeoff
✓ Takeoff completed

[23:29:35] › kc

VX: 0.00 m/s │ VY: 0.00 m/s │ X: 10.50 m │ Y: 20.30 m │ Z: -15.20 m
(Press W to move forward...)
VX: 5.50 m/s │ VY: 0.00 m/s │ X: 10.80 m │ Y: 20.35 m │ Z: -15.22 m
(Press T to exit...)

✓ Keyboard control mode exited

[23:29:45] › home
✓ Returned home and disarmed
```
