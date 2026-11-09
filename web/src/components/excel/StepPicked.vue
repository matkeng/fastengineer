<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed } from 'vue';
import { useWizardContext } from '../../lib/wizardContext';

const { wiz } = useWizardContext();
const r = computed(() => wiz.result);
</script>

<template>
	<div v-if="r" class="picked">
		<p>
			<strong>{{ wiz.workbook?.filename }}</strong> · {{ r.source.name }} ·
			header row {{ r.header_row }}<template v-if="r.header_rows > 1">–{{ r.header_row + r.header_rows - 1 }}</template>
		</p>
		<div class="chips">
			<span class="chip"><strong>{{ r.rows.length }}</strong> rows</span>
			<span class="chip"><strong>{{ r.columns.length }}</strong> columns</span>
			<span class="chip">Key: <strong>{{ r.columns[r.key_column].name }}</strong></span>
			<span v-if="r.duplicate_keys.length" class="chip warn-chip">{{ r.duplicate_keys.length }} duplicate key(s)</span>
		</div>
	</div>
</template>
