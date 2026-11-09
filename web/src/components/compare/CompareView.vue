<script setup lang="ts">
import { computed, ref } from 'vue';
import sampleC from '../../../../samples/cable-schedule-sample.xlsx?url';
import sampleD from '../../../../samples/cable-schedule-sample-revD.xlsx?url';
import { STATUS_LABELS, type StatusFilter } from '../../lib/cells';
import type { RowStatus } from '../../lib/types';
import { useCompare, useNewTable, useOldTable } from '../../stores/compare';
import ExcelWizard from '../excel/ExcelWizard.vue';
import CompareTable from './CompareTable.vue';

const cmp = useCompare();
const oldT = useOldTable();
const newT = useNewTable();
const table = ref<InstanceType<typeof CompareTable> | null>(null);

const SAMPLE_C = { label: 'Use sample Rev C (old)', url: sampleC, filename: 'cable-schedule-sample.xlsx' };
const SAMPLE_D = { label: 'Use sample Rev D (new)', url: sampleD, filename: 'cable-schedule-sample-revD.xlsx' };

function oldDone() {
	cmp.stage = 'b';
}

const r = computed(() => cmp.result);
const chips = computed(() => {
	const s = r.value?.summary;
	if (!s) return [];
	const order: RowStatus[] = ['added', 'deleted', 'struck', 'restored', 'changed', 'unchanged'];
	return order.map((k) => ({ key: k, label: STATUS_LABELS[k], count: s[k] }));
});
const active = ref<StatusFilter>('changes');

function filter(v: StatusFilter) {
	active.value = v;
	table.value?.setStatusFilter(v);
}

function rerun() {
	active.value = 'changes';
	void cmp.run();
}

function sideLabel(w: typeof oldT) {
	const res = w.result;
	if (!res) return 'Not chosen yet';
	return `${w.workbook?.filename} · ${res.source.name} · ${res.rows.length} rows · key ${res.columns[res.key_column].name}`;
}
</script>

<template>
	<div class="compare">
		<!-- Choosing the two tables -->
		<template v-if="cmp.stage !== 'result'">
			<div class="sides">
				<button
					v-for="side in (['a', 'b'] as const)"
					:key="side"
					type="button"
					class="side"
					:class="{ current: cmp.stage === side, ready: !!(side === 'a' ? oldT : newT).result }"
					@click="cmp.stage = side"
				>
					<span class="side-title">{{ side === 'a' ? '1 · Old table' : '2 · New table' }}</span>
					<span class="side-desc">{{ sideLabel(side === 'a' ? oldT : newT) }}</span>
				</button>
				<button
					type="button"
					class="compare-go"
					:disabled="!oldT.result || !newT.result || cmp.busy"
					@click="cmp.run()"
				>
					{{ cmp.busy ? 'Comparing…' : 'Compare →' }}
				</button>
			</div>
			<p v-if="cmp.error" class="error">{{ cmp.error }}</p>

			<ExcelWizard
				v-if="cmp.stage === 'a'"
				key="a"
				:wiz="oldT"
				mode="pick"
				title="Old table (the earlier revision)"
				:samples="[SAMPLE_C]"
				@done="oldDone"
			>
				<template #last-actions>
					<button type="button" @click="cmp.stage = 'b'">Next: new table</button>
				</template>
			</ExcelWizard>
			<ExcelWizard
				v-else
				key="b"
				:wiz="newT"
				mode="pick"
				title="New table (the later revision)"
				:samples="[SAMPLE_D]"
				:reuse-from="oldT"
				@done="cmp.run()"
			>
				<template #last-actions>
					<button type="button" :disabled="!oldT.result || cmp.busy" @click="cmp.run()">Compare</button>
				</template>
			</ExcelWizard>
		</template>

		<!-- Results -->
		<section v-else-if="r" class="card wizard">
			<div class="compare-head">
				<span class="label-old" :title="r.a_label">Old: {{ r.a_label }}</span>
				<span class="arrow">→</span>
				<span class="label-new" :title="r.b_label">New: {{ r.b_label }}</span>
			</div>
			<div class="step-body">
				<div class="results">
					<div class="chips">
						<button
							type="button"
							class="chip filter-chip"
							:class="{ on: active === 'changes' }"
							@click="filter('changes')"
						>
							<strong>{{ r.summary.added + r.summary.deleted + r.summary.struck + r.summary.restored + r.summary.changed }}</strong> rows with changes
						</button>
						<button
							v-for="c in chips"
							:key="c.key"
							type="button"
							class="chip filter-chip"
							:class="[`status-${c.key}`, { on: active === c.key, zero: !c.count }]"
							@click="filter(c.key)"
						>
							<strong>{{ c.count }}</strong> {{ c.label.toLowerCase() }}
						</button>
						<button type="button" class="chip filter-chip" :class="{ on: active === '' }" @click="filter('')">all rows</button>
						<span class="chip"><strong>{{ r.summary.changed_cells }}</strong> changed cells</span>
						<span v-if="r.summary.columns_added" class="chip col-chip added">+{{ r.summary.columns_added }} column(s)</span>
						<span v-if="r.summary.columns_deleted" class="chip col-chip deleted">−{{ r.summary.columns_deleted }} column(s)</span>
						<span v-for="w in r.warnings" :key="w" class="chip warn-chip">⚠ {{ w }}</span>
						<span class="spacer" />
						<label class="opt"><input v-model="cmp.options.ignore_case" type="checkbox" @change="rerun" /> Ignore case</label>
						<label class="opt"><input v-model="cmp.options.compare_strike" type="checkbox" @change="rerun" /> Strikethrough counts as a change</label>
					</div>
					<CompareTable ref="table" :result="r" />
				</div>
			</div>
			<p v-if="cmp.error" class="error">{{ cmp.error }}</p>
			<div class="nav">
				<button type="button" class="secondary" @click="cmp.edit('a')">Change old table</button>
				<button type="button" class="secondary" @click="cmp.edit('b')">Change new table</button>
				<span class="spacer" />
				<button type="button" class="secondary" @click="cmp.reset()">New comparison</button>
			</div>
		</section>
	</div>
</template>
