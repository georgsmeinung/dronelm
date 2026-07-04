# Link Settings Folder

By default, the AirSim settings folder is located in current user Documents directory: [1, 2] 

* Windows: C:\Users\<Your-Username>\Documents\AirSim
* Linux: ~/Documents/AirSim [1] 

Inside this folder, AirSim automatically generates the master configuration file named settings.json the first time you run a simulation. It is also the default directory where flight recordings and telemetry logs are saved. [1, 3] 
Would you like a baseline settings.json template for a drone or a car simulation to place inside that folder?

[1] [https://microsoft.github.io](https://microsoft.github.io/AirSim/settings/)
[2] [https://github.com](https://github.com/catec/nvs_trajectory_guided_ros/blob/master/airsim_datasets_generator/README.md)
[3] [https://microsoft.github.io](https://microsoft.github.io/AirSim/modify_recording_data/)

In order to have a version history of Airsim settings, the default directory containing the `settings.json` file is linked to a folder within the repository.

This command must be run as an administrator in a PowerShell terminal, with the working directory set to the root of the repository. In this case, the Documents folder is backed up to OneDrive, so the link command is:

``` PowerShell
New-Item -ItemType Junction -Path ".\airsim-settings" -Value "$env:USERPROFILE\OneDrive\Documents\AirSim"
```
