# Clone, patch and build the URLab plugin. Plugins/UnrealRoboticsLab is NOT tracked in this repo (owner decision,
# commit ca8af3d: it is its own git repo, ~2.3 GB with build output); this script recreates it from upstream plus
# this repo's patch. Safe to re-run: skips the clone and patch when the plugin folder already exists.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_urlab.ps1
#
# URLab's own changes for this game live in Plugins/urlab_porace.patch (git format-patch against $UrlabBase below).
# After changing the plugin: commit inside Plugins/UnrealRoboticsLab, then
#   git -C Plugins/UnrealRoboticsLab format-patch <UrlabBase> --stdout > Plugins/urlab_porace.patch
$ErrorActionPreference = 'Stop'
$UrlabBase = 'efbc5e2'   # upstream commit the patch applies to
$root   = Split-Path -Parent $PSScriptRoot
$plugin = Join-Path $root 'Plugins/UnrealRoboticsLab'
$patch  = Join-Path $root 'Plugins/urlab_porace.patch'

if (-not (Test-Path $plugin)) {
    git clone https://github.com/URLab-Sim/UnrealRoboticsLab $plugin
    if ($LASTEXITCODE) { throw 'git clone failed' }
    git -C $plugin checkout -q $UrlabBase
    git -C $plugin -c user.name=setup_urlab -c user.email=setup_urlab@localhost am $patch
    if ($LASTEXITCODE) { throw 'git am of Plugins/urlab_porace.patch failed' }
    git -C $plugin submodule update --init --recursive   # the patch moves MuJoCo's gitlink to 4.0.0
    if ($LASTEXITCODE) { throw 'submodule update failed' }
}

# CoACD's build.ps1 hard-codes the "Visual Studio 17 2022" CMake generator; on a machine with only VS 2026 use that.
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$coacd   = Join-Path $plugin 'third_party/CoACD/build.ps1'
if ((Test-Path $vswhere) -and -not (& $vswhere -version '[17.0,18.0)' -property installationPath) -and
    (& $vswhere -version '[18.0,19.0)' -property installationPath)) {
    (Get-Content -Raw $coacd).Replace('"Visual Studio 17 2022"', '"Visual Studio 18 2026"') | Set-Content -NoNewline $coacd
}

# build_all.ps1 uses relative paths: it must run from its own folder. Builds CoACD, MuJoCo and libzmq.
Push-Location (Join-Path $plugin 'third_party')
try { powershell -ExecutionPolicy Bypass -File .\build_all.ps1 } finally { Pop-Location }

# URLab's MJCF importer preprocesses meshes with the engine's bundled Python and asks (a dialog) for these packages and
# for a Python path on its first import; under -unattended that dialog cancels the import. Install the packages and
# store the path (in the plugin's untracked Config/LocalUnrealRoboticsLab.ini), so the dialog never shows.
$uePython = Join-Path $(if ($env:UE_ROOT) { $env:UE_ROOT } else { 'C:\Program Files\Epic Games\UE_5.8' }) 'Engine\Binaries\ThirdParty\Python3\Win64\python.exe'
if (Test-Path $uePython) {
    & $uePython -m pip install --disable-pip-version-check -q trimesh numpy scipy networkx Pillow
    $ini = Join-Path $plugin 'Config/LocalUnrealRoboticsLab.ini'
    [IO.File]::WriteAllText($ini, "[PythonSettings]`nPythonPath=$uePython`n")
    Write-Host "URLab Python: packages installed, path stored in $ini"
} else {
    Write-Warning "UE 5.8 bundled Python not found at ${uePython} (set UE_ROOT): MJCF imports in commandlets will cancel on the Python dialog"
}
