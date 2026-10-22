// What distribution's parts share: the queries every view reads under one
// cache key (['distribution', …]) so an approval, a publish or a connection
// refreshes the queue, the channel and the ledger together; a post and a
// channel are followed while the worker has them (publishing, connecting,
// checking); and the labels and colours of the statuses and kinds.
import { useQuery } from '@tanstack/react-query';
import type { DistributionKind, DistributionPostStatus } from '@zer0/api';

import { call } from '../call';
import { useApi } from '../context';

export const KINDS: { value: DistributionKind; label: string }[] = [
  { value: 'linkedin', label: 'LinkedIn' },
  { value: 'wordpress', label: 'WordPress' },
  { value: 'github_pr', label: 'GitHub pull request' },
  { value: 'email', label: 'Email newsletter' },
];

const DRAFT = { value: 'draft' as DistributionPostStatus, label: 'Draft', color: 'gray' };

export const STATUSES: { value: DistributionPostStatus; label: string; color: string }[] = [
  DRAFT,
  { value: 'approved', label: 'Approved', color: 'blue' },
  { value: 'publishing', label: 'Publishing', color: 'cyan' },
  { value: 'published', label: 'Published', color: 'green' },
  { value: 'failed', label: 'Failed', color: 'red' },
  { value: 'rejected', label: 'Rejected', color: 'orange' },
];

export const statusOf = (value: string) => STATUSES.find((s) => s.value === value) ?? DRAFT;
export const kindLabel = (value: string) => KINDS.find((k) => k.value === value)?.label ?? value;
export const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : '—');

/** What each kind keeps in its settings, as the platform's channel takes them (distribution/models.py). */
export const SETTINGS: Record<DistributionKind, { name: string; label: string; description?: string }[]> = {
  linkedin: [
    { name: 'author', label: 'Author', description: 'urn:li:organization:… for a page, urn:li:person:… for a profile' },
    { name: 'ledger_file', label: 'Site ledger file', description: 'Optional: the site’s own ledger (e.g. .github/linkedin-log.json), read before and written after a publish' },
  ],
  wordpress: [
    { name: 'url', label: 'Site address', description: 'https://blog.example.com' },
    { name: 'username', label: 'Username' },
    { name: 'status', label: 'Post status', description: 'draft (the default), pending, private or publish' },
  ],
  github_pr: [
    { name: 'repo', label: 'Repository', description: 'owner/name' },
    { name: 'branch', label: 'Base branch', description: 'main when empty' },
    { name: 'directory', label: 'Directory', description: 'Where the site lives in the repository (empty: its root)' },
  ],
  email: [],
};

const SECRET_LABELS: Record<string, string> = {
  access_token: 'Access token',
  refresh_token: 'Refresh token',
  application_password: 'Application password',
  token: 'Token',
};
export const secretLabel = (name: string) => SECRET_LABELS[name] ?? name;

export function useChannels(siteId?: number) {
  const api = useApi();
  return useQuery({
    queryKey: ['distribution', 'channels', siteId ?? null],
    queryFn: () => call(api.GET('/api/v2/distribution/channels/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
}

export function useChannel(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: ['distribution', 'channel', id],
    queryFn: () => call(api.GET('/api/v2/distribution/channels/{public_id}/', { params: { path: { public_id: id } } })),
    // The worker is exchanging LinkedIn's code: follow the channel until it is connected or says why not.
    refetchInterval: (query) => (query.state.data?.connecting ? 1500 : false),
  });
}

export function usePost(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: ['distribution', 'post', id],
    queryFn: () => call(api.GET('/api/v2/distribution/posts/{public_id}/', { params: { path: { public_id: id } } })),
    refetchInterval: (query) => (query.state.data?.status === 'publishing' ? 1500 : false),
  });
}
