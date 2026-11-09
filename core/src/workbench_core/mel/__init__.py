"""MEL import: turn a Mechanical Equipment List (or similar list) into a load
list with a saved, re-applicable recipe of rules (see docs/PRD_MEL_IMPORT.md).

The source file is never modified. Every rule is keyed by a header name or a
key-column value, so the same recipe re-applies to a revised file.
"""

from .ingest import IngestError, parse_csv, rows_from_extract, unique_headers, unique_keys
from .models import (
    ELEC_LOAD_FIELDS,
    INSTRUMENT_FIELDS,
    AutoColumn,
    ColumnRule,
    CustomRow,
    FieldMap,
    Override,
    Recipe,
    Revision,
    RowRule,
    TextColumn,
    fields_for,
    output_name,
)
from .pipeline import STAGES, PipelineResult, load_list, output_list, run_pipeline

__all__ = [
    "ELEC_LOAD_FIELDS", "INSTRUMENT_FIELDS", "STAGES", "fields_for", "output_list", "output_name", "AutoColumn", "ColumnRule", "CustomRow", "FieldMap",
    "IngestError", "Override", "PipelineResult", "Recipe", "Revision", "RowRule",
    "TextColumn", "load_list", "parse_csv", "rows_from_extract", "run_pipeline",
    "unique_headers", "unique_keys",
]
