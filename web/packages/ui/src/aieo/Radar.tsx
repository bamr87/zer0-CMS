// The five dimensions as a radar, as AIEO's audit page drew them: one axis per
// dimension from the centre (0) to the rim (100), rings at 25, 50, 75 and 100,
// and the scored shape over them. Inline SVG coloured by the theme's variables,
// so it needs no chart library and follows light and dark; the bars beside it
// carry the exact numbers, and its label reads them out for a screen reader.
import { DIMENSION_LABELS, DIMENSIONS, type Dimension } from './score';

const SHORT: Record<Dimension, string> = { aieo: 'AIEO', seo: 'SEO', readability: 'Readability', humanity: 'Humanity', cro: 'CRO' };
const RINGS = [25, 50, 75, 100];
const PAD = 48; // room beside the rim for the longest label

export function Radar({ dimensions, size = 220 }: { dimensions: Record<Dimension, number | null>; size?: number }) {
  const centre = size / 2;
  const radius = size / 2 - 30;
  const at = (i: number, value: number): [number, number] => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / DIMENSIONS.length;
    const length = (radius * value) / 100;
    return [centre + Math.cos(angle) * length, centre + Math.sin(angle) * length];
  };
  const points = (values: number[]) => values.map((v, i) => at(i, v).map((n) => n.toFixed(1)).join(',')).join(' ');
  const scored = DIMENSIONS.map((d) => Math.max(0, Math.min(100, dimensions[d] ?? 0)));
  const said = DIMENSIONS.map((d) => `${DIMENSION_LABELS[d]} ${dimensions[d] ?? 'not scored'}`).join(', ');
  const line = 'var(--mantine-color-default-border)';
  return (
    <svg
      width={size + 2 * PAD}
      height={size}
      viewBox={`${-PAD} 0 ${size + 2 * PAD} ${size}`}
      role="img"
      aria-label={`The five dimensions: ${said}`}
    >
      {RINGS.map((ring) => (
        <polygon key={ring} points={points(DIMENSIONS.map(() => ring))} fill="none" stroke={line} />
      ))}
      {DIMENSIONS.map((d, i) => {
        const [x, y] = at(i, 100);
        return <line key={d} x1={centre} y1={centre} x2={x} y2={y} stroke={line} />;
      })}
      <polygon
        points={points(scored)}
        fill="var(--mantine-primary-color-filled)"
        fillOpacity={0.25}
        stroke="var(--mantine-primary-color-filled)"
        strokeWidth={2}
      />
      {DIMENSIONS.map((d, i) => {
        const [x, y] = at(i, 116);
        const anchor = Math.abs(x - centre) < 1 ? 'middle' : x < centre ? 'end' : 'start';
        return (
          <text key={d} x={x} y={y} textAnchor={anchor} dominantBaseline="middle" fontSize={11} fill="var(--mantine-color-dimmed)">
            {SHORT[d]}
          </text>
        );
      })}
    </svg>
  );
}
