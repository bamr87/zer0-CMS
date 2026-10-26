// One editor for a text block, on TipTap with Mantine's toolbar: Markdown for
// `markdown` blocks (TipTap's Markdown extension parses and writes it back)
// and Wagtail's rich text HTML for `paragraph` blocks. A block the editor
// cannot reproduce exactly — Liquid, raw HTML, a construct it would rewrite —
// opens as its source instead, because a markdown block is kept verbatim
// (content/cms/blocks.py) and an editor must never rewrite what a person did
// not touch. The editor only reports a change when the person makes one.
import { Badge, Group, SegmentedControl, Stack, Textarea } from '@mantine/core';
import { RichTextEditor } from '@mantine/tiptap';
import { Editor, type Extensions } from '@tiptap/core';
import { Markdown } from '@tiptap/markdown';
import { useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { useState } from 'react';

export type TextFormat = 'markdown' | 'html';

const extensions: Extensions = [StarterKit, Markdown];

const trimEnd = (text: string) => text.replace(/\s+$/, '');
const write = (editor: Editor, format: TextFormat) => (format === 'markdown' ? editor.getMarkdown() : editor.getHTML());

/** What the rich editor writes for `text` when nobody changes anything. */
export function throughEditor(text: string, format: TextFormat): string {
  const editor = new Editor({ element: null, extensions, content: text, contentType: format, injectCSS: false });
  const out = write(editor, format);
  editor.destroy();
  return out;
}

/** Whether the rich editor gives `text` back unchanged (trailing space aside). */
export function roundTrips(text: string, format: TextFormat): boolean {
  return trimEnd(throughEditor(text, format)) === trimEnd(text);
}

interface Props {
  value: string;
  format: TextFormat;
  onChange: (value: string) => void;
  disabled?: boolean;
  label?: string;
}

export function RichText({ value, format, onChange, disabled, label }: Props) {
  const [safe] = useState(() => roundTrips(value, format));
  const [mode, setMode] = useState<'rich' | 'source'>(safe ? 'rich' : 'source');
  return (
    <Stack gap={4}>
      <Group justify="space-between">
        {safe ? (
          <SegmentedControl
            size="xs"
            value={mode}
            onChange={(next) => setMode(next === 'source' ? 'source' : 'rich')}
            data={[
              { value: 'rich', label: 'Rich' },
              { value: 'source', label: format === 'markdown' ? 'Markdown' : 'HTML' },
            ]}
          />
        ) : (
          <Badge variant="light" color="gray" title="The rich editor would rewrite parts of this block">
            Edited as source
          </Badge>
        )}
      </Group>
      {mode === 'rich' ? (
        <RichEditor value={value} format={format} onChange={onChange} disabled={disabled} label={label} />
      ) : (
        <Textarea
          aria-label={label ?? 'Source'}
          autosize
          minRows={3}
          ff="monospace"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.value)}
        />
      )}
    </Stack>
  );
}

function RichEditor({ value, format, onChange, disabled, label }: Props) {
  const editor = useEditor({
    extensions,
    content: value,
    contentType: format,
    injectCSS: false,
    editable: !disabled,
    editorProps: { attributes: { 'aria-label': label ?? 'Text', role: 'textbox', 'aria-multiline': 'true' } },
    onUpdate: ({ editor: current }) => onChange(write(current, format)),
  });
  return (
    <RichTextEditor editor={editor}>
      <RichTextEditor.Toolbar>
        <RichTextEditor.ControlsGroup>
          <RichTextEditor.Bold />
          <RichTextEditor.Italic />
          <RichTextEditor.Code />
          <RichTextEditor.Link />
          <RichTextEditor.Unlink />
        </RichTextEditor.ControlsGroup>
        <RichTextEditor.ControlsGroup>
          <RichTextEditor.H2 />
          <RichTextEditor.H3 />
          <RichTextEditor.BulletList />
          <RichTextEditor.OrderedList />
          <RichTextEditor.Blockquote />
        </RichTextEditor.ControlsGroup>
      </RichTextEditor.Toolbar>
      <RichTextEditor.Content />
    </RichTextEditor>
  );
}
