# Exporta una figura SVG de esta carpeta a PNG (2x) con Chrome headless, en modo claro.
# Uso: .\informe\fig-src\export.ps1 dos_cerebros.svg "2026-1028 dos_cerebros.png"
#      (el PNG queda en informe/, junto a los capitulos)
param(
    [Parameter(Mandatory)] [string] $Svg,
    [Parameter(Mandatory)] [string] $Png
)
$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot $Svg
$out = Join-Path (Split-Path $PSScriptRoot -Parent) $Png
$svgText = Get-Content $src -Raw -Encoding utf8
if ($svgText -notmatch 'width="(\d+)" height="(\d+)"') { throw "El SVG necesita width y height en px" }
$w = $Matches[1]; $h = $Matches[2]

$html = @"
<!doctype html><html lang="es"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+Mono:wght@400;500;700&display=block" rel="stylesheet">
<style>html,body{margin:0;padding:0;background:#fff} svg{display:block}</style>
</head><body>$svgText</body></html>
"@
$tmp = Join-Path $env:TEMP "fig-export-$([guid]::NewGuid().ToString('N')).html"
Set-Content -Path $tmp -Value $html -Encoding utf8

$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
& $chrome --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 `
    --blink-settings=preferredColorScheme=1 --virtual-time-budget=6000 `
    "--window-size=$w,$h" "--screenshot=$out" "file:///$($tmp -replace '\\','/')" 2>&1 |
    Select-String "written"
Remove-Item $tmp
