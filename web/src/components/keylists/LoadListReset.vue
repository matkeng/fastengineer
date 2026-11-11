<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Reset the Load List of the open project: all of it (every row is forgotten and the imports
// are read again), or only some of what people set on its rows. A dialog says what will go
// and asks before anything changes.
import { computed, ref } from 'vue';
import { apiPostJson } from '../../lib/engine';
import { useKeyLists } from '../../stores/keylists';
import AppModal from '../common/AppModal.vue';

const props = defineProps<{ project: string }>();
const kl = useKeyLists();
const PARTS = [
	{ id: 'plant_area', label: 'Plant areas people chose', what: 'They go back to what the import\'s area text gives, or blank.' },
	{ id: 'load_type', label: 'Load types people chose', what: 'They go back to what the import\'s load type text gives, or blank.' },
	{ id: 'supply', label: 'Distribution panels and supplied from', what: 'The panel ticks and supplies people chose go; the import\'s own are filled in again.' },
	{ id: 'cable', label: 'Cable details', what: 'Length, construction, parallel cables, insulation, size and earth size of every row.' },
	{ id: 'deleted', label: 'Rows kept as deleted', what: 'Rows that left their import are forgotten, with what was set on them.' },
] as const;
type Part = (typeof PARTS)[number]['id'];
const open = ref(false);
const mode = ref<'all' | 'parts'>('all');
const chosen = ref<Part[]>([]);
const sure = ref(false);
const busy = ref(false);
const error = ref('');
const done = ref('');
const ready = computed(() => sure.value && (mode.value === 'all' || chosen.value.length > 0));

function start() {
	open.value = true;
	mode.value = 'all';
	chosen.value = [];
	sure.value = false;
	error.value = '';
}

async function reset() {
	if (!ready.value) return;
	busy.value = true;
	error.value = '';
	try {
		const res = await apiPostJson<{ message: string }>('/api/loadlist/reset', { parts: mode.value === 'all' ? ['all'] : chosen.value });
		done.value = res.message;
		open.value = false;
		await kl.load();
		await kl.loadLoadList();
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		busy.value = false;
	}
}
</script>

<template>
	<span class="list-reset-one">
		<button type="button" class="secondary" title="Reset the Load List, or parts of it, and read the imports again" @click="start">Reset…</button>
		<span v-if="done" class="saved" :title="done">✓ {{ done }}</span>
		<AppModal :open="open" title="Reset the Load List" @close="open = false">
			<p>Project <strong>{{ project }}</strong>. The MEL and EEL imports are read again afterwards, so everything their latest files give is filled in automatically. The import files, rules and mappings are not touched.</p>
			<div class="reset-options">
				<label class="reset-option">
					<input v-model="mode" type="radio" value="all" @change="sure = false" />
					<span><strong>Everything</strong><br /><span class="hint">Every row is forgotten: the plant areas, load types, panels, supplies and cable details people set, and the rows kept as deleted. The list is built again from the imports.</span></span>
				</label>
				<label class="reset-option">
					<input v-model="mode" type="radio" value="parts" @change="sure = false" />
					<span><strong>Only these</strong><br /><span class="hint">The rows stay; what you tick is cleared on all of them.</span></span>
				</label>
				<div v-if="mode === 'parts'" class="reset-parts">
					<label v-for="p in PARTS" :key="p.id" class="reset-option">
						<input v-model="chosen" type="checkbox" :value="p.id" @change="sure = false" />
						<span>{{ p.label }}<br /><span class="hint">{{ p.what }}</span></span>
					</label>
				</div>
			</div>
			<p class="hint small">Rows of the Electrical Equipment List keep the plant area, load type, panel and supply set in that list; only their cable details can be cleared here.</p>
			<label class="reset-option confirm">
				<input v-model="sure" type="checkbox" />
				<span>I understand this can't be undone. (The change log records that it was reset, not what was there.)</span>
			</label>
			<p v-if="error" class="error">{{ error }}</p>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="open = false">Cancel</button>
				<button type="button" :disabled="!ready || busy" @click="reset">{{ busy ? 'Resetting…' : mode === 'all' ? 'Reset the Load List' : 'Reset what is ticked' }}</button>
			</template>
		</AppModal>
	</span>
</template>
