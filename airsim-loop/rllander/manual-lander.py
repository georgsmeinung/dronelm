# pyrefly: ignore [missing-import]
import gymnasium as gym
import keyboard  # Keyboard input handling
import argparse

parser = argparse.ArgumentParser(description='LunarLander with configurable gravity')
parser.add_argument('--gravity', type=float, default=-10.0, help='Vertical gravity (default: -10.0)')
args = parser.parse_args()

env = gym.make("LunarLander-v3", render_mode="human", gravity=args.gravity)
observation, info = env.reset()

while True:  # Run until user exits
    # Map keyboard inputs to LunarLander actions
    if keyboard.is_pressed('left'):
        action = 1  # Fire left engine
    elif keyboard.is_pressed('right'):
        action = 3  # Fire right engine
    elif keyboard.is_pressed('up'):
        action = 2  # Fire main engine
    else:
        action = 0  # Do nothing
    observation, reward, terminated, truncated, info = env.step(action)

    if terminated or truncated:
        observation, info = env.reset()
    # Exit on ESC key
    if keyboard.is_pressed('esc'):
        print('Exiting...')
        break

env.close()
