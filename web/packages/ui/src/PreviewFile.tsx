// The editor's Preview tab: the page's latest revision as the very file a
// write-back writes (GET /api/v2/content/pages/<id>/preview/, the exporter's
// own rule) — its path, its body as HTML, its text, and what a write-back
// changes against the file the platform last read or wrote there — shown in
// place, in the studio and in the extension's webview alike, with no Wagtail
// admin and no browser session. The HTML is the platform's, already held to
// what the Markdown renders; it is rendered here as nodes, never injected
// (@zer0/ui's lint), and kept to the same elements: a link only to an absolute
// http(s) address (a site's own path means nothing here), an image as its
// description (the site's design and assets come with its renderer). Unsaved
// edits are not in it: it is the saved draft.
import { Alert, Anchor, Code, Group, Loader, SegmentedControl, Stack, Text, Typography } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { createElement, Fragment, useState, type ReactNode } from 'react';

import { call, errorText } from './call';
import { useApi } from './context';
import { DiffView } from './DiffView';

type View = 'html' | 'file' | 'changes';

const ELEMENTS = new Set([
  ...['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'div'],
  ...['strong', 'b', 'em', 'i', 'sub', 'sup', 'br', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
]);
const EMPTY = new Set(['br', 'hr']);

function nodesOf(parent: Node, key: string): ReactNode[] {
  return Array.from(parent.childNodes, (node, at) => nodeOf(node, `${key}.${at}`));
}

function nodeOf(node: Node, key: string): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (!(node instanceof Element)) return null;
  const tag = node.tagName.toLowerCase();
  if (tag === 'img') {
    return (
      <Text key={key} component="span" c="dimmed">
        [image: {node.getAttribute('alt') || node.getAttribute('src') || 'no description'}]
      </Text>
    );
  }
  if (tag === 'script' || tag === 'style') return null;
  const children = nodesOf(node, key);
  if (tag === 'a') {
    const href = node.getAttribute('href') ?? '';
    return /^https?:\/\//i.test(href) ? (
      <Anchor key={key} href={href} target="_blank" rel="noreferrer">
        {children}
      </Anchor>
    ) : (
      <span key={key} title={href}>
        {children}
      </span>
    );
  }
  if (!ELEMENTS.has(tag)) return <Fragment key={key}>{children}</Fragment>;
  return createElement(tag, { key }, ...(EMPTY.has(tag) ? [] : children));
}

/** The platform's HTML as React nodes, kept to the elements its whitelist keeps. */
export function HtmlNodes({ html }: { html: string }) {
  return <>{nodesOf(new DOMParser().parseFromString(html, 'text/html').body, 'h')}</>;
}

export function PreviewFile({ pageId, dirty }: { pageId: number; dirty: boolean }) {
  const api = useApi();
  const [view, setView] = useState<View>('html');
  const preview = useQuery({
    queryKey: ['page-preview', pageId],
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/preview/', { params: { path: { id: pageId } } })),
  });
  if (preview.isPending) return <Loader aria-label="Loading the preview" />;
  if (preview.isError) return <Alert color="red">{errorText(preview.error)}</Alert>;
  const file = preview.data;
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm">
          The file a write-back writes: <Code>{file.path}</Code>
        </Text>
        <SegmentedControl
          value={view}
          onChange={(next) => setView(next as View)}
          data={[
            { value: 'html', label: 'As HTML' },
            { value: 'file', label: 'The file' },
            { value: 'changes', label: 'What a write-back changes' },
          ]}
        />
      </Group>
      {dirty ? <Alert color="yellow">Unsaved edits are not in the preview: save a draft to see them here.</Alert> : null}
      {view === 'html' ? (
        <Typography>
          <article aria-label="The page as HTML">
            <HtmlNodes html={file.html} />
          </article>
        </Typography>
      ) : null}
      {view === 'file' ? (
        <Code block aria-label="The file">
          {file.text}
        </Code>
      ) : null}
      {view === 'changes' ? (
        file.indexed === null ? (
          <Text size="sm">A write-back creates this file.</Text>
        ) : (
          <DiffView before={file.indexed} after={file.text} />
        )
      ) : null}
    </Stack>
  );
}
