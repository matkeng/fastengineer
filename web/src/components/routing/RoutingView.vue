<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Cable Routing: a node map of the cable ladder routes. The cables of the Project Master Cable
// Schedule are routed over it, which gives their lengths and each segment's ladder width and mass.
import { computed, watch } from 'vue';
import { useRouting } from '../../stores/routing';
import { useUi } from '../../stores/ui';
import HistoryButton from '../audit/HistoryButton.vue';
import UndoButtons from '../common/UndoButtons.vue';
import RoutingCables from './RoutingCables.vue';
import RoutingCanvas from './RoutingCanvas.vue';
import RoutingInspector from './RoutingInspector.vue';
import RoutingPalette from './RoutingPalette.vue';
import RoutingRules from './RoutingRules.vue';
import RoutingSegments from './RoutingSegments.vue';

const rt = useRouting();
const ui = useUi();
// each time the section is opened the cable schedule may have changed: read it again (unsaved edits are kept and checked again)
watch(() => ui.tab, (tab) => {
	if (tab !== 'routing') return;
	if (rt.dirty) void rt.check();
	else void rt.load();
}, { immediate: true });

const problems = computed(() => Object.keys(rt.errors).length);
const unrouted = computed(() => (rt.view?.cables ?? []).filter((c) => c.status !== 'ok').length);
function discard() {
	if (confirm('Discard the unsaved changes to the map and the rules?')) rt.discard();
}
function renumber() {
	if (confirm('Number the nodes and segments again from N001 and S-001, in the order they were drawn? Tags already on drawings will change.')) void rt.renumber();
}
</script>

<template>
	<section class="routing">
		<div class="rt-head">
			<div class="subtabs">
				<button type="button" :class="{ active: rt.tab === 'map' }" @click="rt.tab = 'map'">Map</button>
				<button type="button" :class="{ active: rt.tab === 'cables' }" @click="rt.tab = 'cables'">Cables<span v-if="unrouted" class="count" title="Cables not routed">{{ unrouted }}</span></button>
				<button type="button" :class="{ active: rt.tab === 'segments' }" @click="rt.tab = 'segments'">Segments and ladders</button>
				<button type="button" :class="{ active: rt.tab === 'rules' }" @click="rt.tab = 'rules'">Rules</button>
			</div>
			<span class="spacer" />
			<span v-if="rt.error" class="error">{{ rt.error }}</span>
			<span v-else-if="rt.message" class="saved">{{ rt.message }}</span>
			<span v-else-if="problems" class="warn">{{ problems }} problem{{ problems === 1 ? '' : 's' }} to fix before saving</span>
			<UndoButtons :can-undo="rt.canUndo" :can-redo="rt.canRedo" :disabled="rt.busy" small @undo="rt.undo()" @redo="rt.redo()" />
			<button type="button" class="secondary small" :disabled="rt.busy || !rt.draft?.nodes.length" title="Number the nodes and segments again from 1" @click="renumber">Renumber</button>
			<HistoryButton entity="cable_routing" record-id="cable-routing" label="Cable Routing" />
			<button type="button" class="secondary small" :disabled="!rt.dirty || rt.busy" @click="discard">Discard</button>
			<button type="button" :disabled="!rt.dirty || rt.busy" data-testid="routing-save" @click="rt.save()">Save</button>
		</div>
		<template v-if="rt.draft">
			<div v-show="rt.tab === 'map'" class="rt-map">
				<RoutingPalette />
				<RoutingCanvas />
				<RoutingInspector />
			</div>
			<RoutingCables v-if="rt.tab === 'cables'" />
			<RoutingSegments v-if="rt.tab === 'segments'" />
			<RoutingRules v-if="rt.tab === 'rules'" />
		</template>
		<p v-else class="hint">{{ rt.error ? '' : 'Loading the map…' }}</p>
	</section>
</template>
