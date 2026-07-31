/**
 * The whole "reactivity" story: a section-level reconciler, ninety lines, no
 * virtual DOM.
 *
 * Front Matter re-rendered a React tree on every message. We receive one full
 * state snapshot instead (decision D4), so the only question worth asking is
 * *which parts of the page that snapshot changed*. A `Section` answers it
 * directly — it declares its own staleness predicate and rebuilds its own
 * subtree. Diffing a section is a handful of field comparisons; diffing a tree
 * is a framework.
 *
 * The one subtlety is focus. Clearing and rebuilding a subtree destroys the
 * element the user is typing in, which loses the caret and, in a webview, the
 * IME composition. So a stale section that contains `document.activeElement`
 * is not rebuilt: the snapshot is parked and flushed on the next `focusout`.
 * Late is correct here; interrupting a keystroke is not.
 */

import { clear } from './dom';

export interface Section<S> {
  /** Stable id — becomes `data-section` and is useful in tests. */
  id: string;
  /** `prev` is the state at the last check (`undefined` on first render). */
  stale(prev: S | undefined, next: S): boolean;
  /** Fill `host`. The host is emptied first; never cache nodes across calls. */
  render(next: S, host: HTMLElement): void;
  /** Optional wrapper class, in addition to `z-section`. */
  className?: string;
}

interface Mounted<S> {
  section: Section<S>;
  host: HTMLElement;
  /** The state this section was last rendered with, or last found unchanged. */
  prev: S | undefined;
  /** A stale snapshot held back because the section owns the focus. */
  pending: S | undefined;
}

function holdsFocus(host: HTMLElement): boolean {
  const active = document.activeElement;
  return active !== null && active !== document.body && host.contains(active);
}

/**
 * Mount `sections` into `root` in order and return the update function. Call
 * it with each snapshot; only sections whose `stale()` says so are rebuilt.
 */
export function mountSections<S>(root: HTMLElement, sections: Section<S>[]): (state: S) => void {
  clear(root);

  const flush = (entry: Mounted<S>, next: S): void => {
    clear(entry.host);
    entry.section.render(next, entry.host);
    entry.prev = next;
    entry.pending = undefined;
  };

  const mounted: Array<Mounted<S>> = sections.map((section) => {
    const host = document.createElement('div');
    host.className = section.className ? `z-section ${section.className}` : 'z-section';
    host.dataset.section = section.id;
    root.appendChild(host);
    const entry: Mounted<S> = { section, host, prev: undefined, pending: undefined };
    // One listener for the lifetime of the host — registering it lazily each
    // time a snapshot is deferred would pile up a listener per defer cycle.
    host.addEventListener('focusout', () => {
      // `focusout` fires *before* the next element takes focus, so re-check on
      // the following tick: tabbing between two controls inside the section
      // must not trigger a rebuild under the user's hands.
      setTimeout(() => {
        const held = entry.pending;
        if (held !== undefined && !holdsFocus(entry.host)) {
          flush(entry, held);
        }
      }, 0);
    });
    return entry;
  });

  return (state: S): void => {
    for (const entry of mounted) {
      if (!entry.section.stale(entry.prev, state)) {
        // Not stale: adopt the snapshot so the next comparison is against
        // what is actually on screen.
        if (entry.pending === undefined) {
          entry.prev = state;
        }
        continue;
      }
      if (holdsFocus(entry.host)) {
        entry.pending = state;
        continue;
      }
      flush(entry, state);
    }
  };
}

/**
 * The common staleness predicate: rebuild when any of the projected values
 * differs by `Object.is`. Keep the projections cheap and primitive — an array
 * or object literal in there means the section is stale on every snapshot.
 */
export function staleOn<S>(...projections: Array<(state: S) => unknown>): Section<S>['stale'] {
  return (prev, next) => {
    if (prev === undefined) {
      return true;
    }
    return projections.some((project) => !Object.is(project(prev), project(next)));
  };
}

/** A section that always rebuilds. Correct for cheap, input-free subtrees. */
export const alwaysStale = (): boolean => true;
