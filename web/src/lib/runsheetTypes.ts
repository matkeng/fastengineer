// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.keylists.instrument_runsheet and the MEL list of loadlist_api.

/** A row of the Instrument Runsheet as it is typed: one text per column. */
export interface TypedRow { id: string; cells: string[] }
export interface RunsheetColumn { key: string; heading: string; tag: string }
export interface RunsheetView {
	rows: TypedRow[]; columns: RunsheetColumn[];
	/** What the three reference columns can be. */
	equipment_types: string[]; areas: string[]; parents: string[];
	errors: Record<string, string>; updated_at: string | null;
	/** The most number columns (#1, #2, ...) a runsheet can have. `columns` has 35, or as many as the widest saved row uses. */
	max_numbers: number;
}
/** The columns before the numbers. */
export const FIXED_COLUMNS = 8;
export const numberColumn = (n: number): RunsheetColumn => ({ key: String(n), heading: `#${n}`, tag: `<<#${n}>>` });

export interface MelRow { source: string; recipe_id: string; key: string; tag: string; in_load_list: boolean; values: Record<string, string> }
export interface MelList { headers: string[]; rows: MelRow[]; sources: { id: string; name: string; rows: number; has_file: boolean }[]; warnings: string[] }

/** As the engine compares names: case and extra spaces don't count. */
export const nameKey = (s: string) => s.trim().replace(/\s+/g, ' ').toLowerCase();
const TRUE = ['true', 'yes', 'y', '1', 'x'];
const FALSE = ['false', 'no', 'n', '0', ''];
const blank = (r: TypedRow) => !r.cells.some((c, i) => i !== 6 && (c ?? '').trim());

/** What stops the rows being saved, as the engine checks it: `<row id>.<column key>` -> message. A blank row is ignored. */
export function runsheetProblems(rows: TypedRow[], view: RunsheetView): Record<string, string> {
	const known = [view.equipment_types, view.areas, view.parents].map((list) => new Set(list.map(nameKey)));
	const what = [
		['equipment_type', 'Equipment Type Ref', 'an equipment type of Equipment Packages'],
		['area', 'Area Ref', "a plant area's tag number"],
		['parent', 'Parent Equipment Ref', 'a tag in the Electrical Equipment List or the MEL'],
	];
	const out: Record<string, string> = {};
	for (const r of rows) {
		if (blank(r)) continue;
		what.forEach(([key, label, where], i) => {
			const v = (r.cells[i] ?? '').trim();
			if (!v) out[`${r.id}.${key}`] = `${label} is required`;
			else if (!known[i].has(nameKey(v))) out[`${r.id}.${key}`] = `'${v}' is not ${where}`;
		});
		const flag = (r.cells[6] ?? '').trim().toLowerCase();
		if (!TRUE.includes(flag) && !FALSE.includes(flag)) out[`${r.id}.confirmed`] = 'Confirmed is TRUE or FALSE';
	}
	return out;
}
export const filledRows = (rows: TypedRow[]) => rows.filter((r) => !blank(r));
