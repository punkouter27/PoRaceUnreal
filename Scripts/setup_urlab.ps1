# Clone, patch and build the URLab plugin (Plugins/UnrealRoboticsLab is not tracked in this repo).
# Safe to re-run: skips the clone and patch when the plugin folder already exists.
#
#   powershell -ExecutionPolicy Bypass -File Scripts\setup_urlab.ps1
#
# URLab's own changes for this game live in Plugins/urlab_porace.patch (git format-patch against URLAB_BASE below).
# After changing the plugin: commit inside Plugins/UnrealRoboticsLab, then
#   git -C Plugins/UnrealRoboticsLab format-patch <URLAB_BASE> --stdout > Plugins/urlab_porace.patch
$ErrorActionPreference = 'Stop'
$UrlabBase = 'efbc5e2'   # upstream commit the patch applies to
$root   = Split-Path -Parent $PSScriptRoot
$plugin = Join-Path $root 'Plugins/UnrealRoboticsLab'
$patch  = Join-Path $root 'Plugins/urlab_porace.patch'

if (-not (Test-Path $plugin)) {
    git clone https://github.com/URLab-Sim/UnrealRoboticsLab $plugin
    git -C $plugin checkout -q $UrlabBase
    git -C $plugin am $patch
    git -C $plugin submodule update --init --recursive   # the patch moves MuJoCo's gitlink to 4.0.0
}

# build_all.ps1 uses relative paths: it must run from its own folder. Builds CoACD, MuJoCo and libzmq.
Push-Location (Join-Path $plugin 'third_party')
try { powershell -ExecutionPolicy Bypass -File .\build_all.ps1 } finally { Pop-Location }

# URLab's MJCF importer preprocesses meshes with the engine's bundled Python and asks (a dialog) for these packages and
# for a Python path on its first import; under -unattended that dialog cancels the import. Install the packages and
# store the path, so the dialog never shows.
$uePython = 'C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\ThirdParty\Python3\Win64\python.exe'
if (Test-Path $uePython) {
    & $uePython -m pip install --disable-pip-version-check -q trimesh numpy scipy networkx Pillow
    $ini = Join-Path $plugin 'Config/LocalUnrealRoboticsLab.ini'   # untracked with the plugin: rewritten on every clone
    [IO.File]::WriteAllText($ini, "[PythonSettings]`nPythonPath=$uePython`n")
    Write-Host "URLab Python: packages installed, path stored in $ini"
} else {
    Write-Warning "UE 5.8 bundled Python not found at $uePython: MJCF imports in commandlets will cancel on the Python dialog"
}
