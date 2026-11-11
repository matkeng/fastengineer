// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly

/** One changed field: `path` is e.g. "items[HV].description", or "" for the whole record. */
export interface AuditChange { path: string; old: unknown; new: unknown }

export interface AuditEntry {
	id: number;
	at: string;
	user: string;
	machine: string;
	entity: string;
	entity_label: string;
	record_id: string;
	parent_id: string | null;
	action: 'create' | 'update' | 'delete';
	label: string;
	changes: AuditChange[];
}

export interface AuditPage { entries: AuditEntry[]; more: boolean }
export interface AuditFilters { users: string[]; entities: Record<string, string> }
