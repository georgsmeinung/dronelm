import cosysairsim as airsim

import numpy as np
import os
import tempfile
import pprint
import cv2
from dotenv import load_dotenv

# connect to the AirSim simulator
load_dotenv()
airsim_ip = os.getenv("AIRSIM_IP", "")
if airsim_ip:
    client = airsim.MultirotorClient(ip=airsim_ip)
else:
    client = airsim.MultirotorClient()
client.confirmConnection()
client.enableApiControl(True)

state = client.getMultirotorState()
s = pprint.pformat(state)
print("state: %s" % s)

imu_data = client.getImuData()
s = pprint.pformat(imu_data)
print("imu_data: %s" % s)

barometer_data = client.getBarometerData()
s = pprint.pformat(barometer_data)
print("barometer_data: %s" % s)

magnetometer_data = client.getMagnetometerData()
s = pprint.pformat(magnetometer_data)
print("magnetometer_data: %s" % s)

gps_data = client.getGpsData()
s = pprint.pformat(gps_data)
print("gps_data: %s" % s)

airsim.wait_key('Press any key to takeoff')
print("Taking off...")
client.armDisarm(True)
client.takeoffAsync().join()

state = client.getMultirotorState()
print("state: %s" % pprint.pformat(state))

airsim.wait_key('Press any key to move vehicle to (-10, 50, -50) at 10 m/s')
client.moveToPositionAsync(-10, 50, -50, 10).join()

client.hoverAsync().join()

state = client.getMultirotorState()
print("state: %s" % pprint.pformat(state))

airsim.wait_key('Press any key to move vehicle to (40, 30, -30) at 10 m/s')
client.moveToPositionAsync(40, 30, -30, 10).join()

client.hoverAsync().join()

state = client.getMultirotorState()
print("state: %s" % pprint.pformat(state))

airsim.wait_key('Press any key to move vehicle to (0, 0, 0) at 7 m/s')
client.moveToPositionAsync(0, 0, 0, 7).join()

client.hoverAsync().join()

state = client.getMultirotorState()
print("state: %s" % pprint.pformat(state))

airsim.wait_key('Press any key to reset to original state')

client.reset()
client.armDisarm(False)

# that's enough fun for now. let's quit cleanly
client.enableApiControl(False)
