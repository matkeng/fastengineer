<script setup lang="ts">
import { useWizardContext } from '../../lib/wizardContext';

const { wiz } = useWizardContext();
</script>

<template>
	<div v-if="wiz.workbook">
		<p class="hint">Pick a whole worksheet, or a defined Excel table (its range and header are already known).</p>
		<div class="choices">
			<label v-for="s in wiz.workbook.sources" :key="s.id" class="choice" :class="{ selected: wiz.sourceId === s.id }">
				<input type="radio" name="source" :checked="wiz.sourceId === s.id" @change="wiz.chooseSource(s.id)" />
				<span class="kind" :class="s.kind">{{ s.kind === 'sheet' ? 'Sheet' : 'Table' }}</span>
				<span class="name">{{ s.name }}</span>
				<span class="meta">
					<template v-if="s.kind === 'table'">on {{ s.sheet }} · </template>
					{{ s.ref }} · {{ s.last_row - s.first_row + 1 }} rows × {{ s.last_col - s.first_col + 1 }} cols
				</span>
			</label>
		</div>
	</div>
</template>
