const NOW = Date.parse("2026-08-19T12:00:00Z");

export function formatFreshness(isoDate: string): string {
  const diffMs = NOW - Date.parse(isoDate);
  const hours = Math.max(0, Math.round(diffMs / 3_600_000));
  if (hours < 1) return "actualizat acum";
  if (hours < 24) return `actualizat acum ${hours}h`;
  const days = Math.round(hours / 24);
  return `actualizat acum ${days}z`;
}

export function formatPrice(amount: number, currency: "EUR" | "RON"): string {
  const symbol = currency === "EUR" ? "€" : "RON";
  return `${amount.toLocaleString("ro-RO")} ${symbol}/lună`;
}
