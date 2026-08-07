/** Display formatting. Shared so the two surfaces never drift cosmetically. */

export function relativeTime(iso: string, now: Date = new Date()): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function sourceLine(name: string, count: number, publishedAt: string): string {
  const when = relativeTime(publishedAt);
  return count > 1 ? `${name} · ${when} · ${count} sources` : `${name} · ${when}`;
}

/** "about 6 a day" -- shown BEFORE the topic is wrong, not after a bad week. */
export function rateLabel(perDay: number): string {
  if (perDay === 0) return "nothing yet";
  if (perDay < 1) return "about 1 a week";
  return `about ${Math.round(perDay)} a day`;
}
