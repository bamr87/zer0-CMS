// Writing one chapter: the page editor (its blocks, its fields — number, act,
// status, point of view, characters … — its suggestions and revisions) with
// the book assistant beside it and the chapter's own validation findings
// under that. Whatever the assistant writes arrives as suggestions in the
// editor's Suggestions tab; nothing reaches the chapter until it is accepted.
import { Alert, Anchor, Grid, Loader, Stack, Text, Title } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { PageEditor } from '../PageEditor';
import { BookAssist } from './BookAssist';
import { Checks } from './BookView';

export function ChapterWriter({ bookId, chapterId }: { bookId: number; chapterId: number }) {
  const api = useApi();
  const go = useGo();
  const book = useQuery({
    queryKey: ['book', bookId],
    queryFn: () => call(api.GET('/api/v2/books/{id}/', { params: { path: { id: bookId } } })),
  });
  if (book.isPending) return <Loader />;
  if (book.isError) return <Alert color="red">{errorText(book.error)}</Alert>;
  const chapter = book.data.chapter_list.find((c) => c.id === chapterId);
  return (
    <Stack>
      <Anchor component="button" type="button" size="sm" onClick={() => go({ to: 'book', id: bookId })}>
        ← {book.data.title}
      </Anchor>
      {chapter === undefined ? <Alert color="yellow">This chapter is not in {book.data.title}.</Alert> : null}
      <Grid>
        <Grid.Col span={{ base: 12, lg: 8 }}>
          <PageEditor key={chapterId} pageId={chapterId} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <Stack>
            <BookAssist key={chapterId} bookId={bookId} chapterId={chapterId} />
            <Title order={4}>Checks</Title>
            {chapter ? (
              <>
                <Text size="xs" c="dimmed">
                  {chapter.path} · {chapter.word_count.toLocaleString()} words of prose
                </Text>
                <Checks bookId={bookId} path={chapter.path} />
              </>
            ) : null}
          </Stack>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
