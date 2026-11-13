# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Electrical Equipment List: equipment items edited here, each also a Load List row
(whose plant area, load type, panel and supply are set here, not in the Load List)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from workbench_core.keylists import EEL_SOURCE, KEPT, PRIMARY_SUPPLY, EelItem, check_eel, supply_loop
from workbench_core.keylists.loadlist import load_type_choice
from workbench_core.refdata import RefValidationError, name_key

from .loadlist_api import EEL_GONE, EEL_NAME, Choice, _choices, eel_rows, import_rows, sync_rows
from .refdata_api import invalid
from .storage import get_keylists, get_loadlist

router = APIRouter(prefix="/api/eel", tags=["electrical equipment"])


class LoadTypeChoice(Choice):
    rating_unit: str
    voltage: int
    phases: str


class EelChoices(BaseModel):
    equipment_codes: list[Choice]
    packages: list[Choice]
    plant_areas: list[Choice]
    load_types: list[LoadTypeChoice]
    supplies: list[Choice]  # Primary Supply, then the active distribution panels (imports and this list)


class EelView(BaseModel):
    items: list[EelItem]
    choices: EelChoices
    clashes: dict[str, list[str]] = Field(default_factory=dict)  # item id -> imports that have its tag too
    updated_at: str | None = None


def _import_panels() -> list[Choice]:
    rows = [r for r in get_loadlist().rows() if r.recipe_id != EEL_SOURCE and r.status == "active" and r.is_panel]
    return [Choice(id=r.ref(), label=f"{r.tag()} – {r.values.get('desc') or ''} ({r.source})".replace(" –  (", " (")) for r in rows]


def _view(items: list[EelItem], updated_at=None) -> EelView:
    lists = get_keylists()
    areas, _ = _choices()
    supplies = [Choice(id=PRIMARY_SUPPLY, label="Primary Supply")] + sorted(
        _import_panels() + [Choice(id=f"{EEL_SOURCE}/{i.id}", label=f"{i.tag} – {i.description}") for i in items if i.is_panel],
        key=lambda c: c.label.casefold())
    choices = EelChoices(
        equipment_codes=[Choice(id=c.id, label=f"{c.code} – {c.name}") for c in lists.code_list("equipment-codes").items],
        packages=[Choice(id=p.id, label=f"{p.number} – {p.description}") for p in lists.equipment_packages().items],
        plant_areas=areas,
        load_types=[LoadTypeChoice(id=t.id, label=load_type_choice(t, lists.load_types().items), rating_unit=t.rating_unit, voltage=t.voltage,
                                   phases=t.phases) for t in lists.load_types().items],
        supplies=supplies)
    imported: dict[str, set[str]] = {}
    for r in get_loadlist().rows():
        if r.recipe_id != EEL_SOURCE and r.status == "active":
            imported.setdefault(name_key(r.tag()), set()).add(r.source)
    clashes = {i.id: sorted(imported[name_key(i.tag)]) for i in items if name_key(i.tag) in imported}
    return EelView(items=items, choices=choices, clashes=clashes, updated_at=updated_at and updated_at.isoformat())


@router.get("", response_model=EelView)
def get_eel() -> EelView:
    eel = get_keylists().eel()
    return _view(eel.items, eel.updated_at)


class EelUpdate(BaseModel):
    items: list[dict]  # as typed in: check_eel converts the numbers and names each problem


@router.put("", response_model=EelView)
def save_eel(body: EelUpdate):
    lists = get_keylists()
    loadlist = get_loadlist()
    packages = {p.id for p in lists.equipment_packages().items}
    panels_sent = {f"{EEL_SOURCE}/{r.get('id')}" for r in body.items if str(r.get("is_panel")).casefold() in ("true", "1", "yes")}
    known = {
        "equipment_code_id": {c.id for c in lists.code_list("equipment-codes").items},
        "plant_area_id": {n.id for n in lists.plant_areas().nodes},
        "load_type_id": {t.id for t in lists.load_types().items},
        "vendor_package_id": packages, "supplied_by_id": packages, "installed_by_id": packages, "terminated_by_id": packages,
        "supplied_from": {c.id for c in _import_panels()} | panels_sent,
    }
    errors: dict[str, str] = {}
    eel = None
    try:
        eel = check_eel(body.items, known)
    except RefValidationError as exc:
        if not exc.fields:
            return invalid(exc)
        errors |= exc.fields

    # A panel this list's own items are supplied from can't stop being one: say so on the panel too.
    sent = {str(r.get("id")): r for r in body.items}
    for raw in body.items:
        target = str(raw.get("supplied_from") or "")
        panel_id = target[len(EEL_SOURCE) + 1:] if target.startswith(f"{EEL_SOURCE}/") else None
        if panel_id in sent and target not in panels_sent:
            tag = str(raw.get("tag") or "").strip() or "Another item"
            errors.setdefault(f"{panel_id}.is_panel", f"{tag} is supplied from it: change that first")

    # Tags are unique across this list and the imports (as they are now).
    live, gone, _, _ = import_rows()
    imported: dict[str, set[str]] = {}
    for r in live:
        if r.status == "active":
            imported.setdefault(name_key(r.tag()), set()).add(r.source)
    for raw in body.items:
        tag = str(raw.get("tag") or "").strip()
        if tag and name_key(tag) in imported:
            errors.setdefault(f"{raw.get('id')}.tag", f"Tag {tag} is already in {', '.join(sorted(imported[name_key(tag)]))}")

    if eel is not None and not errors:
        # Supply: no loops through the imports' rows, and no panel taken away from rows a person
        # (or this list) supplies from it.
        stored = {r.ref(): r for r in loadlist.rows() if r.recipe_id != EEL_SOURCE}
        mine = {r.ref(): r for r in eel_rows(eel)}
        graph = stored | mine
        for ref in supply_loop(graph):
            if ref in mine:
                errors[f"{mine[ref].key}.supplied_from"] = "That makes a supply loop: " + " → ".join(
                    graph[r].tag() for r in supply_loop(graph))
                break
        old = lists.eel()
        for item in old.items:
            ref = f"{EEL_SOURCE}/{item.id}"
            if not item.is_panel or (ref in mine and mine[ref].is_panel):
                continue
            fed = [r for r in stored.values() if r.supplied_from == ref and r.supplied_from_by in KEPT]
            if fed:
                field = f"{item.id}.is_panel" if ref in mine else None
                message = (f"{item.tag} supplies {len(fed)} row(s) in the Load List "
                           f"({', '.join(r.tag() for r in fed[:5])}). Change what they are supplied from first.")
                if field:
                    errors[field] = message
                else:
                    return invalid(RefValidationError(message))
    if errors:
        return invalid(RefValidationError(f"{len(errors)} problem(s) in the equipment list.", errors))

    saved = lists.save_eel(eel)
    sync_rows(live + eel_rows(saved), gone | {EEL_SOURCE: EEL_GONE})
    return _view(saved.items, saved.updated_at)


def eel_uses(fields: tuple[str, ...], removed: dict[str, str]) -> list[str]:
    """`label (n items)` for each removed id (id -> label) that EEL items refer to in `fields`."""
    counts: dict[str, int] = {}
    for item in get_keylists().eel().items:
        for value in {getattr(item, f) for f in fields} & removed.keys():  # an item counts once per id
            counts[value] = counts.get(value, 0) + 1
    return [f"{removed[i]} ({n} item{'s' if n > 1 else ''})" for i, n in counts.items()]


__all__ = ["router", "eel_uses", "EEL_NAME"]
