<script setup lang="ts">
import { ref } from 'vue';
import sampleUrl from '../../../../samples/cable-schedule-sample.xlsx?url';
import { useExcelWizard } from '../../stores/excelWizard';

const wiz = useExcelWizard();
const dragging = ref(false);
const input = ref<HTMLInputElement | null>(null);

function open(file: File | undefined) {
	if (file) void wiz.openFile(file, file.name);
}

function onDrop(e: DragEvent) {
	dragging.value = false;
	open(e.dataTransfer?.files[0]);
}

async function useSample() {
	const blob = await (await fetch(sampleUrl)).blob();
	await wiz.openFile(blob, 'cable-schedule-sample.xlsx');
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
			No workbook to hand?
			<button class="link" type="button" :disabled="wiz.busy" @click="useSample">Use the sample cable schedule</button>
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
