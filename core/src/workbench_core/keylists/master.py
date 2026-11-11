# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Project Master lists, and the Instrument generator that (with the Power generator) fills them.

A project has one master of each list: the Project Master Cable Schedule, Equipment List,
Instrument List and I/O List. Both generators write to the same four:

- **Power** (keylists.loadgen): every load of the Project Load List adds the rows its load
  type has for the list.
- **Instrument** (here): every row of the Instrument Runsheet adds the rows its equipment
  type has for the list, with the <<tags>> in them filled in from the runsheet row.

A master list is worked out when it is asked for, so it is always up to date, and it is not
edited: to change a row, change what it comes from. Besides the list's own columns each row
says which **Generator** made it and whether it is **Confirmed** (a runsheet row's Confirmed;
a load's rows are always confirmed), so a deliverable can keep only the confirmed rows.

Deliverables take their content from a master list through a filter and a choice and order
of columns, and freeze it when a revision is issued.
"""

from __future__ import annotations

from ..generators.models import BuildResult, BuildStats, OutputRow, Scalar
from .instrument_runsheet import FIXED, MAX_NUMBERS, InstrumentRunsheet
from .loadgen import LISTS, TEMPLATE_LISTS, expand_cell
from .models import EquipmentType

#: The lists that have a project master (the lists load types and equipment types have rows for).
MASTER_LISTS: list[str] = list(TEMPLATE_LISTS)
MASTER_NAMES: dict[str, str] = {"cable_schedule": "Project Master Cable Schedule", "equipment_list": "Project Master Equipment List",
                                "instrument_list": "Project Master Instrument List", "plc_io_list": "Project Master IO List"}
GENERATOR, CONFIRMED = "Generator", "Confirmed"
#: The columns a master list has after the list's own.
EXTRA_COLUMNS: tuple[str, ...] = (GENERATOR, CONFIRMED)
POWER, INSTRUMENT = "Power", "Instrument"
_BLANK_NUMBERS = {f"#{n}": "" for n in range(1, MAX_NUMBERS + 1)}  # a number a row doesn't have fills in as nothing


def master_columns(list_key: str, columns: list[str] | None = None) -> list[str]:
    """A master list's header: the list's own columns (`columns`, the project's; default the
    built-in ones), then Generator and Confirmed."""
    return list(LISTS[list_key].columns if columns is None else columns) + list(EXTRA_COLUMNS)


def runsheet_tags(row, type_name: str, area_tag: str) -> dict[str, str]:
    """Tag name (lower case, without the brackets) -> text, for one runsheet row."""
    values = [type_name, area_tag, row.parent_tag, row.suffix, row.pid, row.via_mb, "TRUE" if row.confirmed else "FALSE", row.rack]
    tags = dict(_BLANK_NUMBERS)
    tags |= {c[2][2:-2].casefold(): v for c, v in zip(FIXED, values)}
    tags |= {f"#{n}": v for n, v in enumerate(row.numbers, start=1)}
    return tags


def instrument_rows(list_key: str, runsheet: InstrumentRunsheet, types: dict[str, EquipmentType], area_tags: dict[str, str],
                    unresolved: dict[str, int] | None = None, columns: list[str] | None = None,
                    links=None) -> list[tuple[OutputRow, bool]]:
    """What the Instrument generator adds to a list: for each runsheet row, in order, the rows
    its equipment type has for the list, filled in. Each comes with the runsheet row's
    Confirmed. `types`: equipment types by id; `area_tags`: plant area id -> tag number.
    A row whose equipment type is gone produces nothing. `links`: the project's lists
    (tag_paths.Links) for dot notation (<<EquipmentType.Package.Vendor>>, <<Parent.LoadType.Code>>)."""
    from .tag_paths import Links

    links = links or Links(equipment_types=types.values())
    cols = LISTS[list_key].columns if columns is None else columns
    unresolved = {} if unresolved is None else unresolved
    out: list[tuple[OutputRow, bool]] = []
    for row in runsheet.rows:
        kind = types.get(row.equipment_type_id)
        if kind is None:
            continue
        tags = runsheet_tags(row, kind.name, area_tags.get(row.plant_area_id, ""))
        for i, template in enumerate(kind.rows.get(list_key, []), start=1):
            tags["row"] = str(i)
            root = links.runsheet(row, tags)
            cells = [expand_cell(template.get(c, ""), tags, unresolved, root) for c in cols]
            out.append((OutputRow(cells=cells, run_row_id=f"runsheet/{row.id}", template_id=kind.name, template_seq=i), row.confirmed))
    return out


def master_list(list_key: str, power: BuildResult, runsheet: InstrumentRunsheet, types: dict[str, EquipmentType],
                area_tags: dict[str, str], columns: list[str] | None = None, links=None) -> BuildResult:
    """The project master of a list: the Power generator's rows (`power`: loadgen.generate for
    the list, with the same `columns`), then the Instrument generator's, each with its
    Generator and Confirmed. `columns`: the project's columns of the list."""
    unresolved: dict[str, int] = {}
    rows = [r.model_copy(update={"cells": [*r.cells, POWER, "TRUE"]}) for r in power.rows]
    for r, confirmed in instrument_rows(list_key, runsheet, types, area_tags, unresolved, columns, links):
        extra: list[Scalar] = [INSTRUMENT, "TRUE" if confirmed else "FALSE"]
        rows.append(r.model_copy(update={"cells": [*r.cells, *extra]}))
    tokens = sorted(set(power.unresolved_tokens) | set(unresolved))
    return BuildResult(header=master_columns(list_key, columns), rows=rows, stats=BuildStats(rows_written=len(rows), output_rows=len(rows)),
                       unresolved_tokens=tokens, unresolved_count=power.unresolved_count + sum(unresolved.values()),
                       engine_version="project master lists")


def generator_counts(result: BuildResult) -> dict[str, int]:
    """Rows of a master list by the generator that made them."""
    i = result.header.index(GENERATOR)
    counts = {POWER: 0, INSTRUMENT: 0}
    for r in result.rows:
        counts[str(r.cells[i])] = counts.get(str(r.cells[i]), 0) + 1
    return counts
