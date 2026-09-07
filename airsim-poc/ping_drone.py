import cosysairsim as airsim
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).resolve().parents[1] / "config" / ".env")

airsim_ip = os.getenv("AIRSIM_IP", "")
if airsim_ip:
    client = airsim.MultirotorClient(ip=airsim_ip)
else:
    client = airsim.MultirotorClient()
client.confirmConnection()
client.enableApiControl(True)
print(client.getMultirotorState())