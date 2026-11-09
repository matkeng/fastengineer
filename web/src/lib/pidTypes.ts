// Mirrors workbench_core.pid.models. Boxes are [x1, y1, x2, y2] in page-image pixels (200 DPI).
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

export interface Drawing {
	id: string;
	file_name: string;
	drawing_type: string;
	block_set: string;
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
	desc: string;
	drawing_type: string;
	block_set: string;
	priority: number;
	active: boolean;
	threshold: number;
	buffer_space: number;
	use_mask: boolean;
	variants: Variants;
	scales: number[];
	max_hits: number;
	tag_format: string;
	points: TagPoint[];
	width: number;
	height: number;
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
}

export interface FoundTag {
	tag: string;
	function: string;
	loop: string;
	suffix: string;
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
}

export interface Exclusion { words: string[]; areas: Box[] }

export interface Settings {
	tag_pattern: string;
	pattern_scan: boolean;
	min_pdf_words: number;
	exclusions: Record<string, Exclusion>;
}

export interface RunInfo {
	id: string;
	doc_ids: string[];
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

export interface Library { drawing_type: string; block_set: string; templates: number; drawings: number }
export interface OcrStatus { available: boolean; engine: string | null; reason: string | null }
export interface TagsTable { headers: string[]; rows: Record<string, string>[] }
export interface TestResult { symbols: Symbol[]; best: number; skipped: string | null }

export const libKey = (o: { drawing_type: string; block_set: string }) => `${o.drawing_type}/${o.block_set}`;
