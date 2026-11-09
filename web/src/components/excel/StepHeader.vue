<script setup lang="ts">
import { computed } from 'vue';
import { cellHtml } from '../../lib/cells';
import { useWizardContext } from '../../lib/wizardContext';

const { wiz } = useWizardContext();
const pv = computed(() => wiz.preview);

const lastHeader = computed(() => (wiz.headerRow ?? 0) + wiz.headerRows - 1);

function rowLabel(row: { row: number; cells: { t: string }[] }) {
	const texts = [...new Set(row.cells.map((c) => c.t.trim()).filter(Boolean))].slice(0, 4);
	const text = texts.join(' | ');
	return `Row ${row.row}${text ? ` — ${text.length > 70 ? `${text.slice(0, 70)}…` : text}` : ' (empty)'}`;
}

function rowClass(r: number) {
	const h = wiz.headerRow;
	if (h === null) return '';
	if (r >= h && r <= lastHeader.value) return 'is-header';
	return r < h ? 'is-above' : 'is-data';
}
</script>

<template>
	<div v-if="pv">
		<p class="hint">
			Select the row that holds the column names. If the names are stacked over several rows (for example
			"Cable" above "Size" and "Cores"), set how many rows the header spans and they are joined.
			<template v-if="pv.suggested_header_row">
				Suggested: row {{ pv.suggested_header_row }}<template v-if="pv.suggested_header_rows > 1">
					spanning {{ pv.suggested_header_rows }} rows</template>.
			</template>
		</p>
		<div class="row controls">
			<label>
				Header row
				<select
					:value="wiz.headerRow ?? ''"
					@change="wiz.chooseHeader(Number(($event.target as HTMLSelectElement).value))"
				>
					<option value="" disabled>Choose…</option>
					<option v-for="r in pv.rows" :key="r.row" :value="r.row" :disabled="r.filled === 0">
						{{ rowLabel(r) }}
					</option>
				</select>
			</label>
			<label>
				Header spans
				<select
					:value="wiz.headerRows"
					:disabled="wiz.headerRow === null"
					@change="wiz.chooseHeader(wiz.headerRow!, Number(($event.target as HTMLSelectElement).value))"
				>
					<option v-for="n in 4" :key="n" :value="n">{{ n }} row{{ n > 1 ? 's' : '' }}</option>
				</select>
			</label>
		</div>

		<div class="grid-wrap">
			<table class="grid">
				<thead>
					<tr>
						<th class="rownum" />
						<th v-for="c in pv.columns" :key="c">{{ c }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in pv.rows"
						:key="r.row"
						:class="rowClass(r.row)"
						:title="r.filled ? 'Click to use this row as the header' : ''"
						@click="r.filled && wiz.chooseHeader(r.row)"
					>
						<th class="rownum">{{ r.row }}</th>
						<!-- cellHtml escapes all text -->
						<td v-for="(c, i) in r.cells" :key="i" :class="{ merged: c.m }" v-html="cellHtml(c)" />
					</tr>
				</tbody>
			</table>
		</div>
		<p v-if="pv.truncated" class="hint small">Showing the first {{ pv.rows.length }} rows of {{ pv.source.ref }}.</p>
		<p class="legend small">
			<span class="swatch header" /> header <span class="swatch merged" /> value copied from a merged cell
			<s class="struck">struck</s> strikethrough
		</p>
	</div>
</template>
