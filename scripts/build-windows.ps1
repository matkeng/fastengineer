# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
# Full Windows build: Python sidecar -> Vue front end -> Tauri installers.
# Output: desktop/src-tauri/target/release/bundle/{nsis,msi}/
#
# Prereqs: Python 3.11+, Node 20+, Rust (MSVC toolchain), VS Build Tools (C++).
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')

& (Join-Path $PSScriptRoot 'build-engine.ps1')

Push-Location (Join-Path $root 'web')
try { npm ci; if ($LASTEXITCODE) { throw 'web npm ci failed' } } finally { Pop-Location }

Push-Location (Join-Path $root 'desktop')
try {
    npm ci; if ($LASTEXITCODE) { throw 'desktop npm ci failed' }
    # Bundling downloads NSIS/WiX on first use; retry so a transient download error
    # (e.g. an HTTP 504 from GitHub) doesn't fail the whole build.
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        npx tauri build
        if (-not $LASTEXITCODE) { break }
        if ($attempt -eq 3) { throw 'tauri build failed' }
        Write-Host "tauri build failed (attempt $attempt); retrying in $(15 * $attempt) s"
        Start-Sleep -Seconds (15 * $attempt)
    }
}
finally { Pop-Location }

Get-ChildItem (Join-Path $root 'desktop/src-tauri/target/release/bundle') -Recurse -Include *.exe, *.msi |
    ForEach-Object { Write-Host "Built: $($_.FullName)" }

# Portable build: the app exe plus the engine next to it (the shell looks for
# workbench-engine.exe in its own folder). Nothing is installed; needs the
# WebView2 runtime, which Windows 10/11 normally already have.
$version = (Get-Content (Join-Path $root 'desktop/src-tauri/tauri.conf.json') -Raw | ConvertFrom-Json).version
$release = Join-Path $root 'desktop/src-tauri/target/release'
$portable = Join-Path $root "dist/Drawing-Workbench-$version-portable-x64"
if (Test-Path $portable) { Remove-Item $portable -Recurse -Force }
New-Item -ItemType Directory -Path $portable | Out-Null
Copy-Item (Join-Path $release 'drawing-workbench.exe') (Join-Path $portable 'Drawing Workbench.exe')
Copy-Item (Join-Path $release 'workbench-engine.exe') (Join-Path $portable 'workbench-engine.exe')
Copy-Item (Join-Path $root 'samples/*') $portable
Copy-Item (Join-Path $root 'docs/THIRD_PARTY_LICENSES.md') $portable
Copy-Item (Join-Path $root 'LICENSE') (Join-Path $portable 'LICENSE.txt')
@"
Drawing Workbench $version (portable)

Run "Drawing Workbench.exe". Nothing is installed.
Keep workbench-engine.exe in the same folder: it is the Python engine the app starts.

- Windows may warn that the app is unrecognised (it is not code-signed yet):
  click More info, then Run anyway.
- Needs the Microsoft Edge WebView2 Runtime, already present on most
  Windows 10/11 PCs. If the window stays blank, install it from
  https://developer.microsoft.com/microsoft-edge/webview2/
- Drawing Workbench is free software under the GNU AGPL-3.0-only (LICENSE.txt);
  source code: https://github.com/matkeng/fastengineer
- THIRD_PARTY_LICENSES.md lists the open-source components and their licenses.
- pid-sample*.pdf and pid-library.json are the symbol-detection example.
- cable-schedule-sample*.xlsx and mel-sample*.csv are synthetic sample data for
  the Excel query, Compare tables and MEL import tabs.
- Saved MEL imports are kept in %APPDATA%\com.drawingworkbench.poc\workbench.db
- If the engine does not start, see %TEMP%\workbench-engine.log
- For a team: workbench-engine.exe can run on a server for several users at once,
  with a log of who changed what. See "Multi-user" in the project README.
"@ | Set-Content (Join-Path $portable 'README.txt') -Encoding utf8
Compress-Archive -Path "$portable/*" -DestinationPath "$portable.zip" -Force
Write-Host "Built: $portable.zip"

