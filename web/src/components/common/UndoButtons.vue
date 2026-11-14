<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The Undo and Redo buttons of an editor (see lib/history.ts).
defineProps<{ canUndo: boolean; canRedo: boolean; disabled?: boolean; small?: boolean }>();
defineEmits<{ undo: []; redo: [] }>();
</script>

<template>
	<span class="undo-buttons">
		<button type="button" class="secondary" :class="{ small }" :disabled="!canUndo || disabled" title="Undo the last change (Ctrl+Z in a grid)" @click="$emit('undo')">↶ Undo</button>
		<button type="button" class="secondary" :class="{ small }" :disabled="!canRedo || disabled" title="Redo what was undone (Ctrl+Y in a grid)" @click="$emit('redo')">↷ Redo</button>
	</span>
</template>
