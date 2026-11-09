<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import sampleC from '../../samples/cable-schedule-sample.xlsx?url';
import EnginePanel from './components/EnginePanel.vue';
import CompareView from './components/compare/CompareView.vue';
import ExcelWizard from './components/excel/ExcelWizard.vue';
import { useCompare } from './stores/compare';
import { useExcelWizard } from './stores/excelWizard';
import { useWorkbench } from './stores/workbench';

const wb = useWorkbench();
const wiz = useExcelWizard();
const cmp = useCompare();
const tab = ref<'excel' | 'compare' | 'engine'>('excel');
const SAMPLES = [{ label: 'Use the sample cable schedule', url: sampleC, filename: 'cable-schedule-sample.xlsx' }];

// Results views fill the window; the table takes the free space.
const fill = computed(
	() =>
		wb.status === 'ready' &&
		((tab.value === 'excel' && wiz.step === 4) || (tab.value === 'compare' && cmp.stage === 'result')),
);

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
			<button type="button" :class="{ active: tab === 'engine' }" @click="tab = 'engine'">Engine</button>
		</nav>

		<EnginePanel v-show="tab === 'engine'" />
		<!-- v-show keeps each tab's progress when switching between them -->
		<template v-if="wb.status === 'ready'">
			<ExcelWizard v-show="tab === 'excel'" :wiz="wiz" :samples="SAMPLES" />
			<CompareView v-show="tab === 'compare'" />
		</template>
		<section v-else-if="tab !== 'engine'" class="card">
			<p v-if="wb.status === 'connecting'">Waiting for the Python engine to start…</p>
			<template v-else>
				<p class="error">{{ wb.error }}</p>
				<button type="button" @click="wb.connect()">Retry</button>
			</template>
		</section>
	</main>
</template>
