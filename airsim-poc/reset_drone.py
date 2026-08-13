import os
import time
import cosysairsim as airsim
from dotenv import load_dotenv

# Cargar variables de entorno (.env)
load_dotenv()

airsim_ip = os.getenv("AIRSIM_IP", "")
if airsim_ip:
    client = airsim.MultirotorClient(ip=airsim_ip)
else:
    client = airsim.MultirotorClient()

print("Conectando con AirSim...")
client.confirmConnection()

# 1. Habilitar control API y leer estado inicial
client.enableApiControl(True)
print("\n--- Estado Actual del Multirotor ---")
print(client.getMultirotorState())

# 2. Enviar comando de Reset a la simulación
print("\nEnviando comando de RESET a AirSim...")
client.reset()
time.sleep(1.0)

# 3. Liberar el control API limpiamente
client.enableApiControl(False)
print("Reset completado y control API liberado.")
