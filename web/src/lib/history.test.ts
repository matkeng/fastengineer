// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
import { describe, expect, it } from 'vitest';
import { UNDO_STEPS, createHistory, restoreInto, useSavedUndo, useUndo } from './history';

describe('createHistory', () => {
	it('goes back and forward through what was recorded', () => {
		const h = createHistory<number[]>();
		expect(h.canUndo.value).toBe(false);
		h.record([1]);
		h.record([1, 2]);
		expect(h.undo([1, 2, 3])).toEqual([1, 2]);
		expect(h.undo([1, 2])).toEqual([1]);
		expect(h.undo([1])).toBeUndefined();
		expect(h.canUndo.value).toBe(false);
		expect(h.redo([1])).toEqual([1, 2]);
		expect(h.redo([1, 2])).toEqual([1, 2, 3]);
		expect(h.canRedo.value).toBe(false);
	});

	it('a new change drops what could be redone', () => {
		const h = createHistory<string>();
		h.record('a');
		h.undo('b');
		expect(h.canRedo.value).toBe(true);
		h.record('a');
		expect(h.canRedo.value).toBe(false);
	});

	it('keeps copies, not the objects themselves', () => {
		const h = createHistory<{ n: number }>();
		const state = { n: 1 };
		h.record(state);
		state.n = 2;
		expect(h.undo(state)).toEqual({ n: 1 });
	});

	it(`keeps at least 50 steps (${UNDO_STEPS}) and drops the oldest after that`, () => {
		expect(UNDO_STEPS).toBeGreaterThanOrEqual(50);
		const h = createHistory<number>();
		for (let i = 0; i < UNDO_STEPS + 20; i++) h.record(i);
		let steps = 0;
		let last: number | undefined;
		for (let v = h.undo(-1); v !== undefined; v = h.undo(v)) {
			steps++;
			last = v;
		}
		expect(steps).toBe(UNDO_STEPS);
		expect(last).toBe(20);
	});

	it('does not record the same state twice in a row', () => {
		const h = createHistory<number>();
		h.record(1);
		h.record(1);
		h.undo(2);
		expect(h.canUndo.value).toBe(false);
	});
});

describe('restoreInto', () => {
	it('puts a snapshot back into the same array or object', () => {
		const list = [{ a: 1 }, { a: 2 }];
		const same = list;
		restoreInto(list, [{ a: 9 }]);
		expect(list).toBe(same);
		expect(list).toEqual([{ a: 9 }]);
		const obj: Record<string, unknown> = { keep: 1, drop: 2 };
		restoreInto(obj, { keep: 3, added: 4 });
		expect(obj).toEqual({ keep: 3, added: 4 });
	});
});

describe('useUndo (a draft)', () => {
	it('undoes and redoes edits made in place', async () => {
		const draft = { rows: [{ v: 'a' }] };
		const u = useUndo({ get: () => draft.rows });
		u.record();
		draft.rows[0].v = 'b';
		await new Promise((r) => setTimeout(r, 100)); // a later edit is its own step
		u.record();
		draft.rows.push({ v: 'c' });
		u.undo();
		expect(draft.rows).toEqual([{ v: 'b' }]);
		u.undo();
		expect(draft.rows).toEqual([{ v: 'a' }]);
		u.redo();
		u.redo();
		expect(draft.rows).toEqual([{ v: 'b' }, { v: 'c' }]);
	});

	it('takes changes made within a moment of each other as one step (a paste: rows added, then filled)', () => {
		const rows: string[] = ['a'];
		const u = useUndo({ get: () => rows });
		u.record();
		rows.push('');
		u.record(); // straight after: the same step
		rows[1] = 'b';
		u.undo();
		expect(rows).toEqual(['a']);
		expect(u.canUndo.value).toBe(false);
	});
});

describe('useSavedUndo (a list saved on every change)', () => {
	function editor() {
		const server = { items: ['a'] as string[], fail: false, saves: 0 };
		const local = { items: ['a'] as string[] };
		const apply = async (list: string[]) => {
			if (server.fail) return false;
			server.items = local.items = [...list];
			server.saves++;
			return true;
		};
		const u = useSavedUndo<string[]>(() => local.items, apply);
		const save = async (list: string[]) => {
			const before = [...local.items];
			await apply(list);
			u.saved(before);
		};
		return { server, local, u, save };
	}

	it('undo saves the earlier list again, and redo the later one', async () => {
		const e = editor();
		await e.save(['a', 'b']);
		await e.save(['a', 'b', 'c']);
		expect(await e.u.step()).toBe('Undone');
		expect(e.server.items).toEqual(['a', 'b']);
		expect(await e.u.step()).toBe('Undone');
		expect(e.server.items).toEqual(['a']);
		expect(await e.u.step()).toBe(''); // nothing left
		expect(await e.u.step(true)).toBe('Redone');
		expect(await e.u.step(true)).toBe('Redone');
		expect(e.server.items).toEqual(['a', 'b', 'c']);
	});

	it('keeps the history when the save is refused', async () => {
		const e = editor();
		await e.save(['a', 'b']);
		e.server.fail = true;
		expect(await e.u.step()).toBe('');
		expect(e.u.canUndo.value).toBe(true);
		e.server.fail = false;
		expect(await e.u.step()).toBe('Undone');
	});

	it('undoes nothing when the list was changed somewhere else since', async () => {
		const e = editor();
		await e.save(['a', 'b']);
		e.local.items = ['a', 'b', 'imported']; // an import, or a colleague
		const saves = e.server.saves;
		expect(await e.u.step()).toMatch(/has changed since/);
		expect(e.server.saves).toBe(saves);
		expect(e.u.canUndo.value).toBe(false);
	});
});
