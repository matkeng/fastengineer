<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import EquipmentPackagesEditor from './EquipmentPackagesEditor.vue';
import LoadListEditor from './LoadListEditor.vue';
import LoadTypesEditor from './LoadTypesEditor.vue';
import PlantAreasEditor from './PlantAreasEditor.vue';

// The project's built-in lists; more are added to the sidebar.
const kl = useKeyLists();
const ui = useUi();
const TITLES = { 'plant-areas': 'Plant Areas', 'equipment-packages': 'Equipment Packages', 'load-types': 'Load Types', 'load-list': 'Load List' };
const loaded = computed(() => !!{ 'plant-areas': kl.areasDraft, 'equipment-packages': kl.packagesDraft, 'load-types': kl.loadTypes, 'load-list': true }[kl.selected]);

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
					</ul>
				</section>
				<section>
					<h3>Load List</h3>
					<p class="hint">The MEL and EEL imports' rows, with a plant area and load type for each.</p>
					<ul class="ref-nav">
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
			<LoadListEditor v-if="kl.selected === 'load-list'" />
			<section v-if="!loaded" class="card wizard ref-empty">
				<h2>{{ TITLES[kl.selected] }}</h2>
				<p v-if="kl.error" class="error">{{ kl.error }}</p>
				<p v-else class="hint">Loading…</p>
			</section>
		</div>
	</div>
</template>
