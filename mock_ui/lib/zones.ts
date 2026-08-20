import proximityJson from "./data/proximity.json";

const PROXIMITY = proximityJson as Record<string, string[]>;

export function expandWithProximity(zones: string[]): string[] {
  const selected = new Set(zones);
  const extra: string[] = [];
  for (const zone of zones) {
    for (const neighbor of PROXIMITY[zone] ?? []) {
      if (!selected.has(neighbor) && !extra.includes(neighbor)) extra.push(neighbor);
    }
  }
  return extra;
}
