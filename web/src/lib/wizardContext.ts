// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { type InjectionKey, inject } from 'vue';
import type { TableWizard } from '../stores/excelWizard';

export interface SampleFile {
	label: string;
	url: string;
	filename: string;
}

/** What the step components need; provided by ExcelWizard. */
export interface WizardContext {
	wiz: TableWizard;
	samples: SampleFile[];
	/** Another wizard whose workbook can be reused (compare: the old table). */
	reuseFrom?: TableWizard;
}

export const WIZARD_CONTEXT: InjectionKey<WizardContext> = Symbol('wizard');

export function useWizardContext(): WizardContext {
	const ctx = inject(WIZARD_CONTEXT);
	if (!ctx) throw new Error('Wizard steps must be used inside ExcelWizard');
	return ctx;
}
