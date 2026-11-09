<script setup lang="ts">
import { computed, ref } from 'vue';
import { useSymbols } from '../../stores/symbols';

const sym = useSymbols();
const lib = computed(() => sym.libraryDraft!);
const fe = computed(() => sym.fieldErrors);
const summary = computed(() => sym.libraries.find((l) => l.id === lib.value.id) ?? null);
const sample = ref('FT-1023  PV 101A  LIC1030  SHT-01');
const ISA = {
	pattern: '(?P<function>[A-Z]{1,5})[- ]?(?P<loop>\\d{2,6})(?P<suffix>[A-Z]{0,2})',
	format: '{function}-{loop}{suffix}',
};

// Python's (?P<name>…) -> JavaScript's (?<name>…), for the live preview only.
const jsRegex = computed(() => {
	try {
		return lib.value.tag_pattern.trim() ? new RegExp(`^(?:${lib.value.tag_pattern.replace(/\(\?P</g, '(?<')})$`) : null;
	} catch {
		return undefined;
	}
});
const groups = computed(() => [...lib.value.tag_pattern.matchAll(/\(\?P<([A-Za-z_][A-Za-z0-9_]*)>/g)].map((m) => m[1]));

function fmt(format: string, g: Record<string, string>): string {
	return format.replace(/\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}/g, (_, k: string) => g[k] ?? '');
}

const tryResults = computed(() => {
	const rx = jsRegex.value;
	if (rx === undefined) return [{ text: '', ok: false, out: 'Not a valid pattern' }];
	return sample.value.split(/\s{2,}|\t|,/).map((w) => w.trim()).filter(Boolean).map((text) => {
		if (!rx) return { text, ok: true, out: text };
		const m = rx.exec(text) ?? rx.exec(text.replace(/\s+/g, ''));
		if (!m) return { text, ok: false, out: 'no match' };
		const g = m.groups ?? {};
		return { text, ok: true, out: lib.value.tag_format.trim() ? fmt(lib.value.tag_format, g) : text };
	});
});

const wordsText = computed({
	get: () => lib.value.exclusion.words.join(', '),
	set: (v: string) => { lib.value.exclusion.words = v.split(/[,\n]+/).map((w) => w.trim()).filter(Boolean); },
});

function useIsa() {
	lib.value.tag_pattern = ISA.pattern;
	lib.value.tag_format = ISA.format;
}

function remove() {
	if (confirm(`Delete the library “${lib.value.name}” and its ${summary.value?.templates ?? 0} template(s)?`)) void sym.deleteLibrary(lib.value.id);
}

async function copy() {
	const name = prompt('Name for the copy', `${lib.value.name} (copy)`);
	if (name) await sym.createLibrary(name, lib.value.id);
}
</script>

<template>
	<section class="card sym-main sym-settings">
		<div class="mel-head">
			<input v-model="lib.name" class="name-input" aria-label="Library name" :class="{ invalid: fe.name }" />
			<span class="chip">{{ summary?.templates ?? 0 }} templates · {{ summary?.drawings ?? 0 }} drawings</span>
			<span class="spacer" />
			<span v-if="sym.libraryDirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="sym.message" class="saved">✓ {{ sym.message }}</span>
			<button type="button" class="secondary" :disabled="!sym.libraryDirty" @click="sym.discardLibrary()">Discard</button>
			<button type="button" :disabled="!sym.libraryDirty || sym.busy" @click="sym.saveLibrary()">Save</button>
		</div>
		<p v-if="sym.error" class="error">{{ sym.error }}</p>
		<p v-if="fe.name" class="warn small">{{ fe.name }}</p>

		<label class="field">Description
			<textarea v-model="lib.description" rows="2" placeholder="What drawings and symbols this library is for" />
		</label>

		<h4>Tags</h4>
		<p class="hint small">
			How a tag looks, as a regular expression. Named groups such as <code>(?P&lt;loop&gt;\d+)</code> become columns of
			the tags list, and the <em>format</em> writes every tag the same way, e.g. <code>{function}-{loop}</code>.
			Leave the pattern blank to take template tags exactly as written (and skip the text scan).
		</p>
		<label class="field">Tag pattern
			<input v-model="lib.tag_pattern" class="mono" :class="{ invalid: fe.tag_pattern || jsRegex === undefined }" placeholder="(blank: any text)" />
			<span v-if="fe.tag_pattern" class="warn small">{{ fe.tag_pattern }}</span>
			<span v-else-if="groups.length" class="hint small">Columns: {{ groups.join(', ') }}</span>
		</label>
		<label class="field">Tag format
			<input v-model="lib.tag_format" class="mono" :class="{ invalid: fe.tag_format }" placeholder="(blank: as found)" />
			<span v-if="fe.tag_format" class="warn small">{{ fe.tag_format }}</span>
		</label>
		<div class="row tight wrap">
			<button type="button" class="link small" @click="useIsa">Use the ISA instrument tag rules (FT-1023, TT-1026A)</button>
		</div>
		<label class="field">Try it (separate examples with two spaces or commas)
			<input v-model="sample" />
		</label>
		<div class="row tight wrap">
			<span v-for="r in tryResults" :key="r.text" class="chip" :class="r.ok ? 'ok' : 'muted'">{{ r.text }} → {{ r.out }}</span>
		</div>
		<div class="row tight wrap">
			<label class="check"><input v-model="lib.pattern_scan" type="checkbox" :disabled="!lib.tag_pattern.trim()" /> Also find tags anywhere in the page text</label>
			<label class="check"><input v-model="lib.scan_stacked" type="checkbox" :disabled="!lib.pattern_scan || !lib.tag_pattern.trim()" /> including two words stacked one above the other</label>
		</div>

		<h4>Matching</h4>
		<label class="field">Threshold for new templates <strong>{{ lib.default_threshold.toFixed(2) }}</strong>
			<input v-model.number="lib.default_threshold" type="range" min="0.4" max="1" step="0.01" />
			<span class="hint small">Each template has its own threshold, and any page can override it.</span>
		</label>

		<h4>Scanned drawings</h4>
		<label class="field">Use OCR on a page when its PDF text layer has fewer than
			<span class="row tight"><input v-model.number="lib.min_pdf_words" type="number" min="0" class="num" /> words</span>
		</label>
		<p v-if="sym.ocr?.available" class="small">✓ {{ sym.ocr.engine }} is available.</p>
		<p v-else class="warn small">OCR is not available: {{ sym.ocr?.reason }}</p>

		<h4>Ignored text</h4>
		<p class="hint small">Draw areas on a page with <strong>Ignore area</strong>; they are stored as fractions of the sheet, so one box fits every sheet of the same layout.</p>
		<label class="field">Words to ignore (comma separated)
			<input v-model="wordsText" placeholder="e.g. NOTE, SHT, REV" />
		</label>
		<ul v-if="lib.exclusion.areas.length" class="small">
			<li v-for="(a, i) in lib.exclusion.areas" :key="i">
				Area {{ i + 1 }}: {{ Math.round(a[0] * 100) }}–{{ Math.round(a[2] * 100) }}% across,
				{{ Math.round(a[1] * 100) }}–{{ Math.round(a[3] * 100) }}% down
				<button type="button" class="link small" @click="lib.exclusion.areas.splice(i, 1)">remove</button>
			</li>
		</ul>
		<p v-else class="hint small">No ignored areas.</p>

		<div class="row tight wrap danger-zone">
			<button type="button" class="secondary small" @click="sym.exportLibrary(lib.id)">Export…</button>
			<button type="button" class="secondary small" @click="copy">Copy…</button>
			<button type="button" class="secondary small" :disabled="!!summary?.drawings" :title="summary?.drawings ? 'Drawings use this library' : ''" @click="remove">Delete library</button>
		</div>
	</section>
</template>
