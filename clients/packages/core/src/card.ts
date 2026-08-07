import type { Card } from "./types";

export interface CardRenderModel {
  headline: string;
  showSummary: boolean;
  summary: string;
  labels: string[];
  matchedBy: string[];
  hasImage: boolean;
}

/**
 * WHAT to show. Each app decides only HOW to draw it -- which is what keeps two
 * view layers from becoming two products.
 */
export function renderModel(card: Card): CardRenderModel {
  return {
    headline: card.headline,
    // An unjudged story degrades to headline + source. It is never hidden: the
    // user still sees the event, attributed to the publisher.
    showSummary: typeof card.summary === "string" && card.summary.length > 0,
    summary: card.summary ?? "",
    labels: card.topicLabels.map((t) => t.label),
    matchedBy: card.matchedBy,
    hasImage: Boolean(card.imageUrl),
  };
}

/** The client must never invent cards. There is no padding path here either. */
export function visibleCards(d: { cards: Card[] }): Card[] {
  return d.cards;
}
