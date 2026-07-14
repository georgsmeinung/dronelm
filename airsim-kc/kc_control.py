import os
import pprint
import string

from dotenv import load_dotenv
import cosysairsim as airsim
import numpy as np
from pynput.keyboard import Key, KeyCode, Listener

# TIMEOUT
from airsim_functions.orbit import OrbitNavigator

TIMEOUT = 1200  # 20 mins
HEIGHT_STEP = 0.6

# Mesh ID's
BG = 0
LAND = 100
WATER = 200
SHIP = 300

FORWARD_FORCE = 1
BACKWARD_FORCE = -1
RIGHT_FORCE = 1
LEFT_FORCE = -1


class SimpleTerminalController:
    def __init__(self,
                 verbatim: bool = True,
                 maxmin_velocity: float = 10,
                 drive_type: airsim.DrivetrainType = airsim.DrivetrainType.ForwardOnly,
                 client: airsim.MultirotorClient = None):
        self.verbatim = verbatim
        self.DriveType = drive_type
        self.client = client
        if client is None:
            load_dotenv()
            airsim_ip = os.getenv("AIRSIM_IP", "")
            self.client = airsim.MultirotorClient(ip=airsim_ip) if airsim_ip else airsim.MultirotorClient()
        self.confirm_connection()
        self.setup_segmentation_colors()

        self.vx = 0.0
        self.vy = 0.0
        self.yaw = 0.0
        self.nav = None
        self.maxmin_vel = maxmin_velocity

        # Inline keyboard listener state (was KeyController)
        self._pressed_keys: list = []
        self._listener: Listener = None

    # -------------------------------------------------------------------------
    # Connection / setup
    # -------------------------------------------------------------------------

    def confirm_connection(self):
        self.client.confirmConnection()
        self.client.enableApiControl(True)

    def setup_segmentation_colors(self):
        """Assign segmentation IDs to scene objects."""
        self.set_bg_color(color_id=BG)
        self.change_color("segment_gate", LAND)

    def change_color(self, name: str, id: int):
        self.client.simSetSegmentationObjectID(name + "[\\w]*", id, True)

    def set_bg_color(self, color_id: int):
        for letter in string.ascii_lowercase:
            self.change_color(letter, color_id)

    # -------------------------------------------------------------------------
    # Drone actions
    # -------------------------------------------------------------------------

    def takeoff(self):
        state = self.client.getMultirotorState()
        if state.landed_state == airsim.LandedState.Landed:
            self.client.armDisarm(True)
            print("Taking off...")
            self.client.takeoffAsync().join()
        else:
            self.client.hoverAsync().join()

    def land(self):
        print("Landing in place...")
        self.client.landAsync().join()
        self.client.armDisarm(False)

    def arm(self):
        self.client.armDisarm(True)

    def disarm(self):
        self.client.armDisarm(False)

    def move_to_position(self, args: list):
        if len(args) != 5:
            print("Move needs 5 args")
            return
        self.client.enableApiControl(True)
        print("Move args:", float(args[1]), float(args[2]), float(args[3]), float(args[4]))
        self.client.moveToPositionAsync(
            x=float(args[1]), y=float(args[2]), z=float(args[3]),
            velocity=float(args[4]),
            drivetrain=airsim.DrivetrainType.ForwardOnly,
            yaw_mode=airsim.YawMode(False, 0),
        ).join()
        self.client.hoverAsync().join()

    def move_on_path(self, args: list):
        if len(args) % 3 != 2:
            print("Move needs 3 args per position")
            return
        self.client.enableApiControl(True)
        path = [
            airsim.Vector3r(float(args[i * 3 + 1]), float(args[i * 3 + 2]), float(args[i * 3 + 3]))
            for i in range(int((len(args) - 2) / 3))
        ]
        try:
            self.client.moveOnPathAsync(
                path, float(args[-1]), TIMEOUT,
                airsim.DrivetrainType.ForwardOnly, airsim.YawMode(False, 0),
                20, 1,
            ).join()
        except Exception:
            _, value, _ = airsim.sys.exc_info()
            print("moveOnPath threw exception:", value)
        self.client.hoverAsync().join()
        print("Path moved!")

    def home(self):
        print("Home received")
        self.client.goHomeAsync()
        self.client.armDisarm(False)

    def stop(self):
        self.client.goHomeAsync()
        self.client.armDisarm(False)
        self.client.reset()

    def reset(self):
        print("Resetting simulation")
        self.client.reset()

    def orbit(self, args):
        if len(args) < 3:
            return
        if len(args) != 4:
            target_x, target_y = 72.38, 48.92
            self.client.enableApiControl(True)
            self.client.moveToPositionAsync(
                x=36.33, y=24.32, z=-17.33, velocity=2,
                drivetrain=airsim.DrivetrainType.ForwardOnly,
                yaw_mode=airsim.YawMode(False, 0),
            ).join()
            self.client.hoverAsync().join()
            airsim.time.sleep(2)
        else:
            target_x, target_y = float(args[3]), float(args[4])

        speed = float(args[1])
        iterations = int(args[2])
        for _ in range(iterations):
            current_pos = self.client.getMultirotorState().kinematics_estimated.position
            look_at = np.array([target_x, target_y])
            cur_np = np.array([current_pos.x_val, current_pos.y_val])
            angle = self.lookAt(look_at, np.array([1, 0]))
            l = look_at - cur_np
            radius = np.linalg.norm(l)
            self.client.enableApiControl(True)
            self.client.rotateToYawAsync(angle, 20, 0).join()
            self.nav = OrbitNavigator(
                self.client, radius=radius,
                altitude=float(current_pos.z_val),
                speed=speed, iterations=1, center=l,
            )
            self.nav.start()
            self.client.moveToPositionAsync(
                current_pos.x_val, current_pos.y_val,
                current_pos.z_val - radius, speed, 10,
            ).join()

    def lookAt(self, target_pos, current_pos) -> float:
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]
        return np.arctan2(dy, dx) * 180 / np.pi

    # -------------------------------------------------------------------------
    # Velocity / height helpers
    # -------------------------------------------------------------------------

    def _axis_velocity(self, pos_key: str, neg_key: str, current: float) -> float:
        """Accelerate on key press, dampen on release. Clamps to ±maxmin_vel."""
        pos = KeyCode.from_char(pos_key) in self._pressed_keys
        neg = KeyCode.from_char(neg_key) in self._pressed_keys
        if pos == neg:          # both or neither → dampen
            return round(float(np.clip(current * 0.75, -self.maxmin_vel, self.maxmin_vel)), 2)
        delta = 1 if pos else -1
        return round(float(np.clip(current + delta, -self.maxmin_vel, self.maxmin_vel)), 2)

    def _axis_yaw(self, pos_key: str, neg_key: str) -> float:
        """Return yaw rate (deg/s) based on key state."""
        pos = KeyCode.from_char(pos_key) in self._pressed_keys
        neg = KeyCode.from_char(neg_key) in self._pressed_keys
        if pos == neg:
            return 0.0
        return 20.0 if pos else -20.0

    def _axis_height(self, pos_key: str, neg_key: str, current_z: float) -> float:
        """Step height up/down; no change if both or neither pressed."""
        pos = KeyCode.from_char(pos_key) in self._pressed_keys
        neg = KeyCode.from_char(neg_key) in self._pressed_keys
        if pos == neg:
            return current_z
        return current_z + (HEIGHT_STEP if pos else -HEIGHT_STEP)

    @staticmethod
    def _body_to_world(forward: float, right: float, yaw_rad: float) -> tuple[float, float]:
        wx = forward * np.cos(yaw_rad) - right * np.sin(yaw_rad)
        wy = forward * np.sin(yaw_rad) + right * np.cos(yaw_rad)
        return wx, wy

    @staticmethod
    def _quaternion_to_yaw(orientation) -> float:
        siny = 2.0 * (orientation.w_val * orientation.z_val + orientation.x_val * orientation.y_val)
        cosy = 1.0 - 2.0 * (orientation.y_val ** 2 + orientation.z_val ** 2)
        return float(np.arctan2(siny, cosy))

    # -------------------------------------------------------------------------
    # Keyboard listener (inlined from KeyController)
    # -------------------------------------------------------------------------

    def _on_press(self, key):
        if key not in self._pressed_keys:
            self._pressed_keys.append(key)

    def _on_release(self, key):
        if key in self._pressed_keys:
            self._pressed_keys.remove(key)

    def _start_listener(self):
        self._listener = Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def _stop_listener(self):
        if self._listener and self._listener.running:
            self._listener.stop()

    # -------------------------------------------------------------------------
    # Key-control loop
    # -------------------------------------------------------------------------

    def _handle_oneshot_keys(self, previous_keys: set):
        """
        Execute single-fire actions for keys that were just pressed
        (i.e. present now but not in the previous frame).
        Uses a mapping of KeyCode/Key → callable to avoid repetitive if-blocks.
        """
        oneshot_actions = {
            KeyCode.from_char('t'): self.takeoff,
            KeyCode.from_char('l'): self.land,
            KeyCode.from_char('r'): lambda: (self.reset(), self.client.enableApiControl(True)),
            KeyCode.from_char('?'): self.print_stats,
            Key.space: self._restart_control,
        }
        for key, action in oneshot_actions.items():
            if key in self._pressed_keys and key not in previous_keys:
                action()

    def _restart_control(self):
        """Reset velocity state, show help, and hover."""
        self.clear_terminal()
        self.show_help()
        self.client.hoverAsync().join()
        self.vx = self.vy = self.yaw = 0.0
        print("Keyboard control restarted.")

    def _process_movement(self):
        """Update velocity state and send movement command."""
        if KeyCode.from_char('h') in self._pressed_keys:
            self.client.hoverAsync()
            return

        self.vx = self._axis_velocity('w', 's', self.vx)
        self.vy = self._axis_velocity('d', 'a', self.vy)
        self.yaw = self._axis_yaw('e', 'q')

        state = self.client.getMultirotorState()
        yaw_rad = self._quaternion_to_yaw(state.kinematics_estimated.orientation)
        world_vx, world_vy = self._body_to_world(self.vx, self.vy, yaw_rad)
        z_target = self._axis_height('z', 'x', state.kinematics_estimated.position.z_val)

        self.client.moveByVelocityZAsync(
            world_vx, world_vy, z_target, 0.1,
            airsim.DrivetrainType.MaxDegreeOfFreedom,
            airsim.YawMode(True, self.yaw),
        ).join()

    def enter_keyboard_control(self):
        print("Keyboard Control mode active.")
        print("W/S: forward/back | A/D: left/right | Z/X: z-axis | Q/E: yaw")
        print("H: hover | T: takeoff | L: land | R: reset | Space: help | ?: telemetry | ESC: exit")

        self._start_listener()
        self.client.enableApiControl(True)
        previous_keys: set = set()

        while self._listener.running:
            keys_set = set(self._pressed_keys)

            if Key.esc in keys_set:
                self._stop_listener()
                break

            self._handle_oneshot_keys(previous_keys)
            self._process_movement()
            previous_keys = keys_set

        self.client.hoverAsync().join()

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    def close_connection(self):
        for fn in (
            lambda: self.client.hoverAsync().join(),
            lambda: self.client.armDisarm(False),
            lambda: self.client.enableApiControl(False),
        ):
            try:
                fn()
            except Exception:
                pass

    def print_stats(self):
        for label, getter in [
            ("state", self.client.getMultirotorState),
            ("imu_data", self.client.getImuData),
            ("barometer_data", self.client.getBarometerData),
            ("magnetometer_data", self.client.getMagnetometerData),
            ("gps_data", self.client.getGpsData),
        ]:
            print(f"{label}: {pprint.pformat(getter())}")

    def clear_terminal(self):
        """Clears the terminal screen."""
        os.system('cls' if os.name == 'nt' else 'clear')

    def show_help(self):
        """Shows keyboard controls supported."""
        print("""
        Keyboard Control:
           [Q] Turn Left    [W] Forward    [E] Turn Right
           [A] Move Left    [S] Backward   [D] Move Right
           [Z] Move Up
           [X] Move Down           
           ----------------------------------------------
           [H]  Hover
           [T]  Takeoff / hover if already flying
           [L]  Land in place (current x/y position)
           [R]  Reset simulation
           [Space] = clear screen, show this help, and restart keyboard control state
           [?] = Get drone telemetry
           [ESC] = end control script and release AirSim control
        """)

    def run(self):
        self.show_help()
        try:
            self.enter_keyboard_control()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            self._stop_listener()
            self.close_connection()
            print("Control script ended and AirSim connection released.")


if __name__ == '__main__':
    controller = SimpleTerminalController(maxmin_velocity=20)
    controller.run()
