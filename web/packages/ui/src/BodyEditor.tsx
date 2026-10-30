// A page body, block by block: text blocks in the rich editor, structured
// blocks (heading, code, quote, image, brief, letter, callout, document …) as
// their own fields, the two table blocks as a grid (TableFields.tsx), and the
// blocks a site's build reads verbatim (raw HTML, Liquid, an embed's URL) as
// source text. A document's file in the library shows as its id: choosing one
// waits for the studio's media library.
// Blocks keep their ids, so a pending suggestion and a block's provenance
// still find it after a save; a new block has none until the platform gives
// it one. The platform validates every block a person changed
// (cms.services.clean_body), so this stays a thin view of the data.
//
// Each block is keyed by its id, or — new in this session — by a client key
// that follows the block through edits, moves and removals. Never by its
// position: the rich editor reads its content once, so a positional key would
// hand one block's editor to another block's data after a remove or a move.
// A saved block carries its id in the page (`data-block-id`) and each field of
// a structured block its name (`data-field`), so the editor's AI panel knows
// which block — and which field — a selection is in.
import { ActionIcon, Badge, Button, Group, NumberInput, Paper, Select, Stack, Textarea, TextInput } from '@mantine/core';
import type { Block } from '@zer0/api';

import { RichText } from './RichText';
import { TableFields } from './TableFields';

type Value = Record<string, unknown>;

const NEW_BLOCKS: Record<string, Block['value']> = {
  markdown: '',
  heading: { level: '2', text: '' },
  code: { language: '', code: '' },
  quote: { text: '', attribution: '' },
  callout: { kind: 'note', fold: '', title: '', body: '' },
  table: { data: [['', ''], ['', '']], first_row_is_table_header: true, first_col_is_header: false, table_caption: '', table_header_choice: 'row' },
  typed_table: { columns: [{ type: 'text', heading: '' }, { type: 'number', heading: '' }], rows: [{ values: ['', ''] }], caption: '' },
  embed: '',
  document: { title: '', href: '', document: null },
  raw_html: '',
  liquid: '',
};
const LONG = new Set(['code', 'notes', 'text', 'tagline', 'subject', 'body']);
// Blocks the site's build reads as they are: shown and edited as their source.
const SOURCE = new Set(['raw_html', 'liquid']);
const FOLDS = [
  { value: 'none', label: 'Not foldable' },
  { value: '+', label: 'Foldable, open' },
  { value: '-', label: 'Foldable, closed' },
];
const isRecord = (value: unknown): value is Value => typeof value === 'object' && value !== null && !Array.isArray(value);

const clientKeys = new WeakMap<Block, string>();
let made = 0;
function keyOf(block: Block): string {
  if (block.id) return block.id;
  const key = clientKeys.get(block) ?? `new-${(made += 1)}`;
  clientKeys.set(block, key);
  return key;
}

interface Props {
  blocks: Block[];
  onChange: (blocks: Block[]) => void;
  disabled?: boolean;
}

export function BodyEditor({ blocks, onChange, disabled }: Props) {
  const set = (at: number, block: Block, value: unknown) => {
    const next = { ...block, value };
    clientKeys.set(next, keyOf(block));
    onChange(blocks.map((b, i) => (i === at ? next : b)));
  };
  const move = (at: number, by: number) => {
    const next = [...blocks];
    next.splice(at + by, 0, ...next.splice(at, 1));
    onChange(next);
  };
  return (
    <Stack>
      {blocks.map((block, i) => (
        <Paper key={keyOf(block)} p="sm" aria-label={`Block ${i + 1}: ${block.type}`} component="section" data-block-id={block.id}>
          <Group justify="space-between" mb="xs">
            <Badge variant="outline">{block.type}</Badge>
            <Group gap={4}>
              <ActionIcon variant="subtle" aria-label="Move up" disabled={disabled || i === 0} onClick={() => move(i, -1)}>
                ↑
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                aria-label="Move down"
                disabled={disabled || i === blocks.length - 1}
                onClick={() => move(i, 1)}
              >
                ↓
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label="Remove block"
                disabled={disabled}
                onClick={() => onChange(blocks.filter((_, j) => j !== i))}
              >
                ×
              </ActionIcon>
            </Group>
          </Group>
          <BlockFields block={block} disabled={disabled} onChange={(value) => set(i, block, value)} />
        </Paper>
      ))}
      <Group gap="xs">
        {Object.keys(NEW_BLOCKS).map((type) => (
          <Button
            key={type}
            size="xs"
            variant="default"
            disabled={disabled}
            onClick={() => onChange([...blocks, { type, value: NEW_BLOCKS[type] }])}
          >
            + {type}
          </Button>
        ))}
      </Group>
    </Stack>
  );
}

function BlockFields({ block, onChange, disabled }: { block: Block; onChange: (value: unknown) => void; disabled?: boolean }) {
  if (block.type === 'markdown' || block.type === 'paragraph') {
    return (
      <RichText
        value={typeof block.value === 'string' ? block.value : ''}
        format={block.type === 'markdown' ? 'markdown' : 'html'}
        label={block.type === 'markdown' ? 'Markdown block' : 'Paragraph block'}
        onChange={onChange}
        disabled={disabled}
      />
    );
  }
  const value = block.value;
  if ((block.type === 'table' || block.type === 'typed_table') && isRecord(value)) {
    return <TableFields type={block.type} value={value} onChange={onChange} disabled={disabled} />;
  }
  if (!isRecord(value)) {
    return (
      <Textarea
        aria-label={block.type}
        autosize
        ff={SOURCE.has(block.type) ? 'monospace' : undefined}
        value={String(value ?? '')}
        disabled={disabled}
        onChange={(e) => onChange(e.currentTarget.value)}
      />
    );
  }
  const put = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  return (
    <Stack gap="xs">
      {Object.entries(value).map(([key, field]) => {
        if (key === 'level') {
          return (
            <Select
              key={key}
              label="Level"
              data={['2', '3', '4', '5', '6']}
              value={String(field)}
              disabled={disabled}
              allowDeselect={false}
              data-field={key}
              onChange={(next) => put(key, next)}
            />
          );
        }
        if (key === 'fold') {
          return (
            <Select
              key={key}
              label="Fold"
              data={FOLDS}
              value={typeof field === 'string' && field ? field : 'none'}
              disabled={disabled}
              allowDeselect={false}
              data-field={key}
              onChange={(next) => put(key, next && next !== 'none' ? next : '')}
            />
          );
        }
        if (typeof field === 'number' || field === null) {
          return <NumberInput key={key} label={key} value={field ?? ''} disabled={disabled} data-field={key} onChange={(next) => put(key, next === '' ? null : Number(next))} />;
        }
        const text = String(field ?? '');
        return LONG.has(key) ? (
          <Textarea key={key} label={key} autosize ff={key === 'code' ? 'monospace' : undefined} value={text} disabled={disabled} data-field={key} onChange={(e) => put(key, e.currentTarget.value)} />
        ) : (
          <TextInput key={key} label={key} value={text} disabled={disabled} data-field={key} onChange={(e) => put(key, e.currentTarget.value)} />
        );
      })}
    </Stack>
  );
}
