// Before and after, as one text with the removed parts struck and the added
// parts marked (jsdiff): by word for a line of text, by line for a block.
// Rendered as <del>/<ins>, so a screen reader announces the change too.
import { Text } from '@mantine/core';
import { diffLines, diffWords } from 'diff';

export function DiffView({ before, after }: { before: string; after: string }) {
  const parts = before.includes('\n') || after.includes('\n') ? diffLines(before, after) : diffWords(before, after);
  if (!parts.some((part) => part.added || part.removed)) {
    return (
      <Text size="sm" c="dimmed">
        No change
      </Text>
    );
  }
  return (
    <pre className="zer0-diff">
      {parts.map((part, i) =>
        part.added ? <ins key={i}>{part.value}</ins> : part.removed ? <del key={i}>{part.value}</del> : <span key={i}>{part.value}</span>,
      )}
    </pre>
  );
}
