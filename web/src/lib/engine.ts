// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { invoke, isTauri } from '@tauri-apps/api/core';
import { ref } from 'vue';

// In the desktop app the Rust shell picks a free port and tells us via the
// `engine_url` command. In a plain browser (`npm run dev`) we fall back to a
// manually started engine on the default port.
const DEV_ENGINE_URL = import.meta.env.VITE_ENGINE_URL ?? 'http://127.0.0.1:8765';

export const runningInTauri = isTauri();

let engineUrl: Promise<string> | null = null;

/** An engine error; `fields` maps a field (or column/item id) to its message. */
export class ApiError extends Error {
	constructor(message: string, public fields: Record<string, string> = {}) {
		super(message);
	}
}

/** A save refused because a colleague changed the record first. */
export class ConflictError extends ApiError {
	constructor(message: string, public changedBy: string, public changedAt: string) {
		super(message);
	}
}

/** The latest refused save, for the app-wide "changed by someone else" dialog. */
export const lastConflict = ref<ConflictError | null>(null);

/** Who is using the app, and whether the engine is a shared server on another machine. */
export interface ClientIdentity {
	user: string; // Windows login, e.g. ACME\jsmith; '' lets a local engine use its own login
	machine: string;
	remote: boolean;
}

let identity: Promise<ClientIdentity> | null = null;

export function clientIdentity(): Promise<ClientIdentity> {
	identity ??= runningInTauri
		? invoke<ClientIdentity>('client_identity').catch(() => ({ user: '', machine: '', remote: false }))
		: // Plain browser (development): ?user=NAME stands in for the Windows login.
			Promise.resolve({ user: new URLSearchParams(location.search).get('user') ?? '', machine: 'browser', remote: false });
	return identity;
}

// The version (ETag) of each record as last read or saved, by URL path. Sent back as
// If-Match so the engine can refuse a save made over a colleague's newer version.
const versions = new Map<string, string>();
const pathOnly = (path: string) => path.split('?')[0];

async function withIdentity(path: string, init?: RequestInit): Promise<RequestInit> {
	const who = await clientIdentity();
	const headers = new Headers(init?.headers);
	if (who.user) headers.set('X-Workbench-User', who.user);
	if (who.machine) headers.set('X-Workbench-Machine', who.machine);
	const method = init?.method ?? 'GET';
	const seen = versions.get(pathOnly(path));
	if (seen && (method === 'PUT' || method === 'DELETE') && !headers.has('If-Match')) headers.set('If-Match', seen);
	return { ...init, headers };
}

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
	const res = await fetch(`${base}${path}`, await withIdentity(path, init));
	if (!res.ok) {
		// FastAPI errors look like {"detail": "..."}; show that to the user.
		let detail = `${res.status} ${res.statusText}`;
		let fields: Record<string, string> = {};
		let body: Record<string, unknown> = {};
		try {
			body = await res.json();
			if (typeof body.detail === 'string') detail = body.detail;
			else if (body.detail) detail = JSON.stringify(body.detail);
			if (body.fields && typeof body.fields === 'object') fields = body.fields as Record<string, string>;
		} catch {
			/* not JSON */
		}
		if (res.status === 409 && body.conflict) {
			const conflict = new ConflictError(detail, String(body.changed_by ?? ''), String(body.changed_at ?? ''));
			lastConflict.value = conflict;
			throw conflict;
		}
		throw new ApiError(detail, fields);
	}
	const method = init?.method ?? 'GET';
	const etag = res.headers.get('ETag');
	if (method === 'DELETE') versions.delete(pathOnly(path));
	else if (etag && (method === 'GET' || method === 'PUT')) versions.set(pathOnly(path), etag);
	return (as === 'blob' ? await res.blob() : await res.json()) as T;
}

export function getJson<T>(baseUrl: string, path: string): Promise<T> {
	return request<T>(path, undefined, baseUrl);
}

export function apiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
	const qs = params ? `?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}` : '';
	return request<T>(`${path}${qs}`);
}

/** GET a file (e.g. a page image) as a Blob. */
export function apiGetBlob(path: string): Promise<Blob> {
	return request<Blob>(path, undefined, undefined, 'blob');
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

export function apiPut<T>(path: string, body: unknown): Promise<T> {
	return request<T>(path, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
}

export function apiPutBytes<T>(path: string, body: Blob | ArrayBuffer): Promise<T> {
	return request<T>(path, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/octet-stream' },
		body,
	});
}

export function apiDelete(path: string, headers?: Record<string, string>): Promise<unknown> {
	return request(path, { method: 'DELETE', headers });
}

/** PUT with extra headers (e.g. the time a table row was last seen, for the conflict check). */
export function apiPutWith<T>(path: string, body: unknown, headers: Record<string, string>): Promise<T> {
	return request<T>(path, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json', ...headers },
		body: JSON.stringify(body),
	});
}

/**
 * Export to the file the user picked in the Save As dialog (desktop app only).
 * A local engine writes the file itself. A shared server can't see this PC's
 * disks, so it sends the file back and the desktop shell writes it here.
 */
export async function exportToPath(url: string, body: object, path: string): Promise<{ path: string }> {
	if (!(await clientIdentity()).remote) return apiPostJson<{ path: string }>(url, { ...body, path });
	const blob = await apiPostJsonForBlob(url, body);
	await invoke('save_bytes', { path, bytes: Array.from(new Uint8Array(await blob.arrayBuffer())) });
	return { path };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// The compiled sidecar can be slow on first launch (onefile extraction plus an
// antivirus scan took ~25 s on a cold CI machine), so poll generously.
export async function waitForEngine(baseUrl: string, timeoutMs = 120000): Promise<void> {
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
