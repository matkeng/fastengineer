<script setup lang="ts">
import { STEPS, useExcelWizard } from '../../stores/excelWizard';
import StepHeader from './StepHeader.vue';
import StepKey from './StepKey.vue';
import StepResults from './StepResults.vue';
import StepSource from './StepSource.vue';
import StepWorkbook from './StepWorkbook.vue';

const wiz = useExcelWizard();
const panels = [StepWorkbook, StepSource, StepHeader, StepKey, StepResults];
</script>

<template>
	<section class="card wizard">
		<ol class="stepper">
			<li
				v-for="(label, i) in STEPS"
				:key="label"
				:class="{ done: i < wiz.step, current: i === wiz.step }"
				@click="wiz.goTo(i)"
			>
				<span class="num">{{ i < wiz.step ? '✓' : i + 1 }}</span>
				<span class="label">{{ label }}</span>
			</li>
		</ol>

		<h2>{{ STEPS[wiz.step] }}</h2>
		<component :is="panels[wiz.step]" />

		<p v-if="wiz.error" class="error">{{ wiz.error }}</p>

		<div class="nav">
			<button v-if="wiz.step > 0" type="button" class="secondary" :disabled="wiz.busy" @click="wiz.back()">Back</button>
			<span class="spacer" />
			<span v-if="wiz.busy" class="busy">Working…</span>
			<button v-if="wiz.step === STEPS.length - 1" type="button" class="secondary" @click="wiz.reset()">Start over</button>
			<button v-else type="button" :disabled="!wiz.canAdvance || wiz.busy" @click="wiz.next()">
				{{ wiz.step === STEPS.length - 2 ? 'Build table' : 'Next' }}
			</button>
		</div>
	</section>
</template>
