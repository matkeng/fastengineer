<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// Board Loading: every board of the Load List (a row marked as a distribution panel: a
// switchboard, an MCC, a transformer) with the demand of the loads below it, against its own
// rating. Worked out by the engine from the Load List as it is, every time it is shown; nothing
// is stored. Read-only: the figures change by changing the Load List or the Load Factors.
import { onMounted, ref } from 'vue';
import { apiGet, apiPostJsonForBlob, exportToPath, runningInTauri } from '../../lib/engine';

interface Board {
	ref: string; tag: string; description: string; depth: number; supplied_from: string; loads: number; left_out: number;
	connected_kw: number; max_kw: number; avg_kw: number; max_kva: number; max_amps: number | null;
	rating: number | null; rating_unit: string; loading_pct: number | null; spare: number | null; over: boolean; problem: string;
}
interface LeftOut { tag: string; reason: string; supplied_from: string }
interface Report { boards: Board[]; left_out: LeftOut[]; warn_at: number; default_pf: number }

const API = '/api/loading';
const report = ref<Report | null>(null);
const warnAt = ref(80);
const busy = ref(false);
const error = ref('');
const note = ref('');

async function load() {
	busy.value = true;
	error.value = '';
	try {
		report.value = await apiGet<Report>(API, { warn_at: warnAt.value });
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	} finally {
		busy.value = false;
	}
}
onMounted(load);
function setWarnAt() {
	if (!(warnAt.value > 0)) warnAt.value = 80;
	void load();
}

async function exportXlsx() {
	note.value = '';
	const file = 'Board Loading.xlsx';
	const body = { warn_at: warnAt.value };
	try {
		if (runningInTauri) {
			const { save: dialog } = await import('@tauri-apps/plugin-dialog');
			const path = await dialog({ defaultPath: file, filters: [{ name: 'Excel workbook', extensions: ['xlsx'] }] });
			if (path) note.value = `Saved ${(await exportToPath(`${API}/export`, body, path)).path}`;
		} else {
			const href = URL.createObjectURL(await apiPostJsonForBlob(`${API}/export`, body));
			Object.assign(document.createElement('a'), { href, download: file }).click();
			setTimeout(() => URL.revokeObjectURL(href), 10_000);
			note.value = `Downloaded ${file}`;
		}
	} catch (err) {
		error.value = err instanceof Error ? err.message : String(err);
	}
}

const num = (v: number | null, digits = 1) => (v === null ? '' : v.toLocaleString(undefined, { maximumFractionDigits: digits }));
</script>

<template>
	<section class="card wizard ref-editor key-loading">
		<div class="mel-head">
			<span class="kind tree">Master list</span>
			<h2 class="key-title">Board Loading</h2>
			<span class="hint small">The demand below each board against its rating, worked out now.</span>
			<span class="spacer" />
			<span v-if="note" class="saved" :title="note">✓ {{ note }}</span>
			<label class="small load-warn">Warn at
				<input v-model.number="warnAt" type="number" min="1" max="1000" step="5" aria-label="Warn at this loading, in percent" @change="setWarnAt"> %
			</label>
			<button type="button" class="secondary" :disabled="busy || !report" @click="exportXlsx">Export .xlsx</button>
			<button type="button" class="secondary" :disabled="busy" title="Work it out again from the Load List" @click="load">Refresh</button>
		</div>
		<p v-if="error" class="error">{{ error }}</p>
		<p class="hint small">
			A board is a Load List row marked as a distribution panel. Its figures are the sum of every load fed from it, directly or through
			the boards below it: <strong>max demand kW</strong> = rating × nameplate load factor × maximum demand factor (from Load Factors, or
			the load's own). kVA uses the load's motor's power factor, {{ report?.default_pf ?? 0.85 }} when it has no motor. There is no
			diversity between boards. <strong>Loading</strong> is the maximum demand over the board's own rating, in the rating's unit.
		</p>

		<div v-if="report" class="sum-read">
			<table class="grid simple load-boards">
				<thead>
					<tr>
						<th>Board</th><th>Supplied from</th><th class="num">Loads</th><th class="num">Connected kW</th><th class="num">Max demand kW</th>
						<th class="num">Average kW</th><th class="num">Max demand kVA</th><th class="num">Max demand A</th><th class="num">Rating</th>
						<th class="num">Loading</th><th class="num">Spare</th><th>Notes</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="b in report.boards" :key="b.ref" :class="{ over: b.over }">
						<td :style="{ paddingLeft: `${8 + b.depth * 18}px` }" :title="b.description">
							<span v-if="b.depth" class="hint">└ </span><strong>{{ b.tag }}</strong> <span class="hint small">{{ b.description }}</span>
						</td>
						<td>{{ b.supplied_from }}</td>
						<td class="num">{{ b.loads }}</td>
						<td class="num">{{ num(b.connected_kw) }}</td>
						<td class="num">{{ num(b.max_kw) }}</td>
						<td class="num">{{ num(b.avg_kw) }}</td>
						<td class="num">{{ num(b.max_kva) }}</td>
						<td class="num">{{ num(b.max_amps) }}</td>
						<td class="num">{{ b.rating === null ? '' : `${num(b.rating)} ${b.rating_unit}` }}</td>
						<td class="num load-pct">
							<span v-if="b.over" :title="`At or above ${report.warn_at} %`">⚠ </span>{{ b.loading_pct === null ? '' : `${num(b.loading_pct)} %` }}
						</td>
						<td class="num">{{ b.spare === null ? '' : `${num(b.spare)} ${b.rating_unit}` }}</td>
						<td class="small">
							<span v-if="b.problem" class="warn">{{ b.problem }}</span>
							<span v-if="b.left_out" class="warn">{{ b.problem ? ' · ' : '' }}{{ b.left_out }} load(s) not counted</span>
						</td>
					</tr>
					<tr v-if="!report.boards.length">
						<td colspan="12" class="hint">No boards yet: tick “distribution panel” on a Load List row (or an Electrical Equipment List item) and supply loads from it.</td>
					</tr>
				</tbody>
			</table>

			<details v-if="report.left_out.length" class="load-left-out">
				<summary>{{ report.left_out.length }} load(s) not counted</summary>
				<table class="grid simple">
					<thead><tr><th>Load</th><th>Supplied from</th><th>Why</th></tr></thead>
					<tbody>
						<tr v-for="x in report.left_out" :key="x.tag"><td>{{ x.tag }}</td><td>{{ x.supplied_from }}</td><td>{{ x.reason }}</td></tr>
					</tbody>
				</table>
			</details>
		</div>
	</section>
</template>
