In order to have a version history of Airsim settings, the default directory containing the `settings.json` file is linked to a folder within the repository.

This command must be run as an administrator in a PowerShell terminal.

``` PowerShell
New-Item -ItemType Junction -Path "D:\TesisMCD\dronelm\Airsim" -Value "$env:USERPROFILE\OneDrive\Documents\AirSim"
```
