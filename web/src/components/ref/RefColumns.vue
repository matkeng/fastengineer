<script setup lang="ts">
import { computed } from 'vue';
import { COLUMN_TYPE_LABELS, type ColumnType, newId } from '../../lib/refTypes';
import { useRefData } from '../../stores/refdata';

const rd = useRefData();
const cols = computed(() => rd.tableDraft!.columns);
const enumList = computed(() => Object.values(rd.allEnums).sort((a, b) => a.name.localeCompare(b.name)));
const savedIds = computed(() => new Set(rd.table?.table.columns.map((c) => c.id) ?? []));
const hasRows = computed(() => (rd.table?.rows.length ?? 0) > 0);

function add() {
	let n = 1;
	while (cols.value.some((c) => c.name === `Column ${n}`)) n++;
	cols.value.push({ id: newId(), name: `Column ${n}`, type: 'text', enum_id: null, required: false, unique: false });
}

function move(i: number, by: -1 | 1) {
	const j = i + by;
	if (j >= 0 && j < cols.value.length) [cols.value[i], cols.value[j]] = [cols.value[j], cols.value[i]];
}

function remove(i: number) {
	const c = cols.value[i];
	if (savedIds.value.has(c.id) && hasRows.value && !confirm(`Delete column "${c.name}"? Its values in every row are removed when you save.`)) return;
	cols.value.splice(i, 1);
}

function setType(i: number, t: ColumnType) {
	const c = cols.value[i];
	c.type = t;
	if (t === 'enum' && !c.enum_id) c.enum_id = enumList.value[0]?.id ?? null;
	if (t !== 'enum') c.enum_id = null;
}
</script>

<template>
	<div>
		<p class="hint">
			Define the columns, then <strong>Save</strong>. Changing a column's type converts the existing rows
			(e.g. text "12" to the number 12, or a list code to its item); if any value can't be converted, nothing is
			saved and the problem values are shown.
		</p>
		<div class="grid-wrap">
			<table class="grid simple cols-def">
				<thead><tr><th class="num" /><th>Column name</th><th>Type</th><th>List</th><th>Required</th><th>Unique</th><th /></tr></thead>
				<tbody>
					<tr v-for="(c, i) in cols" :key="c.id">
						<td class="num">{{ i + 1 }}</td>
						<td>
							<input v-model="c.name" aria-label="Column name" :class="{ invalid: rd.fieldErrors[`${c.id}.name`] }" />
							<div v-if="rd.fieldErrors[`${c.id}.name`]" class="warn small">{{ rd.fieldErrors[`${c.id}.name`] }}</div>
							<div v-if="rd.fieldErrors[c.id]" class="warn small">{{ rd.fieldErrors[c.id] }}</div>
						</td>
						<td>
							<select :value="c.type" aria-label="Type" @change="setType(i, ($event.target as HTMLSelectElement).value as ColumnType)">
								<option v-for="(label, t) in COLUMN_TYPE_LABELS" :key="t" :value="t">{{ label }}</option>
							</select>
						</td>
						<td>
							<select v-if="c.type === 'enum'" v-model="c.enum_id" aria-label="List">
								<option :value="null" disabled>Choose a list…</option>
								<option v-for="e in enumList" :key="e.id" :value="e.id">{{ e.name }}</option>
							</select>
							<div v-if="c.type === 'enum' && !enumList.length" class="warn small">Create a list first</div>
							<div v-if="rd.fieldErrors[`${c.id}.enum_id`]" class="warn small">{{ rd.fieldErrors[`${c.id}.enum_id`] }}</div>
						</td>
						<td class="center"><input v-model="c.required" type="checkbox" aria-label="Required" /></td>
						<td class="center"><input v-model="c.unique" type="checkbox" aria-label="Unique" /></td>
						<td class="actions">
							<button type="button" class="secondary small" :disabled="i === 0" title="Move up" @click="move(i, -1)">↑</button>
							<button type="button" class="secondary small" :disabled="i === cols.length - 1" title="Move down" @click="move(i, 1)">↓</button>
							<button type="button" class="secondary small" title="Delete column" @click="remove(i)">✕</button>
						</td>
					</tr>
					<tr v-if="!cols.length"><td colspan="7" class="hint">No columns yet. Add one to start.</td></tr>
				</tbody>
			</table>
		</div>
		<div class="row"><button type="button" @click="add">Add column</button></div>
	</div>
</template>
