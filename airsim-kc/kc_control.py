import os
import pprint
import string

from dotenv import load_dotenv
import cosysairsim as airsim
import numpy as np
from pynput.keyboard import Key, KeyCode

from KeyController import KeyController

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

    def confirm_connection(self):
        self.client.confirmConnection()
        self.client.enableApiControl(True)

    def setup_segmentation_colors(self):
        """
        Find all objects and make them one color
        then find the specific objects and turn them into different colors.
        :return:
        """
        self.set_bg_color(color_id=BG)
        self.change_color("segment_gate", LAND)

    def change_color(self, name, id):
        success = self.client.simSetSegmentationObjectID(name + "[\w]*", id, True)
        # print("Change of color on", name, "=", success)

    def set_bg_color(self, color_id):
        alphabet = list(string.ascii_lowercase)
        for letter in alphabet:
            self.change_color(letter, color_id)

    def takeoff(self):
        state = self.client.getMultirotorState()
        # print("Takeoff received")
        if state.landed_state == airsim.LandedState.Landed:
            self.client.armDisarm(True)
            print("taking off...")
            self.client.takeoffAsync().join()
        else:
            self.client.hoverAsync().join()

    def land(self):
        print("landing in place...")
        self.client.landAsync().join()
        self.client.armDisarm(False)

    def arm(self):
        # print("Arm received")
        self.client.armDisarm(True)

    def disarm(self):
        # print("Disarm received")
        self.client.armDisarm(False)

    def move_to_position(self, args: list):
        # print("Move received")
        if len(args) != 5:
            print("Move needs 5 args")
            return
        self.client.enableApiControl(True)
        print("Move args:", float(args[1]), float(args[2]), float(args[3]), float(args[4]))
        self.client.moveToPositionAsync(x=float(args[1]), y=float(args[2]), z=float(args[3]),
                                        velocity=float(args[4]), drivetrain=airsim.DrivetrainType.ForwardOnly,
                                        yaw_mode=airsim.YawMode(False, 0)).join()
        self.client.hoverAsync().join()
        # print("Moved!")

    def move_on_path(self, args: list):
        # print("MoveOnPath received")
        if len(args) % 3 != 2:
            print("Move needs 3 args per position args")
            return
        # Have to make sure it is enabled:
        self.client.enableApiControl(True)
        iterations = (len(args) - 2) / 3
        path = []
        for i in range(int(iterations)):
            point = airsim.Vector3r(float(args[(i * 3) + 1]),
                                    float(args[(i * 3) + 2]),
                                    float(args[(i * 3) + 3]))
            path.append(point)
            if self.verbatim:
                # print("path point added", str(point))
                pass
        try:
            result = self.client.moveOnPathAsync(path, float(args[-1]), TIMEOUT,
                                                 airsim.DrivetrainType.ForwardOnly, airsim.YawMode(False, 0),
                                                 20,
                                                 1).join()
        except:
            errorType, value, traceback = airsim.sys.exc_info()
            print("moveOnPath threw exception: " + str(value))
            pass
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

    def orbit(self, args):  # name, speed, x,y
        if len(args) < 3:
            # print("need at least speed parameter and iterations")
            return
        if len(args) != 4:  # Name, x,y
            target_x = float(72.38)  # X coordinate of turbine 1
            target_y = float(48.92)  # Y coordinate of turbine 1

            self.client.enableApiControl(True)
            self.client.moveToPositionAsync(x=float(36.33), y=float(24.32), z=-float(17.33),
                                            velocity=2, drivetrain=airsim.DrivetrainType.ForwardOnly,
                                            yaw_mode=airsim.YawMode(False, 0)).join()
            self.client.hoverAsync().join()
            airsim.time.sleep(2)
        else:
            target_x = float(args[3])
            target_y = float(args[4])
        speed = float(args[1])
        iterations = int(args[2])
        for i in range(iterations):
            current_pos = self.client.getMultirotorState().kinematics_estimated.position
            look_at_point = np.array([target_x, target_y])
            current_pos_np = np.array([current_pos.x_val, current_pos.y_val])
            angle = self.lookAt(look_at_point, np.array([1, 0]))
            l = look_at_point - current_pos_np
            radius = np.linalg.norm(l)
            # print("Radius:", radius)
            # Have to make sure it is enabled:
            self.client.enableApiControl(True)
            self.client.rotateToYawAsync(angle, 20, 0).join()
            # print(self.client.getMultirotorState().kinematics_estimated.orientation)

            self.nav = OrbitNavigator(self.client,
                                      radius=radius,
                                      altitude=float(current_pos.z_val),
                                      speed=speed,
                                      iterations=1,
                                      center=l)

            self.nav.start()
            # print("Orbit ", i, "is done, climb to:", current_pos.x_val, current_pos.y_val, current_pos.z_val - radius)
            self.client.moveToPositionAsync(current_pos.x_val, current_pos.y_val, current_pos.z_val - radius, speed,
                                            10).join()

    def lookAt(self, target_pos, current_pos):
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]
        angle = np.arctan2(dy, dx) * 180 / np.math.pi
        return angle

    def handle_key_pressed(self, keys_to_check: list, pressed_keys: list, current_vel: float) -> float:
        new_vel = current_vel
        positive_axis_press = KeyCode.from_char(keys_to_check[0]) in pressed_keys
        negative_axis_press = KeyCode.from_char(keys_to_check[1]) in pressed_keys

        if positive_axis_press and negative_axis_press:
            return new_vel

        if positive_axis_press:
            return round(number=float(np.clip(new_vel + 1, - self.maxmin_vel, self.maxmin_vel)), ndigits=2)

        if negative_axis_press:
            return round(number=float(np.clip(new_vel - 1, - self.maxmin_vel, self.maxmin_vel)), ndigits=2)

        # nothing is pressed, smoothly lowering the value
        return round(number=float(np.clip(new_vel * 0.75, - self.maxmin_vel, self.maxmin_vel)), ndigits=2)

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
    def handle_height(keys_to_check: list, pressed_keys: list, current_height: float) -> float:
        positive_axis_press = KeyCode.from_char(keys_to_check[0]) in pressed_keys
        negative_axis_press = KeyCode.from_char(keys_to_check[1]) in pressed_keys

        if positive_axis_press and negative_axis_press:
            return current_height
        if positive_axis_press:
            return current_height + HEIGHT_STEP
        if negative_axis_press:
            return current_height - HEIGHT_STEP
        return current_height

    @staticmethod
    def body_to_world_velocity(forward_vel: float, right_vel: float, yaw_rad: float) -> tuple[float, float]:
        world_x = (forward_vel * np.cos(yaw_rad)) - (right_vel * np.sin(yaw_rad))
        world_y = (forward_vel * np.sin(yaw_rad)) + (right_vel * np.cos(yaw_rad))
        return world_x, world_y

    @staticmethod
    def quaternion_to_yaw(orientation) -> float:
        # yaw (z-axis rotation) from quaternion
        siny_cosp = 2.0 * ((orientation.w_val * orientation.z_val) + (orientation.x_val * orientation.y_val))
        cosy_cosp = 1.0 - (2.0 * ((orientation.y_val * orientation.y_val) + (orientation.z_val * orientation.z_val)))
        return float(np.arctan2(siny_cosp, cosy_cosp))

    def enter_keyboard_control(self):
        print("Keyboard Control mode active.")
        print("W/S: forward/back | A/D: left/right | Z/X: z-axis | Q/E: yaw")
        print("H: hover | T: takeoff | L: land | R: reset | Space: help | ?: telemetry | ESC: exit")
        kc = KeyController()
        self.client.enableApiControl(True)
        previous_keys = set()
        while kc.listener.running:
            self.client.cancelLastTask()
            self.client.enableApiControl(True)
            keys = kc.get_key_pressed()
            keys_set = set(keys)

            if Key.esc in keys_set:
                kc.stop()
                break

            is_takeoff_pressed = KeyCode.from_char('t') in keys_set
            was_takeoff_pressed = KeyCode.from_char('t') in previous_keys
            if is_takeoff_pressed and not was_takeoff_pressed:
                self.takeoff()

            is_land_pressed = KeyCode.from_char('l') in keys_set
            was_land_pressed = KeyCode.from_char('l') in previous_keys
            if is_land_pressed and not was_land_pressed:
                self.land()

            is_reset_pressed = KeyCode.from_char('r') in keys_set
            was_reset_pressed = KeyCode.from_char('r') in previous_keys
            if is_reset_pressed and not was_reset_pressed:
                self.reset()
                self.client.enableApiControl(True)

            is_state_pressed = KeyCode.from_char('?') in keys_set
            was_state_pressed = KeyCode.from_char('?') in previous_keys
            if is_state_pressed and not was_state_pressed:
                self.print_stats()

            is_space_pressed = Key.space in keys_set
            was_space_pressed = Key.space in previous_keys
            if is_space_pressed and not was_space_pressed:
                self.clear_terminal()
                self.show_help()
                self.client.cancelLastTask()
                self.client.hoverAsync().join()
                self.client.enableApiControl(True)
                self.vx = 0
                self.vy = 0
                self.vz = 0
                self.yaw = 0
                print("Keyboard control restarted.")

            if 'h' in keys:
                self.client.hoverAsync()
            else:
                self.vx = self.handle_key_pressed(keys_to_check=['w', 's'], pressed_keys=keys,
                                                  current_vel=self.vx)
                self.vy = self.handle_key_pressed(keys_to_check=['d', 'a'], pressed_keys=keys,
                                                  current_vel=self.vy)
                self.yaw = self.handle_rotation(keys_to_check=['e', 'q'], pressed_keys=keys)
                # self.vx/self.vy are body-frame commands (forward/right).
                state = self.client.getMultirotorState()
                orientation = state.kinematics_estimated.orientation
                yaw_rad = self.quaternion_to_yaw(orientation)
                world_vx, world_vy = self.body_to_world_velocity(self.vx, self.vy, yaw_rad)
                current_pos = state.kinematics_estimated.position
                z_target = self.handle_height(keys_to_check=['z', 'x'], pressed_keys=keys,
                                              current_height=current_pos.z_val)
                # print("current pos: \n x:{0:.2f}, y:{1:.2f}\n z:{2:.2f}\n".format(current_pos.x_val, current_pos.y_val, current_pos.z_val))

                self.client.moveByVelocityZAsync(world_vx, world_vy, z_target, 0.1, airsim.DrivetrainType.MaxDegreeOfFreedom, airsim.YawMode(True, self.yaw)).join()
            previous_keys = keys_set
            # self.client.moveByVelocityAsync(self.vx, self.vy, self.vz, 0.1, airsim.DrivetrainType.MaxDegreeOfFreedom,
            #                                 airsim.YawMode(True, self.yaw)).join()
            # airsim.time.sleep(0.2)
        self.client.hoverAsync().join()

    def close_connection(self):
        try:
            self.client.hoverAsync().join()
        except Exception:
            pass
        try:
            self.client.armDisarm(False)
        except Exception:
            pass
        try:
            self.client.enableApiControl(False)
        except Exception:
            pass

    def print_stats(self):
        state = self.client.getMultirotorState()
        s = pprint.pformat(state)
        print("state: %s" % s)

        imu_data = self.client.getImuData()
        s = pprint.pformat(imu_data)
        print("imu_data: %s" % s)

        barometer_data = self.client.getBarometerData()
        s = pprint.pformat(barometer_data)
        print("barometer_data: %s" % s)

        magnetometer_data = self.client.getMagnetometerData()
        s = pprint.pformat(magnetometer_data)
        print("magnetometer_data: %s" % s)

        gps_data = self.client.getGpsData()
        s = pprint.pformat(gps_data)
        print("gps_data: %s" % s)

    def clear_terminal(self):
        """Clears the terminal screen."""
        # Check if the operating system is Windows (nt) or POSIX (Linux, macOS, etc.)
        if os.name == 'nt':
            _ = os.system('cls')
        else:
            _ = os.system('clear')
        print("Type 'help' for listing commands.")

    def show_help(self):
        """Shows keyboard controls supported."""
        print("""
        Keyboard Control:
            W = forward (relative to current yaw)
            S = backward (relative to current yaw)
            D = move right (relative to current yaw)
            A = move left (relative to current yaw)
            X = + z-axis (down)
            Z = - z-axis (up)
            E = turn right
            Q = turn left
            H = hover
            T = takeoff / hover if already flying
            L = land in place (current x/y position)
            R = reset simulation
            Space = clear screen, show this help, and restart keyboard control state
            ? = Get drone telemetry
            ESC = end control script and release AirSim control
        """)

    def reset(self):
        print("Resetting simulation")
        self.client.reset()

    def run(self):
        self.show_help()
        try:
            self.enter_keyboard_control()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            self.close_connection()
            print("Control script ended and AirSim connection released.")


if __name__ == '__main__':
    controller = SimpleTerminalController(maxmin_velocity=20)
    controller.run()
