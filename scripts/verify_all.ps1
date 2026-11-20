# Every check in one place. Run from anywhere:
#
#   powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1            # the CPU checks (about a minute)
#   powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1 -Unreal    # also build the editor and run the parity gate
#   powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1 -Only parity
#
# There is no unit-test suite; these are the tests. Nothing here assumes a drive letter or a working directory:
# every path is resolved from this script's own location.

[CmdletBinding()]
param(
    [switch]$Unreal,          # also build the editor and run the Unreal parity gate
    [string]$Only = ""        # run one group: salvage | contract | brains | race | parity
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
    Step "brains" "Matt's brain reproduces his training run and passes his rungs" { & uv @Py human_check.py --creature matt }
    Step "brains" "The stroller's brain passes its ladder (hold, straight, turns, reverse, 100 race-range runs)" { & uv @Py stroller/sim.py ladder }
    Step "race" "Rules self test: tactics (pass, avoid, block, hold a pass) and the yellow flag" { & uv @Py selftest.py }
    Step "race" "Reference races: Planar Sprint (Blue + Matt, a flip, Matt flipped alone), Flat Oval 2 laps, with the handicap and the contact gate" {
        & uv @Py race.py planar_sprint --seed 1
        if ($LASTEXITCODE -eq 0) { & uv @Py race.py planar_sprint --seed 1 --flip-at 20 }
        if ($LASTEXITCODE -eq 0) { & uv @Py race.py planar_sprint --seed 1 --racers matt --flip-at 20 }
        if ($LASTEXITCODE -eq 0) { & uv @Py race.py flat_oval --seed 1 --laps 2 }
        if ($LASTEXITCODE -eq 0) { & uv @Py race.py flat_oval --seed 3 --laps 2 --handicap --contact-gate }
    }
    if ($Unreal -or $Only -eq "parity") {
        Step "parity" "Editor build" {
            & (Join-Path $UeRoot "Engine\Build\BatchFiles\Build.bat") PoRaceUnrealEditor Win64 Development `
                -Project="$(Join-Path $Root 'PoRaceUnreal.uproject')" -WaitMutex -NoHotReloadFromIDE | Select-Object -Last 15
        }
        Step "parity" "Unreal moves the Go2 as MuJoCo does (hold, replay, policy)" { & uv @Py parity_check.py run }
        Step "parity" "The screens: menu and race checks, layout at 16:9 and a portrait phone (needs a display)" {
            $ue = Join-Path $UeRoot "Engine\Binaries\Win64\UnrealEditor.exe"
            $fails = 0
            foreach ($r in @(@(1280, 720), @(540, 1170))) {
                $out = & $ue (Join-Path $Root "PoRaceUnreal.uproject") -game -windowed "-ResX=$($r[0])" "-ResY=$($r[1])" -ForceRes -unattended -nosplash -nosound `
                    -RaceUiTest -AutoStart=1 -RaceLimit=4 -stdout -FullStdOutLogOutput | Out-String
                $out -split "`n" | Where-Object { $_ -match "\[Check\]|RaceUiTest\]" } | ForEach-Object { $_ -replace '^\[[^\]]*\]\[[^\]]*\]', '' }
                if ($out -notmatch "RaceUiTest\] done at the results card: 0 check failures") { $fails++ }
            }
            $global:LASTEXITCODE = $fails
        }
        Step "parity" "Unreal races match the reference race (Planar Sprint seeds 1-5, contact gate; result, events, contact audit, self test)" {
            & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts/regress.ps1") -Track planar_sprint -Seeds "1,2,3,4,5" -ContactGate
        }
        Step "parity" "Unreal handicap races match the reference race (Flat Oval 2 laps, seeds 1-5)" {
            & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts/regress.ps1") -Track flat_oval -Laps 2 -Seeds "1,2,3,4,5" -Handicap -ContactGate
        }
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
