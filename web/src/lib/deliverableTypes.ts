// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.deliverables and the deliverables API.
import type { BuildInfo, BuildResult, ChangeEntry } from './genTypes';

export interface Deliverable {
	id: string; type: string; name: string; doc_number: string; doc_title: string;
	/** 'project': generated from the Project Load List and the load types' rows; 'generator': a generator's builds. */
	source: 'generator' | 'project' | 'panel'; generator_id: string;
	/** 'panel': the schedule of this panel of the Distribution Panels list. */
	panel_id: string;
	filter_column: string; filter_values: string[];
	/** The columns to keep, in the order to show them. Empty: every column, in the content's order. */
	columns: string[];
	updated_at: string | null;
}
export interface RevisionInfo {
	id: string; deliverable_id: string; letter: string; issued_at: string; issued_by: string; description: string;
	build_seq: number; rows: number; added: number | null; removed: number | null; changed: number | null;
}
export interface Changes { added: number; removed: number; changed: number; entries: ChangeEntry[] }
export interface Revision {
	info: RevisionInfo; result: BuildResult; diff_key: string; doc_number: string; doc_title: string;
	filter_column: string; filter_values: string[]; changes: Changes | null;
	/** Label and value lines frozen with the content (a distribution panel's header block). */
	summary: SummaryLine[];
}
/** What changed from one issued revision (old) to a later one (new). */
export interface Comparison { old: RevisionInfo; new: RevisionInfo; changes: Changes }
export type SummaryLine = [string, string | number | null];
export const PANEL_TYPE = 'Distribution Panel';
export interface PanelChoice { id: string; tag: string; title: string }
export interface DeliverableSummary { deliverable: Deliverable; generator: string; latest: RevisionInfo | null; revisions: number }
export interface GeneratorChoice { id: string; name: string; columns: string[]; builds: number }
export interface DeliverablesOverview { types: string[]; deliverables: DeliverableSummary[]; generators: GeneratorChoice[];
	/** Deliverable type -> the columns of the list generated from the Project Load List. */
	project_columns: Record<string, string[]>;
	/** The Distribution Panels list (what a Distribution Panel deliverable can issue). */
	panels: PanelChoice[];
}
export interface Current {
	build: BuildInfo | null; stale: boolean; rows: number; next_letter: string; changes: Changes | null;
	problem: string | null; result: BuildResult | null;
	source: 'generator' | 'project' | 'panel'; warnings: string[]; summary: SummaryLine[];
}
export interface DeliverableDetail {
	deliverable: Deliverable; generator: string; revisions: RevisionInfo[]; builds: BuildInfo[]; current: Current;
}
/** A deliverable as edited in the form (the filter values as one line of text). */
export type DeliverableForm = Omit<Deliverable, 'filter_values' | 'updated_at'> & { filter_text: string };
