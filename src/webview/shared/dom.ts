/**
 * The DOM constructor, and the four colour helpers the token layer needs.
 *
 * `el()` is the only way a zer0-CMS webview creates an element. Text always
 * goes in through `document.createTextNode`, never through markup, which is
 * what makes the strict CSP in `getWebviewContent()` load-bearing rather than
 * decorative: there is no code path that can turn a draft's body, a file name
 * or a guard message into HTML. An eslint rule bans `innerHTML`, `outerHTML`
 * and `insertAdjacentHTML` across `src/webview/**` so the property stays gone.
 *
 * The colour helpers exist because six design tokens cannot be expressed as a
 * plain `var()` alias — an alpha wash, a darkened border, a theme-flipped
 * translucent surface. They read the *already resolved* `--z-*` tokens rather
 * than VS Code's own theme variables, so `media/tokens.css` remains the one file in the
 * repository that knows VS Code's variable names.
 */

// ---------------------------------------------------------------------------
// Element construction
// ---------------------------------------------------------------------------

export type Child = Node | string | number | boolean | null | undefined | readonly Child[];

export type ElProps<K extends keyof HTMLElementTagNameMap> = Partial<
  Omit<HTMLElementTagNameMap[K], 'style' | 'dataset' | 'classList' | 'children'>
> & {
  /** Shorthand for `className`. */
  class?: string;
  /** `data-*` attributes, written through the real `dataset`. */
  dataset?: Record<string, string>;
  /** Attributes with no matching DOM property (`aria-*`, `role`, `for`…). */
  attrs?: Record<string, string | number | boolean | null | undefined>;
  /** Inline style, as a CSS declaration string. */
  style?: string;
  /** Event listeners keyed by event name, e.g. `{ click: fn }`. */
  on?: Record<string, EventListener>;
};

function appendChild(parent: Node, child: Child): void {
  if (child === null || child === undefined || child === false || child === true) {
    return;
  }
  if (Array.isArray(child)) {
    for (const nested of child as readonly Child[]) {
      appendChild(parent, nested);
    }
    return;
  }
  if (typeof child === 'string' || typeof child === 'number') {
    parent.appendChild(document.createTextNode(String(child)));
    return;
  }
  parent.appendChild(child as Node);
}

/** Append any mix of nodes, strings, numbers, arrays and falsy holes. */
export function append(parent: Node, ...children: Child[]): void {
  for (const child of children) {
    appendChild(parent, child);
  }
}

/**
 * Build an element. Props map to DOM properties when one exists and to
 * attributes otherwise; `on*` keys whose value is a function are registered
 * with `addEventListener` so several handlers can coexist.
 */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props?: ElProps<K>,
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props as Record<string, unknown>)) {
      if (value === undefined || value === null) {
        continue;
      }
      if (key === 'class') {
        node.className = String(value);
      } else if (key === 'style') {
        node.setAttribute('style', String(value));
      } else if (key === 'dataset') {
        for (const [name, item] of Object.entries(value as Record<string, string>)) {
          node.dataset[name] = item;
        }
      } else if (key === 'attrs') {
        for (const [name, item] of Object.entries(value as Record<string, unknown>)) {
          if (item === undefined || item === null || item === false) {
            node.removeAttribute(name);
          } else {
            node.setAttribute(name, item === true ? '' : String(item));
          }
        }
      } else if (key === 'on') {
        for (const [name, handler] of Object.entries(value as Record<string, EventListener>)) {
          node.addEventListener(name, handler);
        }
      } else if (/^on[a-z]/.test(key) && typeof value === 'function') {
        node.addEventListener(key.slice(2), value as EventListener);
      } else if (key in node) {
        (node as unknown as Record<string, unknown>)[key] = value;
      } else {
        node.setAttribute(key, String(value));
      }
    }
  }
  append(node, ...children);
  return node;
}

/** A codicon. The extension ships no SVG assets and no webfont of its own. */
export function icon(name: string, className?: string): HTMLElement {
  return el('i', {
    class: className ? `codicon codicon-${name} ${className}` : `codicon codicon-${name}`,
    attrs: { 'aria-hidden': 'true' },
  });
}

/** Visually hidden label text — a real screen-reader affordance, not
 *  `display:none`, which is what Front Matter's `.sr-only` mistakenly was. */
export function srOnly(text: string): HTMLElement {
  return el('span', { class: 'z-sr-only' }, text);
}

/** Remove every child of a node. The reconciler's only teardown primitive. */
export function clear(node: Node): void {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

// ---------------------------------------------------------------------------
// Events and timing
// ---------------------------------------------------------------------------

/** `addEventListener` that hands back its own disposer. */
export function on(
  target: EventTarget,
  type: string,
  handler: EventListener,
  options?: boolean | AddEventListenerOptions,
): () => void {
  target.addEventListener(type, handler, options);
  return () => {
    target.removeEventListener(type, handler, options);
  };
}

export interface Debounced<A extends unknown[]> {
  (...args: A): void;
  cancel(): void;
  /** Run the pending call now, if there is one. */
  flush(): void;
}

/** Trailing-edge debounce with `cancel`/`flush`, used by text fields (300ms),
 *  the dashboard search box (500ms) and the settings inputs (1000ms). */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): Debounced<A> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let last: A | undefined;
  const wrapper = (...args: A): void => {
    last = args;
    if (timer !== undefined) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = undefined;
      const call = last;
      last = undefined;
      if (call) {
        fn(...call);
      }
    }, ms);
  };
  wrapper.cancel = (): void => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
    last = undefined;
  };
  wrapper.flush = (): void => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
    const call = last;
    last = undefined;
    if (call) {
      fn(...call);
    }
  };
  return wrapper;
}

// ---------------------------------------------------------------------------
// Colour helpers and the six derived tokens
// ---------------------------------------------------------------------------

interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

function clampByte(n: number): number {
  return Math.min(255, Math.max(0, Math.round(n)));
}

function parseColor(input: string): Rgba | null {
  const value = input.trim();
  if (value.startsWith('#')) {
    const hex = value.slice(1);
    const expand = hex.length === 3 || hex.length === 4;
    const step = expand ? 1 : 2;
    const part = (i: number): number => {
      const chunk = hex.slice(i * step, i * step + step);
      if (chunk.length === 0) {
        return 0;
      }
      return parseInt(expand ? chunk + chunk : chunk, 16);
    };
    if (hex.length !== 3 && hex.length !== 4 && hex.length !== 6 && hex.length !== 8) {
      return null;
    }
    const a = hex.length === 4 || hex.length === 8 ? part(3) / 255 : 1;
    return { r: part(0), g: part(1), b: part(2), a };
  }
  const match = /^rgba?\(([^)]+)\)$/i.exec(value);
  if (!match || match[1] === undefined) {
    return null;
  }
  const parts = match[1].split(/[,/\s]+/).filter((p) => p.length > 0);
  const r = Number(parts[0]);
  const g = Number(parts[1]);
  const b = Number(parts[2]);
  if (!Number.isFinite(r) || !Number.isFinite(g) || !Number.isFinite(b)) {
    return null;
  }
  const rawAlpha = parts[3];
  const a = rawAlpha === undefined ? 1 : Number(rawAlpha.endsWith('%') ? Number(rawAlpha.slice(0, -1)) / 100 : rawAlpha);
  return { r, g, b, a: Number.isFinite(a) ? a : 1 };
}

function toRgba(c: Rgba): string {
  return `rgba(${clampByte(c.r)}, ${clampByte(c.g)}, ${clampByte(c.b)}, ${Math.round(c.a * 1000) / 1000})`;
}

/** Drop any alpha: `#RRGGBBAA` → `#RRGGBB`, `rgba(…, .4)` → `rgba(…, 1)`. */
export function preserveColor(input: string): string {
  const c = parseColor(input);
  return c ? toRgba({ ...c, a: 1 }) : input;
}

/** Re-alpha a colour, e.g. the 5 % success/warning washes. */
export function opacityColor(input: string, alpha: number): string {
  const c = parseColor(input);
  return c ? toRgba({ ...c, a: alpha }) : input;
}

/** Subtract `round(255 * pct/100)` from each channel. Negative percentages
 *  lighten, which is how the active border works in dark themes. */
export function darkenColor(input: string, pct: number): string {
  const c = parseColor(input);
  if (!c) {
    return input;
  }
  const delta = Math.round((255 * pct) / 100);
  return toRgba({ r: c.r - delta, g: c.g - delta, b: c.b - delta, a: c.a });
}

function readToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** True for `vscode-dark` and for the dark high-contrast theme. */
export function isDarkTheme(): boolean {
  const classes = document.body.classList;
  return (
    classes.contains('vscode-dark') ||
    (classes.contains('vscode-high-contrast') && !classes.contains('vscode-high-contrast-light'))
  );
}

/**
 * Recompute the six tokens that cannot be a plain alias. Reads the resolved
 * `--z-*` source tokens, never VS Code's own theme variables.
 */
export function updateDerivedTokens(isDark: boolean = isDarkTheme()): void {
  const root = document.documentElement;
  const set = (name: string, value: string): void => {
    root.style.setProperty(name, value);
  };
  set('--z-ok-bg', opacityColor(readToken('--z-ok'), 0.05));
  set('--z-warn-bg', opacityColor(readToken('--z-warn'), 0.05));
  set('--z-border-active', darkenColor(readToken('--z-border'), isDark ? -30 : 30));
  set('--z-overlay', opacityColor(readToken('--z-bg'), 0.75));
  set('--z-translucent', isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)');
  set('--z-btn-solid', preserveColor(readToken('--z-btn-bg')));
}

/**
 * Keep the derived tokens in step with the workbench. VS Code swaps the theme
 * by rewriting `document.body`'s class and inline style, so one observer on
 * its attributes catches every change.
 */
export function watchTheme(): () => void {
  updateDerivedTokens();
  const observer = new MutationObserver(() => {
    updateDerivedTokens();
  });
  observer.observe(document.body, { attributes: true });
  return () => {
    observer.disconnect();
  };
}
