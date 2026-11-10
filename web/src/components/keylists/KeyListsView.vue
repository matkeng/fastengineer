<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { onMounted, watch } from 'vue';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import EquipmentPackagesEditor from './EquipmentPackagesEditor.vue';
import PlantAreasEditor from './PlantAreasEditor.vue';

// The project's built-in lists; more are added to the sidebar.
const kl = useKeyLists();
const ui = useUi();

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
							<span class="count" title="package(s)">{{ kl.overview?.equipment_packages.items ?? 0 }}</span>
						</li>
					</ul>
				</section>
			</aside>
			<!-- v-show keeps each list's filter and expanded rows when switching between them -->
			<PlantAreasEditor v-if="kl.areasDraft" v-show="kl.selected === 'plant-areas'" />
			<EquipmentPackagesEditor v-if="kl.packagesDraft" v-show="kl.selected === 'equipment-packages'" />
			<section v-if="!(kl.selected === 'plant-areas' ? kl.areasDraft : kl.packagesDraft)" class="card wizard ref-empty">
				<h2>{{ kl.selected === 'plant-areas' ? 'Plant Areas' : 'Equipment Packages' }}</h2>
				<p v-if="kl.error" class="error">{{ kl.error }}</p>
				<p v-else class="hint">Loading…</p>
			</section>
		</div>
	</div>
</template>
