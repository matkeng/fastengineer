<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// PLC hardware register: panels -> racks -> slots -> cards, and the shared catalogue of
// rack and card types (Network, DI, DO, AI, AO, RTD in 8 / 12 / 16 / 32 channel variants).
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
	CARD_KINDS, type Card, type CardKind, type CardType, type Panel, type Rack, asTyped, cellText, newId,
} from '../../lib/genTypes';
import { useGenerators } from '../../stores/generators';
import EditGrid, { type CellEdit, type GridColumn } from '../common/EditGrid.vue';

const g = useGenerators();
const view = ref<'racks' | 'types'>('racks');
const panelId = ref<string | null>(null);
const sel = ref<{ rack: string; slot: number } | null>(null);
const addType = ref('');

const hw = computed(() => g.hwDraft);
const cat = computed(() => g.catDraft ?? g.hwView?.catalogue ?? null);
const cardTypes = computed(() => cat.value?.card_types ?? []);
const rackTypes = computed(() => cat.value?.rack_types ?? []);
const typeOf = (id: string) => cardTypes.value.find((t) => t.id === id);
const panel = computed<Panel | null>(() => hw.value?.panels.find((p) => p.id === panelId.value) ?? hw.value?.panels[0] ?? null);
const byKind = computed(() => CARD_KINDS.map((k) => ({ kind: k, types: cardTypes.value.filter((t) => t.kind === k) })).filter((x) => x.types.length));
const typeLabel = (t: CardType) => `${t.kind}${t.channels ? ` ${t.channels}` : ''}${t.part_number ? ` · ${t.part_number}` : ''}${t.description && !t.part_number ? ` · ${t.description}` : ''}`;
const rackLabel = (id: string) => {
	const t = rackTypes.value.find((r) => r.id === id);
	return t ? (t.part_number || t.description || 'Rack') + (t.max_slots ? ` (${t.max_slots} slots)` : '') : 'unknown type';
};

onMounted(async () => {
	if (!g.hwDraft) await g.loadHardware();
	panelId.value = g.hwDraft?.panels[0]?.id ?? null;
	addType.value = cardTypes.value.find((t) => t.kind === 'DI')?.id ?? cardTypes.value[0]?.id ?? '';
});

// live findings and totals while editing
let timer: ReturnType<typeof setTimeout> | null = null;
watch(() => JSON.stringify(g.hwDraft), () => {
	if (timer) clearTimeout(timer);
	timer = setTimeout(() => void g.checkHardware(), 300);
});
onBeforeUnmount(() => timer && clearTimeout(timer));

// -- panels, racks, cards -----------------------------------------------------------------

function addPanel() {
	if (!hw.value) return;
	const n = hw.value.panels.length + 1;
	const p: Panel = { id: newId(), tag: `PANEL${n}`, description: '', location: '', racks: [] };
	hw.value.panels.push(p);
	panelId.value = p.id;
	addRack();
}

function removePanel(p: Panel) {
	const cards = p.racks.reduce((a, r) => a + r.cards.filter(Boolean).length, 0);
	if (!confirm(`Delete panel ${p.tag}${cards ? ` and its ${cards} card(s)` : ''}?`)) return;
	hw.value!.panels = hw.value!.panels.filter((x) => x.id !== p.id);
	panelId.value = hw.value!.panels[0]?.id ?? null;
}

function addRack() {
	const p = panel.value;
	if (!p) return;
	const number = Math.max(0, ...p.racks.map((r) => r.number)) + 1;
	const net = cardTypes.value.find((t) => t.kind === 'Network');
	p.racks.push({
		id: newId(), number, rack_type_id: rackTypes.value[0]?.id ?? '', description: '', first_slot: 1,
		cards: net ? [{ id: newId(), card_type_id: net.id, tag: '', spare: false, notes: '' }] : [],
	});
}

function removeRack(r: Rack) {
	const n = r.cards.filter(Boolean).length;
	if (n && !confirm(`Delete rack ${r.number} and its ${n} card(s)?`)) return;
	panel.value!.racks = panel.value!.racks.filter((x) => x.id !== r.id);
	sel.value = null;
}

function maxSlots(r: Rack) {
	return rackTypes.value.find((t) => t.id === r.rack_type_id)?.max_slots ?? null;
}

function addCard(r: Rack, typeId = addType.value) {
	if (!typeId) return;
	const card: Card = { id: newId(), card_type_id: typeId, tag: '', spare: false, notes: '' };
	const empty = r.cards.findIndex((c) => c === null);
	if (empty >= 0) r.cards[empty] = card;
	else r.cards.push(card);
	sel.value = { rack: r.id, slot: empty >= 0 ? empty : r.cards.length - 1 };
}

const selRack = computed(() => panel.value?.racks.find((r) => r.id === sel.value?.rack) ?? null);
const selCard = computed(() => (selRack.value && sel.value ? selRack.value.cards[sel.value.slot] ?? null : null));

function clickSlot(r: Rack, i: number) {
	sel.value = { rack: r.id, slot: i };
	if (!r.cards[i]) addCard(r);
}

function moveCard(d: -1 | 1) {
	const r = selRack.value;
	if (!r || !sel.value) return;
	const i = sel.value.slot;
	const j = i + d;
	if (j < 0) return;
	while (r.cards.length <= j) r.cards.push(null);
	[r.cards[i], r.cards[j]] = [r.cards[j], r.cards[i]];
	sel.value = { rack: r.id, slot: j };
	trimEnd(r);
}

function removeCard(leaveEmpty: boolean) {
	const r = selRack.value;
	if (!r || !sel.value) return;
	if (leaveEmpty) r.cards[sel.value.slot] = null;
	else r.cards.splice(sel.value.slot, 1);
	trimEnd(r);
	sel.value = null;
}

function insertEmpty() {
	const r = selRack.value;
	if (!r || !sel.value) return;
	r.cards.splice(sel.value.slot, 0, null);
	sel.value = { rack: r.id, slot: sel.value.slot + 1 };
}

function trimEnd(r: Rack) {
	while (r.cards.length && r.cards[r.cards.length - 1] === null) r.cards.pop();
}

const cardName = (p: Panel, r: Rack, i: number, c: Card) => c.tag.trim() || `${p.tag}-R${r.number}-S${r.first_slot + i}`;
const rackChannels = (r: Rack) => {
	const out: Partial<Record<CardKind, number>> = {};
	for (const c of r.cards) {
		const t = c ? typeOf(c.card_type_id) : undefined;
		if (t && t.kind !== 'Network') out[t.kind] = (out[t.kind] ?? 0) + t.channels;
	}
	return Object.entries(out).map(([k, n]) => `${k} ${n}`).join(' · ') || 'no IO';
};
const slotsShown = (r: Rack) => {
	const max = maxSlots(r);
	return Math.max(r.cards.length + (max === null || r.cards.length < max ? 1 : 0), max ?? 0);
};

const findings = computed(() => g.hwView?.findings ?? []);
const summary = computed(() => g.hwView?.summary ?? null);

// -- catalogue (types) ------------------------------------------------------------------

const cardCols: GridColumn[] = [
	{ label: 'Kind', options: CARD_KINDS, width: 90 },
	{ label: 'Channels', width: 80 },
	{ label: 'Part number', width: 150 },
	{ label: 'Description', width: 260 },
	{ label: 'Wiring', width: 110, options: ['2-wire', '4-wire', '2/3/4-wire'] },
];
const cardCells = computed(() => cardTypes.value.map((t) => [t.kind, cellText(t.channels), t.part_number, t.description, t.wiring]));
function setCard(edits: CellEdit[]) {
	for (const e of edits) {
		const t = cardTypes.value[e.r];
		if (!t) continue;
		if (e.c === 0) {
			const k = CARD_KINDS.find((x) => x.toLowerCase() === e.value.trim().toLowerCase());
			if (k) t.kind = k;
		} else if (e.c === 1) {
			const n = asTyped(e.value);
			t.channels = typeof n === 'number' && n >= 0 ? Math.round(n) : 0;
		} else if (e.c === 2) t.part_number = e.value;
		else if (e.c === 3) t.description = e.value;
		else t.wiring = e.value;
	}
}
function insertCardTypes(at: number, n: number) {
	cat.value?.card_types.splice(at, 0, ...Array.from({ length: n }, () => ({
		id: newId(), kind: 'DI' as CardKind, channels: 16, part_number: '', description: '', wiring: '',
	})));
}
const used = computed(() => {
	const s = new Set<string>();
	for (const p of g.hwSaved?.panels ?? []) for (const r of p.racks) {
		s.add(r.rack_type_id);
		for (const c of r.cards) if (c) s.add(c.card_type_id);
	}
	return s;
});
function removeTypes(list: 'card_types' | 'rack_types', idx: number[]) {
	if (!cat.value) return;
	const arr = cat.value[list] as { id: string }[];
	const blocked = idx.filter((i) => used.value.has(arr[i]?.id));
	if (blocked.length) {
		alert(`${blocked.length} of these types are used in a saved rack and can't be removed.`);
		return;
	}
	const drop = new Set(idx);
	(cat.value[list] as { id: string }[]) = arr.filter((_, i) => !drop.has(i));
}

const rackCols: GridColumn[] = [
	{ label: 'Part number', width: 160 },
	{ label: 'Description', width: 280 },
	{ label: 'Max slots', width: 90, title: 'Blank: as many cards as needed (modular rack)' },
];
const rackCells = computed(() => rackTypes.value.map((t) => [t.part_number, t.description, t.max_slots === null ? '' : String(t.max_slots)]));
function setRack(edits: CellEdit[]) {
	for (const e of edits) {
		const t = rackTypes.value[e.r];
		if (!t) continue;
		if (e.c === 0) t.part_number = e.value;
		else if (e.c === 1) t.description = e.value;
		else {
			const n = asTyped(e.value);
			t.max_slots = typeof n === 'number' && n >= 1 ? Math.round(n) : null;
		}
	}
}
function insertRackTypes(at: number, n: number) {
	cat.value?.rack_types.splice(at, 0, ...Array.from({ length: n }, () => ({ id: newId(), part_number: '', description: '', max_slots: null })));
}
</script>

<template>
	<div class="gen-panel gen-hw">
		<div class="row">
			<nav class="subtabs small inline">
				<button type="button" :class="{ active: view === 'racks' }" @click="view = 'racks'">Panels, racks &amp; cards</button>
				<button type="button" :class="{ active: view === 'types' }" @click="view = 'types'">
					Card &amp; rack types<span v-if="g.catDirty" class="count bad">●</span>
				</button>
			</nav>
			<template v-if="summary && view === 'racks'">
				<span class="chip"><strong>{{ summary.panels }}</strong> panels</span>
				<span class="chip"><strong>{{ summary.racks }}</strong> racks</span>
				<span class="chip"><strong>{{ summary.cards }}</strong> cards</span>
				<span v-for="k in summary.by_kind.filter((x) => x.kind !== 'Network')" :key="k.kind" class="chip" :class="`kind-${k.kind}`">
					{{ k.kind }} {{ k.channels }} ch<span v-if="k.spare_cards"> ({{ k.spare_cards }} spare)</span>
				</span>
			</template>
			<span class="spacer" />
			<template v-if="view === 'racks'">
				<span v-if="g.hwDirty" class="unsaved">● Unsaved</span>
				<button type="button" class="secondary" :disabled="!g.hwDirty || g.busy" @click="g.discardHardware()">Discard</button>
				<button type="button" :disabled="!g.hwDirty || g.busy" @click="g.saveHardware()">Save hardware</button>
				<button type="button" class="secondary" :disabled="g.hwDirty || !summary?.cards" title="Saved register as a card schedule" @click="g.exportHardware('xlsx')">Export .xlsx</button>
			</template>
			<template v-else>
				<button type="button" class="secondary" :disabled="g.busy" @click="g.addDefaultTypes()">Add missing default types</button>
				<button type="button" class="secondary" :disabled="!g.catDirty || g.busy" @click="g.discardCatalogue()">Discard</button>
				<button type="button" :disabled="!g.catDirty || g.busy" @click="g.saveCatalogue()">Save types</button>
			</template>
		</div>

		<!-- panels, racks and cards -->
		<div v-if="view === 'racks' && hw" class="hw-layout">
			<aside class="tpl-list">
				<ul>
					<li v-for="p in hw.panels" :key="p.id" :class="{ on: panel?.id === p.id }" @click="panelId = p.id; sel = null">
						<strong>{{ p.tag || '(no tag)' }}</strong>
						<span class="desc">{{ p.description }}</span>
						<span class="meta">{{ p.racks.length }} rack{{ p.racks.length === 1 ? '' : 's' }} · {{ p.racks.reduce((a, r) => a + r.cards.filter(Boolean).length, 0) }} cards</span>
					</li>
				</ul>
				<div class="row"><button type="button" class="secondary small" @click="addPanel">+ Panel</button></div>
			</aside>

			<section v-if="panel" class="hw-main">
				<div class="row hw-panel-fields">
					<label>Panel tag <input v-model="panel.tag" aria-label="Panel tag" /></label>
					<label>Description <input v-model="panel.description" class="wide" /></label>
					<label>Location <input v-model="panel.location" /></label>
					<span class="spacer" />
					<button type="button" class="secondary small" @click="removePanel(panel)">Delete panel</button>
				</div>

				<div v-for="r in panel.racks" :key="r.id" class="hw-rack">
					<div class="row rack-head">
						<label>Rack <input v-model.number="r.number" type="number" min="1" class="num" /></label>
						<label>Type
							<select v-model="r.rack_type_id">
								<option v-for="t in rackTypes" :key="t.id" :value="t.id">{{ rackLabel(t.id) }}</option>
							</select>
						</label>
						<label>First slot <input v-model.number="r.first_slot" type="number" min="0" class="num" /></label>
						<input v-model="r.description" placeholder="Rack description" aria-label="Rack description" />
						<span class="hint">{{ rackChannels(r) }}</span>
						<span class="spacer" />
						<button type="button" class="secondary small" @click="removeRack(r)">Delete rack</button>
					</div>
					<div class="slots" role="list">
						<button
							v-for="i in slotsShown(r)"
							:key="i"
							type="button"
							role="listitem"
							class="slot"
							:class="[r.cards[i - 1] ? `kind-${typeOf(r.cards[i - 1]!.card_type_id)?.kind ?? 'unknown'}` : 'empty',
								{ on: sel?.rack === r.id && sel.slot === i - 1, spare: r.cards[i - 1]?.spare, over: maxSlots(r) !== null && i > maxSlots(r)! }]"
							:title="r.cards[i - 1] ? cardName(panel, r, i - 1, r.cards[i - 1]!) : 'Empty slot: click to add a card'"
							@click="clickSlot(r, i - 1)"
						>
							<span class="slot-no">{{ r.first_slot + i - 1 }}</span>
							<template v-if="r.cards[i - 1]">
								<span class="slot-kind">{{ typeOf(r.cards[i - 1]!.card_type_id)?.kind ?? '?' }}</span>
								<span class="slot-ch">{{ typeOf(r.cards[i - 1]!.card_type_id)?.channels || '' }}</span>
								<span class="slot-pn">{{ typeOf(r.cards[i - 1]!.card_type_id)?.part_number }}</span>
							</template>
							<span v-else class="slot-add">+</span>
						</button>
					</div>
					<div v-if="sel?.rack === r.id && selCard" class="card-edit">
						<strong>{{ cardName(panel, r, sel.slot, selCard) }}</strong>
						<label>Card type
							<select v-model="selCard.card_type_id">
								<optgroup v-for="k in byKind" :key="k.kind" :label="k.kind">
									<option v-for="t in k.types" :key="t.id" :value="t.id">{{ typeLabel(t) }}</option>
								</optgroup>
							</select>
						</label>
						<label>Name <input v-model="selCard.tag" :placeholder="`${panel.tag}-R${r.number}-S${r.first_slot + sel.slot}`" /></label>
						<label class="check"><input v-model="selCard.spare" type="checkbox" /> Spare</label>
						<label>Notes <input v-model="selCard.notes" class="wide" /></label>
						<span class="row">
							<button type="button" class="secondary small" :disabled="sel.slot === 0" title="Move one slot left" @click="moveCard(-1)">◀</button>
							<button type="button" class="secondary small" title="Move one slot right" @click="moveCard(1)">▶</button>
							<button type="button" class="secondary small" title="Shift this and later cards right" @click="insertEmpty">Insert empty slot</button>
							<button type="button" class="secondary small" @click="removeCard(true)">Remove (leave slot empty)</button>
							<button type="button" class="secondary small" @click="removeCard(false)">Remove and close gap</button>
						</span>
					</div>
				</div>
				<div class="row">
					<button type="button" class="secondary small" @click="addRack">+ Rack</button>
					<template v-if="panel.racks.length">
						<span class="hint">Add a card to the last rack:</span>
						<select v-model="addType" aria-label="Card type to add">
							<optgroup v-for="k in byKind" :key="k.kind" :label="k.kind">
								<option v-for="t in k.types" :key="t.id" :value="t.id">{{ typeLabel(t) }}</option>
							</optgroup>
						</select>
						<button type="button" class="secondary small" @click="addCard(panel.racks[panel.racks.length - 1])">+ Card</button>
					</template>
				</div>

				<ul v-if="findings.length" class="warn-list hw-findings">
					<li v-for="(f, i) in findings" :key="i" :class="f.severity.toLowerCase()"><strong>{{ f.item }}</strong> {{ f.detail }}</li>
				</ul>

				<div v-if="summary?.demand.length" class="hw-demand">
					<strong>Channels against the latest IO list build</strong> <span class="hint">(by the {{ summary.demand_column }} column, matched to card part numbers)</span>
					<table class="grid simple">
						<thead><tr><th>{{ summary.demand_column }}</th><th>Kind</th><th>IO points</th><th>Channels installed</th><th>Free</th></tr></thead>
						<tbody>
							<tr v-for="d in summary.demand" :key="d.card_type">
								<td>{{ d.card_type }}</td>
								<td>{{ d.kind ?? '– no card type with this part number' }}</td>
								<td>{{ d.points }}</td>
								<td>{{ d.channels }}</td>
								<td :class="{ bad: d.free < 0 }">{{ d.free }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</section>
			<p v-else class="hint">No panels yet. Use + Panel to add a PLC panel, then racks and cards.</p>
		</div>

		<!-- catalogue -->
		<div v-else-if="view === 'types' && cat" class="hw-types">
			<p class="hint">
				Types are shared by every generator. Fill in the part numbers you use: the IO list's card type column is
				matched to them to show channels against IO points. Types used in a saved rack can't be removed.
			</p>
			<h4>Card types</h4>
			<EditGrid :columns="cardCols" :cells="cardCells" :height="360" @set="setCard" @insert="insertCardTypes" @remove="removeTypes('card_types', $event)" />
			<h4>Rack types</h4>
			<EditGrid :columns="rackCols" :cells="rackCells" :height="160" @set="setRack" @insert="insertRackTypes" @remove="removeTypes('rack_types', $event)" />
		</div>
	</div>
</template>
