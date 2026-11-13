// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.mel (models.py, pipeline.py).
export type TargetList = 'MEL' | 'ELL' | 'EEL' | 'PIL' | 'LIL';
export const TARGETS: TargetList[] = ['MEL', 'ELL', 'EEL', 'PIL', 'LIL'];
/** What each list type is turned into (PIL = process instrument list, fed by P&ID analysis). */
export const TARGET_LABELS: Record<TargetList, string> = {
	MEL: 'MEL → load list', ELL: 'ELL → load list', EEL: 'EEL → load list', PIL: 'PIL → instrument list', LIL: 'LIL → load list',
};

/** What each built-in load-list field is called (a project's own names come from the engine: RecipeDetail.labels, LoadListView.labels). */
export const LOAD_FIELD_LABELS: Record<string, string> = {
	area: 'Area', sub_area: 'Sub-area', tag: 'Tag', equip_qty: 'Quantity', standby_qty: 'Standby quantity',
	multi_load: 'Multiple loads', desc: 'Description', equip_type: 'Equipment type', equip_subtype: 'Equipment subtype',
	load_units: 'Load units (kW, HP…)', load_rating: 'Load rating', load_voltage: 'Voltage', csv_row_num: 'Source row number',
	phases: 'Phases', status: 'Status', starter_type: 'Starter type', load_type: 'Load type', starter_addons: 'Starter add-ons',
	load_addons: 'Load add-ons', field_addons: 'Field add-ons', is_a_loadcentre: 'Is a load centre', loadcentre: 'Load centre',
	supplied_from: 'Supplied from', is_deleted: 'Deleted',
};

export interface ColumnRule { header: string; visible: boolean; rename: string | null }
export interface RowRule { key: string; note?: string }
export interface TextColumn { name: string; value: string }
export interface Override { key: string; column: string; value: string; note?: string }
export interface CustomRow { key: string; values: Record<string, string>; note?: string }
/** An "else if" of a calculated column: when `statement` holds (or doesn't, with `negate`), the value is `value`. */
export interface AutoBranch { statement: string; negate: boolean; value: string }
/** If statement (NOT it, with negate) then true_val; else if each of else_ifs in turn; else false_val. */
export interface AutoColumn {
	name: string; statement: string; negate?: boolean; true_val: string; else_ifs?: AutoBranch[]; false_val: string; error_val: string;
}
/** A whole cell value and what replaces it (blank allowed). */
export interface Replacement { find: string; replace: string }
/** A new column: the values of `column`, whole values replaced as listed (others kept). */
export interface FindReplace { name: string; column: string; replacements: Replacement[] }
export interface FieldMap { field: string; column: string | null; manual: string | null }

export interface Recipe {
	id: string;
	name: string;
	target: TargetList;
	columns: ColumnRule[];
	hidden_rows: RowRule[];
	text_columns: TextColumn[];
	overrides: Override[];
	custom_rows: CustomRow[];
	find_replace: FindReplace[];
	auto_columns: AutoColumn[];
	mapping: FieldMap[];
	updated_at: string | null;
}

export interface RecipeSummary {
	id: string;
	name: string;
	target: TargetList;
	updated_at: string;
	revisions: number;
	latest_rev: number | null;
}

export interface RevisionInfo {
	id: string;
	rev: number;
	file_name: string;
	source: string;
	key_header: string;
	num_rows: number;
	num_cols: number;
	uploaded_at: string;
	warnings: string[];
}

export interface RecipeDetail { recipe: Recipe; revisions: RevisionInfo[]; fields: string[]; labels?: Record<string, string>; output_name: string }

export type Stage = 'source' | 'columns' | 'rows' | 'text' | 'overrides' | 'custom' | 'replace' | 'auto';

export interface PipelineRow {
	key: string;
	origin: 'file' | 'custom';
	file_row: number | null;
	values: Record<string, string>;
	overridden: string[];
	auto_errors: string[];
}

export interface RuleIssue { kind: string; rule: string; message: string }

export interface PipelineResult {
	stage: Stage;
	key_header: string;
	headers: string[];
	source_headers: string[];
	rows: PipelineRow[];
	hidden_rows: PipelineRow[];
	issues: RuleIssue[];
}

export interface LoadListResult {
	fields: string[];
	rows: Record<string, string | number | boolean | null>[];
	warnings: string[];
}

export interface CsvInspect {
	headers: string[];
	headers_original: string[];
	num_rows: number;
	sample: Record<string, string>[];
	suggested_key: string;
	warnings: string[];
}
