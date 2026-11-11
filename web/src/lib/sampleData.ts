// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { apiPostJson } from './engine';

export interface SampleResult { added: Record<string, number>; skipped: string[] }

/** Fill every project list that is still empty with the sample plant (lists with data are left alone). */
export const loadSampleData = () => apiPostJson<SampleResult>('/api/sample-data', {});

/** What was added, in a sentence ("" when nothing was). */
export function sampleSummary(res: SampleResult): string {
	const added = Object.entries(res.added).map(([k, n]) => `${k} (${n})`);
	return added.length ? `Sample data added to the project lists: ${added.join(', ')}.` : '';
}
