In order to have a version history of Airsim settings, the default directory containing the `settings.json` file is linked to a folder within the repository.

This command must be run as an administrator in a PowerShell terminal, with the working directory set to the root of the repository.

``` PowerShell
New-Item -ItemType Junction -Path ".\airsim-settings" -Value "$env:USERPROFILE\OneDrive\Documents\AirSim"
```
