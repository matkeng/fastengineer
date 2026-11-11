<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Distribution Panels: the schedule of each distribution board. A panel is linked to a
// distribution panel of the Load List, whose loads are its circuits; each is put on a way
// (and, on a three-phase panel, a red, white or blue row) with its circuit breaker. The
// engine works out the schedule and the totals; this draws it as the switchboard or as a
// single line diagram.
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { newId } from '../../lib/genTypes';
import {
	KIND_NAMES, PHASE_NAMES, POLES, fmt, type DistributionPanel, type EntryKind, type PanelEntry, type PanelPhaseType, type PoleRow, type Pole,
} from '../../lib/panelTypes';
import { useKeyLists } from '../../stores/keylists';
import HistoryButton from '../audit/HistoryButton.vue';
import AppModal from '../common/AppModal.vue';
import PanelSld from './PanelSld.vue';
import SwitchboardGrid from './SwitchboardGrid.vue';

const g = useKeyLists();
const doc = computed(() => g.panelsDraft);
const view = computed(() => g.panelsView);
const panel = computed<DistributionPanel | null>(() => doc.value?.panels.find((p) => p.id === g.panelSelected) ?? doc.value?.panels[0] ?? null);
const schedule = computed(() => (panel.value ? view.value?.schedules[panel.value.id] ?? null : null));
const totals = computed(() => schedule.value?.totals ?? null);
const three = computed(() => panel.value?.phase_type === 'three-phase');
const errors = computed<Record<string, string>>(() => ({ ...(view.value?.errors ?? {}), ...g.fieldErrors }));
const errorList = computed(() => [...new Set(Object.values(errors.value))]);
const err = (id: string, field: string) => errors.value[`${id}.${field}`];
const unplacedOf = (p: DistributionPanel) => view.value?.schedules[p.id]?.unplaced.length ?? 0;

// the schedules and totals follow the edits
let timer: ReturnType<typeof setTimeout> | null = null;
watch(() => JSON.stringify(g.panelsDraft), () => {
	if (timer) clearTimeout(timer);
	timer = setTimeout(() => void g.checkPanels(), 300);
});
onBeforeUnmount(() => timer && clearTimeout(timer));

// -- panels ------------------------------------------------------------------------------------

const adding = ref<{ load_ref: string; tag: string; phase_type: PanelPhaseType; ways: number } | null>(null);
const freePanels = computed(() => (view.value?.load_panels ?? []).filter((c) => !doc.value?.panels.some((p) => p.load_ref === c.id)));
function startAdd() {
	adding.value = { load_ref: freePanels.value[0]?.id ?? '', tag: '', phase_type: 'three-phase', ways: 20 };
}
async function addPanel() {
	const a = adding.value;
	if (!a || !doc.value || (!a.load_ref && !a.tag.trim())) return;
	const linked = view.value?.load_panels.find((c) => c.id === a.load_ref);
	const p: DistributionPanel = {
		id: newId(), load_ref: a.load_ref || null, tag: linked ? linked.label.split(' – ')[0] : a.tag.trim(), title: '', phase_type: a.phase_type,
		view: 'switchboard', ways: a.ways, voltage: 240, power_factor: 0.85, isolator_rating: 250, upstream_cb: 250, entries: [], dividers: [],
	};
	doc.value.panels.push(p);
	g.panelSelected = p.id;
	adding.value = null;
	if (p.load_ref) await g.placePanelLoads(p.id); // its loads go on the first ways; they can be moved
}
function removePanel(p: DistributionPanel) {
	if (!doc.value || !window.confirm(`Delete the schedule of ${p.tag || 'this panel'}? The Load List is not changed.`)) return;
	doc.value.panels = doc.value.panels.filter((x) => x.id !== p.id);
	g.panelSelected = doc.value.panels[0]?.id ?? null;
}

/** Three-phase <-> single-phase, when no circuit would be lost. */
const phaseNote = ref('');
function setPhaseType(p: DistributionPanel, to: PanelPhaseType) {
	phaseNote.value = '';
	if (to === p.phase_type) return;
	if (to === 'single-phase') {
		const ways = new Set(p.entries.map((e) => e.way));
		if (p.entries.some((e) => e.poles === 3) || ways.size !== p.entries.length) {
			phaseNote.value = 'A single-phase panel has one circuit per way: first remove the three-pole circuits and leave one circuit on each way.';
			return;
		}
		for (const e of p.entries) e.pole = null;
	} else {
		for (const e of p.entries) e.pole = 'R';
	}
	p.phase_type = to;
}

// -- a circuit ---------------------------------------------------------------------------------

interface CircuitForm { id: string | null; kind: EntryKind; load_ref: string; way: number; pole: Pole; poles: 1 | 3; description: string; load_type: string }
const circuit = ref<CircuitForm | null>(null);
const loadChoices = computed(() => {
	const s = schedule.value;
	if (!s) return [];
	const out = s.unplaced.map((u) => ({ ref: u.ref, label: [u.tag, u.description].filter(Boolean).join(' – '), poles: u.poles }));
	const e = panel.value?.entries.find((x) => x.id === circuit.value?.id);
	const row = e && s.rows.find((r) => r.entry_id === e.id);
	if (e?.load_ref && row) out.unshift({ ref: e.load_ref, label: [row.tag, row.description].filter(Boolean).join(' – '), poles: e.poles });
	return out;
});
function editCircuit(r: PoleRow) {
	const p = panel.value;
	if (!p) return;
	const e = p.entries.find((x) => x.id === r.entry_id);
	const firstLoad = schedule.value?.unplaced[0];
	circuit.value = e
		? { id: e.id, kind: e.kind, load_ref: e.load_ref ?? '', way: e.way, pole: e.pole ?? 'R', poles: e.poles, description: e.description, load_type: e.load_type }
		: { id: null, kind: firstLoad ? 'load' : 'spare_cb', load_ref: firstLoad?.ref ?? '', way: r.way, pole: (r.pole || 'R') as Pole,
			poles: firstLoad && three.value && firstLoad.poles === 3 && r.pole === 'R' ? 3 : 1, description: '', load_type: '' };
}
function pickLoad() {
	const c = circuit.value;
	const choice = loadChoices.value.find((x) => x.ref === c?.load_ref);
	if (c && choice && !c.id && three.value) c.poles = choice.poles === 3 ? 3 : 1;
}
const circuitError = computed(() => {
	const c = circuit.value;
	const p = panel.value;
	if (!c || !p) return '';
	if (c.kind === 'load' && !c.load_ref) return 'Choose a load.';
	if (!(c.way >= 1 && c.way <= p.ways)) return `The panel has ways 1 to ${p.ways}.`;
	const cells = (way: number, pole: Pole | null, poles: number) => (poles === 3 ? POLES.map((x) => `${way}/${x}`) : [`${way}/${pole ?? ''}`]);
	const mine = cells(c.way, three.value ? c.pole : null, c.poles);
	const clash = p.entries.find((e) => e.id !== c.id && cells(e.way, e.pole, e.poles).some((x) => mine.includes(x)));
	return clash ? `Way ${c.way} already has a circuit there. Move or remove it first.` : '';
});
function applyCircuit() {
	const c = circuit.value;
	const p = panel.value;
	if (!c || !p || circuitError.value) return;
	const old = p.entries.find((e) => e.id === c.id);
	const poles = three.value ? c.poles : 1;
	const rows = Array.from({ length: poles }, (_, i) => old?.rows[i] ?? { cb_rating: old?.rows[0]?.cb_rating ?? null, qty: null, watts_each: null });
	const entry: PanelEntry = {
		id: old?.id ?? newId(), way: c.way, pole: three.value ? (poles === 3 ? 'R' : c.pole) : null, poles, kind: c.kind,
		load_ref: c.kind === 'load' ? c.load_ref : null, description: c.description.trim(), load_type: c.load_type.trim(), rows,
	};
	if (old) p.entries.splice(p.entries.indexOf(old), 1, entry);
	else p.entries.push(entry);
	circuit.value = null;
}
function removeCircuit() {
	const p = panel.value;
	if (p && circuit.value?.id) p.entries = p.entries.filter((e) => e.id !== circuit.value?.id);
	circuit.value = null;
}

// -- a heading across the schedule ---------------------------------------------------------------

const heading = ref<{ id: string | null; before_way: number; label: string } | null>(null);
const oddWays = computed(() => Array.from({ length: Math.ceil((panel.value?.ways ?? 0) / 2) }, (_, i) => 2 * i + 1));
function editHeading(beforeWay?: number) {
	const d = panel.value?.dividers.find((x) => x.before_way === beforeWay);
	heading.value = d ? { ...d } : { id: null, before_way: oddWays.value.find((w) => !panel.value?.dividers.some((x) => x.before_way === w)) ?? 1, label: '' };
}
function applyHeading(remove = false) {
	const h = heading.value;
	const p = panel.value;
	if (!h || !p) return;
	p.dividers = p.dividers.filter((d) => d.id !== h.id && d.before_way !== h.before_way);
	if (!remove && h.label.trim()) p.dividers.push({ id: h.id ?? newId(), before_way: h.before_way, label: h.label.trim() });
	heading.value = null;
}
</script>

<template>
	<section class="card wizard ref-editor gen-hw key-plc key-dp">
		<div class="mel-head">
			<span class="kind tree">Key list</span>
			<h2 class="key-title">Distribution Panels</h2>
			<span class="hint small">Each panel's schedule. Its circuits are the Load List rows supplied from it.</span>
			<span class="spacer" />
			<span v-if="g.message" class="saved">✓ {{ g.message }}</span>
			<span v-if="g.panelsDirty" class="unsaved">● Unsaved</span>
			<HistoryButton entity="distribution_panels" record-id="distribution-panels" label="Distribution Panels" />
			<button type="button" class="secondary" :disabled="!g.panelsDirty || g.busy" @click="g.discard()">Discard</button>
			<button type="button" :disabled="!g.panelsDirty || g.busy || errorList.length > 0" @click="g.savePanels()">Save</button>
		</div>
		<p v-if="g.error" class="error">{{ g.error }}</p>

		<div v-if="doc" class="hw-layout">
			<aside class="tpl-list">
				<ul>
					<li v-for="p in doc.panels" :key="p.id" :class="{ on: panel?.id === p.id, bad: err(p.id, 'tag') || err(p.id, 'load_ref') }" @click="g.panelSelected = p.id">
						<strong>{{ p.tag || '(no tag)' }}</strong>
						<span class="desc">{{ view?.schedules[p.id]?.title ?? p.title }}</span>
						<span class="meta">{{ p.phase_type === 'three-phase' ? '3ϕ' : '1ϕ' }} · {{ p.ways }} ways<template v-if="unplacedOf(p)"> · <span class="warnText">{{ unplacedOf(p) }} to place</span></template></span>
					</li>
					<li v-if="!doc.panels.length" class="none"><span class="desc">No panels yet.</span></li>
				</ul>
				<div class="row"><button type="button" class="secondary small" @click="startAdd">+ Panel</button></div>
			</aside>

			<section v-if="panel" class="hw-main">
				<!-- the header block of the schedule -->
				<div class="dp-head">
					<div class="dp-title">
						<label>Panel
							<input v-model="panel.tag" class="mono" :readonly="!!panel.load_ref" :class="{ invalid: err(panel.id, 'tag') }"
								:title="err(panel.id, 'tag') ?? (panel.load_ref ? 'The tag of the Load List row it is linked to' : '')" aria-label="Panel tag" />
						</label>
						<label class="grow">Title <input v-model="panel.title" :placeholder="schedule?.title ?? ''" aria-label="Panel title" /></label>
						<label>Type
							<select :value="panel.phase_type" aria-label="Phase type" @change="setPhaseType(panel, ($event.target as HTMLSelectElement).value as PanelPhaseType)">
								<option value="three-phase">Three-phase</option>
								<option value="single-phase">Single-phase</option>
							</select>
						</label>
						<label>Ways <input v-model.number="panel.ways" type="number" min="2" max="96" step="2" class="num" :class="{ invalid: err(panel.id, 'ways') }" :title="err(panel.id, 'ways') ?? ''" /></label>
						<button type="button" class="secondary small" @click="removePanel(panel)">Delete panel</button>
					</div>
					<p v-if="phaseNote" class="warn small">{{ phaseNote }}</p>
					<div class="dp-figures">
						<table class="dp-box">
							<tbody>
								<tr><th>Single Phase Voltage</th><td><input v-model.number="panel.voltage" type="number" min="0" step="any" :class="{ invalid: err(panel.id, 'voltage') }" aria-label="Single phase voltage" /></td></tr>
								<tr><th>Power Factor</th><td><input v-model.number="panel.power_factor" type="number" min="0" max="1" step="0.01" :class="{ invalid: err(panel.id, 'power_factor') }" aria-label="Power factor" /></td></tr>
								<tr><th>Isolator &amp; Chassis Rating (Amps)</th><td><input v-model.number="panel.isolator_rating" type="number" min="0" step="any" :class="{ invalid: err(panel.id, 'isolator_rating') }" aria-label="Isolator and chassis rating" /></td></tr>
								<tr><th>Upstream CB Size (Min)</th><td><input v-model.number="panel.upstream_cb" type="number" min="0" step="any" :class="{ invalid: err(panel.id, 'upstream_cb') }" aria-label="Upstream CB size" /></td></tr>
							</tbody>
						</table>
						<table v-if="totals" class="dp-box calc">
							<tbody>
								<tr><th>Maximum Amp</th><td>{{ fmt(totals.max_amps) }}</td></tr>
								<tr><th>{{ three ? '3PH kW' : 'Total kW' }}</th><td>{{ fmt(totals.total_kw, 2) }}</td></tr>
								<tr><th>Remaining Capacity (Amps)</th><td :class="{ over: totals.remaining_amps < 0 }">{{ fmt(totals.remaining_amps) }}</td></tr>
								<tr><th>Remaining Capacity %</th><td :class="{ over: totals.remaining_amps < 0 }">{{ totals.remaining_pct === null ? '' : `${fmt(totals.remaining_pct)}%` }}</td></tr>
								<tr><th>Maximum kVA Rating</th><td>{{ fmt(totals.max_kva) }}</td></tr>
							</tbody>
						</table>
						<table v-if="totals" class="dp-box phases">
							<tbody>
								<tr><th>kVA</th><td v-for="(p, i) in totals.phases" :key="p" :class="p ? `ph-${p}` : ''" :title="PHASE_NAMES[p]">{{ fmt(totals.phase_kva[i], 2) }}</td></tr>
								<tr><th>Amps</th><td v-for="(p, i) in totals.phases" :key="p">{{ fmt(totals.phase_amps[i]) }}</td></tr>
							</tbody>
						</table>
					</div>
				</div>

				<div class="row dp-tools">
					<div class="seg">
						<button type="button" :class="panel.view === 'switchboard' ? '' : 'secondary'" @click="panel.view = 'switchboard'">Switchboard</button>
						<button type="button" :class="panel.view === 'sld' ? '' : 'secondary'" @click="panel.view = 'sld'">Single line diagram</button>
					</div>
					<button type="button" class="secondary small" @click="editHeading()">+ Heading</button>
					<template v-if="schedule?.unplaced.length">
						<span class="warnText small">{{ schedule.unplaced.length }} load(s) to place:</span>
						<span class="hint small">{{ schedule.unplaced.slice(0, 6).map((u) => u.tag).join(', ') }}{{ schedule.unplaced.length > 6 ? '…' : '' }}</span>
						<button type="button" class="secondary small" :disabled="g.busy" title="Put them on the first free ways" @click="g.placePanelLoads(panel.id)">Place all</button>
					</template>
				</div>

				<template v-if="schedule">
					<SwitchboardGrid v-if="panel.view === 'switchboard'" :panel="panel" :schedule="schedule" :cb-ratings="view?.cb_ratings ?? []" :errors="errors"
						@edit="editCircuit" @divider="editHeading" />
					<PanelSld v-else :panel="panel" :schedule="schedule" />
				</template>

				<ul v-if="errorList.length || schedule?.findings.length" class="warn-list hw-findings">
					<li v-for="m in errorList" :key="m" class="error"><strong>Fix before saving:</strong> {{ m }}</li>
					<li v-for="m in schedule?.findings ?? []" :key="m">{{ m }}</li>
				</ul>
			</section>
			<section v-else class="hw-main">
				<p class="hint">Add a panel to start its schedule. Pick one of the Load List's distribution panels and its loads are placed on the ways for you.</p>
			</section>
		</div>

		<AppModal :open="!!adding" title="New distribution panel" @close="adding = null">
			<form v-if="adding" class="form-grid two-col" @submit.prevent="addPanel">
				<label class="field wide">
					<span>Distribution panel of the Load List</span>
					<select v-model="adding.load_ref">
						<option v-for="c in freePanels" :key="c.id" :value="c.id">{{ c.label }}</option>
						<option value="">Not in the Load List (circuits typed in)</option>
					</select>
				</label>
				<label v-if="!adding.load_ref" class="field wide">
					<span>Tag<span class="req"> *</span></span>
					<input v-model="adding.tag" type="text" class="mono" placeholder="2236-DP3310" />
				</label>
				<label class="field">
					<span>Type</span>
					<select v-model="adding.phase_type">
						<option value="three-phase">Three-phase</option>
						<option value="single-phase">Single-phase</option>
					</select>
				</label>
				<label class="field">
					<span>Ways</span>
					<input v-model.number="adding.ways" type="number" min="2" max="96" step="2" />
				</label>
				<button type="submit" hidden />
			</form>
			<template #footer>
				<span class="spacer" />
				<button type="button" class="secondary" @click="adding = null">Cancel</button>
				<button type="button" :disabled="!adding || (!adding.load_ref && !adding.tag.trim())" @click="addPanel">Add</button>
			</template>
		</AppModal>

		<AppModal :open="!!circuit" :title="circuit?.id ? 'Circuit' : 'New circuit'" @close="circuit = null">
			<form v-if="circuit && panel" class="form-grid two-col" @submit.prevent="applyCircuit">
				<label class="field wide">
					<span>What is on it</span>
					<select v-model="circuit.kind">
						<option v-for="(name, k) in KIND_NAMES" :key="k" :value="k" :disabled="k === 'load' && !loadChoices.length">{{ name }}</option>
					</select>
				</label>
				<label v-if="circuit.kind === 'load'" class="field wide">
					<span>Load<span class="req"> *</span></span>
					<select v-model="circuit.load_ref" @change="pickLoad">
						<option v-for="c in loadChoices" :key="c.ref" :value="c.ref">{{ c.label }}{{ c.poles === 3 ? ' (3ϕ)' : '' }}</option>
					</select>
				</label>
				<label class="field">
					<span>Way</span>
					<input v-model.number="circuit.way" type="number" min="1" :max="panel.ways" />
				</label>
				<label v-if="three" class="field">
					<span>Poles</span>
					<select v-model.number="circuit.poles">
						<option :value="1">1 pole</option>
						<option :value="3">3 poles (red, white and blue)</option>
					</select>
				</label>
				<label v-if="three && circuit.poles === 1" class="field">
					<span>Phase</span>
					<select v-model="circuit.pole">
						<option v-for="p in POLES" :key="p" :value="p">{{ PHASE_NAMES[p] }}</option>
					</select>
				</label>
				<label class="field wide">
					<span>Description</span>
					<input v-model="circuit.description" type="text" :placeholder="circuit.kind === 'load' ? 'The load\'s description' : ''" />
				</label>
				<label class="field wide">
					<span>Load type</span>
					<input v-model="circuit.load_type" type="text" :placeholder="circuit.kind === 'load' ? 'The load\'s load type' : view?.kinds[circuit.kind] ?? ''" />
				</label>
				<button type="submit" hidden />
			</form>
			<p v-if="circuitError" class="warn small">{{ circuitError }}</p>
			<p class="hint small">Quantity, watts and the CB rating are typed on the schedule, a row for each pole.</p>
			<template #footer>
				<button v-if="circuit?.id" type="button" class="secondary" @click="removeCircuit">Remove from the panel</button>
				<span class="spacer" />
				<button type="button" class="secondary" @click="circuit = null">Cancel</button>
				<button type="button" :disabled="!!circuitError" @click="applyCircuit">OK</button>
			</template>
		</AppModal>

		<AppModal :open="!!heading" title="Heading" @close="heading = null">
			<form v-if="heading" class="form-grid two-col" @submit.prevent="applyHeading()">
				<label class="field wide">
					<span>Text</span>
					<input v-model="heading.label" type="text" placeholder="Lighting Contactor" />
				</label>
				<label class="field">
					<span>Above way</span>
					<select v-model.number="heading.before_way">
						<option v-for="w in oddWays" :key="w" :value="w">{{ w }} and {{ w + 1 }}</option>
					</select>
				</label>
				<button type="submit" hidden />
			</form>
			<p class="hint small">A heading runs across the schedule; the ways below it are shown under it (e.g. the circuits behind a lighting contactor).</p>
			<template #footer>
				<button v-if="heading?.id" type="button" class="secondary" @click="applyHeading(true)">Remove</button>
				<span class="spacer" />
				<button type="button" class="secondary" @click="heading = null">Cancel</button>
				<button type="button" :disabled="!heading?.label.trim()" @click="applyHeading()">OK</button>
			</template>
		</AppModal>
	</section>
</template>
