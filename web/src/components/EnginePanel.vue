<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { ref, watch } from 'vue';
import { apiGet } from '../lib/engine';
import { runningInTauri } from '../lib/engine';
import { useWorkbench } from '../stores/workbench';

const wb = useWorkbench();
const name = ref('world');
const dataPath = ref<string | null>(null);
// Ask once the engine is up (this panel exists from start-up, before the engine is ready).
watch(
	() => wb.status,
	async (status) => {
		if (status !== 'ready' || dataPath.value) return;
		try {
			dataPath.value = (await apiGet<{ path: string }>('/api/mel/storage')).path;
		} catch {
			dataPath.value = 'unknown';
		}
	},
	{ immediate: true },
);
</script>

<template>
	<div>
		<section class="card">
			<h2>Engine</h2>
			<p class="status" :class="wb.status">
				<span class="dot" />
				<template v-if="wb.status === 'connecting'">Starting Python engine…</template>
				<template v-else-if="wb.status === 'ready'">Connected in {{ wb.connectMs }} ms</template>
				<template v-else>Engine unavailable</template>
			</p>
			<p v-if="wb.error" class="error">{{ wb.error }}</p>
			<button v-if="wb.status === 'error'" @click="wb.connect()">Retry</button>
			<dl v-if="wb.info">
				<dt>Shell</dt>
				<dd>{{ runningInTauri ? 'Tauri desktop' : 'Browser (dev)' }}</dd>
				<dt>Engine URL</dt>
				<dd><code>{{ wb.baseUrl }}</code></dd>
				<dt>Core version</dt>
				<dd>{{ wb.info.core_version }}</dd>
				<dt>Python</dt>
				<dd>{{ wb.info.python }} {{ wb.info.compiled ? '(Nuitka-compiled)' : '(interpreted)' }}</dd>
				<dt>Platform</dt>
				<dd>{{ wb.info.platform }}</dd>
				<dt>Saved imports</dt>
				<dd><code>{{ dataPath ?? '…' }}</code></dd>
				<dt>Engine PID</dt>
				<dd>{{ wb.info.pid }}</dd>
			</dl>
		</section>

		<section class="card">
			<h2>Say hello</h2>
			<form class="row" @submit.prevent="wb.sayHello(name)">
				<input v-model="name" placeholder="Your name" :disabled="wb.status !== 'ready'" />
				<button type="submit" :disabled="wb.status !== 'ready'">Send to engine</button>
			</form>
			<p v-if="wb.greeting" class="greeting">
				{{ wb.greeting.message }}
				<small>{{ new Date(wb.greeting.at).toLocaleTimeString() }}</small>
			</p>
		</section>

		<section class="card">
			<h2>Shared document model</h2>
			<p class="hint">One object, many views: these come from Pydantic models in <code>workbench_core</code>.</p>
			<button :disabled="wb.status !== 'ready'" @click="wb.loadDemoModel()">Load demo objects</button>
			<table v-if="wb.equipment.length">
				<thead>
					<tr><th>Tag</th><th>Description</th><th>kW</th><th>Views</th><th>UUID</th></tr>
				</thead>
				<tbody>
					<tr v-for="eq in wb.equipment" :key="eq.id">
						<td><strong>{{ eq.tag }}</strong></td>
						<td>{{ eq.description }}</td>
						<td>{{ eq.rating_kw ?? '—' }}</td>
						<td>{{ eq.views.join(', ') }}</td>
						<td><code>{{ eq.id.slice(0, 8) }}…</code></td>
					</tr>
				</tbody>
			</table>
		</section>
		<section class="card about">
			<h2>About</h2>
			<p>
				<strong>ECG Source List</strong> · Copyright © 2026 Matthew Kelly.
			</p>
			<p>
				This program is free software: you can redistribute it and/or modify it under the terms of the
				<strong>GNU Affero General Public License, version 3</strong> (AGPL-3.0-only) as published by the Free
				Software Foundation. It is distributed in the hope that it will be useful, but <strong>without any
				warranty</strong>; without even the implied warranty of merchantability or fitness for a particular purpose.
				See the license for details.
			</p>
			<p>
				Source code: <a href="https://github.com/matkeng/fastengineer" target="_blank" rel="noopener">github.com/matkeng/fastengineer</a>
				· License text: <a href="https://www.gnu.org/licenses/agpl-3.0.html" target="_blank" rel="noopener">gnu.org/licenses/agpl-3.0</a>
				(also <code>LICENSE.txt</code> next to the app) · Third-party components: <code>THIRD_PARTY_LICENSES.md</code>.
			</p>
		</section>
	</div>
</template>