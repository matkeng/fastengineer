// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import type { Cell, RowStatus } from './types';

const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(text: string): string {
	return text.replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

/** HTML for a cell, showing full and partial strikethrough. Always escaped. */
export function cellHtml(cell: Cell): string {
	if (cell.s === 'partial' && cell.runs) {
		return cell.runs
			.map((r) => (r.strike ? `<s class="struck">${escapeHtml(r.text)}</s>` : escapeHtml(r.text)))
			.join('');
	}
	const text = escapeHtml(cell.t);
	return cell.s === 'full' ? `<s class="struck">${text}</s>` : text;
}

export const STRIKE_LABELS = { none: 'No strike', partial: 'Partly struck', full: 'Struck out' } as const;

export type StatusFilter = '' | 'changes' | RowStatus;

export const STATUS_LABELS: Record<RowStatus, string> = {
	added: 'Added',
	deleted: 'Deleted',
	struck: 'Struck out',
	restored: 'Restored',
	changed: 'Changed',
	unchanged: 'Unchanged',
};
