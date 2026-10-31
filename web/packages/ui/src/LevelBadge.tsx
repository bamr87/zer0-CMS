// A brand guard finding's level in one badge whose text can be read: every
// look here is at least 4.5:1 (WCAG 1.4.3) in either colour scheme, because
// the badge carries its own background. Measured in the studio's theme, the
// light and filled variants this replaced were not: a light yellow warning was
// 2.69:1 and a filled one 1.86:1, a filled red error 3.28:1. A warning is amber
// with dark text (`autoContrast`), an error a deep red, a note and a skipped
// rule a deep gray. It never shrinks beside a long message.
import { Badge } from '@mantine/core';
import type { ReactNode } from 'react';

export type Level = 'error' | 'warning' | 'info' | 'skipped';

const LOOK: Record<Level, { color: string; autoContrast?: boolean }> = {
  error: { color: 'red.9' },
  warning: { color: 'yellow.5', autoContrast: true },
  info: { color: 'gray.7' },
  skipped: { color: 'gray.7' },
};

export function LevelBadge({ level, children, size }: { level: Level; children?: ReactNode; size?: 'xs' | 'sm' | 'md' }) {
  const look = LOOK[level];
  return (
    <Badge size={size} color={look.color} autoContrast={look.autoContrast} variant="filled" style={{ flexShrink: 0 }}>
      {children ?? level}
    </Badge>
  );
}
