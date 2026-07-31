/**
 * The two file-system controls: `image` and `file`.
 *
 * Both are drop-zone buttons that delegate the actual choosing to the host —
 * `pickImage` and `pickFile` open a native quick pick or open dialog, which is
 * why the media dashboard Front Matter needed for this could be dropped
 * entirely. The webview never sees a file system; it names an intent and takes
 * back a path.
 *
 * Three behaviours are reproduced deliberately:
 *
 *   • **`<failed to process>` is empty.** A placeholder that failed to resolve
 *     writes that sentinel into the front matter. Treating it as a value would
 *     show a broken preview and, worse, satisfy a required field with garbage.
 *   • **The multi-image grid keeps the add button.** `multiple` switches the
 *     container to a two-column grid and the add button stays visible below it,
 *     so adding the fourth image is the same gesture as adding the first.
 *   • **A preview that cannot load draws a box, not a broken glyph.** The
 *     fallback carries Front Matter's original copy, typo included, because
 *     that string is what project documentation and issue reports quote.
 *
 * Known limitation: a workspace-relative path cannot be loaded by a webview
 * without an `asWebviewUri` round trip, and the request vocabulary in PLAN §4.3
 * has no media-resolve operation. The preview therefore tries the raw value as
 * a source and falls back to the box on error, with the path shown underneath
 * so the author can always see what is set. Adding a `resolveMedia` op (or
 * projecting webview URIs into `PanelState`) would upgrade this in one place.
 */

import { clear, el, icon, on, srOnly } from '../../shared/dom';
import type { FieldFactory, FmValue } from '../../shared/protocol';
import { errorText, fieldShell, labelOf, shellWidget, toStringList } from './index';

/** `path/to/x.png` → `x.png`, for both separators. */
function basename(value: string): string {
  const cut = Math.max(value.lastIndexOf('/'), value.lastIndexOf('\\'));
  return cut === -1 ? value : value.slice(cut + 1);
}

/** Whatever the host answered, as a list of paths. */
function pickedPaths(value: unknown): string[] {
  if (typeof value === 'string') {
    return value === '' ? [] : [value];
  }
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === 'string' && item !== '');
  }
  return [];
}

// ---------------------------------------------------------------------------
// image
// ---------------------------------------------------------------------------

/** The 120px box drawn in place of an image that would not load. */
function imageFallback(path: string): HTMLElement {
  return el(
    'div',
    { class: 'metadata_field__image_fallback', title: path },
    icon('error'),
    el('span', {}, "The image coundn't be loaded"),
  );
}

export const previewImageField: FieldFactory = (ctx) => {
  const field = ctx.field;
  const label = labelOf(field);
  const multiple = field.multiple === true;
  const shell = fieldShell(ctx);

  let values = toStringList(ctx.value);

  const previews = el('div', { class: multiple ? 'metadata_field__multiple_images' : 'z-stack' });
  const addButton = el(
    'button',
    { class: 'metadata_field__preview_image__button', type: 'button' },
    icon('file-media'),
    el('span', {}, `Add your ${label}`),
  );
  shell.control.appendChild(previews);
  shell.control.appendChild(addButton);

  const emit = (): void => {
    shell.setEmpty(values.length === 0);
    const next: FmValue = multiple ? values.slice() : (values[0] ?? '');
    ctx.onChange(next);
  };

  const preview = (path: string, index: number): HTMLElement => {
    const box = el('div', { class: 'metadata_field__preview_image__preview' });
    const image = el('img', { src: path, alt: `${label} preview`, title: path });
    // A path the webview cannot resolve fails silently otherwise; swapping in
    // the fallback keeps the remove button reachable.
    image.addEventListener('error', () => {
      if (image.parentElement === box) {
        box.replaceChild(imageFallback(path), image);
      }
    });
    box.appendChild(image);
    box.appendChild(el('span', { class: 'z-muted', style: 'padding:0.25rem' }, path));
    box.appendChild(
      el(
        'button',
        {
          class: 'metadata_field__preview_image__remove',
          type: 'button',
          onclick: () => {
            values = values.filter((_item, i) => i !== index);
            paint();
            emit();
          },
        },
        'Remove image',
      ),
    );
    return box;
  };

  function paint(): void {
    clear(previews);
    values.forEach((path, index) => {
      previews.appendChild(preview(path, index));
    });
    // A single-image field hides the add button once it is filled; a multiple
    // one keeps it, because there is always another image to add.
    addButton.style.display = !multiple && values.length > 0 ? 'none' : '';
    shell.setEmpty(values.length === 0);
  }
  paint();

  let disposed = false;
  const released = [
    on(addButton, 'click', () => {
      shell.setError(null);
      shell.setLoading('Selecting image...');
      void ctx.msg
        .request<unknown>('pickImage', {
          filePath: ctx.state.filePath,
          fieldName: field.name,
          parents: ctx.parents,
          multiple,
          value: multiple ? values.slice() : (values[0] ?? ''),
        })
        .then((answer) => {
          if (disposed) {
            return;
          }
          shell.setLoading(null);
          const picked = pickedPaths(answer);
          if (picked.length === 0) {
            return;
          }
          values = multiple ? [...values, ...picked] : picked.slice(0, 1);
          paint();
          emit();
        })
        .catch((error: unknown) => {
          if (disposed) {
            return;
          }
          shell.setLoading(null);
          // The picker can outlive the messenger's ten-second request window.
          // The host still applies the choice and pushes a new snapshot, so
          // this is a retry prompt, not a failure.
          shell.setError(`No image was returned: ${errorText(error)}`);
        });
    }),
  ];

  return shellWidget(shell, {
    setValue(value) {
      values = toStringList(value);
      paint();
    },
    focus() {
      addButton.focus();
    },
    dispose() {
      disposed = true;
      for (const release of released) {
        release();
      }
    },
  });
};

// ---------------------------------------------------------------------------
// file
// ---------------------------------------------------------------------------

export const fileField: FieldFactory = (ctx) => {
  const field = ctx.field;
  const label = labelOf(field);
  const multiple = field.multiple === true;
  const shell = fieldShell(ctx);

  let values = toStringList(ctx.value);

  const addButton = el(
    'button',
    { class: 'metadata_field__file__button', type: 'button' },
    icon('file'),
    el('span', {}, `Add your ${label}`),
  );
  const list = el('ul', { class: 'metadata_field__file__list' });
  shell.control.appendChild(addButton);
  shell.control.appendChild(list);

  const emit = (): void => {
    shell.setEmpty(values.length === 0);
    ctx.onChange(multiple ? values.slice() : (values[0] ?? ''));
  };

  function paint(): void {
    clear(list);
    values.forEach((path, index) => {
      list.appendChild(
        el(
          'li',
          { class: 'metadata_field__file__list__item', title: path },
          icon('link'),
          el('span', {}, basename(path)),
          el(
            'button',
            {
              class: 'z-icon-btn z-icon-btn--danger',
              type: 'button',
              title: 'Delete file',
              onclick: () => {
                values = values.filter((_item, i) => i !== index);
                paint();
                emit();
              },
            },
            icon('trash'),
            srOnly('Delete file'),
          ),
        ),
      );
    });
    // Once there is at least one file the drop zone collapses to a compact row,
    // which is what `.not_empty` restyles.
    addButton.classList.toggle('not_empty', values.length > 0);
    shell.setEmpty(values.length === 0);
  }
  paint();

  let disposed = false;
  const released = [
    on(addButton, 'click', () => {
      shell.setError(null);
      shell.setLoading('Selecting file...');
      void ctx.msg
        .request<unknown>('pickFile', {
          filePath: ctx.state.filePath,
          fieldName: field.name,
          parents: ctx.parents,
          multiple,
          fileExtensions: field.fileExtensions ?? [],
          value: multiple ? values.slice() : (values[0] ?? ''),
          type: 'file',
        })
        .then((answer) => {
          if (disposed) {
            return;
          }
          shell.setLoading(null);
          const picked = pickedPaths(answer);
          if (picked.length === 0) {
            return;
          }
          values = multiple ? [...values, ...picked] : picked.slice(0, 1);
          paint();
          emit();
        })
        .catch((error: unknown) => {
          if (disposed) {
            return;
          }
          shell.setLoading(null);
          shell.setError(`No file was returned: ${errorText(error)}`);
        });
    }),
  ];

  return shellWidget(shell, {
    setValue(value) {
      values = toStringList(value);
      paint();
    },
    focus() {
      addButton.focus();
    },
    dispose() {
      disposed = true;
      for (const release of released) {
        release();
      }
    },
  });
};
