/**
 * `svgEl()` — the SVG twin of `el()`.
 *
 * `el()` calls `document.createElement`, which always produces an HTML element:
 * an `<svg>` built that way is inert, and every child inside it is an unknown
 * HTML tag that lays out as nothing. SVG lives in its own namespace and can
 * only be created through `createElementNS`, so a sparkline, a gauge or a
 * timeline in a later tab has no way to exist without this file.
 *
 * The no-markup rule applies here identically and for the same reason: an SVG
 * document is a script host, so `innerHTML` on an `<svg>` is not a lesser risk
 * than `innerHTML` on a `<div>`. Text goes in through `document.createTextNode`
 * and structure is built node by node. eslint's `no-restricted-properties`
 * covers `src/webview/**`, this file included.
 *
 * Everything is written with `setAttribute`. SVG elements do expose typed
 * properties (`SVGAnimatedLength` and friends), but they are read-only mirrors
 * of the attributes for most of the geometry a chart uses, and assigning to
 * them silently does nothing — the exact failure mode the CSP-dead `style:`
 * prop had. One writer, no surprises.
 */

export const SVG_NS = 'http://www.w3.org/2000/svg';

export type SvgChild = Node | string | number | null | undefined | false | readonly SvgChild[];

export type SvgProps = {
  /** Event listeners keyed by event name, e.g. `{ click: fn }`. */
  on?: Record<string, EventListener>;
} & Record<string, string | number | boolean | null | undefined | Record<string, EventListener>>;

function appendSvgChild(parent: Node, child: SvgChild): void {
  if (child === null || child === undefined || child === false) {
    return;
  }
  if (Array.isArray(child)) {
    for (const nested of child as readonly SvgChild[]) {
      appendSvgChild(parent, nested);
    }
    return;
  }
  if (typeof child === 'string' || typeof child === 'number') {
    parent.appendChild(document.createTextNode(String(child)));
    return;
  }
  parent.appendChild(child as Node);
}

/**
 * Build one SVG element in the SVG namespace.
 *
 * ```ts
 * svgEl('svg', { viewBox: '0 0 120 24', role: 'img', 'aria-label': 'Runs per day' },
 *   svgEl('polyline', { points, fill: 'none', stroke: 'currentColor' }));
 * ```
 *
 * `true` writes an empty attribute, `false`/`null`/`undefined` remove it, and
 * every other value is stringified — the same contract `el()`'s `attrs` has, so
 * a reader moving between the two files is never surprised.
 */
export function svgEl(tag: string, props?: SvgProps, ...children: SvgChild[]): SVGElement {
  const node = document.createElementNS(SVG_NS, tag) as SVGElement;
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (key === 'on') {
        for (const [name, handler] of Object.entries(value as Record<string, EventListener>)) {
          node.addEventListener(name, handler);
        }
        continue;
      }
      if (value === undefined || value === null || value === false) {
        node.removeAttribute(key);
        continue;
      }
      node.setAttribute(key, value === true ? '' : String(value));
    }
  }
  for (const child of children) {
    appendSvgChild(node, child);
  }
  return node;
}

/**
 * A root `<svg>` sized by its `viewBox` alone.
 *
 * Charts here scale with their container rather than with a pixel width, so the
 * root carries `viewBox` + `preserveAspectRatio` and leaves the box to CSS.
 * `label` becomes `role="img"` + `aria-label`: a chart with no accessible name
 * is a decorative rectangle to a screen reader, which is never what a figure in
 * an operator console is for.
 */
export function svgRoot(
  options: { width: number; height: number; label: string; className?: string },
  ...children: SvgChild[]
): SVGElement {
  return svgEl(
    'svg',
    {
      viewBox: `0 0 ${options.width} ${options.height}`,
      preserveAspectRatio: 'none',
      role: 'img',
      'aria-label': options.label,
      ...(options.className === undefined ? {} : { class: options.className }),
    },
    ...children,
  );
}
