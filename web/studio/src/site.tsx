// The site the studio works in, picked in the header and handed to every
// workspace as a filter ("all sites" when none is picked). Remembered per
// browser as a convenience: if storage is unavailable nothing else changes.
import { createContext, use, useState, type ReactNode } from 'react';

const KEY = 'zer0-studio-site';

interface SiteChoice {
  siteId: number | undefined;
  setSiteId: (id: number | undefined) => void;
}

const SiteContext = createContext<SiteChoice>({ siteId: undefined, setSiteId: () => undefined });

function remembered(): number | undefined {
  try {
    return Number(window.localStorage.getItem(KEY)) || undefined;
  } catch {
    return undefined; // storage blocked: start with every site
  }
}

function remember(id: number | undefined) {
  try {
    if (id) window.localStorage.setItem(KEY, String(id));
    else window.localStorage.removeItem(KEY);
  } catch {
    // storage blocked: the choice lasts until the page is closed
  }
}

export function SiteProvider({ children }: { children: ReactNode }) {
  const [siteId, setSite] = useState(remembered);
  const setSiteId = (id: number | undefined) => {
    remember(id);
    setSite(id);
  };
  return <SiteContext value={{ siteId, setSiteId }}>{children}</SiteContext>;
}

export const useSite = () => use(SiteContext);
