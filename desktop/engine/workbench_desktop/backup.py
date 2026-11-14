# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Backing up a project to one file, and restoring a backup as a new project.

A backup is a zip of what makes a project: a snapshot of its database (taken with SQLite's
online backup, so it is consistent while people are working), the drawings and page images
beside it (symbols/), the PDFs attached to load types (keylists/), and manifest.json, which
says what the file is. A restore never touches an existing project: the backup becomes a new
one, in a new folder, with a new id and a name that says where it came from.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import workbench_core

from . import projects
from .projects import ProjectError

FORMAT = "ecg-source-list-backup"
VERSION = 1
DATABASE = "workbench.db"
MANIFEST = "manifest.json"
#: The folders beside the database that belong to the project.
FOLDERS = ("symbols", "keylists")
#: The largest backup a restore will unpack (what the files say they hold, before any is written).
MAX_RESTORED_BYTES = 50 * 1024 ** 3


def backup_name(project_name: str, now: datetime | None = None) -> str:
    safe = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in project_name).strip(" .") or "Project"
    return f"{safe} backup {(now or datetime.now()).strftime('%Y-%m-%d %H%M')}.zip"


def write_backup(reg: projects.Registry, project_id: str, target: Path) -> dict:
    """Write the project's backup to ``target`` (a new file). Returns its manifest."""
    entry = reg._entry(project_id)
    manifest = {"format": FORMAT, "version": VERSION, "project_id": entry.meta["id"], "project_name": entry.meta["name"],
                "made_at": datetime.now(timezone.utc).isoformat(), "app_version": workbench_core.__version__}
    fd, snapshot = tempfile.mkstemp(suffix=".db", prefix="backup-")
    os.close(fd)
    try:
        copy = sqlite3.connect(snapshot)
        try:
            with entry.store._lock:  # no write of this engine lands half way through
                entry.store._db.backup(copy)
        finally:
            copy.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
            zf.write(snapshot, DATABASE)
            for name in FOLDERS:
                for file in sorted((entry.folder / name).rglob("*")):
                    if file.is_file() and not file.name.endswith(".part"):
                        zf.write(file, file.relative_to(entry.folder).as_posix())
    finally:
        Path(snapshot).unlink(missing_ok=True)
    return manifest


def _members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """The files of a backup, each checked: only the database, the manifest and what is under
    the project's own folders, by a plain relative path. Anything else refuses the whole file."""
    out, total = [], 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        path = PurePosixPath(name)
        plain = not ("\\" in name or ":" in name or name.startswith("/") or any(p in ("", ".", "..") for p in path.parts))
        if not plain or not (name in (DATABASE, MANIFEST) or (len(path.parts) > 1 and path.parts[0] in FOLDERS)):
            raise ProjectError(422, f"This is not a backup the app made: it holds '{name[:80]}'.")
        total += info.file_size
        out.append(info)
    if total > MAX_RESTORED_BYTES:
        raise ProjectError(422, "The backup is larger than 50 GB unpacked.")
    return out


def read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(zf.read(MANIFEST))
    except (KeyError, ValueError) as exc:
        raise ProjectError(422, "This is not a backup the app made (it has no manifest).") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ProjectError(422, "This is not a backup the app made.")
    if not isinstance(manifest.get("version"), int) or manifest["version"] > VERSION:
        raise ProjectError(422, "This backup was made by a newer version of the app. Update the app to restore it.")
    return manifest


def restore_backup(reg: projects.Registry, source: Path, name: str | None = None) -> dict:
    """Unpack the backup ``source`` as a new project in the engine's data folder and serve it.
    ``name``: its name (default: the backed-up project's, with the date it is restored)."""
    try:
        zf = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProjectError(422, "That file is not a backup (it is not a zip file).") from exc
    with zf:
        manifest = read_manifest(zf)
        members = _members(zf)
        if DATABASE not in {m.filename for m in members}:
            raise ProjectError(422, "The backup has no project database in it.")
        original = str(manifest.get("project_name") or "Project")
        with reg._lock:
            wanted = " ".join((name or "").split()) or f"{original} (restored {datetime.now().strftime('%Y-%m-%d')})"
            name = reg.free_name(wanted)
            folder = reg.new_folder(name)
            try:
                for info in members:
                    if info.filename == MANIFEST:
                        continue
                    out = folder.joinpath(*PurePosixPath(info.filename).parts)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                with open(folder / DATABASE, "rb") as f:
                    if f.read(16) != b"SQLite format 3\x00":
                        raise ProjectError(422, "The backup's project database can't be read.")
                made = str(manifest.get("made_at") or "")[:10]
                return reg.adopt(folder, name, note=f"restored from a backup of '{original}'" + (f" made {made}" if made else ""))
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise
