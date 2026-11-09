<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import type { CustomRow } from '../../lib/melTypes';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';
import AppModal from '../common/AppModal.vue';

const mel = useMel();
// Custom rows are added after overrides; their columns are the table's at that point.
const { result } = useStage('overrides', (r) => [r.columns, r.hidden_rows, r.text_columns]);
const headers = computed(() => (result.value?.headers ?? []).filter((h) => h !== result.value?.key_header));
const fileKeys = computed(() => new Set([...(result.value?.rows ?? []), ...(result.value?.hidden_rows ?? [])].map((r) => r.key)));

const editing = ref<{ index: number | null; row: CustomRow } | null>(null);

function open(index: number | null) {
	const src = index === null ? { key: '', values: {} } : mel.draft!.custom_rows[index];
	const values: Record<string, string> = {};
	for (const h of headers.value) values[h] = src.values[h] ?? '';
	editing.value = { index, row: { key: src.key, values } };
}

const keyProblem = computed(() => {
	const e = editing.value;
	if (!e) return null;
	const k = e.row.key.trim();
	if (!k) return 'Enter a key value (e.g. a tag).';
	if (fileKeys.value.has(k)) return 'This key is already a row in the file.';
	if (mel.draft!.custom_rows.some((r, i) => i !== e.index && r.key.trim() === k)) return 'Another custom row already uses this key.';
	return null;
});

function save() {
	const e = editing.value;
	if (!e || keyProblem.value) return;
	// Store only filled cells; empty ones show as "-" (PRD 5.8). Editing replaces the row,
	// so old values can't linger (PRD 11, item 2).
	const values = Object.fromEntries(Object.entries(e.row.values).filter(([, v]) => v.trim() !== ''));
	const row = { key: e.row.key.trim(), values };
	if (e.index === null) mel.draft!.custom_rows.push(row);
	else mel.draft!.custom_rows.splice(e.index, 1, row);
	editing.value = null;
}

function remove(i: number) {
	if (confirm(`Delete custom row ${mel.draft!.custom_rows[i].key}?`)) mel.draft!.custom_rows.splice(i, 1);
}
</script>

<template>
	<div>
		<p class="hint">Add rows that aren't in the file, such as a load the mechanical list missed or a load centre. Empty cells show as "-".</p>
		<div v-if="mel.draft!.custom_rows.length" class="grid-wrap">
			<table class="grid simple">
				<thead><tr><th>{{ result?.key_header }}</th><th v-for="h in headers" :key="h">{{ h }}</th><th /></tr></thead>
				<tbody>
					<tr v-for="(r, i) in mel.draft!.custom_rows" :key="i" @click="open(i)">
						<td><strong>{{ r.key }}</strong><span v-if="fileKeys.has(r.key)" class="warn small"> clashes with a file row</span></td>
						<td v-for="h in headers" :key="h">{{ r.values[h] ?? '-' }}</td>
						<td class="actions"><button type="button" class="secondary small" @click.stop="remove(i)">Delete</button></td>
					</tr>
				</tbody>
			</table>
		</div>
		<button type="button" :disabled="!result" @click="open(null)">Add row</button>

		<AppModal :open="!!editing" :title="editing?.index === null ? 'Add row' : 'Edit row'" @close="editing = null">
			<div v-if="editing" class="form-grid">
				<label class="field">{{ result?.key_header }} (key)
					<input v-model="editing.row.key" autofocus />
				</label>
				<p v-if="keyProblem" class="warn small">{{ keyProblem }}</p>
				<label v-for="h in headers" :key="h" class="field">{{ h }}
					<input v-model="editing.row.values[h]" placeholder="-" />
				</label>
			</div>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="editing = null">Cancel</button>
				<button type="button" :disabled="!!keyProblem" @click="save">{{ editing?.index === null ? 'Add' : 'Save' }}</button>
			</template>
		</AppModal>
	</div>
</template>
