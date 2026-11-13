<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// The Help section: a contents list with search on the left, the open page in the middle and its
// headings on the right. Pages are the Markdown files in src/help/pages.
import { computed, nextTick, ref, watch } from 'vue';
import { HELP_HOME, HELP_PAGES, helpContents, helpPage, renderHelp, searchHelp } from '../../help';
import { useUi } from '../../stores/ui';

const ui = useUi();
const contents = helpContents();
const query = ref('');
const hits = computed(() => searchHelp(query.value));
const page = computed(() => helpPage(ui.helpPage) ?? helpPage(HELP_HOME) ?? HELP_PAGES[0]);
const html = computed(() => (page.value ? renderHelp(page.value) : ''));
const at = computed(() => HELP_PAGES.findIndex((p) => p.id === page.value?.id));
const previous = computed(() => (at.value > 0 ? HELP_PAGES[at.value - 1] : null));
const next = computed(() => (at.value >= 0 && at.value < HELP_PAGES.length - 1 ? HELP_PAGES[at.value + 1] : null));

const article = ref<HTMLElement | null>(null);
const scroller = ref<HTMLElement | null>(null);
const headings = ref<{ id: string; text: string; level: number }[]>([]);
const zoomed = ref<string | null>(null);

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/** Give the page's headings ids, list them, and go to the heading asked for (or the top). */
async function settle() {
	await nextTick();
	const root = article.value;
	if (!root) return;
	const found: { id: string; text: string; level: number }[] = [];
	for (const h of root.querySelectorAll<HTMLElement>('h2, h3')) {
		h.id = slug(h.textContent ?? '');
		found.push({ id: h.id, text: h.textContent ?? '', level: h.tagName === 'H2' ? 2 : 3 });
	}
	headings.value = found;
	const target = ui.helpAnchor ? root.querySelector<HTMLElement>(`#${CSS.escape(ui.helpAnchor)}`) : null;
	if (target) target.scrollIntoView();
	else scroller.value?.scrollTo({ top: 0 });
}
watch([() => page.value?.id, () => ui.helpAnchor, () => ui.tab], settle, { immediate: true });

function open(id: string) {
	query.value = '';
	ui.openHelp(id);
}
function toHeading(id: string) {
	article.value?.querySelector<HTMLElement>(`#${CSS.escape(id)}`)?.scrollIntoView({ behavior: 'smooth' });
}
/** Links to other help pages are followed here; a click on a screenshot shows it full size. */
function clicked(event: MouseEvent) {
	const el = event.target as HTMLElement;
	const link = el.closest('a');
	if (link) {
		const href = link.getAttribute('href') ?? '';
		if (href.startsWith('help:')) {
			event.preventDefault();
			ui.openHelp(href.slice(5));
		} else if (href.startsWith('#')) {
			event.preventDefault();
			toHeading(href.slice(1));
		}
		return;
	}
	if (el instanceof HTMLImageElement) zoomed.value = el.src;
}
</script>

<template>
	<div class="help">
		<aside class="card help-side">
			<input v-model="query" type="search" class="help-search" placeholder="Search the help…" aria-label="Search the help" />
			<div v-if="query.trim()" class="help-hits">
				<p v-if="!hits.length" class="hint">Nothing found for “{{ query.trim() }}”.</p>
				<button v-for="h in hits" :key="h.page.id" type="button" class="help-hit" @click="open(h.page.id)">
					<strong>{{ h.page.title }}</strong><span class="group">{{ h.page.group }}</span>
					<span class="snippet">{{ h.snippet }}</span>
				</button>
			</div>
			<nav v-else aria-label="Help contents">
				<details v-for="g in contents" :key="g.group" :open="g.pages.length <= 12 || g.pages.some((p) => p.id === page?.id)">
					<summary>{{ g.group }}</summary>
					<ul class="ref-nav">
						<li v-for="p in g.pages" :key="p.id" :class="{ current: p.id === page?.id }" @click="open(p.id)"><span class="name">{{ p.title }}</span></li>
					</ul>
				</details>
			</nav>
		</aside>

		<div ref="scroller" class="card help-main">
			<article v-if="page" class="help-page">
				<p class="help-crumb">{{ page.group }}</p>
				<h1>{{ page.title }}</h1>
				<!-- eslint-disable-next-line vue/no-v-html -- the app's own bundled pages -->
				<div ref="article" class="help-body" @click="clicked" v-html="html" />
				<footer class="help-foot">
					<button v-if="previous" type="button" class="secondary" @click="open(previous.id)">← {{ previous.title }}</button>
					<span class="spacer" />
					<button v-if="next" type="button" class="secondary" @click="open(next.id)">{{ next.title }} →</button>
				</footer>
			</article>
		</div>

		<aside v-if="headings.length > 1" class="help-toc">
			<strong>On this page</strong>
			<a v-for="h in headings" :key="h.id" href="#" :class="`level-${h.level}`" @click.prevent="toHeading(h.id)">{{ h.text }}</a>
		</aside>

		<div v-if="zoomed" class="help-zoom" role="dialog" aria-label="Screenshot" @click="zoomed = null">
			<img :src="zoomed" alt="" />
		</div>
	</div>
</template>
