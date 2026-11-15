const INK = [24, 24, 27] as const;

/** The light ground of the map the marks stand on. */
export const MAP_GROUND = '#f2f2f0';

const channels = (hex: string): [number, number, number] => [
  Number.parseInt(hex.slice(1, 3), 16),
  Number.parseInt(hex.slice(3, 5), 16),
  Number.parseInt(hex.slice(5, 7), 16),
];

const linear = (value: number) => {
  const unit = value / 255;
  return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
};

function luminance([red, green, blue]: readonly [number, number, number]): number {
  return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
}

/** The contrast ratio of two colours, 1 to 21 (WCAG). */
export function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(channels(a)), luminance(channels(b))].sort((x, y) => y - x);
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05);
}

/** The colour itself when it stands out from the ground by `min` to 1, else the same hue taken toward the ink until it does. */
export function legibleOn(color: string, ground = MAP_GROUND, min = 3): string {
  const base = channels(color);
  for (let step = 0; step <= 20; step += 1) {
    const share = step / 20;
    const mixed = base.map((value, index) =>
      Math.round(value + ((INK[index] ?? 0) - value) * share),
    ) as [number, number, number];
    const hex = `#${mixed.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
    if (contrast(hex, ground) >= min) return hex;
  }
  return `#${INK.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
}
