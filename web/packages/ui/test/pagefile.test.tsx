// The editor's File tab: a page that is a file of its site shows that file's
// path and its raw front matter (JSON in Mantine's JsonInput) and saves only
// what changed, the front matter in the order it was written; text that is not
// JSON goes to the platform as it is and comes back refused by field; a page
// that is not a file of its own has no File tab.
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { PageEditor } from '../src';
import { fromJsonText } from '../src/FieldsPanel';
import { fakePlatform, pageDetail, renderUi, Reply } from '../../../test/harness';

const FILE_SPECS = [
  { name: 'file_path', label: 'File path', group: 'file', kind: 'text', required: false, help_text: 'Where the file goes.', max_length: 512, choices: [] },
  { name: 'front_matter', label: 'Front matter', group: 'file', kind: 'json', required: false, help_text: 'Every other key.', max_length: null, choices: [] },
];

function filePage(overrides: Record<string, unknown> = {}) {
  const page = pageDetail();
  return pageDetail({
    fields: {
      ...page.fields,
      file_path: 'pages/_posts/wire/2026-10-28-example.md',
      front_matter: { excerpt: 'The example, in one line.', sources: ['https://example.com/a'] },
    },
    field_specs: [...page.field_specs, ...FILE_SPECS],
    ...overrides,
  });
}

const patched = (calls: { method: string; body: unknown }[]) => calls.find((c) => c.method === 'PATCH')?.body as { fields: Record<string, unknown> } | undefined;

describe('<PageEditor> File tab', () => {
  it('shows the path and the raw front matter, and saves only what changed, in the order written', async () => {
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => filePage(),
      'PATCH /api/v2/content/pages/5/': () => filePage({ status: 'changed' }),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('tab', { name: 'File' }));
    const path = screen.getByLabelText('File path');
    const frontMatter = screen.getByLabelText('Front matter');
    expect(path).toHaveValue('pages/_posts/wire/2026-10-28-example.md');
    expect(JSON.parse((frontMatter as HTMLTextAreaElement).value)).toEqual({ excerpt: 'The example, in one line.', sources: ['https://example.com/a'] });

    await userEvent.clear(frontMatter);
    await userEvent.click(frontMatter);
    await userEvent.paste('{"permalink": "/wire/example/", "excerpt": "Shorter.", "sources": ["https://example.com/b"]}');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(patched(platform.calls)).toBeDefined());
    const sent = patched(platform.calls);
    expect(Object.keys(sent?.fields ?? {})).toEqual(['front_matter']); // the path did not change, so it is not sent
    expect(Object.keys(sent?.fields.front_matter as object)).toEqual(['permalink', 'excerpt', 'sources']);
  });

  it('sends text that is not JSON as it is, and shows the platform’s refusal by field', async () => {
    const refusal = {
      error: {
        code: 'validation.failed',
        message: 'validation failed',
        status: 422,
        details: [{ field: 'front_matter', code: 'invalid', message: 'raw front matter is a JSON object' }],
      },
    };
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => filePage(),
      'PATCH /api/v2/content/pages/5/': () => new Reply(422, refusal),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('tab', { name: 'File' }));
    const frontMatter = screen.getByLabelText('Front matter');
    await userEvent.clear(frontMatter);
    await userEvent.click(frontMatter);
    await userEvent.paste('excerpt: not JSON');
    await userEvent.tab();
    expect(await screen.findByText('Not valid JSON')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByText(/front_matter: raw front matter is a JSON object/)).toBeInTheDocument();
    expect(patched(platform.calls)?.fields).toEqual({ front_matter: 'excerpt: not JSON' });
  });

  it('has no File tab for a page that is not a file of its own', async () => {
    const platform = fakePlatform({ 'GET /api/v2/content/pages/5/': () => pageDetail() });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await screen.findByRole('tab', { name: 'SEO' });
    expect(screen.queryByRole('tab', { name: 'File' })).not.toBeInTheDocument();
  });
});

describe('fromJsonText', () => {
  it('reads JSON, keeps text that is not, and reads empty as no value', () => {
    expect(fromJsonText('{"b": 1, "a": 2}')).toEqual({ b: 1, a: 2 });
    expect(fromJsonText('{"b": 1')).toBe('{"b": 1');
    expect(fromJsonText('   ')).toBeNull();
  });
});
