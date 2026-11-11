<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Export and import one load type's or equipment type's rows as a workbook: a sheet per list
// (Cable Schedule, Equipment List, Instrument List, PLC I/O List) and a Tags sheet of what a cell
// can use. The export is the rows as they are in the editor, saved or not. An import is read and
// checked first; "Replace" puts its rows in the editor, saved with the form's Save.
import { ref, toRaw } from 'vue';
import { apiPostBytes, apiPostJsonForBlob, exportToPath, runningInTauri } from '../../lib/engine';
import type { TemplateRows } from '../../lib/keyListTypes';
import AppModal from '../common/AppModal.vue';

interface Read { rows: TemplateRows; counts: Record<string, number>; notes: string[] }
const props = defineProps<{ name: string; kind: 'load' | 'equipment'; rows: TemplateRows }>();
const emit = defineEmits<{ replace: [rows: TemplateRows] }>();
const busy = ref(false);
const error = ref('');
const done = ref('');
const input = ref<HTMLInputElement | null>(null);
const importing = ref<{ file: File; read: Read } | null>(null);
const URL_EXPORT = '/api/list-workbooks/type-rows/export';
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));
const fileName = () => `${(props.name.trim() || 'type').replace(/[\\/:*?"<>|]+/g, '_')} rows.xlsx`;

async function exportRows() {
	busy.value = true;
	error.value = done.value = '';
	const body = { name: props.name, kind: props.kind, rows: JSON.parse(JSON.stringify(toRaw(props.rows))) };
	try {
		if (runningInTauri) {
			const { save } = await import('@tauri-apps/plugin-dialog');
			const path = await save({ defaultPath: fileName(), filters: [{ name: 'Excel workbook', extensions: ['xlsx'] }] });
			if (path) done.value = `Saved ${(await exportToPath(URL_EXPORT, body, path)).path}`;
		} else {
			const href = URL.createObjectURL(await apiPostJsonForBlob(URL_EXPORT, body));
			Object.assign(document.createElement('a'), { href, download: fileName() }).click();
			setTimeout(() => URL.revokeObjectURL(href), 10_000);
			done.value = `Downloaded ${fileName()}`;
		}
	} catch (err) {
		error.value = message(err);
	} finally {
		busy.value = false;
	}
}

async function pick(e: Event) {
	const el = e.target as HTMLInputElement;
	const file = el.files?.[0];
	el.value = '';
	if (!file) return;
	busy.value = true;
	error.value = done.value = '';
	try {
		const q = new URLSearchParams({ kind: props.kind, filename: file.name });
		importing.value = { file, read: await apiPostBytes<Read>(`/api/list-workbooks/type-rows/import?${q}`, file) };
	} catch (err) {
		error.value = message(err);
	} finally {
		busy.value = false;
	}
}

function replace() {
	const i = importing.value;
	if (!i) return;
	emit('replace', i.read.rows);
	done.value = `Read ${i.file.name}: save to keep it`;
	importing.value = null;
}
</script>

<template>
	<span class="list-workbook type-rows-workbook">
		<span v-if="done" class="saved" :title="done">✓ {{ done }}</span>
		<span v-else-if="error" class="warn small" :title="error">{{ error }}</span>
		<button type="button" class="secondary small" :disabled="busy" :title="`${name}'s rows, a sheet per list, as an Excel workbook`"
			@click="exportRows">Export rows .xlsx</button>
		<button type="button" class="secondary small" :disabled="busy" :title="`Read ${name}'s rows from an Excel workbook (you see what it holds first)`"
			@click="input?.click()">Import rows…</button>
		<input ref="input" type="file" accept=".xlsx" hidden @change="pick" />
		<AppModal :open="!!importing" :title="`Import ${name}'s rows`" @close="importing = null">
			<template v-if="importing">
				<p><strong>{{ importing.file.name }}</strong></p>
				<ul>
					<li v-for="(n, list) in importing.read.counts" :key="list">{{ list }}: {{ n }} row(s)</li>
				</ul>
				<ul v-if="importing.read.notes.length" class="hint"><li v-for="n in importing.read.notes" :key="n">{{ n }}</li></ul>
				<p class="hint small">Replace puts these rows in place of {{ name }}'s rows for those lists. Nothing is saved until you Save.</p>
			</template>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="importing = null">Cancel</button>
				<button type="button" @click="replace">Replace rows</button>
			</template>
		</AppModal>
	</span>
</template>
