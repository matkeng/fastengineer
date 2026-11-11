<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Check the import's edits against its latest file: which the file has now taken in (a
// changed cell whose value the file now has, a removed row the file no longer has, an added
// row the file now has) and which the import still has to make. The ones taken in are ticked
// to clear; Clear takes them out of the import (saved with Save).
import { computed, ref, watch } from 'vue';
import { apiPostJson } from '../../lib/engine';
import { useMel } from '../../stores/mel';
import AppModal from '../common/AppModal.vue';

interface Edit { kind: 'changed' | 'removed' | 'added'; key: string; column: string; note: string; state: 'done' | 'gone' | 'partly' | 'needed'; detail: string }
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();
const mel = useMel();
const check = ref<{ rev: number; file_name: string; edits: Edit[] } | null>(null);
const picked = ref<Set<number>>(new Set());
const error = ref('');
const busy = ref(false);
const KIND = { changed: 'Changed cell', removed: 'Removed row', added: 'Added row' };
const STATE = { done: 'Done in the file', gone: 'Row gone', partly: 'Partly done', needed: 'Still needed' };

async function load() {
	if (!mel.draft) return;
	busy.value = true;
	error.value = '';
	try {
		check.value = await apiPostJson(`/api/mel/recipes/${mel.draft.id}/edits-check`, { recipe: mel.draft });
		picked.value = new Set(check.value!.edits.map((e, i) => (e.state === 'done' || e.state === 'gone' ? i : -1)).filter((i) => i >= 0));
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		busy.value = false;
	}
}
watch(() => props.open, (o) => { if (o) void load(); }, { immediate: true });

const counts = computed(() => {
	const c = { done: 0, gone: 0, partly: 0, needed: 0 };
	for (const e of check.value?.edits ?? []) c[e.state]++;
	return c;
});
function toggle(i: number) {
	const s = new Set(picked.value);
	if (s.has(i)) s.delete(i);
	else s.add(i);
	picked.value = s;
}

/** Take the ticked edits out of the import (the draft: Save keeps it). */
function clear() {
	const d = mel.draft;
	if (!d || !check.value) return;
	const gone = check.value.edits.filter((_, i) => picked.value.has(i));
	const has = (kind: Edit['kind'], key: string, column = '') => gone.some((e) => e.kind === kind && e.key === key && e.column === column);
	d.overrides = d.overrides.filter((o) => !has('changed', o.key, o.column));
	d.hidden_rows = d.hidden_rows.filter((h) => !has('removed', h.key));
	d.custom_rows = d.custom_rows.filter((c) => !has('added', c.key));
	mel.message = `Cleared ${gone.length} edit(s) the file has taken in: save to keep it`;
	emit('close');
}
</script>

<template>
	<AppModal :open="open" :title="check ? `Edits against rev ${check.rev} (${check.file_name})` : 'Check the edits'" @close="emit('close')">
		<div class="edits-check">
			<p class="hint small">
				Whether the latest file has taken in each of this import's edits. Those it has (and changed cells whose row has gone) change
				nothing any more and are ticked to clear. Clearing takes them out of the import; <strong>Save</strong> keeps it.
			</p>
			<p v-if="error" class="error">{{ error }}</p>
			<p v-else-if="busy && !check" class="hint">Checking…</p>
			<template v-if="check">
				<p v-if="!check.edits.length" class="hint">This import makes no edits to its file.</p>
				<div v-else class="row tight">
					<span class="chip ok">{{ counts.done }} done</span><span v-if="counts.gone" class="chip">{{ counts.gone }} row gone</span>
					<span v-if="counts.partly" class="chip warn-chip">{{ counts.partly }} partly done</span>
					<span class="chip">{{ counts.needed }} still needed</span>
				</div>
				<table v-if="check.edits.length" class="grid simple">
					<thead><tr><th>Clear</th><th>Edit</th><th>{{ mel.latest?.key_header ?? 'Key' }}</th><th>Column</th><th>In the file</th><th>Reason</th></tr></thead>
					<tbody>
						<tr v-for="(e, i) in check.edits" :key="i" :class="`ec-${e.state}`">
							<td class="center"><input type="checkbox" :checked="picked.has(i)" :aria-label="`Clear the edit to ${e.key}`" @change="toggle(i)" /></td>
							<td>{{ KIND[e.kind] }}</td>
							<td><strong>{{ e.key }}</strong></td>
							<td>{{ e.column }}</td>
							<td><span class="ec-state">{{ STATE[e.state] }}</span> <span class="hint small">{{ e.detail }}</span></td>
							<td class="hint small">{{ e.note }}</td>
						</tr>
					</tbody>
				</table>
			</template>
		</div>
		<template #footer>
			<span class="spacer" />
			<button type="button" class="secondary" @click="emit('close')">Close</button>
			<button type="button" :disabled="!picked.size" @click="clear">Clear {{ picked.size }} edit(s)</button>
		</template>
	</AppModal>
</template>
