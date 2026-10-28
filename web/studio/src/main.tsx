// The studio's entry: the styles (tokens before Mantine's, ours last), Mantine
// with the zer0 theme and the page's CSP nonce for the <style> elements it
// writes, TanStack Query, and the router under /studio.
import '@zer0/tokens/tokens.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@zer0/ui/ui.css';

import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { resolver, theme } from '@zer0/tokens';
import { ApiError } from '@zer0/ui';
import { setNonce } from 'get-nonce';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';

import { App } from './App';
import { browserAuth } from './auth';
import { api, openStream } from './transport';

// The platform replaces the placeholder in this meta's nonce on every request
// (content/api/studio.py); `.nonce` is the attribute browsers keep readable.
// Mantine's modals and drawers lock scrolling with a <style> that
// react-style-singleton writes, and it takes its nonce from get-nonce.
const nonce = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce || undefined;
if (nonce) setNonce(nonce);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <MantineProvider
          theme={theme}
          cssVariablesResolver={resolver}
          defaultColorScheme="auto"
          {...(nonce ? { getStyleNonce: () => nonce } : {})}
        >
          <Notifications position="bottom-right" />
          <BrowserRouter basename="/studio">
            <App api={api} stream={openStream} auth={browserAuth} />
          </BrowserRouter>
        </MantineProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}
