# Corrida primaria: 2 escenarios × 3 brazos × 1 semilla = 6 corridas
# Ejecutar secuencialmente para evitar conflictos con AirSim

$scenarios = @("missions/manhattan_a.json", "missions/manhattan_b.json")
$arms = @("reactive", "fsm", "slm")
$seed = 1
$outDir = "runs/tesis_primary"
$maxCycles = 2000
$maxSeconds = 300

$results = @()
$total = $scenarios.Count * $arms.Count
$current = 0

foreach ($scenario in $scenarios) {
    foreach ($arm in $arms) {
        $current++
        $scenarioName = [System.IO.Path]::GetFileNameWithoutExtension($scenario)
        Write-Host "[$current/$total] $scenarioName × $arm × seed=$seed..." -NoNewline

        $t0 = Get-Date
        & .venv/Scripts/python experiments/runner.py --_single `
            --scenario $scenario `
            --arm $arm `
            --seed $seed `
            --out-dir $outDir `
            --max-cycles $maxCycles `
            --max-seconds $maxSeconds `
            2>&1 | Where-Object { $_ -match "summary:" } | ForEach-Object {
            $match = $_ -match '"success": (true|false)'
            if ($match) {
                $success = $matches[1]
                $cycles = [regex]::Match($_, '"cycles": (\d+)').Groups[1].Value
                $duration = [regex]::Match($_, '"duration_s": ([\d.]+)').Groups[1].Value
                $collisions = [regex]::Match($_, '"collisions": (\d+)').Groups[1].Value
                Write-Host " ✓ ($duration s, $cycles ciclos, colisiones=$collisions)"

                $results += @{
                    scenario = $scenarioName
                    arm = $arm
                    seed = $seed
                    success = $success
                    duration_s = $duration
                    cycles = $cycles
                    collisions = $collisions
                }
            }
        }
    }
}

Write-Host "`n=== RESULTADOS PRIMARIOS ===" -ForegroundColor Green
Write-Host "Escenario          Brazo           Duración (s)  Ciclos  Colisiones" -ForegroundColor Yellow
Write-Host "-----------------------------------------------------------------------"

foreach ($r in $results) {
    Write-Host "$($r.scenario -padright 18) $($r.arm -padright 15) $($r.duration_s -padright 12) $($r.cycles -padright 7) $($r.collisions)"
}

Write-Host "`n✓ Corrida primaria completada. Directorio: $outDir"
