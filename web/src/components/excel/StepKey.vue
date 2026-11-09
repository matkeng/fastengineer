<script setup lang="ts">
import { computed } from 'vue';
import { useExcelWizard } from '../../stores/excelWizard';

const wiz = useExcelWizard();
const cols = computed(() => wiz.columns);
</script>

<template>
	<div v-if="cols">
		<p class="hint">
			Choose the key index column: the value that identifies each row, such as a tag or cable number. It becomes
			the first column of the results, and duplicate or blank keys are flagged.
			{{ cols.data_rows }} data rows found below the header.
		</p>
		<div class="grid-wrap">
			<table class="grid keys">
				<thead>
					<tr><th /><th>Column</th><th>Excel</th><th>Filled</th><th>Unique</th><th>Duplicates</th></tr>
				</thead>
				<tbody>
					<tr
						v-for="c in cols.columns"
						:key="c.index"
						:class="{ selected: wiz.keyColumn === c.index }"
						@click="wiz.chooseKey(c.index)"
					>
						<td><input type="radio" name="key" :checked="wiz.keyColumn === c.index" @change="wiz.chooseKey(c.index)" /></td>
						<td>
							<strong>{{ c.name }}</strong>
							<span v-if="c.index === cols.suggested_key" class="badge">suggested</span>
						</td>
						<td>{{ c.letter }}</td>
						<td>{{ c.non_blank }} / {{ cols.data_rows }}</td>
						<td>{{ c.unique }}</td>
						<td :class="{ warnText: c.duplicates }">{{ c.duplicates }}</td>
					</tr>
				</tbody>
			</table>
		</div>
		<label class="check">
			<input
				type="checkbox"
				:checked="wiz.skipBlankKeys"
				@change="wiz.setSkipBlankKeys(($event.target as HTMLInputElement).checked)"
			/>
			Skip rows where the key is blank (notes, subtotals, spacer rows)
		</label>
	</div>
</template>
