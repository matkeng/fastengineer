<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed } from 'vue';
import { useStage } from '../../lib/useStage';
import { useMel } from '../../stores/mel';

const mel = useMel();
const { result } = useStage('source', () => null);

const rows = computed(() => {
	const rules = new Map(mel.draft!.columns.map((c) => [c.header, c]));
	return (result.value?.source_headers ?? []).map((h) => ({
		header: h,
		visible: rules.get(h)?.visible ?? true,
		rename: rules.get(h)?.rename ?? '',
		isKey: h === result.value?.key_header,
	}));
});
const missing = computed(() => {
	const have = new Set(result.value?.source_headers ?? []);
	return mel.draft!.columns.filter((c) => !have.has(c.header));
});

/** Store a rule only when it differs from the default (shown, not renamed). */
function update(header: string, patch: { visible?: boolean; rename?: string }) {
	const d = mel.draft!;
	const cur = d.columns.find((c) => c.header === header) ?? { header, visible: true, rename: null };
	const next = { ...cur, ...patch, rename: (patch.rename ?? cur.rename ?? '').trim() || null };
	d.columns = d.columns.filter((c) => c.header !== header);
	if (!next.visible || next.rename) d.columns.push(next);
}

function setAll(visible: boolean) {
	for (const r of rows.value) if (!r.isKey) update(r.header, { visible });
}
</script>

<template>
	<div>
		<p class="hint">
			Hide columns you don't need and rename the ones you keep. Later rules use the new names. The key column
			({{ result?.key_header }}) is always kept and can't be renamed.
		</p>
		<div class="row">
			<button type="button" class="secondary small" @click="setAll(true)">Show all</button>
			<button type="button" class="secondary small" @click="setAll(false)">Hide all</button>
			<span class="hint">{{ rows.filter((r) => r.visible).length }} of {{ rows.length }} columns kept</span>
		</div>
		<div class="grid-wrap">
			<table class="grid simple cols-editor">
				<thead><tr><th>Keep</th><th>Column in file</th><th>New name</th></tr></thead>
				<tbody>
					<tr v-for="r in rows" :key="r.header" :class="{ off: !r.visible }">
						<td><input type="checkbox" :checked="r.visible" :disabled="r.isKey" @change="update(r.header, { visible: ($event.target as HTMLInputElement).checked })" /></td>
						<td>{{ r.header }} <span v-if="r.isKey" class="badge">key</span></td>
						<td>
							<input :value="r.rename" :disabled="r.isKey || !r.visible" :placeholder="r.header"
								@change="update(r.header, { rename: ($event.target as HTMLInputElement).value })" />
						</td>
					</tr>
				</tbody>
			</table>
		</div>
		<div v-if="missing.length" class="health">
			<h4>Rules for columns not in the latest file</h4>
			<ul>
				<li v-for="c in missing" :key="c.header">
					{{ c.header }} ({{ c.visible ? `rename to ${c.rename}` : 'hidden' }})
					<button type="button" class="link" @click="mel.draft!.columns = mel.draft!.columns.filter((x) => x !== c)">remove rule</button>
				</li>
			</ul>
		</div>
	</div>
</template>
