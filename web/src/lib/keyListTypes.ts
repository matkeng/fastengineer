// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.keylists.
export const AREA_TYPES = ['WBS', 'Area', 'Building', 'Room', 'Panel'] as const;
export type AreaType = (typeof AREA_TYPES)[number];

export interface PlantArea { id: string; parent_id: string | null; wbs: string; tag: string; description: string; area_type: AreaType }
export interface PlantAreaList { nodes: PlantArea[]; updated_at: string | null }
export interface KeyListOverview { plant_areas: { items: number; depth: number }; area_types: string[] }

/** The type a new item under `parent` starts with: the next one down (a suggestion, not a rule). */
export function nextAreaType(parent?: AreaType): AreaType {
	if (!parent) return AREA_TYPES[0];
	return AREA_TYPES[Math.min(AREA_TYPES.indexOf(parent) + 1, AREA_TYPES.length - 1)];
}

export function plantAreaMatches(n: PlantArea, filter: string): boolean {
	const f = filter.trim().toLowerCase();
	return !f || [n.tag, n.description, n.wbs, n.area_type].some((s) => s.toLowerCase().includes(f));
}

/** The same rules as the engine's check_plant_areas, for live feedback: field key -> message. */
export function plantAreaProblems(nodes: PlantArea[]): Record<string, string> {
	const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
	const out: Record<string, string> = {};
	const rules = [['tag', 'Tag number', true], ['description', 'Description', true], ['wbs', 'WBS number', false]] as const;
	for (const [field, label, required] of rules) {
		const seen = new Set<string>();
		for (const n of nodes) {
			const v = key(n[field]);
			if (!v) {
				if (required) out[`${n.id}.${field}`] = `${label} is required`;
			} else if (seen.has(v)) out[`${n.id}.${field}`] = `${label} is used twice`;
			else seen.add(v);
		}
	}
	return out;
}
