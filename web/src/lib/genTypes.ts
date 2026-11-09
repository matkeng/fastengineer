// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core/generators (models.py, editable.py, check.py, preview.py, xlsx_import.py).

export type Scalar = string | number | boolean | null;

export interface GeneratorConfig {
	key_placeholder: string;
	run_placeholder: string;
	locked_placeholder: string;
	stop_at_blank_key: boolean;
	blank_row_between_runs: boolean;
	parent_include_tag: boolean;
	use_parents: boolean;
	collapse_spaces: boolean;
	replace_f_equals: boolean;
	freeze_formulas: boolean;
	run_from: number | null;
	run_up_to: number | null;
	keep_prev: boolean;
	diff_key: string;
	run_column: string;
	doc_number: string;
	doc_title: string;
	doc_revision: string;
	date_format: string;
	mode: 'compat' | 'standard';
	extra: Record<string, string>;
}

export interface ColumnDef {
	name: string;
	tag: string | null;
	source: string | null;
	formula: string | null;
}

export interface RunRow {
	id: string;
	values: Scalar[];
}

export interface Runsheet {
	columns: ColumnDef[];
	rows: RunRow[];
}

export interface Computed {
	kind: 'concat' | 'exists' | 'lookup' | 'expr' | 'count';
	[k: string]: unknown;
}

export interface TemplateCell {
	kind: 'literal' | 'text' | 'late' | 'formula' | 'computed';
	value: Scalar;
	text: string | null;
	override: Computed | null;
}

export interface TemplateRow {
	cells: TemplateCell[];
	source_row: number | null;
}

export interface Template {
	id: string;
	id_value: Scalar;
	rows: TemplateRow[];
	duplicate_blocks: number;
}

export interface DerivedTag {
	name: string;
	source: string;
	transform: string;
	default: string;
}

export interface OutputColumn {
	name: string;
	computed: Computed | null;
	raw: boolean;
}

export interface Generator {
	id: string;
	name: string;
	config: GeneratorConfig;
	runsheet: Runsheet;
	id_column: string;
	output_columns: OutputColumn[];
	templates: Template[];
	derived_tags: DerivedTag[];
	routes: { a: string; b: string; length: number }[];
	cable_prefixes: { cable_type: string; prefix: string }[];
	parents: [string, string][] | null;
	tables: Record<string, unknown>;
}

export interface Finding {
	severity: 'ERROR' | 'WARN' | 'INFO';
	code: string;
	item: string;
	detail: string;
	where: string;
}

export interface ImportReport {
	workbook: string;
	generator: string;
	runsheet_rows: number;
	tags: number;
	templates: number;
	template_rows: number;
	duplicate_template_ids: string[];
	mapped_formulas: Record<string, number>;
	unmapped_formulas: { where: string; formula: string; count: number }[];
	runsheet_formula_columns: Record<string, string>;
	parents: number;
	tables: Record<string, number>;
	baseline_rows: number;
	issues: string[];
}

export interface TableSummary {
	name: string;
	columns: number;
	rows: number;
}

export interface GenRecord {
	id: string;
	name: string;
	kind: string;
	source_file: string;
	updated_at: string | null;
	generator: Generator;
	tables: TableSummary[];
	import_report: ImportReport | null;
}

export interface BuildStats {
	processed: number;
	skipped: number;
	filtered: number;
	blank_key: number;
	no_template: number;
	deleted_rows: number;
	rows_written: number;
	output_rows: number;
	non_empty_cells: number;
	locked_used: number;
	duration_ms: number;
	phase_ms: Record<string, number>;
}

export interface BuildInfo {
	id: string;
	generator_id: string;
	seq: number;
	created_at: string;
	input_hash: string;
	engine_version: string;
	run_from: number | null;
	run_up_to: number | null;
	stats: BuildStats;
	warnings: Finding[];
	unresolved_count: number;
	unresolved_tokens: string[];
	added: number | null;
	removed: number | null;
	changed: number | null;
}

export interface GenSummary {
	id: string;
	name: string;
	kind: string;
	source_file: string;
	updated_at: string | null;
	runs: number;
	templates: number;
	last_build: BuildInfo | null;
}

export interface OutputRow {
	cells: Scalar[];
	run_row_id: string | null;
	template_id: string | null;
	template_seq: number | null;
	locked: boolean;
}

export interface ChangeEntry {
	key: string;
	kind: 'added' | 'removed' | 'changed';
	cells: { column: string; old: Scalar; new: Scalar }[];
}

export interface BuildResult {
	header: string[];
	rows: OutputRow[];
	stats: BuildStats;
	warnings: Finding[];
	unresolved_tokens: string[];
	unresolved_count: number;
	changes: { added: number; removed: number; changed: number; entries: ChangeEntry[] } | null;
	engine_version: string;
}

export interface BuildRecord {
	info: BuildInfo;
	result: BuildResult;
}

export interface TemplateIndexEntry {
	id: string;
	rows: number;
	runs: number;
	used: boolean;
}

export interface CheckResult {
	findings: Finding[];
	template_index: TemplateIndexEntry[];
}

export interface PreviewRow {
	cells: Scalar[];
	sources: string[];
	template_id: string | null;
	template_seq: number | null;
}

export interface PreviewResult {
	header: string[];
	rows: PreviewRow[];
	message: string;
}

export const KIND_LABELS: Record<string, string> = {
	dp: 'DP cable schedule',
	power: 'Power cable schedule',
	instCable: 'Instrument cable schedule',
	deviceList: 'Instrument device list',
	ioList: 'PLC IO list',
};

/** Text of a value the way the engine shows it (VBA CStr for numbers). */
export function cellText(v: Scalar | undefined): string {
	if (v === null || v === undefined) return '';
	if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
	if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(15)));
	return String(v);
}

/** Excel's reading of typed text (mirrors text.as_typed): number, TRUE/FALSE, else text. */
export function asTyped(s: string): Scalar {
	if (s === '') return null;
	if (/^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*$/.test(s)) return Number(s);
	const up = s.trim().toUpperCase();
	if (up === 'TRUE') return true;
	if (up === 'FALSE') return false;
	return s;
}

export const isTag = (s: string | null | undefined) => {
	const t = (s ?? '').trim();
	return t.startsWith('<<') && t.endsWith('>>') && t.length > 4;
};

// -- PLC hardware (mirrors generators/hardware.py) -------------------------------------

export type CardKind = 'Network' | 'DI' | 'DO' | 'AI' | 'AO' | 'RTD';
export const CARD_KINDS: CardKind[] = ['Network', 'DI', 'DO', 'AI', 'AO', 'RTD'];
export const IO_SIZES = [8, 12, 16, 32];

export interface CardType { id: string; kind: CardKind; channels: number; part_number: string; description: string; wiring: string }
export interface RackType { id: string; part_number: string; description: string; max_slots: number | null }
export interface Catalogue { rack_types: RackType[]; card_types: CardType[] }
export interface Card { id: string; card_type_id: string; tag: string; spare: boolean; notes: string }
export interface Rack { id: string; number: number; rack_type_id: string; description: string; first_slot: number; cards: (Card | null)[] }
export interface Panel { id: string; tag: string; description: string; location: string; racks: Rack[] }
export interface Hardware { panels: Panel[] }
export interface ScheduleRow {
	panel: string; rack: number; slot: number; card: string; kind: string; channels: number;
	part_number: string; description: string; spare: boolean; notes: string;
}
export interface HardwareSummary {
	panels: number; racks: number; cards: number;
	by_kind: { kind: string; cards: number; channels: number; spare_cards: number }[];
	demand: { card_type: string; points: number; kind: string | null; channels: number; free: number }[];
	demand_column: string | null;
}
export interface HardwareView {
	hardware: Hardware; catalogue: Catalogue; findings: Finding[]; summary: HardwareSummary; schedule: ScheduleRow[];
}

export const newId = () => Math.random().toString(16).slice(2, 14);

// -- bulk editing workbook (mirrors generators/bulk.py) ----------------------------------------

export interface SheetPreview {
	sheet: string; table: string; rows: number; added: number; removed: number; changed: number;
	changes: { key: string; kind: 'added' | 'removed' | 'changed'; cells: [string, string, string][] }[];
	errors: string[]; notes: string[];
}
export interface InputsImport {
	preview: { sheets: SheetPreview[]; ignored_sheets: string[] };
	applied: string[];
	record: GenRecord | null;
}
