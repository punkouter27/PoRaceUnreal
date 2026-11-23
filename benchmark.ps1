# Opens the training Benchmark page (benchmark/page.html) for this repo: one button runs ~10 s of the real training
# loop and records step time, machine and machine load in benchmark/history.json (commit it to compare laptops).
# The trainer runs in the porace-trainer Docker image (training/Dockerfile); the page server needs only Python 3.11+.
# -Run: no page; runs one Benchmark in this console, records it in benchmark/history.json and exits 0 (recorded) or 1.
$ErrorActionPreference = 'Stop'
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $dd = Join-Path $env:ProgramFiles 'Docker/Docker/Docker Desktop.exe'
    if (-not (Test-Path $dd)) { throw 'Docker is not running and Docker Desktop is not installed (the trainer runs in Docker).' }
    Write-Host 'Starting Docker Desktop...'
    Start-Process $dd
    for ($i = 0; $i -lt 60; $i++) { Start-Sleep 5; docker info *> $null; if ($LASTEXITCODE -eq 0) { break } }
}
docker image inspect porace-trainer *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Building the trainer image (docker build -t porace-trainer training; first time only, ~10 min)...'
    docker build -t porace-trainer (Join-Path $PSScriptRoot 'training')
}
uv run --no-project --python 3.12 python (Join-Path $PSScriptRoot 'benchmark/serve.py') @args
exit $LASTEXITCODE
