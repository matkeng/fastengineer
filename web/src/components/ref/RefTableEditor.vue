<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import HistoryButton from '../audit/HistoryButton.vue';
import { computed, ref } from 'vue';
import { useRefData } from '../../stores/refdata';
import RefColumns from './RefColumns.vue';
import RefRows from './RefRows.vue';

const rd = useRefData();
const tab = ref<'rows' | 'columns'>(rd.table && rd.table.table.columns.length ? 'rows' : 'columns');
const d = computed(() => rd.tableDraft!);
defineExpose({ tab });

function remove() {
	const n = rd.table?.rows.length ?? 0;
	if (confirm(`Delete the table "${rd.table?.table.name}"${n ? ` and its ${n} row(s)` : ''}? This can't be undone.`)) void rd.remove();
}
</script>

<template>
	<section class="card wizard ref-editor" :class="{ 'rows-mode': tab === 'rows' }">
		<div class="mel-head">
			<span class="kind table">Table</span>
			<input v-model="d.name" class="name-input" aria-label="Table name" />
			<span v-if="rd.fieldErrors.name" class="warn small">{{ rd.fieldErrors.name }}</span>
			<span class="spacer" />
			<HistoryButton entity="ref_table" :record-id="d.id" :label="d.name" />
			<template v-if="rd.tableDirty">
				<span class="unsaved">● Unsaved name or column changes</span>
				<button type="button" class="secondary" :disabled="rd.busy" @click="rd.discard()">Discard</button>
				<button type="button" :disabled="rd.busy" @click="rd.saveColumns()">Save</button>
			</template>
			<span v-else-if="rd.message" class="saved">✓ {{ rd.message }}</span>
		</div>
		<nav class="subtabs">
			<button type="button" :class="{ active: tab === 'rows' }" :disabled="!rd.table?.table.columns.length" @click="tab = 'rows'">
				Rows<span class="count">{{ rd.table?.rows.length ?? 0 }}</span>
			</button>
			<button type="button" :class="{ active: tab === 'columns' }" @click="tab = 'columns'">
				Columns<span class="count">{{ d.columns.length }}</span>
			</button>
		</nav>
		<p v-if="rd.error" class="error">{{ rd.error }}</p>
		<div class="step-body">
			<RefRows v-if="tab === 'rows'" />
			<RefColumns v-else />
		</div>
		<div v-if="tab === 'columns'" class="nav">
			<span class="spacer" />
			<button type="button" class="secondary" @click="remove">Delete table</button>
		</div>
	</section>
</template>
