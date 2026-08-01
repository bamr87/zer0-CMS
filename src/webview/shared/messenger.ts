/**
 * The webview end of the wire.
 *
 * Wraps `acquireVsCodeApi()` — which a webview may call exactly once — behind a
 * lazily-created singleton, and adds the two things raw `postMessage` lacks: a
 * request/response channel keyed by `requestId`, and the persisted UI state
 * object described in PLAN §4.5.
 *
 * `request()` rejects after ten seconds. That timeout is not defensive
 * decoration: a field control shows a loading overlay while a request is in
 * flight, so a reply the host never sends would wedge that control forever.
 * Failing loudly turns a dropped reply into a visible error the user can retry.
 */

import type { HostMsg, RequestOp, ViewMsg, ViewState, ViewUiState, CommandId } from './protocol';

interface VsCodeApi {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
}

declare function acquireVsCodeApi(): VsCodeApi;

/** How long a `request()` waits before giving up. */
export const REQUEST_TIMEOUT_MS = 10_000;

const EMPTY_UI_STATE: ViewUiState = { collapse: {} };

function isHostMsg(value: unknown): value is HostMsg {
  return typeof value === 'object' && value !== null && typeof Reflect.get(value, 'type') === 'string';
}

interface Pending {
  resolve(value: unknown): void;
  reject(error: Error): void;
  timer: ReturnType<typeof setTimeout>;
}

export class Messenger {
  private readonly api: VsCodeApi;
  private readonly pending = new Map<string, Pending>();
  private readonly stateHandlers = new Set<(state: ViewState) => void>();
  private readonly msgHandlers = new Set<(msg: HostMsg) => void>();
  private seq = 0;

  constructor(api: VsCodeApi) {
    this.api = api;
    window.addEventListener('message', (event: MessageEvent<unknown>) => {
      this.receive(event.data);
    });
  }

  // -- outbound ------------------------------------------------------------

  post(message: ViewMsg): void {
    this.api.postMessage(message);
  }

  /** Tell the host the bundle is mounted and wants its first snapshot. */
  ready(): void {
    this.post({ type: 'ready' });
  }

  /** Name an intent. Never carries a gate override — see decision D5. */
  command(id: CommandId, args?: unknown): void {
    this.post(args === undefined ? { type: 'command', id } : { type: 'command', id, args });
  }

  updateField(path: string[], value: unknown): void {
    this.post({ type: 'updateField', path, value });
  }

  log(level: 'info' | 'warn' | 'error' | 'verbose', message: string): void {
    this.post({ type: 'log', level, message });
  }

  /** Round-trip a computation the host owns. Rejects on timeout or host error. */
  request<T>(op: RequestOp, payload?: unknown): Promise<T> {
    const requestId = `r${++this.seq}`;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`Request "${op}" timed out after ${REQUEST_TIMEOUT_MS}ms`));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(requestId, {
        resolve: (value) => {
          resolve(value as T);
        },
        reject,
        timer,
      });
      this.post(
        payload === undefined
          ? { type: 'request', requestId, op }
          : { type: 'request', requestId, op, payload },
      );
    });
  }

  // -- inbound -------------------------------------------------------------

  /** Subscribe to full-state snapshots. Returns an unsubscribe function. */
  onState(handler: (state: ViewState) => void): () => void {
    this.stateHandlers.add(handler);
    return () => {
      this.stateHandlers.delete(handler);
    };
  }

  /** Subscribe to every host message, including the imperative four. */
  onMessage(handler: (msg: HostMsg) => void): () => void {
    this.msgHandlers.add(handler);
    return () => {
      this.msgHandlers.delete(handler);
    };
  }

  private receive(data: unknown): void {
    if (!isHostMsg(data)) {
      return;
    }
    if (data.type === 'result') {
      const pending = this.pending.get(data.requestId);
      if (!pending) {
        // A reply that arrived after its timeout. Dropping it is correct: the
        // caller already saw the rejection and moved on.
        return;
      }
      this.pending.delete(data.requestId);
      clearTimeout(pending.timer);
      if (data.error !== undefined) {
        pending.reject(new Error(data.error));
      } else {
        pending.resolve(data.value);
      }
      return;
    }
    if (data.type === 'state') {
      for (const handler of this.stateHandlers) {
        handler(data.state);
      }
    }
    for (const handler of this.msgHandlers) {
      handler(data);
    }
  }

  // -- persisted UI state (§4.5) -------------------------------------------

  getState(): ViewUiState {
    const raw = this.api.getState();
    if (typeof raw !== 'object' || raw === null) {
      return { ...EMPTY_UI_STATE, collapse: {} };
    }
    const state = raw as Partial<ViewUiState>;
    return { ...state, collapse: { ...(state.collapse ?? {}) } };
  }

  /** Merge a patch into the persisted state. Absent keys are left alone. */
  setState(patch: Partial<ViewUiState>): ViewUiState {
    const next: ViewUiState = { ...this.getState(), ...patch };
    if (patch.collapse) {
      next.collapse = { ...this.getState().collapse, ...patch.collapse };
    }
    this.api.setState(next);
    return next;
  }

  /** Record one collapse decision and mirror it into workspace state. */
  setCollapsed(id: string, open: boolean): void {
    const key = `collapse_${id}`;
    this.setState({ collapse: { [key]: open ? 'true' : 'false' } });
    this.post({ type: 'setUiState', key, value: open ? 'true' : 'false' });
  }

  /** Default open, exactly as Front Matter did: only the literal `'false'`
   *  closes a section, so an unknown id is open. */
  isCollapsed(id: string): boolean {
    return this.getState().collapse[`collapse_${id}`] === 'false';
  }
}

let instance: Messenger | undefined;

/**
 * The one `Messenger` for this webview. Acquisition is lazy so that importing
 * this module outside a webview (a unit test, a type-only import) does not
 * throw on the missing global.
 */
export function getMessenger(): Messenger {
  if (!instance) {
    instance = new Messenger(acquireVsCodeApi());
  }
  return instance;
}

/** Test seam: install a stub API instead of the real webview bridge. */
export function setMessenger(messenger: Messenger): void {
  instance = messenger;
}
