// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Hand-written for the PoC. In the real app these are generated from the
// Pydantic models in workbench_core so both sides share one schema (spec 7.1).
export interface EngineInfo {
	core_version: string;
	python: string;
	platform: string;
	pid: number;
	compiled: boolean;
}

export interface Greeting {
	message: string;
	at: string;
}

export interface Equipment {
	id: string;
	tag: string;
	description: string;
	rating_kw: number | null;
	views: string[];
}

// ---- Excel query (mirrors workbench_core.excel.models) ----

export type Strike = 'none' | 'partial' | 'full';

export interface StrikeRun {
	text: string;
	strike: boolean;
}

export interface Cell {
	v: string | number | boolean | null;
	t: string;
	s: Strike;
	runs: StrikeRun[] | null;
	m: boolean;
}

export interface SourceInfo {
	id: string;
	kind: 'sheet' | 'table';
	name: string;
	sheet: string;
	ref: string;
	first_row: number;
	last_row: number;
	first_col: number;
	last_col: number;
}

export interface WorkbookSummary {
	id: string;
	filename: string;
	sources: SourceInfo[];
	warnings: string[];
}

export interface PreviewRow {
	row: number;
	cells: Cell[];
	filled: number;
}

export interface PreviewResult {
	source: SourceInfo;
	columns: string[];
	rows: PreviewRow[];
	suggested_header_row: number | null;
	suggested_header_rows: number;
	truncated: boolean;
}

export interface ColumnInfo {
	index: number;
	letter: string;
	name: string;
	non_blank: number;
	unique: number;
	duplicates: number;
}

export interface ColumnsResult {
	source: SourceInfo;
	header_row: number;
	header_rows: number;
	data_rows: number;
	columns: ColumnInfo[];
	suggested_key: number | null;
}

export interface ExtractedRow {
	row: number;
	key: string;
	strike: Strike;
	duplicate_key: boolean;
	cells: Cell[];
}

export interface ExtractResult {
	source: SourceInfo;
	header_row: number;
	header_rows: number;
	key_column: number;
	columns: ColumnInfo[];
	rows: ExtractedRow[];
	blank_keys_skipped: number;
	duplicate_keys: string[];
	warnings: string[];
}

// ---- Table compare (mirrors workbench_core.excel.compare) ----

export type RowStatus = 'added' | 'deleted' | 'struck' | 'restored' | 'changed' | 'unchanged';
export type CellChange = 'none' | 'value' | 'strike' | 'both';

export interface CompareColumn {
	name: string;
	old_name: string | null;
	a_index: number | null;
	b_index: number | null;
	status: 'same' | 'added' | 'deleted';
	is_key: boolean;
	changed_cells: number;
}

export interface CompareCell {
	a: Cell | null;
	b: Cell | null;
	change: CellChange;
}

export interface CompareRow {
	key: string;
	status: RowStatus;
	a_row: number | null;
	b_row: number | null;
	changed_cells: number;
	duplicate_key: boolean;
	cells: CompareCell[];
}

export interface CompareSummary {
	added: number;
	deleted: number;
	struck: number;
	restored: number;
	changed: number;
	unchanged: number;
	changed_cells: number;
	columns_added: number;
	columns_deleted: number;
}

export interface CompareResult {
	a_label: string;
	b_label: string;
	columns: CompareColumn[];
	rows: CompareRow[];
	summary: CompareSummary;
	warnings: string[];
}
