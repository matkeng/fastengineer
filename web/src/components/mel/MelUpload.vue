<script setup lang="ts">
import { ref } from 'vue';
import melSample from '../../../../samples/mel-sample.csv?url';
import melSample2 from '../../../../samples/mel-sample-rev2.csv?url';
import type { CsvInspect } from '../../lib/melTypes';
import { useMel, useMelExcel } from '../../stores/mel';
import ExcelWizard from '../excel/ExcelWizard.vue';

const mel = useMel();
const excelWiz = useMelExcel();
const mode = ref<'csv' | 'excel'>('csv');
const file = ref<{ blob: Blob; name: string } | null>(null);
const info = ref<CsvInspect | null>(null);
const key = ref('');
const input = ref<HTMLInputElement | null>(null);

async function pick(blob: Blob | undefined, name: string) {
	if (!blob) return;
	file.value = { blob, name };
	info.value = (await mel.inspectCsv(blob)) ?? null;
	// Keep the key of the previous revision when the new file has it.
	const prev = mel.latest?.key_header;
	key.value = info.value ? (prev && info.value.headers.includes(prev) ? prev : info.value.suggested_key) : '';
}

async function sample(url: string, name: string) {
	await pick(await (await fetch(url)).blob(), name);
}

async function upload() {
	if (!file.value || !key.value) return;
	if (await mel.uploadCsv(file.value.blob, file.value.name, key.value)) {
		file.value = null;
		info.value = null;
	}
}

async function excelDone() {
	if (excelWiz.spec && (await mel.uploadExcel(excelWiz.spec))) {
		excelWiz.reset();
		mode.value = 'csv';
	}
}
</script>

<template>
	<div class="upload">
		<h4>{{ mel.latest ? `Upload revision ${mel.latest.rev + 1}` : 'Upload the first file' }}</h4>
		<div class="row seg">
			<button type="button" :class="mode === 'csv' ? '' : 'secondary'" @click="mode = 'csv'">CSV file</button>
			<button type="button" :class="mode === 'excel' ? '' : 'secondary'" @click="mode = 'excel'">From Excel…</button>
		</div>

		<template v-if="mode === 'csv'">
			<div class="row">
				<button type="button" class="secondary" @click="input?.click()">Choose CSV…</button>
				<input ref="input" type="file" accept=".csv,.txt" hidden
					@change="pick(($event.target as HTMLInputElement).files?.[0], ($event.target as HTMLInputElement).files?.[0]?.name ?? '')" />
				<span class="hint">or a sample:
					<button type="button" class="link" @click="sample(melSample, 'mel-sample.csv')">MEL rev 1</button> ·
					<button type="button" class="link" @click="sample(melSample2, 'mel-sample-rev2.csv')">MEL rev 2</button>
				</span>
			</div>
			<div v-if="info && file" class="inspect">
				<p><strong>{{ file.name }}</strong>: {{ info.num_rows }} rows, {{ info.headers.length }} columns.</p>
				<p v-for="w in info.warnings" :key="w" class="warn small">{{ w }}</p>
				<label class="field">
					Key column (identifies each row, usually the equipment tag)
					<select v-model="key">
						<option v-for="h in info.headers" :key="h" :value="h">{{ h }}<template v-if="h === info.suggested_key"> (suggested)</template></option>
					</select>
				</label>
				<p v-if="mel.latest && key !== mel.latest.key_header" class="warn small">
					The previous revision used "{{ mel.latest.key_header }}" as the key. Rules keyed by row won't match if the key changes.
				</p>
				<div class="grid-wrap small-grid">
					<table class="grid">
						<thead><tr><th v-for="h in info.headers" :key="h" :class="{ keyh: h === key }">{{ h }}</th></tr></thead>
						<tbody><tr v-for="(r, i) in info.sample" :key="i"><td v-for="h in info.headers" :key="h" :class="{ keyh: h === key }">{{ r[h] }}</td></tr></tbody>
					</table>
				</div>
				<button type="button" :disabled="mel.busy" @click="upload">Upload as revision {{ (mel.latest?.rev ?? 0) + 1 }}</button>
			</div>
		</template>
		<ExcelWizard v-else :wiz="excelWiz" mode="pick" title="Choose the sheet or table" @done="excelDone">
			<template #last-actions>
				<button type="button" :disabled="mel.busy" @click="excelDone">Upload</button>
			</template>
		</ExcelWizard>
	</div>
</template>
