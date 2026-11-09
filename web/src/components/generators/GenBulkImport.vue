<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Import an edited inputs workbook: per-sheet preview of what would change, then apply the ticked sheets.
import { computed, ref, watch } from 'vue';
import type { InputsImport, SheetPreview } from '../../lib/genTypes';
import { useGenerators } from '../../stores/generators';
import AppModal from '../common/AppModal.vue';

const props = defineProps<{ file: File | null }>();
const emit = defineEmits<{ close: [] }>();
const g = useGenerators();
const result = ref<InputsImport | null>(null);
const chosen = ref<Record<string, boolean>>({});
const open = ref<string | null>(null);
const done = ref<string[] | null>(null);

watch(() => props.file, async (f) => {
	result.value = null;
	done.value = null;
	open.value = null;
	if (!f) return;
	const r = await g.importInputs(f);
	if (!r) return;
	result.value = r;
	chosen.value = Object.fromEntries(r.preview.sheets.map((s) => [s.table, !s.errors.length && differs(s)]));
	open.value = r.preview.sheets.find((s) => differs(s) || s.errors.length)?.table ?? null;
}, { immediate: true });

const differs = (s: SheetPreview) => !!(s.added || s.removed || s.changed);
const tables = computed(() => Object.entries(chosen.value).filter(([, v]) => v).map(([k]) => k));
const shared = computed(() => tables.value.some((t) => t === 'card_types' || t === 'rack_types'));

async function apply() {
	if (!props.file || !tables.value.length) return;
	const r = await g.importInputs(props.file, tables.value);
	if (r?.applied.length) done.value = r.applied;
}
</script>

<template>
	<AppModal :open="!!file" :title="`Import inputs: ${file?.name ?? ''}`" @close="emit('close')">
		<p v-if="g.busy && !result" class="hint">Reading the workbook…</p>
		<p v-if="g.error" class="error">{{ g.error }}</p>
		<template v-if="result && !done">
			<p class="hint">Nothing is saved until you apply. Tick the sheets to apply; sheets not in the file stay as they are.</p>
			<table class="grid simple bulk-sheets">
				<thead><tr><th /><th>Sheet</th><th>Rows</th><th>Added</th><th>Removed</th><th>Changed</th><th /></tr></thead>
				<tbody>
					<template v-for="s in result.preview.sheets" :key="s.table">
						<tr :class="{ err: s.errors.length, same: !differs(s) && !s.errors.length }">
							<td><input v-model="chosen[s.table]" type="checkbox" :disabled="!!s.errors.length || !differs(s)" :aria-label="`Apply ${s.sheet}`" /></td>
							<td><strong>{{ s.sheet }}</strong></td>
							<td>{{ s.rows }}</td>
							<td :class="{ plus: s.added }">{{ s.added || '' }}</td>
							<td :class="{ minus: s.removed }">{{ s.removed || '' }}</td>
							<td :class="{ change: s.changed }">{{ s.changed || '' }}</td>
							<td>
								<span v-if="s.errors.length" class="error">{{ s.errors[0] }}</span>
								<span v-else-if="!differs(s)" class="hint">no changes</span>
								<button v-else type="button" class="link" @click="open = open === s.table ? null : s.table">{{ open === s.table ? 'Hide' : 'Show' }} changes</button>
								<span v-for="n in s.notes" :key="n" class="hint"> · {{ n }}</span>
							</td>
						</tr>
						<tr v-if="open === s.table && s.changes.length" class="detail">
							<td colspan="7">
								<ul class="bulk-changes">
									<li v-for="(c, i) in s.changes" :key="i">
										<span class="chg" :class="`chg-${c.kind}`">{{ c.kind }}</span> <strong>{{ c.key }}</strong>
										<span v-for="(cell, j) in c.cells.slice(0, 6)" :key="j" class="cell-change">
											{{ cell[0] }}: <s>{{ cell[1] || '(blank)' }}</s> → {{ cell[2] || '(blank)' }}
										</span>
										<span v-if="c.cells.length > 6" class="hint">and {{ c.cells.length - 6 }} more</span>
									</li>
								</ul>
								<p v-if="s.changes.length >= 200" class="hint">Only the first 200 changes are listed.</p>
							</td>
						</tr>
					</template>
				</tbody>
			</table>
			<p v-if="result.preview.ignored_sheets.length" class="hint">Sheets not recognised (ignored): {{ result.preview.ignored_sheets.join(', ') }}</p>
			<p v-if="shared" class="warn">Card and rack types are shared by every generator.</p>
		</template>
		<p v-if="done" class="saved">✓ Applied {{ done.length }} sheet{{ done.length === 1 ? '' : 's' }}. Build again to see the effect on the output.</p>
		<template #footer>
			<span class="spacer" />
			<button type="button" class="secondary" @click="emit('close')">{{ done ? 'Close' : 'Cancel' }}</button>
			<button v-if="!done" type="button" :disabled="!tables.length || g.busy" @click="apply">Apply {{ tables.length }} sheet{{ tables.length === 1 ? '' : 's' }}</button>
		</template>
	</AppModal>
</template>
