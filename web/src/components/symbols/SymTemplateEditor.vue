<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import HistoryButton from '../audit/HistoryButton.vue';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { apiGetBlob } from '../../lib/engine';
import type { MaskMode } from '../../lib/symbolTypes';
import { useSymbols } from '../../stores/symbols';

const sym = useSymbols();
const t = computed(() => sym.templateDraft!);
const fe = computed(() => sym.fieldErrors);

const canvas = ref<HTMLCanvasElement | null>(null);
const image = ref<ImageBitmap | null>(null);
const showMask = ref(true);
const selected = ref<number | null>(null);
const zoom = ref(4);
const scalesText = ref('');
const tool = ref<'points' | 'paint' | 'erase'>('points');
const brush = ref(6); // template pixels
const maskInput = ref<HTMLInputElement | null>(null);

// The mask being shown/edited, at template size: white = compared, black = ignored.
const mask = document.createElement('canvas');
const tint = document.createElement('canvas'); // the mask as a translucent overlay

const testDoc = ref<string>('');
const testPage = ref(1);
const readyDrawings = computed(() => sym.drawings.filter((d) => d.status === 'ready'));
const testDrawing = computed(() => readyDrawings.value.find((d) => d.id === testDoc.value) ?? null);
const DEFAULT_NAMES = ['Function', 'Number', 'Suffix'];

async function loadImage() {
	image.value = await createImageBitmap(await apiGetBlob(`/api/symbols/templates/${t.value.id}/image.png`));
	const box = canvas.value?.parentElement;
	const fitZoom = box ? Math.min((box.clientWidth - 40) / image.value.width, 380 / image.value.height) : 4;
	zoom.value = Math.max(1, Math.min(8, Math.floor(fitZoom)));
	await loadMask();
}

/** Show the mask for the current mode (the painted draft wins while editing). */
async function loadMask(mode: MaskMode = t.value.mask_mode) {
	if (mode === 'custom' && sym.maskDraft) {
		await drawMaskFrom(sym.maskDraft);
		return;
	}
	const useMode = mode === 'custom' && !t.value.has_custom_mask ? 'auto' : mode;
	const q = new URLSearchParams({ mode: useMode, buffer_space: String(t.value.buffer_space) });
	await drawMaskFrom(await apiGetBlob(`/api/symbols/templates/${t.value.id}/mask.png?${q}`));
}

async function drawMaskFrom(b: Blob) {
	const bmp = await createImageBitmap(b);
	mask.width = t.value.width;
	mask.height = t.value.height;
	const ctx = mask.getContext('2d')!;
	ctx.imageSmoothingEnabled = false;
	ctx.drawImage(bmp, 0, 0, mask.width, mask.height);
	bmp.close();
	refreshTint();
}

function refreshTint() {
	tint.width = mask.width;
	tint.height = mask.height;
	if (!mask.width) return;
	const src = mask.getContext('2d')!.getImageData(0, 0, mask.width, mask.height);
	const out = tint.getContext('2d')!.createImageData(mask.width, mask.height);
	for (let i = 0; i < src.data.length; i += 4) {
		const on = src.data[i] > 127;
		out.data[i] = on ? 22 : 100;
		out.data[i + 1] = on ? 163 : 116;
		out.data[i + 2] = on ? 74 : 139;
		out.data[i + 3] = on ? 95 : 70;
	}
	tint.getContext('2d')!.putImageData(out, 0, 0);
	draw();
}

function storeMaskDraft() {
	mask.toBlob((b) => { if (b) sym.maskDraft = b; }, 'image/png');
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
	if (showMask.value && t.value.mask_mode !== 'none' && tint.width) ctx.drawImage(tint, PAD, PAD, im.width * z, im.height * z);
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
	if (tool.value !== 'points' && hover) {
		ctx.strokeStyle = tool.value === 'paint' ? '#16a34a' : '#475569';
		ctx.lineWidth = 1.5;
		ctx.beginPath();
		ctx.arc(PAD + hover[0] * z, PAD + hover[1] * z, (brush.value / 2) * z, 0, Math.PI * 2);
		ctx.stroke();
	}
}

let dragging: number | null = null;
let painting: [number, number] | null = null;
let hover: [number, number] | null = null;

function at(e: PointerEvent): [number, number] {
	const r = canvas.value!.getBoundingClientRect();
	const z = zoom.value;
	const im = image.value!;
	const x = Math.min(Math.max((e.clientX - r.left - PAD) / z, 0), im.width);
	const y = Math.min(Math.max((e.clientY - r.top - PAD) / z, 0), im.height);
	return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

function stroke(from: [number, number], to: [number, number]) {
	const ctx = mask.getContext('2d')!;
	ctx.strokeStyle = ctx.fillStyle = tool.value === 'paint' ? '#fff' : '#000';
	ctx.lineCap = 'round';
	ctx.lineWidth = brush.value;
	ctx.beginPath();
	ctx.moveTo(from[0], from[1]);
	ctx.lineTo(to[0], to[1]);
	ctx.stroke();
	ctx.beginPath();
	ctx.arc(to[0], to[1], brush.value / 2, 0, Math.PI * 2);
	ctx.fill();
	refreshTint();
}

function onDown(e: PointerEvent) {
	if (!image.value) return;
	canvas.value!.setPointerCapture(e.pointerId);
	const [x, y] = at(e);
	if (tool.value !== 'points') {
		painting = [x, y];
		stroke(painting, painting);
		return;
	}
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
	if (!image.value) return;
	const pt = at(e);
	hover = pt;
	if (painting) {
		stroke(painting, pt);
		painting = pt;
		return;
	}
	if (dragging === null) {
		if (tool.value !== 'points') draw();
		return;
	}
	const p = t.value.points[dragging];
	p.x = pt[0];
	p.y = pt[1];
	draw();
}

function onUp() {
	if (painting) storeMaskDraft();
	painting = null;
	dragging = null;
}

function onLeave() {
	hover = null;
	draw();
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

// -- mask tools ------------------------------------------------------------------

async function setMode(mode: MaskMode) {
	t.value.mask_mode = mode;
	if (mode === 'custom') {
		if (!t.value.has_custom_mask && !sym.maskDraft) {
			await loadMask('auto'); // start from the auto mask
			storeMaskDraft();
		} else {
			await loadMask('custom');
		}
		showMask.value = true;
		tool.value = 'paint';
	} else {
		tool.value = 'points';
		await loadMask(mode);
	}
}

function fillMask(on: boolean) {
	const ctx = mask.getContext('2d')!;
	ctx.fillStyle = on ? '#fff' : '#000';
	ctx.fillRect(0, 0, mask.width, mask.height);
	refreshTint();
	storeMaskDraft();
}

async function resetToAuto() {
	await loadMask('auto');
	storeMaskDraft();
}

async function uploadMask(file: File | undefined) {
	if (!file) return;
	// Dark or transparent = ignored, light = compared (like the mask preview).
	const bmp = await createImageBitmap(file);
	const tmp = document.createElement('canvas');
	tmp.width = mask.width;
	tmp.height = mask.height;
	const tctx = tmp.getContext('2d')!;
	tctx.fillStyle = '#000';
	tctx.fillRect(0, 0, tmp.width, tmp.height);
	tctx.drawImage(bmp, 0, 0, tmp.width, tmp.height);
	bmp.close();
	mask.getContext('2d')!.drawImage(tmp, 0, 0);
	refreshTint();
	storeMaskDraft();
	if (maskInput.value) maskInput.value.value = '';
}

async function removeCustom() {
	if (!confirm('Remove the painted mask and go back to the automatic one?')) return;
	await sym.clearCustomMask();
	tool.value = 'points';
	await loadMask('auto');
}

const preview = computed(() => {
	const parts: Record<string, string> = Object.fromEntries(t.value.points.map((p, i) => [p.name, ['FT', '1023', 'A'][i] ?? 'X']));
	if (!t.value.tag_format.trim()) return Object.values(parts).join('-');
	return t.value.tag_format.replace(/\{([^}]+)\}/g, (_, k: string) => parts[k] ?? '');
});

function remove() {
	if (confirm(`Delete the template "${t.value.desc}"?`)) void sym.deleteTemplate(t.value.id);
}

function runTest() {
	if (testDoc.value) void sym.testTemplate(testDoc.value, testPage.value);
}

watch(() => t.value?.id, () => { selected.value = null; scalesText.value = t.value.scales.join(', '); void loadImage(); });
watch(() => t.value?.buffer_space, () => { if (t.value.mask_mode === 'auto' && t.value.buffer_space >= 1) void loadMask(); });
watch(() => sym.maskDraft, (b) => { if (!b && t.value) void loadMask(); }); // discarded
watch([zoom, showMask, tool, () => t.value.points], draw, { deep: true });
watch(testDoc, () => { testPage.value = 1; });

onMounted(() => {
	scalesText.value = t.value.scales.join(', ');
	const last = sym.lastPage;
	const d = readyDrawings.value.find((x) => x.id === last?.id)
		?? readyDrawings.value.find((x) => x.library_id === t.value.library_id) ?? readyDrawings.value[0];
	if (d) {
		testDoc.value = d.id;
		testPage.value = last?.id === d.id ? last.page : 1;
	}
	void loadImage();
});
onBeforeUnmount(() => image.value?.close());
</script>

<template>
	<section class="card sym-main sym-template">
		<div class="mel-head">
			<input v-model="t.desc" class="name-input" aria-label="Template name" :class="{ invalid: fe.desc }" />
			<span class="chip">{{ sym.libraryName(t.library_id) }} · priority {{ t.priority + 1 }}</span>
			<span class="chip">{{ t.width }} × {{ t.height }} px</span>
			<span class="spacer" />
			<span v-if="sym.templateDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="sym.message" class="saved">✓ {{ sym.message }}</span>
			<HistoryButton entity="sym_template" :record-id="t.id" :label="t.desc || 'Symbol template'" />
			<button type="button" class="secondary" :disabled="!sym.templateDirty || sym.busy" @click="sym.discardTemplate()">Discard</button>
			<button type="button" :disabled="!sym.templateDirty || sym.busy" @click="sym.saveTemplate()">Save</button>
		</div>
		<p v-if="sym.error" class="error">{{ sym.error }}</p>

		<div class="sym-template-body">
			<div class="sym-template-image">
				<div class="row tight wrap">
					<span class="seg">
						<button type="button" class="small" :class="tool === 'points' ? '' : 'secondary'" title="Click where each part of the tag is written" @click="tool = 'points'">Tag points</button>
						<button type="button" class="small" :class="tool === 'paint' ? '' : 'secondary'" :disabled="t.mask_mode !== 'custom'" title="Paint the parts of the symbol to compare" @click="tool = 'paint'">Paint mask</button>
						<button type="button" class="small" :class="tool === 'erase' ? '' : 'secondary'" :disabled="t.mask_mode !== 'custom'" title="Erase parts to ignore" @click="tool = 'erase'">Erase mask</button>
					</span>
					<label v-if="tool !== 'points'" class="small">Brush <input v-model.number="brush" type="range" min="1" max="40" /> {{ brush }} px</label>
					<span class="spacer" />
					<label class="check small"><input v-model="showMask" type="checkbox" /> Show mask</label>
					<label class="small">Zoom <input v-model.number="zoom" type="range" min="1" max="10" /></label>
				</div>
				<p class="hint small">
					<template v-if="tool === 'points'">Click on the symbol where each part of the tag is written; drag a point to move it.</template>
					<template v-else>Green parts of the symbol are compared, grey parts are ignored (e.g. a variable fill, an arrow that changes direction, text).</template>
				</p>
				<div class="sym-template-canvas">
					<canvas ref="canvas" :class="`tool-${tool}`" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointerleave="onLeave" />
				</div>
				<table class="grid simple points-table">
					<thead><tr><th>Tag point</th><th>x</th><th>y</th><th title="How much of the word must lie inside the symbol (0-1)">Min overlap</th><th /></tr></thead>
					<tbody>
						<tr v-for="(p, i) in t.points" :key="i" :class="{ current: selected === i }" @click="selected = i; draw()">
							<td><input v-model="p.name" aria-label="Point name" /></td>
							<td><input v-model.number="p.x" type="number" step="0.5" class="num" aria-label="x" /></td>
							<td><input v-model.number="p.y" type="number" step="0.5" class="num" aria-label="y" /></td>
							<td><input v-model.number="p.min_overlap" type="number" min="0" max="1" step="0.05" class="num" aria-label="Minimum overlap" /></td>
							<td><button type="button" class="secondary small" @click.stop="removePoint(i)">Remove</button></td>
						</tr>
						<tr v-if="!t.points.length"><td colspan="5" class="hint">No tag points: matches of this template are counted but give no tag (fine for valves and other untagged symbols).</td></tr>
					</tbody>
				</table>
				<p v-if="fe.points" class="warn small">{{ fe.points }}</p>
			</div>

			<div class="sym-template-form">
				<label class="field">Tag format
					<input v-model="t.tag_format" placeholder="{Function}-{Number}" :class="{ invalid: fe.tag_format }" />
					<span class="hint small">Example: <code>{{ preview || '—' }}</code>. Leave blank to join the parts with “-”. The library's tag format is applied after this.</span>
					<span v-if="fe.tag_format" class="warn small">{{ fe.tag_format }}</span>
				</label>
				<label class="field">Match threshold <strong>{{ t.threshold.toFixed(2) }}</strong>
					<input v-model.number="t.threshold" type="range" min="0.3" max="1" step="0.01" />
					<span class="hint small">Lower finds more (and more false matches). Use <em>Test</em> to tune it; a page can override it.</span>
					<span v-if="fe.threshold" class="warn small">{{ fe.threshold }}</span>
				</label>
				<fieldset class="variants mask-modes">
					<legend>Compare</legend>
					<label class="check"><input type="radio" :checked="t.mask_mode === 'auto'" @change="setMode('auto')" /> the symbol's lines, widened by
						<input v-model.number="t.buffer_space" type="number" min="1" max="10" class="num tiny" :disabled="t.mask_mode !== 'auto'" aria-label="Mask width" /> px</label>
					<label class="check"><input type="radio" :checked="t.mask_mode === 'custom'" @change="setMode('custom')" /> a custom mask (paint or upload)</label>
					<label class="check"><input type="radio" :checked="t.mask_mode === 'none'" @change="setMode('none')" /> the whole rectangle</label>
					<div v-if="t.mask_mode === 'custom'" class="row tight wrap mask-tools">
						<button type="button" class="secondary small" @click="resetToAuto">Start from lines</button>
						<button type="button" class="secondary small" @click="fillMask(true)">All</button>
						<button type="button" class="secondary small" @click="fillMask(false)">None</button>
						<button type="button" class="secondary small" @click="maskInput?.click()">Upload…</button>
						<input ref="maskInput" type="file" accept="image/*" hidden @change="uploadMask(($event.target as HTMLInputElement).files?.[0])" />
						<button v-if="t.has_custom_mask" type="button" class="link small" @click="removeCustom">remove saved mask</button>
					</div>
					<span v-if="fe.mask_mode" class="warn small">{{ fe.mask_mode }}</span>
					<span v-if="fe.buffer_space" class="warn small">{{ fe.buffer_space }}</span>
				</fieldset>
				<div class="row tight wrap">
					<label class="check"><input v-model="t.active" type="checkbox" /> Active</label>
				</div>
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
				<label class="field">Library
					<select v-model="t.library_id">
						<option v-for="l in sym.libraries" :key="l.id" :value="l.id">{{ l.name }}</option>
					</select>
				</label>

				<h4>Test</h4>
				<div v-if="readyDrawings.length" class="row tight wrap">
					<select v-model="testDoc" aria-label="Drawing to test on">
						<option v-for="d in readyDrawings" :key="d.id" :value="d.id">{{ d.file_name }}</option>
					</select>
					<select v-if="testDrawing" v-model.number="testPage" aria-label="Page">
						<option v-for="p in testDrawing.pages" :key="p.n" :value="p.n">page {{ p.n }}</option>
					</select>
					<button type="button" :disabled="sym.busy" @click="runTest">Test on page</button>
				</div>
				<p v-else class="hint small">Upload a drawing to test this template.</p>
				<p class="hint small">Tests use the unsaved settings and mask above and show the matches on the page; nothing is saved.</p>

				<div class="row tight danger-zone">
					<button type="button" class="secondary small" @click="remove">Delete template</button>
				</div>
			</div>
		</div>
	</section>
</template>
