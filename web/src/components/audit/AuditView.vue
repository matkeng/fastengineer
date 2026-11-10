<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import type { AuditChange, AuditEntry } from '../../lib/auditTypes';
import { useAudit } from '../../stores/audit';
import { useUi } from '../../stores/ui';

const audit = useAudit();
const ui = useUi();
const open = ref(new Set<number>());

const ACTIONS = { create: 'Created', update: 'Changed', delete: 'Deleted' } as const;
const when = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' });

function show(value: unknown): string {
	if (value === null || value === undefined) return '';
	return typeof value === 'string' ? value : JSON.stringify(value, null, 1);
}

/** The field-by-field rows of an entry; a create or delete lists the record's top-level fields. */
function rows(e: AuditEntry): AuditChange[] {
	const out: AuditChange[] = [];
	for (const c of e.changes) {
		const whole = c.path === '' ? (c.new ?? c.old) : null;
		if (whole && typeof whole === 'object' && !Array.isArray(whole)) {
			for (const [key, v] of Object.entries(whole)) {
				if (key === 'id' || key === 'updated_at' || v === null || v === '') continue;
				out.push({ path: key, old: c.new === null ? v : null, new: c.new === null ? null : v });
			}
		} else out.push(c);
	}
	return out;
}

function summary(e: AuditEntry): string {
	if (e.action !== 'update') return '';
	const paths = e.changes.map((c) => c.path).filter((p) => !p.startsWith('('));
	return paths.slice(0, 3).join(', ') + (paths.length > 3 ? ` and ${paths.length - 3} more` : '');
}

function toggle(id: number) {
	const next = new Set(open.value);
	if (!next.delete(id)) next.add(id);
	open.value = next;
}

// Load when the page is first shown, and again each time the user comes back to it.
onMounted(() => audit.load());
watch(() => ui.tab, (tab) => { if (tab === 'history' && !audit.busy) void audit.load(); });
</script>

<template>
	<section class="card audit">
		<h2>Change log</h2>
		<p v-if="audit.record" class="hint">
			History of <b>{{ audit.record.label }}</b>.
			<a href="#" @click.prevent="audit.showAll()">Show all changes</a>
		</p>
		<p v-else class="hint">Who changed which record, when, and what changed. Newest first.</p>

		<form class="audit-filters" @submit.prevent="audit.load()">
			<label>User
				<input v-model="audit.filter.user" list="audit-users" placeholder="Anyone" />
				<datalist id="audit-users"><option v-for="u in audit.options.users" :key="u" :value="u" /></datalist>
			</label>
			<label v-if="!audit.record">Record type
				<select v-model="audit.filter.entity">
					<option value="">All</option>
					<option v-for="(label, key) in audit.options.entities" :key="key" :value="key">{{ label }}</option>
				</select>
			</label>
			<label>From <input v-model="audit.filter.since" type="date" /></label>
			<label>To <input v-model="audit.filter.until" type="date" /></label>
			<button type="submit" :disabled="audit.busy">Show</button>
		</form>

		<p v-if="audit.error" class="error">{{ audit.error }}</p>
		<p v-else-if="!audit.busy && audit.entries.length === 0" class="hint">No changes match.</p>

		<table v-if="audit.entries.length" class="audit-table">
			<thead>
				<tr><th>When</th><th>User</th><th>PC</th><th>Action</th><th>Record</th><th>What changed</th></tr>
			</thead>
			<tbody>
				<template v-for="e in audit.entries" :key="e.id">
					<tr class="audit-row" :class="e.action" @click="toggle(e.id)">
						<td class="nowrap">{{ when.format(new Date(e.at)) }}</td>
						<td class="nowrap">{{ e.user }}</td>
						<td class="nowrap">{{ e.machine }}</td>
						<td><span class="audit-action">{{ ACTIONS[e.action] }}</span></td>
						<td>{{ e.label || e.record_id }} <span class="hint">({{ e.entity_label }})</span></td>
						<td>
							<button type="button" class="secondary small" :aria-expanded="open.has(e.id)">
								{{ open.has(e.id) ? 'Hide' : 'Details' }}
							</button>
							<span class="audit-summary">{{ summary(e) }}</span>
						</td>
					</tr>
					<tr v-if="open.has(e.id)" class="audit-detail">
						<td colspan="6">
							<table>
								<thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
								<tbody>
									<tr v-for="(c, i) in rows(e)" :key="i">
										<td class="mono">{{ c.path || '(record)' }}</td>
										<td class="old"><pre>{{ show(c.old) }}</pre></td>
										<td class="new"><pre>{{ show(c.new) }}</pre></td>
									</tr>
								</tbody>
							</table>
						</td>
					</tr>
				</template>
			</tbody>
		</table>
		<button v-if="audit.more" type="button" class="secondary" :disabled="audit.busy" @click="audit.loadMore()">Show older changes</button>
	</section>
</template>
