<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { Box, FoundTag, PageOverride, PageResult, ReviewAction, RunSheet, Symbol, TemplatePreview, Word } from '../../lib/symbolTypes';
import { useSymbols } from '../../stores/symbols';

// With runId the page shows that analysis run's result, page navigation goes through the
// run's sheets, and corrections also update the run's tags list.
const props = defineProps<{ docId: string; page: number; runId?: string | null }>();
const emit = defineEmits<{ navigate: [docId: string, page: number] }>();
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
// `words`: every piece of text read on the sheet (from the PDF, or by OCR), shown as a light yellow box
const show = ref({ symbols: true, tags: true, words: true, excluded: true, rejected: true });
const mode = ref<'pan' | 'add' | 'template' | 'exclude'>('pan');
const addTemplate = ref(''); // "Add missed": the template placed on click
const selection = ref<Box | null>(null); // dragged rectangle, image pixels
const dragging = ref(false); // banners wait for the drag to end (and overlay the canvas: no layout shift)
// New template: what the dragged box would cut (trimmed to the linework), shown before creating it
const preview = ref<TemplatePreview | null>(null);
const previewError = ref<string | null>(null);
const trimOn = ref(true);
type Handle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'move';
const hoverHandle = ref<Handle | null>(null);
const newName = ref('');
// What a click picked: a symbol or a text-scan tag, kept or marked as a false positive.
type Pick =
	| { kind: 'symbol'; rejected: boolean; item: Symbol }
	| { kind: 'tag'; rejected: boolean; item: FoundTag }
	| { kind: 'test'; rejected: false; item: Symbol };
const picked = ref<Pick | null>(null);
const typedTag = ref('');
const sheets = ref<RunSheet[]>([]);
const sheetIndex = computed(() => sheets.value.findIndex((x) => x.doc_id === props.docId && x.page === props.page));
const pickedInfo = computed(() => {
	const p = picked.value;
	if (!p) return null;
	if (p.kind === 'tag') return { box: p.item.box, title: p.item.tag, lines: ['Found by the text scan (the library\'s tag pattern)'] };
	const s = p.item;
	return {
		box: s.box,
		title: s.tag ?? '(no tag)',
		lines: [
			`${s.template_desc} · ${s.origin === 'manual' ? 'added by hand, score' : 'score'} ${s.score.toFixed(3)}${s.variant !== '0' ? ` · variant ${s.variant}` : ''}`,
			...Object.entries(s.parts).map(([k, v]) => `${k}: ${v ?? 'Not found'}`),
		],
	};
});
const manualSymbols = computed(() => result.value?.symbols.filter((s) => s.origin === 'manual') ?? []);
const corrections = computed(
	() => (result.value?.rejected_symbols?.length ?? 0) + (result.value?.rejected_tags?.length ?? 0) + manualSymbols.value.length,
);
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
			props.runId ? sym.runPageResult(props.runId, props.docId, props.page) : sym.pageResult(props.docId, props.page),
			sym.overrides(props.docId, props.page),
		]);
		img.value = bmp;
		result.value = res;
		overrides.value = Object.fromEntries(ovs.map((o) => [o.template_id, o]));
		words.value = show.value.words ? await sym.pageWords(props.docId, props.page) : [];
		if (props.runId && !sheets.value.length) sheets.value = await sym.runSheets(props.runId);
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
	ctx.clearRect(0, 0, w, h); // the host's grid paper shows around the sheet
	if (!img.value) return;
	ctx.shadowColor = 'rgba(0, 0, 0, 0.18)';
	ctx.shadowBlur = 6;
	ctx.fillStyle = '#fff';
	ctx.fillRect(ox, oy, img.value.width * scale, img.value.height * scale);
	ctx.shadowColor = 'transparent';
	ctx.shadowBlur = 0;
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
		// a see-through highlighter over each word, so the drawing stays readable under it
		ctx.fillStyle = 'rgba(255, 235, 59, 0.4)';
		for (const wd of words.value) {
			const [x1, y1, x2, y2] = wd.box;
			ctx.fillRect(x1 * scale + ox, y1 * scale + oy, (x2 - x1) * scale, (y2 - y1) * scale);
		}
	}
	const res = result.value;
	if (res && show.value.symbols && !testHere.value) {
		ctx.lineWidth = 2;
		for (const s of res.symbols) {
			const col = colorOf(s.template_id);
			ctx.strokeStyle = col;
			ctx.lineWidth = s.origin === 'manual' ? 3 : 2;
			rect(ctx, s.box);
			if (scale > 0.25) label(ctx, s.box, `${s.origin === 'manual' ? '+ ' : ''}${s.tag ?? s.template_desc}`, col);
		}
	}
	if (res && show.value.rejected && !testHere.value) {
		// False positives: grey, dashed and crossed out (click one to restore it)
		ctx.lineWidth = 2;
		ctx.strokeStyle = '#6b7280';
		ctx.setLineDash([5, 4]);
		for (const b of [...(res.rejected_symbols ?? []), ...(res.rejected_tags ?? [])].map((x) => x.box)) {
			rect(ctx, b);
			ctx.beginPath();
			ctx.moveTo(b[0] * scale + ox, b[1] * scale + oy);
			ctx.lineTo(b[2] * scale + ox, b[3] * scale + oy);
			ctx.moveTo(b[2] * scale + ox, b[1] * scale + oy);
			ctx.lineTo(b[0] * scale + ox, b[3] * scale + oy);
			ctx.stroke();
		}
		ctx.setLineDash([]);
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
	if (pickedInfo.value) {
		ctx.lineWidth = 3;
		ctx.strokeStyle = '#facc15';
		rect(ctx, pickedInfo.value.box.map((v, i) => v + (i < 2 ? -4 : 4)) as Box);
	}
	if (selection.value) {
		const b = selection.value;
		const col = mode.value === 'exclude' ? '#5f6368' : '#1a73e8';
		if (mode.value === 'template' && preview.value && trimOn.value && !dragging.value) {
			// What the template keeps
			ctx.lineWidth = 1.5;
			ctx.strokeStyle = '#16a34a';
			rect(ctx, preview.value.rect);
		}
		ctx.lineWidth = 2;
		ctx.strokeStyle = col;
		ctx.setLineDash([5, 3]);
		rect(ctx, b);
		ctx.setLineDash([]);
		label(ctx, b, `${Math.round(b[2] - b[0])} × ${Math.round(b[3] - b[1])} px`, col, true);
		ctx.fillStyle = '#fff';
		for (const [, hx, hy] of handles(b)) {
			ctx.fillRect(hx - HANDLE / 2, hy - HANDLE / 2, HANDLE, HANDLE);
			ctx.strokeRect(hx - HANDLE / 2, hy - HANDLE / 2, HANDLE, HANDLE);
		}
	}
}

// -- selection handles (screen pixels) --------------------------------------------
const HANDLE = 8;

function handles(b: Box): [Handle, number, number][] {
	const x1 = b[0] * scale + ox, y1 = b[1] * scale + oy, x2 = b[2] * scale + ox, y2 = b[3] * scale + oy;
	const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
	return [['nw', x1, y1], ['n', mx, y1], ['ne', x2, y1], ['e', x2, my], ['se', x2, y2], ['s', mx, y2], ['sw', x1, y2], ['w', x1, my]];
}

function handleAt(e: PointerEvent): Handle | null {
	const b = selection.value;
	if (!b || (mode.value !== 'template' && mode.value !== 'exclude')) return null;
	const r = canvas.value!.getBoundingClientRect();
	const x = e.clientX - r.left, y = e.clientY - r.top;
	const hit = handles(b).find(([, hx, hy]) => Math.abs(x - hx) <= HANDLE && Math.abs(y - hy) <= HANDLE);
	if (hit) return hit[0];
	return inside(toImage(e), b) ? 'move' : null;
}

function adjusted(h: Handle, b: Box, dx: number, dy: number): Box {
	if (h === 'move') return [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy];
	const n = [...b] as Box;
	if (h.includes('w')) n[0] += dx;
	if (h.includes('e')) n[2] += dx;
	if (h.includes('n')) n[1] += dy;
	if (h.includes('s')) n[3] += dy;
	return [Math.min(n[0], n[2]), Math.min(n[1], n[3]), Math.max(n[0], n[2]), Math.max(n[1], n[3])];
}

// -- template preview ---------------------------------------------------------------
let previewTimer: ReturnType<typeof setTimeout> | undefined;
let previewSeq = 0;

function schedulePreview() {
	clearTimeout(previewTimer);
	if (mode.value !== 'template' || !selection.value) return;
	const rect = selection.value.map((v) => Math.round(v));
	previewTimer = setTimeout(async () => {
		const seq = ++previewSeq;
		try {
			const pv = await sym.previewTemplate(props.docId, props.page, rect, trimOn.value);
			if (seq !== previewSeq) return;
			preview.value = pv;
			previewError.value = null;
		} catch (err) {
			if (seq !== previewSeq) return;
			preview.value = null;
			previewError.value = err instanceof Error ? err.message : String(err);
		}
		draw();
	}, 250);
}

// -- pointer -------------------------------------------------------------------
let drag: {
	x: number; y: number; ox: number; oy: number; moved: boolean;
	start?: [number, number]; // drawing a new box from here (image pixels)
	edit?: { handle: Handle; box: Box; from: [number, number] }; // resizing / moving the box
} | null = null;

function toImage(e: PointerEvent | MouseEvent): [number, number] {
	const r = canvas.value!.getBoundingClientRect();
	return [(e.clientX - r.left - ox) / scale, (e.clientY - r.top - oy) / scale];
}

function onDown(e: PointerEvent) {
	canvas.value!.setPointerCapture(e.pointerId);
	drag = { x: e.clientX, y: e.clientY, ox, oy, moved: false };
	dragging.value = true;
	if ((mode.value === 'template' || mode.value === 'exclude') && e.button === 0) {
		const h = handleAt(e);
		if (h && selection.value) drag.edit = { handle: h, box: [...selection.value] as Box, from: toImage(e) };
		else {
			drag.start = toImage(e);
			selection.value = null;
		}
	}
}

function onMove(e: PointerEvent) {
	if (!drag) {
		const h = handleAt(e);
		if (h !== hoverHandle.value) hoverHandle.value = h;
		return;
	}
	const dx = e.clientX - drag.x;
	const dy = e.clientY - drag.y;
	if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
	if (drag.edit) {
		const [x, y] = toImage(e);
		selection.value = adjusted(drag.edit.handle, drag.edit.box, x - drag.edit.from[0], y - drag.edit.from[1]);
	} else if (drag.start) {
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
	if (!d.moved && !d.start && !d.edit) {
		if (mode.value === 'add') void addAt(toImage(e));
		else pick(toImage(e));
	}
	if (d.start && selection.value && (selection.value[2] - selection.value[0] < 6 || selection.value[3] - selection.value[1] < 6)) {
		selection.value = null;
	}
	if ((d.start || d.edit) && selection.value) schedulePreview();
	draw();
}

function onWheel(e: WheelEvent) {
	const r = canvas.value!.getBoundingClientRect();
	zoomBy(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left, e.clientY - r.top);
}

function inside(p: [number, number], b: Box) {
	return p[0] >= b[0] && p[0] <= b[2] && p[1] >= b[1] && p[1] <= b[3];
}

function pick(p: [number, number]) {
	const res = result.value;
	picked.value = null;
	typedTag.value = '';
	const at = <T extends { box: Box }>(xs: T[] | undefined) => (xs ?? []).find((x) => inside(p, x.box));
	if (testHere.value) {
		const s = at(testHere.value.result.symbols);
		if (s) picked.value = { kind: 'test', rejected: false, item: s };
	} else if (res) {
		const s = show.value.symbols ? at(res.symbols) : undefined;
		const t = show.value.tags ? at(res.tags.filter((x) => x.source === 'pattern')) : undefined;
		const rs = show.value.rejected ? at(res.rejected_symbols) : undefined;
		const rt = show.value.rejected ? at(res.rejected_tags) : undefined;
		if (s) picked.value = { kind: 'symbol', rejected: false, item: s };
		else if (t) picked.value = { kind: 'tag', rejected: false, item: t };
		else if (rs) picked.value = { kind: 'symbol', rejected: true, item: rs };
		else if (rt) picked.value = { kind: 'tag', rejected: true, item: rt };
		if (picked.value?.kind === 'symbol') typedTag.value = picked.value.item.tag_override ?? '';
	}
	draw();
}

// -- review: false positives and missed symbols ---------------------------------
const centre = (b: Box): [number, number] => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];

/** Send one correction; show the corrected result and re-pick what was clicked. */
async function correct(body: ReviewAction, reselect: [number, number] | null) {
	const r = await sym.review(props.docId, props.page, body, props.runId ?? null);
	if (!r) return;
	result.value = r.result;
	if (r.symbol) {
		const s = r.result.symbols.find((x) => inside(centre(x.box), r.symbol!.box)) ?? r.symbol;
		picked.value = { kind: 'symbol', rejected: false, item: s };
		typedTag.value = s.tag_override ?? '';
		sym.message = s.tag ? `Added ${s.tag}.` : 'Added. No tag text was read for that symbol: type it in the side panel.';
	} else if (reselect) pick(reselect);
	else picked.value = null;
	if (props.runId) sheets.value = await sym.runSheets(props.runId);
	draw();
}

function reject() {
	const p = picked.value;
	if (!p || p.kind === 'test' || p.rejected) return;
	if (p.kind === 'symbol') {
		void correct({ action: 'reject', kind: 'symbol', box: p.item.box, template_id: p.item.template_id },
			p.item.origin === 'manual' ? null : centre(p.item.box));
	} else void correct({ action: 'reject', kind: 'tag', box: p.item.box, tag: p.item.tag }, centre(p.item.box));
}

function restore(kind: 'symbol' | 'tag', box: Box) {
	void correct({ action: 'restore', kind, box }, centre(box));
}

function removeManual(s: Symbol) {
	void correct({ action: 'reject', kind: 'symbol', box: s.box, template_id: s.template_id }, null);
}

function saveTag() {
	const p = picked.value;
	if (p?.kind !== 'symbol' || p.item.origin !== 'manual') return;
	void correct({ action: 'tag', box: p.item.box, tag: typedTag.value.trim() || null }, centre(p.item.box));
}

async function addAt(pt: [number, number]) {
	if (!addTemplate.value) sym.error = 'Pick the template of the missed symbol first.';
	else if (!result.value) sym.error = 'Analyse the page first.';
	else await correct({ action: 'add', template_id: addTemplate.value, x: pt[0], y: pt[1] }, null);
}

function select(kind: 'symbol' | 'tag', rejected: boolean, item: Symbol | FoundTag) {
	picked.value = (kind === 'symbol' ? { kind, rejected, item } : { kind, rejected, item }) as Pick;
	typedTag.value = kind === 'symbol' ? (item as Symbol).tag_override ?? '' : '';
	zoomTo(item.box);
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
	if (previewError.value) return;
	const rect = selection.value.map((v) => Math.round(v));
	const t = await sym.templateFromPage(props.docId, props.page, rect, newName.value || 'Symbol', trimOn.value);
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

function goSheet(i: number) {
	const sh = sheets.value[i];
	if (sh?.doc_id) emit('navigate', sh.doc_id, sh.page);
}

watch(() => [props.docId, props.page, drawing.value?.status], load);
watch(() => show.value.words, async (on) => {
	words.value = on ? await sym.pageWords(props.docId, props.page) : [];
	draw();
});
watch([show, exclusion, testHere, () => sym.templates], draw, { deep: true });
watch(mode, () => { selection.value = null; draw(); });
watch(selection, (b) => {
	if (!b) {
		clearTimeout(previewTimer);
		previewSeq++;
		preview.value = null;
		previewError.value = null;
	}
});
watch(trimOn, () => schedulePreview());
// The sidebar's "Draw on a drawing" opens the page ready to draw
function takePendingMode() {
	if (sym.pendingMode !== 'template') return;
	sym.pendingMode = null;
	mode.value = 'template';
	sym.message = 'Drag a box around one symbol. Adjust it with the handles, check the preview, then create the template.';
}
watch(() => sym.pendingMode, takePendingMode);

function onKey(e: KeyboardEvent) {
	if (!selection.value || dragging.value) return;
	const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
	if (e.key === 'Escape') {
		selection.value = null;
		draw();
	} else if (e.key === 'Enter' && !typing && mode.value === 'template') void createTemplate();
	else if (e.key === 'Enter' && !typing && mode.value === 'exclude') void addExclusion();
}
watch(libTemplates, (ts) => {
	if (!ts.some((t) => t.id === addTemplate.value)) addTemplate.value = ts[0]?.id ?? '';
}, { immediate: true });

let ro: ResizeObserver | null = null;
onMounted(() => {
	ro = new ResizeObserver(() => (img.value && scale ? draw() : fit()));
	if (host.value) ro.observe(host.value);
	window.addEventListener('keydown', onKey);
	takePendingMode();
	void load();
});
onBeforeUnmount(() => {
	ro?.disconnect();
	window.removeEventListener('keydown', onKey);
	clearTimeout(previewTimer);
});
</script>

<template>
	<section class="card sym-main sym-viewer">
		<div class="sym-toolbar">
			<strong class="name" :title="drawing?.file_name">{{ drawing?.file_name }}</strong>
			<span v-if="runId" class="row tight">
				<button type="button" class="secondary small" :disabled="sheetIndex <= 0" title="Previous page of this analysis" @click="goSheet(sheetIndex - 1)">‹</button>
				<select class="small" aria-label="Page of this analysis" :value="sheetIndex" @change="goSheet(Number(($event.target as HTMLSelectElement).value))">
					<option v-for="(sh, i) in sheets" :key="`${sh.doc_id}/${sh.page}`" :value="i" :disabled="!sh.doc_id">
						{{ sh.file_name }} p{{ sh.page }} · {{ sh.symbols }} symbols{{ sh.rejected || sh.added ? ` · ${sh.rejected + sh.added} corrected` : '' }}
					</option>
				</select>
				<button type="button" class="secondary small" :disabled="sheetIndex < 0 || sheetIndex >= sheets.length - 1" title="Next page of this analysis" @click="goSheet(sheetIndex + 1)">›</button>
			</span>
			<span v-else class="row tight">
				<button type="button" class="secondary small" :disabled="page <= 1" @click="goPage(page - 1)">‹</button>
				<span class="small">Page {{ page }} / {{ drawing?.pages.length ?? '?' }}</span>
				<button type="button" class="secondary small" :disabled="!drawing || page >= drawing.pages.length" @click="goPage(page + 1)">›</button>
			</span>
			<span class="seg">
				<button type="button" class="small" :class="mode === 'pan' ? '' : 'secondary'" title="Drag to pan, wheel to zoom, click a box to review it (reject a false positive)" @click="mode = 'pan'">Select</button>
				<button type="button" class="small" :class="mode === 'add' ? '' : 'secondary'" :disabled="!libTemplates.length || !result" title="Click on a symbol the analysis missed to add it" @click="mode = 'add'">Add missed</button>
				<button type="button" class="small" :class="mode === 'template' ? '' : 'secondary'" title="Drag a box around one symbol to make a template" @click="mode = 'template'">New template</button>
				<button type="button" class="small" :class="mode === 'exclude' ? '' : 'secondary'" title="Drag a box over the title block or notes: text there is ignored" @click="mode = 'exclude'">Ignore area</button>
			</span>
			<span class="row tight">
				<button type="button" class="secondary small" title="Zoom out" @click="zoomBy(1 / 1.4)">−</button>
				<button type="button" class="secondary small" title="Zoom in" @click="zoomBy(1.4)">+</button>
				<button type="button" class="secondary small" @click="fit">Fit</button>
			</span>
			<select v-if="mode === 'add'" v-model="addTemplate" class="small" aria-label="Template of the missed symbol" title="The symbol you'll click on">
				<option v-for="t in libTemplates" :key="t.id" :value="t.id">{{ t.desc }}</option>
			</select>
			<span class="spacer" />
			<button v-if="!runId" type="button" :disabled="sym.busy || drawing?.status !== 'ready'" @click="analyse">Analyse page</button>
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
			<div ref="host" class="sym-canvas-host" :class="[`mode-${mode}`, hoverHandle ? `handle-${hoverHandle}` : '']">
				<canvas ref="canvas" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @wheel.prevent="onWheel" @dblclick="fit" />
				<div v-if="selection && !dragging && mode === 'template'" class="sym-banner floating bottom">
					<div class="sym-preview" :title="preview ? 'What the template will be. Its text (yellow) is shown so you can put tag points on it; matching leaves the text out, so any tag matches' : ''">
						<svg v-if="preview" :viewBox="`0 0 ${preview.width} ${preview.height}`" role="img" aria-label="Template preview">
							<image :href="`data:image/png;base64,${preview.view_png || preview.png}`" :width="preview.width" :height="preview.height" />
							<rect v-for="(w, i) in preview.view_png ? preview.words : []" :key="i" :x="w.box[0]" :y="w.box[1]"
								:width="w.box[2] - w.box[0]" :height="w.box[3] - w.box[1]" fill="rgba(255, 235, 59, 0.4)" />
						</svg>
						<span v-else-if="!previewError" class="hint small">Preview…</span>
					</div>
					<div class="sym-preview-side">
						<span v-if="previewError" class="error small">{{ previewError }}</span>
						<span v-else-if="preview" class="small">New template: {{ preview.width }} × {{ preview.height }} px{{ trimOn ? ' after trimming' : '' }}.
							Drag the handles to adjust the box; Esc cancels.</span>
						<label class="check small" title="Shrink the box to the symbol's lines (green outline)"><input v-model="trimOn" type="checkbox" /> Trim to the linework</label>
						<div class="row tight">
							<input v-model="newName" placeholder="Name, e.g. Instrument bubble" aria-label="Template name" @keydown.enter="createTemplate" />
							<button type="button" class="small" :disabled="sym.busy || !!previewError" @click="createTemplate">Create template</button>
						</div>
					</div>
					<button type="button" class="secondary small" @click="selection = null; draw()">Cancel</button>
				</div>
				<div v-else-if="selection && !dragging && mode === 'exclude'" class="sym-banner floating bottom">
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
					<label class="check" title="A light yellow box on every piece of text read on the drawing"><input v-model="show.words" type="checkbox" /> Text</label>
					<label class="check"><input v-model="show.excluded" type="checkbox" /> Ignored areas</label>
					<label class="check" title="Detections marked as false positives (grey, crossed out)"><input v-model="show.rejected" type="checkbox" /> Rejected</label>
				</div>
				<p v-if="mode === 'add'" class="hint small sym-modehint">Click on a missed <strong>{{ libTemplates.find((t) => t.id === addTemplate)?.desc }}</strong>: the box snaps to the symbol and its tag is read.</p>
				<p v-else-if="result && !picked" class="hint small sym-modehint">Click a highlighted box to review it, or <strong>Add missed</strong> to add a symbol the analysis didn't find.</p>
				<div v-if="pickedInfo && picked" class="sym-picked" :class="{ rejected: picked.rejected }">
					<strong>{{ pickedInfo.title }}</strong>
					<span v-if="picked.rejected" class="chip small">false positive</span>
					<div v-for="l in pickedInfo.lines" :key="l" class="small">{{ l }}</div>
					<template v-if="picked.kind === 'symbol' && picked.item.origin === 'manual'">
						<div class="row tight">
							<input v-model="typedTag" class="grow" placeholder="Type the tag" aria-label="Tag" @keydown.enter="saveTag" />
							<button type="button" class="small" :disabled="sym.busy" @click="saveTag">Set tag</button>
						</div>
						<button type="button" class="secondary small" :disabled="sym.busy" @click="removeManual(picked.item)">Remove this symbol</button>
					</template>
					<button v-else-if="picked.kind !== 'test' && !picked.rejected" type="button" class="secondary small" :disabled="sym.busy" @click="reject">✕ Not a {{ picked.kind === 'tag' ? 'tag' : 'symbol' }} (false positive)</button>
					<button v-else-if="picked.kind !== 'test'" type="button" class="small" :disabled="sym.busy" @click="restore(picked.kind, picked.item.box)">Restore</button>
				</div>
				<template v-if="corrections">
					<h4>Corrections on this page</h4>
					<p class="hint small">Kept with the drawing: later analyses of this page apply them again.</p>
					<ul class="sym-taglist sym-corrections">
						<li v-for="(s, i) in result?.rejected_symbols ?? []" :key="`rs${i}`" @click="select('symbol', true, s)">
							<span class="tag strike">{{ s.tag ?? s.template_desc }}</span>
							<span class="src">rejected {{ s.template_desc }}</span>
							<button type="button" class="link small" title="Restore" @click.stop="restore('symbol', s.box)">undo</button>
						</li>
						<li v-for="(t, i) in result?.rejected_tags ?? []" :key="`rt${i}`" @click="select('tag', true, t)">
							<span class="tag strike">{{ t.tag }}</span>
							<span class="src">rejected text</span>
							<button type="button" class="link small" title="Restore" @click.stop="restore('tag', t.box)">undo</button>
						</li>
						<li v-for="(s, i) in manualSymbols" :key="`m${i}`" @click="select('symbol', false, s)">
							<span class="tag">+ {{ s.tag ?? '(no tag)' }}</span>
							<span class="src">added {{ s.template_desc }}</span>
							<button type="button" class="link small" title="Remove" @click.stop="removeManual(s)">undo</button>
						</li>
					</ul>
				</template>
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
