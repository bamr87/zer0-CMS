// The extension's webview app (PLAN G10): the providers every @zer0/ui
// workspace needs — TanStack Query, Mantine in the editor's colour scheme with
// the page's CSP nonce on the <style> elements it writes, and the host
// contract over postMessage — around the one view the extension host asked for:
//
//   dashboard  every workspace in WORKSPACES, as tabs, with the site picker —
//              the studio's areas, each with the destinations it shows;
//   page       the page behind the file open in the editor, found through the
//              path its import recorded, or a plain "not on the platform";
//   ai         the AI workspace (the agent view): runs, assistants, pipelines,
//              output schemas, conversations, providers and models.
//
// Nothing here is per workspace: a workspace @zer0/ui registers is a tab. A
// destination this view does not show is handed to the host, which opens the
// dashboard there.
import { Alert, Button, Group, Loader, MantineProvider, Stack, Tabs, Text } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { resolver, theme } from '@zer0/tokens';
import { ApiError, call, errorText, PageEditor, SitePicker, StudioProvider, useApi, WORKSPACES, workspaceFor, type Destination } from '@zer0/ui';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { connect, type Connection, type OpenFile, type Port } from './transport';

export type View = 'dashboard' | 'page' | 'ai';

/** VS Code's theme kind, from the class it keeps on <body>; high contrast follows its base. */
function editorScheme(): 'light' | 'dark' {
  const kind = document.body.classList;
  return kind.contains('vscode-light') || kind.contains('vscode-high-contrast-light') ? 'light' : 'dark';
}

function useEditorScheme() {
  const [scheme, setScheme] = useState(editorScheme);
  useEffect(() => {
    const observer = new MutationObserver(() => setScheme(editorScheme()));
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);
  return scheme;
}

export function App({ view, port, nonce }: { view: View; port: Port; nonce?: string }) {
  const connection = useMemo(() => connect(port), [port]);
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { refetchOnWindowFocus: false, retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2 },
        },
      }),
  );
  const scheme = useEditorScheme();
  useEffect(() => {
    // A link in a workspace (a draft's preview, a live page) points at the
    // platform: the host opens it in the browser, against the platform's origin.
    const open = (event: MouseEvent) => {
      const href = event.target instanceof Element ? event.target.closest('a[href]')?.getAttribute('href') : null;
      if (!href || href.startsWith('#')) return;
      event.preventDefault();
      connection.post({ type: 'open', href });
    };
    document.addEventListener('click', open);
    connection.post({ type: 'ready' });
    return () => document.removeEventListener('click', open);
  }, [connection]);
  return (
    <QueryClientProvider client={client}>
      <MantineProvider theme={theme} cssVariablesResolver={resolver} forceColorScheme={scheme} {...(nonce ? { getStyleNonce: () => nonce } : {})}>
        <Notifications position="bottom-right" />
        {view === 'page' ? <PageView connection={connection} /> : <Workbench connection={connection} ids={view === 'ai' ? ['ai'] : WORKSPACES.map((w) => w.id)} />}
      </MantineProvider>
    </QueryClientProvider>
  );
}

interface Place {
  id: string;
  at?: Destination;
}

function Workbench({ connection, ids }: { connection: Connection; ids: readonly string[] }) {
  const shown = WORKSPACES.filter((w) => ids.includes(w.id));
  const [place, setPlace] = useState<Place>({ id: shown[0]?.id ?? '' });
  const [siteId, setSiteId] = useState<number>();
  const here = useCallback(
    (to: Destination) => {
      const workspace = workspaceFor(to);
      return workspace && ids.includes(workspace.id) ? workspace : undefined;
    },
    [ids],
  );
  const go = useCallback(
    (to: Destination) => {
      const workspace = here(to);
      if (workspace) setPlace({ id: workspace.id, at: to });
      else connection.post({ type: 'go', to });
    },
    [here, connection],
  );
  // The host opens the dashboard at a destination another view asked for.
  useEffect(
    () =>
      connection.onGo((to) => {
        const workspace = here(to);
        if (workspace) setPlace({ id: workspace.id, at: to });
      }),
    [connection, here],
  );
  const current = shown.find((w) => w.id === place.id) ?? shown[0];
  if (!current) return null;
  return (
    <StudioProvider api={connection.api} stream={connection.stream} go={go}>
      <Stack p="sm" gap="sm">
        {shown.length > 1 ? (
          <Group justify="space-between" wrap="nowrap" align="flex-end">
            <Tabs value={current.id} onChange={(id) => id && setPlace({ id })}>
              <Tabs.List aria-label="Workspaces">
                {shown.map((w) => (
                  <Tabs.Tab key={w.id} value={w.id} title={w.summary}>
                    {w.label}
                  </Tabs.Tab>
                ))}
              </Tabs.List>
            </Tabs>
            <SitePicker value={siteId} onChange={setSiteId} />
          </Group>
        ) : null}
        <current.View siteId={siteId} at={place.at} />
      </Stack>
    </StudioProvider>
  );
}

function PageView({ connection }: { connection: Connection }) {
  const [file, setFile] = useState<OpenFile | null>(null);
  useEffect(() => connection.onFile(setFile), [connection]);
  const go = useCallback((to: Destination) => connection.post({ type: 'go', to }), [connection]);
  return (
    <StudioProvider api={connection.api} stream={connection.stream} go={go}>
      <Stack p="xs">
        {file ? (
          <PageForFile key={file.path} file={file} />
        ) : (
          <Text c="dimmed" size="sm">
            Open a file of a site on the platform to edit its page here.
          </Text>
        )}
      </Stack>
    </StudioProvider>
  );
}

function PageForFile({ file }: { file: OpenFile }) {
  const api = useApi();
  const [picked, setPicked] = useState<number>();
  const found = useQuery({
    queryKey: ['source', file.path],
    queryFn: () => call(api.GET('/api/v2/content/pages/', { params: { query: { source: file.path } } })),
  });
  if (found.isPending) return <Loader size="sm" />;
  if (found.isError) return <Alert color="red">{errorText(found.error)}</Alert>;
  const pages = found.data.results;
  const id = picked ?? (pages.length === 1 ? pages[0]?.id : undefined);
  if (id !== undefined) return <PageEditor key={id} pageId={id} />;
  if (pages.length === 0) {
    return (
      <Alert color="gray" title="Not on the platform">
        {file.name} is not a page on the platform: no page you can open was imported from {file.path}. Its front matter is still yours to edit as a
        file; to edit it here, import its site into the platform.
      </Alert>
    );
  }
  return (
    <Stack gap="xs">
      <Text size="sm">
        {file.name} was imported into {pages.length} pages. Which one?
      </Text>
      {pages.map((p) => (
        <Button key={p.id} variant="light" justify="flex-start" onClick={() => setPicked(p.id)}>
          {p.title} — {p.url_path}
        </Button>
      ))}
    </Stack>
  );
}
