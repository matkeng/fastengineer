// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors desktop/engine/workbench_desktop/dashboard_api.py.
export interface DashEvent {
	kind: 'run' | 'drawing' | 'revision' | 'recipe' | 'enum' | 'tree' | 'table' | 'generator' | 'build';
	section: 'symbols' | 'mel' | 'ref' | 'generators';
	id: string;
	title: string;
	detail: string;
	at: string;
}
export interface RunBar { id: string; at: string; template: number; text_scan: number; status: string }
export interface DashCounts {
	libraries: number; templates: number; drawings: number; pages: number; pages_unanalysed: number; runs: number;
	latest_tags: number | null; latest_run_at: string | null; recipes: number; revisions: number;
	latest_revision_at: string | null; enums: number; trees: number; tables: number; rows: number; plant_areas: number; equipment_packages: number; equipment_types: number; load_types: number; load_list_rows: number; equipment_codes: number; instrument_codes: number; open_workbooks: number;
	generators: number; gen_builds: number; latest_build_at: string | null; plc_panels: number; plc_cards: number;
}
export interface DashStorage {
	data_dir: string; database_bytes: number; drawings_bytes: number; page_images: number;
	ocr_available: boolean; ocr_engine: string | null; ocr_reason: string | null;
}
export interface Dashboard { counts: DashCounts; recent: DashEvent[]; runs: RunBar[]; storage: DashStorage }
