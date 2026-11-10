<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import EquipmentPackagesEditor from './EquipmentPackagesEditor.vue';
import LoadListEditor from './LoadListEditor.vue';
import CableTypesEditor from './CableTypesEditor.vue';
import CodeListEditor from './CodeListEditor.vue';
import EelEditor from './EelEditor.vue';
import PlcEditor from './PlcEditor.vue';
import LoadTypesEditor from './LoadTypesEditor.vue';
import PlantAreasEditor from './PlantAreasEditor.vue';

// The project's built-in lists; more are added to the sidebar.
const kl = useKeyLists();
const ui = useUi();
const TITLES = { 'plant-areas': 'Plant Areas', 'equipment-packages': 'Equipment Packages', 'load-types': 'Load Types', 'load-list': 'Load List',
	'equipment-codes': 'Equipment Codes', 'instrument-codes': 'Instrument Codes', eel: 'Electrical Equipment List', plc: 'PLC List',
	'cable-types': 'Cable Types' };
const loaded = computed(() => !!{ 'plant-areas': kl.areasDraft, 'equipment-packages': kl.packagesDraft, 'load-types': kl.loadTypes, 'load-list': true,
	'equipment-codes': kl.codeLists['equipment-codes'], 'instrument-codes': kl.codeLists['instrument-codes'], eel: kl.eel, plc: kl.plcDraft,
	'cable-types': kl.cableTypes }[kl.selected]);

onMounted(() => kl.load());
// Coming back to the section shows what is saved now (a draft with unsaved changes is kept).
watch(() => ui.tab, (tab) => { if (tab === 'keylists') void kl.load(); });
</script>

<template>
	<div class="ref">
		<div class="ref-layout">
			<aside class="card ref-side">
				<section>
					<h3>Project lists</h3>
					<p class="hint">The key lists every project has. Their columns and rules are fixed.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'plant-areas' }" @click="kl.select('plant-areas')">
							<span class="name">Plant Areas</span><span v-if="kl.areasDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" :title="`${kl.overview?.plant_areas.depth ?? 0} level(s)`">{{ kl.overview?.plant_areas.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'equipment-packages' }" @click="kl.select('equipment-packages')">
							<span class="name">Equipment Packages</span><span v-if="kl.packagesDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" :title="`package(s), with ${kl.overview?.equipment_packages.types ?? 0} equipment type(s)`">{{ kl.overview?.equipment_packages.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'load-types' }" @click="kl.select('load-types')">
							<span class="name">Load Types</span>
							<span class="count" title="load type(s)">{{ kl.overview?.load_types.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'equipment-codes' }" @click="kl.select('equipment-codes')">
							<span class="name">Equipment Codes</span>
							<span class="count" title="equipment code(s)">{{ kl.overview?.equipment_codes.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'instrument-codes' }" @click="kl.select('instrument-codes')">
							<span class="name">Instrument Codes</span>
							<span class="count" title="instrument code(s)">{{ kl.overview?.instrument_codes.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'cable-types' }" @click="kl.select('cable-types')">
							<span class="name">Cable Types</span>
							<span class="count" title="cable type(s)">{{ kl.overview?.cable_types.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'plc' }" @click="kl.select('plc')">
							<span class="name">PLC List</span><span v-if="kl.plcDirty || kl.catDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" :title="`${kl.overview?.plc.systems ?? 0} system(s), ${kl.overview?.plc.racks ?? 0} rack(s)`">{{ kl.overview?.plc.cards ?? 0 }}</span>
						</li>
					</ul>
				</section>
				<section>
					<h3>Load List</h3>
					<p class="hint">The Electrical Equipment List, and the Load List: its items and the MEL and EEL imports' rows.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'eel' }" @click="kl.select('eel')">
							<span class="name">Electrical Equipment List</span>
							<span class="count" title="equipment item(s)">{{ kl.overview?.eel.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'load-list' }" @click="kl.select('load-list')">
							<span class="name">Load List</span>
							<span class="count" :class="{ warn: kl.overview?.load_list.unallocated }"
								:title="`${kl.overview?.load_list.rows ?? 0} row(s), ${kl.overview?.load_list.unallocated ?? 0} without a plant area or load type`">{{ kl.overview?.load_list.rows ?? 0 }}</span>
						</li>
					</ul>
				</section>
			</aside>
			<!-- v-show keeps each list's filter and expanded rows when switching between them -->
			<PlantAreasEditor v-if="kl.areasDraft" v-show="kl.selected === 'plant-areas'" />
			<EquipmentPackagesEditor v-if="kl.packagesDraft" v-show="kl.selected === 'equipment-packages'" />
			<LoadTypesEditor v-if="kl.loadTypes" v-show="kl.selected === 'load-types'" />
			<CodeListEditor v-if="kl.codeLists['equipment-codes']" v-show="kl.selected === 'equipment-codes'" list-id="equipment-codes" />
			<CodeListEditor v-if="kl.codeLists['instrument-codes']" v-show="kl.selected === 'instrument-codes'" list-id="instrument-codes" />
			<CableTypesEditor v-if="kl.cableTypes" v-show="kl.selected === 'cable-types'" />
			<EelEditor v-if="kl.eel" v-show="kl.selected === 'eel'" />
			<PlcEditor v-if="kl.plcDraft" v-show="kl.selected === 'plc'" />
			<LoadListEditor v-if="kl.selected === 'load-list'" />
			<section v-if="!loaded" class="card wizard ref-empty">
				<h2>{{ TITLES[kl.selected] }}</h2>
				<p v-if="kl.error" class="error">{{ kl.error }}</p>
				<p v-else class="hint">Loading…</p>
			</section>
		</div>
	</div>
</template>
