# Race regression: Unreal races for a set of seeds, each checked against the Python reference race.
#
#   powershell -ExecutionPolicy Bypass -File Scripts\regress.ps1 [-Track planar_sprint] [-Seeds 1,2,3,4,5] [-FlipAt 20] [-Parallel 3]
#
# Per seed:
#   Unreal      UnrealEditor-Cmd -game -nullrhi -RaceTest (the level's checks gate it: exit 3 on a failed check)
#   exact       Python on the model Unreal ran (Saved/PoRace/model_bound_<track>.mjb): the result line must be identical
#   reference   Python on the track file (training/assets/tracks/<track>.xml): finish times within 1 %
#               (URLab simplifies the drawn meshes, which reorders contacts at rounding level; docs/20261110/slice2.md)
# Writes Saved/PoRace/regress_<track>.json and prints a table. Exit 1 if any seed fails.

[CmdletBinding()]
param(
    [string]$Track = "planar_sprint",
    [string]$Seeds = "1,2,3,4,5",   # text: "powershell -File" passes 1,2,3 as one argument
    [double]$FlipAt = -1,
    [int]$Parallel = 3,
    [double]$Tolerance = 0.01
)

$ErrorActionPreference = "Stop"
$SeedList = @($Seeds -split "[,\s]+" | Where-Object { $_ } | ForEach-Object { [int]$_ })   # a new name: $Seeds stays [string]
$Root = Split-Path -Parent $PSScriptRoot
$UeRoot = if ($env:UE_ROOT) { $env:UE_ROOT } else { "C:\Program Files\Epic Games\UE_5.8" }
$Editor = Join-Path $UeRoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$Project = Join-Path $Root "PoRaceUnreal.uproject"
$Pascal = (($Track -split "_") | ForEach-Object { $_.Substring(0, 1).ToUpper() + $_.Substring(1) }) -join ""
$Level = "/Game/Levels/L_$Pascal"
$Out = Join-Path $Root "Saved\PoRace\regress"
New-Item -ItemType Directory -Force $Out | Out-Null
$Py = @("run", "--no-project", "--python", "3.12", "--with", "mujoco==4.0.0", "--with", "onnxruntime", "--with", "numpy", "python")

function RaceLine([string]$Text) {
    $m = [regex]::Match($Text, "\[Race\] ((FINISHED|DNF) map=.*)")
    if ($m.Success) { return $m.Groups[1].Value.Trim() } else { return $null }
}
function Times([string]$Line) {
    if (-not $Line) { return @() }
    return [regex]::Matches($Line, "(\w+) (\d+\.\d+)s") | ForEach-Object { [pscustomobject]@{ Name = $_.Groups[1].Value; T = [double]$_.Groups[2].Value } }
}

# 1. Unreal, a few at a time
$t0 = Get-Date
$jobs = @()
foreach ($s in $SeedList) {
    while (@($jobs | Where-Object { -not $_.Process.HasExited }).Count -ge $Parallel) { Start-Sleep -Milliseconds 500 }
    $log = Join-Path $Out "ue_${Track}_$s.log"
    $args = @("`"$Project`"", $Level, "-game", "-nullrhi", "-unattended", "-nosplash", "-nosound", "-RaceTest", "-Seed=$s", "-stdout", "-FullStdOutLogOutput")
    if ($FlipAt -ge 0) { $args += "-RaceFlipAt=$FlipAt" }
    $p = Start-Process -FilePath $Editor -ArgumentList $args -RedirectStandardOutput $log -RedirectStandardError "$log.err" -NoNewWindow -PassThru
    $null = $p.Handle   # read the handle now, or ExitCode comes back empty once the process has exited
    $jobs += [pscustomobject]@{ Seed = $s; Process = $p; Log = $log }
    Write-Host "Unreal seed $s started (pid $($p.Id))"
}
$jobs | ForEach-Object { $_.Process.WaitForExit() }
Write-Host ("Unreal: {0} races in {1:N0} s" -f $SeedList.Count, ((Get-Date) - $t0).TotalSeconds)

# 2. Python, per seed: on Unreal's model (exact) and on the track file (reference)
$Mjb = Join-Path $Root "Saved\PoRace\model_bound_$Track.mjb"
$rows = @()
$failed = 0
Push-Location (Join-Path $Root "training")
try {
    foreach ($j in $jobs) {
        $s = $j.Seed
        $text = Get-Content $j.Log -Raw
        $ue = RaceLine $text
        $code = $j.Process.ExitCode
        $checks = @([regex]::Matches($text, "\[Check\] ([^\r\n]*)") | ForEach-Object { $_.Groups[1].Value })
        $flip = if ($FlipAt -ge 0) { @("--flip-at", "$FlipAt") } else { @() }
        $exact = RaceLine ((& uv @Py race.py $Track --seed $s --mjb $Mjb @flip 2>&1) -join "`n")
        $ref = RaceLine ((& uv @Py race.py $Track --seed $s @flip 2>&1) -join "`n")
        $tu = Times $ue; $tr = Times $ref
        $worst = 0.0
        foreach ($a in $tu) { $b = $tr | Where-Object Name -eq $a.Name; if ($b) { $worst = [Math]::Max($worst, [Math]::Abs($a.T - $b.T) / $b.T) } else { $worst = 1.0 } }
        if ($tu.Count -eq 0) { $worst = 1.0 }
        $ok = ($code -eq 0) -and $ue -and ($ue -eq $exact) -and ($worst -le $Tolerance) -and -not ($checks | Where-Object { $_ -match "FAIL" })
        if (-not $ok) { $failed++ }
        $rows += [pscustomobject]@{ seed = $s; ok = $ok; exit = $code; unreal = $ue; python_exact = $exact; python_reference = $ref;
                                    exact_match = ($ue -eq $exact); worst_time_diff = [Math]::Round($worst, 5); checks = $checks }
    }
} finally { Pop-Location }

# 3. report
Write-Host ""
foreach ($r in $rows) {
    $col = if ($r.ok) { "Green" } else { "Red" }
    $ut = (Times $r.unreal | ForEach-Object { "{0} {1:N2}s" -f $_.Name, $_.T }) -join ", "
    $pt = (Times $r.python_reference | ForEach-Object { "{0:N2}s" -f $_.T }) -join ", "
    Write-Host ("seed {0,-3} {1,-4} exit {2}  Unreal {3}  | Python same model: {4}  | Python track file {5} ({6:P2})  | checks {7}" -f `
        $r.seed, $(if ($r.ok) { "OK" } else { "FAIL" }), $r.exit, $ut, $(if ($r.exact_match) { "identical" } else { "DIFFERENT" }), $pt, $r.worst_time_diff,
        (@($r.checks | Where-Object { $_ -match "OK$" }).Count.ToString() + " OK, " + @($r.checks | Where-Object { $_ -match "FAIL" }).Count + " FAIL")) -ForegroundColor $col
    if (-not $r.exact_match) { Write-Host "    Unreal: $($r.unreal)`n    Python: $($r.python_exact)" }
}
[IO.File]::WriteAllText((Join-Path $Root "Saved\PoRace\regress_$Track.json"), ($rows | ConvertTo-Json -Depth 4))
Write-Host ""
if ($failed) { Write-Host "$failed of $($rows.Count) seeds FAILED" -ForegroundColor Red; exit 1 }
Write-Host "all $($rows.Count) seeds passed" -ForegroundColor Green
exit 0
