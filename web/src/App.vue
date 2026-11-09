<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import sampleC from '../../samples/cable-schedule-sample.xlsx?url';
import EnginePanel from './components/EnginePanel.vue';
import CompareView from './components/compare/CompareView.vue';
import ExcelWizard from './components/excel/ExcelWizard.vue';
import MelView from './components/mel/MelView.vue';
import PidView from './components/pid/PidView.vue';
import RefView from './components/ref/RefView.vue';
import { useCompare } from './stores/compare';
import { useExcelWizard } from './stores/excelWizard';
import { useMel } from './stores/mel';
import { usePid } from './stores/pid';
import { useRefData } from './stores/refdata';
import { useWorkbench } from './stores/workbench';

const wb = useWorkbench();
const wiz = useExcelWizard();
const cmp = useCompare();
const mel = useMel();
const rd = useRefData();
const pid = usePid();
const tab = ref<'excel' | 'compare' | 'pid' | 'mel' | 'ref' | 'engine'>('excel');
const SAMPLES = [{ label: 'Use the sample cable schedule', url: sampleC, filename: 'cable-schedule-sample.xlsx' }];

// Results views fill the window; the table takes the free space.
const fill = computed(
	() =>
		wb.status === 'ready' &&
		((tab.value === 'excel' && wiz.step === 4) ||
			(tab.value === 'compare' && cmp.stage === 'result') ||
			(tab.value === 'mel' && !!mel.draft && ['rows', 'overrides', 'result'].includes(mel.tab)) ||
			tab.value === 'pid' ||
			tab.value === 'ref'),
);

/** From a P&ID analysis: show the instrument-list import it was sent to. */
async function openImport(recipeId: string) {
	if (mel.dirty && !confirm('Discard unsaved changes to the open list import?')) return;
	await mel.open(recipeId);
	mel.tab = 'overview';
	tab.value = 'mel';
}

onMounted(() => wb.connect());
</script>

<template>
	<main :class="{ fill }">
		<header class="top">
			<div>
				<h1>Drawing Workbench</h1>
				<p class="sub">Proof of concept · Tauri 2 shell · Vue 3 + Pinia · Python engine sidecar</p>
			</div>
			<span class="pill" :class="wb.status" :title="wb.error ?? ''">
				<span class="dot" />
				{{ wb.status === 'ready' ? 'Engine ready' : wb.status === 'connecting' ? 'Starting engine…' : 'Engine error' }}
			</span>
		</header>

		<nav class="tabs">
			<button type="button" :class="{ active: tab === 'excel' }" @click="tab = 'excel'">Excel query</button>
			<button type="button" :class="{ active: tab === 'compare' }" @click="tab = 'compare'">Compare tables</button>
			<button type="button" :class="{ active: tab === 'pid' }" @click="tab = 'pid'">
				P&amp;ID analysis<span v-if="pid.dirty" class="dirty-dot" title="Unsaved changes">●</span>
			</button>
			<button type="button" :class="{ active: tab === 'mel' }" @click="tab = 'mel'">
				List import<span v-if="mel.dirty" class="dirty-dot" title="Unsaved changes">●</span>
			</button>
			<button type="button" :class="{ active: tab === 'ref' }" @click="tab = 'ref'">
				Lists &amp; tables<span v-if="rd.dirty" class="dirty-dot" title="Unsaved changes">●</span>
			</button>
			<button type="button" :class="{ active: tab === 'engine' }" @click="tab = 'engine'">Engine</button>
		</nav>

		<EnginePanel v-show="tab === 'engine'" />
		<!-- v-show keeps each tab's progress when switching between them -->
		<template v-if="wb.status === 'ready'">
			<ExcelWizard v-show="tab === 'excel'" :wiz="wiz" :samples="SAMPLES" />
			<CompareView v-show="tab === 'compare'" />
			<PidView v-show="tab === 'pid'" @open-import="openImport" />
			<MelView v-show="tab === 'mel'" />
			<RefView v-show="tab === 'ref'" />
		</template>
		<section v-else-if="tab !== 'engine'" class="card">
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
</template>
