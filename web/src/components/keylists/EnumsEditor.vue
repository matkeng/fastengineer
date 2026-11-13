<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The project's Enums: the choice lists other lists pick from. Disciplines (Equipment Codes,
// the Drawing List and the Document List), Drawing types, Document types and Drawing statuses. They are
// edited together and saved with Save. An item that is in use can't be removed; renaming one
// is fine, as the lists that use it follow.
import { computed } from 'vue';
import type { EnumItem, EnumKey } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';

const kl = useKeyLists();
const view = computed(() => kl.enumsView!);
const d = computed(() => kl.enumsDraft!);
const KEYS: EnumKey[] = ['disciplines', 'drawing_types', 'document_types', 'drawing_statuses', 'x_proper'];
const USED_BY: Record<EnumKey, string> = {
	disciplines: 'Used by Equipment Codes, the Drawing List and the Document List. Every discipline needs a code.',
	drawing_types: 'Used by the Drawing List. A code is optional.',
	document_types: 'Used by the Document List. A code is optional.',
	drawing_statuses: 'Used by the Drawing List and the Document List. A status with a code is shown by its code.',
	x_proper: 'Words that keep their capitals, exactly as written, when text is put into proper case: <<…|title>>, <<…|proper>>, .title() and proper(). One word per row: MCC, PLC, I/O, kW…',
};
// enums that are plain lists of words (no code column)
const isWords = (k: EnumKey) => (view.value.word_lists ?? ['x_proper']).includes(k);
const key = (s: string) => s.trim().toLowerCase().replace(/\s+/g, ' ');
const uses = (i: EnumItem) => view.value.in_use[i.id] ?? 0;

// Same rules as the engine, so problems show while typing.
const problems = computed(() => {
	const out: Record<string, string> = {};
	for (const k of KEYS) {
		const seen = { code: new Set<string>(), name: new Set<string>() };
		for (const i of d.value[k]) {
			if (!key(i.name)) out[`${i.id}.name`] = 'Name is required';
			if (view.value.need_code.includes(k) && !key(i.code)) out[`${i.id}.code`] = 'A code is required';
			for (const f of ['code', 'name'] as const) {
				const v = key(i[f]);
				if (v && seen[f].has(v)) out[`${i.id}.${f}`] = `'${i[f].trim()}' is used twice`;
				seen[f].add(v);
			}
		}
	}
	return { ...out, ...kl.fieldErrors };
});
const problemCount = computed(() => Object.keys(problems.value).length);

function add(k: EnumKey) {
	d.value[k].push({ id: newId(), code: '', name: '' });
}
function move(k: EnumKey, i: number, by: -1 | 1) {
	const list = d.value[k];
	if (i + by >= 0 && i + by < list.length) [list[i], list[i + by]] = [list[i + by], list[i]];
}
</script>

<template>
	<section class="card wizard ref-editor key-enums">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Enums</h2>
			<span class="hint small">The choices other lists pick from, for this project.</span>
			<span class="spacer" />
			<span v-if="problemCount" class="warn small">{{ problemCount }} problem(s)</span>
			<span v-if="kl.enumsDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<HistoryButton entity="enums" record-id="enums" label="Enums" />
			<button type="button" class="secondary" :disabled="!kl.enumsDirty || kl.busy" @click="kl.discard()">Discard</button>
			<button type="button" :disabled="!kl.enumsDirty || kl.busy || problemCount > 0" @click="kl.saveEnums()">Save</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>
		<div class="enum-columns">
			<div v-for="k in KEYS" :key="k" class="enum-box">
				<h3>{{ view.titles[k] }} <span class="count">{{ d[k].length }}</span></h3>
				<p class="hint small">{{ USED_BY[k] }}</p>
				<table class="grid simple enum-items">
					<thead><tr><th v-if="!isWords(k)" class="code">Code</th><th>{{ isWords(k) ? 'Word' : 'Name' }}</th><th /></tr></thead>
					<tbody>
						<tr v-for="(item, i) in d[k]" :key="item.id">
							<td v-if="!isWords(k)" class="code">
								<input v-model="item.code" class="mono" :aria-label="`${view.titles[k]} code`" :class="{ invalid: problems[`${item.id}.code`] }"
									:title="problems[`${item.id}.code`] ?? ''" />
							</td>
							<td>
								<input v-model="item.name" :aria-label="`${view.titles[k]} name`" :class="{ invalid: problems[`${item.id}.name`] }"
									:title="problems[`${item.id}.name`] ?? ''" />
								<div v-if="problems[`${item.id}.code`] || problems[`${item.id}.name`]" class="warn small">
									{{ problems[`${item.id}.code`] || problems[`${item.id}.name`] }}
								</div>
							</td>
							<td class="actions">
								<span v-if="uses(item)" class="used" :title="`In use ${uses(item)} time(s): it can be renamed, not removed`">{{ uses(item) }}</span>
								<button type="button" class="secondary small" :disabled="i === 0" title="Move up" @click="move(k, i, -1)">↑</button>
								<button type="button" class="secondary small" :disabled="i === d[k].length - 1" title="Move down" @click="move(k, i, 1)">↓</button>
								<button type="button" class="secondary small" :disabled="uses(item) > 0"
									:title="uses(item) ? `In use ${uses(item)} time(s): change what uses it first` : 'Remove'" @click="d[k].splice(i, 1)">✕</button>
							</td>
						</tr>
						<tr v-if="!d[k].length"><td colspan="3" class="hint">None yet.</td></tr>
					</tbody>
				</table>
				<button type="button" class="secondary small" @click="add(k)">+ Add</button>
			</div>
		</div>
	</section>
</template>
