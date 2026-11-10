<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { onMounted, watch } from 'vue';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import PlantAreasEditor from './PlantAreasEditor.vue';

// The project's built-in lists. Plant Areas is the first; more are added to the sidebar.
const kl = useKeyLists();
const ui = useUi();

onMounted(() => kl.loadAreas());
// Coming back to the section shows what is saved now (a draft with unsaved changes is kept).
watch(() => ui.tab, (tab) => { if (tab === 'keylists') void kl.loadAreas(); });
</script>

<template>
	<div class="ref">
		<div class="ref-layout">
			<aside class="card ref-side">
				<section>
					<h3>Project lists</h3>
					<p class="hint">The key lists every project has. Their columns and rules are fixed.</p>
					<ul class="ref-nav">
						<li class="current">
							<span class="name">Plant Areas</span>
							<span class="count" :title="`${kl.overview?.plant_areas.depth ?? 0} level(s)`">{{ kl.overview?.plant_areas.items ?? 0 }}</span>
						</li>
					</ul>
				</section>
			</aside>
			<PlantAreasEditor v-if="kl.areasDraft" />
			<section v-else class="card wizard ref-empty">
				<h2>Plant Areas</h2>
				<p v-if="kl.error" class="error">{{ kl.error }}</p>
				<p v-else class="hint">Loading…</p>
			</section>
		</div>
	</div>
</template>
