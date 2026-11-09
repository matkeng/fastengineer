<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import type { PipelineResult } from '../../lib/melTypes';
import { type MelTab, useMel } from '../../stores/mel';
import MelUpload from './MelUpload.vue';

const mel = useMel();
const result = ref<PipelineResult | null>(null);

async function refresh() {
	result.value = mel.latest ? ((await mel.runStage('auto')) ?? null) : null;
}

const RULES: { tab: MelTab; label: string; n: () => number; what: string }[] = [
	{ tab: 'columns', label: 'Columns', n: () => mel.draft!.columns.length, what: 'hide or rename source columns' },
	{ tab: 'rows', label: 'Rows', n: () => mel.draft!.hidden_rows.length, what: 'hide rows you don\'t want in the list' },
	{ tab: 'text', label: 'Text columns', n: () => mel.draft!.text_columns.length, what: 'add a column with one value' },
	{ tab: 'overrides', label: 'Overrides', n: () => mel.draft!.overrides.length, what: 'correct single cells' },
	{ tab: 'custom', label: 'Custom rows', n: () => mel.draft!.custom_rows.length, what: 'add rows not in the file' },
	{ tab: 'auto', label: 'Calculated columns', n: () => mel.draft!.auto_columns.length, what: 'if/else formulas per row' },
	{ tab: 'mapping', label: 'Mapping', n: () => mel.draft!.mapping.length, what: `columns to ${mel.outputName.toLowerCase()} fields` },
];

function removeRevision(id: string, rev: number) {
	if (confirm(`Delete revision ${rev}? The previous revision becomes the active one.`)) void mel.deleteRevision(id).then(refresh);
}

onMounted(refresh);
watch(() => mel.revisions, refresh);
</script>

<template>
	<div class="mel-overview">
		<div class="two-col">
			<div>
				<h3>Recipe</h3>
				<p class="hint">Rules run in this order every time the data is read. Nothing changes the uploaded file.</p>
				<table class="grid simple rules">
					<tbody>
						<tr v-for="(r, i) in RULES" :key="r.tab" :class="{ disabled: !mel.latest }" @click="mel.latest && (mel.tab = r.tab)">
							<td class="num">{{ i + 1 }}</td>
							<td><strong>{{ r.label }}</strong><br /><span class="hint">{{ r.what }}</span></td>
							<td class="n">{{ r.n() }}</td>
						</tr>
					</tbody>
				</table>
				<p v-if="result" class="hint">
					Result: <strong>{{ result.rows.length }}</strong> rows × <strong>{{ result.headers.length }}</strong> columns.
					<button type="button" class="link" @click="mel.tab = 'result'">View and export →</button>
				</p>
				<div v-if="result?.issues.length" class="health">
					<h4>⚠ {{ result.issues.length }} rule(s) not applied</h4>
					<p class="hint">Usually because the latest file no longer has that key or column. Fix or delete these rules.</p>
					<ul>
						<li v-for="(i, n) in result.issues" :key="n">
							<button type="button" class="link" @click="mel.tab = (i.kind as MelTab)">{{ i.kind }}</button>&nbsp;·
							<strong>{{ i.rule }}</strong>: {{ i.message }}
						</li>
					</ul>
				</div>
				<p v-else-if="result" class="ok-text">✓ Every rule applies to the latest file.</p>
			</div>
			<div>
				<h3>Files</h3>
				<p class="hint">Every upload is kept as a revision; the newest is the one used.</p>
				<table v-if="mel.revisions.length" class="grid simple">
					<thead><tr><th>Rev</th><th>File</th><th>Key</th><th>Rows</th><th>Uploaded</th><th /></tr></thead>
					<tbody>
						<tr v-for="(v, i) in mel.revisions" :key="v.id">
							<td>{{ v.rev }}<span v-if="i === 0" class="badge">active</span></td>
							<td :title="v.source">{{ v.file_name }}<div v-for="w in v.warnings" :key="w" class="warn small">{{ w }}</div></td>
							<td>{{ v.key_header }}</td>
							<td>{{ v.num_rows }} × {{ v.num_cols }}</td>
							<td>{{ new Date(v.uploaded_at).toLocaleString() }}</td>
							<td class="actions"><button type="button" class="secondary small" @click="removeRevision(v.id, v.rev)">Delete</button></td>
						</tr>
					</tbody>
				</table>
				<MelUpload />
			</div>
		</div>
	</div>
</template>
