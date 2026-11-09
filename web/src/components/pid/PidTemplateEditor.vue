<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { apiGetBlob } from '../../lib/engine';
import type { TagPoint } from '../../lib/pidTypes';
import { usePid } from '../../stores/pid';

const pid = usePid();
const t = computed(() => pid.templateDraft!);
const fe = computed(() => pid.fieldErrors);

const canvas = ref<HTMLCanvasElement | null>(null);
const image = ref<ImageBitmap | null>(null);
const mask = ref<ImageBitmap | null>(null);
const showMask = ref(false);
const selected = ref<number | null>(null);
const zoom = ref(4);
const scalesText = ref('');

const testDoc = ref<string>('');
const testPage = ref(1);
const readyDrawings = computed(() => pid.drawings.filter((d) => d.status === 'ready'));
const testDrawing = computed(() => readyDrawings.value.find((d) => d.id === testDoc.value) ?? null);

const DEFAULT_NAMES = ['Function', 'Number', 'Suffix'];

async function loadImages() {
	const id = t.value.id;
	image.value = await createImageBitmap(await apiGetBlob(`/api/pid/templates/${id}/image.png`));
	await loadMask();
	const box = canvas.value?.parentElement;
	const fitZoom = box ? Math.min((box.clientWidth - 40) / image.value.width, 360 / image.value.height) : 4;
	zoom.value = Math.max(1, Math.min(8, Math.floor(fitZoom)));
	draw();
}

async function loadMask() {
	mask.value = await createImageBitmap(
		await apiGetBlob(`/api/pid/templates/${t.value.id}/mask.png?buffer_space=${t.value.buffer_space}`),
	);
	draw();
}

const PAD = 20;
function draw() {
	const c = canvas.value;
	const im = image.value;
	if (!c || !im) return;
	const z = zoom.value;
	const dpr = window.devicePixelRatio || 1;
	const w = im.width * z + PAD * 2;
	const h = im.height * z + PAD * 2;
	c.style.width = `${w}px`;
	c.style.height = `${h}px`;
	c.width = Math.round(w * dpr);
	c.height = Math.round(h * dpr);
	const ctx = c.getContext('2d')!;
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.fillStyle = '#f1f5f9';
	ctx.fillRect(0, 0, w, h);
	ctx.imageSmoothingEnabled = false;
	ctx.drawImage(im, PAD, PAD, im.width * z, im.height * z);
	if (showMask.value && mask.value) {
		ctx.globalAlpha = 0.35;
		ctx.drawImage(mask.value, PAD, PAD, im.width * z, im.height * z);
		ctx.globalAlpha = 1;
	}
	ctx.strokeStyle = '#94a3b8';
	ctx.strokeRect(PAD - 0.5, PAD - 0.5, im.width * z + 1, im.height * z + 1);
	ctx.font = '12px system-ui, sans-serif';
	t.value.points.forEach((p, i) => {
		const x = PAD + p.x * z;
		const y = PAD + p.y * z;
		ctx.strokeStyle = i === selected.value ? '#e11d48' : '#dc2626';
		ctx.lineWidth = i === selected.value ? 3 : 2;
		ctx.beginPath();
		ctx.moveTo(x - 8, y); ctx.lineTo(x + 8, y);
		ctx.moveTo(x, y - 8); ctx.lineTo(x, y + 8);
		ctx.stroke();
		ctx.beginPath();
		ctx.arc(x, y, 4, 0, Math.PI * 2);
		ctx.stroke();
		const tw = ctx.measureText(p.name).width + 6;
		ctx.fillStyle = 'rgba(220, 38, 38, 0.9)';
		ctx.fillRect(x + 8, y - 18, tw, 15);
		ctx.fillStyle = '#fff';
		ctx.fillText(p.name, x + 11, y - 7);
	});
}

let dragging: number | null = null;
function at(e: PointerEvent): [number, number] {
	const r = canvas.value!.getBoundingClientRect();
	const z = zoom.value;
	const im = image.value!;
	const x = Math.min(Math.max((e.clientX - r.left - PAD) / z, 0), im.width);
	const y = Math.min(Math.max((e.clientY - r.top - PAD) / z, 0), im.height);
	return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

function onDown(e: PointerEvent) {
	if (!image.value) return;
	canvas.value!.setPointerCapture(e.pointerId);
	const [x, y] = at(e);
	const near = t.value.points.findIndex((p) => Math.hypot((p.x - x) * zoom.value, (p.y - y) * zoom.value) < 10);
	if (near >= 0) {
		selected.value = near;
		dragging = near;
	} else {
		const used = new Set(t.value.points.map((p) => p.name));
		const name = DEFAULT_NAMES.find((n) => !used.has(n)) ?? `Part ${t.value.points.length + 1}`;
		t.value.points.push({ name, x, y, min_overlap: 0.5 });
		selected.value = t.value.points.length - 1;
		dragging = selected.value;
		if (!t.value.tag_format && t.value.points.length === 2) {
			t.value.tag_format = `{${t.value.points[0].name}}-{${t.value.points[1].name}}`;
		}
	}
	draw();
}

function onMove(e: PointerEvent) {
	if (dragging === null) return;
	const [x, y] = at(e);
	const p = t.value.points[dragging];
	p.x = x;
	p.y = y;
	draw();
}

function onUp() {
	dragging = null;
}

function removePoint(i: number) {
	t.value.points.splice(i, 1);
	selected.value = null;
	draw();
}

function setScales(text: string) {
	scalesText.value = text;
	const vals = text.split(/[,\s]+/).filter(Boolean).map(Number);
	t.value.scales = vals.length && vals.every((v) => Number.isFinite(v)) ? vals : [1];
}

const preview = computed(() => {
	const parts: Record<string, string> = Object.fromEntries(t.value.points.map((p, i) => [p.name, ['FT', '1023', 'A'][i] ?? 'X']));
	if (!t.value.tag_format.trim()) return Object.values(parts).join('-');
	return t.value.tag_format.replace(/\{([^}]+)\}/g, (_, k: string) => parts[k] ?? '');
});

function remove() {
	if (confirm(`Delete the template "${t.value.desc}"?`)) void pid.deleteTemplate(t.value.id);
}

function runTest() {
	if (testDoc.value) void pid.testTemplate(testDoc.value, testPage.value);
}

watch(() => t.value?.id, () => { selected.value = null; scalesText.value = t.value.scales.join(', '); void loadImages(); });
watch(() => t.value?.buffer_space, () => { if (t.value.buffer_space >= 1) void loadMask(); });
watch([zoom, showMask, () => t.value.points], draw, { deep: true });
watch(testDoc, () => { testPage.value = 1; });

onMounted(() => {
	scalesText.value = t.value.scales.join(', ');
	const last = pid.lastPage;
	const d = readyDrawings.value.find((x) => x.id === last?.id) ?? readyDrawings.value.find((x) => x.drawing_type === t.value.drawing_type && x.block_set === t.value.block_set) ?? readyDrawings.value[0];
	if (d) {
		testDoc.value = d.id;
		testPage.value = last?.id === d.id ? last.page : 1;
	}
	void loadImages();
});
onBeforeUnmount(() => { image.value?.close(); mask.value?.close(); });
</script>

<template>
	<section class="card pid-main pid-template">
		<div class="mel-head">
			<input v-model="t.desc" class="name-input" aria-label="Template name" :class="{ invalid: fe.desc }" />
			<span class="chip">{{ t.drawing_type }}/{{ t.block_set }} · priority {{ t.priority + 1 }}</span>
			<span class="chip">{{ t.width }} × {{ t.height }} px</span>
			<span class="spacer" />
			<span v-if="pid.templateDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="pid.message" class="saved">✓ {{ pid.message }}</span>
			<button type="button" class="secondary" :disabled="!pid.templateDirty || pid.busy" @click="pid.discardTemplate()">Discard</button>
			<button type="button" :disabled="!pid.templateDirty || pid.busy" @click="pid.saveTemplate()">Save</button>
		</div>
		<p v-if="pid.error" class="error">{{ pid.error }}</p>

		<div class="pid-template-body">
			<div class="pid-template-image">
				<div class="row tight">
					<span class="hint small">Click on the symbol where each part of the tag is written; drag a point to move it.</span>
					<span class="spacer" />
					<label class="check small"><input v-model="showMask" type="checkbox" /> Show search mask</label>
					<label class="small">Zoom <input v-model.number="zoom" type="range" min="1" max="10" /></label>
				</div>
				<div class="pid-template-canvas">
					<canvas ref="canvas" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" />
				</div>
				<table class="grid simple points-table">
					<thead><tr><th>Tag point</th><th>x</th><th>y</th><th title="How much of the word must lie inside the symbol (0-1)">Min overlap</th><th /></tr></thead>
					<tbody>
						<tr v-for="(p, i) in t.points" :key="i" :class="{ current: selected === i }" @click="selected = i; draw()">
							<td><input v-model="p.name" aria-label="Point name" /></td>
							<td><input v-model.number="p.x" type="number" step="0.5" class="num" aria-label="x" /></td>
							<td><input v-model.number="p.y" type="number" step="0.5" class="num" aria-label="y" /></td>
							<td><input v-model.number="(p as TagPoint).min_overlap" type="number" min="0" max="1" step="0.05" class="num" aria-label="Minimum overlap" /></td>
							<td><button type="button" class="secondary small" @click.stop="removePoint(i)">Remove</button></td>
						</tr>
						<tr v-if="!t.points.length"><td colspan="5" class="hint">No tag points: matches of this template are counted but give no tag (fine for valves and other untagged symbols).</td></tr>
					</tbody>
				</table>
				<p v-if="fe.points" class="warn small">{{ fe.points }}</p>
			</div>

			<div class="pid-template-form">
				<label class="field">Tag format
					<input v-model="t.tag_format" placeholder="{Function}-{Number}" :class="{ invalid: fe.tag_format }" />
					<span class="hint small">Example: <code>{{ preview || '—' }}</code>. Leave blank to join the parts with “-”.</span>
					<span v-if="fe.tag_format" class="warn small">{{ fe.tag_format }}</span>
				</label>
				<label class="field">Match threshold <strong>{{ t.threshold.toFixed(2) }}</strong>
					<input v-model.number="t.threshold" type="range" min="0.4" max="1" step="0.01" />
					<span class="hint small">Lower finds more (and more false matches). Use <em>Test</em> to tune it.</span>
					<span v-if="fe.threshold" class="warn small">{{ fe.threshold }}</span>
				</label>
				<div class="row tight wrap">
					<label class="check"><input v-model="t.active" type="checkbox" /> Active</label>
					<label class="check" title="Only score the area around the symbol's lines, so pipes or text crossing it don't count against a match"><input v-model="t.use_mask" type="checkbox" /> Use search mask</label>
				</div>
				<label class="field">Mask width (line-weight tolerance)
					<input v-model.number="t.buffer_space" type="number" min="1" max="10" class="num" :disabled="!t.use_mask" />
					<span v-if="fe.buffer_space" class="warn small">{{ fe.buffer_space }}</span>
				</label>
				<fieldset class="variants">
					<legend>Also find it</legend>
					<label class="check"><input v-model="t.variants.rot90" type="checkbox" /> rotated 90°</label>
					<label class="check"><input v-model="t.variants.rot180" type="checkbox" /> 180°</label>
					<label class="check"><input v-model="t.variants.rot270" type="checkbox" /> 270°</label>
					<label class="check"><input v-model="t.variants.mirror" type="checkbox" /> mirrored</label>
				</fieldset>
				<label class="field">Sizes (1 = as cut; e.g. 0.9, 1, 1.1)
					<input :value="scalesText" :class="{ invalid: fe.scales }" @change="setScales(($event.target as HTMLInputElement).value)" />
					<span v-if="fe.scales" class="warn small">{{ fe.scales }}</span>
				</label>
				<label class="field">Skip if more matches than
					<input v-model.number="t.max_hits" type="number" min="1" class="num" />
				</label>
				<label class="field">Library (drawing type / block set)
					<span class="row tight">
						<input v-model="t.drawing_type" class="short" aria-label="Drawing type" />
						<input v-model="t.block_set" class="short" aria-label="Block set" />
					</span>
				</label>

				<h4>Test</h4>
				<div v-if="readyDrawings.length" class="row tight wrap">
					<select v-model="testDoc" aria-label="Drawing to test on">
						<option v-for="d in readyDrawings" :key="d.id" :value="d.id">{{ d.file_name }}</option>
					</select>
					<select v-if="testDrawing" v-model.number="testPage" aria-label="Page">
						<option v-for="p in testDrawing.pages" :key="p.n" :value="p.n">page {{ p.n }}</option>
					</select>
					<button type="button" :disabled="pid.busy" @click="runTest">Test on page</button>
				</div>
				<p v-else class="hint small">Upload a drawing to test this template.</p>
				<p class="hint small">Tests use the unsaved settings above and show the matches on the page; nothing is saved.</p>

				<div class="row tight danger-zone">
					<button type="button" class="secondary small" @click="remove">Delete template</button>
				</div>
			</div>
		</div>
	</section>
</template>
