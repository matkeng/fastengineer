<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Finding } from '../../lib/genTypes';
import { useGenerators } from '../../stores/generators';

const g = useGenerators();
const RULES: Record<string, string> = {
	C1: 'No tags on the runsheet', C2: 'Duplicate tag', C3: 'Template ID in more than one block',
	C4: 'Tag with no source', C5: 'Parent lookup without Parents', C6: 'Key with no template', C7: 'Run number blank or not a number',
	C8: 'Duplicate run number', C9: 'Not found on Parents', C10: 'Duplicate tag on Parents', C11: 'Row with data but no key',
	C12: 'Runsheet tag not used', C13: 'Template not used', C14: 'Key and scope disagree', C15: 'Lookup key not in its table',
	C16: 'Card type not in the catalogue', C17: 'Calculated column references something missing', C18: 'Late formula does not parse',
	C19: 'Loop number blank', C20: 'Same tag or cable number produced twice', BUILD: 'Build failed',
};
const show = ref<Record<Finding['severity'], boolean>>({ ERROR: true, WARN: true, INFO: false });
const findings = computed(() => g.checkResult?.findings ?? []);
const count = (s: Finding['severity']) => findings.value.filter((f) => f.severity === s).length;
const shown = computed(() => findings.value.filter((f) => show.value[f.severity]));

function canOpen(f: Finding) {
	return /^row \S+/.test(f.item) || /^Template \S+/.test(f.item) || /template \S+/i.test(f.detail);
}

function open(f: Finding) {
	const row = /^row (\S+)/.exec(f.item);
	if (row) {
		g.jumpToRow = row[1];
		g.tab = 'runsheet';
		return;
	}
	const tpl = /^Template (\S+)/.exec(f.item) ?? /template (\S+?)[ ,(]/i.exec(`${f.detail} `);
	if (tpl) {
		g.selectedTemplate = tpl[1].replace(/[,()]/g, '');
		g.tab = 'templates';
	}
}
</script>

<template>
	<div class="gen-panel">
		<div class="row">
			<button type="button" :disabled="g.busy" @click="g.check()">Check again</button>
			<label class="chip sev-error"><input v-model="show.ERROR" type="checkbox" /> {{ count('ERROR') }} errors</label>
			<label class="chip sev-warn"><input v-model="show.WARN" type="checkbox" /> {{ count('WARN') }} warnings</label>
			<label class="chip"><input v-model="show.INFO" type="checkbox" /> {{ count('INFO') }} info</label>
			<span class="hint">Checks the current edits, saved or not. Click a finding to go to it.</span>
		</div>
		<p v-if="!g.checkResult" class="hint">Checking…</p>
		<p v-else-if="!findings.length" class="saved">✓ No problems found.</p>
		<div v-else class="grid-wrap findings">
			<table class="grid simple">
				<thead><tr><th>Severity</th><th>Rule</th><th>Item</th><th>Detail</th><th>Where</th></tr></thead>
				<tbody>
					<tr v-for="(f, i) in shown" :key="i" :class="{ link: canOpen(f) }" @click="open(f)">
						<td><span class="sev" :class="`sev-${f.severity.toLowerCase()}`">{{ f.severity }}</span></td>
						<td :title="RULES[f.code] ?? ''"><strong>{{ f.code }}</strong> {{ RULES[f.code] ?? '' }}</td>
						<td>{{ f.item }}</td>
						<td class="detail">{{ f.detail }}</td>
						<td>{{ f.where }}</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
