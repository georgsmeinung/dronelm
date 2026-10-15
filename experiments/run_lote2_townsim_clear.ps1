# Corrida productiva v4 - Lote 2: townsim_clear
# El diseno (celdas, semillas, presupuesto, plan de ruta) esta en run_lotes.ps1 (misma carpeta);
# este script solo lo llama con el lote 2. Usa el python de airsimenv: no hace falta activarlo.
# Antes de correr: arbol commiteado y el nivel de UE del escenario abierto.
#   -Pilot       piloto slm:depth semilla 99 (revisar antes del lote)
#   -Resume      saltea las corridas validas ya hechas con el mismo code_version
#   -SeedJitter  arranca desde start_pose del manifiesto con jitter por semilla (+-1.5 m, +-10 grados)

param(
    [switch]$Pilot,
    [switch]$Resume,
    [switch]$SeedJitter,
    [switch]$NoVideo
)

$ErrorActionPreference = "Stop"
$Launcher = Join-Path $PSScriptRoot "run_lotes.ps1"
# Resultados en airsim-runs/produccion/v4/ (fuera de git).
& $Launcher -Lotes 2 @PSBoundParameters
