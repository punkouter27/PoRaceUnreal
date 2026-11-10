# Every check in one place. Run from anywhere:
#
#   powershell -ExecutionPolicy Bypass -File Scripts\verify_all.ps1            # the CPU checks (about a minute)
#   powershell -ExecutionPolicy Bypass -File Scripts\verify_all.ps1 -Unreal    # also build the editor and run the parity gate
#   powershell -ExecutionPolicy Bypass -File Scripts\verify_all.ps1 -Only parity
#
# There is no unit-test suite; these are the tests. Nothing here assumes a drive letter or a working directory:
# every path is resolved from this script's own location.

[CmdletBinding()]
param(
    [switch]$Unreal,          # also build the editor and run the Unreal parity gate
    [string]$Only = ""        # run one group: salvage | contract | brains | parity
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$UeRoot = if ($env:UE_ROOT) { $env:UE_ROOT } else { "C:\Program Files\Epic Games\UE_5.8" }
$Py = @("run", "--no-project", "--python", "3.12", "--with", "mujoco==4.0.0", "--with", "onnxruntime", "--with", "numpy", "python")

$Results = @()
function Step($Group, $Name, $Script) {
    if ($Only -and $Only -ne $Group) { return }
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host "  $Name" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    $out = & $Script 2>&1 | Out-String
    $code = $LASTEXITCODE
    Write-Host $out
    $script:Results += [pscustomobject]@{ Name = $Name; Code = $code }
    if ($code -ne 0) { Write-Host "  -> FAILED (exit $code)" -ForegroundColor Red } else { Write-Host "  -> PASS" -ForegroundColor Green }
}

Push-Location (Join-Path $Root "training")
try {
    Step "salvage" "Salvaged brains, models and cards load" { & uv @Py (Join-Path $Root "tools\salvage_check.py") }
    Step "contract" "Generated contract files are up to date" { & uv @Py contract.py --check }
    Step "brains" "Go2 brains pass their rungs on this MuJoCo" { & uv @Py version_check.py }
    if ($Unreal -or $Only -eq "parity") {
        Step "parity" "Editor build" {
            & (Join-Path $UeRoot "Engine\Build\BatchFiles\Build.bat") PoRaceUnrealEditor Win64 Development `
                -Project="$(Join-Path $Root 'PoRaceUnreal.uproject')" -WaitMutex -NoHotReloadFromIDE | Select-Object -Last 15
        }
        Step "parity" "Unreal moves the Go2 as MuJoCo does (hold, replay, policy)" { & uv @Py parity_check.py run }
    }
} finally { Pop-Location }

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host "  SUMMARY"
Write-Host ("=" * 72) -ForegroundColor DarkGray
foreach ($r in $Results) {
    $mark = if ($r.Code -eq 0) { "PASS" } else { "FAIL" }
    Write-Host ("  {0,-4}  {1}" -f $mark, $r.Name) -ForegroundColor $(if ($r.Code -eq 0) { "Green" } else { "Red" })
}
$Failed = @($Results | Where-Object { $_.Code -ne 0 })
Write-Host ""
if ($Failed.Count) { Write-Host "  $($Failed.Count) of $($Results.Count) checks FAILED." -ForegroundColor Red; exit 1 }
Write-Host "  all $($Results.Count) checks passed." -ForegroundColor Green
exit 0
