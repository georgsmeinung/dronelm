import os
import sys
import pprint
import string
import time
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv

# Enable UTF-8 output on Windows
if sys.platform.startswith("win"):
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

import cosysairsim as airsim
import numpy as np
from pynput.keyboard import KeyCode

from KeyController import KeyController

# TIMEOUT
from airsim_functions.orbit import OrbitNavigator

TIMEOUT = 1200  # 20 mins

# Mesh ID's
BG = 0
LAND = 100
WATER = 200
SHIP = 300

# Commands:
ARM = "arm"
CLEAR = "clear"
DISARM = "disarm"
MOVE = "move"
MOVE_PATH = "moveonpath"
HELP = "help"
HOME = "home"
STATE = "state"
TAKEOFF = "takeoff"
RESET = "reset"
STOP = "stop"
KEYBOARD_CONTROL = "kc"
PILOT_CONTROL = "pc"
ORBIT = "inspect"
FORWARD_FORCE = 1
BACKWARD_FORCE = -1
RIGHT_FORCE = 1
LEFT_FORCE = -1


# UI Colors and Styles
class UIColors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    GRAY = "\033[90m"
    END = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


class UIFormatter:
    @staticmethod
    def print_header(text: str):
        """Print a formatted header"""
        width = 80
        print(f"\n{UIColors.BOLD}{UIColors.CYAN}{'─' * width}{UIColors.END}")
        print(f"{UIColors.BOLD}{UIColors.CYAN}▸ {text}{UIColors.END}")
        print(f"{UIColors.BOLD}{UIColors.CYAN}{'─' * width}{UIColors.END}\n")

    @staticmethod
    def print_section(title: str, content: str = ""):
        """Print a section with title and optional content"""
        print(f"{UIColors.BOLD}{UIColors.BLUE}┌─ {title}{UIColors.END}")
        if content:
            for line in content.split("\n"):
                if line.strip():
                    print(f"{UIColors.BLUE}│ {UIColors.END}{line}")
        print(f"{UIColors.BLUE}└─{UIColors.END}\n")

    @staticmethod
    def print_success(message: str):
        """Print a success message"""
        print(f"{UIColors.GREEN}✓ {message}{UIColors.END}")

    @staticmethod
    def print_error(message: str):
        """Print an error message"""
        print(f"{UIColors.RED}✗ {message}{UIColors.END}")

    @staticmethod
    def print_info(message: str):
        """Print an info message"""
        print(f"{UIColors.CYAN}ℹ {message}{UIColors.END}")

    @staticmethod
    def print_warning(message: str):
        """Print a warning message"""
        print(f"{UIColors.YELLOW}⚠ {message}{UIColors.END}")

    @staticmethod
    def format_value(label: str, value, unit: str = ""):
        """Format a key-value pair for display"""
        return f"{UIColors.GRAY}{label}:{UIColors.END} {UIColors.BOLD}{value}{UIColors.END} {unit}"

    @staticmethod
    def print_table(headers: List[str], rows: List[List[str]]):
        """Print a formatted table"""
        col_widths = [
            max(len(h), max((len(str(r[i])) for r in rows), default=0))
            for i, h in enumerate(headers)
        ]

        # Header
        header_line = " │ ".join(f"{h:<{col_widths[i]}}" for i, h in enumerate(headers))
        print(f"{UIColors.BOLD}{UIColors.BLUE}{header_line}{UIColors.END}")
        print(f"{UIColors.BLUE}{'─' * len(header_line)}{UIColors.END}")

        # Rows
        for row in rows:
            row_line = " │ ".join(
                f"{str(r):<{col_widths[i]}}" for i, r in enumerate(row)
            )
            print(row_line)


class CommandHistory:
    def __init__(self, max_size: int = 100):
        self.history: List[str] = []
        self.max_size = max_size
        self.position = 0

    def add(self, command: str):
        """Add a command to history"""
        if command.strip():
            self.history.append(command)
            if len(self.history) > self.max_size:
                self.history.pop(0)
            self.position = len(self.history)

    def get_previous(self) -> Optional[str]:
        """Get previous command from history"""
        if self.position > 0:
            self.position -= 1
            return self.history[self.position]
        return None

    def get_next(self) -> Optional[str]:
        """Get next command from history"""
        if self.position < len(self.history) - 1:
            self.position += 1
            return self.history[self.position]
        return None


class AdvancedTerminalController:
    def __init__(
        self,
        verbatim: bool = True,
        maxmin_velocity: float = 10,
        drive_type: airsim.DrivetrainType = airsim.DrivetrainType.ForwardOnly,
        client: airsim.MultirotorClient = None,
    ):
        # Should this class print to terminal
        self.verbatim = verbatim
        self.DriveType = drive_type
        self.client = client
        if client is None:
            load_dotenv()
            airsim_ip = os.getenv("AIRSIM_IP", "")
            if airsim_ip:
                self.client = airsim.MultirotorClient(ip=airsim_ip)
            else:
                self.client = airsim.MultirotorClient()
        self.confirm_connection()
        # Segmentation setup
        self.setup_segmentation_colors()

        # Movement and constraints:
        self.vx = 0
        self.vy = 0
        self.vz = 0
        self.yaw = 0
        self.nav = None

        self.maxmin_vel = maxmin_velocity
        self.command_history = CommandHistory()
        self.show_welcome()

    def show_welcome(self):
        """Display welcome screen"""
        UIFormatter.print_header("AirSim Advanced Control System")
        print(f"{UIColors.GRAY}Connected to AirSim simulation{UIColors.END}\n")
        self.show_help()

    def confirm_connection(self):
        self.client.confirmConnection()
        self.client.enableApiControl(True)

    def setup_segmentation_colors(self):
        """
        Find all objects and make them one color
        then find the specific objects and turn them into different colors.
        """
        self.set_bg_color(color_id=BG)
        self.change_color("segment_gate", LAND)

    def change_color(self, name, id):
        success = self.client.simSetSegmentationObjectID(name + "[\w]*", id, True)
        # Suppress verbose color change messages during initialization
        # Only log errors if explicitly requested
        if False:  # Disabled to reduce startup noise
            status = (
                f"{UIColors.GREEN}success{UIColors.END}"
                if success
                else f"{UIColors.RED}failed{UIColors.END}"
            )
            UIFormatter.print_info(f"Color change on '{name}': {status}")

    def set_bg_color(self, color_id):
        alphabet = list(string.ascii_lowercase)
        for letter in alphabet:
            self.change_color(letter, color_id)

    def takeoff(self):
        UIFormatter.print_info("Executing takeoff sequence...")
        state = self.client.getMultirotorState()
        if state.landed_state == airsim.LandedState.Landed:
            UIFormatter.print_info("Drone is landed, initiating takeoff...")
            self.client.takeoffAsync().join()
            UIFormatter.print_success("Takeoff completed")
        else:
            UIFormatter.print_info("Drone already airborne, engaging hover...")
            self.client.hoverAsync().join()

    def arm(self):
        UIFormatter.print_info("Arming drone...")
        self.client.armDisarm(True)
        UIFormatter.print_success("Drone armed")

    def disarm(self):
        UIFormatter.print_info("Disarming drone...")
        self.client.armDisarm(False)
        UIFormatter.print_success("Drone disarmed")

    def move_to_position(self, args: list):
        UIFormatter.print_info("Processing movement command...")
        if len(args) != 5:
            UIFormatter.print_error(
                "Move requires 5 arguments: move <x> <y> <z> <velocity>"
            )
            return
        try:
            x, y, z, vel = (
                float(args[1]),
                float(args[2]),
                float(args[3]),
                float(args[4]),
            )
            print(
                f"{UIColors.GRAY}Target: x={x}, y={y}, z={z}, velocity={vel}{UIColors.END}"
            )
            self.client.enableApiControl(True)
            self.client.moveToPositionAsync(
                x=x,
                y=y,
                z=z,
                velocity=vel,
                drivetrain=airsim.DrivetrainType.ForwardOnly,
                yaw_mode=airsim.YawMode(False, 0),
            ).join()
            self.client.hoverAsync().join()
            UIFormatter.print_success("Movement completed")
        except ValueError as e:
            UIFormatter.print_error(f"Invalid argument format: {e}")

    def move_on_path(self, args: list):
        UIFormatter.print_info("Processing path movement command...")
        if len(args) % 3 != 2:
            UIFormatter.print_error(
                "MoveOnPath requires 3n+2 arguments: moveonpath <x1> <y1> <z1> ... <xn> <yn> <zn> <velocity>"
            )
            return
        try:
            self.client.enableApiControl(True)
            iterations = (len(args) - 2) / 3
            path = []
            for i in range(int(iterations)):
                point = airsim.Vector3r(
                    float(args[(i * 3) + 1]),
                    float(args[(i * 3) + 2]),
                    float(args[(i * 3) + 3]),
                )
                path.append(point)
                if self.verbatim:
                    UIFormatter.print_info(
                        f"Waypoint {i + 1}: ({point.x_val}, {point.y_val}, {point.z_val})"
                    )

            result = self.client.moveOnPathAsync(
                path,
                float(args[-1]),
                TIMEOUT,
                airsim.DrivetrainType.ForwardOnly,
                airsim.YawMode(False, 0),
                20,
                1,
            ).join()
            self.client.hoverAsync().join()
            UIFormatter.print_success("Path completed")
        except Exception as e:
            UIFormatter.print_error(f"Path movement failed: {str(e)}")

    def home(self):
        UIFormatter.print_info("Returning to home...")
        self.client.goHomeAsync()
        self.client.armDisarm(False)
        UIFormatter.print_success("Returned home and disarmed")

    def stop(self):
        UIFormatter.print_warning("Stopping all operations...")
        self.client.goHomeAsync()
        self.client.armDisarm(False)
        self.client.reset()
        UIFormatter.print_success("All operations stopped")

    def orbit(self, args):
        if len(args) < 3:
            UIFormatter.print_error(
                "Orbit requires at least: orbit <speed> <iterations> [x] [y]"
            )
            return
        try:
            if len(args) != 5:
                target_x = float(72.38)
                target_y = float(48.92)
                UIFormatter.print_info("Using default turbine 1 coordinates")
                self.client.enableApiControl(True)
                self.client.moveToPositionAsync(
                    x=float(36.33),
                    y=float(24.32),
                    z=-float(17.33),
                    velocity=2,
                    drivetrain=airsim.DrivetrainType.ForwardOnly,
                    yaw_mode=airsim.YawMode(False, 0),
                ).join()
                self.client.hoverAsync().join()
                airsim.time.sleep(2)
            else:
                target_x = float(args[3])
                target_y = float(args[4])
                UIFormatter.print_info(f"Using custom target: ({target_x}, {target_y})")

            speed = float(args[1])
            iterations = int(args[2])

            for i in range(iterations):
                current_pos = (
                    self.client.getMultirotorState().kinematics_estimated.position
                )
                look_at_point = np.array([target_x, target_y])
                current_pos_np = np.array([current_pos.x_val, current_pos.y_val])
                angle = self.lookAt(look_at_point, np.array([1, 0]))
                l = look_at_point - current_pos_np
                radius = np.linalg.norm(l)

                UIFormatter.print_info(
                    f"Orbit iteration {i + 1}/{iterations}, radius: {radius:.2f}m"
                )
                self.client.enableApiControl(True)
                self.client.rotateToYawAsync(angle, 20, 0).join()

                self.nav = OrbitNavigator(
                    self.client,
                    radius=radius,
                    altitude=float(current_pos.z_val),
                    speed=speed,
                    iterations=1,
                    center=l,
                )

                self.nav.start()
                self.client.moveToPositionAsync(
                    current_pos.x_val,
                    current_pos.y_val,
                    current_pos.z_val - radius,
                    speed,
                    10,
                ).join()

            UIFormatter.print_success("Orbit maneuver completed")
        except Exception as e:
            UIFormatter.print_error(f"Orbit failed: {str(e)}")

    def lookAt(self, target_pos, current_pos):
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]
        angle = np.arctan2(dy, dx) * 180 / np.math.pi
        return angle

    def handle_key_pressed(
        self, keys_to_check: list, pressed_keys: list, current_vel: float
    ) -> float:
        new_vel = current_vel
        positive_axis_press = KeyCode.from_char(keys_to_check[0]) in pressed_keys
        negative_axis_press = KeyCode.from_char(keys_to_check[1]) in pressed_keys

        if positive_axis_press and negative_axis_press:
            return new_vel

        if positive_axis_press:
            return round(
                number=float(np.clip(new_vel + 1, -self.maxmin_vel, self.maxmin_vel)),
                ndigits=2,
            )

        if negative_axis_press:
            return round(
                number=float(np.clip(new_vel - 1, -self.maxmin_vel, self.maxmin_vel)),
                ndigits=2,
            )

        # nothing is pressed, smoothly lowering the value
        return round(
            number=float(np.clip(new_vel * 0.75, -self.maxmin_vel, self.maxmin_vel)),
            ndigits=2,
        )

    @staticmethod
    def handle_rotation(keys_to_check: list, pressed_keys: list) -> float:
        positive_rotation_press = KeyCode.from_char(keys_to_check[0]) in pressed_keys
        negative_rotation_press = KeyCode.from_char(keys_to_check[1]) in pressed_keys

        if positive_rotation_press and negative_rotation_press:
            return 0
        if positive_rotation_press:
            return 20
        if negative_rotation_press:
            return -20
        return 0

    @staticmethod
    def handle_height(
        keys_to_check: list, pressed_keys: list, current_height: float
    ) -> float:
        positive_axis_press = KeyCode.from_char(keys_to_check[0]) in pressed_keys
        negative_axis_press = KeyCode.from_char(keys_to_check[1]) in pressed_keys

        if positive_axis_press and negative_axis_press:
            return current_height
        if positive_axis_press:
            return current_height + 0.2
        if negative_axis_press:
            return current_height - 0.2
        return current_height

    @staticmethod
    def body_frame_to_global(
        body_vx: float, body_vy: float, yaw_degrees: float
    ) -> tuple:
        """
        Convert velocity from drone body frame to global frame.
        body_vx: forward/backward velocity in body frame
        body_vy: left/right velocity in body frame
        yaw_degrees: drone heading in degrees (0 = North, 90 = East)
        Returns: (global_vx, global_vy)
        """
        # Convert yaw to radians
        yaw_rad = np.radians(yaw_degrees)

        # Rotation matrix for body frame to global frame
        cos_yaw = np.cos(yaw_rad)
        sin_yaw = np.sin(yaw_rad)

        # Apply rotation
        global_vx = body_vx * cos_yaw - body_vy * sin_yaw
        global_vy = body_vx * sin_yaw + body_vy * cos_yaw

        return float(global_vx), float(global_vy)

    def enter_keyboard_control(self):
        # Use plain text to avoid ANSI character display issues
        print("\n" + "=" * 80)
        print("Keyboard Control Mode".center(80))
        print("=" * 80)
        print("Press 't' to return to command mode\n")

        # Disable echo on Windows to prevent key characters from appearing
        if sys.platform.startswith("win"):
            try:
                import ctypes
                from ctypes import wintypes

                # Get handle to stdout
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE = -11

                # Get current console mode
                mode = wintypes.DWORD()
                kernel32.GetConsoleMode(handle, ctypes.byref(mode))

                # Disable echo (ENABLE_ECHO_INPUT = 0x0004)
                ENABLE_ECHO_INPUT = 0x0004
                mode.value &= ~ENABLE_ECHO_INPUT
                kernel32.SetConsoleMode(handle, mode)

                echo_disabled = True
            except Exception as e:
                if self.verbatim:
                    UIFormatter.print_warning(f"Could not disable echo: {str(e)}")
                echo_disabled = False
        else:
            echo_disabled = False

        kc = KeyController()
        z = self.client.getMultirotorState().kinematics_estimated.position.z_val
        self.client.enableApiControl(True)
        last_pos = None

        try:
            while kc.listener.running:
                self.client.cancelLastTask()
                self.client.enableApiControl(True)
                keys = kc.get_key_pressed()

                if "h" in keys:
                    self.client.hoverAsync()
                else:
                    quad_vel = self.client.getMultirotorState().kinematics_estimated.linear_velocity
                    quad_state = self.client.getMultirotorState()

                    # Get body frame velocities from keyboard input
                    body_vx = self.handle_key_pressed(
                        keys_to_check=["w", "s"],
                        pressed_keys=keys,
                        current_vel=quad_vel.x_val,
                    )
                    body_vy = self.handle_key_pressed(
                        keys_to_check=["d", "a"],
                        pressed_keys=keys,
                        current_vel=quad_vel.y_val,
                    )

                    # Get drone orientation to convert body frame to global frame
                    # Extract yaw from quaternion
                    orientation = quad_state.kinematics_estimated.orientation
                    # Convert quaternion to yaw (simplified - assuming mostly yaw rotation)
                    # Using standard quaternion to euler angles formula
                    qw, qx, qy, qz = (
                        orientation.w_val,
                        orientation.x_val,
                        orientation.y_val,
                        orientation.z_val,
                    )

                    # Calculate yaw from quaternion
                    yaw_rad = np.arctan2(
                        2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz)
                    )
                    yaw_deg = np.degrees(yaw_rad)

                    # Convert body frame velocities to global frame
                    global_vx, global_vy = self.body_frame_to_global(
                        body_vx, body_vy, yaw_deg
                    )
                    self.vx = global_vx
                    self.vy = global_vy

                    z = self.handle_height(
                        keys_to_check=["z", "x"], pressed_keys=keys, current_height=z
                    )
                    self.yaw = self.handle_rotation(
                        keys_to_check=["e", "q"], pressed_keys=keys
                    )

                    current_pos = (
                        self.client.getMultirotorState().kinematics_estimated.position
                    )

                    # Display telemetry in simple format (no colors to avoid escape char issues)
                    telemetry_line = (
                        f"VX: {self.vx:6.2f} m/s │ "
                        f"VY: {self.vy:6.2f} m/s │ "
                        f"X: {current_pos.x_val:8.2f} m │ "
                        f"Y: {current_pos.y_val:8.2f} m │ "
                        f"Z: {current_pos.z_val:8.2f} m"
                    )
                    # Pad to clear old content and print on same line
                    display_line = telemetry_line.ljust(100)
                    print(f"\r{display_line}", end="", flush=True)

                    self.client.moveByVelocityZAsync(
                        self.vx,
                        self.vy,
                        z,
                        0.1,
                        airsim.DrivetrainType.MaxDegreeOfFreedom,
                        airsim.YawMode(True, self.yaw),
                    ).join()
        finally:
            # Re-enable echo on Windows if it was disabled
            if sys.platform.startswith("win") and echo_disabled:
                try:
                    import ctypes
                    from ctypes import wintypes

                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE = -11

                    # Get current console mode
                    mode = wintypes.DWORD()
                    kernel32.GetConsoleMode(handle, ctypes.byref(mode))

                    # Re-enable echo (ENABLE_ECHO_INPUT = 0x0004)
                    ENABLE_ECHO_INPUT = 0x0004
                    mode.value |= ENABLE_ECHO_INPUT
                    kernel32.SetConsoleMode(handle, mode)
                except Exception as e:
                    if self.verbatim:
                        UIFormatter.print_warning(f"Could not re-enable echo: {str(e)}")

            # Clean up after exiting keyboard control
            print(f"\n")
            UIFormatter.print_success("Keyboard control mode exited")
            self.client.hoverAsync().join()

            # Stop the keyboard controller listener and clear key buffer
            kc.listener.stop()
            kc.key_pressed.clear()  # Clear all remaining pressed keys

            # Wait to let terminal settle and avoid key echo
            time.sleep(0.5)

            # Clear any leftover input in the buffer
            if sys.platform.startswith("win"):
                # Windows: use Windows API to flush input buffer
                try:
                    import ctypes

                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE = -10
                    kernel32.FlushConsoleInputBuffer(handle)
                except Exception as e:
                    if self.verbatim:
                        UIFormatter.print_warning(
                            f"Could not flush input buffer: {str(e)}"
                        )
            else:
                # Unix/Linux: use termios to flush input
                try:
                    import termios

                    termios.tcflush(sys.stdin, termios.TCIFLUSH)
                except (ImportError, OSError):
                    # Not on Unix or stdin not a tty, that's ok
                    pass

    def print_stats(self):
        UIFormatter.print_header("Drone Telemetry")

        try:
            state = self.client.getMultirotorState()
            pos = state.kinematics_estimated.position
            vel = state.kinematics_estimated.linear_velocity

            print(
                f"{UIFormatter.format_value('Position', f'({pos.x_val:.2f}, {pos.y_val:.2f}, {pos.z_val:.2f})', 'm')}"
            )
            print(
                f"{UIFormatter.format_value('Velocity', f'({vel.x_val:.2f}, {vel.y_val:.2f}, {vel.z_val:.2f})', 'm/s')}"
            )
            print(f"{UIFormatter.format_value('Landed State', state.landed_state)}\n")

            imu_data = self.client.getImuData()
            print(
                f"{UIFormatter.format_value('IMU Linear Acceleration', f'{imu_data.linear_acceleration}', 'm/s²')}"
            )
            print(
                f"{UIFormatter.format_value('IMU Angular Velocity', f'{imu_data.angular_velocity}', 'rad/s')}\n"
            )

            barometer_data = self.client.getBarometerData()
            print(
                f"{UIFormatter.format_value('Barometer Altitude', f'{barometer_data.altitude:.2f}', 'm')}"
            )
            print(
                f"{UIFormatter.format_value('Barometer Pressure', f'{barometer_data.pressure:.2f}', 'Pa')}\n"
            )

            magnetometer_data = self.client.getMagnetometerData()
            print(
                f"{UIFormatter.format_value('Magnetometer Field', f'{magnetometer_data.magnetic_field_body}', 'Tesla')}\n"
            )

            gps_data = self.client.getGpsData()
            print(
                f"{UIFormatter.format_value('GPS Position', f'Lat: {gps_data.gnss.latitude:.6f}, Lon: {gps_data.gnss.longitude:.6f}')}\n"
            )
        except Exception as e:
            UIFormatter.print_error(f"Failed to retrieve telemetry: {str(e)}")

    def clear_terminal(self):
        """Clears the terminal screen."""
        if os.name == "nt":
            _ = os.system("cls")
        else:
            _ = os.system("clear")
        self.show_welcome()

    def show_help(self):
        """Shows commands supported with improved formatting"""
        UIFormatter.print_header("Available Commands")

        commands = [
            ("arm", "Arm the drone motors"),
            ("disarm", "Disarm the drone motors"),
            ("takeoff", "Take off from ground"),
            ("home", "Return to home position"),
            ("reset", "Reset the simulation"),
            ("stop", "Stop all operations and return home"),
            ("state", "Display drone telemetry"),
            ("kc", "Enter keyboard control mode"),
            ("move", "Move to position: move <x> <y> <z> <velocity>"),
            (
                "moveonpath",
                "Follow waypoints: moveonpath <x1> <y1> <z1> ... <xn> <yn> <zn> <velocity>",
            ),
            ("inspect", "Orbit around target: inspect <speed> <iterations> [x] [y]"),
            ("help", "Display this help message"),
            ("clear", "Clear the terminal"),
        ]

        UIFormatter.print_table(["Command", "Description"], commands)

        UIFormatter.print_section(
            "Keyboard Control Keys",
            "W/S ─ Forward/Backward  │  D/A ─ Right/Left\n"
            "Z/X ─ Up/Down  │  E/Q ─ Turn Right/Left\n"
            "H ─ Hover  │  ? ─ Telemetry  │  T ─ Exit Mode",
        )

    def reset(self):
        UIFormatter.print_warning("Resetting simulation...")
        self.client.reset()
        UIFormatter.print_success("Simulation reset complete")

    def run(self):
        # Map command strings to lambda functions to normalize the input signature.
        command_dispatch = {
            ARM: lambda _: self.arm(),
            CLEAR: lambda _: self.clear_terminal(),
            DISARM: lambda _: self.disarm(),
            MOVE: lambda args: self.move_to_position(args),
            MOVE_PATH: lambda args: self.move_on_path(args),
            HELP: lambda _: self.show_help(),
            HOME: lambda _: self.home(),
            TAKEOFF: lambda _: self.takeoff(),
            STATE: lambda _: self.print_stats(),
            RESET: lambda _: self.reset(),
            KEYBOARD_CONTROL: lambda _: self.enter_keyboard_control(),
            STOP: lambda _: self.stop(),
            ORBIT: lambda args: self.orbit(args),
        }

        while True:
            try:
                # Get input and clean it
                timestamp = datetime.now().strftime("%H:%M:%S")
                raw_input = input(
                    f"\n{UIColors.GRAY}[{timestamp}]{UIColors.END} {UIColors.BOLD}›{UIColors.END} "
                ).strip()
                if not raw_input:
                    continue

                self.command_history.add(raw_input)
                args = raw_input.split(" ")
                command_type = args[0].lower()

                # 1. Look up the function (returns None if not found)
                action = command_dispatch.get(command_type)

                # 2. Execute or handle error
                if action:
                    action(args)
                else:
                    UIFormatter.print_error(
                        f"Unknown command: '{command_type}' (type 'help' for available commands)"
                    )

                # 3. Handle loop exit condition
                if command_type == STOP.lower():
                    UIFormatter.print_header("Shutting Down")
                    break

            except (KeyboardInterrupt, EOFError):
                print(f"\n")
                UIFormatter.print_warning("Interrupted by user")
                break
            except Exception as e:
                UIFormatter.print_error(f"An error occurred: {str(e)}")


if __name__ == "__main__":
    controller = AdvancedTerminalController(maxmin_velocity=20)
    controller.run()
