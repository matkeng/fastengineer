<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Undo and Redo for a list whose every change is saved at once (see stores/keylists.ts listUndo).
import { ref } from 'vue';
import { type SavedListKey, useKeyLists } from '../../stores/keylists';
import UndoButtons from '../common/UndoButtons.vue';

const props = defineProps<{ list: SavedListKey }>();
const kl = useKeyLists();
const note = ref('');
async function step(redo: boolean) {
	note.value = await kl.stepList(props.list, redo);
}
</script>

<template>
	<span v-if="note" class="saved" :title="note">✓ {{ note }}</span>
	<UndoButtons :can-undo="kl.canUndoList(list)" :can-redo="kl.canRedoList(list)" :disabled="kl.busy" @undo="step(false)" @redo="step(true)" />
</template>
