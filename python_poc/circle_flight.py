import math
import time

# This would use the drone-control MCP tools through the proper client
# For now, creating the coordinate sequence

def generate_circle_points(center_x, center_y, altitude, radius, num_points=12):
    """Generate points for a circle in NED coordinates"""
    points = []
    for i in range(num_points):
        angle = (2 * math.pi * i) / num_points
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        points.append((x, y, altitude))
    return points

# Flight parameters
center_x = 0
center_y = 0
altitude = -3  # 3 meters up (negative is up in NED)
radius = 5  # 5 meter radius circles
points_per_circle = 12
num_circles = 10

print("Generating flight path for 10 circles...")
print(f"Circle radius: {radius}m, Altitude: {-altitude}m, Points per circle: {points_per_circle}")
print()

all_waypoints = []
for circle_num in range(num_circles):
    circle_points = generate_circle_points(center_x, center_y, altitude, radius, points_per_circle)
    all_waypoints.extend(circle_points)
    print(f"Circle {circle_num + 1}: {len(circle_points)} waypoints")

print(f"\nTotal waypoints: {len(all_waypoints)}")
print("\nFirst few waypoints:")
for i, (x, y, z) in enumerate(all_waypoints[:5]):
    print(f"  {i+1}. x={x:.2f}, y={y:.2f}, z={z:.2f}")
