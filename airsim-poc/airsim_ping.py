import cosysairsim as airsim
from dotenv import load_dotenv
import os

load_dotenv()

airsim_ip = os.getenv("AIRSIM_IP", "")
if airsim_ip:
    client = airsim.MultirotorClient(ip=airsim_ip)
else:
    client = airsim.MultirotorClient()
client.confirmConnection()
client.enableApiControl(True)
print(client.getMultirotorState())