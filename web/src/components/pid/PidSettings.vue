<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { Settings } from '../../lib/pidTypes';
import { usePid } from '../../stores/pid';

const pid = usePid();
const draft = ref<Settings | null>(null);
const wordsText = ref<Record<string, string>>({});
const sample = ref('FT-1023  PV 101A  LIC1030  SHT-01');
const DEFAULT = '^(?P<function>[A-Z]{1,5})[- ]?(?P<loop>\\d{2,6})(?P<suffix>[A-Z]{0,2})$';

function reset() {
	draft.value = pid.settings ? JSON.parse(JSON.stringify(pid.settings)) : null;
	wordsText.value = Object.fromEntries(Object.entries(draft.value?.exclusions ?? {}).map(([k, v]) => [k, v.words.join(', ')]));
}
watch(() => pid.settings, reset, { immediate: true });

const dirty = computed(() => JSON.stringify(build()) !== JSON.stringify(pid.settings));

function build(): Settings | null {
	if (!draft.value) return null;
	const s: Settings = JSON.parse(JSON.stringify(draft.value));
	for (const [k, text] of Object.entries(wordsText.value)) {
		if (s.exclusions[k]) s.exclusions[k].words = text.split(/[,\n]+/).map((w) => w.trim()).filter(Boolean);
	}
	return s;
}

// Python named groups (?P<name>…) -> JS (?<name>…) for the live preview.
const tryResults = computed(() => {
	if (!draft.value) return [];
	let rx: RegExp;
	try {
		rx = new RegExp(draft.value.tag_pattern.replace(/\(\?P</g, '(?<'));
	} catch {
		return [{ text: '', ok: false, out: 'Not a valid pattern' }];
	}
	return sample.value.split(/\s{2,}|\t|,/).map((w) => w.trim()).filter(Boolean).map((text) => {
		const m = rx.exec(text.toUpperCase().replace(/\s/g, '')) ?? rx.exec(text);
		const g = m?.groups ?? {};
		return { text, ok: !!m, out: m ? `${g.function ?? ''}-${g.loop ?? ''}${g.suffix ?? ''}` : 'no match' };
	});
});

function removeArea(key: string, i: number) {
	draft.value!.exclusions[key].areas.splice(i, 1);
}

function removeLib(key: string) {
	delete draft.value!.exclusions[key];
	delete wordsText.value[key];
}

async function save() {
	const s = build();
	if (s) await pid.saveSettings(s);
}
</script>

<template>
	<section v-if="draft" class="card pid-main pid-settings">
		<div class="mel-head">
			<h3>Tag reading settings</h3>
			<span class="spacer" />
			<span v-if="dirty" class="unsaved">● Unsaved changes</span>
			<span v-else-if="pid.message" class="saved">✓ {{ pid.message }}</span>
			<button type="button" class="secondary" :disabled="!dirty" @click="reset">Discard</button>
			<button type="button" :disabled="!dirty || pid.busy" @click="save">Save</button>
		</div>
		<p v-if="pid.error" class="error">{{ pid.error }}</p>

		<h4>Tag pattern</h4>
		<p class="hint small">
			A regular expression for an instrument tag, with named groups <code>function</code>, <code>loop</code> and
			(optional) <code>suffix</code>. It splits template tags into parts and drives the text scan, which finds
			tags written as one word (<code>FT-1023</code>) or as letters stacked over a number inside a bubble.
		</p>
		<label class="field">
			<input v-model="draft.tag_pattern" class="mono" :class="{ invalid: pid.fieldErrors.tag_pattern }" aria-label="Tag pattern" />
			<span v-if="pid.fieldErrors.tag_pattern" class="warn small">{{ pid.fieldErrors.tag_pattern }}</span>
		</label>
		<div class="row tight wrap">
			<button type="button" class="link small" @click="draft.tag_pattern = DEFAULT">Use the default ISA pattern</button>
		</div>
		<label class="field">Try it (separate examples with two spaces or commas)
			<input v-model="sample" />
		</label>
		<div class="row tight wrap">
			<span v-for="r in tryResults" :key="r.text" class="chip" :class="r.ok ? 'ok' : 'muted'">{{ r.text }} → {{ r.out }}</span>
		</div>
		<div class="row tight wrap">
			<label class="check"><input v-model="draft.pattern_scan" type="checkbox" /> Scan all page text for tags (not only inside matched symbols)</label>
		</div>

		<h4>Scanned drawings</h4>
		<label class="field">Use OCR on a page when its PDF text layer has fewer than
			<span class="row tight"><input v-model.number="draft.min_pdf_words" type="number" min="0" class="num" /> words</span>
		</label>
		<p v-if="pid.ocr?.available" class="small">✓ {{ pid.ocr.engine }} is available.</p>
		<p v-else class="warn small">OCR is not available: {{ pid.ocr?.reason }}</p>

		<h4>Ignored text</h4>
		<p class="hint small">Per library. Draw areas on a page with <strong>Ignore area</strong>; they are stored as fractions of the sheet so one box fits every sheet of the same layout.</p>
		<p v-if="!Object.keys(draft.exclusions).length" class="hint small">Nothing is ignored yet.</p>
		<div v-for="(ex, key) in draft.exclusions" :key="key" class="pid-excl">
			<div class="row tight">
				<strong>{{ key }}</strong>
				<span class="spacer" />
				<button type="button" class="secondary small" @click="removeLib(String(key))">Remove all</button>
			</div>
			<label class="field">Words to ignore (comma separated)
				<input v-model="wordsText[key]" placeholder="e.g. NOTE, SHT, REV" />
			</label>
			<ul class="small">
				<li v-for="(a, i) in ex.areas" :key="i">
					Area {{ i + 1 }}: {{ Math.round(a[0] * 100) }}–{{ Math.round(a[2] * 100) }}% across,
					{{ Math.round(a[1] * 100) }}–{{ Math.round(a[3] * 100) }}% down
					<button type="button" class="link small" @click="removeArea(String(key), i)">remove</button>
				</li>
			</ul>
		</div>
	</section>
</template>
