<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { Box, PageOverride, PageResult, Word } from '../../lib/symbolTypes';
import { useSymbols } from '../../stores/symbols';

const props = defineProps<{ docId: string; page: number }>();
const sym = useSymbols();

const drawing = computed(() => sym.drawings.find((d) => d.id === props.docId) ?? null);
const info = computed(() => drawing.value?.pages[props.page - 1] ?? null);
const lib = computed(() => sym.libraries.find((l) => l.id === drawing.value?.library_id) ?? null);
const libTemplates = computed(() => (drawing.value ? sym.templates.filter((t) => t.library_id === drawing.value!.library_id) : []));
const exclusion = computed(() => lib.value?.exclusion);
const testHere = computed(() =>
	sym.test && sym.test.doc === props.docId && sym.test.page === props.page ? sym.test : null,
);

const host = ref<HTMLDivElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const img = ref<ImageBitmap | null>(null);
const result = ref<PageResult | null>(null);
const words = ref<Word[]>([]);
const overrides = ref<Record<string, PageOverride>>({});
const show = ref({ symbols: true, tags: true, words: false, excluded: true });
const mode = ref<'pan' | 'template' | 'exclude'>('pan');
const selection = ref<Box | null>(null); // dragged rectangle, image pixels
const dragging = ref(false); // banners wait for the drag to end (and overlay the canvas: no layout shift)
const newName = ref('');
const picked = ref<{ box: Box; title: string; lines: string[] } | null>(null);
const loading = ref(false);
const side = ref(true);

// view transform: screen = image * scale + offset (CSS pixels)
let scale = 1;
let ox = 0;
let oy = 0;

const COLORS = ['#2563eb', '#16a34a', '#d97706', '#9333ea', '#dc2626', '#0891b2', '#65a30d', '#db2777'];
const colorOf = (templateId: string) => {
	const i = libTemplates.value.findIndex((t) => t.id === templateId);
	return COLORS[(i < 0 ? 0 : i) % COLORS.length];
};

async function load() {
	if (!drawing.value || drawing.value.status !== 'ready') return;
	loading.value = true;
	picked.value = null;
	selection.value = null;
	try {
		const [bmp, res, ovs] = await Promise.all([
			sym.pageImage(props.docId, props.page),
			sym.pageResult(props.docId, props.page),
			sym.overrides(props.docId, props.page),
		]);
		img.value = bmp;
		result.value = res;
		overrides.value = Object.fromEntries(ovs.map((o) => [o.template_id, o]));
		words.value = show.value.words ? await sym.pageWords(props.docId, props.page) : [];
		fit();
	} catch (err) {
		sym.error = err instanceof Error ? err.message : String(err);
	} finally {
		loading.value = false;
	}
}

function fit() {
	const c = canvas.value;
	if (!c || !img.value) return;
	const w = c.clientWidth;
	const h = c.clientHeight;
	scale = Math.min(w / img.value.width, h / img.value.height) * 0.98;
	ox = (w - img.value.width * scale) / 2;
	oy = (h - img.value.height * scale) / 2;
	draw();
}

function zoomTo(box: Box) {
	const c = canvas.value;
	if (!c) return;
	const bw = box[2] - box[0];
	const bh = box[3] - box[1];
	scale = Math.min(c.clientWidth / (bw * 6), c.clientHeight / (bh * 6), 3);
	ox = c.clientWidth / 2 - ((box[0] + box[2]) / 2) * scale;
	oy = c.clientHeight / 2 - ((box[1] + box[3]) / 2) * scale;
	draw();
}

function zoomBy(f: number, cx?: number, cy?: number) {
	const c = canvas.value;
	if (!c) return;
	const x = cx ?? c.clientWidth / 2;
	const y = cy ?? c.clientHeight / 2;
	const next = Math.min(Math.max(scale * f, 0.02), 8);
	ox = x - ((x - ox) * next) / scale;
	oy = y - ((y - oy) * next) / scale;
	scale = next;
	draw();
}

function rect(ctx: CanvasRenderingContext2D, b: Box) {
	ctx.strokeRect(b[0] * scale + ox, b[1] * scale + oy, (b[2] - b[0]) * scale, (b[3] - b[1]) * scale);
}

function label(ctx: CanvasRenderingContext2D, b: Box, text: string, color: string, below = false) {
	ctx.font = '11px system-ui, sans-serif';
	const w = ctx.measureText(text).width + 6;
	const x = b[0] * scale + ox;
	const y = below ? b[3] * scale + oy : b[1] * scale + oy - 14;
	ctx.fillStyle = color;
	ctx.fillRect(x, y, w, 14);
	ctx.fillStyle = '#fff';
	ctx.fillText(text, x + 3, y + 11);
}

function draw() {
	const c = canvas.value;
	if (!c) return;
	const dpr = window.devicePixelRatio || 1;
	const w = c.clientWidth;
	const h = c.clientHeight;
	if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
		c.width = Math.round(w * dpr);
		c.height = Math.round(h * dpr);
	}
	const ctx = c.getContext('2d')!;
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.fillStyle = '#e5e7eb';
	ctx.fillRect(0, 0, w, h);
	if (!img.value) return;
	ctx.imageSmoothingEnabled = scale < 1;
	ctx.imageSmoothingQuality = 'high';
	ctx.drawImage(img.value, ox, oy, img.value.width * scale, img.value.height * scale);
	const iw = img.value.width;
	const ih = img.value.height;

	if (show.value.excluded && exclusion.value) {
		ctx.fillStyle = 'rgba(100, 116, 139, 0.18)';
		ctx.strokeStyle = '#64748b';
		ctx.setLineDash([6, 4]);
		for (const a of exclusion.value.areas) {
			const b: Box = [a[0] * iw, a[1] * ih, a[2] * iw, a[3] * ih];
			ctx.fillRect(b[0] * scale + ox, b[1] * scale + oy, (b[2] - b[0]) * scale, (b[3] - b[1]) * scale);
			rect(ctx, b);
		}
		ctx.setLineDash([]);
	}
	if (show.value.words) {
		ctx.strokeStyle = 'rgba(14, 165, 233, 0.8)';
		ctx.lineWidth = 1;
		for (const wd of words.value) rect(ctx, wd.box);
	}
	const res = result.value;
	if (res && show.value.symbols && !testHere.value) {
		ctx.lineWidth = 2;
		for (const s of res.symbols) {
			const col = colorOf(s.template_id);
			ctx.strokeStyle = col;
			rect(ctx, s.box);
			if (scale > 0.25) label(ctx, s.box, s.tag ?? s.template_desc, col);
		}
	}
	if (res && show.value.tags && !testHere.value) {
		ctx.lineWidth = 2;
		ctx.setLineDash([4, 3]);
		for (const t of res.tags.filter((x) => x.source === 'pattern')) {
			ctx.strokeStyle = '#7c3aed';
			rect(ctx, t.box);
			if (scale > 0.25) label(ctx, t.box, t.tag, '#7c3aed', true);
		}
		ctx.setLineDash([]);
	}
	if (testHere.value) {
		ctx.lineWidth = 3;
		ctx.strokeStyle = '#ea580c';
		for (const s of testHere.value.result.symbols) {
			rect(ctx, s.box);
			if (scale > 0.25) label(ctx, s.box, `${s.score.toFixed(2)}${s.tag ? ' ' + s.tag : ''}`, '#ea580c');
		}
	}
	if (picked.value) {
		ctx.lineWidth = 3;
		ctx.strokeStyle = '#facc15';
		rect(ctx, picked.value.box.map((v, i) => v + (i < 2 ? -4 : 4)) as Box);
	}
	if (selection.value) {
		ctx.lineWidth = 2;
		ctx.strokeStyle = mode.value === 'exclude' ? '#475569' : '#e11d48';
		ctx.setLineDash([5, 3]);
		rect(ctx, selection.value);
		ctx.setLineDash([]);
	}
}

// -- pointer -------------------------------------------------------------------
let drag: { x: number; y: number; ox: number; oy: number; moved: boolean; start?: [number, number] } | null = null;

function toImage(e: PointerEvent | MouseEvent): [number, number] {
	const r = canvas.value!.getBoundingClientRect();
	return [(e.clientX - r.left - ox) / scale, (e.clientY - r.top - oy) / scale];
}

function onDown(e: PointerEvent) {
	canvas.value!.setPointerCapture(e.pointerId);
	drag = { x: e.clientX, y: e.clientY, ox, oy, moved: false };
	dragging.value = true;
	if (mode.value !== 'pan' && e.button === 0) {
		drag.start = toImage(e);
		selection.value = null;
	}
}

function onMove(e: PointerEvent) {
	if (!drag) return;
	const dx = e.clientX - drag.x;
	const dy = e.clientY - drag.y;
	if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
	if (drag.start) {
		const [x, y] = toImage(e);
		selection.value = [Math.min(drag.start[0], x), Math.min(drag.start[1], y), Math.max(drag.start[0], x), Math.max(drag.start[1], y)];
	} else {
		ox = drag.ox + dx;
		oy = drag.oy + dy;
	}
	draw();
}

function onUp(e: PointerEvent) {
	const d = drag;
	drag = null;
	dragging.value = false;
	if (!d) return;
	if (!d.moved && !d.start) pick(e);
	if (d.start && selection.value && selection.value[2] - selection.value[0] < 6) selection.value = null;
	draw();
}

function onWheel(e: WheelEvent) {
	const r = canvas.value!.getBoundingClientRect();
	zoomBy(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left, e.clientY - r.top);
}

function inside(p: [number, number], b: Box) {
	return p[0] >= b[0] && p[0] <= b[2] && p[1] >= b[1] && p[1] <= b[3];
}

function pick(e: PointerEvent) {
	const p = toImage(e);
	const res = result.value;
	picked.value = null;
	const s = (testHere.value?.result.symbols ?? res?.symbols ?? []).find((x) => inside(p, x.box));
	if (s) {
		picked.value = {
			box: s.box,
			title: s.tag ?? '(no tag)',
			lines: [
				`${s.template_desc} · score ${s.score.toFixed(3)}${s.variant !== '0' ? ` · variant ${s.variant}` : ''}`,
				...Object.entries(s.parts).map(([k, v]) => `${k}: ${v ?? 'Not found'}`),
			],
		};
	} else {
		const t = res?.tags.find((x) => inside(p, x.box));
		if (t) picked.value = { box: t.box, title: t.tag, lines: [`Found by the ${t.source} scan`] };
	}
	draw();
}

// -- actions -------------------------------------------------------------------
async function analyse() {
	const r = await sym.analysePage(props.docId, props.page);
	if (r) {
		result.value = r;
		sym.test = null;
		draw();
	}
}

async function createTemplate() {
	if (!selection.value) return;
	const t = await sym.templateFromPage(props.docId, props.page, selection.value, newName.value || 'Symbol');
	if (t) {
		selection.value = null;
		newName.value = '';
		mode.value = 'pan';
	}
}

async function addExclusion() {
	if (!selection.value || !img.value || !drawing.value) return;
	const b = selection.value;
	const iw = img.value.width;
	const ih = img.value.height;
	const r = (v: number) => Math.round(v * 10000) / 10000;
	const area: Box = [r(b[0] / iw), r(b[1] / ih), r(b[2] / iw), r(b[3] / ih)];
	if (await sym.patchLibrary(drawing.value.library_id, (l) => l.exclusion.areas.push(area))) {
		sym.message = `Text in that area is now ignored on every sheet that uses “${lib.value?.name}”. Analyse again to apply it.`;
		selection.value = null;
		mode.value = 'pan';
		draw();
	}
}

async function setOv(templateId: string, patch: Partial<PageOverride> | null) {
	if (patch === null) {
		await sym.setOverride(props.docId, props.page, { template_id: templateId, clear: true });
		delete overrides.value[templateId];
	} else {
		const base: PageOverride = overrides.value[templateId] ?? { template_id: templateId, threshold: null, ignore: false };
		const ov: PageOverride = { ...base, ...patch };
		if (await sym.setOverride(props.docId, props.page, ov)) overrides.value[templateId] = ov;
	}
}

function goPage(n: number) {
	if (!drawing.value || n < 1 || n > drawing.value.pages.length) return;
	sym.show({ kind: 'drawing', id: props.docId, page: n });
}

watch(() => [props.docId, props.page, drawing.value?.status], load);
watch(() => show.value.words, async (on) => {
	words.value = on ? await sym.pageWords(props.docId, props.page) : [];
	draw();
});
watch([show, exclusion, testHere, () => sym.templates], draw, { deep: true });
watch(mode, () => { selection.value = null; draw(); });

let ro: ResizeObserver | null = null;
onMounted(() => {
	ro = new ResizeObserver(() => (img.value && scale ? draw() : fit()));
	if (host.value) ro.observe(host.value);
	void load();
});
onBeforeUnmount(() => ro?.disconnect());
</script>

<template>
	<section class="card sym-main sym-viewer">
		<div class="sym-toolbar">
			<strong class="name" :title="drawing?.file_name">{{ drawing?.file_name }}</strong>
			<span class="row tight">
				<button type="button" class="secondary small" :disabled="page <= 1" @click="goPage(page - 1)">‹</button>
				<span class="small">Page {{ page }} / {{ drawing?.pages.length ?? '?' }}</span>
				<button type="button" class="secondary small" :disabled="!drawing || page >= drawing.pages.length" @click="goPage(page + 1)">›</button>
			</span>
			<span class="seg">
				<button type="button" class="small" :class="mode === 'pan' ? '' : 'secondary'" title="Drag to pan, wheel to zoom, click a box for details" @click="mode = 'pan'">Pan</button>
				<button type="button" class="small" :class="mode === 'template' ? '' : 'secondary'" title="Drag a box around one symbol to make a template" @click="mode = 'template'">New template</button>
				<button type="button" class="small" :class="mode === 'exclude' ? '' : 'secondary'" title="Drag a box over the title block or notes: text there is ignored" @click="mode = 'exclude'">Ignore area</button>
			</span>
			<span class="row tight">
				<button type="button" class="secondary small" title="Zoom out" @click="zoomBy(1 / 1.4)">−</button>
				<button type="button" class="secondary small" title="Zoom in" @click="zoomBy(1.4)">+</button>
				<button type="button" class="secondary small" @click="fit">Fit</button>
			</span>
			<span class="spacer" />
			<button type="button" :disabled="sym.busy || drawing?.status !== 'ready'" @click="analyse">Analyse page</button>
			<button type="button" class="secondary small" :title="side ? 'Hide the side panel' : 'Show the side panel'" @click="side = !side">{{ side ? '⇥' : '⇤' }}</button>
		</div>

		<div v-if="testHere" class="sym-banner test">
			<span>
				Testing <strong>{{ testHere.template.desc }}</strong>: {{ testHere.result.symbols.length }} match(es) at threshold
				{{ testHere.template.threshold }} · best score {{ testHere.result.best.toFixed(3) }}
				<template v-if="testHere.result.skipped"> · <span class="warn">{{ testHere.result.skipped }}</span></template>
			</span>
			<button type="button" class="small" @click="sym.backToTemplate()">Back to the template</button>
			<button type="button" class="secondary small" @click="sym.test = null">Clear test</button>
		</div>
		<p v-if="sym.error" class="error">{{ sym.error }}</p>
		<p v-else-if="sym.message" class="saved">{{ sym.message }}</p>

		<div class="sym-body" :class="{ 'no-side': !side }">
			<div ref="host" class="sym-canvas-host" :class="`mode-${mode}`">
				<canvas ref="canvas" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @wheel.prevent="onWheel" @dblclick="fit" />
				<div v-if="selection && !dragging && mode === 'template'" class="sym-banner floating">
					<span>Make a template from the selected symbol (its text is left out, and the box is trimmed to the linework):</span>
					<input v-model="newName" placeholder="Name, e.g. Instrument bubble" @keydown.enter="createTemplate" />
					<button type="button" class="small" :disabled="sym.busy" @click="createTemplate">Create template</button>
					<button type="button" class="secondary small" @click="selection = null; draw()">Cancel</button>
				</div>
				<div v-else-if="selection && !dragging && mode === 'exclude'" class="sym-banner floating">
					<span>Ignore text in this area on every sheet that uses “{{ lib?.name }}” (title block, notes, revision table)?</span>
					<button type="button" class="small" :disabled="sym.busy" @click="addExclusion">Ignore area</button>
					<button type="button" class="secondary small" @click="selection = null; draw()">Cancel</button>
				</div>
				<p v-if="drawing?.status === 'rendering'" class="sym-overlay-msg">Preparing pages…</p>
				<p v-else-if="drawing?.status === 'error'" class="sym-overlay-msg error">{{ drawing.error }}</p>
				<p v-else-if="loading" class="sym-overlay-msg">Loading…</p>
			</div>
			<aside v-if="side" class="sym-side">
				<div class="row tight wrap">
					<label class="check"><input v-model="show.symbols" type="checkbox" /> Symbols</label>
					<label class="check"><input v-model="show.tags" type="checkbox" /> Text tags</label>
					<label class="check"><input v-model="show.words" type="checkbox" /> Words</label>
					<label class="check"><input v-model="show.excluded" type="checkbox" /> Ignored areas</label>
				</div>
				<div v-if="picked" class="sym-picked">
					<strong>{{ picked.title }}</strong>
					<div v-for="l in picked.lines" :key="l" class="small">{{ l }}</div>
				</div>
				<h4>Drawing</h4>
				<div v-if="drawing" class="row tight wrap">
					<select :value="drawing.library_id" title="Which symbol library to use for this drawing" aria-label="Library"
						@change="sym.editDrawing(drawing, { library_id: ($event.target as HTMLSelectElement).value })">
						<option v-for="l in sym.libraries" :key="l.id" :value="l.id">{{ l.name }}</option>
					</select>
					<label class="check small" :title="sym.ocr?.available ? 'Read text with OCR even where the PDF has a text layer' : sym.ocr?.reason ?? ''">
						<input type="checkbox" :checked="drawing.force_ocr" @change="sym.editDrawing(drawing, { force_ocr: ($event.target as HTMLInputElement).checked })" /> Always OCR
					</label>
				</div>
				<h4>This page</h4>
				<p v-if="info" class="small">
					Text from
					<strong>{{ info.text_source === 'pdf' ? 'the PDF text layer' : info.text_source === 'ocr' ? 'OCR' : 'nowhere (no text)' }}</strong>
					· {{ info.word_count }} words<template v-if="info.rotation"> · rotated {{ info.rotation }}°</template>
				</p>
				<p v-for="w in result?.warnings ?? []" :key="w" class="warn small">{{ w }}</p>
				<template v-if="result">
					<p class="small">{{ result.symbols.length }} symbols · {{ result.tags.length }} tags</p>
					<ul class="sym-taglist">
						<li v-for="(t, i) in result.tags" :key="i" @click="zoomTo(t.box)">
							<span class="tag">{{ t.tag }}</span>
							<span class="src" :class="t.source">{{ t.source === 'template' ? t.template_desc : 'text scan' }}</span>
						</li>
					</ul>
				</template>
				<p v-else class="hint small">Not analysed yet: use <strong>Analyse page</strong>, or analyse the drawing from the list.</p>

				<h4>Templates on this page</h4>
				<p class="hint small">Override a threshold for this page only, or skip a template here.</p>
				<table v-if="libTemplates.length" class="grid simple ov-table">
					<thead><tr><th>Template</th><th>Threshold</th><th>Skip</th></tr></thead>
					<tbody>
						<tr v-for="t in libTemplates" :key="t.id">
							<td><span class="swatch" :style="{ background: colorOf(t.id) }" />{{ t.desc }}</td>
							<td>
								<input type="number" min="0.05" max="1" step="0.01" class="num"
									:placeholder="String(t.threshold)" :value="overrides[t.id]?.threshold ?? ''"
									@change="setOv(t.id, { threshold: ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value) })" />
							</td>
							<td>
								<input type="checkbox" :checked="overrides[t.id]?.ignore ?? false"
									@change="setOv(t.id, { ignore: ($event.target as HTMLInputElement).checked })" />
								<button v-if="overrides[t.id]" type="button" class="link small" title="Remove the override" @click="setOv(t.id, null)">reset</button>
							</td>
						</tr>
					</tbody>
				</table>
				<p v-else class="hint small">“{{ lib?.name }}” has no templates yet: use <strong>New template</strong>.</p>
			</aside>
		</div>
	</section>
</template>
