# Build script: informe/ -> docs/informe/ (HTML + PDF)
# Ejecutar desde cualquier directorio; usa $PSScriptRoot para ubicar la raiz del repo.
# Uso: .\informe\build.ps1              (HTML + PDF)
#      .\informe\build.ps1 -HtmlOnly    (solo HTML)

param(
    [switch]$HtmlOnly,
    [int]$Port = 8765
)

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$chrome   = "C:\Program Files\Google\Chrome\Application\chrome.exe"
Push-Location $repoRoot

function Wait-Port {
    param([int]$P, [int]$MaxSeconds = 12)
    for ($i = 0; $i -lt ($MaxSeconds * 2); $i++) {
        Start-Sleep -Milliseconds 500
        $tcp = New-Object System.Net.Sockets.TcpClient
        try {
            $tcp.Connect("127.0.0.1", $P)
            $tcp.Close()
            return $true
        } catch { }
    }
    return $false
}

try {
    # ------------------------------------------------------------------ HTML --
    Write-Host "`n[1/2] Building HTML (MkDocs Material)..." -ForegroundColor Cyan
    mkdocs build --config-file mkdocs.yml
    if ($LASTEXITCODE -ne 0) { throw "mkdocs build failed (exit $LASTEXITCODE)" }
    Write-Host "      OK -> docs\informe\" -ForegroundColor Green

    if ($HtmlOnly) { return }

    # ------------------------------------------------------------------ PDF ---
    Write-Host "`n[2/2] Generating PDF via Chrome headless..." -ForegroundColor Cyan

    if (-not (Test-Path $chrome)) {
        Write-Warning "Chrome not found at '$chrome' — skipping PDF. Instala Chrome o ajusta la ruta."
        return
    }

    $docsDir  = Join-Path $repoRoot "docs"
    $printUrl = "http://localhost:$Port/informe/print_page.html"
    $pdfOut   = Join-Path $repoRoot "docs\informe\tesis-dronelm.pdf"

    # Levantar HTTP server con Start-Process (no Start-Job, mas confiable)
    Write-Host "      Starting HTTP server on port $Port..." -ForegroundColor Gray
    $server = Start-Process `
        -FilePath "python" `
        -ArgumentList "-m http.server $Port --bind 127.0.0.1" `
        -WorkingDirectory $docsDir `
        -NoNewWindow `
        -PassThru

    # Esperar a que el puerto este escuchando
    $ready = Wait-Port -P $Port -MaxSeconds 12
    if (-not $ready) {
        Write-Warning "HTTP server (port $Port) no respondio — abortando PDF."
        $server | Stop-Process -Force -ErrorAction SilentlyContinue
        return
    }
    Write-Host "      Server ready. Printing $printUrl ..." -ForegroundColor Gray

    # Chrome headless: imprime desde HTTP (no file://) para que cargue todo el CSS/JS
    & $chrome `
        --headless=new `
        --disable-gpu `
        "--print-to-pdf=$pdfOut" `
        --no-pdf-header-footer `
        --run-all-compositor-stages-before-draw `
        --disable-extensions `
        --no-sandbox `
        --print-to-pdf-no-header `
        $printUrl

    $chromeExit = $LASTEXITCODE

    # Parar HTTP server
    $server | Stop-Process -Force -ErrorAction SilentlyContinue

    if ($chromeExit -ne 0) {
        Write-Warning "Chrome exited with code $chromeExit"
    } else {
        $sizeKB = [math]::Round((Get-Item $pdfOut).Length / 1KB)
        Write-Host "      OK -> docs\informe\tesis-dronelm.pdf ($sizeKB KB)" -ForegroundColor Green
    }

} finally {
    Pop-Location
    Write-Host ""
}
