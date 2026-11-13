# Third-party licenses

This report was checked on 2026-11-09 from the installed packages' metadata. It covers:

- the Python wheels, including the binaries bundled inside them;
- `npm ls --omit=dev` for the front end;
- `cargo tree --target x86_64-pc-windows-msvc` for the Tauri shell.

Re-run the checks below after changing dependencies.

**Summary:** everything that ships in the Windows app is under a permissive license (MIT, BSD,
Apache-2.0, ISC, Zlib, PSF, Unicode, FreeType License, …) or a weak, file-level copyleft that
doesn't affect the rest of the app (MPL-2.0, used by 5 unmodified Rust crates). There is no
GPL, AGPL or LGPL code in the shipped app:

- **PyMuPDF was replaced by pypdfium2.** PyMuPDF and MuPDF are AGPL-3.0 (or a commercial
  license); pypdfium2 and PDFium are BSD-3-Clause / Apache-2.0.
- **OpenCV's FFmpeg plug-in is left out of the engine.** The `opencv_videoio_ffmpeg*.dll`
  bundled in the OpenCV wheel is LGPL-2.1. The app only uses OpenCV's image functions, so
  the Windows build passes `--noinclude-dlls=opencv_videoio_ffmpeg*`.
- **NumPy's `libgfortran` is GPL-3.0 with the GCC Runtime Library Exception.** The exception
  allows distributing it with software under any license.

What you need to do when distributing: include the license texts and notices of the
components below with the app (for example in an "About / licenses" file next to the exe).
None of them requires publishing this app's source code. The app's own license (AGPL-3.0,
see below) does.

## Python engine (compiled into `workbench-engine.exe` by Nuitka)

| Package | License | Notes |
|---|---|---|
| CPython runtime | PSF-2.0 | |
| fastapi | MIT | |
| starlette | BSD-3-Clause | |
| uvicorn | BSD-3-Clause | |
| h11, anyio, annotated-types, annotated-doc, typing-inspection | MIT | |
| click, idna | BSD-3-Clause | |
| typing-extensions | PSF-2.0 | |
| opentelemetry-api | Apache-2.0 | dependency of FastAPI |
| pydantic, pydantic-core | MIT | |
| openpyxl, et-xmlfile | MIT | |
| asteval | MIT | |
| numpy | BSD-3-Clause | Bundles OpenBLAS (BSD-3-Clause) and the GCC runtime (GPL-3.0 **with GCC Runtime Library Exception**, permitted in any app). |
| opencv-python-headless | Apache-2.0 | The wheel's FFmpeg plug-in (LGPL-2.1) is **excluded** from the build; see above. |
| pypdfium2 | BSD-3-Clause / Apache-2.0 | PDFium is BSD-3-Clause; bundled libraries are FreeType (FTL), libjpeg-turbo (IJG/BSD), OpenJPEG (BSD-2), LittleCMS (MIT), libpng, zlib, abseil (Apache-2.0), ICU (Unicode). Texts: `pypdfium2-*.dist-info/licenses/`. |
| winrt-runtime, winrt-Windows.* | MIT | Windows only. Python bindings for the OCR engine built into Windows (not shipped by us). |
| Nuitka (build tool) | AGPL-3.0 with the Nuitka Runtime Library Exception | The exception covers the runtime code compiled into the exe, so the exe's license is our choice (AGPL-3.0 for the open core, proprietary for commercial editions). |

Not used any more: **PyMuPDF** (AGPL-3.0); it was removed before release.

## Front end (bundled into the app by Vite)

| Package | License |
|---|---|
| vue, @vue/* | MIT |
| pinia | MIT |
| marked (renders the Help pages) | MIT |
| datatables.net, datatables.net-dt, datatables.net-buttons(-dt) | MIT |
| @tauri-apps/api, @tauri-apps/plugin-dialog | MIT OR Apache-2.0 |
| @babel/parser, @babel/types, magic-string, nanoid, postcss, csstype, … (Vue's compiler deps) | MIT |
| entities | BSD-2-Clause |
| source-map-js | BSD-3-Clause |
| picocolors | ISC |
| typescript (type-checking only) | Apache-2.0 |

## Desktop shell (Rust crates in the Windows build, 236 crates)

| License | Crates |
|---|---|
| MIT OR Apache-2.0 (and variants) | 151, e.g. tauri, serde, tokio, windows, wry |
| MIT | 41 |
| Unicode-3.0 | 18 (`icu_*`) |
| **MPL-2.0** | 5: cssparser, cssparser-macros, dtoa-short, option-ext, selectors. File-level copyleft; we don't modify them, so only the notice is needed. |
| Unlicense OR MIT | 6 |
| BSD-3-Clause (and with MIT) | 5 (brotli, encoding_rs, …) |
| Zlib, 0BSD/MIT/Apache, CC0/MIT-0/Apache | 4 |
| Apache-2.0 | 1 (tao) |

## Other components

- **Microsoft Edge WebView2.** The installer embeds Microsoft's WebView2 bootstrapper, which
  Microsoft licenses for redistribution. The runtime itself is part of Windows 10/11.
- **Windows OCR** (Windows.Media.Ocr) is a Windows component; the app only calls it.

## This project

ECG Source List is **open core**: this repository is licensed under the **GNU AGPL-3.0-only**
(`LICENSE`), copyright © 2026 Matthew Kelly, with commercial licenses available from the
copyright holder; see `LICENSING.md`.

**Compatibility.** Every component above may be combined with and distributed as part of an
AGPL-3.0 program:

- MIT, BSD, ISC, Zlib, PSF, Unicode and FTL are permissive.
- Apache-2.0 is compatible with the GPL-3.0 family.
- MPL-2.0 allows combination with GPL-family licenses.
- The GCC and Nuitka runtime exceptions allow any license.

Commercial editions can use the same components, because none of them is copyleft beyond
file level.

## How to re-check

```bash
# Python: every runtime dependency's declared license
.venv/bin/python - <<'PY'
import importlib.metadata as md
for d in sorted(md.distributions(), key=lambda d: d.metadata["Name"].lower()):
    m = d.metadata
    print(f'{m["Name"]:30} {d.version:12} {m.get("License-Expression") or (m.get("License") or "").splitlines()[:1]}')
PY
# Front end
cd web && npm ls --omit=dev --all --parseable | tail -n +2 | xargs -I{} node -p "const p=require('{}/package.json'); p.name+' '+p.license"
# Rust
cd desktop/src-tauri && cargo tree --target x86_64-pc-windows-msvc -e normal,build --prefix none --format "{p} {l}" | sort -u
```
