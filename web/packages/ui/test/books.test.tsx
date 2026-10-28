// The Books workspace: the library's shelf with each book's status and
// progress; a new book from the template; a book from a premise — outlined by a
// run, read by the person, and made only when they say so; a book's facts saved
// as a draft revision; its other files edited one at a time; its chapters,
// findings and manuscript; the outliner's proposal as a diff the person may
// take; the chapter writer — the page editor, the book assistant's chapter tasks
// and that chapter's own findings — and the assistant, whose writing comes back
// as suggestions to review and whose continuity check comes back as findings.
// The platform is a fake behind the real client.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { BookAssist, BookShelf, BookView, ChapterWriter, PremiseToBook } from '../src';
import { fakePlatform, pageDetail, renderUi } from '../../../test/harness';

const summary = (overrides: Record<string, unknown> = {}) => ({
  id: 20,
  slug: 'impairment',
  title: 'The Impairment',
  status: 'drafting',
  page_status: 'live',
  profile: 'book',
  logline: 'A laid-off engineer finds the cover-up.',
  genre: 'Financial thriller',
  chapters: 14,
  planned_chapters: 14,
  word_count: 10096,
  target_word_count: 90000,
  progress: 0.1122,
  site_id: 1,
  template: false,
  ...overrides,
});

const chapterRow = (number: number, overrides: Record<string, unknown> = {}) => ({
  id: 30 + number,
  number,
  title: `Chapter ${number}`,
  subtitle: '',
  act: 1,
  status: 'draft',
  pov: 'Third person limited',
  word_count: 700,
  path: `impairment/chapters/ch0${number}.md`,
  errors: 0,
  warnings: 0,
  ...overrides,
});

const detail = (overrides: Record<string, unknown> = {}) => ({
  ...summary(),
  stats: {
    chapters: 2,
    status_counts: { draft: 2 },
    word_count: 1400,
    target_word_count: 90000,
    planned_chapters: 14,
    average: 700,
    longest: { number: 1, title: 'Chapter 1', word_count: 700 },
    shortest: { number: 2, title: 'Chapter 2', word_count: 700 },
    progress: 0.0156,
  },
  chapter_list: [chapterRow(1), chapterRow(2, { errors: 1 })],
  errors: 1,
  warnings: 0,
  documents: ['README.md', 'book.yml'],
  can_edit: true,
  can_add_chapter: true,
  ...overrides,
});

const TASKS = [
  { key: 'draft', label: 'Draft', description: 'Write the chapter body.', chapter: true, suggests: true },
  { key: 'continue', label: 'Continue', description: 'Carry on.', chapter: true, suggests: true },
  { key: 'revise', label: 'Revise', description: 'Rewrite a passage.', chapter: true, suggests: true },
  { key: 'check', label: 'Continuity check', description: 'Report what breaks.', chapter: true, suggests: false },
  { key: 'critique', label: 'Critique', description: 'An editor’s read.', chapter: true, suggests: false },
  { key: 'outline', label: 'Outline', description: 'Write the outline.', chapter: false, suggests: false },
];

const run = (status: string, output: unknown = {}) => ({
  id: 'r77',
  agent: 'books',
  status,
  is_final: status === 'succeeded' || status === 'failed',
  trigger: 'rest',
  target: { type: 'chapterpage', id: 31 },
  input: {},
  output,
  error: status === 'failed' ? 'the passage to revise is not in the chapter' : '',
  cost_usd: '0.02',
  tokens: 900,
  trace_id: '',
  schema_version: '1',
  created_at: '2026-10-22T09:00:00Z',
  finished_at: null,
  links: { self: '/api/v2/agent-runs/r77/', stream: '/api/v2/agent-runs/r77/stream/' },
});

const BOOK_FIELDS = {
  title: 'The Impairment',
  book_status: 'drafting',
  logline: 'A laid-off engineer finds the cover-up.',
  cast: ['Kareem Hassan'],
  outline: '# The Impairment\n\nOld plan.\n',
};
const bookPage = () =>
  pageDetail({
    id: 20,
    type: 'cms.BookPage',
    fields: BOOK_FIELDS,
    field_specs: [
      { name: 'book_status', label: 'Status', group: 'content', kind: 'choice', required: true, help_text: '', max_length: 16, choices: [{ value: 'drafting', label: 'Drafting' }, { value: 'revising', label: 'Revising' }] },
      { name: 'logline', label: 'Logline', group: 'content', kind: 'textarea', required: false, help_text: '', max_length: null, choices: [] },
      { name: 'cast', label: 'Cast', group: 'content', kind: 'tags', required: false, help_text: '', max_length: null, choices: [] },
      { name: 'outline', label: 'Outline', group: 'content', kind: 'textarea', required: false, help_text: '', max_length: null, choices: [] },
    ],
  });

describe('<BookShelf>', () => {
  it('shows each book with its status and progress, and opens one', async () => {
    const { api, calls } = fakePlatform({ 'GET /api/v2/books/': () => [summary()] });
    const { go } = renderUi(<BookShelf />, { api });
    expect(await screen.findByText('A laid-off engineer finds the cover-up.')).toBeInTheDocument();
    expect(screen.getByText('drafting')).toBeInTheDocument();
    expect(screen.getByText(/14 of 14 chapters · 10,096 of 90,000 words · 11%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'The Impairment' }));
    expect(go).toHaveBeenCalledWith({ to: 'book', id: 20 });
    expect([...(calls[0]?.query.keys() ?? [])]).toEqual([]); // the library's books, whichever site is picked
  });

  it('starts a book from the template', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/books/': () => [],
      'POST /api/v2/books/': () => detail({ id: 41, title: 'The Quiet Part' }),
    });
    const { go } = renderUi(<BookShelf />, { api });
    expect(await screen.findByText('No books yet.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'New book' }));
    await userEvent.type(screen.getByLabelText(/^Title/), 'The Quiet Part');
    await userEvent.type(screen.getByLabelText(/^Logline/), 'A speechwriter tells the truth.');
    await userEvent.click(screen.getByRole('button', { name: 'Create book' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'book', id: 41 }));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ title: 'The Quiet Part', logline: 'A speechwriter tells the truth.', genre: '' });
  });
});

describe('<PremiseToBook>', () => {
  it('outlines a premise, shows the plan, and makes the book only when asked', async () => {
    let polls = 0;
    const outline = {
      title: 'The Quiet Part',
      logline: 'A speechwriter starts telling the truth.',
      genre: 'Satire',
      synopsis: 'Nell writes what the minister means.',
      themes: [{ name: 'Candour', argument: 'The truth costs the teller first.' }],
      chapters: [
        { number: 1, act: 1, title: 'Opening Remarks', beat: 'The slip.' },
        { number: 2, act: 2, title: 'The Leak', beat: 'The line trends.' },
      ],
    };
    const { api, calls } = fakePlatform({
      'POST /api/v2/books/premise/': () => ({ brief: { id: 'b-1', status: 'generating' }, run: run('queued') }),
      'GET /api/v2/ai/briefs/b-1/': () => (++polls < 2 ? { id: 'b-1', status: 'generating', result: null } : { id: 'b-1', status: 'ready', result: outline }),
      'POST /api/v2/books/premise/b-1/create/': () => detail({ id: 42 }),
    });
    const { go } = renderUi(<PremiseToBook />, { api });
    await userEvent.type(screen.getByLabelText(/^Premise/), 'A speechwriter starts telling the truth.');
    await userEvent.click(screen.getByRole('button', { name: 'Outline it' }));
    expect(await screen.findByText('The outliner is writing…')).toBeInTheDocument();
    const plan = await screen.findByRole('table', { name: 'Chapter plan' }, { timeout: 3000 });
    expect(within(plan).getByText('Opening Remarks')).toBeInTheDocument();
    expect(screen.getByText('Candour')).toBeInTheDocument();
    expect(calls.filter((c) => c.path.endsWith('/create/'))).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: 'Create this book' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'book', id: 42 }));
    expect(calls.find((c) => c.path === '/api/v2/books/premise/')?.body).toEqual({ premise: 'A speechwriter starts telling the truth.' });
  });
});

describe('<BookView>', () => {
  function platform(extra: Record<string, () => unknown> = {}) {
    return fakePlatform({
      'GET /api/v2/books/20/': () => detail(),
      'GET /api/v2/content/pages/20/': () => bookPage(),
      'PATCH /api/v2/content/pages/20/': () => bookPage(),
      'GET /api/v2/books/tasks/': () => TASKS,
      'GET /api/v2/books/20/issues/': () => [
        { level: 'error', code: 'placeholder', message: 'unresolved placeholder [Company Name] left in the file', path: 'impairment/chapters/ch02.md', line: 38 },
      ],
      'GET /api/v2/books/20/manuscript/': () => ({ filename: 'impairment-manuscript.md', markdown: '# The Impairment\n\n---\n', word_count: 1400 }),
      'POST /api/v2/books/20/chapters/': () => detail({ chapter_list: [chapterRow(1), chapterRow(2), chapterRow(3, { title: 'Later' })] }),
      ...extra,
    });
  }

  it('saves the book’s facts as a draft revision of its page', async () => {
    const { api, calls } = platform();
    renderUi(<BookView bookId={20} />, { api });
    expect(await screen.findByRole('heading', { name: 'The Impairment' })).toBeInTheDocument();
    expect(screen.getByText(/1,400 of 90,000 words of prose/)).toBeInTheDocument();
    const logline = await screen.findByLabelText(/^Logline/);
    await userEvent.clear(logline);
    await userEvent.type(logline, 'A sharper logline.');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ base_revision_id: 41, fields: { logline: 'A sharper logline.' } });
  });

  it('lists the chapters in order, opens one, and adds the next', async () => {
    const { api, calls } = platform();
    const { go } = renderUi(<BookView bookId={20} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Chapters (2)' }));
    const table = screen.getByRole('table', { name: 'Chapters' });
    await userEvent.click(within(table).getByRole('button', { name: 'Chapter 2' }));
    expect(go).toHaveBeenCalledWith({ to: 'chapter', book: 20, id: 32 });
    await userEvent.type(screen.getByLabelText('Next chapter'), 'Later');
    await userEvent.click(screen.getByRole('button', { name: 'Add chapter' }));
    expect(await within(screen.getByRole('table', { name: 'Chapters' })).findByRole('button', { name: 'Later' })).toBeInTheDocument();
    expect(calls.find((c) => c.path === '/api/v2/books/20/chapters/')?.body).toEqual({ title: 'Later' });
  });

  it('shows the findings and builds the manuscript to download', async () => {
    const { api } = platform();
    renderUi(<BookView bookId={20} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Checks (1 / 0)' }));
    expect(await screen.findByText('impairment/chapters/ch02.md')).toBeInTheDocument();
    expect(screen.getByText(/unresolved placeholder \[Company Name\]/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Manuscript' }));
    await userEvent.click(screen.getByRole('button', { name: 'Build the manuscript' }));
    const link = await screen.findByRole('link', { name: 'Download impairment-manuscript.md' });
    expect(link).toHaveAttribute('download', 'impairment-manuscript.md');
    expect(link.getAttribute('href')).toBe(`data:text/markdown;charset=utf-8,${encodeURIComponent('# The Impairment\n\n---\n')}`);
  });

  it('edits an act guide as a draft revision of the book, against the revision it was read from', async () => {
    const guide = { path: 'guides/act-1-chapters-01-05.md', text: '# Act I\n\nOpen cold.\n' };
    const { api, calls } = platform({
      'GET /api/v2/books/20/documents/': () => ({ revision: 41, documents: [{ path: 'README.md', text: '# The Impairment\n' }, guide] }),
      'POST /api/v2/books/20/documents/': () => ({ revision: 42, documents: [{ path: 'README.md', text: '# The Impairment\n' }, { ...guide, text: '# Act I\n\nOpen warm.\n' }] }),
    });
    renderUi(<BookView bookId={20} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Files' }));
    await userEvent.click(await screen.findByText('guides/act-1-chapters-01-05.md'));
    const editor = screen.getByLabelText('guides/act-1-chapters-01-05.md');
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
    await userEvent.clear(editor);
    await userEvent.type(editor, '# Act I{enter}{enter}Open warm.{enter}');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v2/books/20/documents/' && c.method === 'POST')).toBe(true));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ base_revision_id: 41, path: 'guides/act-1-chapters-01-05.md', text: '# Act I\n\nOpen warm.\n' });
    expect(await screen.findByRole('button', { name: 'Save draft' })).toBeDisabled();
  });

  it('offers the outliner’s proposal as a diff, and saves it only when the person does', async () => {
    const proposal = '# The Impairment\n\nNew plan.\n';
    const { api, calls } = platform({
      'POST /api/v2/books/20/assist/': () => ({ run: { id: 'r77', status: 'queued', links: { self: '', stream: '' } } }),
      'GET /api/v2/agent-runs/r77/': () => run('succeeded', { task: 'outline', markdown: proposal, json: {} }),
    });
    renderUi(<BookView bookId={20} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Outline' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Outline' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Compare with the outline' }));
    expect(screen.getByText(/The outliner.s proposal/)).toBeInTheDocument();
    expect(calls.find((c) => c.path === '/api/v2/books/20/assist/')?.body).toEqual({ task: 'outline', instruction: '', selection: '' });
    await userEvent.click(screen.getByRole('button', { name: 'Use it (then save)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ base_revision_id: 41, fields: { outline: proposal } });
  });
});

describe('<BookAssist> beside a chapter', () => {
  it('drafts the chapter as suggestions to review', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/books/tasks/': () => TASKS,
      'POST /api/v2/books/20/assist/': () => ({ run: { id: 'r77', status: 'queued', links: { self: '', stream: '' } } }),
      'GET /api/v2/agent-runs/r77/': () => run('succeeded', { task: 'draft', markdown: 'Ana sat.', suggestions: ['s501'] }),
    });
    const { go } = renderUi(<BookAssist bookId={20} chapterId={31} />, { api });
    await userEvent.type(await screen.findByLabelText(/^Instruction/), 'Keep it short.');
    await userEvent.click(screen.getByRole('button', { name: 'Draft' }));
    expect(await screen.findByText('1 suggestion to review')).toBeInTheDocument();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ task: 'draft', chapter: 31, instruction: 'Keep it short.', selection: '' });
    await userEvent.click(screen.getByRole('button', { name: 'Review this run' }));
    expect(go).toHaveBeenCalledWith({ to: 'review', runId: 'r77' });
  });

  it('asks for the passage to revise, and shows a failed run’s reason', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/books/tasks/': () => TASKS,
      'POST /api/v2/books/20/assist/': () => ({ run: { id: 'r77', status: 'queued', links: { self: '', stream: '' } } }),
      'GET /api/v2/agent-runs/r77/': () => run('failed'),
    });
    renderUi(<BookAssist bookId={20} chapterId={31} />, { api });
    await userEvent.click(await screen.findByRole('radio', { name: 'Revise' }));
    const button = screen.getByRole('button', { name: 'Revise' });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^Passage to revise/), 'the empty chairs');
    await userEvent.click(button);
    expect(await screen.findByText('the passage to revise is not in the chapter')).toBeInTheDocument();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ task: 'revise', chapter: 31, instruction: '', selection: 'the empty chairs' });
  });

  it('shows a continuity check’s findings with the text at fault', async () => {
    const findings = {
      summary: 'One contradiction.',
      findings: [{ severity: 'high', kind: 'continuity', quote: 'Puffin Rock', problem: 'The ledger says Gannet Rock.', suggestion: 'Use Gannet Rock.' }],
    };
    const { api } = fakePlatform({
      'GET /api/v2/books/tasks/': () => TASKS,
      'POST /api/v2/books/20/assist/': () => ({ run: { id: 'r77', status: 'queued', links: { self: '', stream: '' } } }),
      'GET /api/v2/agent-runs/r77/': () => run('succeeded', { task: 'check', markdown: '', json: findings }),
      'GET /api/v2/books/20/context/': () => ({ text: '# Book brief: The Impairment' }),
    });
    renderUi(<BookAssist bookId={20} chapterId={31} />, { api });
    await userEvent.click(await screen.findByRole('radio', { name: 'Continuity check' }));
    await userEvent.click(screen.getByRole('button', { name: 'What it reads' }));
    expect(await screen.findByText('# Book brief: The Impairment')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Continuity check' }));
    expect(await screen.findByText('One contradiction.')).toBeInTheDocument();
    expect(screen.getByText('Puffin Rock')).toBeInTheDocument();
    expect(screen.getByText('The ledger says Gannet Rock.')).toBeInTheDocument();
    expect(screen.getByText('high')).toBeInTheDocument();
  });
});

describe('<ChapterWriter>', () => {
  it('puts the page editor, the chapter tasks and that chapter’s findings side by side, and drafts into suggestions', async () => {
    const chapterPage = pageDetail({
      id: 31,
      title: 'Chapter 1',
      type: 'cms.ChapterPage',
      type_label: 'Chapter page',
      fields: { title: 'Chapter 1', number: 1, chapter_status: 'draft', pov: 'First person' },
      field_specs: [
        { name: 'title', label: 'Title', group: 'content', kind: 'text', required: true, help_text: '', max_length: 255, choices: [] },
        { name: 'number', label: 'Number', group: 'content', kind: 'integer', required: false, help_text: '', max_length: null, choices: [] },
        { name: 'chapter_status', label: 'Status', group: 'content', kind: 'choice', required: true, help_text: '', max_length: 16, choices: [{ value: 'draft', label: 'Draft' }, { value: 'final', label: 'Final' }] },
        { name: 'pov', label: 'Point of view', group: 'content', kind: 'text', required: false, help_text: '', max_length: 255, choices: [] },
      ],
    });
    const { api, calls } = fakePlatform({
      'GET /api/v2/books/20/': () => detail({ chapter_list: [chapterRow(1, { path: 'impairment/chapters/ch01.md' }), chapterRow(2, { path: 'impairment/chapters/ch02.md' })] }),
      'GET /api/v2/content/pages/31/': () => chapterPage,
      'GET /api/v2/books/tasks/': () => TASKS,
      'GET /api/v2/books/20/issues/': () => [
        { level: 'warning', code: 'nav-missing', message: 'no link to the next chapter', path: 'impairment/chapters/ch01.md', line: null },
        { level: 'error', code: 'placeholder', message: 'unresolved placeholder [Company Name] left in the file', path: 'impairment/chapters/ch02.md', line: 38 },
      ],
      'POST /api/v2/books/20/assist/': () => ({ run: { id: 'r77', status: 'queued', links: { self: '', stream: '' } } }),
      'GET /api/v2/agent-runs/r77/': () => run('succeeded', { task: 'draft', markdown: 'Kareem sat.', suggestions: ['s501', 's502'] }),
    });
    renderUi(<ChapterWriter bookId={20} chapterId={31} />, { api });
    expect(await screen.findByLabelText(/^Point of view/)).toHaveValue('First person'); // the page editor's fields
    for (const task of ['Draft', 'Continue', 'Revise', 'Continuity check', 'Critique']) {
      expect(await screen.findByRole('radio', { name: task })).toBeInTheDocument();
    }
    expect(screen.queryByRole('radio', { name: 'Outline' })).toBeNull(); // the book's task, not a chapter's
    expect(await screen.findByText('no link to the next chapter')).toBeInTheDocument();
    expect(screen.queryByText(/unresolved placeholder/)).toBeNull(); // chapter 2's finding is not this chapter's
    await userEvent.click(screen.getByRole('button', { name: 'Draft' }));
    expect(await screen.findByText('2 suggestions to review')).toBeInTheDocument();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ task: 'draft', chapter: 31, instruction: '', selection: '' });
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false); // nothing is written by running
  });
});
