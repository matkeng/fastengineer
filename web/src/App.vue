<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { runningInTauri } from './lib/engine';
import { useWorkbench } from './stores/workbench';

const wb = useWorkbench();
const name = ref('world');

onMounted(() => wb.connect());
</script>

<template>
	<main>
		<header>
			<h1>Drawing Workbench</h1>
			<p class="sub">Hello-world proof of concept · Tauri 2 shell · Vue 3 + Pinia · Python engine sidecar</p>
		</header>

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
	</main>
</template>
