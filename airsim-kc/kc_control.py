import math
import os
import pprint
import string
import time

from dotenv import load_dotenv
import cosysairsim as airsim
import numpy as np
from pynput.keyboard import Key, KeyCode, Listener

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


class OrbitNavigator:
    def __init__(self, client, radius=2, altitude=10, speed=1, iterations=1, center=[1, 0], snapshots=0):
        self.radius = radius
        self.altitude = altitude
        self.speed = speed
        self.iterations = iterations
        self.snapshots = snapshots
        self.snapshot_delta = None
        self.next_snapshot = None
        self.z = None
        self.snapshot_index = 0
        self.takeoff = False  # whether we did a take off

        if self.snapshots > 0:
            self.snapshot_delta = 360 / self.snapshots

        if self.iterations <= 0:
            self.iterations = 1

        if len(center) != 2:
            raise Exception("Expecting '[x,y]' for the center direction vector")

        # center is just a direction vector, so normalize it to compute the actual cx,cy locations.
        cx = float(center[0])
        cy = float(center[1])
        length = math.sqrt((cx * cx) + (cy * cy))
        cx /= length
        cy /= length
        cx *= self.radius
        cy *= self.radius

        self.client = client
        self.client.confirmConnection()
        self.client.enableApiControl(True)

        self.home = self.client.getMultirotorState().kinematics_estimated.position
        # check that our home position is stable
        start = time.time()
        count = 0
        while count < 100:
            pos = self.client.getMultirotorState().kinematics_estimated.position
            if abs(pos.z_val - self.home.z_val) > 1:
                count = 0
                self.home = pos
                if time.time() - start > 10:
                    print("Drone position is drifting, we are waiting for it to settle down...")
                    start = time.time()
            else:
                count += 1

        self.center = pos
        self.center.x_val += cx
        self.center.y_val += cy

    def start(self):
        print("arming the drone...")
        self.client.armDisarm(True)

        # AirSim uses NED coordinates so negative axis is up.
        start = self.client.getMultirotorState().kinematics_estimated.position

        print("already flying so we will orbit at current altitude {}".format(start.z_val))
        z = start.z_val  # use current altitude then

        print("climbing to position: {},{},{}".format(start.x_val, start.y_val, z))
        self.client.moveToPositionAsync(start.x_val, start.y_val, z, self.speed).join()
        self.z = z

        print("ramping up to speed...")
        count = 0
        self.start_angle = None
        self.next_snapshot = None

        # ramp up time
        ramptime = self.radius / 10
        self.start_time = time.time()

        while count < self.iterations:
            if 0 < self.snapshots <= self.snapshot_index:
                break
            # ramp up to full speed in smooth increments so we don't start too aggressively.
            now = time.time()
            speed = self.speed
            diff = now - self.start_time
            if diff < ramptime:
                print("Ramping up")
                speed = self.speed * diff / ramptime
            elif ramptime > 0:
                print("reached full speed...")
                ramptime = 0

            lookahead_angle = speed / self.radius

            # compute current angle
            pos = self.client.getMultirotorState().kinematics_estimated.position
            dx = pos.x_val - self.center.x_val
            dy = pos.y_val - self.center.y_val
            actual_radius = math.sqrt((dx * dx) + (dy * dy))
            angle_to_center = math.atan2(dy, dx)

            camera_heading = (angle_to_center - math.pi) * 180 / math.pi

            # compute lookahead
            lookahead_x = self.center.x_val + self.radius * math.cos(angle_to_center + lookahead_angle)
            lookahead_y = self.center.y_val + self.radius * math.sin(angle_to_center + lookahead_angle)

            vx = lookahead_x - pos.x_val
            vy = lookahead_y - pos.y_val

            if self.track_orbits(angle_to_center * 180 / math.pi):
                count += 1
                print("completed {} orbits".format(count))

            self.camera_heading = camera_heading
            self.client.moveByVelocityAsync(vx, vy, 0, 1, airsim.DrivetrainType.MaxDegreeOfFreedom,
                                            airsim.YawMode(False, camera_heading))
        self.client.moveToPositionAsync(start.x_val, start.y_val, z, 2).join()

    def track_orbits(self, angle):
        # tracking # of completed orbits is surprisingly tricky to get right in order to handle random wobbles
        # about the starting point.  So we watch for complete 1/2 orbits to avoid that problem.
        if angle < 0:
            angle += 360

        if self.start_angle is None:
            self.start_angle = angle
            if self.snapshot_delta:
                self.next_snapshot = angle + self.snapshot_delta
            self.previous_angle = angle
            self.shifted = False
            self.previous_sign = None
            self.previous_diff = None
            self.quarter = False
            return False

        # now we just have to watch for a smooth crossing from negative diff to positive diff
        if self.previous_angle is None:
            self.previous_angle = angle
            return False

            # ignore the click over from 360 back to 0
        if self.previous_angle > 350 and angle < 10:
            if self.snapshot_delta and self.next_snapshot >= 360:
                self.next_snapshot -= 360
            return False

        diff = self.previous_angle - angle
        crossing = False
        self.previous_angle = angle

        if self.snapshot_delta and angle > self.next_snapshot:
            print("Taking snapshot at angle {}".format(angle))
            self.take_snapshot()
            self.next_snapshot += self.snapshot_delta

        diff = abs(angle - self.start_angle)
        if diff > 45:
            self.quarter = True

        if self.quarter and self.previous_diff is not None and diff != self.previous_diff:
            # watch direction this diff is moving if it switches from shrinking to growing
            # then we passed the starting point.
            direction = self.sign(self.previous_diff - diff)
            if self.previous_sign is None:
                self.previous_sign = direction
            elif self.previous_sign > 0 and direction < 0:
                if diff < 45:
                    self.quarter = False
                    if self.snapshots <= self.snapshot_index + 1:
                        crossing = True
            self.previous_sign = direction
        self.previous_diff = diff

        return crossing

    def take_snapshot(self):
        # first hold our current position so drone doesn't try and keep flying while we take the picture.
        pos = self.client.getMultirotorState().kinematics_estimated.position
        self.client.moveToPositionAsync(pos.x_val, pos.y_val, self.z, 0.5, 10, airsim.DrivetrainType.MaxDegreeOfFreedom,
                                        airsim.YawMode(False, self.camera_heading)).join()
        responses = self.client.simGetImages(
            [airsim.ImageRequest(1, airsim.ImageType.Scene)])  # scene vision image in png format
        response = responses[0]
        filename = "photo_" + str(self.snapshot_index)
        self.snapshot_index += 1
        airsim.write_file(os.path.normpath(filename + '.png'), response.image_data_uint8)
        print("Saved snapshot: {}".format(filename))
        self.start_time = time.time()  # cause smooth ramp up to happen again after photo is taken.

    def sign(self, s):
        if s < 0:
            return -1
        return 1


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
        self.target_z = None

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
        self.target_z = None

    def land(self):
        print("Landing in place...")
        self.client.landAsync().join()
        self.client.armDisarm(False)
        self.target_z = None

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
        self.target_z = None

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
        # In AirSim, Z axis is downwards. Decrease Z to move up, increase to move down.
        return current_z - HEIGHT_STEP if pos else current_z + HEIGHT_STEP

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
        self.target_z = None
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
        
        # Initialize target_z if not set
        if self.target_z is None:
            self.target_z = state.kinematics_estimated.position.z_val

        # Update target_z via keyboard input (X=up, Z=down)
        self.target_z = self._axis_height('x', 'z', self.target_z)

        # Convert body velocity command to world frame
        yaw_rad = self._quaternion_to_yaw(state.kinematics_estimated.orientation)
        world_vx, world_vy = self._body_to_world(self.vx, self.vy, yaw_rad)

        # Dynamic tilt compensation to prevent altitude loss during translation
        h_speed = np.sqrt(world_vx**2 + world_vy**2)
        compensation = 0.15 * h_speed
        z_target = self.target_z - compensation

        self.client.moveByVelocityZAsync(
            world_vx, world_vy, z_target, 0.1,
            airsim.DrivetrainType.MaxDegreeOfFreedom,
            airsim.YawMode(True, self.yaw),
        ).join()

    def enter_keyboard_control(self):
        self.target_z = None
        self._start_listener()
        self.client.enableApiControl(True)
        previous_keys: set = set()

        while self._listener.running:
            keys_set = set(self._pressed_keys)

            if Key.esc in keys_set:
                self._stop_listener()
                self._pressed_keys.clear()  # Flush pressed keys on exit
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
        try:
            state = self.client.getMultirotorState()
            pos = state.kinematics_estimated.position
            vel = state.kinematics_estimated.linear_velocity
            orient = state.kinematics_estimated.orientation
            gps = state.gps_location

            # Convert quaternion to roll, pitch, yaw (in degrees)
            sinr_cosp = 2.0 * (orient.w_val * orient.x_val + orient.y_val * orient.z_val)
            cosr_cosp = 1.0 - 2.0 * (orient.x_val ** 2 + orient.y_val ** 2)
            roll = np.arctan2(sinr_cosp, cosr_cosp) * 180.0 / np.pi

            sinp = 2.0 * (orient.w_val * orient.y_val - orient.z_val * orient.x_val)
            pitch = np.arcsin(np.clip(sinp, -1.0, 1.0)) * 180.0 / np.pi

            siny_cosp = 2.0 * (orient.w_val * orient.z_val + orient.x_val * orient.y_val)
            cosy_cosp = 1.0 - 2.0 * (orient.y_val ** 2 + orient.z_val ** 2)
            yaw = np.arctan2(siny_cosp, cosy_cosp) * 180.0 / np.pi

            # Map landed state to text
            landed_val = getattr(state, 'landed_state', 0)
            if hasattr(airsim, 'LandedState'):
                if landed_val == airsim.LandedState.Landed:
                    landed_str = "Landed"
                elif landed_val == airsim.LandedState.Flying:
                    landed_str = "Flying"
                else:
                    landed_str = f"Unknown ({landed_val})"
            else:
                landed_str = "Flying" if landed_val == 1 else "Landed"

            pos_str = f"({pos.x_val:.2f}, {pos.y_val:.2f}, {pos.z_val:.2f}) m"
            alt_str = f"{-pos.z_val:.2f} m (GPS: {gps.altitude:.2f} m)"
            vel_str = f"({vel.x_val:.2f}, {vel.y_val:.2f}, {vel.z_val:.2f}) m/s"
            speed_val = float(np.sqrt(vel.x_val**2 + vel.y_val**2 + vel.z_val**2))
            speed_str = f"{speed_val:.2f} m/s"
            rpy_str = f"R:{roll:.1f} P:{pitch:.1f} Y:{yaw:.1f}"
            gps_str = f"Lat:{gps.latitude:.6f}, Lon:{gps.longitude:.6f}"

            print("\n+-------------------------------------------------------------+")
            print(f"| {'DRONE TELEMETRY':^59} |")
            print("+---------------------------+---------------------------------+")
            print(f"| {'Parameter':<25} | {'Value':<31} |")
            print("+---------------------------+---------------------------------+")
            print(f"| {'Position (X, Y, Z)':<25} | {pos_str:<31} |")
            print(f"| {'Altitude (Z / GPS)':<25} | {alt_str:<31} |")
            print(f"| {'Velocity (Vx, Vy, Vz)':<25} | {vel_str:<31} |")
            print(f"| {'Speed (magnitude)':<25} | {speed_str:<31} |")
            print(f"| {'Roll / Pitch / Yaw':<25} | {rpy_str:<31} |")
            print(f"| {'Landed State':<25} | {landed_str:<31} |")
            print(f"| {'GPS Location':<25} | {gps_str:<31} |")
            print("+---------------------------+---------------------------------+\n")

        except Exception as e:
            print(f"Error fetching telemetry: {e}")

    def clear_terminal(self):
        """Clears the terminal screen."""
        os.system('cls' if os.name == 'nt' else 'clear')

    def show_help(self):
        """Shows keyboard controls supported."""
        print("""
        Keyboard Control:
           [Q] Turn Left    [W] Forward    [E] Turn Right
           [A] Move Left    [S] Backward   [D] Move Right
           [X] Move Up
           [Z] Move Down           
           ----------------------------------------------
           [H] Hover        [T] Takeoff    [L] Land in place 
           [R] Reset        [Space] = clear screen, show help
           [?] = Get drone telemetry     
           ----------------------------------------------
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
