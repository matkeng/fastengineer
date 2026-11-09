<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed } from 'vue';
import type { GeneratorConfig } from '../../lib/genTypes';
import { useGenerators } from '../../stores/generators';

const g = useGenerators();
const cfg = computed(() => g.draft!.generator.config);
const rec = computed(() => g.draft!);
type BoolKey = { [K in keyof GeneratorConfig]: GeneratorConfig[K] extends boolean ? K : never }[keyof GeneratorConfig];
const FLAGS: { key: BoolKey; label: string; hint: string }[] = [
	{ key: 'blank_row_between_runs', label: 'Blank row between runs', hint: 'One empty row after each run in the output' },
	{ key: 'stop_at_blank_key', label: 'Stop at the first blank key', hint: 'Otherwise blank rows are skipped' },
	{ key: 'use_parents', label: 'Use Parents', hint: '_P and <<PARENT>> look up descriptions on Parents' },
	{ key: 'parent_include_tag', label: 'Parent text includes the tag', hint: '"DESCRIPTION (TAG) " instead of "DESCRIPTION"' },
	{ key: 'collapse_spaces', label: 'Collapse double spaces', hint: 'In expanded text' },
	{ key: 'replace_f_equals', label: 'F= starts a formula', hint: 'Late formulas such as F=<<LEN>>*<<QTY>>' },
	{ key: 'freeze_formulas', label: 'Expand tags in calculated values', hint: 'Lookups that return text with tags are expanded again' },
	{ key: 'keep_prev', label: 'Compare with the previous build', hint: 'Change report and locked runs' },
];
const numOrNull = (v: string) => (v.trim() === '' || !Number.isFinite(Number(v)) ? null : Number(v));
</script>

<template>
	<div class="gen-panel gen-settings">
		<fieldset>
			<legend>Runsheet</legend>
			<label>Key tag (selects the template) <input v-model="cfg.key_placeholder" /></label>
			<label>Run number tag <input v-model="cfg.run_placeholder" /></label>
			<label>Locked tag <input v-model="cfg.locked_placeholder" /></label>
			<label>From run <input :value="cfg.run_from ?? ''" class="num" @change="cfg.run_from = numOrNull(($event.target as HTMLInputElement).value)" /></label>
			<label title="Exclusive: this run number itself is not built">Run below <input :value="cfg.run_up_to ?? ''" class="num" @change="cfg.run_up_to = numOrNull(($event.target as HTMLInputElement).value)" /></label>
		</fieldset>
		<fieldset>
			<legend>Expansion</legend>
			<label v-for="f in FLAGS" :key="f.key" class="check" :title="f.hint"><input v-model="cfg[f.key]" type="checkbox" /> {{ f.label }} <span class="hint">{{ f.hint }}</span></label>
			<label>Mode
				<select v-model="cfg.mode">
					<option value="compat">Compatibility (same results as the Excel workbook)</option>
					<option value="standard">Standard (agreed fixes)</option>
				</select>
			</label>
		</fieldset>
		<fieldset>
			<legend>Output and export</legend>
			<label>Change report key column <input v-model="cfg.diff_key" /></label>
			<label>Run number column <input v-model="cfg.run_column" /></label>
			<label>Document number <input v-model="cfg.doc_number" /></label>
			<label>Document title <input v-model="cfg.doc_title" /></label>
			<label>Revision <input v-model="cfg.doc_revision" class="num" /></label>
		</fieldset>
		<fieldset>
			<legend>Source</legend>
			<p class="hint">
				Imported from <strong>{{ rec.source_file || '–' }}</strong>.
				<template v-if="rec.tables.length">Lookup tables (read-only):
					<span v-for="t in rec.tables" :key="t.name" class="chip">{{ t.name }} · {{ t.rows }} rows</span>
				</template>
				<template v-if="rec.generator.parents"> · Parents: {{ rec.generator.parents.length }} tags</template>
			</p>
		</fieldset>
	</div>
</template>
