/**
 * The feedback queue. Shared by web and mobile, byte-for-byte.
 *
 * Several invariants are only true if BOTH surfaces behave identically, so the
 * logic lives here and each app supplies only a Storage adapter and the flush
 * triggers.
 */

import type { Card, EventDraft, EventKind } from "./types";

/**
 * A card counts as "shown" once it has been >=50% visible for >=1s.
 * Web uses IntersectionObserver, mobile uses FlatList viewability -- both feed
 * this SAME predicate. Two definitions of "shown" would mean the personal layer
 * learns from a blend of two different signals.
 */
export const SHOWN_THRESHOLD = { ratio: 0.5, ms: 1000 } as const;

/** Kinds that count as the user having acted on a card. */
const ACTED: ReadonlySet<EventKind> = new Set([
  "expanded",
  "dwell",
  "tapped_through",
  "saved",
  "shared",
  "hidden",
  "best_of_day",
]);

export interface ShownCard {
  storyId: number;
  position: number;
}

export interface StoredEvent extends EventDraft {
  id: string;
}

export interface Storage {
  enqueue(e: EventDraft): Promise<void>;
  takePending(limit: number): Promise<StoredEvent[]>;
  clear(ids: string[]): Promise<void>;
  actedStoryIds(): Promise<Set<number>>;
}

export interface Transport {
  postEvents(batch: EventDraft[]): Promise<void>;
}

/**
 * With a finite daily set the user has seen everything, so every card shown and
 * not acted on is a REAL negative. That is what lets the personal layer learn
 * from hundreds of users instead of hundreds of thousands.
 *
 * It only holds because the API never pads a short day.
 */
export function cleanNegatives(
  shown: readonly ShownCard[],
  acted: ReadonlySet<number>,
): EventDraft[] {
  return shown
    .filter((c) => !acted.has(c.storyId))
    .map((c) => ({ kind: "skipped" as const, storyId: c.storyId, position: c.position }));
}

export function isActed(kind: EventKind): boolean {
  return ACTED.has(kind);
}

export interface FeedbackQueue {
  track(kind: EventKind, card: Pick<Card, "storyId">, position: number): Promise<void>;
  enqueue(e: EventDraft): Promise<void>;
  flush(): Promise<number>;
  dayComplete(shown: readonly ShownCard[]): Promise<number>;
}

export function createFeedbackQueue(opts: {
  storage: Storage;
  transport: Transport;
  batchSize?: number;
}): FeedbackQueue {
  const { storage, transport, batchSize = 200 } = opts;

  async function enqueue(e: EventDraft): Promise<void> {
    await storage.enqueue(e);
  }

  return {
    enqueue,

    async track(kind, card, position) {
      // Never block a UI transition on a network write.
      await enqueue({ kind, storyId: card.storyId, position });
    },

    async flush() {
      const batch = await storage.takePending(batchSize);
      if (batch.length === 0) return 0;
      try {
        await transport.postEvents(batch.map(({ id: _id, ...e }) => e));
        await storage.clear(batch.map((e) => e.id));
        return batch.length;
      } catch {
        // Stays queued; retried on the next flush. Events must survive a
        // dropped connection, a closed tab, or a backgrounded app.
        return 0;
      }
    },

    async dayComplete(shown) {
      const acted = await storage.actedStoryIds();
      const negatives = cleanNegatives(shown, acted);
      for (const e of negatives) await enqueue(e);
      await this.flush();
      return negatives.length;
    },
  };
}
