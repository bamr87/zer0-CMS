// Output schemas: the schema is checked as it is typed (JSON, an object,
// refers only to itself) and by the platform on save, whose verdict shows
// under the field; a saved change is a new version; staff add the bundled
// schemas; a document imports as a new schema.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { SchemaEditor, SchemaList, schemaProblem } from '../../src';
import { fakePlatform, renderUi, Reply } from '../../../../test/harness';
import { me, page, schema } from './fixtures';

describe('schemaProblem', () => {
  it('says what is wrong before the platform is asked', () => {
    expect(schemaProblem('{"type": "object"')).toMatch(/^Not JSON yet/);
    expect(schemaProblem('[1, 2]')).toBe('A JSON Schema is an object: { … }');
    expect(schemaProblem('{"$ref": "https://example.com/s.json"}')).toMatch(/refers only to itself/);
    expect(schemaProblem('{"$defs": {"a": {"type": "string"}}, "$ref": "#/$defs/a"}')).toBeNull();
  });
});

describe('<SchemaEditor>', () => {
  it('gives feedback as the schema is typed, and shows the platform’s verdict on save', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/sites/': () => [],
      'GET /api/v2/ai/output-schemas/s1/': () => schema(),
      'PATCH /api/v2/ai/output-schemas/s1/': () =>
        new Reply(422, {
          error: {
            code: 'request.invalid',
            message: 'the request is not valid',
            status: 422,
            details: [{ field: 'schema', code: 'invalid', message: "not a valid JSON Schema: 'strin' is not valid under any of the given schemas" }],
          },
        }),
    });
    renderUi(<SchemaEditor id="s1" />, { api });
    const field = await screen.findByRole('textbox', { name: /JSON Schema/ });
    expect(screen.getByRole('status')).toHaveTextContent('Valid JSON');
    await userEvent.clear(field);
    await userEvent.paste('{"type": ');
    expect(screen.getByText(/^Not JSON yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await userEvent.paste('"strin"}');
    expect(await screen.findByRole('status')).toHaveTextContent('Valid JSON');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(field).toHaveAccessibleDescription(/not a valid JSON Schema: 'strin'/));
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ name: 'Story', schema: { type: 'strin' } });
  });

  it('exports a schema with its render template', async () => {
    const document = { name: 'Story', description: '', version: 1, schema: { type: 'object' }, render_template: '## {{ headline }}' };
    const { api } = fakePlatform({
      'GET /api/v2/sites/': () => [],
      'GET /api/v2/ai/output-schemas/s1/': () => schema(),
      'GET /api/v2/ai/output-schemas/s1/export/': () => document,
    });
    renderUi(<SchemaEditor id="s1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Export' }));
    const dialog = await screen.findByRole('dialog', { name: 'Export Story' });
    expect(within(dialog).getByLabelText('The exported document')).toHaveTextContent('"render_template": "## {{ headline }}"');
    expect(within(dialog).getByRole('link', { name: 'Download story.json' })).toHaveAttribute('download', 'story.json');
  });

  it('creates a schema and opens it', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/sites/': () => [],
      'POST /api/v2/ai/output-schemas/': ({ body }) => schema({ ...(body as object), id: 's2' }),
    });
    const { go } = renderUi(<SchemaEditor />, { api });
    await userEvent.type(await screen.findByLabelText(/^Name/), 'Headline');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'schema', id: 's2' }));
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ name: 'Headline', schema: { type: 'object', required: ['headline', 'body'] } });
  });
});

describe('<SchemaList>', () => {
  it('lets staff add the bundled schemas and anyone import a document', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me([], true),
      'GET /api/v2/ai/output-schemas/': () => page([schema({ bundled: true, version: 2, visibility: 'shared' })]),
      'POST /api/v2/ai/output-schemas/import-bundled/': () => ({ schemas: ['s1'], assistants: ['a1'] }),
      'POST /api/v2/ai/output-schemas/': () => schema({ id: 's3', name: 'Imported' }),
    });
    const { go } = renderUi(<SchemaList />, { api });
    const table = await screen.findByRole('table', { name: 'Output schemas' });
    expect(within(table).getByText('v2')).toBeInTheDocument();
    expect(within(table).getByText('bundled')).toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'Add the bundled schemas' }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/import-bundled/'))).toBe(true));
    await userEvent.click(screen.getByRole('button', { name: 'Import a schema' }));
    const dialog = await screen.findByRole('dialog', { name: 'Import a schema' });
    await userEvent.click(within(dialog).getByLabelText(/The document/));
    await userEvent.paste('{"name": "Imported", "schema": {"type": "object"}}');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'schema', id: 's3' }));
    expect(calls.findLast((c) => c.method === 'POST')?.body).toEqual({ name: 'Imported', schema: { type: 'object' } });
  });

  it('refuses a document that is not one, and says why', async () => {
    const { api, calls } = fakePlatform({ 'GET /api/v2/me': () => me(), 'GET /api/v2/ai/output-schemas/': () => page([]) });
    renderUi(<SchemaList />, { api });
    expect(screen.queryByRole('button', { name: 'Add the bundled schemas' })).toBeNull();
    await userEvent.click(await screen.findByRole('button', { name: 'Import a schema' }));
    const dialog = await screen.findByRole('dialog', { name: 'Import a schema' });
    await userEvent.click(within(dialog).getByLabelText(/The document/));
    await userEvent.paste('[1, 2, 3]');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Import' }));
    expect(await within(dialog).findByText(/an object with a name/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });
});
