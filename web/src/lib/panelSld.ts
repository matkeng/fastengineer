// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Where things go on a panel's single line diagram: the incomer and isolator at the top, a
// busbar across, and one drop per circuit (a three-pole circuit is one drop), in way order.
import { fmt, type PanelSchedule } from './panelTypes';

export interface SldBranch {
	x: number; circuit: string; pole: string; poles: number; kind: string; cb: string; label: string; watts: string; problem: string;
}
export interface SldGroup { x1: number; x2: number; label: string }
export interface SldLayout { width: number; height: number; busY: number; busX1: number; busX2: number; centre: number; branches: SldBranch[]; groups: SldGroup[] }

export const SLD = { pitch: 46, margin: 40, busY: 150, breakerY: 190, labelY: 240, labelLength: 300 };

export function sldLayout(schedule: PanelSchedule): SldLayout {
	const first = schedule.rows.filter((r) => r.entry_id && r.span > 0);
	const branches: SldBranch[] = [];
	const groups: SldGroup[] = [];
	let section = '';
	first.forEach((r, i) => {
		const x = SLD.margin + SLD.pitch / 2 + i * SLD.pitch;
		const rows = schedule.rows.filter((o) => o.entry_id === r.entry_id);
		const watts = rows.reduce((a, o) => a + o.total_w, 0);
		const ratings = [...new Set(rows.map((o) => o.cb_rating).filter((v): v is number => v !== null))];
		branches.push({
			x, circuit: r.span === 3 ? `Q${r.way}` : r.circuit, pole: r.span === 3 ? '' : r.pole, poles: r.span, kind: r.kind,
			cb: ratings.length ? `${ratings.map((v) => fmt(v)).join('/')} A` : '',
			label: [r.tag, r.description || r.load_type].filter(Boolean).join(' · '), watts: watts ? `${fmt(watts / 1000, 2)} kW` : '', problem: r.problem,
		});
		if (r.section && r.section === section) groups[groups.length - 1].x2 = x;
		else if (r.section) groups.push({ x1: x, x2: x, label: r.section });
		section = r.section;
	});
	const width = Math.max(420, SLD.margin * 2 + Math.max(branches.length, 1) * SLD.pitch);
	return {
		width, height: SLD.labelY + SLD.labelLength + 30, busY: SLD.busY, busX1: SLD.margin, busX2: width - SLD.margin, centre: width / 2,
		branches, groups,
	};
}
