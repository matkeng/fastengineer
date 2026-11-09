<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { ref } from 'vue';
import { type SampleFile, useWizardContext } from '../../lib/wizardContext';

const { wiz, samples, reuseFrom } = useWizardContext();
const dragging = ref(false);
const input = ref<HTMLInputElement | null>(null);

function open(file: File | undefined) {
	if (file) void wiz.openFile(file, file.name);
}

function onDrop(e: DragEvent) {
	dragging.value = false;
	open(e.dataTransfer?.files[0]);
}

async function useSample(s: SampleFile) {
	const blob = await (await fetch(s.url)).blob();
	await wiz.openFile(blob, s.filename);
}

function reuse() {
	const f = reuseFrom?.file;
	if (f) void wiz.openFile(f.blob, f.name);
}
</script>

<template>
	<div>
		<p class="hint">Choose an Excel workbook (.xlsx or .xlsm). It is read locally by the engine and never uploaded anywhere.</p>
		<div
			class="drop"
			:class="{ dragging }"
			role="button"
			tabindex="0"
			@click="input?.click()"
			@keydown.enter.space.prevent="input?.click()"
			@dragover.prevent="dragging = true"
			@dragleave="dragging = false"
			@drop.prevent="onDrop"
		>
			<strong>Drop a workbook here</strong>
			<span>or click to browse</span>
			<input
				ref="input"
				type="file"
				accept=".xlsx,.xlsm,.xltx,.xltm"
				hidden
				@change="open(($event.target as HTMLInputElement).files?.[0])"
			/>
		</div>
		<p class="sample">
			<template v-if="reuseFrom?.file">
				<button class="link" type="button" :disabled="wiz.busy" @click="reuse">
					Use the same workbook as the old table ({{ reuseFrom.file.name }})
				</button>
				·
			</template>
			<template v-if="samples.length">
				No workbook to hand?
				<template v-for="(s, i) in samples" :key="s.url">
					<template v-if="i"> or </template>
					<button class="link" type="button" :disabled="wiz.busy" @click="useSample(s)">{{ s.label }}</button>
				</template>
			</template>
		</p>

		<div v-if="wiz.workbook" class="loaded">
			<p>
				<strong>{{ wiz.workbook.filename }}</strong> loaded:
				{{ wiz.workbook.sources.filter((s) => s.kind === 'sheet').length }} sheet(s),
				{{ wiz.workbook.sources.filter((s) => s.kind === 'table').length }} Excel table(s).
			</p>
			<p v-for="w in wiz.workbook.warnings" :key="w" class="warn">{{ w }}</p>
		</div>
	</div>
</template>
