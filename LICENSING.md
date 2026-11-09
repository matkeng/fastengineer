# Licensing: open core

Drawing Workbench is **open core**:

| Part | License |
|---|---|
| Everything in this repository (`core/`, `desktop/`, `web/`, `scripts/`, `samples/`, `docs/`) | **GNU AGPL-3.0-only**: see [`LICENSE`](LICENSE) |
| Commercial editions, add-ons and services (kept outside this repository) | Proprietary, from the copyright holder |
| Third-party components | Their own licenses: see [`docs/THIRD_PARTY_LICENSES.md`](docs/THIRD_PARTY_LICENSES.md) |

Copyright © 2026 Matthew Kelly.

## What the AGPL means for you

- You may use, study, change and share the app, including commercially.
- If you **distribute** it (the installer, the portable folder, or a modified version), you
  must give recipients the complete corresponding source code under the AGPL-3.0, including
  your changes.
- If you **run a modified version that users interact with over a network** (for example a
  hosted web version), you must offer those users its source code (AGPL §13).
- It comes with no warranty.

Each source file carries `SPDX-License-Identifier: AGPL-3.0-only`.

## Commercial license

If the AGPL doesn't fit, a commercial license (no obligation to publish your changes,
proprietary add-ons, support) is available from the copyright holder. Please open an issue
or contact the maintainer through GitHub, [@matkeng](https://github.com/matkeng).

## Keeping the open core dual-licensable

Dual licensing only works while the copyright holder can license all of the core. So:

- **Contributions** are accepted under the terms in [`CONTRIBUTING.md`](CONTRIBUTING.md),
  which grant the copyright holder the right to also license them commercially.
- **Proprietary add-ons** should talk to the core through its engine API (`/api/...`) or
  plug-ins, and must not copy AGPL code from other projects.
- **Dependencies** stay permissively licensed (MIT/BSD/Apache-2.0, or file-level MPL-2.0).
  AGPL or GPL dependencies would block the commercial editions. This is why the app uses
  PDFium (pypdfium2) rather than PyMuPDF/MuPDF, which are AGPL-3.0 or commercial.
- **Nuitka** (the compiler for the Python engine) is AGPL-3.0 with the *Nuitka Runtime
  Library Exception*. That exception lets compiled programs, including proprietary editions,
  carry any license.
