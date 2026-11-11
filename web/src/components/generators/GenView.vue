<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import HistoryButton from '../audit/HistoryButton.vue';
import { computed, onMounted, ref, watch } from 'vue';
import { apiGet } from '../../lib/engine';
import { KIND_LABELS } from '../../lib/genTypes';
import { useDeliverables } from '../../stores/deliverables';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import { type GenTab, useGenerators } from '../../stores/generators';
import GenBuild from './GenBuild.vue';
import GenBulkImport from './GenBulkImport.vue';
import GenCheck from './GenCheck.vue';
import GenHardware from './GenHardware.vue';
import GenRunsheet from './GenRunsheet.vue';
import GenSettings from './GenSettings.vue';
import GenTemplates from './GenTemplates.vue';

const g = useGenerators();
const kl = useKeyLists();
const dl = useDeliverables();
const ui = useUi();

// The two types of generator, built into the app. (Generators are no longer made from a workbook.)
interface PowerList { type: string; rows: number; deliverables: number }
interface GeneratorType {
	id: 'power' | 'instrument'; name: string; available: boolean; description: string;
	loads: number; load_types: number; missing_load_types: string[]; lists: PowerList[];
}
const types = ref<GeneratorType[]>([]);
const typesError = ref('');
const power = computed(() => types.value.find((t) => t.id === 'power') ?? null);
const instrument = computed(() => types.value.find((t) => t.id === 'instrument') ?? null);
async function loadTypes() {
	try {
		types.value = await apiGet<GeneratorType[]>('/api/generators/types');
		typesError.value = '';
	} catch (err) {
		typesError.value = err instanceof Error ? err.message : String(err);
	}
}
function openList(id: 'load-list' | 'load-types') {
	void kl.select(id);
	ui.go('keylists');
}
async function openDeliverables() {
	await dl.refresh();
	ui.go('deliverables');
}
const bulkInput = ref<HTMLInputElement | null>(null);
const bulkFile = ref<File | null>(null);

function pickBulk(files: FileList | null | undefined) {
	const f = files?.[0];
	if (bulkInput.value) bulkInput.value.value = '';
	if (!f) return;
	if (g.anyDirty && !confirm('Save or discard your unsaved edits first: importing replaces whole tables. Continue anyway (the edits will be lost)?')) return;
	g.discard();
	bulkFile.value = f;
}

const errors = computed(() => g.checkResult?.findings.filter((f) => f.severity === 'ERROR').length ?? 0);
const TABS = computed<{ id: GenTab; label: string; count?: number; tone?: string }[]>(() => [
	{ id: 'runsheet', label: 'Runsheet', count: g.draft?.generator.runsheet.rows.length },
	{ id: 'templates', label: 'Templates', count: new Set(g.draft?.generator.templates.map((t) => t.id)).size },
	{ id: 'check', label: 'Check', count: errors.value || undefined, tone: errors.value ? 'bad' : undefined },
	{ id: 'build', label: 'Build', count: g.builds.length || undefined },
	{ id: 'hardware', label: 'PLC hardware', count: g.hwView?.summary.cards || undefined },
	{ id: 'settings', label: 'Settings' },
]);
const panels: Record<GenTab, unknown> = { runsheet: GenRunsheet, templates: GenTemplates, check: GenCheck, build: GenBuild, hardware: GenHardware, settings: GenSettings };
function leave() {
	if (g.anyDirty && !confirm('Discard unsaved changes to this generator?')) return;
	g.close();
}

function remove(id: string, name: string) {
	if (confirm(`Delete the generator "${name}" and all its builds? This can't be undone.`)) void g.remove(id);
}

function ago(at: string | null) {
	return at ? new Date(at).toLocaleString() : '–';
}

onMounted(() => { void g.refreshList(); void loadTypes(); });
// coming back to the section: the Load List or the load types may have changed
watch(() => ui.tab, (tab) => { if (tab === 'generators' && !g.draft) { void g.refreshList(); void loadTypes(); } });
</script>

<template>
	<div class="gen">
		<!-- The generator types, and any generators kept from earlier versions -->
		<section v-if="!g.draft" class="card">
			<h2>Generators</h2>
			<p class="hint">
				A generator makes a project's lists from its data. There are two types, built into the app. What a generator
				produces is issued in revisions under <strong>Deliverables</strong>.
			</p>
			<p v-if="typesError" class="error">{{ typesError }}</p>
			<div class="gen-types">
				<article v-if="power" class="gen-type">
					<header><strong>{{ power.name }}</strong><span class="chip ok">Available</span></header>
					<p class="hint">{{ power.description }} It is always up to date: there is nothing to import or build.</p>
					<p>
						<strong>{{ power.loads }}</strong> load(s) in the Load List · <strong>{{ power.load_types }}</strong> load type(s)
					</p>
					<p v-if="power.missing_load_types.length" class="warn">
						{{ power.missing_load_types.length }} load(s) have no load type and produce nothing yet:
						{{ power.missing_load_types.slice(0, 8).join(', ') }}{{ power.missing_load_types.length > 8 ? '…' : '' }}
					</p>
					<table class="grid simple gen-type-lists">
						<thead><tr><th>List</th><th>Rows now</th><th>Deliverables</th></tr></thead>
						<tbody>
							<tr v-for="l in power.lists" :key="l.type">
								<td>{{ l.type }}</td><td class="n">{{ l.rows }}</td><td class="n">{{ l.deliverables || '–' }}</td>
							</tr>
						</tbody>
					</table>
					<div class="row">
						<button type="button" @click="openDeliverables">Deliverables</button>
						<button type="button" class="secondary" @click="openList('load-list')">Load List</button>
						<button type="button" class="secondary" @click="openList('load-types')">Load Types</button>
					</div>
				</article>
				<article v-if="instrument" class="gen-type planned">
					<header><strong>{{ instrument.name }}</strong><span class="chip">Planned</span></header>
					<p class="hint">{{ instrument.description }}</p>
				</article>
			</div>

			<template v-if="g.list.length">
				<h3 class="gen-older">Generators from imported workbooks</h3>
				<p class="hint">
					Made in an earlier version, from a generator workbook. Workbooks can no longer be imported, but these keep
					working: open one to edit, check, build and export it, or delete it when it is no longer needed.
				</p>
				<div class="gen-cards">
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
			</template>
			<p v-if="g.error" class="error">{{ g.error }}</p>
		</section>

		<!-- One generator -->
		<section v-else class="card wizard gen-card-open">
			<div class="mel-head">
				<button type="button" class="secondary small" @click="leave">← All generators</button>
				<input v-model="g.draft.name" class="name-input" aria-label="Generator name" />
				<span class="chip">{{ KIND_LABELS[g.draft.kind] ?? g.draft.kind }}</span>
				<button type="button" class="secondary small" :disabled="g.anyDirty || g.busy" :title="g.anyDirty ? 'Save first' : 'Every input table in one workbook, for editing in Excel'" @click="g.exportInputs()">Export inputs</button>
				<button type="button" class="secondary small" :disabled="g.busy" @click="bulkInput?.click()">Import inputs…</button>
				<input ref="bulkInput" type="file" accept=".xlsx" hidden @change="pickBulk(($event.target as HTMLInputElement).files)" />
				<span class="spacer" />
				<span v-if="g.dirty" class="unsaved">● Unsaved changes</span>
				<span v-else-if="g.message" class="saved" :title="g.message">✓ {{ g.message }}</span>
				<HistoryButton v-if="g.draft" entity="generator" :record-id="g.draft.id" :label="g.draft.name" />
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

		<GenBulkImport :file="bulkFile" @close="bulkFile = null" />
	</div>
</template>
