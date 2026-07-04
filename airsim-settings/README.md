# AirSim Settings

This folder keeps the AirSim / Cosys-AirSim configuration files used by the project and a few reference notes for environment setup.

## What is here

| File | Purpose |
| --- | --- |
| `settings.json` | Active AirSim settings file. In a normal AirSim installation this file lives under `%USERPROFILE%\OneDrive\Documents\AirSim` and can be linked into this repository for version tracking. |
| `settings-default.json` | Baseline Cosys-AirSim settings with the common project defaults. |
| `settings-api-enabled.json` | Minimal configuration that enables the API server and hides the recording UI. |
| `settings-px4.json` | PX4-oriented configuration for multirotor simulation. |
| `settings-old-v1.2.json` | Legacy AirSim v1.2-compatible settings snapshot kept for reference. |
| `link_folders.md` | Notes for creating a junction so the local AirSim settings folder can be tracked in this repo. |
| `unreal_custenv.md` | Unreal Engine setup notes for creating and configuring a custom environment with AirSim. |

## Recommended usage

1. Pick the settings file that matches the simulator mode you want to run.
2. Copy or rename it to `settings.json` in the active AirSim settings directory.
3. Keep this folder in sync with the configuration used by your Unreal project or control scripts.

## Linking the active AirSim settings folder

If you want the active AirSim settings directory to be tracked from this repository, create a junction from the repository folder to the AirSim documents folder.

```powershell
New-Item -ItemType Junction -Path ".\airsim-settings" -Value "$env:USERPROFILE\OneDrive\Documents\AirSim"
```

Run the command from the repository root in an elevated PowerShell session.

## Notes

- The settings files follow the Cosys-AirSim format unless otherwise noted.
- `settings-old-v1.2.json` is preserved only for compatibility and migration checks.
- The Unreal setup notes in `unreal_custenv.md` are useful when this folder is paired with a custom map or packaged environment.