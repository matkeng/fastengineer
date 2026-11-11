<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import LoadFieldsEditor from '../keylists/LoadFieldsEditor.vue';
import { LOAD_FIELD_LABELS } from '../../lib/melTypes';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const mel = useMel();
const { result } = useStage('auto', (r) => [r.columns, r.hidden_rows, r.text_columns, r.overrides, r.custom_rows, r.auto_columns]);
const MANUAL = '__manual__';

const label = (f: string) => mel.labels[f] ?? LOAD_FIELD_LABELS[f] ?? f;
const isLoad = computed(() => mel.draft?.target !== 'PIL');
const editing = ref(false);

/** The Load List's fields changed: open the import again for its fields (a deleted field's mapping is gone). */
async function fieldsSaved() {
	if (!mel.draft) return;
	const tab = mel.tab;
	await mel.open(mel.draft.id);
	mel.tab = tab;
}
// Header patterns for "Suggest mapping".
const GUESS: Record<string, RegExp> = {
	area: /^area$/i, sub_area: /sub.?area/i, desc: /desc/i, equip_type: /(equip|equipment).*type|^type$/i,
	equip_subtype: /sub.?type/i, equip_qty: /^(qty|quantity|equip.*qty)$/i, standby_qty: /standby|spare/i,
	load_rating: /(kw|hp|rating|power)/i, load_voltage: /volt/i, phases: /phase/i, starter_type: /starter/i,
	load_type: /load.?type/i, supplied_from: /(fed|supplied).?from|source.?bus/i,
};

const rows = computed(() => mel.fields.map((f) => {
	const m = mel.draft!.mapping.find((x) => x.field === f);
	return { field: f, choice: m ? (m.column ?? MANUAL) : '', manual: m?.manual ?? '', missing: !!m?.column && !(result.value?.headers ?? []).includes(m.column) };
}));

function set(field: string, choice: string, manual?: string) {
	const d = mel.draft!;
	d.mapping = d.mapping.filter((m) => m.field !== field);
	if (choice === MANUAL) d.mapping.push({ field, column: null, manual: manual ?? '' });
	else if (choice) d.mapping.push({ field, column: choice, manual: null });
	d.mapping.sort((a, b) => mel.fields.indexOf(a.field) - mel.fields.indexOf(b.field));
}

function suggest() {
	const headers = result.value?.headers ?? [];
	const used = new Set(mel.draft!.mapping.map((m) => m.column));
	for (const f of mel.fields) {
		if (mel.draft!.mapping.some((m) => m.field === f)) continue;
		let h: string | undefined;
		if (f === 'tag') h = result.value?.key_header;
		else if (GUESS[f]) h = headers.find((x) => GUESS[f].test(x) && !used.has(x));
		if (h) { set(f, h); used.add(h); }
	}
}
</script>

<template>
	<div>
		<p class="hint">Choose which column fills each {{ mel.outputName.toLowerCase() }} field, or type a fixed value. Unmapped fields are left out of the {{ mel.outputName.toLowerCase() }}.</p>
		<div class="row">
			<button type="button" class="secondary small" @click="suggest">Suggest mapping for unmapped fields</button>
			<button v-if="isLoad" type="button" class="secondary small" :disabled="mel.dirty"
				:title="mel.dirty ? 'Save this import first' : 'Rename, add, delete or reorder the Project Master Load List\'s fields (for every import)'"
				@click="editing = true">Edit the Load List fields…</button>
		</div>
		<div class="grid-wrap">
			<table class="grid simple mapping">
				<thead><tr><th>Load-list field</th><th>Comes from</th><th>Fixed value</th></tr></thead>
				<tbody>
					<tr v-for="r in rows" :key="r.field" :class="{ off: !r.choice }">
						<td><strong>{{ label(r.field) }}</strong> <code class="hint">{{ r.field }}</code></td>
						<td>
							<select :value="r.choice" @change="set(r.field, ($event.target as HTMLSelectElement).value)">
								<option value="">(not mapped)</option>
								<option :value="MANUAL">✎ Fixed value…</option>
								<option v-for="h in result?.headers ?? []" :key="h" :value="h">{{ h }}</option>
							</select>
							<div v-if="r.missing" class="warn small">Column not in the table any more</div>
						</td>
						<td>
							<input v-if="r.choice === MANUAL" :value="r.manual" @input="set(r.field, MANUAL, ($event.target as HTMLInputElement).value)" />
						</td>
					</tr>
				</tbody>
			</table>
		</div>
		<LoadFieldsEditor v-if="isLoad" :open="editing" @close="editing = false" @saved="fieldsSaved" />
	</div>
</template>
