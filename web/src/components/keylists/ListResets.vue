<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Reset a project list of the open project: empty it (the Load List: forget its rows and read
// the imports again). Every reset asks first, and goes through the list's own rules, so a list
// whose rows are in use elsewhere is refused with the reason.
import { ref } from 'vue';
import { apiPostJson } from '../../lib/engine';
import { useKeyLists } from '../../stores/keylists';

const props = defineProps<{ project: string; only?: string }>();
const kl = useKeyLists();
const LISTS: { id: string; name: string; what: string }[] = [
	{ id: 'load-list', name: 'Load List', what: 'Every row is forgotten, with the plant areas, load types, panels, supplies and cable details people chose, and the rows kept as deleted. Then the MEL and EEL imports are read again, so the list holds what the latest files give, filled in automatically where it can be. The import files, rules and mappings are not touched.' },
	{ id: 'distribution-panels', name: 'Distribution Panels', what: 'Every panel schedule is deleted.' },
	{ id: 'eel', name: 'Electrical Equipment List', what: 'Every item is deleted, and so are its rows in the Load List.' },
	{ id: 'plc', name: 'PLC List', what: 'Every system, rack, card and IO point is deleted. The card and rack types are kept.' },
	{ id: 'load-types', name: 'Load Types', what: 'Every load type is deleted, with its rows for the deliverables and its PDF.' },
	{ id: 'plant-areas', name: 'Plant Areas', what: 'Every plant area is deleted.' },
	{ id: 'equipment-packages', name: 'Equipment Packages', what: 'Every package and equipment type is deleted.' },
	{ id: 'equipment-codes', name: 'Equipment Codes', what: 'Every equipment code is deleted.' },
	{ id: 'instrument-codes', name: 'Instrument Codes', what: 'Every instrument code is deleted.' },
	{ id: 'cable-types', name: 'Cable Types', what: 'The list goes back to the default cable types: yours are deleted and changed ones are put back.' },
];
const shown = props.only ? LISTS.filter((l) => l.id === props.only) : LISTS;
const busy = ref('');
const results = ref<Record<string, { ok: boolean; text: string }>>({});

async function reset(l: (typeof LISTS)[number]) {
	const question = `Reset ${l.name} in the project "${props.project}"?\n\n${l.what}\n\nThis can't be undone (the change log keeps a record of it).`;
	if (!window.confirm(question)) return;
	busy.value = l.id;
	try {
		const res = await apiPostJson<{ message: string }>(`/api/list-workbooks/${l.id}/reset`, {});
		results.value[l.id] = { ok: true, text: res.message };
		await kl.load();
		if (kl.selected === 'load-list' || l.id === 'load-list') await kl.loadLoadList();
	} catch (err) {
		results.value[l.id] = { ok: false, text: err instanceof Error ? err.message : String(err) };
	} finally {
		busy.value = '';
	}
}
</script>

<template>
	<span v-if="only" class="list-reset-one">
		<button type="button" class="secondary" :disabled="!!busy" :title="shown[0].what" @click="reset(shown[0])">{{ busy ? 'Resetting…' : 'Reset…' }}</button>
		<span v-if="results[only]" :class="results[only].ok ? 'saved' : 'warn small'" :title="results[only].text">{{ results[only].text }}</span>
	</span>
	<table v-else class="list-resets">
		<tbody>
			<tr v-for="l in shown" :key="l.id">
				<th>{{ l.name }}</th>
				<td class="what">{{ l.what }}
					<div v-if="results[l.id]" :class="results[l.id].ok ? 'saved' : 'warn'">{{ results[l.id].ok ? '✓ ' : '' }}{{ results[l.id].text }}</div>
				</td>
				<td><button type="button" class="secondary small" :disabled="!!busy" @click="reset(l)">{{ busy === l.id ? 'Resetting…' : 'Reset…' }}</button></td>
			</tr>
		</tbody>
	</table>
</template>
