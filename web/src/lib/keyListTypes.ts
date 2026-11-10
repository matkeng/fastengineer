// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.keylists.
export const AREA_TYPES = ['WBS', 'Area', 'Building', 'Room', 'Panel'] as const;
export type AreaType = (typeof AREA_TYPES)[number];

export interface PlantArea { id: string; parent_id: string | null; wbs: string; tag: string; description: string; area_type: AreaType }
export interface PlantAreaList { nodes: PlantArea[]; updated_at: string | null }
export const PACKAGE_TYPES = ['Vendor', 'Client', 'SWR Supplier', 'Valves', 'Instrumentation', 'Large Mech', 'Installer', 'Other'] as const;
export type PackageType = (typeof PACKAGE_TYPES)[number];

export interface EquipmentPackage { id: string; number: string; description: string; vendor: string; package_type: PackageType }
/** A kind of equipment supplied in a package; package_id is the id of its EquipmentPackage. */
export interface EquipmentType { id: string; package_id: string; name: string; description: string }
export interface EquipmentPackageList { items: EquipmentPackage[]; types: EquipmentType[]; updated_at: string | null }

export type KeyListId = 'plant-areas' | 'equipment-packages';
export interface KeyListOverview {
	plant_areas: { items: number; depth: number };
	area_types: string[];
	equipment_packages: { items: number; types: number };
	package_types: string[];
}

/** The type a new item under `parent` starts with: the next one down (a suggestion, not a rule). */
export function nextAreaType(parent?: AreaType): AreaType {
	if (!parent) return AREA_TYPES[0];
	return AREA_TYPES[Math.min(AREA_TYPES.indexOf(parent) + 1, AREA_TYPES.length - 1)];
}

export function plantAreaMatches(n: PlantArea, filter: string): boolean {
	const f = filter.trim().toLowerCase();
	return !f || [n.tag, n.description, n.wbs, n.area_type].some((s) => s.toLowerCase().includes(f));
}

type Rule<T> = readonly [field: keyof T & string, label: string, required: boolean];

/** Required fields must be filled in and no value is used twice: field key -> message. */
function uniqueProblems<T extends { id: string }>(items: T[], rules: readonly Rule<T>[]): Record<string, string> {
	const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
	const out: Record<string, string> = {};
	for (const [field, label, required] of rules) {
		const seen = new Set<string>();
		for (const it of items) {
			const v = key(String(it[field] ?? ''));
			if (!v) {
				if (required) out[`${it.id}.${field}`] = `${label} is required`;
			} else if (seen.has(v)) out[`${it.id}.${field}`] = `${label} is used twice`;
			else seen.add(v);
		}
	}
	return out;
}

/** The same rules as the engine's check_plant_areas, for live feedback. */
export function plantAreaProblems(nodes: PlantArea[]): Record<string, string> {
	return uniqueProblems(nodes, [['tag', 'Tag number', true], ['description', 'Description', true], ['wbs', 'WBS number', false]]);
}

/** The same rules as the engine's check_equipment_packages, for live feedback. */
export function equipmentPackageProblems(items: EquipmentPackage[], types: EquipmentType[] = []): Record<string, string> {
	const out = {
		...uniqueProblems(items, [['number', 'Package number', true], ['description', 'Description', true]]),
		...uniqueProblems(types, [['name', 'Name', true]]),
	};
	const ids = new Set(items.map((p) => p.id));
	for (const t of types) if (!ids.has(t.package_id)) out[`${t.id}.package`] = 'Its package is not in the list';
	return out;
}

const includes = (texts: string[], filter: string) => {
	const f = filter.trim().toLowerCase();
	return !f || texts.some((s) => s.toLowerCase().includes(f));
};
export const equipmentPackageMatches = (p: EquipmentPackage, filter: string) => includes([p.number, p.description, p.vendor, p.package_type], filter);
export const equipmentTypeMatches = (t: EquipmentType, filter: string) => includes([t.name, t.description], filter);
