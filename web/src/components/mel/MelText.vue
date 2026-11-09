<script setup lang="ts">
import { computed } from 'vue';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const mel = useMel();
const { result } = useStage('rows', (r) => [r.columns, r.hidden_rows]);
const taken = computed(() => new Set(result.value?.headers ?? []));

function add() {
	const d = mel.draft!;
	let n = 1;
	while (taken.value.has(`New column ${n}`) || d.text_columns.some((t) => t.name === `New column ${n}`)) n++;
	d.text_columns.push({ name: `New column ${n}`, value: '' });
}

function problem(i: number): string | null {
	const t = mel.draft!.text_columns[i];
	if (!t.name.trim()) return 'Needs a name';
	if (taken.value.has(t.name.trim())) return 'A column with this name already exists';
	if (mel.draft!.text_columns.some((x, j) => j < i && x.name.trim() === t.name.trim())) return 'Duplicate name';
	return null;
}
</script>

<template>
	<div>
		<p class="hint">
			Add columns that hold the same value in every row, for example <code>source = MEL</code> or
			<code>load_type = Motor</code>. Individual cells can still be changed with an override.
		</p>
		<table v-if="mel.draft!.text_columns.length" class="grid simple">
			<thead><tr><th>Column name</th><th>Value in every row</th><th /></tr></thead>
			<tbody>
				<tr v-for="(t, i) in mel.draft!.text_columns" :key="i">
					<td><input v-model="t.name" aria-label="Column name" /><div v-if="problem(i)" class="warn small">{{ problem(i) }}</div></td>
					<td><input v-model="t.value" aria-label="Value" /></td>
					<td class="actions"><button type="button" class="secondary small" @click="mel.draft!.text_columns.splice(i, 1)">Delete</button></td>
				</tr>
			</tbody>
		</table>
		<button type="button" @click="add">Add text column</button>
	</div>
</template>
