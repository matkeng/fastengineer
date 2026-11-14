<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// What can be put on the map: the Project Master Equipment List's equipment that is not on it yet,
// and the cable schedule's From and To tags that are in no equipment list ("Primary Supply").
import { computed, ref } from 'vue';
import { nameKey } from '../../lib/routingCanvas';
import { useRouting } from '../../stores/routing';

const rt = useRouting();
const search = ref('');
const placed = computed(() => new Set((rt.draft?.placements ?? []).map((p) => nameKey(p.tag))));
const waiting = computed(() => new Map((rt.view?.unplaced ?? []).map((e) => [nameKey(e.tag), e.cables])));
const fits = (text: string) => !search.value.trim() || text.toLowerCase().includes(search.value.trim().toLowerCase());
const equipment = computed(() => (rt.view?.equipment ?? []).filter((e) => !placed.value.has(nameKey(e.tag)) && fits(`${e.tag} ${e.description}`)));
const others = computed(() => (rt.view?.unplaced ?? []).filter((e) => !e.in_equipment_list && !placed.value.has(nameKey(e.tag)) && fits(e.tag)));
const total = computed(() => rt.view?.equipment.length ?? 0);

type Item = { tag: string; description: string; source: string | null };
function onDrag(e: DragEvent, item: Item) {
	e.dataTransfer?.setData('application/x-routing-equipment', JSON.stringify(item));
	if (e.dataTransfer) e.dataTransfer.effectAllowed = 'copy';
}
function typed() {
	const tag = prompt('Tag of the equipment (a junction box, a supply...)')?.trim();
	if (tag) rt.placeRequest = { tag, description: '', source: null };
}
</script>

<template>
	<aside class="rt-palette">
		<h3>Equipment <span class="count">{{ total - equipment.length }}/{{ total }} placed</span></h3>
		<input v-model="search" type="search" placeholder="Search tag or description" aria-label="Search equipment" />
		<ul class="rt-list" data-testid="routing-palette">
			<li v-for="e in equipment" :key="e.source" draggable="true" :title="`${e.tag} – ${e.description}\nDrag onto the map, or double-click`"
				@dragstart="onDrag($event, { tag: e.tag, description: e.description, source: e.source })"
				@dblclick="rt.placeRequest = { tag: e.tag, description: e.description, source: e.source }">
				<span class="mono">{{ e.tag }}</span><span class="desc">{{ e.description }}</span>
				<span v-if="waiting.get(nameKey(e.tag))" class="count" title="Cables that start or end here">{{ waiting.get(nameKey(e.tag)) }}</span>
			</li>
			<li v-if="!equipment.length" class="none hint">{{ total ? (search ? 'Nothing matches.' : 'All of it is on the map.') : 'The Project Master Equipment List is empty.' }}</li>
		</ul>
		<template v-if="others.length">
			<h3 title="From and To tags of the cable schedule that are in no equipment list">Other cable ends</h3>
			<ul class="rt-list">
				<li v-for="e in others" :key="e.tag" draggable="true" title="Drag onto the map, or double-click"
					@dragstart="onDrag($event, { tag: e.tag, description: '', source: null })" @dblclick="rt.placeRequest = { tag: e.tag, description: '', source: null }">
					<span class="mono">{{ e.tag }}</span><span class="desc" /><span class="count" title="Cables that start or end here">{{ e.cables }}</span>
				</li>
			</ul>
		</template>
		<button type="button" class="secondary small" @click="typed">+ Other equipment…</button>
	</aside>
</template>
