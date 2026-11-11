<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { useAudit } from '../../stores/audit';

// Opens the change log on one record: who changed it, when, and what changed.
const props = defineProps<{ entity: string; recordId: string; label: string }>();
const audit = useAudit();
</script>

<template>
	<button type="button" class="secondary" title="Who changed this, when, and what changed"
		@click="audit.showRecord(props.entity, props.recordId, props.label)">History</button>
</template>
