<script setup lang="ts">
import { computed } from 'vue';
import { useExcelWizard } from '../../stores/excelWizard';
import ResultTable from './ResultTable.vue';

const wiz = useExcelWizard();
const r = computed(() => wiz.result);
const counts = computed(() => {
	const rows = r.value?.rows ?? [];
	return {
		full: rows.filter((x) => x.strike === 'full').length,
		partial: rows.filter((x) => x.strike === 'partial').length,
	};
});
</script>

<template>
	<div v-if="r">
		<div class="chips">
			<span class="chip"><strong>{{ r.rows.length }}</strong> rows</span>
			<span class="chip"><strong>{{ r.columns.length }}</strong> columns</span>
			<span class="chip">Key: <strong>{{ r.columns[r.key_column].name }}</strong></span>
			<span class="chip">{{ r.source.name }} · header row {{ r.header_row }}<template v-if="r.header_rows > 1">–{{ r.header_row + r.header_rows - 1 }}</template></span>
			<span v-if="counts.full" class="chip struck-chip">{{ counts.full }} struck out</span>
			<span v-if="counts.partial" class="chip struck-chip">{{ counts.partial }} partly struck</span>
			<span v-if="r.blank_keys_skipped" class="chip">{{ r.blank_keys_skipped }} blank-key rows skipped</span>
			<span v-if="r.duplicate_keys.length" class="chip warn-chip" :title="r.duplicate_keys.join(', ')">
				Duplicate keys: {{ r.duplicate_keys.slice(0, 5).join(', ') }}<template v-if="r.duplicate_keys.length > 5">…</template>
			</span>
		</div>
		<p v-for="w in r.warnings" :key="w" class="warn">{{ w }}</p>
		<ResultTable :result="r" />
	</div>
</template>
