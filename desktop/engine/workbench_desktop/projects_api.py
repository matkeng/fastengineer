# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Projects: which ones the user has, opening one, and (administrators) managing them."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from . import identity, projects
from .audit_api import AuditEntry

router = APIRouter(prefix="/api/projects", tags=["projects"])


class Project(BaseModel):
    id: str
    name: str
    archived: bool = False


class ProjectDetail(Project):
    folder: str
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
                       enforced=projects.enforced())


@router.get("/log", response_model=list[AuditEntry])
def project_log(limit: int = 100) -> list[AuditEntry]:
    """Who created, renamed or archived projects and changed their members."""
    return _admin().log_entries(limit=limit)


class NewProject(BaseModel):
    name: str
    path: str | None = None          # a folder of its own; omit for the standard place
    copy_from: str | None = None     # start with this project's lists, tables, libraries and types
    members: list[str] = []


@router.post("", response_model=ProjectDetail)
def create_project(body: NewProject) -> ProjectDetail:
    return ProjectDetail(**_admin().create(body.name, body.path, body.copy_from, body.members))


class ProjectUpdate(BaseModel):
    name: str | None = None
    archived: bool | None = None
    members: list[str] | None = None


@router.put("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: str, body: ProjectUpdate) -> ProjectDetail:
    return ProjectDetail(**_admin().update(project_id, body.name, body.archived, body.members))
