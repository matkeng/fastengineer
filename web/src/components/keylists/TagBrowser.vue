<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
// What a template row's cells can use, beside the rows while they are edited: the row's own
// tags, the linked records' fields (dot notation, <<LoadType.Name>>), the type's component
// tables and the modifiers after | (<<Tag|upper>>). Searchable; a click puts one in the cell.
import { computed, ref } from 'vue';
import { type TagModifier, modifierText } from '../../lib/keyListTypes';

interface Tag { tag: string; meaning: string }
const props = defineProps<{ tags: Tag[]; paths: Tag[]; tables?: Tag[]; modifiers: TagModifier[]; what: string }>();
const emit = defineEmits<{ pick: [text: string] }>();
const query = ref('');
const closed = ref(new Set<string>());

const words = computed(() => query.value.toLowerCase().split(/\s+/).filter(Boolean));
const hit = (...texts: string[]) => {
	const hay = texts.join(' ').toLowerCase();
	return words.value.every((w) => hay.includes(w));
};
/** The linked records' tags, grouped by the link they start with (LoadType, PlantArea, Motor…). */
const groups = computed(() => {
	const out: { id: string; title: string; hint?: string; items: { text: string; label: string; meaning: string }[] }[] = [];
	const add = (id: string, title: string, tags: Tag[], hint?: string) => {
		const items = tags.filter((t) => hit(t.tag, t.meaning)).map((t) => ({ text: t.tag, label: t.tag, meaning: t.meaning }));
		if (items.length) out.push({ id, title, hint, items });
	};
	add('row', props.what, props.tags);
	if (props.tables?.length) add('tables', "This type's component tables", props.tables, 'The row of the table the load falls in');
	const links = new Map<string, Tag[]>();
	for (const t of props.paths) {
		const link = /^<<([^.>]+)/.exec(t.tag)?.[1] ?? '';
		links.set(link, [...(links.get(link) ?? []), t]);
	}
	for (const [link, tags] of links) add(`link:${link}`, `${link} ›`, tags, tags[0]?.meaning.replace(/'s [^']*$/, ''));
	const mods = props.modifiers.filter((m) => hit(m.name, m.meaning, m.example))
		.map((m) => ({ text: `|${modifierText(m)}`, label: `|${modifierText(m)}`, meaning: `${m.meaning} · ${m.example}` }));
	if (mods.length) out.push({ id: 'mods', title: 'Modifiers, after |', hint: 'Added to the tag the cursor is in', items: mods });
	return out;
});
const count = computed(() => groups.value.reduce((n, g) => n + g.items.length, 0));
// while searching every group is open; otherwise the row's own tags are, and the rest open on a click
const isOpen = (id: string) => !!words.value.length || (id === 'row' || id === 'tables' ? !closed.value.has(id) : closed.value.has(id));
function toggle(id: string) {
	const next = new Set(closed.value);
	if (next.has(id)) next.delete(id);
	else next.add(id);
	closed.value = next;
}
</script>

<template>
	<aside class="tag-browser" aria-label="Tags">
		<div class="tb-head">
			<strong>Tags</strong>
			<span class="hint small">Click one to put it in the cell</span>
		</div>
		<input v-model="query" type="search" class="tb-search" placeholder="Search tags, e.g. cable, motor, upper…" aria-label="Search tags" />
		<div class="tb-list">
			<section v-for="g in groups" :key="g.id" :class="{ open: isOpen(g.id) }">
				<button type="button" class="tb-group" :aria-expanded="isOpen(g.id)" :title="g.hint" @click="toggle(g.id)">
					<span class="tb-chev">▸</span>{{ g.title }}<span class="count">{{ g.items.length }}</span>
				</button>
				<ul v-if="isOpen(g.id)">
					<!-- mousedown.prevent: the cell being edited keeps the cursor -->
					<li v-for="t in g.items" :key="t.text">
						<button type="button" class="tb-tag" :title="`${t.label}\n${t.meaning}`" @mousedown.prevent @click="emit('pick', t.text)">
							<code>{{ t.label }}</code><span>{{ t.meaning }}</span>
						</button>
					</li>
				</ul>
			</section>
			<p v-if="!count" class="hint small">Nothing matches “{{ query }}”.</p>
		</div>
		<p class="hint small tb-foot">
			<code>&lt;&lt;path|modifier|modifier:arg&gt;&gt;</code>. Names ignore case, spaces and _. A link the row doesn't have gives
			blank (<code>|default:TBA</code> fills it).
		</p>
	</aside>
</template>
