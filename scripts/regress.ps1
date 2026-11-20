# Race regression: Unreal races for a set of seeds, each checked against the Python reference race.
#
#   powershell -ExecutionPolicy Bypass -File scripts\regress.ps1 [-Track planar_sprint] [-Seeds "1,2,3,4,5"] [-Racers blue,matt]
#       [-Laps 2] [-FlipAt 20 [-FlipCount 2]] [-NoTactics] [-Handicap] [-YellowFlag] [-ContactGate] [-Parallel 3]
#
# Per seed:
#   Unreal      UnrealEditor-Cmd -game -nullrhi -RaceTest (the level's checks gate it: exit 3 on a failed check)
#   exact       Python on the model Unreal ran (Saved/PoRace/model_bound_<track>.mjb): the result line, the events (passes,
#               yellow flags) and the contact audit must be identical
#   self test   the tactics and yellow-flag rules without physics (-RaceSelfTest vs training/selftest.py): identical lines
#   reference   Python on the track file (training/assets/tracks/<track>.xml): finish times within 1 %
#               (URLab simplifies the drawn meshes, which reorders contacts at rounding level; docs/20261110/slice2.md)
# Writes Saved/PoRace/regress_<track>.json and prints a table. Exit 1 if any seed fails.

[CmdletBinding()]
param(
    [string]$Track = "planar_sprint",
    [string]$Seeds = "1,2,3,4,5",   # text: "powershell -File" passes 1,2,3 as one argument
    [double]$FlipAt = -1,
    [int]$FlipCount = 1,
    [switch]$NoTactics,
    [switch]$Handicap,
    [switch]$YellowFlag,
    [switch]$ContactGate,
    [string]$Racers = "",           # "blue,matt": who is on the grid (default every racer of the track model)
    [int]$Laps = 0,                 # 0: the track's default
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
$Tag = if ($Racers) { "_" + ($Racers -replace ",", "-") } else { "" }
$Extra = @()   # the same race for Python
if ($FlipAt -ge 0) { $Extra += @("--flip-at", "$FlipAt") }
if ($Racers) { $Extra += @("--racers", $Racers) }
if ($Laps -gt 0) { $Extra += @("--laps", "$Laps") }
if ($FlipAt -ge 0) { $Tag += "_flip" }
if ($FlipCount -gt 1) { $Extra += @("--flip-count", "$FlipCount") }
if ($NoTactics) { $Extra += "--no-tactics"; $Tag += "_notactics" }
if ($Handicap) { $Extra += "--handicap"; $Tag += "_handicap" }
if ($YellowFlag) { $Extra += "--yellow-flag" }
if ($ContactGate) { $Extra += "--contact-gate" }

function RaceLine([string]$Text) {
    $m = [regex]::Match($Text, "\[Race\] ((FINISHED|CALLED|DNF) map=.*)")
    if ($m.Success) { return $m.Groups[1].Value.Trim() } else { return $null }
}
function Tagged([string]$Text, [string]$Name) {   # every "[Name] ..." line, joined
    return (@([regex]::Matches($Text, "\[$Name\] ([^\r\n]*)") | ForEach-Object { $_.Groups[1].Value.Trim() }) -join "`n")
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
    $log = Join-Path $Out "ue_${Track}${Tag}_$s.log"
    $ueArgs = @("`"$Project`"", $Level, "-game", "-nullrhi", "-unattended", "-nosplash", "-nosound", "-RaceTest", "-Seed=$s", "-stdout", "-FullStdOutLogOutput")
    if ($FlipAt -ge 0) { $ueArgs += "-RaceFlipAt=$FlipAt" }
    if ($Racers) { $ueArgs += "-Racers=$Racers" }
    if ($Laps -gt 0) { $ueArgs += "-Laps=$Laps" }
    if ($FlipCount -gt 1) { $ueArgs += "-RaceFlipCount=$FlipCount" }
    if ($NoTactics) { $ueArgs += "-NoTactics" }
    if ($Handicap) { $ueArgs += "-Handicap" }
    if ($YellowFlag) { $ueArgs += "-YellowFlag" }
    if ($ContactGate) { $ueArgs += "-ContactGate" }
    if ($s -eq $SeedList[0]) { $ueArgs += "-RaceSelfTest" }
    $p = Start-Process -FilePath $Editor -ArgumentList $ueArgs -RedirectStandardOutput $log -RedirectStandardError "$log.err" -NoNewWindow -PassThru
    $null = $p.Handle   # read the handle now, or ExitCode comes back empty once the process has exited
    $jobs += [pscustomobject]@{ Seed = $s; Process = $p; Log = $log }
    Write-Host "Unreal seed $s started (pid $($p.Id))"
    # Staggered: the next one starts only once this one has compiled its model. URLab writes each mesh to a shared
    # cache file while compiling; three launches at once broke a save, the compile failed and the races hung (Slice 3).
    $wait = Get-Date
    while (-not $p.HasExited -and ((Get-Date) - $wait).TotalSeconds -lt 300) {
        $text = if (Test-Path $log) { Get-Content $log -Raw -ErrorAction SilentlyContinue } else { "" }
        if ($text -match "LogRace: (Display: )?MuJoCo \S+, track|Model compilation failed") { break }
        Start-Sleep -Seconds 2
    }
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
        $exactText = (& uv @Py race.py $Track --seed $s --mjb $Mjb --audit @Extra 2>&1) -join "`n"
        $exact = RaceLine $exactText
        $sameExtras = ((Tagged $text "Event") -eq (Tagged $exactText "Event")) -and ((Tagged $text "ContactAudit") -eq (Tagged $exactText "ContactAudit"))
        if (-not $sameExtras) { Write-Host "  seed ${s}: events / contact audit differ`n    Unreal: $(Tagged $text 'Event') $(Tagged $text 'ContactAudit')`n    Python: $(Tagged $exactText 'Event') $(Tagged $exactText 'ContactAudit')" }
        $ref = RaceLine ((& uv @Py race.py $Track --seed $s @Extra 2>&1) -join "`n")
        $tu = Times $ue; $tr = Times $ref
        $worst = 0.0
        foreach ($a in $tu) { $b = $tr | Where-Object Name -eq $a.Name; if ($b) { $worst = [Math]::Max($worst, [Math]::Abs($a.T - $b.T) / $b.T) } else { $worst = 1.0 } }
        if ($tu.Count -eq 0) { $worst = 1.0 }
        $ok = ($code -eq 0) -and $ue -and ($ue -eq $exact) -and $sameExtras -and ($worst -le $Tolerance) -and -not ($checks | Where-Object { $_ -match "FAIL" })
        if (-not $ok) { $failed++ }
        $rows += [pscustomobject]@{ seed = $s; ok = $ok; exit = $code; unreal = $ue; python_exact = $exact; python_reference = $ref;
                                    exact_match = ($ue -eq $exact); events_audit_match = $sameExtras; events = (Tagged $text "Event");
                                    contact_audit = (Tagged $text "ContactAudit"); contact_gate = (Tagged $text "ContactGate"); worst_time_diff = [Math]::Round($worst, 5); checks = $checks }
    }
    # the self test: the first seed's Unreal run printed it
    $ueSelf = Tagged (Get-Content $jobs[0].Log -Raw) "SelfTest"
    $pySelf = ((Tagged ((& uv @Py selftest.py 2>&1) -join "`n") "SelfTest") -split "`n" | Where-Object { $_ -notmatch "^all passed|FAILED" }) -join "`n"
    $selfOk = $ueSelf -and ($ueSelf -eq $pySelf)
    Write-Host ("self test (tactics, yellow flag): {0} lines, Unreal and Python {1}" -f @($ueSelf -split "`n").Count, $(if ($selfOk) { "identical" } else { "DIFFERENT" })) -ForegroundColor $(if ($selfOk) { "Green" } else { "Red" })
    if (-not $selfOk) { $failed++; Write-Host "  Unreal:`n$ueSelf`n  Python:`n$pySelf" }
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
[IO.File]::WriteAllText((Join-Path $Root "Saved\PoRace\regress_$Track$Tag.json"), ($rows | ConvertTo-Json -Depth 4))
Write-Host ""
if ($failed) { Write-Host "$failed of $($rows.Count) seeds FAILED" -ForegroundColor Red; exit 1 }
Write-Host "all $($rows.Count) seeds passed" -ForegroundColor Green
exit 0
