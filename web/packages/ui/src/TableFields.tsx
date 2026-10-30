// A table block's cells, edited in place: Wagtail's `table` (rows of text, the
// first its header) and `typed_table` (columns, each a heading and a type —
// text or number — and rows of values). Rows and columns are added and removed
// here; the platform checks every cell with the block's own rules (a number
// column takes numbers only) and the exporter writes the block as a Markdown
// pipe table. The inputs are controlled, so a row keeps its place by position.
import { ActionIcon, Button, Group, Select, Stack, Table, TextInput } from '@mantine/core';

type Value = Record<string, unknown>;

interface Grid {
  header: string[];
  rows: string[][];
  types?: string[];
}

const cells = (row: unknown): string[] => (Array.isArray(row) ? row.map((cell) => (cell == null ? '' : String(cell))) : []);
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

/** `table`: `data` is the rows, the first the header. */
function fromTable(value: Value): Grid {
  const data = list(value.data).map(cells);
  return { header: data[0] ?? [], rows: data.slice(1) };
}

/** `typed_table`: `columns` are {type, heading}, `rows` are {values}. */
function fromTyped(value: Value): Grid {
  const columns = list(value.columns) as { type?: string; heading?: string }[];
  return {
    header: columns.map((column) => column.heading ?? ''),
    types: columns.map((column) => column.type ?? 'text'),
    rows: (list(value.rows) as { values?: unknown }[]).map((row) => cells(row.values)),
  };
}

interface Props {
  type: 'table' | 'typed_table';
  value: Value;
  onChange: (value: Value) => void;
  disabled?: boolean;
}

export function TableFields({ type, value, onChange, disabled }: Props) {
  const typed = type === 'typed_table';
  const grid = typed ? fromTyped(value) : fromTable(value);
  const put = ({ header, rows, types }: Grid) =>
    onChange(
      typed
        ? { ...value, columns: header.map((heading, c) => ({ type: types?.[c] ?? 'text', heading })), rows: rows.map((values) => ({ values })) }
        : { ...value, data: [header, ...rows] },
    );
  const at = <T,>(items: T[], index: number, item: T) => items.map((old, i) => (i === index ? item : old));
  const without = <T,>(items: T[], index: number) => items.filter((_, i) => i !== index);
  const width = grid.header.length;
  return (
    <Stack gap="xs">
      <Table withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr>
            {grid.header.map((heading, c) => (
              <Table.Th key={c}>
                <Stack gap={4}>
                  <Group gap={4} wrap="nowrap">
                    <TextInput
                      aria-label={`Heading ${c + 1}`}
                      value={heading}
                      disabled={disabled}
                      onChange={(e) => put({ ...grid, header: at(grid.header, c, e.currentTarget.value) })}
                    />
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={`Remove column ${c + 1}`}
                      disabled={disabled || width === 1}
                      onClick={() =>
                        put({ header: without(grid.header, c), rows: grid.rows.map((row) => without(row, c)), types: grid.types && without(grid.types, c) })
                      }
                    >
                      ×
                    </ActionIcon>
                  </Group>
                  {typed ? (
                    <Select
                      aria-label={`Column ${c + 1} type`}
                      data={['text', 'number']}
                      value={grid.types?.[c] ?? 'text'}
                      allowDeselect={false}
                      disabled={disabled}
                      onChange={(next) => put({ ...grid, types: at(grid.types ?? [], c, next ?? 'text') })}
                    />
                  ) : null}
                </Stack>
              </Table.Th>
            ))}
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {grid.rows.map((row, r) => (
            <Table.Tr key={r}>
              {grid.header.map((_, c) => (
                <Table.Td key={c}>
                  <TextInput
                    aria-label={`Row ${r + 1}, column ${c + 1}`}
                    value={row[c] ?? ''}
                    disabled={disabled}
                    onChange={(e) => put({ ...grid, rows: at(grid.rows, r, at(row, c, e.currentTarget.value)) })}
                  />
                </Table.Td>
              ))}
              <Table.Td>
                <ActionIcon variant="subtle" color="red" aria-label={`Remove row ${r + 1}`} disabled={disabled} onClick={() => put({ ...grid, rows: without(grid.rows, r) })}>
                  ×
                </ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group gap="xs">
        <Button size="xs" variant="default" disabled={disabled} onClick={() => put({ ...grid, rows: [...grid.rows, grid.header.map(() => '')] })}>
          + row
        </Button>
        <Button
          size="xs"
          variant="default"
          disabled={disabled}
          onClick={() => put({ header: [...grid.header, ''], rows: grid.rows.map((row) => [...row, '']), types: grid.types && [...grid.types, 'text'] })}
        >
          + column
        </Button>
      </Group>
    </Stack>
  );
}
