# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
# Compiles the Python engine sidecar with Nuitka and drops it where Tauri
# expects it: desktop/src-tauri/binaries/workbench-engine-<target-triple>.exe
#
# Usage (from anywhere):  pwsh scripts/build-engine.ps1
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Push-Location $root
try {
    if (-not (Test-Path .venv)) { python -m venv .venv }
    $py = Join-Path $root '.venv\Scripts\python.exe'
    & $py -m pip install --upgrade pip | Out-Null
    & $py -m pip install -e core -e "desktop/engine[build]"
    if ($LASTEXITCODE) { throw 'pip install failed' }

    & $py -m nuitka `
        --onefile `
        --assume-yes-for-downloads `
        --include-package=uvicorn `
        --include-package=winrt `
        --include-package-data=winrt `
        --noinclude-dlls=opencv_videoio_ffmpeg* `
        --nofollow-import-to=watchfiles,uvloop,httptools,websockets,wsproto `
        --product-name="ECG Source List Engine" `
        --file-version=0.1.0 --product-version=0.1.0 `
        --file-description="ECG Source List Python engine" `
        --output-dir=desktop/engine/build `
        --output-filename=workbench-engine.exe `
        desktop/engine/engine_main.py
    if ($LASTEXITCODE) { throw 'Nuitka build failed' }

    $triple = (rustc -vV | Select-String '^host: (.+)$').Matches[0].Groups[1].Value
    $dest = "desktop/src-tauri/binaries/workbench-engine-$triple.exe"
    Copy-Item desktop/engine/build/workbench-engine.exe $dest -Force
    Write-Host "Sidecar ready: $dest"
}
finally { Pop-Location }
