<script setup lang="ts">
import { ref, watch } from 'vue';

const props = defineProps<{ open: boolean; title: string }>();
const emit = defineEmits<{ close: [] }>();
const dlg = ref<HTMLDialogElement | null>(null);

watch(
	() => props.open,
	(open) => {
		if (!dlg.value) return;
		if (open && !dlg.value.open) dlg.value.showModal();
		if (!open && dlg.value.open) dlg.value.close();
	},
	{ flush: 'post' },
);
</script>

<template>
	<dialog ref="dlg" class="modal" @close="emit('close')" @cancel.prevent="emit('close')">
		<form method="dialog" class="modal-inner" @submit.prevent>
			<header class="modal-head">
				<h3>{{ title }}</h3>
				<button type="button" class="secondary close" aria-label="Close" @click="emit('close')">✕</button>
			</header>
			<div class="modal-body"><slot /></div>
			<footer class="modal-foot"><slot name="footer" /></footer>
		</form>
	</dialog>
</template>
