# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Projects: which ones the user has, opening one, and (administrators) managing them."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import backup, identity, projects
from .uploads import save_upload
from .audit_api import AuditEntry

router = APIRouter(prefix="/api/projects", tags=["projects"])


class Project(BaseModel):
    id: str
    name: str
    archived: bool = False


class ProjectDetail(Project):
    folder: str
    external: bool               # kept outside the engine's data folder (can be removed from the list)
    members: list[str]
    created_at: str
    created_by: str


class MyProjects(BaseModel):
    projects: list[Project]      # the ones this user may open
    current: str | None          # the one they had open last (else the first), if any
    is_admin: bool
    enforced: bool               # False: every project is open to everyone


class AllProjects(BaseModel):
    projects: list[ProjectDetail]
    users: list[str]             # everyone who has started the app or is a member somewhere
    default_folder: str          # where projects without a folder of their own are kept
    missing: list[str]           # folders the engine was pointed at that are not there now
    enforced: bool


def _admin() -> projects.Registry:
    if not projects.is_admin(identity.current().user):
        raise projects.ProjectError(403, "Only an administrator can manage projects.")
    return projects.registry()


@router.get("", response_model=MyProjects)
def my_projects() -> MyProjects:
    user = identity.current().user
    reg = projects.registry()
    reg.seen(user)
    return MyProjects(projects=reg.for_user(user), current=reg.default_for(user), is_admin=projects.is_admin(user),
                      enforced=projects.enforced())


@router.post("/{project_id}/open", response_model=Project)
def open_project(project_id: str) -> Project:
    """Make this the project the user starts in next time."""
    user = identity.current().user
    reg = projects.registry()
    project = reg.get(project_id)
    if not reg.may_open(project, user):
        raise projects.ProjectError(403, f"You can't open the project '{project['name']}'.")
    reg.seen(user, project_id)
    return Project(**project)


@router.get("/all", response_model=AllProjects)
def all_projects() -> AllProjects:
    reg = _admin()
    return AllProjects(projects=reg.all(), users=reg.known_users(), default_folder=str(reg.root / "projects"),
                       missing=reg.missing,
                       enforced=projects.enforced())


@router.get("/log", response_model=list[AuditEntry])
def project_log(limit: int = 100) -> list[AuditEntry]:
    """Who created, renamed or archived projects and changed their members."""
    return _admin().log_entries(limit=limit)


class NewProject(BaseModel):
    name: str
    path: str | None = None          # a new folder of its own; omit for the standard place
    copy_from: str | None = None     # start with this project's lists, tables, libraries and types
    members: list[str] = []


@router.post("", response_model=ProjectDetail)
def create_project(body: NewProject) -> ProjectDetail:
    return ProjectDetail(**_admin().create(body.name, body.path, body.copy_from, body.members))


class Folder(BaseModel):
    path: str


@router.post("/attach", response_model=ProjectDetail)
def attach_project(body: Folder) -> ProjectDetail:
    """List a project folder that already exists. It keeps its own name, members and history."""
    return ProjectDetail(**_admin().attach(body.path))


@router.post("/forget", response_model=AllProjects)
def forget_missing(body: Folder) -> AllProjects:
    """Stop looking for a project folder that is no longer there."""
    _admin().forget_missing(body.path)
    return all_projects()


@router.delete("/{project_id}")
def detach_project(project_id: str) -> dict[str, str]:
    """Take a project kept outside the data folder off the list. Its folder is not touched."""
    _admin().detach(project_id)
    return {"status": "removed from the list"}


class BackupBody(BaseModel):
    path: str | None = None  # desktop: chosen in a Save As dialog


def _temp_zip() -> Path:
    fd, name = tempfile.mkstemp(suffix=".zip", prefix="project-backup-")
    os.close(fd)
    return Path(name)


@router.post("/{project_id}/backup")
def backup_project(project_id: str, body: BackupBody, request: Request):
    """The whole project as one .zip: its database, drawings and attached PDFs. On the user's
    own PC the engine writes it to ``path``; otherwise (a shared server) it is sent back."""
    # JSON only: forces a CORS preflight, so a cross-site page can't trigger a file write.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    reg = _admin()
    name = backup.backup_name(reg.get(project_id)["name"])
    if body.path is not None and identity.server_mode:
        raise HTTPException(403, "A shared server does not save files on its own disk. "
                                 "Download the backup instead (leave out the path).")
    tmp = _temp_zip()
    try:
        backup.write_backup(reg, project_id, tmp)
        if body.path is None:
            return FileResponse(tmp, media_type="application/zip", filename=name, background=BackgroundTask(tmp.unlink, missing_ok=True))
        target = Path(body.path)
        if target.suffix.lower() != ".zip":
            target = target.with_suffix(".zip")
        try:
            shutil.move(str(tmp), target)
        except OSError as exc:
            raise HTTPException(409, f"Could not save {target.name}: {exc.strerror or exc}.") from exc
        return {"path": str(target)}
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


#: The largest backup file a restore accepts.
MAX_BACKUP = 8 * 1024 ** 3


@router.post("/restore", response_model=ProjectDetail)
async def restore_project(request: Request, name: str | None = Query(None)) -> ProjectDetail:
    """Restore a backup (the request body) as a NEW project. No existing project is changed."""
    reg = _admin()
    tmp = _temp_zip()
    try:
        if await save_upload(request, MAX_BACKUP, tmp) == 0:
            raise HTTPException(400, "The file is empty.")
        # in a worker thread (it unpacks files); the request's user goes with it
        return ProjectDetail(**await run_in_threadpool(backup.restore_backup, reg, tmp, name))
    finally:
        tmp.unlink(missing_ok=True)


class ProjectUpdate(BaseModel):
    name: str | None = None
    archived: bool | None = None
    members: list[str] | None = None


@router.put("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: str, body: ProjectUpdate) -> ProjectDetail:
    return ProjectDetail(**_admin().update(project_id, body.name, body.archived, body.members))
