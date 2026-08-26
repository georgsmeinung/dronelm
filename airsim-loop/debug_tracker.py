#!/usr/bin/env python
"""Debug script para entender por qué WP_1 nunca se completa."""
import json
import math
from pathlib import Path

# Cargar misión
with open("missions/manhattan_a.json") as f:
    mission = json.load(f)

waypoints = mission["waypoints"]
print("Waypoints:")
for i, wp in enumerate(waypoints):
    print(f"  WP_{i}: ({wp['x']}, {wp['y']}, {wp['z']})")

# Simular posiciones del log
log_file = Path("runs/tesis_test/manhattan_a/reactive/seed_1.jsonl")
print(f"\nAnalizando {log_file}...")

with open(log_file) as f:
    for i, line in enumerate(f):
        if i >= 5:
            break
        record = json.loads(line)
        pos = record["pos"]
        wp_idx = record["wp_index"]

        # Calcular distancia a cada waypoint
        x, y, z = pos["x"], pos["y"], pos["z"]
        print(f"\nCiclo {record['cycle']}, wp_index={wp_idx}:")
        print(f"  Pos: ({x:.2f}, {y:.2f}, {z:.2f})")

        for j, wp in enumerate(waypoints):
            wx, wy, wz = wp["x"], wp["y"], wp["z"]
            dist = math.sqrt((wx - x)**2 + (wy - y)**2 + (wz - z)**2)
            print(f"  Dist a WP_{j}: {dist:.2f}m {'<-- ACEPTADO' if dist <= 3.5 else ''}")

        print(f"  Logged dist_to_wp_m: {record['dist_to_wp_m']:.2f}m")
