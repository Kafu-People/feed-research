/** Domain types. Mirrors the backend's OpenAPI schema. */

export type EventKind =
  | "shown"
  | "expanded"
  | "dwell"
  | "tapped_through"
  | "saved"
  | "shared"
  | "scrolled_past"
  | "skipped"
  | "hidden"
  | "best_of_day";
// NOTE: no "click". Invariant #8 -- rank on tap-through and dwell, never raw
// clicks, or the ranking learns that outrage works.

export interface TopicLabel {
  topic_id: number;
  label: string;
}

export interface Card {
  storyId: number;
  headline: string;
  /** null when unjudged/refused/failed verification -> degrade, don't hide. */
  summary: string | null;
  sourceName: string;
  sourceCount: number;
  publishedAt: string;
  imageUrl: string | null;
  url: string;
  topicLabels: TopicLabel[];
  matchedBy: string[];
}

export interface Dashboard {
  cards: Card[];
  generatedAt: string;
  /** "That's today." The bottom exists -- finishing is a feature. */
  done: boolean;
  more: Card[];
}

export interface EventDraft {
  kind: EventKind;
  storyId?: number | null;
  position?: number | null;
  reason?: string | null;
  dwellMs?: number | null;
}

export interface TopicDraft {
  title: string;
  must: string[];
  should: string[];
  entities: string[];
  exclude: string[];
  ambiguity: string | null;
  options: string[];
  count7d: number;
  perDay: number;
  preview: Card[];
}
