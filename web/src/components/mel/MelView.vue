<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import HistoryButton from '../audit/HistoryButton.vue';
import { onMounted, ref } from 'vue';
import { TARGET_LABELS, TARGETS, type TargetList } from '../../lib/melTypes';
import { type MelTab, useMel } from '../../stores/mel';
import MelAuto from './MelAuto.vue';
import MelColumns from './MelColumns.vue';
import MelCustom from './MelCustom.vue';
import MelMapping from './MelMapping.vue';
import MelOverrides from './MelOverrides.vue';
import MelOverview from './MelOverview.vue';
import MelResult from './MelResult.vue';
import MelRows from './MelRows.vue';
import MelText from './MelText.vue';

const mel = useMel();
const newName = ref('');
const newTarget = ref<TargetList>('MEL');

const TABS: { id: MelTab; label: string; count?: () => number }[] = [
	{ id: 'overview', label: 'Overview' },
	{ id: 'columns', label: 'Columns', count: () => mel.draft?.columns.length ?? 0 },
	{ id: 'rows', label: 'Rows', count: () => mel.draft?.hidden_rows.length ?? 0 },
	{ id: 'text', label: 'Text columns', count: () => mel.draft?.text_columns.length ?? 0 },
	{ id: 'overrides', label: 'Overrides', count: () => mel.draft?.overrides.length ?? 0 },
	{ id: 'custom', label: 'Custom rows', count: () => mel.draft?.custom_rows.length ?? 0 },
	{ id: 'auto', label: 'Calculated', count: () => mel.draft?.auto_columns.length ?? 0 },
	{ id: 'mapping', label: 'Mapping', count: () => mel.draft?.mapping.length ?? 0 },
	{ id: 'result', label: 'Result' },
];
const panels: Record<MelTab, unknown> = {
	overview: MelOverview, columns: MelColumns, rows: MelRows, text: MelText, overrides: MelOverrides,
	custom: MelCustom, auto: MelAuto, mapping: MelMapping, result: MelResult,
};

async function create() {
	await mel.create(newName.value || newTarget.value, newTarget.value);
	newName.value = '';
}

function leave() {
	if (mel.dirty && !confirm('Discard unsaved changes to this import?')) return;
	mel.close();
}

function removeRecipe(id: string, name: string) {
	if (confirm(`Delete the import "${name}" with all its files and rules? This can't be undone.`)) void mel.remove(id);
}

onMounted(() => mel.refreshList());
</script>

<template>
	<div class="mel">
		<!-- Saved imports -->
		<section v-if="!mel.draft" class="card">
			<h2>List imports</h2>
			<p class="hint">
				Turn a Mechanical Equipment List into a load list, or a tags list (from the Symbol detection tab, or a CSV)
				into an instrument list, with a saved recipe of rules. The source file is never changed, and the same rules
				re-apply when you upload a revision.
			</p>
			<table v-if="mel.recipes.length" class="grid simple">
				<thead><tr><th>Name</th><th>List</th><th>Files</th><th>Last changed</th><th /></tr></thead>
				<tbody>
					<tr v-for="r in mel.recipes" :key="r.id" @click="mel.open(r.id)">
						<td><strong>{{ r.name }}</strong></td>
						<td>{{ TARGET_LABELS[r.target] }}</td>
						<td>{{ r.revisions ? `${r.revisions} (latest rev ${r.latest_rev})` : 'none yet' }}</td>
						<td>{{ new Date(r.updated_at).toLocaleString() }}</td>
						<td class="actions">
							<button type="button" class="secondary small" @click.stop="removeRecipe(r.id, r.name)">Delete</button>
						</td>
					</tr>
				</tbody>
			</table>
			<p v-else class="hint">No imports yet.</p>
			<form class="row create" @submit.prevent="create">
				<input v-model="newName" placeholder="New import name, e.g. Plant MEL" />
				<select v-model="newTarget" aria-label="List type">
					<option v-for="t in TARGETS" :key="t" :value="t">{{ TARGET_LABELS[t] }}</option>
				</select>
				<button type="submit" :disabled="mel.busy">Create</button>
			</form>
			<p v-if="mel.error" class="error">{{ mel.error }}</p>
		</section>

		<!-- One import: hub and editors -->
		<section v-else class="card wizard mel-card">
			<div class="mel-head">
				<button type="button" class="secondary small" @click="leave">← All imports</button>
				<input v-model="mel.draft.name" class="name-input" aria-label="Import name" />
				<span class="chip" :title="TARGET_LABELS[mel.draft.target]">{{ mel.draft.target }} → {{ mel.outputName.toLowerCase() }}</span>
				<span v-if="mel.latest" class="chip" :title="mel.latest.file_name">
					rev {{ mel.latest.rev }} · {{ mel.latest.num_rows }} rows · key {{ mel.latest.key_header }}
				</span>
				<span class="spacer" />
				<span v-if="mel.dirty" class="unsaved">● Unsaved changes</span>
				<span v-else-if="mel.message" class="saved" :title="mel.message">✓ {{ mel.message }}</span>
				<HistoryButton v-if="mel.draft" entity="mel_recipe" :record-id="mel.draft.id" :label="mel.draft.name" />
				<button type="button" class="secondary" :disabled="!mel.dirty || mel.busy" @click="mel.discard()">Discard</button>
				<button type="button" :disabled="!mel.dirty || mel.busy" @click="mel.save()">Save</button>
			</div>
			<nav class="subtabs">
				<button
					v-for="t in TABS"
					:key="t.id"
					type="button"
					:class="{ active: mel.tab === t.id }"
					:disabled="t.id !== 'overview' && !mel.latest"
					@click="mel.tab = t.id"
				>
					{{ t.label }}<span v-if="t.count && t.count()" class="count">{{ t.count() }}</span>
				</button>
			</nav>
			<p v-if="mel.error" class="error">{{ mel.error }}</p>
			<div class="step-body">
				<component :is="panels[mel.tab]" :key="mel.tab" />
			</div>
		</section>
	</div>
</template>
