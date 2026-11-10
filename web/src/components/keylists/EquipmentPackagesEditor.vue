<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import HistoryButton from '../audit/HistoryButton.vue';
import { computed, nextTick, ref } from 'vue';
import { PACKAGE_TYPES, type EquipmentPackage, equipmentPackageMatches, equipmentPackageProblems } from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';

const kl = useKeyLists();
const d = computed(() => kl.packagesDraft!);
const filter = ref('');
const host = ref<HTMLDivElement | null>(null);

// Same rules as the engine, so problems show while typing.
const problems = computed(() => ({ ...equipmentPackageProblems(d.value.items), ...kl.fieldErrors }));
const problemCount = computed(() => Object.keys(problems.value).length);
// Rows keep their place in the whole list (the number shown) while a filter hides others.
const rows = computed(() => d.value.items.map((item, index) => ({ item, index })).filter((r) => equipmentPackageMatches(r.item, filter.value)));

async function add() {
	const item: EquipmentPackage = { id: newId(), number: '', description: '', vendor: '', package_type: PACKAGE_TYPES[0] };
	d.value.items.push(item);
	filter.value = '';
	await nextTick();
	host.value?.querySelector<HTMLInputElement>(`[data-item="${item.id}"] input`)?.focus();
}

function move(i: number, by: -1 | 1) {
	const list = d.value.items;
	const j = i + by;
	if (j >= 0 && j < list.length) [list[i], list[j]] = [list[j], list[i]];
}
</script>

<template>
	<section class="card wizard ref-editor key-packages">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Equipment Packages</h2>
			<span class="spacer" />
			<span v-if="problemCount" class="warn small">{{ problemCount }} problem(s)</span>
			<span v-if="kl.packagesDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="kl.message" class="saved">✓ {{ kl.message }}</span>
			<HistoryButton entity="equipment_packages" record-id="equipment-packages" label="Equipment Packages" />
			<button type="button" class="secondary" :disabled="!kl.packagesDirty || kl.busy" @click="kl.discard()">Discard</button>
			<button type="button" :disabled="!kl.packagesDirty || kl.busy || problemCount > 0" @click="kl.savePackages()">Save</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>

		<div class="row tree-toolbar">
			<input v-model="filter" type="search" class="tree-filter" placeholder="Filter by number, description, vendor or type…" aria-label="Filter" />
			<span class="hint small">{{ d.items.length }} package(s)<template v-if="filter.trim()"> · {{ rows.length }} shown</template></span>
		</div>

		<div ref="host" class="grid-wrap">
			<table class="grid simple enum-items">
				<thead><tr><th class="num" /><th>Package number</th><th>Description</th><th>Vendor name</th><th>Package type</th><th /></tr></thead>
				<tbody>
					<tr v-for="r in rows" :key="r.item.id" :data-item="r.item.id">
						<td class="num">{{ r.index + 1 }}</td>
						<td>
							<input v-model="r.item.number" class="mono" aria-label="Package number" :class="{ invalid: problems[`${r.item.id}.number`] }" />
							<div v-if="problems[`${r.item.id}.number`]" class="warn small">{{ problems[`${r.item.id}.number`] }}</div>
						</td>
						<td>
							<input v-model="r.item.description" aria-label="Description" :class="{ invalid: problems[`${r.item.id}.description`] }" />
							<div v-if="problems[`${r.item.id}.description`]" class="warn small">{{ problems[`${r.item.id}.description`] }}</div>
						</td>
						<td><input v-model="r.item.vendor" aria-label="Vendor name" /></td>
						<td>
							<select v-model="r.item.package_type" aria-label="Package type">
								<option v-for="t in PACKAGE_TYPES" :key="t" :value="t">{{ t }}</option>
							</select>
						</td>
						<td class="actions">
							<button type="button" class="secondary small" :disabled="r.index === 0 || !!filter.trim()" title="Move up" @click="move(r.index, -1)">↑</button>
							<button type="button" class="secondary small" :disabled="r.index === d.items.length - 1 || !!filter.trim()" title="Move down" @click="move(r.index, 1)">↓</button>
							<button type="button" class="secondary small" title="Delete package" @click="d.items.splice(r.index, 1)">✕</button>
						</td>
					</tr>
					<tr v-if="!d.items.length"><td colspan="6" class="hint">No equipment packages yet. Add the first one below.</td></tr>
					<tr v-else-if="!rows.length"><td colspan="6" class="hint">Nothing matches “{{ filter }}”.</td></tr>
				</tbody>
			</table>
		</div>
		<div class="nav">
			<button type="button" @click="add">Add package</button>
			<span class="hint">Package numbers and descriptions are required and unique in the list (ignoring case). The vendor name is optional.</span>
		</div>
	</section>
</template>
