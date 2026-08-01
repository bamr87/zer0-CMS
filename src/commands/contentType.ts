/**
 * Content-type commands: generate one from a file, add the fields a file has
 * that its type does not declare, and bind a file to a type.
 *
 * All three edit `zer0.json` or the file's front matter — never VS Code
 * settings. A content type is repository schema: it describes what the site's
 * pages look like, it is reviewed in pull requests, and it must be identical
 * for everyone who checks the repository out. A user-scoped setting would be
 * none of those things.
 *
 * The generated type is explicitly **a starting point, not an authority**.
 * `generateContentTypeFrom` infers field types from key names first and value
 * shapes second, which is right often enough to save typing and wrong often
 * enough that the command opens `zer0.json` afterwards so the author sees what
 * it guessed. That is why nothing here writes silently.
 *
 * One asymmetry worth knowing: a workspace with **no** `contentTypes` array
 * still has a working content type — `DEFAULT_CONTENT_TYPE`, supplied by the
 * core so that "not configured yet" is a usable CMS rather than an error. Any
 * command that edits a type therefore has to materialise that default into the
 * file first, which `contentTypeEntries()` below does.
 */

import * as vscode from 'vscode';

import {
  CONTENT_TYPE_FIELD,
  DEFAULT_CONTENT_TYPE,
  DEFAULT_CONTENT_TYPE_NAME,
  generateContentTypeFrom,
  getContentTypes,
  missingFields,
  relPath,
  writeArticle,
  type ContentType,
  type Field,
  type Zer0Config,
} from '../core';
import { configFilePath, hasProjectConfig, updateConfigFileJson } from '../config';
import type { Zer0Shell } from '../extension';
import { notifyInfo, notifyWarning } from '../uiState';
import { activeArticle } from './content';
import { openInEditor, register, starterConfig } from './project';

/**
 * The `contentTypes` array as it appears in `zer0.json`, with the built-in
 * default materialised when the file declares none.
 *
 * Without this step, "add the missing fields to `default`" would append them
 * to a type that exists only in memory and vanish on the next read.
 */
function contentTypeEntries(json: Record<string, unknown>): Array<Record<string, unknown>> {
  const raw = json.contentTypes;
  const entries = Array.isArray(raw)
    ? raw.filter(
        (entry): entry is Record<string, unknown> =>
          typeof entry === 'object' && entry !== null && !Array.isArray(entry),
      )
    : [];
  if (entries.length === 0) {
    return [{ ...DEFAULT_CONTENT_TYPE }];
  }
  return entries;
}

/** The `fields` array of a raw content-type entry. */
function fieldEntries(entry: Record<string, unknown>): unknown[] {
  return Array.isArray(entry.fields) ? [...entry.fields] : [];
}

/** Make sure there is a project config to write types into. */
async function ensureProjectConfig(): Promise<boolean> {
  if (hasProjectConfig()) {
    return true;
  }
  const answer = await notifyWarning(
    'this workspace has no project config yet.',
    'Initialize project',
  );
  if (answer !== 'Initialize project') {
    return false;
  }
  await updateConfigFileJson((json) => {
    Object.assign(json, starterConfig());
  });
  return true;
}

/** Open `zer0.json` so the author reviews what was just written. */
async function revealProjectConfig(): Promise<void> {
  const target = configFilePath();
  if (target !== undefined) {
    await openInEditor(target);
  }
}

/** A default name for a generated type: what the file claims, else its folder. */
function suggestedName(cfg: Zer0Config, filePath: string, declared: unknown): string {
  if (typeof declared === 'string' && declared.trim() !== '') {
    return declared.trim();
  }
  const relative = relPath(cfg, filePath);
  const parent = relative.split('/').slice(-2, -1)[0] ?? '';
  return parent.replace(/^_/, '') || DEFAULT_CONTENT_TYPE_NAME;
}

export function registerContentTypeCommands(shell: Zer0Shell): void {
  // --- Generate a content type from the active file ------------------------
  register(shell, 'contentType.generate', async () => {
    const active = await activeArticle();
    if (active === undefined) {
      return;
    }
    const { cfg, article, filePath } = active;

    if (Object.keys(article.data).length === 0) {
      await notifyWarning('this file has no front matter to infer a content type from.');
      return;
    }
    if (!(await ensureProjectConfig())) {
      return;
    }

    const name = await vscode.window.showInputBox({
      title: 'Generate content type',
      prompt: 'Name for the new content type',
      value: suggestedName(cfg, filePath, article.data[CONTENT_TYPE_FIELD]),
      ignoreFocusOut: true,
      validateInput: (value) => (value.trim() === '' ? 'A name is required.' : undefined),
    });
    if (name === undefined || name.trim() === '') {
      return;
    }

    const generated: ContentType = generateContentTypeFrom(article.data, name.trim());
    if (generated.fields.length === 0) {
      await notifyWarning('none of this file’s keys map onto a supported field type.');
      return;
    }

    let replaced = false;
    await updateConfigFileJson((json) => {
      const entries = contentTypeEntries(json);
      const index = entries.findIndex((entry) => entry.name === generated.name);
      if (index >= 0) {
        entries[index] = { ...generated };
        replaced = true;
      } else {
        entries.push({ ...generated });
      }
      json.contentTypes = entries;
    });

    shell.log.info(
      `${replaced ? 'replaced' : 'generated'} content type "${generated.name}" ` +
        `(${generated.fields.length} field(s)) from ${relPath(cfg, filePath)}`,
    );
    await notifyInfo(
      `${replaced ? 'replaced' : 'added'} content type "${generated.name}" with ` +
        `${generated.fields.length} field(s). Review it before relying on it.`,
    );
    await revealProjectConfig();
    await shell.store.refresh();
  });

  // --- Add the fields the file has and the type does not -------------------
  register(shell, 'contentType.addMissingFields', async () => {
    const active = await activeArticle();
    if (active === undefined) {
      return;
    }
    const { cfg, article, contentType, filePath } = active;

    const missing: Field[] = missingFields(contentType, article.data);
    if (missing.length === 0) {
      await notifyInfo(`"${contentType.name}" already declares every key in this file.`);
      return;
    }
    if (!(await ensureProjectConfig())) {
      return;
    }

    await updateConfigFileJson((json) => {
      const entries = contentTypeEntries(json);
      const index = entries.findIndex((entry) => entry.name === contentType.name);
      // A type that is not in the file yet (the built-in default) is written
      // out whole; one that is gets only its `fields` array extended, so the
      // author's other keys and their formatting survive.
      if (index < 0) {
        entries.push({ ...contentType, fields: [...contentType.fields, ...missing] });
      } else {
        const entry = entries[index];
        if (entry !== undefined) {
          entry.fields = [...fieldEntries(entry), ...missing];
        }
      }
      json.contentTypes = entries;
    });

    shell.log.info(
      `added ${missing.length} field(s) to "${contentType.name}" from ${relPath(cfg, filePath)}: ` +
        missing.map((field) => field.name).join(', '),
    );
    await notifyInfo(
      `added ${missing.length} field(s) to "${contentType.name}": ` +
        missing.map((field) => field.name).join(', '),
    );
    await revealProjectConfig();
    await shell.store.refresh();
  });

  // --- Bind this file to a content type ------------------------------------
  register(shell, 'contentType.set', async (arg: unknown) => {
    const active = await activeArticle();
    if (active === undefined) {
      return;
    }
    const { cfg, article, contentType, filePath } = active;

    const types = getContentTypes(cfg);
    const requested = typeof arg === 'string' ? arg.trim() : '';
    const chosen =
      requested !== ''
        ? types.find((type) => type.name === requested)
        : (
            await vscode.window.showQuickPick(
              types.map((type) => ({
                label: type.name,
                description:
                  type.name === contentType.name
                    ? 'current'
                    : `${type.fields.length} field${type.fields.length === 1 ? '' : 's'}`,
                type,
              })),
              { placeHolder: 'Select a content type for this file', ignoreFocusOut: true },
            )
          )?.type;

    if (chosen === undefined) {
      if (requested !== '') {
        await notifyWarning(`unknown content type "${requested}".`);
      }
      return;
    }

    // The binding lives in the file, in the key the resolution chain reads
    // first. One line changes; everything else in the front matter is untouched.
    await writeArticle(article, [{ key: CONTENT_TYPE_FIELD, value: chosen.name }], cfg);
    shell.log.info(`${relPath(cfg, filePath)} is now a "${chosen.name}"`);
    shell.diagnostics.validateVisible();
    await shell.store.refresh();
  });
}
