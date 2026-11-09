import { invoke, isTauri } from '@tauri-apps/api/core';

// In the desktop app the Rust shell picks a free port and tells us via the
// `engine_url` command. In a plain browser (`npm run dev`) we fall back to a
// manually started engine on the default port.
const DEV_ENGINE_URL = import.meta.env.VITE_ENGINE_URL ?? 'http://127.0.0.1:8765';

export const runningInTauri = isTauri();

let engineUrl: Promise<string> | null = null;

export function resolveEngineUrl(): Promise<string> {
	engineUrl ??= (runningInTauri ? invoke<string>('engine_url') : Promise.resolve(DEV_ENGINE_URL)).catch(
		(err) => {
			engineUrl = null; // allow a retry
			throw err;
		},
	);
	return engineUrl;
}

async function request<T>(path: string, init?: RequestInit, baseUrl?: string, as: 'json' | 'blob' = 'json'): Promise<T> {
	const base = baseUrl ?? (await resolveEngineUrl());
	const res = await fetch(`${base}${path}`, init);
	if (!res.ok) {
		// FastAPI errors look like {"detail": "..."}; show that to the user.
		let detail = `${res.status} ${res.statusText}`;
		try {
			const body = await res.json();
			if (typeof body.detail === 'string') detail = body.detail;
			else if (body.detail) detail = JSON.stringify(body.detail);
		} catch {
			/* not JSON */
		}
		throw new Error(detail);
	}
	return (as === 'blob' ? await res.blob() : await res.json()) as T;
}

export function getJson<T>(baseUrl: string, path: string): Promise<T> {
	return request<T>(path, undefined, baseUrl);
}

export function apiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
	const qs = params ? `?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}` : '';
	return request<T>(`${path}${qs}`);
}

export function apiPostJson<T>(path: string, body: unknown): Promise<T> {
	return request<T>(path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
}

/** POST JSON and get a file back (e.g. an .xlsx export). */
export function apiPostJsonForBlob(path: string, body: unknown): Promise<Blob> {
	return request<Blob>(path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	}, undefined, 'blob');
}

export function apiPostBytes<T>(path: string, body: Blob | ArrayBuffer): Promise<T> {
	return request<T>(path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/octet-stream' },
		body,
	});
}

export function apiDelete(path: string): Promise<unknown> {
	return request(path, { method: 'DELETE' });
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
