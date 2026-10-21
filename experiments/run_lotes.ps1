<#
Corrida productiva v4: los seis lotes finales de la tesis con el sistema de los caps. 5-8.

Este archivo es la definicion versionada del diseno; los run_loteN_*.ps1 de esta misma carpeta solo lo
llaman con su numero de lote. Los resultados van a airsim-runs/produccion/v4/ (fuera de git: los logs y
videos son muy pesados). Ver README.md de esta carpeta.

Diseno (2026-10-15):
  - Escenarios despejados (lotes 1, 2, 5): 3 brazos, slm:depth fsm:depth reactive (cap. 10 Sec. 10.5.3).
  - Escenarios con obstruccion (lotes 3, 4, 6 = D, E, F de Sec. 10.12.2): se suma fsm:blind (FSM sin barrido),
    que aisla el aporte del barrido con profundidad.
  - Las celdas se alternan dentro de cada semilla, con el orden rotado por semilla (runner.py --cells).
  - 10 semillas por celda: los primeros 60 primos, sin repetir entre lotes.
  - El runner no arranca con el arbol sucio; -Resume saltea las corridas validas ya hechas.

| Lote | Escenario                   | Nivel UE | Celdas | Presupuesto           | Plan de ruta |
|------|-----------------------------|----------|--------|-----------------------|--------------|
| 1    | minisim_clear               | MiniSim  | 3      | 1200 s / 6000 ciclos  | off          |
| 2    | townsim_clear               | TownSim  | 3      | 1200 s / 6000 ciclos  | vlm          |
| 3    | townsim_ini                 | TownSim  | 4      | 1200 s / 6000 ciclos  | vlm          |
| 4    | townsim_calib_cruce_frontal | TownSim  | 4      | 1200 s / 6000 ciclos  | vlm          |
| 5    | citysim_clear               | CitySim  | 3      | 1200 s / 6000 ciclos  | vlm          |
| 6    | citysim_pilot               | CitySim  | 4      | 1200 s / 6000 ciclos  | vlm          |

Presupuesto unico de 1200 s / 6000 ciclos en todos los lotes (2026-10-15): el mismo techo en todos los
escenarios, holgado para que un brazo lento falle por el obstaculo y no por el tiempo (en octubre slm:depth
tardo 430-500 s en citysim_pilot). Las corridas que llegan terminan antes; el techo solo alarga las que se
traban. 6000 ciclos para que, a 5 Hz, el limite que se agote primero sea el de tiempo (Sec. 10.5.4).
El plan de ruta con el VLM (vlm) necesita Ollama en 127.0.0.1:11434 (startOllama.ps1); se usa sobre mapas
registrados con el mundo (citysim_ortho.png, townsim_ortho.png). MiniSim queda en off: su nivel es un plano liso, sin
obstaculos, y no hay mapa que juzgar (crater.png no corresponde al mundo). Correr juntos solo los
lotes del mismo nivel de UE.

Uso (desde cualquier directorio):
  .\run_lotes.ps1 -Lotes 3 -Pilot           # piloto slm:depth semilla 99, a revisar antes del lote
  .\run_lotes.ps1 -Lotes 3,4                # lotes
  .\run_lotes.ps1 -Lotes 3 -Resume          # reanudar
#>
param(
    [Parameter(Mandatory = $true)][ValidateRange(1, 6)][int[]]$Lotes,
    [switch]$Pilot,
    [switch]$Resume,
    [switch]$SeedJitter,
    [switch]$NoVideo,
    [string]$OutRoot = (Join-Path $PSScriptRoot "..\airsim-runs\produccion\v4"),
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

# Python del entorno de los lotes: AIRSIM_ENV_DIR en config/.env (fuente unica). runner.py tambien lo controla
# y no arranca un lote con otro interprete.
if (-not $Python) {
    $envFile = Join-Path $PSScriptRoot "..\config\.env"
    $line = Select-String -Path $envFile -Pattern '^\s*AIRSIM_ENV_DIR\s*=' | Select-Object -First 1
    if (-not $line) { throw "AIRSIM_ENV_DIR no esta definido en $envFile." }
    $envDir = ($line.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    $Python = Join-Path $envDir "python.exe"
}

$OutRoot = [System.IO.Path]::GetFullPath($OutRoot)
$Plans = Join-Path $PSScriptRoot "..\airsim-plan\missions\flightplans"
$Runner = (Resolve-Path (Join-Path $PSScriptRoot "..\airsim-loop\experiments\runner.py")).Path
$Analyze = (Resolve-Path (Join-Path $PSScriptRoot "..\airsim-loop\experiments\analyze_lotes.py")).Path
$Clear = @("slm:depth", "fsm:depth", "reactive")
$Obstructed = @("slm:depth", "fsm:depth", "fsm:blind", "reactive")

$Def = @{
    1 = @{ Scenario = "minisim_clear";               Cells = $Clear;      Seconds = 1200; Cycles = 6000; Route = "off"
           Seeds = 2, 3, 5, 7, 11, 13, 17, 19, 23, 29 }
    2 = @{ Scenario = "townsim_clear";               Cells = $Clear;      Seconds = 1200; Cycles = 6000; Route = "vlm"
           Seeds = 31, 37, 41, 43, 47, 53, 59, 61, 67, 71 }
    3 = @{ Scenario = "townsim_ini";                 Cells = $Obstructed; Seconds = 1200; Cycles = 6000; Route = "vlm"
           Seeds = 73, 79, 83, 89, 97, 101, 103, 107, 109, 113 }
    4 = @{ Scenario = "townsim_calib_cruce_frontal"; Cells = $Obstructed; Seconds = 1200; Cycles = 6000; Route = "vlm"
           Seeds = 127, 131, 137, 139, 149, 151, 157, 163, 167, 173 }
    5 = @{ Scenario = "citysim_clear";               Cells = $Clear;      Seconds = 1200; Cycles = 6000; Route = "vlm"
           Seeds = 179, 181, 191, 193, 197, 199, 211, 223, 227, 229 }
    6 = @{ Scenario = "citysim_pilot";               Cells = $Obstructed; Seconds = 1200; Cycles = 6000; Route = "vlm"
           Seeds = 233, 239, 241, 251, 257, 263, 269, 271, 277, 281 }
}

if (-not (Test-Path $Python)) { throw "No se encontro el python del entorno de los lotes en $Python (AIRSIM_ENV_DIR en config/.env)." }

function Test-Ollama {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", 11434)
        $c.Close()
        return $true
    } catch { return $false }
}

foreach ($lote in $Lotes) {
    $d = $Def[$lote]
    if ($d.Route -eq "vlm" -and -not (Test-Ollama)) {
        throw "Lote ${lote}: el plan de ruta necesita Ollama en 127.0.0.1:11434 (correr startOllama.ps1)."
    }
    $scenario = (Resolve-Path (Join-Path $Plans "$($d.Scenario).json")).Path
    $name = "lote${lote}_$($d.Scenario)"
    if ($Pilot) {
        $outDir = Join-Path $OutRoot "pilotos\$name"
        $runArgs = @("--cells", "slm:depth", "--seeds", "99")
    } else {
        $outDir = Join-Path $OutRoot $name
        $runArgs = @("--cells") + $d.Cells + @("--seeds") + ($d.Seeds | ForEach-Object { "$_" })
    }
    $runArgs = @($Runner, "--scenarios", $scenario) + $runArgs + @(
        "--out-dir", $outDir,
        "--max-seconds", "$($d.Seconds)", "--max-cycles", "$($d.Cycles)",
        "--route-plan", $d.Route
    )
    if ($Resume) { $runArgs += "--skip-existing" }
    if ($SeedJitter) { $runArgs += "--seed-jitter" }
    if ($NoVideo) { $runArgs += "--no-video" }

    New-Item -ItemType Directory -Force $outDir | Out-Null
    $log = Join-Path $outDir ("batch_{0}.log" -f (Get-Date -Format "yyyyMMddTHHmmss"))
    if ($Pilot) { $n = 1; $cellsTxt = "slm:depth (piloto)" } else { $n = $d.Cells.Count * $d.Seeds.Count; $cellsTxt = $d.Cells -join ' ' }
    Write-Host "[v4] lote $lote -> $($d.Scenario) ($n corridas, celdas: $cellsTxt, jitter=$SeedJitter)"
    Write-Host "[v4] $Python $($runArgs -join ' ')"
    # stderr del runner va al log; no debe cortar el script como si fuera un error de PowerShell.
    $ErrorActionPreference = "Continue"
    # -u: sin buffer. Con la salida en un pipe Python la acumula y la consola no mostraba cada corrida.
    & $Python -u @runArgs 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) { throw "Lote ${lote}: runner.py termino con codigo $LASTEXITCODE (ver $log)." }
}
Write-Host "[v4] Listo. Analisis: $Python $Analyze $OutRoot --family 18"
