<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useRefData } from '../../stores/refdata';
import RefEnumEditor from './RefEnumEditor.vue';
import RefTableEditor from './RefTableEditor.vue';

const rd = useRefData();
const newName = ref({ enum: '', table: '' });
const createError = ref<{ kind: string; msg: string } | null>(null);

async function create(kind: 'enum' | 'table') {
	createError.value = null;
	const name = newName.value[kind].trim();
	if (!name) return;
	if (await rd.create(kind, name)) newName.value[kind] = '';
	else if (rd.error) createError.value = { kind, msg: rd.error };
}

onMounted(() => rd.refresh());
</script>

<template>
	<div class="ref">
		<div class="ref-layout">
			<aside class="card ref-side">
				<section>
					<h3>Lists</h3>
					<p class="hint">Enumerated values with a code, value and description.</p>
					<ul class="ref-nav">
						<li v-for="e in rd.overview.enums" :key="e.id"
							:class="{ current: rd.selected?.kind === 'enum' && rd.selected.id === e.id }" @click="rd.select('enum', e.id)">
							<span class="name">{{ e.name }}</span><span class="count">{{ e.items }}</span>
						</li>
					</ul>
					<form class="row tight" @submit.prevent="create('enum')">
						<input v-model="newName.enum" placeholder="New list name" aria-label="New list name" />
						<button type="submit" class="small" :disabled="!newName.enum.trim()">Add</button>
					</form>
					<p v-if="createError?.kind === 'enum'" class="warn small">{{ createError.msg }}</p>
				</section>
				<section>
					<h3>Tables</h3>
					<p class="hint">Your own tables with typed columns.</p>
					<ul class="ref-nav">
						<li v-for="t in rd.overview.tables" :key="t.id"
							:class="{ current: rd.selected?.kind === 'table' && rd.selected.id === t.id }" @click="rd.select('table', t.id)">
							<span class="name">{{ t.name }}</span><span class="count" :title="`${t.columns} columns`">{{ t.rows }}</span>
						</li>
					</ul>
					<form class="row tight" @submit.prevent="create('table')">
						<input v-model="newName.table" placeholder="New table name" aria-label="New table name" />
						<button type="submit" class="small" :disabled="!newName.table.trim()">Add</button>
					</form>
					<p v-if="createError?.kind === 'table'" class="warn small">{{ createError.msg }}</p>
				</section>
			</aside>
			<RefEnumEditor v-if="rd.selected?.kind === 'enum' && rd.enumDraft" :key="rd.selected.id" />
			<RefTableEditor v-else-if="rd.selected?.kind === 'table' && rd.tableDraft" :key="rd.selected.id" />
			<section v-else class="card wizard ref-empty">
				<h2>Lists &amp; tables</h2>
				<p class="hint">
					Create a <strong>list</strong> for values you pick from (starter types, voltages, areas…), then a
					<strong>table</strong> whose columns can be text, numbers, yes/no, or a value from one of your lists.
					Everything is saved on this computer and is there next time.
				</p>
				<p v-if="rd.error" class="error">{{ rd.error }}</p>
			</section>
		</div>
	</div>
</template>
