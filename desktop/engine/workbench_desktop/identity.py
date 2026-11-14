# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Who is making the current request.

The desktop app reads the Windows login and sends it with every request
(``X-Workbench-User`` / ``X-Workbench-Machine``). The name is reported by the
client, not verified, so it identifies colleagues on a trusted network; it is
not a security boundary.

The same per-request context carries the optimistic-concurrency tokens:
``If-Match`` in (the record version the client last saw) and ``ETag`` out.
"""

from __future__ import annotations

import contextvars
import getpass
import json
import os
import re
import socket
from dataclasses import dataclass

from workbench_core.text_case import PROPER_WORDS, use_proper_words

USER_HEADER = "x-workbench-user"
MACHINE_HEADER = "x-workbench-machine"
BASE_TIME_HEADER = "x-workbench-base-time"
PROJECT_HEADER = "x-workbench-project"

#: Set by ``--server``: every request must name its user (no falling back to the engine's own login).
server_mode = False
#: Answered without a user even on a shared server: the app asks these before it knows who is asking.
OPEN_PATHS = {"/api/health", "/api/hello"}
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
#: Where the app's own pages are served from. The Tauri WebView origin differs by OS
#: (http://tauri.localhost on Windows, tauri://localhost on macOS/Linux); the Vite dev server
#: runs on localhost:5173.
APP_ORIGINS = r"^(https?://tauri\.localhost|tauri://localhost|http://localhost:\d+|http://127\.0\.0\.1:\d+)$"
#: Set by ``--admin`` (lower-cased): who may create projects and choose their members.
admins: set[str] = set()


@dataclass
class RequestContext:
    user: str
    machine: str
    #: The project this request works in (see ``projects.resolve``).
    project: str | None = None
    #: (entity, record id, version) the client last saw, from ``If-Match``.
    expect: tuple[str, str, int] | None = None
    #: ``updated_at`` of the row the client last saw (rows have no URL of their own to GET).
    base_time: str | None = None
    #: Sent back as the ``ETag`` header.
    etag: str | None = None


_current: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar("workbench_request", default=None)


def local_user() -> str:
    """The login of the account this process runs as, e.g. ``ACME\\jsmith`` on Windows."""
    try:
        name = getpass.getuser()
    except Exception:  # no login name available (some service accounts)
        name = "unknown"
    domain = os.environ.get("USERDOMAIN", "")
    return f"{domain}\\{name}" if domain else name


def local_machine() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname()


def current() -> RequestContext:
    """The request's context; outside a request (tests, start-up) the local login."""
    return _current.get() or RequestContext(local_user(), local_machine())


def carry(fn):
    """Wrap a background job so its changes are logged under the user who started it."""
    ctx = current()
    words = PROPER_WORDS.get()

    def run(*args, **kwargs):
        token = _current.set(RequestContext(ctx.user, ctx.machine, ctx.project))
        wtoken = PROPER_WORDS.set(words)
        try:
            return fn(*args, **kwargs)
        finally:
            PROPER_WORDS.reset(wtoken)
            _current.reset(token)

    return run


def format_etag(entity: str, record_id: str, version: int) -> str:
    return json.dumps(f"{entity}:{record_id}:{version}")


def parse_etag(value: str | None) -> tuple[str, str, int] | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("W/"):
        value = value[2:]
    parts = value.strip('"').rsplit(":", 1)
    if len(parts) != 2 or ":" not in parts[0] or not parts[1].isdigit():
        return None
    entity, record_id = parts[0].split(":", 1)
    return entity, record_id, int(parts[1])


class IdentityMiddleware:
    """Pure ASGI middleware: sets the request context and adds the ETag header.

    (Not BaseHTTPMiddleware, so the context object is the same one the route and
    the storage layer see, including from the sync-route thread pool.)
    """

    def __init__(self, app, record_of=None, version_of=None, resolve_project=None, proper_words=None):
        self.app = app
        self.allowed_origin = re.compile(APP_ORIGINS).match
        #: () -> the request's project's xProper words, read on first use (text_case.proper_case)
        self.proper_words = proper_words
        #: (context, path, requested project id) -> sets context.project, or raises
        #: an exception with ``status`` and ``message`` when the user may not use it.
        self.resolve_project = resolve_project
        #: (method, path) -> (entity, record id) for URLs that address one record.
        self.record_of = record_of
        self.version_of = version_of

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("utf-8", "replace") for k, v in scope.get("headers", [])}
        user = headers.get(USER_HEADER, "").strip()[:200]
        machine = headers.get(MACHINE_HEADER, "").strip()[:200]
        method = scope.get("method", "GET")

        async def refuse(status: int, detail: str) -> None:
            body = json.dumps({"detail": detail}).encode()
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        # A page of another website can POST to the engine without asking first (no preflight for
        # a request with no body or a plain one). Browsers name the page in Origin: refuse any
        # change that comes from a page that is not the app.
        origin = headers.get("origin", "")
        if origin and method not in SAFE_METHODS and not self.allowed_origin(origin):
            await refuse(403, "This request came from a web page that is not the app.")
            return
        if server_mode and not user and method != "OPTIONS" and scope.get("path", "") not in OPEN_PATHS:
            await refuse(401, "This server needs to know who you are. Update the desktop app, "
                              f"or send the {USER_HEADER} header.")
            return
        ctx = RequestContext(
            user=user or (local_user() if not server_mode else "unknown"),
            machine=machine or (local_machine() if not server_mode else ""),
            expect=parse_etag(headers.get("if-match")),
            base_time=headers.get(BASE_TIME_HEADER) or None,
        )
        if self.resolve_project and method != "OPTIONS":
            try:
                self.resolve_project(ctx, scope.get("path", ""), headers.get(PROJECT_HEADER, "").strip() or None)
            except Exception as exc:
                if not hasattr(exc, "status"):
                    raise
                await refuse(exc.status, exc.message)
                return
        token = _current.set(ctx)
        words = use_proper_words(self.proper_words) if self.proper_words else None

        async def send_with_etag(message):
            if message["type"] == "http.response.start" and 200 <= message["status"] < 300:
                if not ctx.etag and self.record_of and method in ("GET", "PUT"):
                    record = self.record_of(scope.get("path", ""))
                    if record:
                        ctx.etag = format_etag(*record, self.version_of(*record))
            if message["type"] == "http.response.start" and ctx.etag and 200 <= message["status"] < 300:
                message = {**message, "headers": [*message.get("headers", []), (b"etag", ctx.etag.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_etag)
        finally:
            if words is not None:
                PROPER_WORDS.reset(words)
            _current.reset(token)
