/**
 * A zero-dependency mini-DOM, so the webview bundles can be tested by the fast
 * plain-Mocha loop.
 *
 * The repository ships **no runtime dependencies** (decision D3), and the fast
 * inner loop is plain Mocha over `tsc` output with no VS Code download. Pulling
 * jsdom in — 2 MB of devDependency and a full HTML parser — to assert that a
 * route renders an empty state would buy far more than the question needs. So
 * this file implements the small slice of the DOM `src/webview/**` actually
 * uses, and nothing else.
 *
 * **Importing this module installs the globals.** That is deliberate and it is
 * why every suite here lists it as its *first* import: `src/webview/dashboard/
 * main.ts` calls `getMessenger()` and `boot()` while it is being evaluated, so
 * the globals have to exist before the first `require` of a webview module, not
 * merely before the first test. `boot()` then finds no `#z-dashboard` element,
 * logs one line to the stub bridge and returns — which is exactly the shape the
 * real shell guards against, and costs the suite nothing.
 *
 * ## What it implements
 *
 * `document.createElement` / `createElementNS` / `createTextNode` /
 * `getElementById` / `querySelector` / `querySelectorAll`, `documentElement`
 * and `body`; element `appendChild` / `insertBefore` / `removeChild` /
 * `replaceChild` / `remove` / `contains`, `classList`, `dataset`,
 * `className`, `id`, `textContent`, `setAttribute` and friends, the handful of
 * real DOM properties `el()` assigns through (`value`, `checked`, `disabled`,
 * `type`, `rows`, `placeholder`, `selected`, `title`, `href`, `src`, `alt`),
 * `addEventListener` / `removeEventListener` / `dispatchEvent` with bubbling,
 * and the constructors webview code narrows against (`Node`, `HTMLElement`,
 * `HTMLInputElement`, `HTMLSelectElement`, `HTMLTextAreaElement`,
 * `KeyboardEvent`, `MessageEvent`). `MutationObserver`, `getComputedStyle`,
 * `requestAnimationFrame` and `acquireVsCodeApi` are stubs with the shape their
 * callers need.
 *
 * ## What it deliberately does NOT implement
 *
 * No layout or geometry — there is no `getBoundingClientRect`, no `offset*`,
 * no `client*`; a test that needs a pixel is asking a question this shim cannot
 * answer honestly. No CSS cascade: `getComputedStyle().getPropertyValue()`
 * returns `''` and the derived-token helpers are therefore not exercised here.
 * No selector engine beyond compound simple selectors (`tag`, `.class`, `#id`,
 * `[attr]`, `[attr="value"]`, and any combination of those) joined by the
 * descendant combinator — no `>`, `+`, `~`, `:has()`, `:not()` or attribute
 * operators. No capture phase, no default actions, no `stopPropagation`
 * beyond the flag, and no live collections. No `innerHTML` — the eslint rule
 * bans it in the code under test, so there is nothing here to parse.
 *
 * The leak counter is the one thing measured rather than modelled:
 * `persistentListenerCount()` reports the listeners attached to `document` and
 * `window`, the two targets that outlive a widget. A listener on a node the
 * caller then drops is collected with the node and is not a leak.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

interface EventInitLike {
  bubbles?: boolean;
  cancelable?: boolean;
}

class FakeEvent {
  readonly type: string;
  readonly bubbles: boolean;
  readonly cancelable: boolean;
  target: FakeNode | FakeWindow | FakeDocument | null = null;
  currentTarget: FakeNode | FakeWindow | FakeDocument | null = null;
  defaultPrevented = false;
  propagationStopped = false;

  constructor(type: string, init: EventInitLike = {}) {
    this.type = type;
    this.bubbles = init.bubbles === true;
    this.cancelable = init.cancelable === true;
  }

  preventDefault(): void {
    this.defaultPrevented = true;
  }

  stopPropagation(): void {
    this.propagationStopped = true;
  }
}

class FakeKeyboardEvent extends FakeEvent {
  readonly key: string;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly shiftKey: boolean;

  constructor(
    type: string,
    init: EventInitLike & { key?: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean } = {},
  ) {
    super(type, init);
    this.key = init.key ?? '';
    this.ctrlKey = init.ctrlKey === true;
    this.metaKey = init.metaKey === true;
    this.shiftKey = init.shiftKey === true;
  }
}

class FakeMessageEvent extends FakeEvent {
  readonly data: unknown;

  constructor(type: string, init: EventInitLike & { data?: unknown } = {}) {
    super(type, init);
    this.data = init.data;
  }
}

type Listener = (event: FakeEvent) => void;

/** Every listener currently registered, so the leak test has a number to read. */
const listeners = new WeakMap<object, Map<string, Listener[]>>();
const persistentTargets = new Set<object>();

function listenersFor(target: object): Map<string, Listener[]> {
  let map = listeners.get(target);
  if (map === undefined) {
    map = new Map<string, Listener[]>();
    listeners.set(target, map);
  }
  return map;
}

function addListener(target: object, type: string, handler: Listener): void {
  const map = listenersFor(target);
  const bucket = map.get(type);
  if (bucket === undefined) {
    map.set(type, [handler]);
  } else {
    bucket.push(handler);
  }
}

function removeListener(target: object, type: string, handler: Listener): void {
  const bucket = listenersFor(target).get(type);
  if (bucket === undefined) {
    return;
  }
  const at = bucket.indexOf(handler);
  if (at >= 0) {
    bucket.splice(at, 1);
  }
}

function countListeners(target: object): number {
  let total = 0;
  for (const bucket of listenersFor(target).values()) {
    total += bucket.length;
  }
  return total;
}

// ---------------------------------------------------------------------------
// Nodes
// ---------------------------------------------------------------------------

class FakeNode {
  parentNode: FakeElement | null = null;
  readonly childNodes: FakeNode[] = [];

  get parentElement(): FakeElement | null {
    return this.parentNode;
  }

  get firstChild(): FakeNode | null {
    return this.childNodes[0] ?? null;
  }

  get textContent(): string {
    return this.childNodes.map((child) => child.textContent).join('');
  }

  set textContent(value: string) {
    this.childNodes.splice(0, this.childNodes.length);
    if (value !== '') {
      this.appendChild(new FakeText(value));
    }
  }

  appendChild<T extends FakeNode>(child: T): T {
    child.parentNode?.removeChild(child);
    child.parentNode = this instanceof FakeElement ? this : null;
    this.childNodes.push(child);
    return child;
  }

  insertBefore<T extends FakeNode>(child: T, reference: FakeNode | null): T {
    if (reference === null) {
      return this.appendChild(child);
    }
    const at = this.childNodes.indexOf(reference);
    if (at < 0) {
      return this.appendChild(child);
    }
    child.parentNode?.removeChild(child);
    child.parentNode = this instanceof FakeElement ? this : null;
    this.childNodes.splice(at, 0, child);
    return child;
  }

  removeChild<T extends FakeNode>(child: T): T {
    const at = this.childNodes.indexOf(child);
    if (at >= 0) {
      this.childNodes.splice(at, 1);
      child.parentNode = null;
    }
    return child;
  }

  replaceChild<T extends FakeNode>(next: FakeNode, old: T): T {
    const at = this.childNodes.indexOf(old);
    if (at < 0) {
      return old;
    }
    next.parentNode?.removeChild(next);
    next.parentNode = this instanceof FakeElement ? this : null;
    this.childNodes.splice(at, 1, next);
    old.parentNode = null;
    return old;
  }

  contains(other: FakeNode | null): boolean {
    for (let node: FakeNode | null = other; node !== null; node = node.parentNode) {
      if (node === this) {
        return true;
      }
    }
    return false;
  }

  addEventListener(type: string, handler: Listener): void {
    addListener(this, type, handler);
  }

  removeEventListener(type: string, handler: Listener): void {
    removeListener(this, type, handler);
  }

  dispatchEvent(event: FakeEvent): boolean {
    event.target = this;
    // The bubble path, taken once up front: a handler that reparents the node
    // must not change which ancestors still hear the event.
    const path: FakeNode[] = [this];
    if (event.bubbles) {
      for (let up = this.parentNode; up !== null; up = up.parentNode) {
        path.push(up);
      }
    }
    for (const node of path) {
      event.currentTarget = node;
      for (const handler of [...(listenersFor(node).get(event.type) ?? [])]) {
        handler(event);
      }
      if (event.propagationStopped) {
        break;
      }
    }
    return !event.defaultPrevented;
  }
}

class FakeText extends FakeNode {
  private text: string;

  constructor(text: string) {
    super();
    this.text = text;
  }

  override get textContent(): string {
    return this.text;
  }

  override set textContent(value: string) {
    this.text = value;
  }
}

class FakeClassList {
  private readonly owner: FakeElement;

  constructor(owner: FakeElement) {
    this.owner = owner;
  }

  private names(): string[] {
    return this.owner.className.split(/\s+/).filter((name) => name !== '');
  }

  private write(names: readonly string[]): void {
    this.owner.className = names.join(' ');
  }

  contains(name: string): boolean {
    return this.names().includes(name);
  }

  add(...names: string[]): void {
    const current = this.names();
    for (const name of names) {
      if (name !== '' && !current.includes(name)) {
        current.push(name);
      }
    }
    this.write(current);
  }

  remove(...names: string[]): void {
    this.write(this.names().filter((name) => !names.includes(name)));
  }

  toggle(name: string, force?: boolean): boolean {
    const on = force === undefined ? !this.contains(name) : force;
    if (on) {
      this.add(name);
    } else {
      this.remove(name);
    }
    return on;
  }

  get length(): number {
    return this.names().length;
  }
}

/**
 * One element class for every tag. The three `instanceof`-narrowed subclasses
 * below exist only so webview code that asks "is this an input?" gets a
 * truthful answer; nothing else distinguishes them.
 */
class FakeElement extends FakeNode {
  readonly tagName: string;
  readonly namespaceURI: string | null;
  readonly attributes = new Map<string, string>();
  readonly dataset: Record<string, string> = {};
  readonly classList: FakeClassList;
  className = '';
  id = '';
  title = '';
  value = '';
  type = '';
  placeholder = '';
  href = '';
  src = '';
  alt = '';
  rows = 0;
  checked = false;
  selected = false;
  disabled = false;
  focused = false;

  constructor(tag: string, namespaceURI: string | null = null) {
    super();
    this.tagName = tag.toUpperCase();
    this.namespaceURI = namespaceURI;
    this.classList = new FakeClassList(this);
  }

  get localName(): string {
    return this.tagName.toLowerCase();
  }

  get children(): FakeElement[] {
    return this.childNodes.filter((child): child is FakeElement => child instanceof FakeElement);
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
    if (name === 'class') {
      this.className = value;
    }
    if (name === 'id') {
      this.id = value;
    }
  }

  getAttribute(name: string): string | null {
    if (name === 'class') {
      return this.className === '' ? (this.attributes.get('class') ?? null) : this.className;
    }
    return this.attributes.get(name) ?? null;
  }

  hasAttribute(name: string): boolean {
    return this.getAttribute(name) !== null;
  }

  removeAttribute(name: string): void {
    this.attributes.delete(name);
  }

  remove(): void {
    this.parentNode?.removeChild(this);
  }

  focus(): void {
    this.focused = true;
    doc.activeElement = this;
  }

  blur(): void {
    this.focused = false;
    if (doc.activeElement === this) {
      doc.activeElement = null;
    }
  }

  click(): void {
    this.dispatchEvent(new FakeEvent('click', { bubbles: true, cancelable: true }));
  }

  querySelector(selector: string): FakeElement | null {
    return querySelector(this, selector);
  }

  querySelectorAll(selector: string): FakeElement[] {
    return querySelectorAll(this, selector);
  }
}

class FakeHtmlInputElement extends FakeElement {}
class FakeHtmlSelectElement extends FakeElement {}
class FakeHtmlTextAreaElement extends FakeElement {}

function makeElement(tag: string, namespaceURI: string | null): FakeElement {
  const lower = tag.toLowerCase();
  if (namespaceURI === null && lower === 'input') {
    return new FakeHtmlInputElement(tag);
  }
  if (namespaceURI === null && lower === 'select') {
    return new FakeHtmlSelectElement(tag);
  }
  if (namespaceURI === null && lower === 'textarea') {
    return new FakeHtmlTextAreaElement(tag);
  }
  return new FakeElement(tag, namespaceURI);
}

// ---------------------------------------------------------------------------
// The selector subset
// ---------------------------------------------------------------------------

interface Simple {
  tag: string | null;
  classes: string[];
  id: string | null;
  attrs: Array<{ name: string; value: string | null }>;
}

/** `button.z-btn#save[data-id="x"]` → one `Simple`. Nothing else is accepted. */
function parseSimple(text: string): Simple {
  const simple: Simple = { tag: null, classes: [], id: null, attrs: [] };
  const pattern = /^([a-zA-Z][\w-]*)|^\.([\w-]+)|^#([\w-]+)|^\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/;
  let rest = text;
  while (rest.length > 0) {
    const match = pattern.exec(rest);
    if (match === null) {
      throw new Error(`mini-DOM: unsupported selector fragment "${rest}" in "${text}"`);
    }
    if (match[1] !== undefined) {
      simple.tag = match[1].toUpperCase();
    } else if (match[2] !== undefined) {
      simple.classes.push(match[2]);
    } else if (match[3] !== undefined) {
      simple.id = match[3];
    } else if (match[4] !== undefined) {
      const value = match[5] ?? match[6] ?? match[7] ?? null;
      simple.attrs.push({ name: match[4], value });
    }
    rest = rest.slice(match[0].length);
  }
  return simple;
}

function matchesSimple(node: FakeElement, simple: Simple): boolean {
  if (simple.tag !== null && node.tagName !== simple.tag) {
    return false;
  }
  if (simple.id !== null && node.id !== simple.id) {
    return false;
  }
  for (const name of simple.classes) {
    if (!node.classList.contains(name)) {
      return false;
    }
  }
  for (const attr of simple.attrs) {
    const actual = attr.name.startsWith('data-')
      ? (node.dataset[dataKey(attr.name)] ?? node.getAttribute(attr.name))
      : node.getAttribute(attr.name);
    if (actual === null || actual === undefined) {
      return false;
    }
    if (attr.value !== null && actual !== attr.value) {
      return false;
    }
  }
  return true;
}

function dataKey(attribute: string): string {
  return attribute
    .slice('data-'.length)
    .replace(/-([a-z])/g, (_all, letter: string) => letter.toUpperCase());
}

function descendants(root: FakeNode, out: FakeElement[] = []): FakeElement[] {
  for (const child of root.childNodes) {
    if (child instanceof FakeElement) {
      out.push(child);
      descendants(child, out);
    }
  }
  return out;
}

function querySelectorAll(root: FakeNode, selector: string): FakeElement[] {
  const parts = selector
    .trim()
    .split(/\s+/)
    .filter((part) => part !== '')
    .map(parseSimple);
  if (parts.length === 0) {
    return [];
  }
  let scope: FakeNode[] = [root];
  let found: FakeElement[] = [];
  for (const part of parts) {
    found = [];
    for (const container of scope) {
      for (const node of descendants(container)) {
        if (matchesSimple(node, part) && !found.includes(node)) {
          found.push(node);
        }
      }
    }
    scope = found;
  }
  return found;
}

function querySelector(root: FakeNode, selector: string): FakeElement | null {
  return querySelectorAll(root, selector)[0] ?? null;
}

// ---------------------------------------------------------------------------
// document / window
// ---------------------------------------------------------------------------

class FakeDocument {
  readonly documentElement: FakeElement;
  readonly body: FakeElement;
  readyState = 'complete';
  activeElement: FakeElement | null = null;

  constructor() {
    this.documentElement = new FakeElement('html');
    this.body = new FakeElement('body');
    this.documentElement.appendChild(this.body);
    // `updateDerivedTokens()` writes through `documentElement.style`; the token
    // layer is CSS, so the shim only has to accept the writes, not resolve them.
    Reflect.set(this.documentElement, 'style', {
      setProperty(): void {
        /* the cascade is not modelled — see the header */
      },
    });
  }

  createElement(tag: string): FakeElement {
    return makeElement(tag, null);
  }

  createElementNS(namespaceURI: string, tag: string): FakeElement {
    return makeElement(tag, namespaceURI);
  }

  createTextNode(text: string): FakeText {
    return new FakeText(text);
  }

  getElementById(id: string): FakeElement | null {
    return descendants(this.documentElement).find((node) => node.id === id) ?? null;
  }

  querySelector(selector: string): FakeElement | null {
    return querySelector(this.documentElement, selector);
  }

  querySelectorAll(selector: string): FakeElement[] {
    return querySelectorAll(this.documentElement, selector);
  }

  addEventListener(type: string, handler: Listener): void {
    addListener(this, type, handler);
  }

  removeEventListener(type: string, handler: Listener): void {
    removeListener(this, type, handler);
  }

  dispatchEvent(event: FakeEvent): boolean {
    event.target = this;
    for (const handler of [...(listenersFor(this).get(event.type) ?? [])]) {
      handler(event);
    }
    return !event.defaultPrevented;
  }
}

class FakeWindow {
  addEventListener(type: string, handler: Listener): void {
    addListener(this, type, handler);
  }

  removeEventListener(type: string, handler: Listener): void {
    removeListener(this, type, handler);
  }

  dispatchEvent(event: FakeEvent): boolean {
    event.target = this;
    for (const handler of [...(listenersFor(this).get(event.type) ?? [])]) {
      handler(event);
    }
    return !event.defaultPrevented;
  }
}

class FakeMutationObserver {
  observe(): void {
    /* the shim never mutates the workbench body, so nothing can fire */
  }

  disconnect(): void {
    /* symmetry with observe() */
  }
}

// ---------------------------------------------------------------------------
// The webview bridge
// ---------------------------------------------------------------------------

export interface PostedMessage {
  [key: string]: unknown;
}

/** Everything the bundle posted to the host, newest last. */
export const posted: PostedMessage[] = [];

let persistedState: unknown = undefined;

const vsCodeApi = {
  postMessage(message: unknown): void {
    if (typeof message === 'object' && message !== null) {
      posted.push(message as PostedMessage);
    }
  },
  getState(): unknown {
    return persistedState;
  },
  setState(state: unknown): void {
    persistedState = state;
  },
};

// ---------------------------------------------------------------------------
// Installation
// ---------------------------------------------------------------------------

const doc = new FakeDocument();
const win = new FakeWindow();

persistentTargets.add(doc);
persistentTargets.add(win);

const globals = globalThis as unknown as Record<string, unknown>;

// Only what webview code actually reaches for. Node 22 already defines `Event`,
// `MessageEvent` and `EventTarget`, and nothing under `src/webview/**` narrows
// against them, so they are left alone rather than shadowed.
globals.document = doc;
globals.window = win;
globals.Node = FakeNode;
globals.HTMLElement = FakeElement;
globals.HTMLInputElement = FakeHtmlInputElement;
globals.HTMLSelectElement = FakeHtmlSelectElement;
globals.HTMLTextAreaElement = FakeHtmlTextAreaElement;
globals.KeyboardEvent = FakeKeyboardEvent;
globals.MutationObserver = FakeMutationObserver;
globals.getComputedStyle = (): { getPropertyValue(): string } => ({
  getPropertyValue: (): string => '',
});
globals.requestAnimationFrame = (callback: () => void): number => {
  // Synchronous on purpose: a test that has to wait a frame to see a class is
  // a test that will be flaky on a loaded machine.
  callback();
  return 0;
};
globals.cancelAnimationFrame = (): void => {
  /* nothing is ever queued — see requestAnimationFrame above */
};
globals.acquireVsCodeApi = (): typeof vsCodeApi => vsCodeApi;

// ---------------------------------------------------------------------------
// The test-facing surface
// ---------------------------------------------------------------------------

export {
  FakeElement,
  FakeEvent,
  FakeKeyboardEvent,
  FakeMessageEvent,
  FakeNode,
  FakeText,
  SVG_NS,
};

/** A detached element to render into, of the same class `el()` produces. */
export function mountPoint(tag = 'div'): FakeElement {
  return makeElement(tag, null);
}

/**
 * Listeners on `document` and `window` — the two targets that outlive a widget.
 * A listener left on a node the caller has dropped is collected with the node
 * and is not a leak; a listener left on one of these is forever.
 */
export function persistentListenerCount(): number {
  let total = 0;
  for (const target of persistentTargets) {
    total += countListeners(target);
  }
  return total;
}

/** Every element under `root` matching the selector subset described above. */
export function findAll(root: FakeNode, selector: string): FakeElement[] {
  return querySelectorAll(root, selector);
}

/** The first match, or `null`. */
export function find(root: FakeNode, selector: string): FakeElement | null {
  return querySelector(root, selector);
}

/** Every class name anywhere under `root`, deduplicated. */
export function classNames(root: FakeNode): Set<string> {
  const names = new Set<string>();
  for (const node of descendants(root)) {
    for (const name of node.className.split(/\s+/)) {
      if (name !== '') {
        names.add(name);
      }
    }
  }
  return names;
}

/** Forget every message the bundle posted. */
export function resetPosted(): void {
  posted.splice(0, posted.length);
}

/** Empty `document.body` and drop the persisted view state. */
export function resetDom(): void {
  doc.body.childNodes.splice(0, doc.body.childNodes.length);
  doc.activeElement = null;
  persistedState = undefined;
  resetPosted();
}
