/**
 * The `.cms/` contract and the distribution worklist.
 *
 * Two of these four commands shell out to Python, which makes them the only
 * commands in the extension that run somebody else's code. Three rules follow
 * from that, and all three are visible below.
 *
 * **The engine is optional.** `.cms/` absent is a normal state (decision D9) —
 * the page index supplies the same `ContentRecord` shape with `health: -1`, and
 * every surface keeps working. So a missing interpreter or a missing script is
 * reported as a fact about this workspace, not as a failure of the extension.
 * `runEngine` never rejects; it returns a code, and code `2` means "the
 * normalizer found work", not "something broke".
 *
 * **A preview never writes.** `contract.normalizePreview` runs the normalizer
 * without `--apply` and renders its output into a scratch document. The
 * `--apply` variant is a separate command with a separate modal confirmation
 * that says, in words, that it rewrites files — because it does, in bulk,
 * across every directory in `cms.contentDirs`.
 *
 * **The worklist comes from the same renderer as the tree.**
 * `writeCateringWorklist` is `renderWorklist` plus a write, so the file on disk
 * and the Distribution view can never disagree. With no `.cms/` there is
 * nowhere to write *into*, and the command renders the same bytes into an
 * untitled document instead of inventing a directory.
 */

import * as vscode from 'vscode';

import {
  ENGINE_COMMANDS,
  condenseNormalizerOutput,
  engineConfigFor,
  relPath,
  renderWorklist,
  runEngine,
  runNormalizerApply,
  runNormalizerPreview,
  utcDate,
  writeCateringWorklist,
  type EngineCommand,
  type EngineResult,
  type Zer0Config,
} from '../core';
import { currentConfig } from '../config';
import type { Zer0Shell } from '../extension';
import { confirm, notifyError, notifyInfo, notifyWarning } from '../uiState';
import { openInEditor, register, showReport } from './project';

/** One-line descriptions, so the picker is readable without the Python docs. */
const COMMAND_BLURBS: Record<EngineCommand, string> = {
  index: 'Rebuild .cms/index/ from the content on disk',
  analyze: 'Score health and freshness, and collect issues',
  plan: 'Produce the remediation worklists',
  all: 'index → analyze → plan',
  status: 'Report what the contract currently holds',
};

/** Everything an engine run said, in one readable block. */
function renderEngineResult(title: string, result: EngineResult): string {
  const sections = [`# ${title}`, ''];
  sections.push(
    result.changesPending
      ? '_Exit code 2 — there are changes to apply. Not a failure._'
      : `_Exit code ${result.code}._`,
    '',
  );
  if (result.stdout.trim() !== '') {
    sections.push('## Output', '', '```', result.stdout.trimEnd(), '```', '');
  }
  if (result.stderr.trim() !== '') {
    sections.push('## Diagnostics', '', '```', result.stderr.trimEnd(), '```', '');
  }
  if (result.stdout.trim() === '' && result.stderr.trim() === '') {
    sections.push('The engine produced no output.', '');
  }
  return sections.join('\n');
}

/** Log a run in full; the output channel is where the detail belongs. */
function logResult(shell: Zer0Shell, label: string, result: EngineResult): void {
  shell.log.info(`${label}: exit ${result.code}${result.changesPending ? ' (changes pending)' : ''}`);
  if (result.stdout.trim() !== '') {
    shell.log.verbose(result.stdout.trimEnd());
  }
  if (result.stderr.trim() !== '') {
    shell.log.warn(result.stderr.trimEnd());
  }
}

/** `true` when there is a workspace to run anything in. */
async function requireWorkspace(cfg: Zer0Config): Promise<boolean> {
  if (cfg.workspaceRoot !== '') {
    return true;
  }
  await notifyWarning('open a folder before running the CMS engine.');
  return false;
}

export function registerContractCommands(shell: Zer0Shell): void {
  // --- Run the engine ------------------------------------------------------
  register(shell, 'contract.run', async (arg: unknown) => {
    const cfg = currentConfig();
    if (!(await requireWorkspace(cfg))) {
      return;
    }

    const requested = typeof arg === 'string' ? arg.trim() : '';
    const command: EngineCommand | undefined = ENGINE_COMMANDS.includes(requested as EngineCommand)
      ? (requested as EngineCommand)
      : (
          await vscode.window.showQuickPick(
            ENGINE_COMMANDS.map((id) => ({ label: id, description: COMMAND_BLURBS[id] })),
            { placeHolder: `Run ${cfg.cms.engineScript}`, ignoreFocusOut: true },
          )
        )?.label;

    if (command === undefined) {
      return;
    }

    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `zer0-CMS: cms ${command}…` },
      () => runEngine(engineConfigFor(cfg), command),
    );
    logResult(shell, `cms ${command}`, result);

    // The engine writes `.cms/`; the store's watcher will notice, but an
    // explicit refresh makes the trees update before the debounce elapses.
    await shell.store.refresh();

    if (result.code !== 0 && !result.changesPending) {
      // A failed run is exactly when the output matters, so it is put in front
      // of the user rather than left in a channel they have to know about.
      await showReport(renderEngineResult(`cms ${command} — failed`, result));
      await notifyError(`cms ${command} exited ${result.code}.`);
      return;
    }
    if (command === 'status') {
      // `status` produces nothing but a report; a toast saying it finished
      // would be the least useful possible rendering of it.
      await showReport(renderEngineResult('cms status', result));
      return;
    }
    await notifyInfo(`cms ${command} finished.`);
  });

  // --- Normalize front matter (preview) ------------------------------------
  register(shell, 'contract.normalizePreview', async () => {
    const cfg = currentConfig();
    if (!(await requireWorkspace(cfg))) {
      return;
    }

    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: 'zer0-CMS: normalizing (dry run)…' },
      () => runNormalizerPreview(engineConfigFor(cfg)),
    );
    logResult(shell, 'normalize --dry-run', result);

    // The normalizer prints one SKIP line per vendored file, which on a large
    // site outnumbers the real output ten to one. Condensing keeps the count
    // rather than pretending those files were not considered.
    const { shown, skipped } = condenseNormalizerOutput(result.stdout);
    await showReport(
      [
        '# Normalize front matter — preview',
        '',
        '_Nothing was written. Run **Normalize front matter (apply)** to make these changes._',
        '',
        result.changesPending
          ? '_The normalizer reports changes are pending._'
          : '_The normalizer reports nothing to change._',
        '',
        ...(skipped === 0
          ? []
          : [`${skipped} read-only/vendored file(s) were skipped and are not listed.`, '']),
        '```',
        shown === '' ? '(no output)' : shown,
        '```',
        ...(result.stderr.trim() === '' ? [] : ['', '## Diagnostics', '', '```', result.stderr.trimEnd(), '```']),
        '',
      ].join('\n'),
    );
  });

  // --- Normalize front matter (apply) --------------------------------------
  register(shell, 'contract.normalizeApply', async () => {
    const cfg = currentConfig();
    if (!(await requireWorkspace(cfg))) {
      return;
    }

    // This one rewrites files in bulk. The dialog names the directories and
    // says the word "rewrites", because "Normalize" on a button does not.
    const ok = await confirm(
      'Rewrite front matter across the configured content directories?',
      'Rewrite files',
      [
        `Script: ${cfg.cms.normalizerScript}`,
        `Directories: ${cfg.cms.contentDirs.join(', ') || '(none configured)'}`,
        '',
        'This edits files on disk. Commit or stash first — the preview command shows what it would do.',
      ].join('\n'),
    );
    if (!ok) {
      return;
    }

    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: 'zer0-CMS: normalizing…' },
      () => runNormalizerApply(engineConfigFor(cfg)),
    );
    logResult(shell, 'normalize --apply', result);
    await shell.store.refresh();

    const { shown, skipped } = condenseNormalizerOutput(result.stdout);
    await showReport(
      [
        '# Normalize front matter — applied',
        '',
        `_Exit code ${result.code}._`,
        '',
        ...(skipped === 0 ? [] : [`${skipped} read-only/vendored file(s) were skipped.`, '']),
        '```',
        shown === '' ? '(no output)' : shown,
        '```',
        ...(result.stderr.trim() === '' ? [] : ['', '## Diagnostics', '', '```', result.stderr.trimEnd(), '```']),
        '',
      ].join('\n'),
    );

    if (result.code !== 0 && !result.changesPending) {
      shell.log.show(false);
      await notifyError(`the normalizer exited ${result.code}. See the output channel.`);
    }
  });

  // --- Generate the distribution worklist -----------------------------------
  register(shell, 'catering.worklist', async () => {
    const snapshot = await shell.store.current();
    const date = utcDate();

    if (!snapshot.contract.present) {
      // Nowhere to write it, but the rendering is still the useful part.
      await showReport(
        `${renderWorklist(snapshot.catering, date)}\n` +
          '\n> No `.cms/` contract in this workspace — this was rendered, not written. ' +
          'Adopt the CMS engine to make worklists part of the repository.\n',
      );
      return;
    }

    const target = await writeCateringWorklist(snapshot.contract, snapshot.catering, date);
    const relative = relPath(snapshot.cfg, target);
    shell.log.info(`wrote ${relative}`);
    const answer = await notifyInfo(`wrote ${relative}`, 'Open');
    if (answer === 'Open') {
      await openInEditor(target);
    }
  });
}
