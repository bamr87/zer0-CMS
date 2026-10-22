// The studio's frame: the navigation over every area, the site switcher, the
// light/dark switch and sign-out, around whichever area is open.
import { ActionIcon, AppShell, Badge, Burger, Group, Menu, NavLink, Select, Text, useComputedColorScheme, useMantineColorScheme } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconMoon, IconSun } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { call, useApi } from '@zer0/ui';
import { Link, Outlet, useLocation } from 'react-router';

import { AREAS } from './areas';
import { useSignOut, type Person } from './auth';
import { useSite } from './site';

export function Shell({ person }: { person: Person }) {
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname } = useLocation();
  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 230, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Navigation" />
            <Text fw={700}>zer0 studio</Text>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <SiteSwitcher />
            <SchemeToggle />
            <PersonMenu person={person} />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs" aria-label="Areas">
        {AREAS.map((area) => (
          <NavLink
            key={area.path}
            component={Link}
            to={area.path}
            onClick={close}
            label={area.label}
            leftSection={<area.icon size={18} stroke={1.6} />}
            rightSection={area.milestone ? <Badge size="xs" variant="light" color="gray">{area.milestone}</Badge> : null}
            active={area.path === '/' ? pathname === '/' : pathname.startsWith(area.path)}
          />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}

function SiteSwitcher() {
  const api = useApi();
  const { siteId, setSiteId } = useSite();
  const sites = useQuery({ queryKey: ['sites'], queryFn: () => call(api.GET('/api/v2/sites/')) });
  return (
    <Select
      aria-label="Site"
      size="xs"
      w={190}
      data={[{ value: '', label: 'All sites' }, ...(sites.data ?? []).map((s) => ({ value: String(s.id), label: s.name }))]}
      value={siteId ? String(siteId) : ''}
      allowDeselect={false}
      onChange={(value) => setSiteId(Number(value) || undefined)}
    />
  );
}

function SchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const dark = useComputedColorScheme('light') === 'dark';
  return (
    <ActionIcon variant="default" size="lg" aria-label={dark ? 'Use the light theme' : 'Use the dark theme'} onClick={() => setColorScheme(dark ? 'light' : 'dark')}>
      {dark ? <IconSun size={18} /> : <IconMoon size={18} />}
    </ActionIcon>
  );
}

function PersonMenu({ person }: { person: Person }) {
  const signOut = useSignOut();
  return (
    <Menu position="bottom-end">
      <Menu.Target>
        <ActionIcon variant="default" size="lg" aria-label={`Signed in as ${person.username}`} w="auto" px="xs">
          <Text size="sm">{person.name || person.username}</Text>
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{person.email || person.username}</Menu.Label>
        <Menu.Item onClick={() => signOut.mutate()}>Sign out</Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
