<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import sampleC from '../../samples/cable-schedule-sample.xlsx?url';
import EnginePanel from './components/EnginePanel.vue';
import Icon from './components/common/Icon.vue';
import CompareView from './components/compare/CompareView.vue';
import DashboardView from './components/dashboard/DashboardView.vue';
import ExcelWizard from './components/excel/ExcelWizard.vue';
import GenView from './components/generators/GenView.vue';
import MelView from './components/mel/MelView.vue';
import RefView from './components/ref/RefView.vue';
import SymView from './components/symbols/SymView.vue';
import { apiGet } from './lib/engine';
import { useCompare } from './stores/compare';
import { useExcelWizard } from './stores/excelWizard';
import { useGenerators } from './stores/generators';
import { useMel } from './stores/mel';
import { useRefData } from './stores/refdata';
import { useSymbols } from './stores/symbols';
import { SECTIONS, useUi } from './stores/ui';
import { useWorkbench } from './stores/workbench';

const wb = useWorkbench();
const ui = useUi();
const wiz = useExcelWizard();
const cmp = useCompare();
const mel = useMel();
const rd = useRefData();
const sym = useSymbols();
const gens = useGenerators();
const SAMPLES = [{ label: 'Use the sample cable schedule', url: sampleC, filename: 'cable-schedule-sample.xlsx' }];

// Results views fill the window; the table takes the free space.
const fill = computed(
	() =>
		wb.status === 'ready' &&
		((ui.tab === 'excel' && wiz.step === 4) ||
			(ui.tab === 'compare' && cmp.stage === 'result') ||
			(ui.tab === 'mel' && !!mel.draft && ['rows', 'overrides', 'result'].includes(mel.tab)) ||
			ui.tab === 'symbols' ||
			(ui.tab === 'generators' && !!gens.draft) ||
			ui.tab === 'ref'),
);
const dirty: Partial<Record<string, () => boolean>> = {
	symbols: () => sym.dirty,
	mel: () => mel.dirty,
	ref: () => rd.dirty,
	generators: () => gens.dirty,
};
const sectionLabel = computed(() => SECTIONS.find((s) => s.id === ui.tab)?.label ?? '');

// Status bar
const port = computed(() => (wb.baseUrl ? new URL(wb.baseUrl).port : ''));
const dataPath = ref('');
const ocr = ref<{ available: boolean; engine: string | null } | null>(null);
watch(
	() => wb.status,
	async (s) => {
		if (s !== 'ready') return;
		try {
			dataPath.value = (await apiGet<{ path: string }>('/api/mel/storage')).path.replace(/[\\/][^\\/]+$/, '');
			ocr.value = await apiGet('/api/symbols/ocr');
		} catch {
			/* shown as unknown */
		}
	},
	{ immediate: true },
);

/** From symbol detection: show the list import its tags were sent to. */
async function openImport(recipeId: string) {
	if (mel.dirty && !confirm('Discard unsaved changes to the open list import?')) return;
	await mel.open(recipeId);
	mel.tab = 'overview';
	ui.go('mel');
}

onMounted(() => wb.connect());
</script>

<template>
	<div class="app">
		<header class="titlebar">
			<Icon name="logo" class="logo" />
			<h1>Drawing Workbench</h1>
			<span class="section">{{ sectionLabel }}</span>
			<span class="spacer" />
			<span class="pill" :class="wb.status" :title="wb.error ?? ''">
				<span class="dot" />
				{{ wb.status === 'ready' ? 'Engine ready' : wb.status === 'connecting' ? 'Starting engine…' : 'Engine error' }}
			</span>
			<span v-if="wb.info" class="version">v{{ wb.info.core_version }}</span>
		</header>

		<nav class="menubar" aria-label="Sections">
			<button v-for="s in SECTIONS" :key="s.id" type="button" :class="{ active: ui.tab === s.id }" @click="ui.go(s.id)">
				<Icon :name="s.icon" />{{ s.label }}<span v-if="dirty[s.id]?.()" class="dirty-dot" title="Unsaved changes">●</span>
			</button>
		</nav>

		<main :class="{ fill }">
			<EnginePanel v-show="ui.tab === 'engine'" />
			<!-- v-show keeps each section's progress when switching between them -->
			<template v-if="wb.status === 'ready'">
				<DashboardView v-if="ui.tab === 'dashboard'" />
				<ExcelWizard v-show="ui.tab === 'excel'" :wiz="wiz" :samples="SAMPLES" />
				<CompareView v-show="ui.tab === 'compare'" />
				<SymView v-show="ui.tab === 'symbols'" @open-import="openImport" />
				<MelView v-show="ui.tab === 'mel'" />
				<RefView v-show="ui.tab === 'ref'" />
				<GenView v-show="ui.tab === 'generators'" />
			</template>
			<section v-else-if="ui.tab !== 'engine'" class="card">
				<template v-if="wb.status === 'connecting'">
					<p>Waiting for the Python engine to start…</p>
					<p v-if="wb.slowStart" class="hint">
						The first start after installing or updating can take up to a minute while the engine unpacks and
						Windows checks it. Later starts are quicker.
					</p>
				</template>
				<template v-else>
					<p class="error">{{ wb.error }}</p>
					<button type="button" @click="wb.connect()">Retry</button>
				</template>
			</section>
		</main>

		<footer class="statusbar">
			<span><span class="dot" :style="{ display: 'inline-block', background: wb.status === 'ready' ? 'var(--ok)' : wb.status === 'error' ? 'var(--danger)' : 'var(--warn)' }" />
				engine {{ wb.status }}<template v-if="port"> · <span class="mono">127.0.0.1:{{ port }}</span></template></span>
			<span v-if="wb.info">{{ wb.info.compiled ? 'compiled' : 'Python ' + wb.info.python.split(' ')[0] }}</span>
			<span v-if="ocr">OCR: {{ ocr.available ? ocr.engine : 'not available' }}</span>
			<span v-if="dataPath" :title="dataPath">data: <span class="mono">{{ dataPath }}</span></span>
			<span class="spacer" />
			<span>AGPL-3.0-only · <a href="#" @click.prevent="ui.go('engine')">About</a></span>
		</footer>
	</div>
</template>
