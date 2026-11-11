// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.keylists.distribution_panels and panel_calc.
import type { LoadListChoice } from './keyListTypes';

export type PanelPhaseType = 'three-phase' | 'single-phase';
export type PanelViewKind = 'switchboard' | 'sld';
export type Pole = 'R' | 'W' | 'B';
export const POLES: Pole[] = ['R', 'W', 'B'];
export const PHASE_NAMES: Record<string, string> = { R: 'Red', W: 'White', B: 'Blue', '': '' };
export type EntryKind = 'load' | 'spare_cb' | 'rcd' | 'light_control' | 'other';
export const KIND_NAMES: Record<EntryKind, string> = {
	load: 'A load of the Load List', spare_cb: 'Spare circuit breaker', rcd: 'RCD RTS', light_control: 'Lighting control circuit', other: 'Something else',
};

/** One pole row of an entry. Blank quantity: 1. Blank watts: from the load's rating. */
export interface PoleValues { cb_rating: number | null; qty: number | null; watts_each: number | null }
export interface PanelEntry {
	id: string; way: number; pole: Pole | null; poles: 1 | 3; kind: EntryKind; load_ref: string | null;
	description: string; load_type: string; rows: PoleValues[];
}
/** A heading across the schedule above ways before_way and before_way + 1. */
export interface PanelDivider { id: string; before_way: number; label: string }
export interface DistributionPanel {
	id: string; load_ref: string | null; tag: string; title: string; phase_type: PanelPhaseType; view: PanelViewKind; ways: number;
	voltage: number; power_factor: number; isolator_rating: number; upstream_cb: number;
	entries: PanelEntry[]; dividers: PanelDivider[];
}
export interface DistributionPanelList { panels: DistributionPanel[]; updated_at: string | null }

export interface PanelTotals {
	phases: string[]; phase_w: number[]; phase_kva: number[]; phase_amps: number[];
	max_amps: number; total_kw: number; remaining_amps: number; remaining_pct: number | null; max_kva: number;
}
/** One row of the schedule, worked out by the engine. */
export interface PoleRow {
	circuit: string; way: number; pole: string; side: 'Left' | 'Right'; entry_id: string | null; index: number; span: number;
	kind: string; tag: string; description: string; load_type: string; qty: number | null; watts_each: number | null;
	qty_default: boolean; watts_default: boolean; total_w: number; cb_rating: number | null; section: string; problem: string;
}
export interface UnplacedLoad { ref: string; tag: string; description: string; load_type: string; poles: number; watts: number | null }
export interface PanelSchedule {
	panel_id: string; tag: string; title: string; phase_type: PanelPhaseType; rows: PoleRow[]; totals: PanelTotals;
	unplaced: UnplacedLoad[]; findings: string[];
}
export interface PanelsView {
	doc: DistributionPanelList; schedules: Record<string, PanelSchedule>; errors: Record<string, string>;
	load_panels: LoadListChoice[]; cb_ratings: number[]; kinds: Record<string, string>; spare_space: string;
}

/** A number for the schedule: no trailing zeros, at most `digits` decimals. */
export function fmt(v: number | null | undefined, digits = 1): string {
	if (v === null || v === undefined || Number.isNaN(v)) return '';
	return String(Number(v.toFixed(digits)));
}
