import { invoke, isTauri } from '@tauri-apps/api/core';

// In the desktop app the Rust shell picks a free port and tells us via the
// `engine_url` command. In a plain browser (`npm run dev`) we fall back to a
// manually started engine on the default port.
const DEV_ENGINE_URL = import.meta.env.VITE_ENGINE_URL ?? 'http://127.0.0.1:8765';

export const runningInTauri = isTauri();

export async function resolveEngineUrl(): Promise<string> {
	if (runningInTauri) return invoke<string>('engine_url');
	return DEV_ENGINE_URL;
}

export async function getJson<T>(baseUrl: string, path: string): Promise<T> {
	const res = await fetch(`${baseUrl}${path}`);
	if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
	return (await res.json()) as T;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// The compiled sidecar can take a few seconds on first launch (onefile
// extraction, antivirus scan), so poll the health endpoint.
export async function waitForEngine(baseUrl: string, timeoutMs = 30000): Promise<void> {
	const start = Date.now();
	let lastError: unknown;
	while (Date.now() - start < timeoutMs) {
		try {
			await getJson(baseUrl, '/api/health');
			return;
		} catch (err) {
			lastError = err;
			await sleep(300);
		}
	}
	throw new Error(`Engine did not respond within ${timeoutMs / 1000}s: ${String(lastError)}`);
}
