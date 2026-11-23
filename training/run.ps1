# PoRace trainer launcher. Usage (from repo root):
#   powershell -File training\run.ps1 -Gpu train.py --env joystick --num_envs 4096 --logdir runs/r1 --restore runs/r1/checkpoints
#   powershell -File training\run.ps1 eval.py --rung r1 --params runs/r1/params.pkl
# --init          : reaps child processes so a hung run can be stopped (a zombie cost a Docker restart on 2026-10-07)
# --log-driver none: Warp prints a solver warning per step; do not let it fill the container log
# --name          : fixed names so a run can be found and stopped
param([switch]$Gpu, [string]$Name = "", [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$root = Split-Path -Parent $PSScriptRoot
$a = @("run", "--rm", "--init", "--log-driver", "none",
       "-v", "$root\training:/work", "-v", "$root\docs:/docs", "-v", "$root\Assets:/assets")
if ($Name) { $a += @("--name", $Name) }
if ($Gpu) { $a += @("--gpus", "all") } else { $a += @("-e", "JAX_PLATFORMS=cpu") }
$a += @("porace-trainer", "python") + $Rest
# A train.py run is recorded in the training runs grid when the container exits (finished, stopped or crashed):
# benchmark/runs.py, with this host's Python, notes the machine (Windows', not the container's), the commit and how
# it ended, and rebuilds training\runs\runs.html. That step can never fail or change the run.
$train = $Rest.Count -gt 0 -and $Rest[0] -match '(^|[/\\])train\.py$'
$started = Get-Date
$code = $null
try {
    & docker @a 2>&1 | Where-Object { $_ -notmatch 'iterations limit reached|To disable the print|^\s*$|CUDA|NVIDIA|container image|nvidia.com|license|By pulling|convenience' }
    $code = $LASTEXITCODE
} finally {
    if ($train) {
        try {
            $runs = Join-Path $root 'training\runs'
            $logdir = $null
            for ($i = 0; $i -lt $Rest.Count; $i++) {
                if ($Rest[$i] -eq '--logdir' -and $i + 1 -lt $Rest.Count) { $logdir = $Rest[$i + 1] }
                elseif ($Rest[$i] -like '--logdir=*') { $logdir = $Rest[$i].Substring(9) }
            }
            $run = if ($logdir) {
                if ($logdir -match '^(\./)?runs[/\\](.+)$') { $Matches[2].TrimEnd('/', '\') }
            } else {  # train.py's default logdir runs/<env>-<time>: the run folder this session created
                Get-ChildItem $runs -Directory -ErrorAction SilentlyContinue |
                    Where-Object { (Test-Path (Join-Path $_.FullName 'ppo_params.json')) -and
                        (Get-Item (Join-Path $_.FullName 'ppo_params.json')).LastWriteTime -ge $started } |
                    Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty Name
            }
            if ($run) {
                $ended = if ($null -eq $code) { 'stopped (Ctrl+C)' } else { "exit $code" }
                $py = if (Get-Command uv -ErrorAction SilentlyContinue) { @('uv', 'run', '--no-project', '--python', '3.12', 'python') } else { @('python') }
                $grid = @((Join-Path $root 'benchmark\runs.py'), '--record', $run, '--ended', $ended,
                          '--launcher', 'training/run.ps1', "--args=$(@($Rest | Select-Object -Skip 1) -join ' ')")
                if (-not $Gpu) { $grid += '--device=CPU' }
                $exe = $py[0]; $pre = @($py | Select-Object -Skip 1)
                & $exe @pre @grid 2>&1 | Write-Host
            }
        } catch { Write-Host "runs grid not rebuilt: $_" }
    }
}
exit $code
