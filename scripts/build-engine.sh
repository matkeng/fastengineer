#!/usr/bin/env bash
# macOS/Linux equivalent of build-engine.ps1 (for developing the shell off Windows).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -e core -e "desktop/engine[build]"
[ "$(uname)" = Linux ] && .venv/bin/python -m pip install -q patchelf && export PATH="$root/.venv/bin:$PATH"
.venv/bin/python -m nuitka --onefile --assume-yes-for-downloads \
  --include-package=uvicorn \
  --nofollow-import-to=watchfiles,uvloop,httptools,websockets,wsproto,winrt \
  --noinclude-custom-mode=pymupdf.mupdf:bytecode \
  --output-dir=desktop/engine/build --output-filename=workbench-engine \
  desktop/engine/engine_main.py
triple="$(rustc -vV | sed -n 's/^host: //p')"
cp desktop/engine/build/workbench-engine "desktop/src-tauri/binaries/workbench-engine-$triple"
echo "Sidecar ready: desktop/src-tauri/binaries/workbench-engine-$triple"
