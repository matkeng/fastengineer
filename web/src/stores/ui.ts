// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { IconName } from '../lib/icons';

export type Section = 'dashboard' | 'excel' | 'compare' | 'symbols' | 'mel' | 'ref' | 'generators' | 'history' | 'engine';

export const SECTIONS: { id: Section; label: string; icon: IconName }[] = [
	{ id: 'dashboard', label: 'Dashboard', icon: 'home' },
	{ id: 'excel', label: 'Excel query', icon: 'table' },
	{ id: 'compare', label: 'Compare tables', icon: 'compare' },
	{ id: 'symbols', label: 'Symbol detection', icon: 'symbol' },
	{ id: 'mel', label: 'List import', icon: 'recipe' },
	{ id: 'ref', label: 'Lists & tables', icon: 'database' },
	{ id: 'generators', label: 'Generators', icon: 'generator' },
	{ id: 'history', label: 'Change log', icon: 'history' },
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
