// The editor's Preview tab: the page's latest revision as the very file a
// write-back writes, in place — its file name, its HTML rendered as nodes (a
// link only to an absolute address, an image as its description, nothing the
// platform's whitelist would not have kept), the file's text, and what a
// write-back changes against the file there now — with no admin link left to
// open. A page with no file of its own says so, and unsaved edits are named as
// not in it.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { PageEditor } from '../src';
import { fakePlatform, pageDetail, renderUi, Reply } from '../../../test/harness';

const PATH = 'pages/_posts/2026-10-20-nightly-backups.md';
const TEXT = '---\ntitle: Nightly backups\n---\n## How it works\n\nWe copy the site to a second disk every night.\n';
const PREVIEW = {
  path: PATH,
  text: TEXT,
  indexed: '---\ntitle: Backups\n---\n## How it works\n\nWe copy the site to a second disk every night.\n',
  html:
    '<h2>How it works</h2><p>We copy <a href="https://example.com/disks">the site</a> to <a href="/about/">a second disk</a>' +
    '<img src="/assets/disk.png" alt="A disk"><script>window.bad = true</script> every night.</p>' +
    '<table><tbody><tr><td>nightly</td></tr></tbody></table>',
};

function platform(preview: () => unknown = () => PREVIEW) {
  return fakePlatform({
    'GET /api/v2/content/pages/5/': () => pageDetail(),
    'GET /api/v2/content/pages/5/preview/': preview,
  });
}

describe('<PageEditor> Preview tab', () => {
  it('shows the file a write-back writes, its HTML in place, its text and what it changes', async () => {
    const { api, calls } = platform();
    renderUi(<PageEditor pageId={5} />, { api });
    expect(await screen.findByDisplayValue('Nightly backups')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Preview' })).not.toBeInTheDocument(); // no admin view to leave for
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(screen.getByRole('tab', { name: 'Preview', selected: true })).toBeInTheDocument();
    expect(await screen.findByText(PATH)).toBeInTheDocument();
    expect(calls.filter((c) => c.path === '/api/v2/content/pages/5/preview/').map((c) => c.method)).toEqual(['GET']);

    const html = screen.getByRole('article', { name: 'The page as HTML' });
    expect(within(html).getByRole('heading', { level: 2, name: 'How it works' })).toBeInTheDocument();
    expect(within(html).getByRole('link', { name: 'the site' })).toHaveAttribute('href', 'https://example.com/disks');
    expect(within(html).queryByRole('link', { name: 'a second disk' })).not.toBeInTheDocument(); // the site's own path
    expect(within(html).getByText('[image: A disk]')).toBeInTheDocument();
    expect(within(html).getByRole('cell', { name: 'nightly' })).toBeInTheDocument();
    expect(html.querySelector('script, img')).toBeNull();
    expect(within(html).queryByText(/window\.bad/)).toBeNull();

    await userEvent.click(screen.getByRole('radio', { name: 'The file' }));
    expect(screen.getByLabelText('The file', { selector: 'pre' })).toHaveTextContent('title: Nightly backups');
    await userEvent.click(screen.getByRole('radio', { name: 'What a write-back changes' }));
    expect(document.querySelector('del')?.textContent).toContain('title: Backups');
    expect(document.querySelector('ins')?.textContent).toContain('title: Nightly backups');
  });

  it('says a write-back creates the file when there is none yet, and that unsaved edits are not in it', async () => {
    const { api } = platform(() => ({ ...PREVIEW, indexed: null }));
    renderUi(<PageEditor pageId={5} />, { api });
    const title = await screen.findByDisplayValue('Nightly backups');
    await userEvent.type(title, ', explained');
    await userEvent.click(screen.getByRole('tab', { name: 'Preview' }));
    expect(await screen.findByText(/Unsaved edits are not in the preview/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'What a write-back changes' }));
    expect(screen.getByText('A write-back creates this file.')).toBeInTheDocument();
  });

  it('says so when the page has no file of its own', async () => {
    const { api } = platform(
      () => new Reply(404, { error: { code: 'resource.not_found', message: "page 5 has no file of its own: a site's root and its collections are index pages, not files", status: 404, details: [] } }),
    );
    renderUi(<PageEditor pageId={5} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Preview' }));
    await waitFor(() => expect(screen.getByText(/has no file of its own/)).toBeInTheDocument());
  });
});
