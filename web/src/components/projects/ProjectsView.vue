<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { clientIdentity, runningInTauri } from '../../lib/engine';
import { type ProjectDetail, useProjects } from '../../stores/projects';
import MemberList from './MemberList.vue';
import { useUi } from '../../stores/ui';
import LoadListReset from '../keylists/LoadListReset.vue';

// Administrators: create projects, choose who may open each one, rename and archive.
const pr = useProjects();
const ui = useUi();
const selectedId = ref<string | null>(null);
const selected = computed(() => pr.all.find((p) => p.id === selectedId.value) ?? null);
const edit = reactive({ name: '', members: [] as string[] });
const fresh = reactive({ name: '', copyFrom: '', path: '', members: [] as string[] });
const existing = ref(''); // folder of a project to add as it is
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

async function browse(target: 'new' | 'existing') {
	const { open } = await import('@tauri-apps/plugin-dialog');
	const folder = await open({ directory: true, title: target === 'new' ? 'Folder for the new project' : 'Project folder to open' });
	if (typeof folder !== 'string') return;
	if (target === 'new') fresh.path = folder;
	else existing.value = folder;
}

async function attach() {
	const p = await pr.attach(existing.value);
	if (!p) return;
	existing.value = '';
	pick(pr.all.find((x) => x.id === p.id) ?? null);
	saved.value = `Added ${p.name}`;
}

async function detach() {
	const p = selected.value;
	if (!p) return;
	if (!confirm(`Take "${p.name}" off the list? Nobody will be able to open it from this engine. Its folder is not deleted:\n${p.folder}`)) return;
	if (await pr.detach(p.id)) pick(null);
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
				Each project is a folder that is complete on its own: its data, drawings and change log, and its own name and members.
				A project folder can be copied, moved or backed up by itself.
				<template v-if="pr.enforced">People only see the projects they are a member of.</template>
				<template v-else>Every project is open to everyone who uses this engine.</template>
			</p>
			<p v-if="pr.error" class="error">{{ pr.error }}</p>
			<div v-for="m in pr.missing" :key="m" class="warn missing">
				Project folder not found: <span class="mono">{{ m }}</span>
				<button type="button" class="secondary small" :disabled="pr.busy" title="If it was moved, add it again from its new place below"
					@click="pr.forget(m)">Stop looking for it</button>
			</div>
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

		<section class="card tool-card">
			<h2>Compare tables</h2>
			<div class="row">
				<p class="hint">
					Pick an old and a new table from Excel (two revisions of a list, say) and see what was added, deleted, struck
					out and changed between them. Nothing is saved in the project.
				</p>
				<span class="spacer" />
				<button type="button" :disabled="!pr.current" :title="pr.current ? '' : 'Open a project first'" @click="ui.go('compare')">Open Compare tables</button>
			</div>
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
					<button v-if="selected.external && selected.id !== pr.currentId" type="button" class="secondary" :disabled="pr.busy"
						title="Stop serving this project here. Its folder is left as it is." @click="detach">Remove from list</button>
					<button v-if="!selected.archived && selected.id !== pr.currentId" type="button" class="secondary"
						:disabled="pr.busy || editDirty" @click="pr.switchTo(selected.id)">Open this project</button>
					<span v-if="saved" class="saved">✓ {{ saved }}</span>
				</div>
			</form>
			<div class="project-resets">
				<h3>Reset the Load List</h3>
				<template v-if="selected.id === pr.currentId">
					<p class="hint">
						Start this project's Load List again from its MEL and EEL imports: all of it, or only the plant areas, load types,
						panels and supplies, cable details or deleted rows. You choose what goes and confirm before anything changes.
					</p>
					<LoadListReset :project="selected.name" />
				</template>
				<p v-else class="hint">Open this project to reset its Load List.</p>
			</div>
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
						<input v-model="fresh.path" class="mono wide" :placeholder="`Leave empty to keep it in ${pr.defaultFolder}`" />
						<button v-if="canBrowse" type="button" class="secondary" @click="browse('new')">Browse…</button>
					</span>
				</label>
				<p class="hint">
					A new or empty folder on a local disk of the machine the engine runs on, not a network share.
				</p>
				<div class="field">
					<span>Members</span>
					<MemberList v-model="fresh.members" :known="pr.users" list-id="members-new" />
				</div>
				<div class="row"><button type="submit" :disabled="!fresh.name.trim() || pr.busy">Create project</button></div>
			</form>
		</section>

		<section class="card">
			<h2>Open an existing project folder</h2>
			<p class="hint">
				For a project folder that was moved, restored from a backup, or copied from another PC or server.
				It keeps its own name, members, data and history.
			</p>
			<form class="project-form" @submit.prevent="attach">
				<label>Folder
					<span class="row">
						<input v-model="existing" class="mono wide" placeholder="The folder that contains workbench.db" />
						<button v-if="canBrowse" type="button" class="secondary" @click="browse('existing')">Browse…</button>
					</span>
				</label>
				<div class="row"><button type="submit" :disabled="!existing.trim() || pr.busy">Add project</button></div>
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
