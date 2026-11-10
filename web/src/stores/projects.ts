// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { AuditEntry } from '../lib/auditTypes';
import { ApiError, apiDelete, apiGet, apiPostJson, apiPut, setProject } from '../lib/engine';

export interface Project { id: string; name: string; archived: boolean }
export interface ProjectDetail extends Project {
	folder: string;
	external: boolean; // kept outside the engine's data folder: can be taken off the list
	members: string[];
	created_at: string;
	created_by: string;
}
interface MyProjects { projects: Project[]; current: string | null; is_admin: boolean; enforced: boolean }
interface AllProjects { projects: ProjectDetail[]; users: string[]; default_folder: string; missing: string[]; enforced: boolean }
export interface NewProject { name: string; path: string | null; copy_from: string | null; members: string[] }

/** Projects: each has its own database. The user works in one at a time. */
export const useProjects = defineStore('projects', () => {
	const mine = ref<Project[]>([]);
	const currentId = ref<string | null>(null);
	const isAdmin = ref(false);
	const enforced = ref(false); // false: every project is open to everyone
	const loaded = ref(false);
	const current = computed(() => mine.value.find((p) => p.id === currentId.value) ?? null);

	// administration
	const all = ref<ProjectDetail[]>([]);
	const users = ref<string[]>([]);
	const defaultFolder = ref('');
	const missing = ref<string[]>([]); // folders the engine was pointed at that are not there now
	const log = ref<AuditEntry[]>([]);
	const busy = ref(false);
	const error = ref<string | null>(null);
	const fieldErrors = ref<Record<string, string>>({});

	/** Which projects this user has, and the one to start in (the one they had open last). */
	async function load() {
		const res = await apiGet<MyProjects>('/api/projects');
		mine.value = res.projects;
		isAdmin.value = res.is_admin;
		enforced.value = res.enforced;
		currentId.value = res.current;
		setProject(res.current);
		loaded.value = true;
	}

	/** Open another project. Every view holds the old project's data, so the app starts afresh in the new one. */
	async function switchTo(id: string) {
		if (id === currentId.value) return;
		await apiPostJson(`/api/projects/${id}/open`, {});
		location.reload();
	}

	async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
		busy.value = true;
		error.value = null;
		fieldErrors.value = {};
		try {
			return await fn();
		} catch (err) {
			error.value = err instanceof Error ? err.message : String(err);
			if (err instanceof ApiError) fieldErrors.value = err.fields;
			return undefined;
		} finally {
			busy.value = false;
		}
	}

	async function loadAll() {
		await run(async () => {
			const res = await apiGet<AllProjects>('/api/projects/all');
			all.value = res.projects;
			users.value = res.users;
			defaultFolder.value = res.default_folder;
			missing.value = res.missing;
			log.value = await apiGet<AuditEntry[]>('/api/projects/log', { limit: 50 });
		});
	}

	async function refresh() {
		await loadAll();
		const before = currentId.value;
		await load().catch(() => undefined);
		// Stay where we are unless that project was just taken away or archived.
		if (before && mine.value.some((p) => p.id === before)) {
			currentId.value = before;
			setProject(before);
		}
	}

	async function create(body: NewProject) {
		const p = await run(() => apiPostJson<ProjectDetail>('/api/projects', body));
		if (p) await refresh();
		return p;
	}

	async function update(id: string, body: { name?: string; archived?: boolean; members?: string[] }) {
		const p = await run(() => apiPut<ProjectDetail>(`/api/projects/${id}`, body));
		if (p) await refresh();
		return p;
	}

	/** List a project folder that already exists; it brings its own name, members and history. */
	async function attach(path: string) {
		const p = await run(() => apiPostJson<ProjectDetail>('/api/projects/attach', { path }));
		if (p) await refresh();
		return p;
	}

	/** Take a project off this engine's list. Its folder is not touched. */
	async function detach(id: string) {
		const ok = await run(() => apiDelete(`/api/projects/${id}`));
		if (ok !== undefined) await refresh();
		return ok !== undefined;
	}

	async function forget(path: string) {
		if (await run(() => apiPostJson('/api/projects/forget', { path }))) await refresh();
	}

	return {
		mine, currentId, current, isAdmin, enforced, loaded, all, users, defaultFolder, missing, log, busy, error, fieldErrors,
		load, switchTo, loadAll, create, update, attach, detach, forget,
	};
});
