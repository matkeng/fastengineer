// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { IconName } from '../lib/icons';

export type Section = 'dashboard' | 'compare' | 'symbols' | 'mel' | 'keylists' | 'generators' | 'deliverables' | 'history' | 'projects' | 'engine';

/** `menu: false`: not a tab of its own; it is opened from another section. */
export const SECTIONS: { id: Section; label: string; icon: IconName; menu?: false }[] = [
	{ id: 'dashboard', label: 'Dashboard', icon: 'home' },
	{ id: 'compare', label: 'Compare tables', icon: 'compare', menu: false }, // opened from its card on the Projects tab
	{ id: 'symbols', label: 'Symbol detection', icon: 'symbol' },
	{ id: 'mel', label: 'List import', icon: 'recipe' },
	{ id: 'keylists', label: 'Project lists', icon: 'tree' },
	{ id: 'generators', label: 'Generators', icon: 'generator' },
	{ id: 'deliverables', label: 'Deliverables', icon: 'file' },
	{ id: 'history', label: 'Change log', icon: 'history' },
	{ id: 'projects', label: 'Projects', icon: 'layers' }, // administrators only (see App.vue)
	{ id: 'engine', label: 'Engine', icon: 'cpu' },
];

/** Which section of the app is showing; any view can switch it. */
export const useUi = defineStore('ui', () => {
	const tab = ref<Section>('dashboard');
	function go(section: Section) {
		tab.value = section;
	}
	return { tab, go };
});
