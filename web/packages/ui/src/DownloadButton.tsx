// A file a workspace offers to download — a book's manuscript, a channel's
// ledger file, an exported document. The studio saves the text the page
// already has, as a Blob (no data: link, which browsers cap in length). A host
// that saves files itself (the extension, whose webviews cannot) is handed the
// intent instead — the path that answers the file, the field that holds its
// text and the name to offer — and fetches it again through its own gates.
import { Button, type ButtonProps } from '@mantine/core';
import type { ReactNode } from 'react';

import { useSave, type SaveIntent } from './context';

/** How long an object URL outlives its click: long enough for the browser to start the download. */
const KEEP_URL_MS = 60_000;

export function DownloadButton({
  path,
  field,
  filename,
  text,
  type,
  children,
  ...button
}: SaveIntent & { text: string; type: string; children: ReactNode; variant?: ButtonProps['variant']; size?: ButtonProps['size'] }) {
  const save = useSave();
  const download = () => {
    if (save) {
      save({ path, filename, ...(field === undefined ? {} : { field }) });
      return;
    }
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), KEEP_URL_MS);
  };
  return (
    <Button {...button} onClick={download}>
      {children}
    </Button>
  );
}
