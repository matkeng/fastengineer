<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The predefined rows something has for the deliverable lists: one tab per list (Cable
// Schedule, Equipment List, Instrument List, PLC I/O List), each a grid whose cells can hold
// <<tags>>. The same lists, columns and tags as a load type's rows. Edits go straight into `rows`.
import { computed, onMounted, ref, watch } from 'vue';
import { type TemplateRows, modifierText } from '../../lib/keyListTypes';
import { useKeyLists } from '../../stores/keylists';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';
import { useUndo } from '../../lib/history';
import TagHelp from './TagHelp.vue';
import TypeRowsWorkbook from './TypeRowsWorkbook.vue';

// `tags`, `paths`: the tags and the linked records' dotted tags to offer (default: a load's, as for a load type).
// `name`, `kind`: whose rows they are, for Export / Import rows (left out: no workbook buttons).
const props = defineProps<{ rows: TemplateRows; errors?: string[]; tags?: { tag: string; meaning: string }[]; paths?: { tag: string; meaning: string }[];
	name?: string; kind?: 'load' | 'equipment' }>();
const kl = useKeyLists();
// Undo for the grid, across the lists' rows; it starts again when another record's rows are shown.
const hist = useUndo({ get: () => props.rows, resetOn: () => props.rows });
onMounted(() => kl.loadTemplateLists());
const lists = computed(() => kl.templateLists?.lists ?? []);
const tagList = computed(() => props.tags ?? kl.templateLists?.tags ?? []);
const pathList = computed(() => props.paths ?? kl.templateLists?.paths ?? []);
const modifiers = computed(() => kl.templateLists?.modifiers ?? []);
const tagNames = computed(() => [...tagList.value, ...pathList.value].map((t) => t.tag));
const modifierNames = computed(() => modifiers.value.map(modifierText));
const tab = ref('');
watch(lists, (l) => { if (!tab.value && l.length) tab.value = l[0].key; }, { immediate: true });
const list = computed(() => lists.value.find((l) => l.key === tab.value) ?? null);
const listRows = computed(() => (list.value ? (props.rows[list.value.key] ??= []) : []));
// A list's row settings (the cable schedule's "Repeat") come first, then its columns.
const settings = computed(() => list.value?.settings ?? []);
const fields = computed(() => [...settings.value.map((s) => s.name), ...(list.value?.columns ?? [])]);
const gridCols = computed((): GridColumn[] => [
	...settings.value.map((s): GridColumn => ({ label: s.name, options: s.values, width: 130, badge: 'setting',
		title: `Blank: one row. ${s.values.join(' / ')}: one row for each power cable.` })),
	...(list.value?.columns ?? []).map((c): GridColumn => ({ label: c, width: /Description|Remarks|Code/.test(c) ? 200 : 130 })),
]);
const gridCells = computed(() => listRows.value.map((r) => fields.value.map((c) => r[c] ?? '')));
const tagClass = (r: number, c: number) => (/<<[^<>]+>>/.test(gridCells.value[r]?.[c] ?? '') ? 'has-tag' : '');

function setCells(edits: CellEdit[]) {
	for (const e of edits) {
		const row = listRows.value[e.r];
		const field = fields.value[e.c];
		if (!row || !field) continue;
		if (e.value.trim()) row[field] = e.value;
		else delete row[field];
	}
}
const insertRows = (at: number, count: number) => listRows.value.splice(at, 0, ...Array.from({ length: count }, () => ({})));
/** An imported workbook's rows, in place of these lists' rows. */
function replaceRows(rows: TemplateRows) {
	for (const [k, v] of Object.entries(rows)) props.rows[k] = v;
}
function removeRows(idx: number[]) {
	if (!list.value) return;
	const drop = new Set(idx);
	props.rows[list.value.key] = listRows.value.filter((_, i) => !drop.has(i));
}
</script>

<template>
	<div class="tpl-rows">
		<div v-if="kind" class="row tight tpl-workbook"><span class="spacer" />
			<TypeRowsWorkbook :name="name ?? ''" :kind="kind" :rows="rows" @replace="replaceRows" /></div>
		<nav class="subtabs small">
			<button v-for="l in lists" :key="l.key" type="button" :class="{ active: tab === l.key }" @click="tab = l.key">
				{{ l.name }}<span class="count">{{ rows[l.key]?.length ?? 0 }}</span>
			</button>
		</nav>
		<template v-if="list">
			<p class="hint small">
				<slot :list="list" />
				Type <code>&lt;&lt;</code> in a cell to pick a tag, a <code>.</code> to follow a link (<code>&lt;&lt;LoadType.Name&gt;&gt;</code>)
				and <code>|</code> for a modifier (<code>&lt;&lt;Tag|upper&gt;&gt;</code>).
				<TagHelp :tags="tagList" :paths="pathList" :modifiers="modifiers" />
			</p>
			<EditGrid :columns="gridCols" :cells="gridCells" :history="hist" :tag-suggestions="tagNames" :modifier-suggestions="modifierNames" :cell-class="tagClass"
				:height="Math.min(360, 96 + 26 * Math.max(4, listRows.length))" @set="setCells" @insert="insertRows" @remove="removeRows" />
			<p v-if="!listRows.length" class="hint small">No rows yet for the {{ list.name }}. Use “+ Row”.</p>
			<p v-for="m in errors ?? []" :key="m" class="warn small">{{ m }}</p>
		</template>
	</div>
</template>
