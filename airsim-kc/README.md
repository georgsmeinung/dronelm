# AirSim Terminal Drone Control
---
This repository provides a keyboard-based control script for AirSim multirotors using the `cosysairsim` library (from [Cosys-AirSim](https://github.com/Cosys-Lab/Cosys-AirSim)).

## Available Scripts

### **kc_control.py**
A standalone script that launches directly into interactive keyboard control. It listens to keyboard events and controls the drone in real-time.

**Start with:**
```bash
python kc_control.py
```

## Features

- **Dynamic Tilt Compensation**: Moving horizontally causes multirotors to lose lift due to tilt. The script automatically calculates a feed-forward altitude compensation based on translation speed to prevent the drone from losing height.
- **Max Degree of Freedom Control**: Translates forward/backward and left/right relative to the drone's heading without automatic rotation/yaw lock.
- **Clean Keyboard Buffer Exit**: Flushes the pressed key sequence when exiting with `ESC`, preventing key echo pollution in your terminal.
- **Simplified Telemetry**: Formats drone state variables (position, speed, orientation, GPS coordinates, landed state) into a clean, aligned ASCII table.

---

## Keyboard Bindings

| Key | Action |
| :---: | :--- |
| **W** / **S** | Move Forward / Backward |
| **A** / **D** | Move Left / Right |
| **X** / **Z** | Move Up / Down |
| **Q** / **E** | Yaw (Turn Left / Right) |
| **H** | Hover (stabilize) |
| **T** | Take off / hover if already flying |
| **L** | Land in place |
| **R** | Reset simulation |
| **Space** | Clear terminal screen, reprint help, and reset input velocity state |
| **?** | Print simplified telemetry table |
| **ESC** | Exit keyboard control and release AirSim connection |

---

## Installation

Install the required dependencies:

```bash
pip install cosysairsim pynput python-dotenv numpy
```

Ensure you have a `.env` file in the directory pointing to your AirSim instance if running on a remote machine:
```env
AIRSIM_IP=127.0.0.1
```
