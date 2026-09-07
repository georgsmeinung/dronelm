# Build script: informe/ -> docs/informe/ (HTML + PDF)
# Ejecutar desde cualquier directorio; usa $PSScriptRoot para ubicar la raiz del repo.
# Uso: .\informe\build.ps1              (HTML + PDF)
#      .\informe\build.ps1 -HtmlOnly    (solo HTML)

param(
    [switch]$HtmlOnly,
    [int]$Port = 8765
)

$repoRoot  = (Resolve-Path "$PSScriptRoot\..").Path
$makePdf   = Join-Path $repoRoot "informe\make_pdf.py"
Push-Location $repoRoot

try {
    # ------------------------------------------------------------------ HTML --
    Write-Host "`n[1/2] Building HTML (MkDocs Material)..." -ForegroundColor Cyan
    mkdocs build --config-file mkdocs.yml
    if ($LASTEXITCODE -ne 0) { throw "mkdocs build failed (exit $LASTEXITCODE)" }
    Write-Host "      OK -> docs\informe\" -ForegroundColor Green

    if ($HtmlOnly) { return }

    # ------------------------------------------------------------------ PDF ---
    Write-Host "`n[2/2] Generating PDF (Playwright + Chromium)..." -ForegroundColor Cyan
    python $makePdf --port $Port
    if ($LASTEXITCODE -ne 0) { Write-Warning "PDF generation failed (exit $LASTEXITCODE)" }
    else {
        $pdf = Join-Path $repoRoot "docs\informe\tesis-dronelm.pdf"
        if (Test-Path $pdf) {
            $kb = [math]::Round((Get-Item $pdf).Length / 1KB)
            Write-Host "      OK -> docs\informe\tesis-dronelm.pdf ($kb KB)" -ForegroundColor Green
        }
    }

} finally {
    Pop-Location
    Write-Host ""
}
