// The editor's Markdown round trip: what TipTap reads it writes back
// unchanged, an edit made through the editor comes out as Markdown, and a
// block it would rewrite opens as its source instead — so nobody's Liquid,
// HTML or hand-formatting is changed behind their back.
import { Editor } from '@tiptap/core';
import { Markdown } from '@tiptap/markdown';
import StarterKit from '@tiptap/starter-kit';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { RichText, roundTrips, throughEditor } from '../src';
import { fakePlatform, renderUi } from '../../../test/harness';

const PLAIN = 'We copy the site **every night**, and keep *a week* of copies.\n\n- the pages\n- the images';

describe('the Markdown round trip', () => {
  it('writes back what it read', () => {
    expect(throughEditor(PLAIN, 'markdown')).toBe(PLAIN);
    expect(roundTrips(PLAIN, 'markdown')).toBe(true);
    expect(roundTrips('## A heading\n\nA paragraph with `code` and a [link](https://example.com).', 'markdown')).toBe(true);
  });

  it('turns an edit made in the editor into Markdown', () => {
    const editor = new Editor({ element: null, extensions: [StarterKit, Markdown], content: 'Backups', contentType: 'markdown' });
    editor.commands.setTextSelection(editor.state.doc.content.size - 1);
    editor.commands.insertContent(' matter');
    editor.commands.selectAll();
    editor.commands.toggleBold();
    expect(editor.getMarkdown()).toBe('**Backups matter**');
    editor.destroy();
  });

  it('knows what it would rewrite', () => {
    expect(roundTrips('<div class="note">Raw HTML</div>', 'markdown')).toBe(false);
    expect(roundTrips('* a list written with stars', 'markdown')).toBe(false);
  });
});

describe('<RichText>', () => {
  const { api } = fakePlatform({});

  it('opens a block it can reproduce in the rich editor', () => {
    renderUi(<RichText value={PLAIN} format="markdown" label="Body" onChange={vi.fn()} />, { api });
    expect(screen.getByRole('textbox', { name: 'Body' })).toHaveAttribute('contenteditable', 'true');
    expect(screen.queryByText('Edited as source')).toBeNull();
  });

  it('opens a block it would rewrite as source, and edits it verbatim', async () => {
    const onChange = vi.fn();
    const liquid = '<div class="note">{% include note.html %}</div>';
    renderUi(<RichText value={liquid} format="markdown" label="Body" onChange={onChange} />, { api });
    expect(screen.getByText('Edited as source')).toBeInTheDocument();
    const source = screen.getByRole('textbox', { name: 'Body' });
    expect(source).toHaveValue(liquid);
    await userEvent.type(source, '!');
    expect(onChange).toHaveBeenLastCalledWith(`${liquid}!`);
  });

  it('shows the Markdown of a rich block on request', async () => {
    renderUi(<RichText value={PLAIN} format="markdown" label="Body" onChange={vi.fn()} />, { api });
    await userEvent.click(screen.getByText('Markdown'));
    expect(screen.getByRole('textbox', { name: 'Body' })).toHaveValue(PLAIN);
  });
});
