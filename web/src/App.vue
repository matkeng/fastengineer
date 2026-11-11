<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import EnginePanel from './components/EnginePanel.vue';
import AuditView from './components/audit/AuditView.vue';
import ProjectsView from './components/projects/ProjectsView.vue';
import AppModal from './components/common/AppModal.vue';
import Icon from './components/common/Icon.vue';
import CompareView from './components/compare/CompareView.vue';
import DashboardView from './components/dashboard/DashboardView.vue';
import DeliverablesView from './components/deliverables/DeliverablesView.vue';
import GenView from './components/generators/GenView.vue';
import KeyListsView from './components/keylists/KeyListsView.vue';
import MelView from './components/mel/MelView.vue';
import SymView from './components/symbols/SymView.vue';
import { apiGet, lastConflict } from './lib/engine';
import { useCompare } from './stores/compare';
import { useDeliverables } from './stores/deliverables';
import { useGenerators } from './stores/generators';
import { useKeyLists } from './stores/keylists';
import { useMel } from './stores/mel';
import { useProjects } from './stores/projects';
import { useSymbols } from './stores/symbols';
import { SECTIONS, useUi } from './stores/ui';
import { useWorkbench } from './stores/workbench';

const wb = useWorkbench();
const ui = useUi();
const cmp = useCompare();
const mel = useMel();
const kl = useKeyLists();
const dl = useDeliverables();
const sym = useSymbols();
const projects = useProjects();
const gens = useGenerators();

// Results views fill the window; the table takes the free space.
const fill = computed(
	() =>
		wb.status === 'ready' &&
		((ui.tab === 'compare' && cmp.stage === 'result') ||
			ui.tab === 'mel' ||
			ui.tab === 'symbols' ||
			(ui.tab === 'generators' && !!gens.draft) ||
			ui.tab === 'keylists' ||
			ui.tab === 'deliverables'),
);
const dirty: Partial<Record<string, () => boolean>> = {
	symbols: () => sym.dirty,
	mel: () => mel.dirty,
	keylists: () => kl.dirty,
	generators: () => gens.anyDirty,
	deliverables: () => dl.dirty,
};
const sections = computed(() => SECTIONS.filter((s) => s.id !== 'projects' || projects.isAdmin));
// Sections that work without a project: the engine's own page and project administration.
const noProjectNeeded = computed(() => ui.tab === 'engine' || ui.tab === 'projects');

async function switchProject(event: Event) {
	const select = event.target as HTMLSelectElement;
	const unsaved = Object.values(dirty).some((isDirty) => isDirty?.());
	if (unsaved && !confirm('Discard unsaved changes and open the other project?')) {
		select.value = projects.currentId ?? '';
		return;
	}
	await projects.switchTo(select.value);
}

const sectionLabel = computed(() => SECTIONS.find((s) => s.id === ui.tab)?.label ?? '');

// Status bar
const host = computed(() => (wb.baseUrl ? new URL(wb.baseUrl).host : ''));
const who = ref<{ user: string; machine: string; server: boolean; host: string } | null>(null);
const conflictTime = computed(() => {
	const at = lastConflict.value?.changedAt;
	return at ? new Date(at).toLocaleString() : '';
});
const dataPath = ref('');
const ocr = ref<{ available: boolean; engine: string | null } | null>(null);
watch(
	() => wb.status,
	async (s) => {
		if (s !== 'ready') return;
		try {
			who.value = await apiGet('/api/whoami'); // first: it works even without a project
			dataPath.value = (await apiGet<{ path: string }>('/api/mel/storage')).path.replace(/[\\/][^\\/]+$/, '');
			ocr.value = await apiGet('/api/symbols/ocr');
		} catch {
			/* shown as unknown */
		}
	},
	{ immediate: true },
);

/** From symbol detection: show the list import its tags were sent to. */
async function openImport(recipeId: string) {
	if (mel.dirty && !confirm('Discard unsaved changes to the open list import?')) return;
	await mel.open(recipeId);
	mel.tab = 'overview';
	ui.go('mel');
}

onMounted(() => wb.connect());
</script>

<template>
	<div class="app">
		<header class="titlebar">
			<Icon name="logo" class="logo" />
			<h1>Drawing Workbench</h1>
			<span class="section">{{ sectionLabel }}</span>
			<label v-if="projects.mine.length" class="project-pick" title="Each project has its own database">
				Project
				<select :value="projects.currentId ?? ''" aria-label="Project" @change="switchProject">
					<option v-for="p in projects.mine" :key="p.id" :value="p.id">{{ p.name }}</option>
				</select>
			</label>
			<span class="spacer" />
			<span class="pill" :class="wb.status" :title="wb.error ?? ''">
				<span class="dot" />
				{{ wb.status === 'ready' ? 'Engine ready' : wb.status === 'connecting' ? 'Starting engine…' : 'Engine error' }}
			</span>
			<span v-if="wb.info" class="version">v{{ wb.info.core_version }}</span>
		</header>

		<nav class="menubar" aria-label="Sections">
			<button v-for="s in sections" :key="s.id" type="button" :class="{ active: ui.tab === s.id }" @click="ui.go(s.id)">
				<Icon :name="s.icon" />{{ s.label }}<span v-if="dirty[s.id]?.()" class="dirty-dot" title="Unsaved changes">●</span>
			</button>
		</nav>

		<main :class="{ fill }">
			<EnginePanel v-show="ui.tab === 'engine'" />
			<!-- v-show keeps each section's progress when switching between them -->
			<ProjectsView v-if="wb.status === 'ready' && ui.tab === 'projects' && projects.isAdmin" />
			<template v-if="wb.status === 'ready' && projects.current">
				<DashboardView v-if="ui.tab === 'dashboard'" />
				<CompareView v-show="ui.tab === 'compare'" />
				<SymView v-show="ui.tab === 'symbols'" @open-import="openImport" />
				<MelView v-show="ui.tab === 'mel'" />
				<KeyListsView v-show="ui.tab === 'keylists'" />
				<GenView v-show="ui.tab === 'generators'" />
				<DeliverablesView v-show="ui.tab === 'deliverables'" />
				<AuditView v-if="ui.tab === 'history'" />
			</template>
			<section v-else-if="wb.status === 'ready' && !noProjectNeeded" class="card">
				<h2>No project</h2>
				<p>You have not been added to a project yet. Ask an administrator to add you, then start the app again.</p>
				<p v-if="who" class="hint">You are signed in as <span class="mono">{{ who.user }}</span>.</p>
				<button v-if="projects.isAdmin" type="button" @click="ui.go('projects')">Manage projects</button>
			</section>
			<section v-else-if="!noProjectNeeded" class="card">
				<template v-if="wb.status === 'connecting'">
					<p>Waiting for the Python engine to start…</p>
					<p v-if="wb.slowStart" class="hint">
						The first start after installing or updating can take up to a minute while the engine unpacks and
						Windows checks it. Later starts are quicker.
					</p>
				</template>
				<template v-else>
					<p class="error">{{ wb.error }}</p>
					<button type="button" @click="wb.connect()">Retry</button>
				</template>
			</section>
		</main>

		<footer class="statusbar">
			<span><span class="dot" :style="{ display: 'inline-block', background: wb.status === 'ready' ? 'var(--ok)' : wb.status === 'error' ? 'var(--danger)' : 'var(--warn)' }" />
				engine {{ wb.status }}<template v-if="host"> · <span class="mono">{{ host }}</span></template>
				<template v-if="who?.server"> · shared server</template></span>
			<span v-if="projects.current">project: <span class="who">{{ projects.current.name }}</span></span>
			<span v-if="who" title="Changes you make are recorded under this name">user: <span class="who">{{ who.user }}</span></span>
			<span v-if="wb.info">{{ wb.info.compiled ? 'compiled' : 'Python ' + wb.info.python.split(' ')[0] }}</span>
			<span v-if="ocr">OCR: {{ ocr.available ? ocr.engine : 'not available' }}</span>
			<span v-if="dataPath" :title="dataPath">data: <span class="mono">{{ dataPath }}</span></span>
			<span class="spacer" />
			<span>AGPL-3.0-only · <a href="#" @click.prevent="ui.go('engine')">About</a></span>
		</footer>

		<AppModal :open="!!lastConflict" title="Changed by someone else" @close="lastConflict = null">
			<p>{{ lastConflict?.message }}</p>
			<p v-if="lastConflict?.changedBy" class="hint">
				Last changed by {{ lastConflict.changedBy }}<template v-if="conflictTime"> on {{ conflictTime }}</template>.
				Your change was not saved. The Change log shows what they changed.
			</p>
			<template #footer>
				<button type="button" class="secondary" @click="lastConflict = null; ui.go('history')">Open change log</button>
				<button type="button" @click="lastConflict = null">OK</button>
			</template>
		</AppModal>
	</div>
</template>
