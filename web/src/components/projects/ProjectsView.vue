<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { clientIdentity, runningInTauri } from '../../lib/engine';
import { type ProjectDetail, useProjects } from '../../stores/projects';
import MemberList from './MemberList.vue';

// Administrators: create projects, choose who may open each one, rename and archive.
const pr = useProjects();
const selectedId = ref<string | null>(null);
const selected = computed(() => pr.all.find((p) => p.id === selectedId.value) ?? null);
const edit = reactive({ name: '', members: [] as string[] });
const fresh = reactive({ name: '', copyFrom: '', path: '', members: [] as string[] });
const saved = ref<string | null>(null);
const canBrowse = ref(false); // only when the engine runs on this PC: the folder is on the engine's disks
const when = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const ACTIONS = { create: 'Created', update: 'Changed', delete: 'Deleted' } as const;

function pick(p: ProjectDetail | null) {
	selectedId.value = p?.id ?? null;
	edit.name = p?.name ?? '';
	edit.members = [...(p?.members ?? [])];
	saved.value = null;
	pr.error = null;
	pr.fieldErrors = {};
}
const editDirty = computed(() => !!selected.value
	&& (edit.name !== selected.value.name || edit.members.join('\n') !== selected.value.members.join('\n')));

async function create() {
	const p = await pr.create({
		name: fresh.name, path: fresh.path.trim() || null, copy_from: fresh.copyFrom || null, members: fresh.members,
	});
	if (!p) return;
	Object.assign(fresh, { name: '', copyFrom: '', path: '', members: [] });
	pick(pr.all.find((x) => x.id === p.id) ?? null);
	saved.value = `Created ${p.name}`;
}

async function save() {
	if (!selected.value) return;
	const p = await pr.update(selected.value.id, { name: edit.name, members: edit.members });
	if (p) { pick(pr.all.find((x) => x.id === p.id) ?? null); saved.value = 'Saved'; }
}

async function archive(archived: boolean) {
	const p = selected.value;
	if (!p) return;
	if (archived && !confirm(`Archive "${p.name}"? Nobody will be able to open it until it is restored. Its data is kept.`)) return;
	if (await pr.update(p.id, { archived })) saved.value = archived ? 'Archived' : 'Restored';
}

async function browse() {
	const { open } = await import('@tauri-apps/plugin-dialog');
	const folder = await open({ directory: true, title: 'Folder for the project' });
	if (typeof folder === 'string') fresh.path = folder;
}

function summary(changes: { path: string; old: unknown; new: unknown }[]): string {
	return changes.filter((c) => c.path).map((c) => (c.path === '(note)' ? String(c.new) : c.path)).join(', ');
}

onMounted(async () => {
	canBrowse.value = runningInTauri && !(await clientIdentity()).remote;
	await pr.loadAll();
});
// A project removed from under the selection (never happens today, but archive order changes the list).
watch(() => pr.all, () => { if (selectedId.value && !selected.value) pick(null); });
</script>

<template>
	<div class="projects">
		<section class="card">
			<h2>Projects</h2>
			<p class="hint">
				Each project has its own database: its own lists, tables, drawings, imports, generators and change log.
				<template v-if="pr.enforced">People only see the projects they are a member of.</template>
				<template v-else>Every project is open to everyone who uses this engine.</template>
			</p>
			<p v-if="pr.error" class="error">{{ pr.error }}</p>
			<table class="projects-table">
				<thead><tr><th>Project</th><th>Members</th><th>Folder</th><th /></tr></thead>
				<tbody>
					<tr v-for="p in pr.all" :key="p.id" :class="{ active: p.id === selectedId, archived: p.archived }" @click="pick(p)">
						<td>{{ p.name }}<span v-if="p.id === pr.currentId" class="badge">open</span>
							<span v-if="p.archived" class="hint"> (archived)</span></td>
						<td>{{ p.members.length || '—' }}</td>
						<td class="mono">{{ p.folder }}</td>
						<td><button type="button" class="secondary small">Edit</button></td>
					</tr>
				</tbody>
			</table>
		</section>

		<section v-if="selected" class="card">
			<h2>{{ selected.name }}</h2>
			<form class="project-form" @submit.prevent="save">
				<label>Name
					<input v-model="edit.name" :class="{ invalid: pr.fieldErrors.name }" />
				</label>
				<div class="field">
					<span>Members</span>
					<MemberList v-model="edit.members" :known="pr.users" list-id="members-edit" />
				</div>
				<p class="hint">Folder: <span class="mono">{{ selected.folder }}</span><br />
					Created by {{ selected.created_by }} on {{ when.format(new Date(selected.created_at)) }}.</p>
				<div class="row">
					<button type="submit" :disabled="!editDirty || pr.busy">Save</button>
					<button v-if="!selected.archived" type="button" class="secondary" :disabled="pr.busy" @click="archive(true)">Archive</button>
					<button v-else type="button" class="secondary" :disabled="pr.busy" @click="archive(false)">Restore</button>
					<button v-if="!selected.archived && selected.id !== pr.currentId" type="button" class="secondary"
						:disabled="pr.busy || editDirty" @click="pr.switchTo(selected.id)">Open this project</button>
					<span v-if="saved" class="saved">✓ {{ saved }}</span>
				</div>
			</form>
		</section>

		<section class="card">
			<h2>New project</h2>
			<form class="project-form" @submit.prevent="create">
				<label>Name
					<input v-model="fresh.name" placeholder="e.g. Plant A expansion" :class="{ invalid: !selected && pr.fieldErrors.name }" />
				</label>
				<label>Start with
					<select v-model="fresh.copyFrom">
						<option value="">Nothing (an empty project)</option>
						<option v-for="p in pr.all" :key="p.id" :value="p.id">
							The lists, tables, symbol libraries and card types of {{ p.name }}
						</option>
					</select>
				</label>
				<label>Folder (optional)
					<span class="row">
						<input v-model="fresh.path" class="mono wide" :placeholder="`Leave empty to keep it in ${pr.defaultFolder}`"
							:class="{ invalid: pr.fieldErrors.path }" />
						<button v-if="canBrowse" type="button" class="secondary" @click="browse">Browse…</button>
					</span>
				</label>
				<p class="hint">
					A folder on a local disk of the machine the engine runs on, not a network share.
					If it already holds a project database, that project is opened as it is.
				</p>
				<div class="field">
					<span>Members</span>
					<MemberList v-model="fresh.members" :known="pr.users" list-id="members-new" />
				</div>
				<div class="row"><button type="submit" :disabled="!fresh.name.trim() || pr.busy">Create project</button></div>
			</form>
		</section>

		<section v-if="pr.log.length" class="card">
			<h2>Project changes</h2>
			<table class="projects-table">
				<thead><tr><th>When</th><th>User</th><th>Action</th><th>Project</th><th>What changed</th></tr></thead>
				<tbody>
					<tr v-for="e in pr.log" :key="e.id">
						<td>{{ when.format(new Date(e.at)) }}</td>
						<td>{{ e.user }}</td>
						<td>{{ ACTIONS[e.action] }}</td>
						<td>{{ e.label }}</td>
						<td>{{ e.action === 'update' ? summary(e.changes) : summary(e.changes.filter((c) => c.path === '(note)')) }}</td>
					</tr>
				</tbody>
			</table>
		</section>
	</div>
</template>
