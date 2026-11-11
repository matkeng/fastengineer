<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import ListWorkbook from './ListWorkbook.vue';
import HistoryButton from '../audit/HistoryButton.vue';
import { computed, nextTick, ref } from 'vue';
import {
	PACKAGE_TYPES, type EquipmentPackage, type EquipmentType, copyName, equipmentPackageMatches, equipmentPackageProblems, equipmentTypeMatches,
} from '../../lib/keyListTypes';
import { newId } from '../../lib/refTypes';
import { useKeyLists } from '../../stores/keylists';
import AppModal from '../common/AppModal.vue';
import TemplateRows from './TemplateRows.vue';

// Equipment packages, each with its equipment types as child rows. The types are one flat
// list (each names its package), saved together with the packages.
const kl = useKeyLists();
const d = computed(() => kl.packagesDraft!);
const filter = ref('');
const filtering = computed(() => !!filter.value.trim());
const collapsed = ref(new Set<string>());
const host = ref<HTMLDivElement | null>(null);

// Same rules as the engine, so problems show while typing.
const problems = computed(() => ({ ...equipmentPackageProblems(d.value.items, d.value.types), ...kl.fieldErrors }));
const problemCount = computed(() => Object.keys(problems.value).length);

const typesOf = (packageId: string) => d.value.types.filter((t) => t.package_id === packageId);

/** Packages to show, each with the types to show under it. A filter keeps a package that
 *  matches (with all its types) or that has matching types (with only those), opened. */
const rows = computed(() => {
	const out: { item: EquipmentPackage; index: number; count: number; open: boolean; types: EquipmentType[] }[] = [];
	d.value.items.forEach((item, index) => {
		const all = typesOf(item.id);
		const own = equipmentPackageMatches(item, filter.value);
		const types = !filtering.value || own ? all : all.filter((t) => equipmentTypeMatches(t, filter.value));
		if (!own && !types.length) return;
		out.push({ item, index, count: all.length, open: filtering.value || !collapsed.value.has(item.id), types });
	});
	return out;
});

function toggle(id: string) {
	const s = new Set(collapsed.value);
	if (s.has(id)) s.delete(id);
	else s.add(id);
	collapsed.value = s;
}

async function focusRow(id: string) {
	await nextTick();
	host.value?.querySelector<HTMLInputElement>(`[data-item="${id}"] input`)?.focus();
}

function add() {
	const item: EquipmentPackage = { id: newId(), number: '', description: '', vendor: '', package_type: PACKAGE_TYPES[0] };
	d.value.items.push(item);
	filter.value = '';
	void focusRow(item.id);
}

function move(i: number, by: -1 | 1) {
	const list = d.value.items;
	const j = i + by;
	if (j >= 0 && j < list.length) [list[i], list[j]] = [list[j], list[i]];
}

function addType(pkg: EquipmentPackage) {
	const type: EquipmentType = { id: newId(), package_id: pkg.id, name: '', description: '', rows: {} };
	d.value.types.push(type);
	filter.value = '';
	if (collapsed.value.has(pkg.id)) toggle(pkg.id);
	void focusRow(type.id);
}

/** Swap a type with the previous or next type of the same package. */
function moveType(t: EquipmentType, by: -1 | 1) {
	const sibs = typesOf(t.package_id);
	const other = sibs[sibs.indexOf(t) + by];
	if (!other) return;
	const list = d.value.types;
	const i = list.indexOf(t);
	const j = list.indexOf(other);
	[list[i], list[j]] = [list[j], list[i]];
}

/** A copy of an equipment type, with its rows, straight after it (part of the draft: saved with Save). */
function cloneType(t: EquipmentType) {
	const list = d.value.types;
	const copy: EquipmentType = { ...JSON.parse(JSON.stringify(t)), id: newId(), name: copyName(t.name, list.map((x) => x.name), 'name') };
	list.splice(list.indexOf(t) + 1, 0, copy);
	filter.value = '';
	if (collapsed.value.has(t.package_id)) toggle(t.package_id);
	void focusRow(copy.id);
}

function removeType(t: EquipmentType) {
	d.value.types.splice(d.value.types.indexOf(t), 1);
}

// An equipment type's predefined rows for the deliverable lists (as a load type has), edited
// in a dialog. They are part of the draft: Save on the list saves them.
const listsOf = ref<EquipmentType | null>(null);
const rowCount = (t: EquipmentType) => Object.values(t.rows ?? {}).reduce((n, r) => n + r.length, 0);
const rowErrors = computed(() => (listsOf.value
	? Object.entries(problems.value).filter(([k]) => k.startsWith(`${listsOf.value!.id}.rows`)).map(([, m]) => m) : []));
function openLists(t: EquipmentType) {
	t.rows ??= {};
	listsOf.value = t;
}
function closeLists() {
	const t = listsOf.value;
	// rows left wholly blank, and lists left with none, are not kept
	if (t) t.rows = Object.fromEntries(Object.entries(t.rows).map(([k, v]) => [k, v.filter((r) => Object.keys(r).length)] as const).filter(([, v]) => v.length));
	listsOf.value = null;
}

const label = (p: EquipmentPackage) => [p.number, p.description].filter(Boolean).join(' – ') || '(new package)';
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
			<ListWorkbook list-id="equipment-packages" name="Equipment Packages" :unsaved="kl.packagesDirty" />
			<button type="button" class="secondary" :disabled="!kl.packagesDirty || kl.busy" @click="kl.discard()">Discard</button>
			<button type="button" :disabled="!kl.packagesDirty || kl.busy || problemCount > 0" @click="kl.savePackages()">Save</button>
		</div>
		<p v-if="kl.error" class="error">{{ kl.error }}</p>

		<div class="row tree-toolbar">
			<input v-model="filter" type="search" class="tree-filter" placeholder="Filter packages and equipment types…" aria-label="Filter" />
			<button type="button" class="secondary small" @click="collapsed = new Set()">Expand all</button>
			<button type="button" class="secondary small" @click="collapsed = new Set(d.items.map((p) => p.id))">Collapse all</button>
			<span class="hint small">{{ d.items.length }} package(s) · {{ d.types.length }} equipment type(s)<template v-if="filtering"> · {{ rows.length }} package(s) shown</template></span>
		</div>

		<div ref="host" class="grid-wrap">
			<table class="grid simple enum-items">
				<thead><tr><th class="num" /><th>Package number</th><th>Description</th><th>Vendor name</th><th>Package type</th><th /></tr></thead>
				<tbody>
					<template v-for="r in rows" :key="r.item.id">
						<tr class="package-row" :data-item="r.item.id">
							<td class="num">{{ r.index + 1 }}</td>
							<td>
								<div class="with-chev">
									<button v-if="r.count" type="button" class="chev" :class="{ open: r.open }" :disabled="filtering"
										:aria-label="r.open ? 'Hide equipment types' : 'Show equipment types'" @click="toggle(r.item.id)">▸</button>
									<span v-else class="chev-space" />
									<input v-model="r.item.number" class="mono" aria-label="Package number" :class="{ invalid: problems[`${r.item.id}.number`] }" />
									<span v-if="r.count" class="kids" :title="`${r.count} equipment type(s)`">{{ r.count }}</span>
								</div>
								<div v-if="problems[`${r.item.id}.number`]" class="warn small under-chev">{{ problems[`${r.item.id}.number`] }}</div>
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
								<button type="button" class="secondary small" title="Add an equipment type to this package" @click="addType(r.item)">+ Type</button>
								<button type="button" class="secondary small" :disabled="r.index === 0 || filtering" title="Move up" @click="move(r.index, -1)">↑</button>
								<button type="button" class="secondary small" :disabled="r.index === d.items.length - 1 || filtering" title="Move down" @click="move(r.index, 1)">↓</button>
								<button type="button" class="secondary small" :disabled="r.count > 0"
									:title="r.count ? `Has ${r.count} equipment type(s): move them to another package or delete them first` : 'Delete package'"
									@click="d.items.splice(r.index, 1)">✕</button>
							</td>
						</tr>
						<template v-if="r.open">
							<tr v-for="(t, ti) in r.types" :key="t.id" class="type-row" :data-item="t.id">
								<td class="num" />
								<td>
									<div class="with-chev type-name">
										<span class="elbow" :class="{ last: ti === r.types.length - 1 }" />
										<input v-model="t.name" aria-label="Equipment type name" placeholder="Equipment type name" :class="{ invalid: problems[`${t.id}.name`] }" />
									</div>
									<div v-if="problems[`${t.id}.name`]" class="warn small under-chev">{{ problems[`${t.id}.name`] }}</div>
								</td>
								<td><input v-model="t.description" aria-label="Equipment type description" placeholder="Description (optional)" /></td>
								<td colspan="2">
									<div class="with-chev">
										<span class="hint small in-package">in package</span>
										<select v-model="t.package_id" aria-label="Package" title="Move this equipment type to another package" :class="{ invalid: problems[`${t.id}.package`] }">
											<option v-for="p in d.items" :key="p.id" :value="p.id">{{ label(p) }}</option>
										</select>
									</div>
								</td>
								<td class="actions">
									<button type="button" class="secondary small" :class="{ 'has-rows': rowCount(t) }"
										title="The rows this equipment type has for the Cable Schedule, Equipment List, Instrument List and PLC I/O List"
										@click="openLists(t)">Lists<span class="count">{{ rowCount(t) }}</span></button>
									<button type="button" class="secondary small" :disabled="ti === 0 || filtering" title="Move up" @click="moveType(t, -1)">↑</button>
									<button type="button" class="secondary small" :disabled="ti === r.types.length - 1 || filtering" title="Move down" @click="moveType(t, 1)">↓</button>
									<button type="button" class="secondary small" title="Duplicate equipment type, with its rows" @click="cloneType(t)">⧉</button>
									<button type="button" class="secondary small" title="Delete equipment type" @click="removeType(t)">✕</button>
								</td>
							</tr>
						</template>
					</template>
					<tr v-if="!d.items.length"><td colspan="6" class="hint">No equipment packages yet. Add the first one below.</td></tr>
					<tr v-else-if="!rows.length"><td colspan="6" class="hint">Nothing matches “{{ filter }}”.</td></tr>
				</tbody>
			</table>
		</div>
		<div class="nav">
			<button type="button" @click="add">Add package</button>
			<span class="hint">Package numbers and descriptions are required and unique. Equipment type names are required and unique across all
				packages. A package with equipment types can't be deleted. <strong>Lists</strong> on an equipment type holds the rows the
				Instrument generator adds to the Project Master lists for each Instrument Runsheet row of that type.</span>
		</div>

		<AppModal class="type-lists" :open="!!listsOf" :title="`Lists of ${listsOf?.name || 'the equipment type'}`" @close="closeLists">
			<TemplateRows v-if="listsOf" :key="listsOf.id" :rows="listsOf.rows" :errors="rowErrors" :tags="kl.templateLists?.instrument_tags" :paths="kl.templateLists?.instrument_paths"
				:name="listsOf.name" kind="equipment">
				<template #default="{ list }">
					The rows this equipment type has for the <strong>{{ list.name }}</strong>, set out as a load type's are.
					The tags are the columns of the <strong>Instrument Runsheet</strong>: the <strong>Instrument generator</strong> adds these rows
					to the Project Master {{ list.name }} once for each runsheet row that names this equipment type, filled in from that row.
				</template>
			</TemplateRows>
			<template #footer>
				<span class="hint small">Kept with the list: press Save on Equipment Packages to save them.</span>
				<span class="spacer" />
				<button type="button" @click="closeLists">Done</button>
			</template>
		</AppModal>
	</section>
</template>
