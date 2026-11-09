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
    npx tauri build; if ($LASTEXITCODE) { throw 'tauri build failed' }
}
finally { Pop-Location }

Get-ChildItem (Join-Path $root 'desktop/src-tauri/target/release/bundle') -Recurse -Include *.exe, *.msi |
    ForEach-Object { Write-Host "Built: $($_.FullName)" }
