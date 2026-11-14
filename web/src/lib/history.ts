// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Matthew Kelly
// Undo and redo. A history keeps what something looked like before each change (as JSON, so a
// later edit can't reach into it), the last UNDO_STEPS of them. Two ways to use it:
//   useUndo: an unsaved draft (a spreadsheet-style grid): undo puts the earlier draft back.
//   useSavedUndo: an editor that saves each change at once: undo saves the earlier list again.
import { type Ref, computed, ref, watch } from 'vue';

/** How many steps back undo goes. */
export const UNDO_STEPS = 100;

export interface History<T> {
	readonly canUndo: Ref<boolean>;
	readonly canRedo: Ref<boolean>;
	/** Remember `before`, the state a change is about to replace. Clears what could be redone. */
	record(before: T): void;
	/** The state to go back to (undefined: nothing to undo). `current` becomes what redo returns to. */
	undo(current: T): T | undefined;
	redo(current: T): T | undefined;
	/** What undo / redo would return, without moving. */
	peekUndo(): T | undefined;
	peekRedo(): T | undefined;
	clear(): void;
}

export function createHistory<T>(limit = UNDO_STEPS): History<T> {
	const past = ref<string[]>([]);
	const future = ref<string[]>([]);
	const parse = (s: string | undefined) => (s === undefined ? undefined : (JSON.parse(s) as T));
	const step = (from: Ref<string[]>, to: Ref<string[]>, current: T) => {
		const s = from.value.pop();
		if (s === undefined) return undefined;
		to.value.push(JSON.stringify(current));
		return parse(s);
	};
	return {
		canUndo: computed(() => past.value.length > 0),
		canRedo: computed(() => future.value.length > 0),
		record(before) {
			const s = JSON.stringify(before);
			if (past.value[past.value.length - 1] === s) return; // nothing changed since the last one
			past.value.push(s);
			if (past.value.length > limit) past.value.splice(0, past.value.length - limit);
			future.value = [];
		},
		undo: (current) => step(past, future, current),
		redo: (current) => step(future, past, current),
		peekUndo: () => parse(past.value[past.value.length - 1]),
		peekRedo: () => parse(future.value[future.value.length - 1]),
		clear() {
			past.value = [];
			future.value = [];
		},
	};
}

/** Put a snapshot back into the object or array it was taken from, keeping that same object
 *  (others hold on to it), with its contents replaced. */
export function restoreInto(target: unknown, snapshot: unknown): void {
	if (Array.isArray(target) && Array.isArray(snapshot)) {
		target.splice(0, target.length, ...snapshot);
	} else if (target && snapshot && typeof target === 'object' && typeof snapshot === 'object') {
		const t = target as Record<string, unknown>;
		const s = snapshot as Record<string, unknown>;
		for (const k of Object.keys(t)) if (!(k in s)) delete t[k];
		Object.assign(t, s);
	}
}

export interface Undo {
	readonly canUndo: Ref<boolean>;
	readonly canRedo: Ref<boolean>;
	/** Call before changing the draft. Changes within a moment of each other are one step (a paste adds rows, then fills them). */
	record(): void;
	undo(): void;
	redo(): void;
	clear(): void;
}

/**
 * Undo for a draft that is edited in place and saved later.
 * `get`: the part of the draft the edits change (null while there is none).
 * `set`: put an earlier copy back (default: into the same object, see restoreInto).
 * `resetOn`: something that changes when the draft is loaded or saved (the saved copy): the history starts again.
 */
export function useUndo<T>(options: { get: () => T | null | undefined; set?: (earlier: T) => void; resetOn?: () => unknown; limit?: number }): Undo {
	const h = createHistory<T>(options.limit);
	let last = 0;
	const put = (earlier: T | undefined) => {
		if (earlier === undefined) return;
		if (options.set) options.set(earlier);
		else restoreInto(options.get(), earlier);
	};
	if (options.resetOn) watch(options.resetOn, () => h.clear());
	return {
		canUndo: h.canUndo,
		canRedo: h.canRedo,
		record() {
			const now = Date.now();
			const current = options.get();
			if (current == null || now - last < 80) return;
			last = now;
			h.record(current);
		},
		undo() {
			const current = options.get();
			if (current != null) put(h.undo(current));
		},
		redo() {
			const current = options.get();
			if (current != null) put(h.redo(current));
		},
		clear: h.clear,
	};
}

export interface SavedUndo<T> {
	readonly canUndo: Ref<boolean>;
	readonly canRedo: Ref<boolean>;
	readonly busy: Ref<boolean>;
	/** Call after a change was saved, with the list as it was before it. */
	saved(before: T): void;
	/** Undo (or redo) the last change by saving the earlier list again. Returns what to tell the
	 *  user: "Undone", "Redone", why nothing was done, or '' when the save failed (the editor
	 *  shows its own error, and the history is kept). */
	step(redo?: boolean): Promise<string>;
	clear(): void;
}

/**
 * Undo for an editor that saves every change at once: undo saves the list as it was before.
 * `current`: the list as it is now. `apply`: save a list (true when it worked); it goes through
 * the editor's normal save, so it is logged and a colleague's newer change is still reported.
 * If the list is no longer what the last change here left (an import, a reset, a colleague's
 * edit), there is nothing safe to undo: the history is dropped and the list is left alone.
 */
export function useSavedUndo<T>(current: () => T | null | undefined, apply: (earlier: T) => Promise<boolean>, limit?: number): SavedUndo<T> {
	const h = createHistory<T>(limit);
	const busy = ref(false);
	let left = ''; // the list as the last change made here left it
	const now = () => JSON.stringify(current() ?? null);
	return {
		canUndo: h.canUndo,
		canRedo: h.canRedo,
		busy,
		saved(before) {
			h.record(before);
			left = now();
		},
		async step(redo = false) {
			const target = redo ? h.peekRedo() : h.peekUndo();
			const state = current();
			if (target === undefined || state == null || busy.value) return '';
			if (now() !== left) {
				h.clear();
				return 'The list has changed since (an import, a reset or a colleague): nothing was undone';
			}
			const before = JSON.parse(JSON.stringify(state)) as T;
			busy.value = true;
			try {
				if (!(await apply(target))) return '';
				if (redo) h.redo(before);
				else h.undo(before);
				left = now();
				return redo ? 'Redone' : 'Undone';
			} finally {
				busy.value = false;
			}
		},
		clear: h.clear,
	};
}
