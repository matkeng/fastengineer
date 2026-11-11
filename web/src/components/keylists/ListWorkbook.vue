<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Export .xlsx and Import .xlsx for a project list. The export is the saved list. An import
// is read and checked first and shown as a summary; only "Replace" (or "Apply") saves it,
// through the list's own save, so the same rules hold as when it is edited in the app.
import { ref } from 'vue';
import { apiPostBytes, apiPostJsonForBlob, exportToPath, runningInTauri } from '../../lib/engine';
import type { KeyListId } from '../../lib/keyListTypes';
import { useKeyLists } from '../../stores/keylists';
import AppModal from '../common/AppModal.vue';

interface Preview { summary: string; notes: string[]; applied: boolean }
const props = defineProps<{ listId: KeyListId; name: string; unsaved?: boolean; exportOnly?: boolean }>();
const kl = useKeyLists();
const busy = ref(false);
const error = ref('');
const done = ref('');
const input = ref<HTMLInputElement | null>(null);
const importing = ref<{ file: File; preview: Preview } | null>(null);
const url = (what: string) => `/api/list-workbooks/${props.listId}/${what}`;
const message = (err: unknown) => (err instanceof Error ? err.message : String(err));
// the Load List's rows come from the imports: a file changes rows, it doesn't replace the list
const changesRows = props.listId === 'load-list';

async function exportList() {
	busy.value = true;
	error.value = done.value = '';
	const file = `${props.name}.xlsx`;
	try {
		if (runningInTauri) {
			const { save } = await import('@tauri-apps/plugin-dialog');
			const path = await save({ defaultPath: file, filters: [{ name: 'Excel workbook', extensions: ['xlsx'] }] });
			if (path) done.value = `Saved ${(await exportToPath(url('export'), {}, path)).path}`;
		} else {
			const href = URL.createObjectURL(await apiPostJsonForBlob(url('export'), {}));
			Object.assign(document.createElement('a'), { href, download: file }).click();
			setTimeout(() => URL.revokeObjectURL(href), 10_000);
			done.value = `Downloaded ${file}`;
		}
	} catch (err) {
		error.value = message(err);
	} finally {
		busy.value = false;
	}
}

async function send(file: File, apply: boolean): Promise<Preview | undefined> {
	busy.value = true;
	error.value = done.value = '';
	try {
		const q = new URLSearchParams({ filename: file.name, apply: String(apply) });
		return await apiPostBytes<Preview>(`${url('import')}?${q}`, file);
	} catch (err) {
		error.value = message(err);
		return undefined;
	} finally {
		busy.value = false;
	}
}

async function pick(e: Event) {
	const el = e.target as HTMLInputElement;
	const file = el.files?.[0];
	el.value = '';
	if (!file) return;
	const preview = await send(file, false);
	if (preview) importing.value = { file, preview };
}

async function apply() {
	const i = importing.value;
	if (!i) return;
	const res = await send(i.file, true);
	if (!res?.applied) return; // the reason is shown in the dialog
	importing.value = null;
	done.value = [`Imported ${i.file.name}`, ...(changesRows ? res.notes.slice(-2) : [])].join('. ');
	await kl.load();
	if (props.listId === 'load-list') await kl.loadLoadList();
}
</script>

<template>
	<span class="list-workbook">
		<span v-if="done" class="saved" :title="done">✓ {{ done }}</span>
		<span v-else-if="error && !importing" class="warn small" :title="error">{{ error }}</span>
		<button type="button" class="secondary" :disabled="busy || unsaved" :title="unsaved ? 'Save or discard your changes first' : `The saved ${name}, as an Excel workbook`" @click="exportList">Export .xlsx</button>
		<button v-if="!exportOnly" type="button" class="secondary" :disabled="busy || unsaved" :title="unsaved ? 'Save or discard your changes first' : `Read ${name} from an Excel workbook (you see what it holds before anything changes)`" @click="input?.click()">Import .xlsx…</button>
		<input ref="input" type="file" accept=".xlsx" hidden @change="pick" />
		<AppModal :open="!!importing" :title="`Import ${name}`" @close="importing = null">
			<template v-if="importing">
				<p><strong>{{ importing.file.name }}</strong></p>
				<p>{{ importing.preview.summary }}</p>
				<ul v-if="importing.preview.notes.length" class="hint"><li v-for="n in importing.preview.notes" :key="n">{{ n }}</li></ul>
				<p v-if="changesRows" class="hint small">Rows are matched by Source and Key. Only the plant area, load type, distribution panel, supplied from and cable columns are read; everything else comes from the imports.</p>
				<p v-else class="warn small">Importing replaces the whole list with the file. Rows are matched by name, so what refers to them still does; a row that is in use elsewhere can't be removed.</p>
				<p v-if="error" class="error">{{ error }}</p>
			</template>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="importing = null">Cancel</button>
				<button type="button" :disabled="busy" @click="apply">{{ changesRows ? 'Apply the changes' : 'Replace the list' }}</button>
			</template>
		</AppModal>
	</span>
</template>
