// The Mantine theme over the zer0 tokens. Mantine's own variables point at the
// --zer0-* custom properties (tokens.css), so the theme holds no colour value:
// a host that redefines a token restyles every component, and light and dark
// come from the tokens' light-dark() pairs rather than from two palettes here.
import { createTheme, type CSSVariablesResolver } from '@mantine/core';

export const theme = createTheme({
  primaryColor: 'blue',
  fontFamily: 'var(--zer0-sans)',
  fontFamilyMonospace: 'var(--zer0-mono)',
  headings: { fontFamily: 'var(--zer0-sans)', fontWeight: '650' },
  radius: { sm: 'var(--zer0-radius-sm)', md: 'var(--zer0-radius)' },
  defaultRadius: 'md',
  cursorType: 'pointer',
  components: {
    Paper: { defaultProps: { withBorder: true } },
    Badge: { defaultProps: { radius: 'sm', tt: 'none', fw: 500 } },
  },
});

/** Mantine's colour roles, each read from a token; the same in both schemes. */
export const roles: Record<string, string> = {
  '--mantine-color-body': 'var(--zer0-bg)',
  '--mantine-color-text': 'var(--zer0-text)',
  '--mantine-color-dimmed': 'var(--zer0-text-dim)',
  '--mantine-color-placeholder': 'var(--zer0-text-faint)',
  '--mantine-color-default': 'var(--zer0-bg-raised)',
  '--mantine-color-default-hover': 'var(--zer0-bg-inset)',
  '--mantine-color-default-color': 'var(--zer0-text)',
  '--mantine-color-default-border': 'var(--zer0-border)',
  '--mantine-color-anchor': 'var(--zer0-accent)',
  '--mantine-color-error': 'var(--zer0-err)',
  '--mantine-primary-color-filled': 'var(--zer0-accent-strong)',
};

export const resolver: CSSVariablesResolver = () => ({ variables: {}, light: roles, dark: roles });
