// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { reactive, ref } from 'vue';
import type { AuditEntry, AuditFilters, AuditPage } from '../lib/auditTypes';
import { apiGet } from '../lib/engine';
import { useUi } from './ui';

/** The change log: who changed which record, when, and what changed. */
export const useAudit = defineStore('audit', () => {
	const entries = ref<AuditEntry[]>([]);
	const more = ref(false);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const options = ref<AuditFilters>({ users: [], entities: {} });
	const filter = reactive({ user: '', entity: '', since: '', until: '' });
	/** Set when showing one record's history (from a History button). */
	const record = ref<{ entity: string; id: string; label: string } | null>(null);

	function params(beforeId?: number): Record<string, string | number> {
		const p: Record<string, string | number> = { limit: 100 };
		if (record.value) Object.assign(p, { entity: record.value.entity, record_id: record.value.id, children: 'true' });
		else if (filter.entity) p.entity = filter.entity;
		if (filter.user) p.user = filter.user;
		// The date boxes are local days; the log is kept in UTC.
		if (filter.since) p.since = new Date(`${filter.since}T00:00:00`).toISOString();
		if (filter.until) p.until = new Date(`${filter.until}T23:59:59.999`).toISOString();
		if (beforeId) p.before_id = beforeId;
		return p;
	}

	async function fetchPage(beforeId?: number) {
		busy.value = true;
		error.value = null;
		try {
			const page = await apiGet<AuditPage>('/api/audit', params(beforeId));
			entries.value = beforeId ? [...entries.value, ...page.entries] : page.entries;
			more.value = page.more;
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
		} finally {
			busy.value = false;
		}
	}

	async function load() {
		await fetchPage();
		try {
			options.value = await apiGet<AuditFilters>('/api/audit/filters');
		} catch {
			/* the filter boxes just stay empty */
		}
	}

	function loadMore() {
		const last = entries.value[entries.value.length - 1];
		return last ? fetchPage(last.id) : load();
	}

	/** Open the change log on one record's history. */
	function showRecord(entity: string, id: string, label: string) {
		record.value = { entity, id, label };
		useUi().go('history');
		return load();
	}

	function showAll() {
		record.value = null;
		return load();
	}

	return { entries, more, busy, error, options, filter, record, load, loadMore, showRecord, showAll };
});
