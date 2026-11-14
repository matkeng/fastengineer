<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The project's rules: the services cables are split into, how each service's ladders are sized
// and loaded, and what is added to a route's length for the cable schedule.
import { computed } from 'vue';
import { newId } from '../../lib/refTypes';
import { type Allowance, type CableRouting, RULE_FIELDS, type RuleField, type Service, type ServiceRule } from '../../lib/routingTypes';
import { useRouting } from '../../stores/routing';

const rt = useRouting();
const doc = computed(() => rt.draft as CableRouting);
const value = (e: Event) => (e.target as HTMLInputElement | HTMLSelectElement).value;
const num = (e: Event, fallback = 0) => (value(e).trim() === '' || Number.isNaN(Number(value(e))) ? fallback : Number(value(e)));
const err = (id: string, field: string) => rt.errors[`${id}.${field}`];

function setService<K extends keyof Service>(id: string, field: K, v: Service[K]) {
	rt.edit((d) => {
		const s = d.services.find((x) => x.id === id);
		if (s) s[field] = v;
	});
}
const widths = (text: string) => [...new Set(text.split(/[,;\s]+/).map(Number).filter((n) => Number.isFinite(n) && n > 0))].sort((a, b) => a - b);
function addService() {
	rt.edit((d) => void d.services.push({ id: newId(), name: 'New service', colour: '#64748b', spacing_factor: 0, max_layers: 1, spare_pct: 25,
		widths_mm: [150, 300, 450, 600, 750, 900], max_kg_per_m: 50 }));
}
function removeService(s: Service) {
	const used = (rt.view?.cables ?? []).filter((c) => c.service_id === s.id).length;
	if (used && !confirm(`${used} cable(s) are in ${s.name}. Delete it? Its rules go with it and those cables fall to the default service.`)) return;
	rt.edit((d) => {
		d.services = d.services.filter((x) => x.id !== s.id);
		d.service_rules = d.service_rules.filter((r) => r.service_id !== s.id);
		for (const seg of d.segments) delete seg.ladders[s.id];
		if (d.default_service_id === s.id) d.default_service_id = d.services[0]?.id ?? '';
	});
}

function setRule<K extends keyof ServiceRule>(id: string, field: K, v: ServiceRule[K]) {
	rt.edit((d) => {
		const r = d.service_rules.find((x) => x.id === id);
		if (r) r[field] = v;
	});
}
function addRule() {
	rt.edit((d) => void d.service_rules.push({ id: newId(), field: 'type', contains: '', service_id: d.default_service_id }));
}
function moveRule(index: number, by: number) {
	rt.edit((d) => {
		const [r] = d.service_rules.splice(index, 1);
		d.service_rules.splice(index + by, 0, r);
	});
}
function setAllowance<K extends keyof Allowance>(field: K, v: Allowance[K]) {
	rt.edit((d) => {
		d.allowance[field] = v;
	});
}
const example = computed(() => {
	const a = doc.value.allowance;
	const raw = (100 + a.tail_from_m + a.tail_to_m) * (1 + a.contingency_pct / 100);
	const out = a.round_up_to_m > 0 ? Math.ceil(Math.round((raw / a.round_up_to_m) * 1e6) / 1e6) * a.round_up_to_m : Math.round(raw * 10) / 10;
	return Math.round(out * 1000) / 1000;
});
</script>

<template>
	<div class="rt-rules">
		<section class="card">
			<h2>Cable lengths</h2>
			<p class="hint">A cable's length is its route's segments added up, plus a tail at each end, plus a contingency, rounded up.
				A route of 100 m gives <strong>{{ example }} m</strong>.</p>
			<div class="rt-form">
				<label class="field"><span>Tail at the From end (m)</span>
					<input type="number" min="0" step="any" :value="doc.allowance.tail_from_m" @change="setAllowance('tail_from_m', num($event))" /></label>
				<label class="field"><span>Tail at the To end (m)</span>
					<input type="number" min="0" step="any" :value="doc.allowance.tail_to_m" @change="setAllowance('tail_to_m', num($event))" /></label>
				<label class="field"><span>Contingency (%)</span>
					<input type="number" min="0" step="any" :value="doc.allowance.contingency_pct" @change="setAllowance('contingency_pct', num($event))" /></label>
				<label class="field"><span>Round up to (m; 0: not rounded)</span>
					<input type="number" min="0" step="any" :value="doc.allowance.round_up_to_m" @change="setAllowance('round_up_to_m', num($event))" /></label>
			</div>
			<label class="rt-check big">
				<input type="checkbox" :checked="doc.allowance.apply_to_master" data-testid="apply-to-master"
					@change="setAllowance('apply_to_master', ($event.target as HTMLInputElement).checked)" />
				Show these lengths in the Project Master Cable Schedule
			</label>
			<p class="hint">When on, <strong>Length (m)</strong> of every routed cable comes from the map, in the master list and in new revisions of its
				deliverables. Cables that are not routed keep the length from the Load List; issued revisions do not change.</p>
			<label class="field narrow"><span>Write the route (N001-N004…) in the Route column</span>
				<select :value="doc.allowance.route_column" :disabled="!doc.allowance.apply_to_master"
					@change="setAllowance('route_column', value($event) as Allowance['route_column'])">
					<option value="when blank">where it is blank</option><option value="always">always</option><option value="never">never</option>
				</select></label>
		</section>

		<section class="card">
			<h2>Services and ladder loading rules</h2>
			<p class="hint">Each service has ladders of its own on a segment. A ladder's width is the cables' diameters side by side (three single core
				cables of one circuit count as a trefoil, 2.15 diameters), with the spacing beside each cable, divided by the layers, plus the spare;
				then the next standard width. The load limit is what one ladder carries.</p>
			<table class="grid simple rt-table rt-edit" data-testid="routing-services">
				<thead>
					<tr><th>Service</th><th>Colour</th><th class="num" title="The gap left beside each cable, in cable diameters">Spacing (× diameter)</th>
						<th class="num">Layers</th><th class="num">Spare (%)</th><th>Standard widths (mm)</th><th class="num">Load limit (kg/m)</th><th /></tr>
				</thead>
				<tbody>
					<tr v-for="s in doc.services" :key="s.id">
						<td><input type="text" :value="s.name" :class="{ bad: err(s.id, 'name') }" :title="err(s.id, 'name')" @change="setService(s.id, 'name', value($event))" /></td>
						<td><input type="color" :value="s.colour" @change="setService(s.id, 'colour', value($event))" /></td>
						<td class="num"><input type="number" min="0" step="any" :value="s.spacing_factor" @change="setService(s.id, 'spacing_factor', num($event))" /></td>
						<td class="num"><input type="number" min="1" step="1" :value="s.max_layers" :class="{ bad: err(s.id, 'max_layers') }"
							@change="setService(s.id, 'max_layers', Math.round(num($event, 1)))" /></td>
						<td class="num"><input type="number" min="0" step="any" :value="s.spare_pct" @change="setService(s.id, 'spare_pct', num($event))" /></td>
						<td><input type="text" class="wide" :value="s.widths_mm.join(', ')" :class="{ bad: err(s.id, 'widths_mm') }" :title="err(s.id, 'widths_mm')"
							@change="setService(s.id, 'widths_mm', widths(value($event)))" /></td>
						<td class="num"><input type="number" min="0" step="any" :value="s.max_kg_per_m ?? ''" placeholder="none" :class="{ bad: err(s.id, 'max_kg_per_m') }"
							@change="setService(s.id, 'max_kg_per_m', value($event).trim() === '' ? null : num($event))" /></td>
						<td><button type="button" class="secondary small" title="Delete the service" :disabled="doc.services.length < 2" @click="removeService(s)">×</button></td>
					</tr>
				</tbody>
			</table>
			<button type="button" class="secondary small" @click="addService">+ Service</button>
		</section>

		<section class="card">
			<h2>Which service a cable belongs to</h2>
			<p class="hint">Read from the cable's Cable Type (Project lists). The first rule that fits wins; a cable no rule fits is in the default service.</p>
			<table class="grid simple rt-table rt-edit">
				<thead><tr><th class="num">#</th><th>Cable type's</th><th>contains</th><th>Service</th><th /></tr></thead>
				<tbody>
					<tr v-for="(r, i) in doc.service_rules" :key="r.id">
						<td class="num">{{ i + 1 }}</td>
						<td><select :value="r.field" @change="setRule(r.id, 'field', value($event) as RuleField)">
							<option v-for="(label, f) in RULE_FIELDS" :key="f" :value="f">{{ label }}</option></select></td>
						<td><input type="text" :value="r.contains" :class="{ bad: err(r.id, 'contains') }" :title="err(r.id, 'contains')" @change="setRule(r.id, 'contains', value($event))" /></td>
						<td><select :value="r.service_id" :class="{ bad: err(r.id, 'service_id') }" @change="setRule(r.id, 'service_id', value($event))">
							<option v-for="s in doc.services" :key="s.id" :value="s.id">{{ s.name }}</option></select></td>
						<td class="rt-row-buttons">
							<button type="button" class="secondary small" title="Move up" :disabled="i === 0" @click="moveRule(i, -1)">↑</button>
							<button type="button" class="secondary small" title="Move down" :disabled="i === doc.service_rules.length - 1" @click="moveRule(i, 1)">↓</button>
							<button type="button" class="secondary small" title="Delete the rule" @click="rt.edit((d) => void d.service_rules.splice(i, 1))">×</button>
						</td>
					</tr>
				</tbody>
			</table>
			<div class="rt-bar">
				<button type="button" class="secondary small" @click="addRule">+ Rule</button>
				<label>Default service
					<select :value="doc.default_service_id" @change="rt.edit((d) => { d.default_service_id = value($event); })">
						<option v-for="s in doc.services" :key="s.id" :value="s.id">{{ s.name }}</option>
					</select></label>
			</div>
		</section>
	</div>
</template>
