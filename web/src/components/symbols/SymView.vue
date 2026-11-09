<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import pidLibrary from '../../../../samples/pid-library.json?url';
import pidSample from '../../../../samples/pid-sample.pdf?url';
import pidScanned from '../../../../samples/pid-sample-scanned.pdf?url';
import { useSymbols } from '../../stores/symbols';
import SymLibrary from './SymLibrary.vue';
import SymPageViewer from './SymPageViewer.vue';
import SymRun from './SymRun.vue';
import SymTemplateEditor from './SymTemplateEditor.vue';

const emit = defineEmits<{ 'open-import': [recipeId: string] }>();
const sym = useSymbols();
const fileInput = ref<HTMLInputElement | null>(null);
const libInput = ref<HTMLInputElement | null>(null);
const imgInput = ref<HTMLInputElement | null>(null);

const libTemplates = computed(() => sym.templates.filter((t) => t.library_id === sym.libraryId));
const checkedReady = computed(() => sym.checked.filter((id) => sym.drawings.some((d) => d.id === id && d.status === 'ready')));
const hasExample = computed(() => sym.libraries.some((l) => l.name.startsWith('P&ID instruments')));

async function onFiles(files: FileList | null | undefined) {
	for (const f of Array.from(files ?? [])) await sym.upload(f, f.name, sym.libraryId);
	if (fileInput.value) fileInput.value.value = '';
}

async function sample(url: string, name: string) {
	// The samples belong with the P&ID example library.
	const lib = sym.libraries.find((l) => l.name.startsWith('P&ID instruments')) ?? sym.library;
	if (lib) await sym.upload(await (await fetch(url)).blob(), name, lib.id);
}

async function loadLibrary(file: File | Blob | undefined) {
	if (!file) return;
	try {
		await sym.importLibrary(JSON.parse(await file.text()));
	} catch (err) {
		sym.error = `That file is not a symbol library: ${err instanceof Error ? err.message : err}`;
	}
	if (libInput.value) libInput.value.value = '';
}

async function onTemplateImage(file: File | undefined) {
	if (!file) return;
	await sym.uploadTemplate(file, file.name, sym.libraryId);
	if (imgInput.value) imgInput.value.value = '';
}

function toggle(id: string) {
	const i = sym.checked.indexOf(id);
	if (i >= 0) sym.checked.splice(i, 1);
	else sym.checked.push(id);
}

function removeDrawing(id: string, name: string) {
	if (confirm(`Remove ${name} and its results?`)) void sym.removeDrawing(id);
}

async function newLibrary() {
	const name = prompt('Name of the new library (e.g. "Electrical schematics" or "Fire alarm devices")');
	if (name?.trim()) await sym.createLibrary(name.trim());
}

const isCurrent = (kind: string, id?: string) => {
	const v = sym.view as { kind: string; id?: string };
	return v.kind === kind && (id === undefined || v.id === id);
};

onMounted(() => sym.refresh());
</script>

<template>
	<div class="sym">
		<div class="sym-layout">
			<aside class="card ref-side sym-sidebar">
				<section>
					<h3>Library</h3>
					<div class="row tight">
						<select v-model="sym.libraryId" aria-label="Symbol library" class="grow">
							<option v-for="l in sym.libraries" :key="l.id" :value="l.id">{{ l.name }}</option>
						</select>
						<button type="button" class="secondary small" :disabled="!sym.library" title="Tag rules, ignored text, export" @click="sym.openLibrary(sym.libraryId)">Settings</button>
					</div>
					<p v-if="sym.library?.description" class="hint">{{ sym.library.description }}</p>
					<div class="row tight wrap">
						<button type="button" class="link small" @click="newLibrary">New library…</button>
						<button type="button" class="link small" @click="libInput?.click()">Import…</button>
						<input ref="libInput" type="file" accept=".json" hidden @change="loadLibrary(($event.target as HTMLInputElement).files?.[0])" />
						<button v-if="!hasExample" type="button" class="link small" @click="sym.restoreExample()">Add the P&amp;ID example</button>
					</div>
				</section>

				<section>
					<h3>Templates</h3>
					<p class="hint">Matched in this order; each match is blanked before the next runs, so put specific symbols first.</p>
					<ol class="ref-nav sym-tlist">
						<li v-for="(t, i) in libTemplates" :key="t.id" :class="{ current: isCurrent('template', t.id), off: !t.active }" @click="sym.openTemplate(t.id)">
							<span class="name">{{ t.desc }}</span>
							<span v-if="t.mask_mode === 'custom'" class="count" title="Custom mask">M</span>
							<span v-if="t.points.length" class="count" title="Tag points">{{ t.points.length }}</span>
							<button type="button" class="link small" :disabled="i === 0" title="Move up" @click.stop="sym.moveTemplate(t.id, i - 1)">▲</button>
							<button type="button" class="link small" :disabled="i === libTemplates.length - 1" title="Move down" @click.stop="sym.moveTemplate(t.id, i + 1)">▼</button>
						</li>
					</ol>
					<p v-if="!libTemplates.length" class="hint">None yet: open a drawing and use <strong>New template</strong>, or add a symbol image.</p>
					<button type="button" class="secondary small" :disabled="!sym.library" title="Add a symbol image file as a template" @click="imgInput?.click()">Add image…</button>
					<input ref="imgInput" type="file" accept="image/*" hidden @change="onTemplateImage(($event.target as HTMLInputElement).files?.[0])" />
				</section>

				<section>
					<h3>Drawings</h3>
					<div class="row tight wrap">
						<button type="button" class="small" :disabled="!sym.library" @click="fileInput?.click()">Add PDFs…</button>
						<input ref="fileInput" type="file" accept=".pdf,application/pdf" multiple hidden @change="onFiles(($event.target as HTMLInputElement).files)" />
						<span class="hint small">into “{{ sym.library?.name }}”</span>
					</div>
					<p class="hint">P&amp;ID samples:
						<button type="button" class="link" @click="sample(pidSample, 'pid-sample.pdf')">drawing</button> ·
						<button type="button" class="link" @click="sample(pidScanned, 'pid-sample-scanned.pdf')">scanned</button> ·
						<a class="link" :href="pidLibrary" download="pid-library.json">library file</a>
					</p>
					<ul class="ref-nav">
						<li v-for="d in sym.drawings" :key="d.id" :class="{ current: isCurrent('drawing', d.id) }" @click="sym.show({ kind: 'drawing', id: d.id, page: 1 })">
							<input type="checkbox" :checked="sym.checked.includes(d.id)" :disabled="d.status !== 'ready'" title="Include in the next analysis" @click.stop="toggle(d.id)" />
							<span class="name" :title="`${d.file_name} · ${sym.libraryName(d.library_id)}`">{{ d.file_name }}</span>
							<span v-if="d.status === 'rendering'" class="count">…</span>
							<span v-else-if="d.status === 'error'" class="count bad" :title="d.error ?? ''">!</span>
							<span v-else class="count" :title="`${sym.libraryName(d.library_id)} · ${d.pages.length} page(s)`">{{ d.pages.length }}p</span>
							<button type="button" class="link small" title="Remove" @click.stop="removeDrawing(d.id, d.file_name)">✕</button>
						</li>
					</ul>
					<button type="button" :disabled="!checkedReady.length || sym.busy || !!sym.activeRun" @click="sym.startRun(checkedReady)">
						Analyse {{ checkedReady.length }} drawing(s)
					</button>
				</section>

				<section>
					<h3>Analyses</h3>
					<ul class="ref-nav">
						<li v-for="r in sym.runs" :key="r.id" :class="{ current: isCurrent('run', r.id) }" @click="sym.show({ kind: 'run', id: r.id })">
							<span class="name">{{ r.started_at ? new Date(r.started_at).toLocaleString() : 'queued' }}</span>
							<span class="count" :class="{ bad: r.status === 'error' }" :title="r.status">
								{{ r.status === 'done' ? `${r.tag_count} tags` : r.status === 'running' ? `${r.done_steps}/${r.total_steps}` : r.status }}
							</span>
						</li>
					</ul>
					<p v-if="!sym.runs.length" class="hint">Tick drawings and press <strong>Analyse</strong>.</p>
				</section>
			</aside>

			<SymPageViewer v-if="sym.view.kind === 'drawing'" :key="sym.view.id" :doc-id="sym.view.id" :page="sym.view.page" />
			<SymTemplateEditor v-else-if="sym.view.kind === 'template' && sym.templateDraft" :key="sym.view.id" />
			<SymRun v-else-if="sym.view.kind === 'run'" :key="sym.view.id" :run-id="sym.view.id" @open-import="emit('open-import', $event)" />
			<SymLibrary v-else-if="sym.view.kind === 'library' && sym.libraryDraft" :key="sym.view.id" />
			<section v-else class="card wizard sym-main sym-empty">
				<h2>Symbol detection</h2>
				<p class="hint">
					Find any symbol on PDF drawings and read the text tag written in or beside it. Symbols and tag rules are kept
					in <strong>libraries</strong>, one per kind of drawing. The <strong>P&amp;ID instruments</strong> library is set
					up as an example: add the sample drawing and press Analyse.
				</p>
				<ol class="steps-help">
					<li><strong>Library:</strong> pick one, or make a <em>New library</em> for your drawings. Its <em>Settings</em>
						say what a tag looks like (a pattern such as <code>FT-1023</code>, or any text) and what text to ignore.</li>
					<li><strong>Templates:</strong> open a drawing, choose <em>New template</em> and drag a box around a symbol. In
						the template, click where each part of its tag is written, set the threshold, and if needed paint a
						custom mask of the parts to compare.</li>
					<li><strong>Analyse</strong> the ticked drawings: symbols are matched with OpenCV, and tags are read from the PDF
						text, or with Windows OCR on scanned sheets.</li>
					<li>Export the <strong>tags list</strong>, or send it to a <strong>List import</strong> (for P&amp;IDs: the
						instrument list) with saved rules.</li>
				</ol>
				<p v-if="sym.error" class="error">{{ sym.error }}</p>
				<p v-else-if="sym.message" class="saved">{{ sym.message }}</p>
			</section>
		</div>
	</div>
</template>
