<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { ref } from 'vue';

// The people who may open a project: Windows logins, e.g. ACME\jsmith.
const props = defineProps<{ modelValue: string[]; known: string[]; listId: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>();
const entry = ref('');
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

function add() {
	const name = entry.value.trim();
	if (name && !props.modelValue.some((m) => same(m, name))) emit('update:modelValue', [...props.modelValue, name]);
	entry.value = '';
}
</script>

<template>
	<div class="members">
		<ul v-if="modelValue.length">
			<li v-for="m in modelValue" :key="m">
				<span class="mono">{{ m }}</span>
				<button type="button" class="secondary small" :title="`Remove ${m}`"
					@click="emit('update:modelValue', modelValue.filter((x) => x !== m))">✕</button>
			</li>
		</ul>
		<p v-else class="hint">Nobody yet. Administrators can always open it.</p>
		<div class="row">
			<input v-model="entry" :list="listId" placeholder="DOMAIN\username" aria-label="User to add" @keydown.enter.prevent="add" />
			<datalist :id="listId">
				<option v-for="u in known.filter((k) => !modelValue.some((m) => same(m, k)))" :key="u" :value="u" />
			</datalist>
			<button type="button" class="secondary" :disabled="!entry.trim()" @click="add">Add</button>
		</div>
	</div>
</template>
