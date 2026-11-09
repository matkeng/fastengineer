<script setup lang="ts">
import { computed } from 'vue';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const mel = useMel();
const { result } = useStage('auto', (r) => [r.columns, r.hidden_rows, r.text_columns, r.overrides, r.custom_rows, r.auto_columns]);
const MANUAL = '__manual__';

const LABELS: Record<string, string> = {
	area: 'Area', sub_area: 'Sub-area', tag: 'Tag', equip_qty: 'Quantity', standby_qty: 'Standby quantity',
	multi_load: 'Multiple loads', desc: 'Description', equip_type: 'Equipment type', equip_subtype: 'Equipment subtype',
	load_units: 'Load units (kW, HP…)', load_rating: 'Load rating', load_voltage: 'Voltage', csv_row_num: 'Source row number',
	phases: 'Phases', status: 'Status', starter_type: 'Starter type', load_type: 'Load type', starter_addons: 'Starter add-ons',
	load_addons: 'Load add-ons', field_addons: 'Field add-ons', is_a_loadcentre: 'Is a load centre', loadcentre: 'Load centre',
	supplied_from: 'Supplied from', is_deleted: 'Deleted',
};
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
		<div class="row"><button type="button" class="secondary small" @click="suggest">Suggest mapping for unmapped fields</button></div>
		<div class="grid-wrap">
			<table class="grid simple mapping">
				<thead><tr><th>Load-list field</th><th>Comes from</th><th>Fixed value</th></tr></thead>
				<tbody>
					<tr v-for="r in rows" :key="r.field" :class="{ off: !r.choice }">
						<td><strong>{{ LABELS[r.field] ?? r.field }}</strong> <code class="hint">{{ r.field }}</code></td>
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
	</div>
</template>
