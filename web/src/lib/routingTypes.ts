// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.keylists.cable_routing.

export const MAX_NODES = 999;

export interface Placement { id: string; tag: string; description: string; source: string | null; x: number; y: number; w: number; h: number }
export interface RouteNode { id: string; tag: string; x: number; y: number }
export interface End { kind: 'node' | 'equipment'; id: string }
export interface LadderOverride { width_mm: number | null; max_kg_per_m: number | null }
export interface Segment {
	id: string;
	tag: string;
	a: End;
	b: End;
	/** The corners of a polyline, from a to b. */
	bends: [number, number][];
	length_m: number | null;
	ladders: Record<string, LadderOverride>;
}
export interface Service {
	id: string;
	name: string;
	colour: string;
	spacing_factor: number;
	max_layers: number;
	spare_pct: number;
	widths_mm: number[];
	max_kg_per_m: number | null;
}
export type RuleField = 'application' | 'type' | 'voltage' | 'code' | 'description';
export const RULE_FIELDS: Record<RuleField, string> = { type: 'Type', application: 'Application', voltage: 'Voltage', code: 'Code', description: 'Description' };
export interface ServiceRule { id: string; field: RuleField; contains: string; service_id: string }
export interface Allowance {
	apply_to_master: boolean;
	tail_from_m: number;
	tail_to_m: number;
	contingency_pct: number;
	round_up_to_m: number;
	route_column: 'never' | 'when blank' | 'always';
}
export interface CableOverride { via: string[]; avoid: string[] }
export interface CableRouting {
	placements: Placement[];
	nodes: RouteNode[];
	segments: Segment[];
	services: Service[];
	service_rules: ServiceRule[];
	default_service_id: string;
	allowance: Allowance;
	/** Cable number (lower case, single spaces) -> its own route. */
	overrides: Record<string, CableOverride>;
	next_node: number;
	next_segment: number;
	grid: number;
	updated_at: string | null;
}

export interface EquipmentChoice { tag: string; description: string; source: string; placed: boolean }
export interface Endpoint { tag: string; cables: number; in_equipment_list: boolean }
export type CableStatus = 'ok' | 'from not placed' | 'to not placed' | 'same equipment' | 'no route' | 'missing lengths';
export interface CableRoute {
	row: number;
	key: string;
	number: string;
	from_tag: string;
	to_tag: string;
	cable_code: string;
	service_id: string;
	od_mm: number | null;
	mass_kg_per_m: number | null;
	status: CableStatus;
	overridden: boolean;
	segments: string[];
	nodes: string[];
	route: string;
	route_m: number | null;
	length_m: number | null;
}
export interface ServiceLoad {
	service_id: string;
	cables: number;
	trefoils: number;
	sum_od_mm: number;
	required_mm: number;
	width_mm: number | null;
	ladders: number;
	fill_pct: number | null;
	kg_per_m: number;
	max_kg_per_m: number | null;
	missing_od: string[];
	missing_mass: string[];
	flags: string[];
}
export interface SegmentLoad {
	id: string;
	tag: string;
	length_m: number | null;
	cables: number[];
	services: ServiceLoad[];
	width_mm: number;
	kg_per_m: number;
	worst: '' | 'ok' | 'full' | 'over';
}
export interface RoutingView {
	doc: CableRouting;
	errors: Record<string, string>;
	warnings: string[];
	equipment: EquipmentChoice[];
	unplaced: Endpoint[];
	cables: CableRoute[];
	segments: SegmentLoad[];
}

/** What is selected on the map. */
export interface Selection { kind: 'node' | 'equipment' | 'segment' | 'cable'; id: string }
