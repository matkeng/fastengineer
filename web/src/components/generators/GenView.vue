<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import sampleUrl from '../../../../samples/generator-sample.xlsx?url';
import { type ImportReport, KIND_LABELS } from '../../lib/genTypes';
import { type GenTab, useGenerators } from '../../stores/generators';
import AppModal from '../common/AppModal.vue';
import GenBuild from './GenBuild.vue';
import GenCheck from './GenCheck.vue';
import GenRunsheet from './GenRunsheet.vue';
import GenSettings from './GenSettings.vue';
import GenTemplates from './GenTemplates.vue';

const g = useGenerators();
const fileInput = ref<HTMLInputElement | null>(null);
const over = ref(false);
const reportOpen = ref(false);

const errors = computed(() => g.checkResult?.findings.filter((f) => f.severity === 'ERROR').length ?? 0);
const TABS = computed<{ id: GenTab; label: string; count?: number; tone?: string }[]>(() => [
	{ id: 'runsheet', label: 'Runsheet', count: g.draft?.generator.runsheet.rows.length },
	{ id: 'templates', label: 'Templates', count: new Set(g.draft?.generator.templates.map((t) => t.id)).size },
	{ id: 'check', label: 'Check', count: errors.value || undefined, tone: errors.value ? 'bad' : undefined },
	{ id: 'build', label: 'Build', count: g.builds.length || undefined },
	{ id: 'settings', label: 'Settings' },
]);
const panels: Record<GenTab, unknown> = { runsheet: GenRunsheet, templates: GenTemplates, check: GenCheck, build: GenBuild, settings: GenSettings };
const report = computed<ImportReport | null>(() => g.draft?.import_report ?? null);

async function pick(files: FileList | null | undefined) {
	const f = files?.[0];
	if (!f) return;
	if (!/\.(xlsx|xlsm)$/i.test(f.name)) {
		g.error = 'Choose an Excel workbook (.xlsx or .xlsm).';
		return;
	}
	await g.importWorkbook(f);
	if (g.draft) reportOpen.value = true;
	if (fileInput.value) fileInput.value.value = '';
}

async function useSample() {
	const blob = await (await fetch(sampleUrl)).blob();
	await g.importWorkbook(new File([blob], 'generator-sample.xlsx'));
	if (g.draft) reportOpen.value = true;
}

function onDrop(e: DragEvent) {
	over.value = false;
	void pick(e.dataTransfer?.files);
}

function leave() {
	if (g.dirty && !confirm('Discard unsaved changes to this generator?')) return;
	g.close();
}

function remove(id: string, name: string) {
	if (confirm(`Delete the generator "${name}" and all its builds? This can't be undone.`)) void g.remove(id);
}

function ago(at: string | null) {
	return at ? new Date(at).toLocaleString() : '–';
}

onMounted(() => g.refreshList());
</script>

<template>
	<div class="gen">
		<!-- All generators -->
		<section
			v-if="!g.draft"
			class="card"
			:class="{ dropping: over }"
			@dragover.prevent="over = true"
			@dragleave="over = false"
			@drop.prevent="onDrop"
		>
			<h2>Generators</h2>
			<p class="hint">
				A generator turns a runsheet (one row per run) into a schedule by copying the template block each run picks
				and filling in its <code>&lt;&lt;TAGS&gt;&gt;</code>. Import a generator workbook to start; every build is kept so you
				can see what changed.
			</p>
			<div v-if="g.list.length" class="gen-cards">
				<article v-for="x in g.list" :key="x.id" class="gen-card" @click="g.open(x.id)">
					<header>
						<strong>{{ x.name }}</strong>
						<button type="button" class="secondary small" @click.stop="remove(x.id, x.name)">Delete</button>
					</header>
					<div class="hint">{{ KIND_LABELS[x.kind] ?? x.kind }} · {{ x.runs }} runs · {{ x.templates }} templates</div>
					<div v-if="x.last_build" class="last">
						Build {{ x.last_build.seq }}: {{ x.last_build.stats.rows_written }} rows
						<span v-if="x.last_build.stats.no_template" class="warn"> · {{ x.last_build.stats.no_template }} without a template</span>
						<span v-if="x.last_build.added !== null"> · +{{ x.last_build.added }} −{{ x.last_build.removed }} ~{{ x.last_build.changed }}</span>
						<div class="hint">{{ ago(x.last_build.created_at) }}</div>
					</div>
					<div v-else class="last hint">Not built yet · {{ x.source_file }}</div>
				</article>
			</div>
			<p v-else class="hint">No generators yet.</p>
			<div class="row create">
				<input ref="fileInput" type="file" accept=".xlsx,.xlsm" hidden @change="pick(($event.target as HTMLInputElement).files)" />
				<button type="button" :disabled="g.busy" @click="fileInput?.click()">Import workbook…</button>
				<button type="button" class="secondary" :disabled="g.busy" @click="useSample">Use the sample generator</button>
				<span class="hint">or drop an .xlsx / .xlsm here</span>
				<span v-if="g.busy" class="hint">Importing…</span>
			</div>
			<p v-if="g.error" class="error">{{ g.error }}</p>
		</section>

		<!-- One generator -->
		<section v-else class="card wizard gen-card-open">
			<div class="mel-head">
				<button type="button" class="secondary small" @click="leave">← All generators</button>
				<input v-model="g.draft.name" class="name-input" aria-label="Generator name" />
				<span class="chip">{{ KIND_LABELS[g.draft.kind] ?? g.draft.kind }}</span>
				<button v-if="report" type="button" class="secondary small" @click="reportOpen = true">Import report</button>
				<span class="spacer" />
				<span v-if="g.dirty" class="unsaved">● Unsaved changes</span>
				<span v-else-if="g.message" class="saved" :title="g.message">✓ {{ g.message }}</span>
				<button type="button" class="secondary" :disabled="!g.dirty || g.busy" @click="g.discard()">Discard</button>
				<button type="button" :disabled="!g.dirty || g.busy" @click="g.save()">Save</button>
			</div>
			<nav class="subtabs">
				<button v-for="t in TABS" :key="t.id" type="button" :class="{ active: g.tab === t.id }" @click="g.tab = t.id">
					{{ t.label }}<span v-if="t.count" class="count" :class="t.tone">{{ t.count }}</span>
				</button>
			</nav>
			<p v-if="g.error" class="error">{{ g.error }}</p>
			<div class="step-body">
				<component :is="panels[g.tab]" :key="`${g.draft.id}-${g.tab}`" />
			</div>
		</section>

		<AppModal :open="reportOpen && !!report" :title="`Import report: ${report?.workbook ?? ''}`" @close="reportOpen = false">
			<template v-if="report">
				<p>
					<strong>{{ report.runsheet_rows }}</strong> runsheet rows · <strong>{{ report.tags }}</strong> tags ·
					<strong>{{ report.templates }}</strong> templates ({{ report.template_rows }} rows) ·
					<strong>{{ report.parents }}</strong> parents
				</p>
				<h4>Formulas turned into calculated columns</h4>
				<ul v-if="Object.keys(report.mapped_formulas).length">
					<li v-for="(n, k) in report.mapped_formulas" :key="k">{{ n }} × {{ k }}</li>
				</ul>
				<p v-else class="hint">None.</p>
				<template v-if="report.unmapped_formulas.length">
					<h4 class="warn">Formulas kept as text (not understood)</h4>
					<ul><li v-for="u in report.unmapped_formulas" :key="u.formula + u.where">{{ u.count }} × <code>{{ u.formula }}</code> in {{ u.where }}</li></ul>
				</template>
				<template v-if="Object.keys(report.runsheet_formula_columns).length">
					<h4>Runsheet columns calculated in the workbook (values imported)</h4>
					<ul><li v-for="(f, t) in report.runsheet_formula_columns" :key="t">{{ t }}: <code>{{ f }}</code></li></ul>
				</template>
				<h4>Data issues found</h4>
				<ul v-if="report.issues.length"><li v-for="i in report.issues" :key="i">{{ i }}</li></ul>
				<p v-else class="hint">None.</p>
			</template>
			<template #footer>
				<span class="spacer" />
				<button type="button" @click="reportOpen = false">Close</button>
			</template>
		</AppModal>
	</div>
</template>
