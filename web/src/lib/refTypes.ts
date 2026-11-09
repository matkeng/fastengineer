// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Mirrors workbench_core.refdata.
export type ColumnType = 'text' | 'enum' | 'integer' | 'boolean' | 'decimal';
export const COLUMN_TYPE_LABELS: Record<ColumnType, string> = {
	text: 'Text', enum: 'List (enum)', integer: 'Whole number', boolean: 'Yes / No', decimal: 'Decimal',
};
export type CellValue = string | number | boolean | null;

export interface EnumItem { id: string; code: string; value: string; description: string }
export interface EnumList { id: string; name: string; description: string; items: EnumItem[]; updated_at: string | null }
export interface ColumnDef { id: string; name: string; type: ColumnType; enum_id: string | null; required: boolean; unique: boolean }
export interface RefTable { id: string; name: string; description: string; columns: ColumnDef[]; updated_at: string | null }
export interface RefRow { id: string; values: Record<string, CellValue>; updated_at: string | null }
export interface TableDetail { table: RefTable; rows: RefRow[]; enums: Record<string, EnumList> }

export interface RefOverview {
	enums: { id: string; name: string; description: string; items: number; used_by: string[] }[];
	tables: { id: string; name: string; description: string; columns: number; rows: number }[];
}

export const newId = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : Math.random().toString(16).slice(2) + Date.now().toString(16));

/** How a cell shows in the grid and exports. */
export function displayCell(v: CellValue, col: ColumnDef, enums: Record<string, EnumList>): string {
	if (v === null || v === undefined || v === '') return '';
	if (col.type === 'boolean') return v ? 'Yes' : 'No';
	if (col.type === 'enum') {
		const item = enums[col.enum_id ?? '']?.items.find((i) => i.id === v);
		return item ? `${item.code} – ${item.value}` : String(v);
	}
	return String(v);
}
