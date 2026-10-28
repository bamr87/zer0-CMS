// The Newsroom workspace: the budget board groups stories by status, a column
// a page of the list with its true count and more on request, and moves one
// through its menu (asking first for what a move needs and before anything goes
// live, showing the platform's refusal), and a drop maps to a move; the
// calendar lays a month out by slot date; assignments ask for mine or my desks';
// a story's panel saves what changed in its plan (the desk's decisions the
// desk's), asks the AI and applies what it proposes, and posts a correction
// that publishes nothing else; fronts are edited and saved as a whole; an issue
// is composed from stories found on the platform, previewed, sent and resumed;
// and pitching from a wire item asks the AI and opens the story, saying so if
// the AI could not be asked.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Newsroom, StoryPanel } from '../src';
import { dropTarget } from '../src/newsroom/Board';
import { Calendar, monthGrid } from '../src/newsroom/Calendar';
import { Fronts } from '../src/newsroom/Fronts';
import { Newsletters } from '../src/newsroom/Newsletters';
import { PitchForm } from '../src/newsroom/PitchForm';
import { fakePlatform, renderUi, Reply } from '../../../test/harness';

const STORIES = '/api/v2/newsroom/stories/';

function story(overrides: Record<string, unknown> = {}) {
  return {
    id: 's1',
    desk: 'd1',
    desk_name: 'Metro',
    slug: 'bridge-closes',
    headline: 'Bridge closes',
    summary: 'Six weeks of detours.',
    status: 'drafting',
    priority: 3,
    assignee: { id: 2, username: 'rae', name: 'Rae Porter' },
    deadline: null,
    slot_date: null,
    embargo: null,
    page: null,
    brief: null,
    wire_item: {},
    breaking: false,
    fast_path_reason: '',
    bylines: [],
    moves: ['editing'],
    created_at: '2026-10-20T09:00:00Z',
    updated_at: '2026-10-20T09:00:00Z',
    ...overrides,
  };
}

const detail = (overrides: Record<string, unknown> = {}) => ({ events: [], corrections: [], ai_runs: [], is_editor: true, ...story(overrides) });
const listOf = (results: unknown[], count = results.length) => ({ count, next: null, previous: null, results });
/** The story list as the platform answers it: only the statuses asked for. */
const storiesOf =
  (all: ReturnType<typeof story>[]) =>
  ({ url }: { url: URL }) => {
    const wanted = url.searchParams.getAll('status');
    return listOf(wanted.length ? all.filter((s) => wanted.includes(String(s.status))) : all);
  };
const DESK = { id: 'd1', site: 1, name: 'Metro', slug: 'metro', section: 3, section_title: 'News', editors: [], copy_editors: [], is_editor: true };
const PEOPLE = [{ id: 2, username: 'rae', name: 'Rae Porter' }];

describe('the budget board', () => {
  it('shows each story in its status column and moves one through its menu', async () => {
    const platform = fakePlatform({
      [`GET ${STORIES}`]: storiesOf([story(), story({ id: 's2', headline: 'Fire on Main', status: 'pitch', moves: ['assigned'] })]),
      [`POST ${STORIES}s1/move/`]: () => detail({ status: 'editing' }),
    });
    renderUi(<Newsroom siteId={1} />, { api: platform.api });
    const drafting = await screen.findByLabelText('Drafting column');
    expect(await within(drafting).findByText('Bridge closes')).toBeInTheDocument();
    expect(await within(screen.getByLabelText('Pitch column')).findByText('Fire on Main')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Move “Bridge closes”' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'To editing' }));
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'POST')?.body).toEqual({ status: 'editing' }));
    expect(platform.calls.find((c) => c.method === 'GET' && c.path === STORIES)?.query.get('site')).toBe('1');
  });

  it('asks why before the breaking-news fast path, and shows what the platform refuses', async () => {
    const editing = story({ status: 'editing', moves: ['copy', 'drafting', 'published'] });
    const platform = fakePlatform({
      [`GET ${STORIES}`]: () => listOf([editing]),
      [`POST ${STORIES}s1/move/`]: () =>
        new Reply(409, { error: { code: 'story.embargoed', message: 'the story is embargoed until tomorrow', status: 409, details: [] } }),
    });
    renderUi(<Newsroom siteId={1} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Move “Bridge closes”' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Breaking: publish now' }));
    const send = screen.getAllByRole('button', { name: 'Breaking: publish now' }).at(-1);
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Reason'), 'The bridge is closed now');
    await userEvent.click(screen.getAllByRole('button', { name: 'Breaking: publish now' }).at(-1) as HTMLElement);
    expect(await screen.findByText('the story is embargoed until tomorrow')).toBeInTheDocument();
    expect(platform.calls.find((c) => c.method === 'POST')?.body).toEqual({ status: 'published', reason: 'The bridge is closed now' });
  });

  it('asks before anything goes live, and sends nothing until the person agrees', async () => {
    const atCopy = story({ status: 'copy', moves: ['scheduled', 'published', 'drafting'] });
    const platform = fakePlatform({
      [`GET ${STORIES}`]: storiesOf([atCopy]),
      [`POST ${STORIES}s1/move/`]: () => detail({ status: 'published' }),
    });
    renderUi(<Newsroom siteId={1} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Move “Bridge closes”' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Publish now' }));
    expect(await screen.findByText(/It goes live now: readers, feeds and newsletters see it at once/)).toBeInTheDocument();
    expect(platform.calls.some((c) => c.method === 'POST')).toBe(false);
    await userEvent.click(screen.getAllByRole('button', { name: 'Publish now' }).at(-1) as HTMLElement);
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'POST')?.body).toEqual({ status: 'published' }));
  });

  it('gives each column its true count and more of it on request, the published newest first', async () => {
    const pitches = [story({ id: 'p1', headline: 'One of many', status: 'pitch', moves: ['assigned'] })];
    const platform = fakePlatform({
      [`GET ${STORIES}`]: ({ url }) => (url.searchParams.get('status') === 'pitch' ? listOf(pitches, 120) : listOf([])),
    });
    renderUi(<Newsroom siteId={1} />, { api: platform.api });
    const column = await screen.findByLabelText('Pitch column');
    expect(await within(column).findByText('119 more not shown')).toBeInTheDocument();
    expect(within(column).getByText('120')).toBeInTheDocument();
    await userEvent.click(within(column).getByRole('button', { name: 'Show more' }));
    const asked = (status: string) => platform.calls.filter((c) => c.path === STORIES && c.query.get('status') === status);
    await waitFor(() => expect(asked('pitch').at(-1)?.query.get('page_size')).toBe('100'));
    expect(asked('pitch')[0]?.query.get('page_size')).toBe('50');
    expect(asked('published')[0]?.query.get('ordering')).toBe('-updated_at');
  });

  it('maps a drop to a move, and a drop in the same column to none', () => {
    const stories = [story()] as Parameters<typeof dropTarget>[1];
    expect(dropTarget({ story: 's1', column: 'editing' }, stories)?.to).toBe('editing');
    expect(dropTarget({ story: 's1', column: 'drafting' }, stories)).toBeNull();
    expect(dropTarget({ story: 's1', column: null }, stories)).toBeNull();
  });
});

describe('the calendar and assignments', () => {
  it('lays a month out by slot date, whole weeks, Monday first', async () => {
    const grid = monthGrid(new Date(2026, 10, 1));
    expect(grid[0]?.getDay()).toBe(1);
    expect(grid.length % 7).toBe(0);
    const platform = fakePlatform({ [`GET ${STORIES}`]: () => listOf([story({ slot_date: '2026-11-02' })]) });
    renderUi(<Calendar query={{ site: 1 }} onOpen={() => undefined} today={new Date(2026, 10, 15)} />, { api: platform.api });
    expect(await within(screen.getByLabelText('2026-11-02')).findByText('Bridge closes')).toBeInTheDocument();
    const query = platform.calls[0]?.query;
    expect([query?.get('slot_after'), query?.get('slot_before')]).toEqual(['2026-10-26', '2026-12-06']);
  });

  it('lists what is assigned to me, or to my desks', async () => {
    const platform = fakePlatform({ [`GET ${STORIES}`]: () => listOf([story({ deadline: '2020-01-01T00:00:00Z' })]) });
    renderUi(<Newsroom siteId={1} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Assignments' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
    const mine = platform.calls.filter((c) => c.path === STORIES).at(-1)?.query;
    expect([mine?.get('assignee'), mine?.getAll('status')]).toEqual(['me', ['pitch', 'assigned', 'drafting', 'editing', 'copy']]);
    await userEvent.click(screen.getByText('My desks'));
    await waitFor(() => expect(platform.calls.filter((c) => c.path === STORIES).at(-1)?.query.get('my_desks')).toBe('true'));
  });
});

describe('a story’s panel', () => {
  it('saves the plan, asks for headlines and applies the AI’s pitch', async () => {
    const pitchRun = { kind: 'pitch', run: { id: 9, status: 'succeeded', links: { self: '', stream: '' } }, result: { headline: 'Bridge shut for six weeks', angle: 'Commuters lose their route.' }, text: '', error: '' };
    const platform = fakePlatform({
      [`GET ${STORIES}s1/`]: () => detail({ page: { id: 5, title: 'Bridge closes', live: false, url_path: '/x/', first_published_at: null }, ai_runs: [pitchRun] }),
      [`PATCH ${STORIES}s1/`]: () => story(),
      [`POST ${STORIES}s1/ai/`]: () => new Reply(202, { run: { id: 10, status: 'queued', links: { self: '', stream: '' } } }),
      'GET /api/v2/newsroom/desks/d1/people/': () => PEOPLE,
      'GET /api/v2/newsroom/authors/': () => listOf([{ id: 'a1', name: 'Ada Reporter', slug: 'ada' }]),
    });
    const { go } = renderUi(<StoryPanel storyId="s1" />, { api: platform.api });
    const headline = await screen.findByLabelText('Headline');
    await userEvent.clear(headline);
    await userEvent.type(headline, 'Bridge closes Monday');
    await userEvent.click(screen.getByRole('button', { name: 'Save the plan' }));
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ headline: 'Bridge closes Monday' }));
    await userEvent.click(screen.getByRole('button', { name: 'Suggest headlines and a summary' }));
    await waitFor(() => expect(platform.calls.find((c) => c.path.endsWith('/ai/'))?.body).toEqual({ kind: 'headlines' }));
    await userEvent.click(screen.getByRole('button', { name: 'Use this pitch' }));
    await waitFor(() =>
      expect(platform.calls.filter((c) => c.method === 'PATCH').at(-1)?.body).toEqual({ headline: 'Bridge shut for six weeks', summary: 'Commuters lose their route.' }),
    );
    await userEvent.click(screen.getByRole('button', { name: /Open “Bridge closes” in the editor/ }));
    expect(go).toHaveBeenCalledWith({ to: 'page', id: 5 });
  });

  it('leaves the desk’s decisions to the desk’s editors', async () => {
    const platform = fakePlatform({
      [`GET ${STORIES}s1/`]: () => detail({ is_editor: false }),
      'GET /api/v2/newsroom/desks/d1/people/': () => PEOPLE,
      'GET /api/v2/newsroom/authors/': () => listOf([]),
    });
    renderUi(<StoryPanel storyId="s1" notice="The story is pitched, but the AI was not asked for its pitch: busy" />, { api: platform.api });
    expect(await screen.findByText(/the AI was not asked for its pitch/)).toBeInTheDocument();
    for (const field of ['Priority', 'Deadline', 'Runs on', 'Embargo']) expect(screen.getByLabelText(field, { selector: 'input' })).toBeDisabled();
    expect(screen.getByLabelText('Headline')).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Save the plan' })).toBeDisabled(); // nothing changed yet
  });

  it('asks the AI for a draft from the pitch and makes it the story’s page', async () => {
    const draftRun = { kind: 'draft', run: { id: 13, status: 'succeeded', links: { self: '', stream: '' } }, result: null, text: '# Draft', error: '' };
    const platform = fakePlatform({
      [`GET ${STORIES}s1/`]: () => detail({ status: 'assigned', moves: ['drafting'], ai_runs: [draftRun] }),
      [`POST ${STORIES}s1/ai/`]: () => new Reply(202, { run: { id: 14, status: 'queued', links: { self: '', stream: '' } } }),
      [`POST ${STORIES}s1/apply-draft/`]: () => new Reply(201, { story: detail({ status: 'drafting' }), page_id: 7, suggestions: [1, 2] }),
      'GET /api/v2/newsroom/desks/d1/people/': () => PEOPLE,
      'GET /api/v2/newsroom/authors/': () => listOf([]),
    });
    renderUi(<StoryPanel storyId="s1" />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Draft it from the pitch' }));
    await waitFor(() => expect(platform.calls.find((c) => c.path.endsWith('/ai/'))?.body).toEqual({ kind: 'draft' }));
    await userEvent.click(screen.getByRole('button', { name: "Make the AI's draft the story's page" }));
    await waitFor(() => expect(platform.calls.some((c) => c.method === 'POST' && c.path.endsWith('/apply-draft/'))).toBe(true));
  });

  it('distributes a live story to the channels of its own site', async () => {
    const page = { id: 5, title: 'Bridge closes', live: true, has_unpublished_changes: false, url_path: '/x/', first_published_at: null };
    const platform = fakePlatform({
      [`GET ${STORIES}s1/`]: () => detail({ status: 'published', moves: [], page }),
      'GET /api/v2/newsroom/desks/': () => listOf([{ ...DESK, site: 4 }]),
      'GET /api/v2/newsroom/desks/d1/people/': () => PEOPLE,
      'GET /api/v2/newsroom/authors/': () => listOf([]),
      'GET /api/v2/distribution/channels/': () => listOf([]),
    });
    renderUi(<StoryPanel storyId="s1" />, { api: platform.api });
    await waitFor(() => expect(platform.calls.some((c) => c.path === '/api/v2/newsroom/desks/')).toBe(true));
    await userEvent.click(await screen.findByRole('button', { name: 'Distribute' }));
    await waitFor(() => expect(platform.calls.find((c) => c.path === '/api/v2/distribution/channels/')?.query.get('site')).toBe('4'));
  });

  it('drafts a correction note with the AI and posts the one the editor keeps, which publishes nothing else', async () => {
    const noteRun = { kind: 'correction', run: { id: 11, status: 'succeeded', links: { self: '', stream: '' } }, result: { text: 'An earlier version misstated the day.' }, text: '', error: '' };
    const page = { id: 5, title: 'Bridge closes', live: true, has_unpublished_changes: true, url_path: '/x/', first_published_at: null };
    const platform = fakePlatform({
      [`GET ${STORIES}s1/`]: () => detail({ status: 'published', moves: ['updated', 'corrected'], ai_runs: [noteRun], page }),
      [`POST ${STORIES}s1/ai/`]: () => new Reply(202, { run: { id: 12, status: 'queued', links: { self: '', stream: '' } } }),
      [`POST ${STORIES}s1/move/`]: () => detail({ status: 'corrected' }),
      'GET /api/v2/newsroom/desks/d1/people/': () => PEOPLE,
      'GET /api/v2/newsroom/authors/': () => listOf([]),
    });
    const { go } = renderUi(<StoryPanel storyId="s1" />, { api: platform.api });
    expect(await screen.findByText('Changes saved since the page went live')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Review them in the editor' }));
    expect(go).toHaveBeenCalledWith({ to: 'page', id: 5 });
    await userEvent.type(await screen.findByLabelText(/What changed\?/), 'the vote is Tuesday');
    await userEvent.click(screen.getByRole('button', { name: 'Draft the note with AI' }));
    await waitFor(() => expect(platform.calls.find((c) => c.path.endsWith('/ai/'))?.body).toEqual({ kind: 'correction', text: 'the vote is Tuesday' }));
    await userEvent.click(screen.getByRole('button', { name: "Use the AI's note" }));
    await userEvent.click(screen.getByRole('button', { name: 'Add a correction' }));
    await waitFor(() =>
      expect(platform.calls.find((c) => c.path.endsWith('/move/'))?.body).toEqual({ status: 'corrected', text: 'An earlier version misstated the day.' }),
    );
  });
});

describe('fronts and newsletters', () => {
  it('edits a front’s slots and saves them as a whole', async () => {
    const front = { id: 'f1', site: 1, desk: null, name: 'Home', slug: 'home', slots: [{ rule: 'pinned', story: 's1', desk: null }], created_at: '', updated_at: 'v1' };
    const platform = fakePlatform({
      'GET /api/v2/newsroom/fronts/': () => listOf([front]),
      'GET /api/v2/newsroom/fronts/f1/stories/': () => [{ position: 0, rule: 'pinned', story: { id: 's1', headline: 'Bridge closes', summary: '', status: 'published', desk_name: 'Metro', url_path: '/b/', published_at: null } }],
      [`GET ${STORIES}`]: () => listOf([story({ status: 'published' })]),
      'GET /api/v2/newsroom/desks/': () => listOf([DESK]),
      'PATCH /api/v2/newsroom/fronts/f1/': () => front,
    });
    renderUi(<Fronts siteId={1} />, { api: platform.api });
    expect(await within(await screen.findByLabelText('The front as readers see it')).findByText('Bridge closes')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add a slot' }));
    await userEvent.click(screen.getByRole('button', { name: 'Move slot 2 up' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save the front' }));
    await waitFor(() =>
      expect(platform.calls.find((c) => c.method === 'PATCH')?.body).toEqual({
        slots: [
          { rule: 'latest', desk: null },
          { rule: 'pinned', story: 's1', desk: null },
        ],
      }),
    );
  });

  it('composes an issue from stories, previews it and sends it', async () => {
    const newsletter = { id: 'n1', site: 1, name: 'Morning Brief', slug: 'morning', description: '', from_email: '', subscribers: { pending: 1, confirmed: 2, unsubscribed: 0 }, created_at: '' };
    const issue = { id: 'i1', newsletter: 'n1', subject: 'Monday', intro: '', stories: [], status: 'draft', recipients: 0, sent_at: null, error: '', created_at: '', updated_at: 'v1' };
    const platform = fakePlatform({
      'GET /api/v2/newsroom/newsletters/': () => listOf([newsletter]),
      'GET /api/v2/newsroom/issues/': () => listOf([issue]),
      [`GET ${STORIES}`]: ({ url }) =>
        listOf([story({ status: 'published' }), story({ id: 's2', headline: 'Older news', status: 'published' })].filter((s) => s.headline.includes(url.searchParams.get('q') ?? ''))),
      'POST /api/v2/newsroom/issues/': () => issue,
      'GET /api/v2/newsroom/issues/i1/preview/': () => ({ subject: 'Monday', text: 'Morning Brief — Monday\n1. Bridge closes', html: '<h1></h1>' }),
      'POST /api/v2/newsroom/issues/i1/send/': () => new Reply(202, { ...issue, status: 'sending' }),
    });
    renderUi(<Newsletters siteId={1} />, { api: platform.api });
    expect(await screen.findByText('2 confirmed')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Subject'), 'Monday');
    await userEvent.type(screen.getByLabelText('Stories, in order', { selector: 'input' }), 'Bridge');
    await waitFor(() => expect(platform.calls.filter((c) => c.path === STORIES).at(-1)?.query.get('q')).toBe('Bridge'));
    expect(platform.calls.find((c) => c.path === STORIES)?.query.get('ordering')).toBe('-page__first_published_at');
    await userEvent.click(await screen.findByRole('option', { name: 'Bridge closes' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save the issue' }));
    await waitFor(() =>
      expect(platform.calls.find((c) => c.path === '/api/v2/newsroom/issues/' && c.method === 'POST')?.body).toEqual({
        newsletter: 'n1',
        subject: 'Monday',
        intro: '',
        story_ids: ['s1'],
      }),
    );
    expect(await screen.findByText(/1\. Bridge closes/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Send to 2 confirmed subscribers' }));
    await waitFor(() => expect(platform.calls.some((c) => c.path === '/api/v2/newsroom/issues/i1/send/')).toBe(true));
  });
});

describe('a send that stopped', () => {
  it('offers to resume an issue left sending', async () => {
    const newsletter = { id: 'n1', site: 1, name: 'Morning Brief', slug: 'morning', description: '', from_email: '', subscribers: { pending: 0, confirmed: 3, unsubscribed: 0 }, created_at: '' };
    const issue = { id: 'i1', newsletter: 'n1', subject: 'Monday', intro: '', stories: [], status: 'sending', recipients: 1, sent_at: null, error: '', created_at: '', updated_at: 'v1' };
    const platform = fakePlatform({
      'GET /api/v2/newsroom/newsletters/': () => listOf([newsletter]),
      'GET /api/v2/newsroom/issues/': () => listOf([issue]),
      [`GET ${STORIES}`]: () => listOf([]),
      'GET /api/v2/newsroom/issues/i1/preview/': () => ({ subject: 'Monday', text: 'Morning Brief — Monday', html: '' }),
      'POST /api/v2/newsroom/issues/i1/send/': () => new Reply(409, { error: { code: 'resource.conflict', message: 'this issue is being sent', status: 409, details: [] } }),
    });
    renderUi(<Newsletters siteId={1} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Monday' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Resume sending, if it has stopped' }));
    expect(await screen.findByText('this issue is being sent')).toBeInTheDocument();
  });
});

describe('authors', () => {
  it('adds an author and shows an author’s page of published stories', async () => {
    const ada = { id: 'a1', name: 'Ada Reporter', slug: 'ada-reporter', bio: 'Covers the city.', email: '', user: null, created_at: '' };
    const platform = fakePlatform({
      'GET /api/v2/newsroom/desks/': () => listOf([DESK]),
      [`GET ${STORIES}`]: () => listOf([]),
      'GET /api/v2/newsroom/authors/': () => listOf([ada]),
      'POST /api/v2/newsroom/authors/': () => new Reply(201, { ...ada, id: 'a2', name: 'Bo Writer', slug: 'bo-writer' }),
      'GET /api/v2/newsroom/authors/a1/': () => ({ ...ada, stories: [{ id: 's1', headline: 'Bridge closes', url_path: '/news/bridge/', published_at: null }] }),
      'GET /api/v2/newsroom/authors/a2/': () => ({ ...ada, id: 'a2', name: 'Bo Writer', stories: [] }),
    });
    renderUi(<Newsroom siteId={1} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Authors' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Ada Reporter' }));
    expect(await within(await screen.findByLabelText('Author page')).findByText('Bridge closes')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Name'), 'Bo Writer');
    await userEvent.click(screen.getByRole('button', { name: 'Add the author' }));
    await waitFor(() =>
      expect(platform.calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Bo Writer', bio: '', email: '' }),
    );
    expect(await within(screen.getByLabelText('Author page')).findByText('Bo Writer')).toBeInTheDocument();
  });
});

describe('pitching', () => {
  it('pitches from a wire item, asks the AI for its pitch and opens the story', async () => {
    const platform = fakePlatform({
      'GET /api/v2/newsroom/desks/': () => listOf([DESK]),
      [`GET ${STORIES}`]: () => listOf([]),
      [`POST ${STORIES}`]: () => story({ id: 's9', status: 'pitch' }),
      [`POST ${STORIES}s9/ai/`]: () => new Reply(202, { run: { id: 3, status: 'queued', links: { self: '', stream: '' } } }),
    });
    const { go } = renderUi(<Newsroom siteId={1} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Pitch a story' }));
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument(); // the dialog's close button has a name
    await userEvent.type(screen.getByLabelText('From a wire or feed item: its link'), 'https://wire.example/1');
    await userEvent.type(screen.getByLabelText('Its title'), 'BRIDGE SHUT');
    await userEvent.click(screen.getByRole('button', { name: 'Pitch it' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'story', id: 's9' }));
    const posted = platform.calls.filter((c) => c.method === 'POST');
    expect(posted.map((c) => c.path)).toEqual([STORIES, `${STORIES}s9/ai/`]);
    expect(posted[0]?.body).toEqual({ desk: 'd1', headline: '', summary: '', source: { url: 'https://wire.example/1', title: 'BRIDGE SHUT', text: '' } });
    expect(posted[1]?.body).toEqual({ kind: 'pitch' });
  });

  it('opens a story that was pitched even when the AI could not be asked, and says so', async () => {
    const platform = fakePlatform({
      [`POST ${STORIES}`]: () => story({ id: 's9', status: 'pitch' }),
      [`POST ${STORIES}s9/ai/`]: () => new Reply(403, { error: { code: 'auth.forbidden', message: 'not yours', status: 403, details: [] } }),
    });
    const onDone = vi.fn();
    renderUi(<PitchForm desks={[DESK] as never} onDone={onDone} />, { api: platform.api });
    await userEvent.type(screen.getByLabelText('From a wire or feed item: its link'), 'https://wire.example/1');
    await userEvent.click(screen.getByRole('button', { name: 'Pitch it' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('s9', expect.stringContaining('the AI was not asked for its pitch: not yours')));
    expect(platform.calls.filter((c) => c.method === 'POST' && c.path === STORIES)).toHaveLength(1);
  });
});
