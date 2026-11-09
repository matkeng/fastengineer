<script setup lang="ts">
import { onMounted, ref } from 'vue';
import EnginePanel from './components/EnginePanel.vue';
import ExcelWizard from './components/excel/ExcelWizard.vue';
import { useWorkbench } from './stores/workbench';

const wb = useWorkbench();
const tab = ref<'excel' | 'engine'>('excel');

onMounted(() => wb.connect());
</script>

<template>
	<main>
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
			<button type="button" :class="{ active: tab === 'engine' }" @click="tab = 'engine'">Engine</button>
		</nav>

		<template v-if="tab === 'excel'">
			<ExcelWizard v-if="wb.status === 'ready'" />
			<section v-else class="card">
				<p v-if="wb.status === 'connecting'">Waiting for the Python engine to start…</p>
				<template v-else>
					<p class="error">{{ wb.error }}</p>
					<button type="button" @click="wb.connect()">Retry</button>
				</template>
			</section>
		</template>
		<EnginePanel v-else />
	</main>
</template>
