<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, provide } from 'vue';
import { type SampleFile, WIZARD_CONTEXT } from '../../lib/wizardContext';
import { STEPS, type TableWizard } from '../../stores/excelWizard';
import StepHeader from './StepHeader.vue';
import StepKey from './StepKey.vue';
import StepPicked from './StepPicked.vue';
import StepResults from './StepResults.vue';
import StepSource from './StepSource.vue';
import StepWorkbook from './StepWorkbook.vue';

const props = withDefaults(
	defineProps<{
		wiz: TableWizard;
		/** query: last step shows the full table. pick: last step is a short summary (compare). */
		mode?: 'query' | 'pick';
		samples?: SampleFile[];
		reuseFrom?: TableWizard;
		title?: string;
	}>(),
	{ mode: 'query', samples: () => [], reuseFrom: undefined, title: undefined },
);
const emit = defineEmits<{ done: [] }>();

provide(WIZARD_CONTEXT, { wiz: props.wiz, samples: props.samples, reuseFrom: props.reuseFrom });

const labels = computed(() => (props.mode === 'pick' ? [...STEPS.slice(0, 4), 'Table ready'] : [...STEPS]));
const panels = computed(() => [
	StepWorkbook, StepSource, StepHeader, StepKey, props.mode === 'pick' ? StepPicked : StepResults,
]);
const last = computed(() => labels.value.length - 1);

async function next() {
	await props.wiz.next();
	if (props.wiz.step === last.value) emit('done');
}
</script>

<template>
	<section class="card wizard">
		<p v-if="title" class="wizard-title">{{ title }}</p>
		<ol class="stepper">
			<li
				v-for="(label, i) in labels"
				:key="label"
				:class="{ done: i < wiz.step, current: i === wiz.step }"
				@click="wiz.goTo(i)"
			>
				<span class="num">{{ i < wiz.step ? '✓' : i + 1 }}</span>
				<span class="label">{{ label }}</span>
			</li>
		</ol>

		<h2>{{ labels[wiz.step] }}</h2>
		<div class="step-body">
			<component :is="panels[wiz.step]" />
		</div>

		<p v-if="wiz.error" class="error">{{ wiz.error }}</p>

		<div class="nav">
			<button v-if="wiz.step > 0" type="button" class="secondary" :disabled="wiz.busy" @click="wiz.back()">Back</button>
			<span class="spacer" />
			<span v-if="wiz.busy" class="busy">Working…</span>
			<template v-if="wiz.step === last">
				<slot name="last-actions">
					<button type="button" class="secondary" @click="wiz.reset()">Start over</button>
				</slot>
			</template>
			<button v-else type="button" :disabled="!wiz.canAdvance || wiz.busy" @click="next">
				{{ wiz.step === last - 1 ? (mode === 'pick' ? 'Use this table' : 'Build table') : 'Next' }}
			</button>
		</div>
	</section>
</template>
