// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.keylists.
import type { Catalogue, Finding, HardwareSummary } from './genTypes';
export const AREA_TYPES = ['WBS', 'Area', 'Building', 'Room', 'Panel'] as const;
export type AreaType = (typeof AREA_TYPES)[number];

export interface PlantArea { id: string; parent_id: string | null; wbs: string; tag: string; description: string; area_type: AreaType }
export interface PlantAreaList { nodes: PlantArea[]; updated_at: string | null }
export const PACKAGE_TYPES = ['Vendor', 'Client', 'SWR Supplier', 'Valves', 'Instrumentation', 'Large Mech', 'Installer', 'Other'] as const;
export type PackageType = (typeof PACKAGE_TYPES)[number];

export interface EquipmentPackage { id: string; number: string; description: string; vendor: string; package_type: PackageType }
/** A kind of equipment supplied in a package; package_id is the id of its EquipmentPackage. */
export interface EquipmentType {
	id: string; package_id: string; name: string; description: string;
	/** Predefined rows per deliverable list, as a load type has them: what the Instrument generator adds for each runsheet row of the type. */
	rows: TemplateRows;
}
export interface EquipmentPackageList { items: EquipmentPackage[]; types: EquipmentType[]; updated_at: string | null }

export const RATING_UNITS = ['kW', 'Amps'] as const;
export type RatingUnit = (typeof RATING_UNITS)[number];
export const PHASES = ['AC-3-phase', 'AC-3-phase+N', 'AC-1-phase-LN', 'AC-1-phase-LL', 'DC', 'DC-mA'] as const;
export type Phases = (typeof PHASES)[number];

/** A file attached to a row: the engine keeps the file and fills this in. */
export interface AttachedFile { file_name: string; size: number; pages: number; uploaded_at: string }

/** A row of the Load Types list. from_value/to_value are exact decimals kept as text. */
export interface LoadType {
	id: string; code: string; name: string; rating_unit: RatingUnit; voltage: number; phases: Phases;
	from_value: string | null; to_value: string | null; std_drg: string; bucket_type: string; load_type: string;
	field_options: string; multi_load: boolean; load_qty: number | null; pdf: AttachedFile | null;
	/** Predefined rows per deliverable list (key -> rows of column name -> text with <<tags>>). */
	rows: TemplateRows;
}
/** A load type's predefined rows: list key -> rows; a row is column name -> text. */
export type TemplateRows = Record<string, Record<string, string>[]>;
/** The deliverable lists a load type has rows for, and the tags a row can use. */
export interface TemplateLists { lists: { key: string; name: string; columns: string[]; settings: { name: string; values: string[] }[] }[]; tags: { tag: string; meaning: string }[];
	/** The tags an equipment type's rows can use: the columns of the Instrument Runsheet. */
	instrument_tags: { tag: string; meaning: string }[] }
export interface LoadTypeList { items: LoadType[]; updated_at: string | null }
/** A load type as it is typed into the form: numbers are text until the engine converts them. */
export interface LoadTypeForm {
	id: string; code: string; name: string; rating_unit: RatingUnit | ''; voltage: string; phases: Phases | '';
	from_value: string; to_value: string; std_drg: string; bucket_type: string; load_type: string;
	field_options: string; multi_load: boolean; load_qty: string; rows: TemplateRows;
}
export type LoadTypeField = Exclude<keyof LoadTypeForm, 'id' | 'rows'>;

export type KeyListId = 'plant-areas' | 'equipment-packages' | 'load-types' | 'load-list' | 'eel' | 'plc' | 'cable-types' | 'distribution-panels' | 'instrument-runsheet' | 'mel' | 'master' | 'enums' | 'drawing-list' | CodeListId;

/** A cable type; every project starts with a default set. `sort` orders the list. */
export interface CableType {
	id: string; code: string; application: string; type: string; cores: string; diameter: string; voltage: string;
	/** Core insulation (PVC, XLPE…): a load's cable is matched on it. */
	insulation: string;
	description: string; sort: number | null;
}
export interface CableTypeList { items: CableType[]; updated_at: string | null }
/** As typed into the form (sort is text until the engine converts it). */
export type CableTypeForm = Omit<CableType, 'sort'> & { sort: string };

/** The PLC List: systems -> racks -> cards (by slot) -> IO points (one per channel, from 0). */
export interface IoPoint { channel: number; tag: string; description: string; spare: boolean }
export interface PlcCard { id: string; card_type_id: string; tag: string; spare: boolean; notes: string; points: IoPoint[] }
export interface PlcRack {
	id: string; tag: string; plant_area_id: string | null; rack_type_id: string; description: string; first_slot: number;
	cards: (PlcCard | null)[];
}
export interface PlcSystem { id: string; tag: string; description: string; manufacturer: string; model: string; racks: PlcRack[] }
export interface PlcList { systems: PlcSystem[]; updated_at: string | null }
export interface PlcView {
	plc: PlcList; catalogue: Catalogue; errors: Record<string, string>; findings: Finding[]; summary: HardwareSummary;
	plant_areas: { id: string; label: string; depth: number }[];
}
export interface PlcImportPreview {
	systems: number; racks: number; cards: number; tagged_points: number; card_types: number; rack_types: number;
	notes: string[]; applied: boolean;
}

/** An item of the Electrical Equipment List (references are ids in the other lists). */
export interface EelItem {
	id: string; tag: string; description: string; equipment_code_id: string; plant_area_id: string;
	vendor_package_id: string | null; load_type_id: string | null; rating: string | null; rating_unit: RatingUnit | null;
	voltage: number | null; phases: Phases | null; is_panel: boolean; supplied_from: string | null;
	manufacturer: string; model_number: string; supplied_by_id: string | null; installed_by_id: string | null; terminated_by_id: string | null;
}
/** An item as typed into the form: numbers are text until the engine converts them. */
export type EelForm = Omit<EelItem, 'rating' | 'voltage'> & { rating: string; voltage: string };
export interface EelChoice { id: string; label: string; depth: number }
export interface EelView {
	items: EelItem[];
	choices: {
		equipment_codes: EelChoice[]; packages: EelChoice[]; plant_areas: EelChoice[]; supplies: EelChoice[];
		load_types: (EelChoice & { rating_unit: RatingUnit; voltage: number; phases: Phases })[];
	};
	clashes: Record<string, string[]>; // item id -> imports that have its tag too
	updated_at: string | null;
}
export const EEL_SOURCE = 'eel';

/** The same rules as the engine's check_eel (the import-tag check is the engine's), for the form. */
export function eelProblems(f: EelForm, others: EelItem[]): Record<string, string> {
	const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
	const out: Record<string, string> = {};
	if (!key(f.tag)) out.tag = 'Tag number is required';
	else if (others.some((o) => key(o.tag) === key(f.tag))) out.tag = 'Tag number is used by another item';
	if (!key(f.description)) out.description = 'Description is required';
	if (!f.equipment_code_id) out.equipment_code_id = 'Equipment type is required';
	if (!f.plant_area_id) out.plant_area_id = 'Plant area is required';
	const v = f.voltage.trim().replace(/,/g, '');
	if (v && !/^\d+(\.0*)?$/.test(v)) out.voltage = /^-/.test(v) ? "Can't be negative" : 'Not a whole number';
	const r = f.rating.trim().replace(/,/g, '');
	if (r && !/^[+-]?(\d+\.?\d*|\.\d+)$/.test(r)) out.rating = 'Not a number';
	if (f.supplied_from === `${EEL_SOURCE}/${f.id}`) out.supplied_from = "An item can't be supplied from itself";
	return out;
}

/** Equipment Codes and Instrument Codes: code, name, description and one more field. */
export type CodeListId = 'equipment-codes' | 'instrument-codes';
/** A discipline's code. The disciplines are the project's Disciplines enum (the key lists overview has them). */
export type Discipline = string;
export interface CodeRow { id: string; code: string; name: string; description: string; disciplines?: Discipline[]; plc_code?: string }
export interface CodeList { items: CodeRow[]; updated_at: string | null }

/** The same rules as the engine's check_code_list, for the form. */
export function codeRowProblems(row: CodeRow, others: CodeRow[]): Partial<Record<'code' | 'name', string>> {
	const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
	const out: Partial<Record<'code' | 'name', string>> = {};
	for (const [f, label] of [['code', 'Code'], ['name', 'Name']] as const) {
		if (!key(row[f])) out[f] = `${label} is required`;
		else if (others.some((o) => key(o[f]) === key(row[f]))) out[f] = `${label} is used by another row`;
	}
	return out;
}

/** A Load List row: an import's row, remembered by (import, key), with its two allocations.
 *  "auto" allocations come from the row's area / load type text; "user" ones a person chose. */
export interface LoadListRow {
	recipe_id: string; key: string; source: string; target: string;
	values: Record<string, string | number | boolean | null>;
	status: 'active' | 'deleted'; deleted_reason: string;
	plant_area_id: string | null; plant_area_by: 'auto' | 'user' | null;
	load_type_id: string | null; load_type_by: 'auto' | 'user' | null;
	/** A distribution panel: other rows can be supplied from it. */
	is_panel: boolean; is_panel_by: 'auto' | 'user' | null;
	/** PRIMARY_SUPPLY, a panel row's rowRef(), or null (not set). */
	supplied_from: string | null; supplied_from_by: 'auto' | 'user' | null;
	/** The load's power cable, typed in (sizing is done elsewhere); the cable schedule finds the cable type from these. */
	cable_length: number | null; cable_construction: CableConstruction | null; cable_parallel: number | null;
	cable_insulation: string; cable_size: string; earth_size: string;
	updated_at: string | null;
}
export const PRIMARY_SUPPLY = 'primary';
/** How rows refer to each other (import ids have no "/"). */
export type CableConstruction = 'Multicore' | 'Single core';
export type CableDetails = Pick<LoadListRow, 'cable_length' | 'cable_construction' | 'cable_parallel' | 'cable_insulation' | 'cable_size' | 'earth_size'>;
/** A load's cable in a few words, e.g. "2 × 50 XLPE, 120 m" (blank when nothing is set). */
export function cableSummary(r: CableDetails): string {
	const parts = [r.cable_size ? `${(r.cable_parallel ?? 1) > 1 ? `${r.cable_parallel} × ` : ''}${r.cable_size} mm²` : (r.cable_parallel ?? 1) > 1 ? `${r.cable_parallel} ×` : '',
		r.cable_insulation, r.cable_construction === 'Single core' ? `single core${r.earth_size ? ` + ${r.earth_size} E` : ''}` : ''].filter(Boolean).join(' ');
	return [parts, r.cable_length != null ? `${r.cable_length} m` : ''].filter(Boolean).join(', ');
}
export const rowRef = (r: Pick<LoadListRow, 'recipe_id' | 'key'>) => `${r.recipe_id}/${r.key}`;
export const rowTag = (r: LoadListRow) => (r.values.tag != null && r.values.tag !== '' ? String(r.values.tag) : r.key);
export interface LoadListChoice { id: string; label: string; depth: number }
export interface LoadListView {
	fields: string[]; rows: LoadListRow[];
	sources: { id: string; name: string; target: string; rows: number; has_file: boolean }[];
	plant_areas: LoadListChoice[]; load_types: LoadListChoice[]; warnings: string[];
	/** The choices for a load's cable, from the Cable Types list. */
	cable_insulations: string[]; cable_sizes: string[]; earth_sizes: string[];
}
export type Allocation = { plant_area_id?: string | null; load_type_id?: string | null; is_panel?: boolean; supplied_from?: string | null } & Partial<CableDetails>;
export interface KeyListOverview {
	plant_areas: { items: number; depth: number };
	area_types: string[];
	equipment_packages: { items: number; types: number };
	package_types: string[];
	load_types: { items: number };
	load_list: { rows: number; unallocated: number };
	equipment_codes: { items: number };
	eel: { items: number };
	cable_types: { items: number };
	distribution_panels: { items: number };
	instrument_runsheet: { items: number };
	mel: { items: number };
	drawing_list: { items: number };
	enums: { items: number };
	/** The project's Disciplines enum. */
	disciplines: { code: string; name: string }[];
	plc: { systems: number; racks: number; cards: number };
	instrument_codes: { items: number };
	rating_units: string[];
	phases: string[];
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

/** The same rules as the engine's check_load_types, for the form: field -> message. */
export function loadTypeProblems(f: LoadTypeForm, others: LoadType[]): Partial<Record<LoadTypeField, string>> {
	const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
	const out: Partial<Record<LoadTypeField, string>> = {};
	if (!key(f.code)) out.code = 'Code is required';
	else if (others.some((o) => key(o.code) === key(f.code))) out.code = 'Code is used by another load type';
	if (!key(f.name)) out.name = 'Name is required';
	else if (others.some((o) => key(o.name) === key(f.name))) out.name = 'Name is used by another load type';
	if (!f.rating_unit) out.rating_unit = 'Choose kW or Amps';
	if (!f.phases) out.phases = 'Choose the phases';
	const whole = (field: 'voltage' | 'load_qty', label: string, required: boolean) => {
		const t = f[field].trim().replace(/,/g, '');
		if (!t) {
			if (required) out[field] = `${label} is required`;
		} else if (!/^[+-]?\d+(\.0*)?$/.test(t)) out[field] = 'Not a whole number';
		else if (Number(t) < 0) out[field] = "Can't be negative";
	};
	whole('voltage', 'Voltage', true);
	whole('load_qty', 'Load qty', false);
	const decimal = (field: 'from_value' | 'to_value'): number | null => {
		const t = f[field].trim().replace(/,/g, '');
		if (!t) return null;
		if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(t)) {
			out[field] = 'Not a number';
			return null;
		}
		return Number(t);
	};
	const from = decimal('from_value');
	const to = decimal('to_value');
	if (from !== null && to !== null && from > to) out.to_value = 'Must not be less than the From value';
	return out;
}

/** "1.2 MB", "350 KB" */
export function fileSize(bytes: number): string {
	if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
	return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** The project's Enums: the choice lists other lists pick from (mirrors keylists.enums). */
export interface EnumItem { id: string; code: string; name: string }
export type EnumKey = 'disciplines' | 'drawing_types' | 'drawing_statuses';
export interface ProjectEnums { disciplines: EnumItem[]; drawing_types: EnumItem[]; drawing_statuses: EnumItem[]; updated_at: string | null }
export interface EnumsView { enums: ProjectEnums; titles: Record<EnumKey, string>; need_code: EnumKey[]; in_use: Record<string, number> }
export const enumLabel = (i: EnumItem) => i.code || i.name;

/** A drawing of the Drawing List, as text (mirrors drawing_list_api.DrawingRow). */
export type DrawingChoice = 'discipline' | 'drawing_type' | 'status';
export interface DrawingRow {
	id: string; number: string; project_name: string; title_1: string; title_2: string; title_3: string;
	discipline: string; discipline_id: string | null; drawing_type: string; drawing_type_id: string | null; revision: string;
	status: string; status_id: string | null; issue_date: string; vendor_drg_number: string; vendor_reference: string;
	equipment_reference: string; scope: string; unknown_equipment: string[];
}
export interface DrawingsView { items: DrawingRow[]; columns: { field: string; heading: string }[]; choices: Record<DrawingChoice, EnumItem[]>; updated_at: string | null }
