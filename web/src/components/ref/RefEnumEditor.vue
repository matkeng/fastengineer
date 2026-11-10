<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import HistoryButton from '../audit/HistoryButton.vue';
import { computed, nextTick, ref } from 'vue';
import { newId } from '../../lib/refTypes';
import { useRefData } from '../../stores/refdata';

const rd = useRefData();
const d = computed(() => rd.enumDraft!);
const usedBy = computed(() => rd.overview.enums.find((e) => e.id === d.value.id)?.used_by ?? []);
const codeInputs = ref<HTMLInputElement[]>([]);

const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
// Same rules as the engine, so problems show while typing.
const problems = computed(() => {
	const out: Record<string, string> = {};
	const codes = new Map<string, string>();
	const values = new Map<string, string>();
	for (const it of d.value.items) {
		const c = key(it.code);
		const v = key(it.value);
		if (!c) out[`${it.id}.code`] = 'Required';
		else if (codes.has(c)) out[`${it.id}.code`] = 'Duplicate code';
		else codes.set(c, it.id);
		if (!v) out[`${it.id}.value`] = 'Required';
		else if (values.has(v)) out[`${it.id}.value`] = 'Duplicate value';
		else values.set(v, it.id);
	}
	return { ...out, ...rd.fieldErrors };
});

async function add() {
	d.value.items.push({ id: newId(), code: '', value: '', description: '' });
	await nextTick();
	codeInputs.value[d.value.items.length - 1]?.focus();
}

function move(i: number, by: -1 | 1) {
	const list = d.value.items;
	const j = i + by;
	if (j >= 0 && j < list.length) [list[i], list[j]] = [list[j], list[i]];
}

function remove() {
	if (confirm(`Delete the list "${rd.enumSaved?.name}"?`)) void rd.remove();
}
</script>

<template>
	<section class="card wizard ref-editor">
		<div class="mel-head">
			<span class="kind">List</span>
			<input v-model="d.name" class="name-input" aria-label="List name" />
			<span v-if="rd.fieldErrors.name" class="warn small">{{ rd.fieldErrors.name }}</span>
			<span class="spacer" />
			<span v-if="rd.enumDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="rd.message" class="saved">✓ {{ rd.message }}</span>
			<HistoryButton entity="ref_enum" :record-id="d.id" :label="d.name" />
			<button type="button" class="secondary" :disabled="!rd.enumDirty || rd.busy" @click="rd.discard()">Discard</button>
			<button type="button" :disabled="!rd.enumDirty || rd.busy || Object.keys(problems).length > 0" @click="rd.saveEnum()">Save</button>
		</div>
		<input v-model="d.description" class="desc-input" placeholder="Description (optional)" aria-label="List description" />
		<p v-if="usedBy.length" class="hint">Used by: {{ usedBy.join(', ') }}. Items used in rows can't be deleted.</p>
		<p v-if="rd.error" class="error">{{ rd.error }}</p>

		<div class="grid-wrap">
			<table class="grid simple enum-items">
				<thead><tr><th class="num" /><th>Code</th><th>Value</th><th>Description</th><th /></tr></thead>
				<tbody>
					<tr v-for="(it, i) in d.items" :key="it.id">
						<td class="num">{{ i + 1 }}</td>
						<td>
							<input :ref="(el) => (codeInputs[i] = el as HTMLInputElement)" v-model="it.code" class="mono" aria-label="Code"
								:class="{ invalid: problems[`${it.id}.code`] }" />
							<div v-if="problems[`${it.id}.code`]" class="warn small">{{ problems[`${it.id}.code`] }}</div>
						</td>
						<td>
							<input v-model="it.value" aria-label="Value" :class="{ invalid: problems[`${it.id}.value`] }" />
							<div v-if="problems[`${it.id}.value`]" class="warn small">{{ problems[`${it.id}.value`] }}</div>
						</td>
						<td><input v-model="it.description" aria-label="Description" /></td>
						<td class="actions">
							<button type="button" class="secondary small" :disabled="i === 0" title="Move up" @click="move(i, -1)">↑</button>
							<button type="button" class="secondary small" :disabled="i === d.items.length - 1" title="Move down" @click="move(i, 1)">↓</button>
							<button type="button" class="secondary small" title="Delete item" @click="d.items.splice(i, 1)">✕</button>
						</td>
					</tr>
					<tr v-if="!d.items.length"><td colspan="5" class="hint">No items yet.</td></tr>
				</tbody>
			</table>
		</div>
		<div class="nav">
			<button type="button" @click="add">Add item</button>
			<span class="hint">Codes and values must be unique in the list (ignoring case).</span>
			<span class="spacer" />
			<button type="button" class="secondary" @click="remove">Delete list</button>
		</div>
	</section>
</template>
