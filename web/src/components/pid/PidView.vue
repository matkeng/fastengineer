<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import pidSample from '../../../../samples/pid-sample.pdf?url';
import pidScanned from '../../../../samples/pid-sample-scanned.pdf?url';
import pidTemplates from '../../../../samples/pid-templates.json?url';
import { libKey } from '../../lib/pidTypes';
import { usePid } from '../../stores/pid';
import PidPageViewer from './PidPageViewer.vue';
import PidRun from './PidRun.vue';
import PidSettings from './PidSettings.vue';
import PidTemplateEditor from './PidTemplateEditor.vue';

const emit = defineEmits<{ 'open-import': [recipeId: string] }>();
const pid = usePid();
const fileInput = ref<HTMLInputElement | null>(null);
const libInput = ref<HTMLInputElement | null>(null);
const imgInput = ref<HTMLInputElement | null>(null);
const upType = ref('PID');
const upSet = ref('FIR');
const lib = ref('PID/FIR');

const libs = computed(() => {
	const keys = new Set(pid.libraries.map(libKey));
	keys.add(lib.value);
	return [...keys].sort();
});
const libTemplates = computed(() => pid.templates.filter((t) => libKey(t) === lib.value));
const checkedReady = computed(() => pid.checked.filter((id) => pid.drawings.some((d) => d.id === id && d.status === 'ready')));

async function onFiles(files: FileList | null | undefined) {
	for (const f of Array.from(files ?? [])) await pid.upload(f, f.name, upType.value, upSet.value);
	if (fileInput.value) fileInput.value.value = '';
}

async function sample(url: string, name: string) {
	await pid.upload(await (await fetch(url)).blob(), name, upType.value, upSet.value);
}

async function loadLibrary(file: File | Blob | undefined) {
	if (!file) return;
	try {
		await pid.importLibrary(JSON.parse(await file.text()));
	} catch (err) {
		pid.error = `That file is not a template library: ${err instanceof Error ? err.message : err}`;
	}
	if (libInput.value) libInput.value.value = '';
}

async function starterLibrary() {
	await loadLibrary(await (await fetch(pidTemplates)).blob());
	lib.value = 'PID/FIR';
}

async function onTemplateImage(file: File | undefined) {
	if (!file) return;
	const [type, set] = lib.value.split('/');
	await pid.uploadTemplate(file, file.name, type, set);
	if (imgInput.value) imgInput.value.value = '';
}

function toggle(id: string) {
	const i = pid.checked.indexOf(id);
	if (i >= 0) pid.checked.splice(i, 1);
	else pid.checked.push(id);
}

function removeDrawing(id: string, name: string) {
	if (confirm(`Remove ${name} and its analysis results?`)) void pid.removeDrawing(id);
}

function newLibrary() {
	const name = prompt('New library as TYPE/SET, e.g. PID/CLIENT2', 'PID/');
	if (name && /^[^/]+\/[^/]+$/.test(name.trim())) lib.value = name.trim();
}

const isCurrent = (kind: string, id?: string) => {
	const v = pid.view as { kind: string; id?: string };
	return v.kind === kind && (id === undefined || v.id === id);
};

const statusText: Record<string, string> = { queued: 'queued', running: 'running', done: 'done', cancelled: 'cancelled', error: 'error' };

onMounted(() => pid.refresh());
</script>

<template>
	<div class="pid">
		<div class="pid-layout">
			<aside class="card ref-side pid-sidebar">
				<section>
					<h3>Drawings</h3>
					<div class="row tight wrap">
						<button type="button" class="small" @click="fileInput?.click()">Add PDFs…</button>
						<input ref="fileInput" type="file" accept=".pdf,application/pdf" multiple hidden @change="onFiles(($event.target as HTMLInputElement).files)" />
						<input v-model="upType" class="short" title="Drawing type for new uploads" aria-label="Drawing type" />
						<input v-model="upSet" class="short" title="Block set (template library) for new uploads" aria-label="Block set" />
					</div>
					<p class="hint">Samples:
						<button type="button" class="link" @click="sample(pidSample, 'pid-sample.pdf')">P&amp;ID</button> ·
						<button type="button" class="link" @click="sample(pidScanned, 'pid-sample-scanned.pdf')">scanned P&amp;ID</button>
					</p>
					<ul class="ref-nav">
						<li v-for="d in pid.drawings" :key="d.id" :class="{ current: isCurrent('drawing', d.id) }" @click="pid.show({ kind: 'drawing', id: d.id, page: 1 })">
							<input type="checkbox" :checked="pid.checked.includes(d.id)" :disabled="d.status !== 'ready'" title="Include in the next analysis" @click.stop="toggle(d.id)" />
							<span class="name" :title="d.file_name">{{ d.file_name }}</span>
							<span v-if="d.status === 'rendering'" class="count">…</span>
							<span v-else-if="d.status === 'error'" class="count bad" :title="d.error ?? ''">!</span>
							<span v-else class="count" :title="`${libKey(d)} · ${d.pages.length} page(s)`">{{ d.pages.length }}p</span>
							<button type="button" class="link small" title="Remove" @click.stop="removeDrawing(d.id, d.file_name)">✕</button>
						</li>
					</ul>
					<button type="button" :disabled="!checkedReady.length || pid.busy || !!pid.activeRun" @click="pid.startRun(checkedReady)">
						Analyse {{ checkedReady.length }} drawing(s)
					</button>
				</section>

				<section>
					<h3>Templates</h3>
					<div class="row tight">
						<select v-model="lib" aria-label="Template library">
							<option v-for="k in libs" :key="k" :value="k">{{ k }}</option>
						</select>
						<button type="button" class="link small" @click="newLibrary">new…</button>
					</div>
					<p class="hint">Matched in this order; each match is blanked before the next template runs, so put specific symbols first.</p>
					<ol class="ref-nav pid-tlist">
						<li v-for="(t, i) in libTemplates" :key="t.id" :class="{ current: isCurrent('template', t.id), off: !t.active }" @click="pid.openTemplate(t.id)">
							<span class="name">{{ t.desc }}</span>
							<span v-if="t.points.length" class="count" title="Tag points">{{ t.points.length }}</span>
							<button type="button" class="link small" :disabled="i === 0" title="Move up" @click.stop="pid.moveTemplate(t.id, i - 1)">▲</button>
							<button type="button" class="link small" :disabled="i === libTemplates.length - 1" title="Move down" @click.stop="pid.moveTemplate(t.id, i + 1)">▼</button>
						</li>
					</ol>
					<p v-if="!libTemplates.length" class="hint">None yet. Open a drawing and use <strong>New template</strong>, or
						<button type="button" class="link" @click="starterLibrary">load the starter templates</button>.</p>
					<div class="row tight wrap">
						<button type="button" class="secondary small" @click="libInput?.click()">Import…</button>
						<input ref="libInput" type="file" accept=".json" hidden @change="loadLibrary(($event.target as HTMLInputElement).files?.[0])" />
						<button type="button" class="secondary small" :disabled="!libTemplates.length" @click="pid.exportLibrary(lib.split('/')[0], lib.split('/')[1])">Export…</button>
						<button type="button" class="secondary small" title="Add a symbol image file as a template" @click="imgInput?.click()">Image…</button>
						<input ref="imgInput" type="file" accept="image/*" hidden @change="onTemplateImage(($event.target as HTMLInputElement).files?.[0])" />
					</div>
				</section>

				<section>
					<h3>Analyses</h3>
					<ul class="ref-nav">
						<li v-for="r in pid.runs" :key="r.id" :class="{ current: isCurrent('run', r.id) }" @click="pid.show({ kind: 'run', id: r.id })">
							<span class="name">{{ r.started_at ? new Date(r.started_at).toLocaleString() : 'queued' }}</span>
							<span class="count" :class="{ bad: r.status === 'error' }" :title="statusText[r.status]">
								{{ r.status === 'done' ? `${r.tag_count} tags` : r.status === 'running' ? `${r.done_steps}/${r.total_steps}` : statusText[r.status] }}
							</span>
						</li>
					</ul>
					<p v-if="!pid.runs.length" class="hint">Tick drawings and press <strong>Analyse</strong>.</p>
				</section>

				<section>
					<button type="button" class="link" :class="{ strong: isCurrent('settings') }" @click="pid.show({ kind: 'settings' })">Tag pattern, OCR &amp; ignored text…</button>
				</section>
			</aside>

			<PidPageViewer v-if="pid.view.kind === 'drawing'" :key="pid.view.id" :doc-id="pid.view.id" :page="pid.view.page" />
			<PidTemplateEditor v-else-if="pid.view.kind === 'template' && pid.templateDraft" :key="pid.view.id" />
			<PidRun v-else-if="pid.view.kind === 'run'" :key="pid.view.id" :run-id="pid.view.id" @open-import="emit('open-import', $event)" />
			<PidSettings v-else-if="pid.view.kind === 'settings'" />
			<section v-else class="card wizard pid-main pid-empty">
				<h2>P&amp;ID analysis</h2>
				<ol class="steps-help">
					<li><strong>Add PDFs</strong> (or a sample). Pages are rendered once and kept on this computer.</li>
					<li><strong>Templates:</strong> open a drawing, choose <em>New template</em> and drag a box around a symbol
						(an instrument bubble, a control valve). In the template, click where each part of the tag is written.
						Or load the starter templates.</li>
					<li><strong>Analyse</strong> the ticked drawings: symbols are matched with OpenCV, and tags are read from the PDF
						text, or with Windows OCR on scanned sheets. ISA-style tags elsewhere in the text are picked up too.</li>
					<li>Export the <strong>P&amp;ID tags list</strong>, or send it to a <strong>List import</strong> to build the
						instrument list with saved rules.</li>
				</ol>
				<p v-if="pid.error" class="error">{{ pid.error }}</p>
				<p v-else-if="pid.message" class="saved">{{ pid.message }}</p>
			</section>
		</div>
	</div>
</template>
