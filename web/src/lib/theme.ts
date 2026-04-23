export const OKABE = [
  "#E69F00", "#56B4E9", "#009E73", "#F0E442",
  "#0072B2", "#D55E00", "#CC79A7",
];

export function colourForLink(index: number): string {
  return OKABE[index % OKABE.length]!;
}

export function opacityFor(bytes: number, maxBytes: number): number {
  if (maxBytes <= 0) return 0.6;
  const r = bytes / maxBytes;
  return Math.max(0.2, Math.min(1.0, 0.2 + r * 0.8));
}
