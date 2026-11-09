import { defineStore } from 'pinia';
import { ref } from 'vue';
import { getJson, resolveEngineUrl, waitForEngine } from '../lib/engine';
import type { EngineInfo, Equipment, Greeting } from '../lib/types';

// The shared document model store (spec section 4). Every editor will read
// and write this; for the PoC it holds engine status and a few objects.
export const useWorkbench = defineStore('workbench', () => {
	const baseUrl = ref<string | null>(null);
	const status = ref<'connecting' | 'ready' | 'error'>('connecting');
	const error = ref<string | null>(null);
	const info = ref<EngineInfo | null>(null);
	const greeting = ref<Greeting | null>(null);
	const equipment = ref<Equipment[]>([]);
	const startedAt = performance.now();
	const connectMs = ref<number | null>(null);
	const slowStart = ref(false); // shown after a few seconds of waiting

	async function connect() {
		status.value = 'connecting';
		error.value = null;
		slowStart.value = false;
		const slow = setTimeout(() => (slowStart.value = true), 5000);
		try {
			baseUrl.value = await resolveEngineUrl();
			await waitForEngine(baseUrl.value);
			info.value = await getJson<EngineInfo>(baseUrl.value, '/api/info');
			connectMs.value = Math.round(performance.now() - startedAt);
			status.value = 'ready';
		} catch (err) {
			status.value = 'error';
			error.value = String(err);
		} finally {
			clearTimeout(slow);
		}
	}

	async function sayHello(name: string) {
		if (!baseUrl.value) return;
		greeting.value = await getJson<Greeting>(
			baseUrl.value,
			`/api/hello?name=${encodeURIComponent(name)}`,
		);
	}

	async function loadDemoModel() {
		if (!baseUrl.value) return;
		equipment.value = await getJson<Equipment[]>(baseUrl.value, '/api/model/demo');
	}

	return { baseUrl, status, error, info, greeting, equipment, connectMs, slowStart, connect, sayHello, loadDemoModel };
});
