// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.symbols.models. Boxes are [x1, y1, x2, y2] in page-image pixels (200 DPI).
export type Box = [number, number, number, number];
export type TextSource = 'pdf' | 'ocr' | 'none';

export interface Word { text: string; box: Box; block: number; line: number; word_no: number }

export interface PageInfo {
	n: number;
	width_px: number;
	height_px: number;
	rotation: number;
	text_source: TextSource;
	word_count: number;
	warnings: string[];
}

export interface Exclusion { words: string[]; areas: Box[] }

export interface Library {
	id: string;
	name: string;
	description: string;
	tag_pattern: string;
	tag_format: string;
	pattern_scan: boolean;
	scan_stacked: boolean;
	min_pdf_words: number;
	default_threshold: number;
	exclusion: Exclusion;
	created_at: string | null;
}

export interface LibrarySummary extends Library { templates: number; drawings: number; columns: string[] }

export type MaskMode = 'auto' | 'custom' | 'none';

export interface Drawing {
	id: string;
	file_name: string;
	library_id: string;
	force_ocr: boolean;
	pages: PageInfo[];
	status: 'rendering' | 'ready' | 'error';
	error: string | null;
	uploaded_at: string | null;
}

export interface TagPoint { name: string; x: number; y: number; min_overlap: number }
export interface Variants { rot90: boolean; rot180: boolean; rot270: boolean; mirror: boolean }

export interface Template {
	id: string;
	library_id: string;
	desc: string;
	priority: number;
	active: boolean;
	threshold: number;
	mask_mode: MaskMode;
	buffer_space: number;
	variants: Variants;
	scales: number[];
	max_hits: number;
	tag_format: string;
	points: TagPoint[];
	width: number;
	height: number;
	has_custom_mask: boolean;
}

export interface PageOverride { template_id: string; threshold: number | null; ignore: boolean }

export interface Symbol {
	template_id: string;
	template_desc: string;
	box: Box;
	score: number;
	variant: string;
	parts: Record<string, string | null>;
	tag: string | null;
	origin: 'auto' | 'manual';
	tag_override: string | null;
}

export interface FoundTag {
	tag: string;
	groups: Record<string, string>;
	source: 'template' | 'pattern';
	template_desc: string;
	box: Box;
	page: number;
}

export interface SkippedTemplate { template_id: string; desc: string; hits: number; reason: string }

export interface PageResult {
	page: number;
	text_source: TextSource;
	symbols: Symbol[];
	tags: FoundTag[];
	skipped: SkippedTemplate[];
	warnings: string[];
	rejected_symbols: Symbol[];
	rejected_tags: FoundTag[];
}

/** A detection marked as a false positive; matched to later detections by box overlap. */
export interface Rejection { kind: 'symbol' | 'tag'; box: Box; template_id: string | null; tag: string | null }
/** The user's corrections to one drawing page, re-applied on every analysis. */
export interface PageReview { rejected: Rejection[]; added: Symbol[] }

export type ReviewAction =
	| { action: 'reject' | 'restore'; kind: 'symbol' | 'tag'; box: Box; template_id?: string | null; tag?: string | null }
	| { action: 'add'; template_id: string; x: number; y: number; tag?: string | null }
	| { action: 'tag'; box: Box; tag: string | null };

export interface ReviewResult { result: PageResult; review: PageReview; symbol: Symbol | null }

/** One page an analysis run looked at. */
export interface RunSheet {
	doc_id: string | null;
	file_name: string;
	page: number;
	symbols: number;
	tags: number;
	rejected: number;
	added: number;
}

export interface RunInfo {
	id: string;
	doc_ids: string[];
	columns: string[];
	status: 'queued' | 'running' | 'done' | 'cancelled' | 'error';
	done_steps: number;
	total_steps: number;
	current: string;
	started_at: string | null;
	finished_at: string | null;
	warnings: string[];
	error: string | null;
	tag_count: number;
}

export interface OcrStatus { available: boolean; engine: string | null; reason: string | null }
export interface TagsTable { headers: string[]; rows: Record<string, string>[] }
export interface TestResult { symbols: Symbol[]; best: number; skipped: string | null }

/** What New template would cut from a dragged box (nothing saved). */
export interface TemplatePreview { rect: Box; width: number; height: number; png: string; view_png?: string; words: Word[] }
